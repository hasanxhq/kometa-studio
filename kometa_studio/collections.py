"""SQLite rows for Studio's ready-made collection picks (Phase 1).

Each pick is one row: a static collection (``block`` empty) or one key under a
``dynamic_collections`` block. Callers wrap writes in ``with db:``; these helpers
do not open their own transaction.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .runner import now


@dataclass(frozen=True)
class Ref:
    category: str
    block: str
    key: str


@dataclass
class Pick:
    ref: Ref
    kometa_name: str
    title: str


def rows(db: sqlite3.Connection, library: str, category: str | None = None) -> list[sqlite3.Row]:
    if category is None:
        return list(db.execute("SELECT * FROM collections WHERE library = ? ORDER BY category, block, key", (library,)))
    return list(
        db.execute(
            "SELECT * FROM collections WHERE library = ? AND category = ? ORDER BY block, key",
            (library, category),
        )
    )


def desired(db: sqlite3.Connection, library: str) -> dict[str, list[Ref]]:
    """The refs with ``desired = 1``, grouped by category."""
    found: dict[str, list[Ref]] = {}
    for row in db.execute(
        "SELECT category, block, key FROM collections WHERE library = ? AND desired = 1 ORDER BY category, block, key",
        (library,),
    ):
        found.setdefault(row["category"], []).append(Ref(row["category"], row["block"], row["key"]))
    return found


def mark_present(db: sqlite3.Connection, library: str, picks: list[Pick]) -> list[int]:
    """Upsert picks as desired, updating ``kometa_name`` and ``title``. Returns the row ids."""
    stamp = now()
    ids: list[int] = []
    for pick in picks:
        ref = pick.ref
        db.execute(
            """
            INSERT INTO collections (
                library, category, block, key, kometa_name, title, desired, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT (library, category, block, key) DO UPDATE SET
                kometa_name = excluded.kometa_name,
                title = excluded.title,
                desired = 1,
                updated_at = excluded.updated_at
            """,
            (library, ref.category, ref.block, ref.key, pick.kometa_name, pick.title, stamp, stamp),
        )
        row = db.execute(
            "SELECT id FROM collections WHERE library = ? AND category = ? AND block = ? AND key = ?",
            (library, ref.category, ref.block, ref.key),
        ).fetchone()
        ids.append(int(row["id"]))
    return ids


def mark_absent(db: sqlite3.Connection, library: str, refs: list[Ref]) -> list[int]:
    """Set ``desired = 0`` on existing rows; unknown refs are ignored. Returns the ids touched."""
    stamp = now()
    ids: list[int] = []
    for ref in refs:
        row = db.execute(
            "SELECT id FROM collections WHERE library = ? AND category = ? AND block = ? AND key = ?",
            (library, ref.category, ref.block, ref.key),
        ).fetchone()
        if row is None:
            continue
        db.execute(
            "UPDATE collections SET desired = 0, updated_at = ? WHERE id = ?",
            (stamp, row["id"]),
        )
        ids.append(int(row["id"]))
    return ids


def delete_rows(db: sqlite3.Connection, ids: list[int]) -> None:
    if not ids:
        return
    db.executemany("DELETE FROM collections WHERE id = ?", [(row_id,) for row_id in ids])


def set_run(db: sqlite3.Connection, ids: list[int], run_id: int) -> None:
    if not ids:
        return
    stamp = now()
    db.executemany(
        "UPDATE collections SET last_run_id = ?, updated_at = ? WHERE id = ?",
        [(run_id, stamp, row_id) for row_id in ids],
    )


def record_plex_state(
    db: sqlite3.Connection,
    row_id: int,
    *,
    exists: bool,
    rating_key: str | None,
    items: int | None,
    thumb: str | None,
    built: bool,
    error: str | None,
) -> None:
    stamp = now()
    if built:
        db.execute(
            """
            UPDATE collections SET
                plex_exists = ?, plex_rating_key = ?, plex_items = ?, plex_thumb = ?,
                plex_checked_at = ?, last_built_at = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (1 if exists else 0, rating_key, items, thumb, stamp, stamp, error, stamp, row_id),
        )
    else:
        db.execute(
            """
            UPDATE collections SET
                plex_exists = ?, plex_rating_key = ?, plex_items = ?, plex_thumb = ?,
                plex_checked_at = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (1 if exists else 0, rating_key, items, thumb, stamp, error, stamp, row_id),
        )


def set_run_scope(db: sqlite3.Connection, library: str, category: str, scope: str) -> None:
    stamp = now()
    db.execute(
        "UPDATE collections SET run_scope = ?, updated_at = ? WHERE library = ? AND category = ?",
        (scope, stamp, library, category),
    )


def save_counts(db: sqlite3.Connection, library: str, category: str, data: dict, error: str | None) -> None:
    stamp = now()
    db.execute(
        """
        INSERT INTO preview_counts (library, category, data, counted_at, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (library, category) DO UPDATE SET
            data = excluded.data,
            counted_at = excluded.counted_at,
            error = excluded.error
        """,
        (library, category, json.dumps(data), stamp, error),
    )


def counts(db: sqlite3.Connection, library: str) -> dict[str, dict[str, Any]]:
    """category → {data, counted_at, error}."""
    found: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        "SELECT category, data, counted_at, error FROM preview_counts WHERE library = ?",
        (library,),
    ):
        found[row["category"]] = {
            "data": json.loads(row["data"]),
            "counted_at": row["counted_at"],
            "error": row["error"],
        }
    return found


def record_generated(db: sqlite3.Connection, files: dict[str, str]) -> None:
    """Remember what Studio wrote to its generated files: path (config-relative) → sha256."""
    stamp = now()
    db.executemany(
        "INSERT INTO generated_files (path, hash, written_at) VALUES (?, ?, ?) "
        "ON CONFLICT (path) DO UPDATE SET hash = excluded.hash, written_at = excluded.written_at",
        [(path, digest, stamp) for path, digest in files.items()],
    )


def forget_generated(db: sqlite3.Connection, paths: list[str]) -> None:
    db.executemany("DELETE FROM generated_files WHERE path = ?", [(path,) for path in paths])


def generated(db: sqlite3.Connection) -> dict[str, str]:
    """path → the sha256 Studio last wrote there."""
    return {row["path"]: row["hash"] for row in db.execute("SELECT path, hash FROM generated_files")}


# --- Builder collections (phase 2) -------------------------------------------------------
# One row each, category BUILT, block '', key a stable random id (the title can change), origin 'built',
# and the user's definition as JSON. They share Plex state, the run hook and removal with ready-made rows.

BUILT = "built"


def built_rows(db: sqlite3.Connection, library: str | None = None) -> list[sqlite3.Row]:
    if library is None:
        return list(db.execute("SELECT * FROM collections WHERE category = ? ORDER BY library, title", (BUILT,)))
    return list(db.execute("SELECT * FROM collections WHERE library = ? AND category = ? ORDER BY title", (library, BUILT)))


def built_row(db: sqlite3.Connection, row_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM collections WHERE id = ? AND category = ?", (row_id, BUILT)).fetchone()


def insert_built(db: sqlite3.Connection, library: str, key: str, title: str, definition: dict) -> int:
    stamp = now()
    cursor = db.execute(
        """
        INSERT INTO collections (library, category, block, key, kometa_name, title, origin, desired, definition, created_at, updated_at)
        VALUES (?, ?, '', ?, ?, ?, 'built', 1, ?, ?, ?)
        """,
        (library, BUILT, key, title, title, json.dumps(definition), stamp, stamp),
    )
    return int(cursor.lastrowid)


def update_built(db: sqlite3.Connection, row_id: int, title: str, definition: dict) -> None:
    db.execute(
        "UPDATE collections SET title = ?, kometa_name = ?, definition = ?, last_error = NULL, updated_at = ? WHERE id = ?",
        (title, title, json.dumps(definition), now(), row_id),
    )


def built_definitions(db: sqlite3.Connection, library: str) -> list[tuple[str, dict]]:
    """(title, definition) for the library's builder collections that should exist, by title."""
    return [(row["title"], json.loads(row["definition"] or "{}")) for row in built_rows(db, library) if row["desired"]]
