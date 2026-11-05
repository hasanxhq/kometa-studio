"""Collection pick rows and preview_counts (migration 0010)."""

import sqlite3
from pathlib import Path

import pytest

from starr_studio import collections as col
from starr_studio.db import apply_migrations, connect, load_migrations, open_database, schema_version


def table_names(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_migration_on_fresh_database(tmp_path: Path):
    db = open_database(tmp_path / "studio.db")
    assert schema_version(db) == len(load_migrations())
    assert {"collections", "preview_counts"} <= table_names(db)


def test_migration_from_schema_9(tmp_path: Path):
    migrations = load_migrations()
    db = connect(tmp_path / "studio.db")
    apply_migrations(db, migrations[:9])
    assert schema_version(db) == 9
    assert "collections" not in table_names(db)
    apply_migrations(db, migrations[:10])
    assert schema_version(db) == 10
    assert {"collections", "preview_counts"} <= table_names(db)
    assert "generated_files" not in table_names(db)
    apply_migrations(db, migrations)
    assert schema_version(db) == len(migrations) >= 11
    assert "generated_files" in table_names(db)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return open_database(tmp_path / "studio.db")


def test_mark_present_upserts_and_desired_groups(db: sqlite3.Connection):
    picks = [
        col.Pick(col.Ref("genre", "Genre", "Action"), "Action Movies", "Action Movies"),
        col.Pick(col.Ref("imdb", "", "IMDb Popular"), "IMDb Popular", "IMDb Popular"),
    ]
    with db:
        ids = col.mark_present(db, "Movies", picks)
    assert len(ids) == 2
    assert col.desired(db, "Movies") == {
        "genre": [col.Ref("genre", "Genre", "Action")],
        "imdb": [col.Ref("imdb", "", "IMDb Popular")],
    }
    with db:
        again = col.mark_present(
            db,
            "Movies",
            [col.Pick(col.Ref("genre", "Genre", "Action"), "Action Films", "Action Films")],
        )
    assert again == [ids[0]]
    row = col.rows(db, "Movies", "genre")[0]
    assert row["kometa_name"] == "Action Films" and row["title"] == "Action Films" and row["desired"] == 1


def test_mark_absent_ignores_unknown_and_delete_rows(db: sqlite3.Connection):
    with db:
        ids = col.mark_present(
            db,
            "TV",
            [col.Pick(col.Ref("genre", "Genre", "Drama"), "Drama Shows", "Drama Shows")],
        )
        absent = col.mark_absent(
            db,
            "TV",
            [col.Ref("genre", "Genre", "Drama"), col.Ref("genre", "Genre", "Missing")],
        )
    assert absent == ids
    assert col.desired(db, "TV") == {}
    assert col.rows(db, "TV")[0]["desired"] == 0
    with db:
        col.delete_rows(db, ids)
    assert col.rows(db, "TV") == []


def test_set_run_record_plex_and_scope(db: sqlite3.Connection):
    with db:
        [row_id] = col.mark_present(
            db,
            "Movies",
            [col.Pick(col.Ref("imdb", "", "IMDb Top 250"), "IMDb Top 250", "IMDb Top 250")],
        )
        col.set_run(db, [row_id], 42)
        col.set_run_scope(db, "Movies", "imdb", "file")
        col.record_plex_state(
            db,
            row_id,
            exists=True,
            rating_key="99",
            items=12,
            thumb="/library/collections/99/thumb",
            built=True,
            error=None,
        )
    row = col.rows(db, "Movies")[0]
    assert row["last_run_id"] == 42
    assert row["run_scope"] == "file"
    assert row["plex_exists"] == 1 and row["plex_rating_key"] == "99" and row["plex_items"] == 12
    assert row["plex_checked_at"] and row["last_built_at"] and row["plex_checked_at"] == row["last_built_at"]
    with db:
        col.record_plex_state(
            db,
            row_id,
            exists=False,
            rating_key=None,
            items=None,
            thumb=None,
            built=False,
            error="gone",
        )
    row = col.rows(db, "Movies")[0]
    assert row["plex_exists"] == 0 and row["last_error"] == "gone"
    assert row["last_built_at"]  # unchanged when built=False


def test_preview_counts(db: sqlite3.Connection):
    with db:
        col.save_counts(db, "Movies", "genre", {"Action": 10, "Drama": 3}, None)
        col.save_counts(db, "Movies", "imdb", {}, "timeout")
    found = col.counts(db, "Movies")
    assert found["genre"]["data"] == {"Action": 10, "Drama": 3}
    assert found["genre"]["error"] is None and found["genre"]["counted_at"].endswith("Z")
    assert found["imdb"]["data"] == {} and found["imdb"]["error"] == "timeout"
