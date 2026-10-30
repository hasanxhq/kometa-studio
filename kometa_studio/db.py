"""SQLite access and schema migrations.

Migrations are numbered SQL files in ``kometa_studio/migrations/``
(``0001_initial.sql``, ``0002_...``). The schema version is stored in SQLite's
own ``PRAGMA user_version``, so there is no bookkeeping table to get out of step.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class SchemaTooNewError(RuntimeError):
    """The database was migrated by a newer Studio than the one running now."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> list[Migration]:
    """Read the bundled migration files, sorted by version, and check numbering has no gaps."""
    found = []
    for entry in files("kometa_studio.migrations").iterdir():
        match = MIGRATION_NAME.match(entry.name)
        if match:
            found.append(Migration(int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort(key=lambda m: m.version)
    for expected, migration in enumerate(found, start=1):
        if migration.version != expected:
            raise RuntimeError(f"Migration numbering has a gap: expected {expected:04d}, found {migration.name}")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def apply_migrations(conn: sqlite3.Connection, migrations: list[Migration]) -> int:
    """Bring the database up to the newest migration and return the resulting schema version.

    Each migration must apply completely or not at all, and ``user_version`` must
    only advance past a migration once it has been applied. Migration files must not
    contain their own BEGIN or COMMIT.

    Raises SchemaTooNewError rather than running against a database whose schema
    this code doesn't know (an image downgraded after an upgrade).
    """
    current = schema_version(conn)
    latest = migrations[-1].version if migrations else 0
    if current > latest:
        raise SchemaTooNewError(
            f"The database is at schema version {current}, but this Kometa Studio only knows up to {latest}. "
            "Run the newer Kometa Studio again, or restore a backup taken before the upgrade."
        )

    for migration in migrations:
        if migration.version <= current:
            continue
        # executescript() commits any open transaction before it runs, so BEGIN and the
        # user_version bump go inside the script itself to share one transaction.
        script = f"BEGIN;\n{migration.sql}\n;PRAGMA user_version = {int(migration.version)};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        current = migration.version
    return current


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
            (key, json.dumps(value)),
        )


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    with conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the scheduler's writes
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_database(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    apply_migrations(conn, load_migrations())
    return conn
