import sqlite3

import pytest

from kometa_studio.db import (
    Migration,
    SchemaTooNewError,
    apply_migrations,
    connect,
    load_migrations,
    open_database,
    schema_version,
)


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_bundled_migrations_are_numbered_from_one():
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))


def test_fresh_database_gets_every_migration(tmp_path):
    conn = open_database(tmp_path / "studio.db")
    assert schema_version(conn) == len(load_migrations())
    assert "settings" in table_names(conn)


def test_reapplying_is_a_no_op(tmp_path):
    conn = connect(tmp_path / "studio.db")
    migrations = [Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")]
    assert apply_migrations(conn, migrations) == 1
    assert apply_migrations(conn, migrations) == 1  # would fail with "table a already exists" if it re-ran


def test_only_pending_migrations_run(tmp_path):
    conn = connect(tmp_path / "studio.db")
    first = Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    second = Migration(2, "0002_b.sql", "CREATE TABLE b (x INTEGER);")
    apply_migrations(conn, [first])
    assert apply_migrations(conn, [first, second]) == 2
    assert {"a", "b"} <= table_names(conn)


def test_failed_migration_leaves_no_partial_changes(tmp_path):
    conn = connect(tmp_path / "studio.db")
    good = Migration(1, "0001_good.sql", "CREATE TABLE good (x INTEGER);")
    # The first statement succeeds and the second is a syntax error.
    bad = Migration(2, "0002_bad.sql", "CREATE TABLE half_done (x INTEGER); CREATE TABLE broken (;")
    with pytest.raises(sqlite3.Error):
        apply_migrations(conn, [good, bad])
    assert schema_version(conn) == 1
    assert "half_done" not in table_names(conn)


def test_database_newer_than_the_code_is_refused(tmp_path):
    conn = connect(tmp_path / "studio.db")
    first = Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    second = Migration(2, "0002_b.sql", "CREATE TABLE b (x INTEGER);")
    apply_migrations(conn, [first, second])
    with pytest.raises(SchemaTooNewError):
        apply_migrations(conn, [first])  # an older Studio that only knows migration 1
    assert schema_version(conn) == 2


def test_failed_migration_can_be_retried_once_fixed(tmp_path):
    conn = connect(tmp_path / "studio.db")
    with pytest.raises(sqlite3.Error):
        apply_migrations(conn, [Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER); CREATE TABLE (;")])
    assert not conn.in_transaction
    assert apply_migrations(conn, [Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")]) == 1
