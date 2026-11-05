from pathlib import Path
import sys

from fastapi.testclient import TestClient

from starr_studio.app import create_app
from starr_studio.config_sections import with_library_option
from starr_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"

TEXT = """\
libraries:
  Movies:
    collection_files:
      - file: config/Movies.yml
    operations:
      mass_genre_update: imdb   # keep the comment
      assets_for_all: true
    settings:
      sync_mode: append  # library override
      cache: false
  Shows:
    collection_files:
      - file: config/Shows.yml
"""

LIST_TEXT = """\
libraries:
  Movies:
    collection_files:
      - file: config/Movies.yml
    operations:
      - mass_genre_update: tmdb  # block 1
        schedule: weekly(sunday)
      - assets_for_all: true
"""


def test_changing_operations_keeps_comments_and_other_keys():
    changed = with_library_option(TEXT, "Movies", "operations", {"mass_genre_update": "tmdb", "assets_for_all": True})
    assert "mass_genre_update: tmdb   # keep the comment" in changed
    assert "assets_for_all: true" in changed
    assert "sync_mode: append  # library override" in changed
    removed = with_library_option(TEXT, "Movies", "operations", {})
    assert "operations:" not in removed
    assert "settings:" in removed


def test_list_form_operations_round_trip_only_edits_the_changed_block():
    changed = with_library_option(
        LIST_TEXT,
        "Movies",
        "operations",
        [{"mass_genre_update": "imdb", "schedule": "weekly(sunday)"}, {"assets_for_all": True}],
    )
    assert "mass_genre_update: imdb  # block 1" in changed
    assert "schedule: weekly(sunday)" in changed
    assert "assets_for_all: true" in changed
    assert changed.index("mass_genre_update") < changed.index("assets_for_all")


def test_library_settings_empty_removes_the_section():
    removed = with_library_option(TEXT, "Movies", "settings", {})
    assert "settings:" not in removed
    assert "mass_genre_update: imdb   # keep the comment" in removed
    changed = with_library_option(TEXT, "Movies", "settings", {"sync_mode": "sync", "cache": False})
    assert "sync_mode: sync" in changed and "# library override" in changed


def make_client(tmp_path, text=TEXT):
    config = tmp_path / "config.yml"
    config.write_text(text)
    (tmp_path / "Movies.yml").write_text("collections: {}\n")
    app = create_app(
        Settings(data_dir=tmp_path / "data", kometa_config=config, kometa_entry=FAKE_KOMETA, kometa_python=Path(sys.executable)),
        static_dir=tmp_path / "no-static",
    )
    return TestClient(app, client=("127.0.0.1", 50000)), config


def test_library_operations_through_the_api(tmp_path):
    client, config = make_client(tmp_path)
    with client:
        base = {"mass_genre_update": "imdb", "assets_for_all": True}
        saved = client.put("/api/v1/config/libraries/Movies/operations", json={"base": base, "values": {"mass_genre_update": "tmdb"}})
        stale = client.put("/api/v1/config/libraries/Movies/operations", json={"base": base, "values": {"assets_for_all": False}})
        missing = client.put("/api/v1/config/libraries/NoSuch/operations", json={"base": {}, "values": {"assets_for_all": True}})
        backups = client.get("/api/v1/backups").json()["backups"]
    assert saved.status_code == 200 and saved.json()["validation"]["ok"] is True
    text = config.read_text()
    assert "mass_genre_update: tmdb   # keep the comment" in text
    assert "assets_for_all" not in text
    assert stale.status_code == 409 and "changed since you opened them" in stale.json()["detail"]["message"]
    assert missing.status_code == 404
    assert [b["reason"] for b in backups] == ["Changed the operations for Movies"]


def test_clearing_operations_removes_the_section(tmp_path):
    client, config = make_client(tmp_path)
    with client:
        base = {"mass_genre_update": "imdb", "assets_for_all": True}
        saved = client.put("/api/v1/config/libraries/Movies/operations", json={"base": base, "values": {}})
    assert saved.status_code == 200
    assert "operations:" not in config.read_text()
    assert "settings:" in config.read_text()


def test_list_form_operations_through_the_api(tmp_path):
    client, config = make_client(tmp_path, LIST_TEXT)
    with client:
        base = [{"mass_genre_update": "tmdb", "schedule": "weekly(sunday)"}, {"assets_for_all": True}]
        values = [{"mass_genre_update": "imdb", "schedule": "weekly(sunday)"}, {"assets_for_all": True}]
        saved = client.put("/api/v1/config/libraries/Movies/operations", json={"base": base, "values": values})
    assert saved.status_code == 200
    text = config.read_text()
    assert "mass_genre_update: imdb  # block 1" in text
    assert "assets_for_all: true" in text
    assert text.count("- ") >= 2


def test_library_settings_through_the_api(tmp_path):
    client, config = make_client(tmp_path)
    with client:
        base = {"sync_mode": "append", "cache": False}
        saved = client.put("/api/v1/config/libraries/Movies/settings", json={"base": base, "values": {"sync_mode": "sync"}})
        assert saved.status_code == 200
        assert "sync_mode: sync" in config.read_text() and "# library override" in config.read_text()
        stale = client.put("/api/v1/config/libraries/Movies/settings", json={"base": base, "values": {"cache": True}})
        cleared = client.put("/api/v1/config/libraries/Movies/settings", json={"base": {"sync_mode": "sync"}, "values": {}})
    assert stale.status_code == 409
    assert cleared.status_code == 200 and "settings:" not in config.read_text()
