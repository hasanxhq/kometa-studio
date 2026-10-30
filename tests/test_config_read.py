import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.kometa_files import ConfigReader, mask_secrets, unmask_secrets
from kometa_studio.settings import Settings

CONFIG = """\
libraries:
  Movies:
    remove_overlays: false
    template_variables:
      use_separator: false
    collection_files:
      - default: basic
        template_variables:
          sep_style: purple
      - file: config/Movies.yml
        schedule: weekly(sunday)
      - url: https://example.com/collections.yml
    overlay_files:
      - default: ribbon
      - folder: config/overlays/
    operations:
      mass_genre_update: tmdb
      delete_collections:
        configured: false
  TV Shows:
    collection_files:
      - default: missing_default
      - file: config/Nope.yml
playlist_files:
  - default: playlist
plex:
  url: http://plex:32400
  token: abcdefgh12345678
tmdb:
  apikey: tmdb-secret   # from themoviedb.org
webhooks:
  run_end:
    - http://127.0.0.1:8484/api/v1/kometa/events?token=studio-secret  # managed by Kometa Studio
    - https://discord.com/api/webhooks/123/discord-secret
"""

MOVIES = """\
templates:
  Studio:
    tmdb_company: <<id>>
collections:
  Trending:
    tmdb_trending_weekly: 30
    sync_mode: sync
  Pixar:
    template: {name: Studio, id: 3}
  Best of 2024:
    plex_search:
      all:
        year: 2024
    smart_label: critic_rating.desc
dynamic_collections:
  Genres:
    type: genre
"""

OVERLAYS = """\
overlays:
  4K:
    overlay:
      name: 4K
      horizontal_align: left
      vertical_align: top
    plex_search:
      all:
        resolution: 4K
  IMDb Top 250:
    overlay: IMDb Top 250
    imdb_chart: top_movies
"""

BASIC = """\
##############################################################################
#                         Basic Charts Collections                           #
#                 Created by Yozora, Bullmoose20, & Sohjiro                  #
#          EDITING THIS FILE MAY CAUSE PULLING NEW UPDATES TO FAIL           #
#            https://kometa.wiki/en/latest/defaults/chart/basic              #
##############################################################################

collections:
  Basic Chart Collections:
    template: {name: separator}
  Newly Released:
    template: {name: shared}
"""


@pytest.fixture
def kometa(tmp_path) -> Path:
    """A Kometa install: kometa.py's folder with defaults/, and config/ inside it, as in the Docker image."""
    root = tmp_path / "kometa"
    (root / "defaults" / "chart").mkdir(parents=True)
    (root / "defaults" / "overlays").mkdir()
    (root / "defaults" / "chart" / "basic.yml").write_text(BASIC)
    (root / "defaults" / "overlays" / "ribbon.yml").write_text("overlays:\n  Oscars:\n    overlay: {name: oscars}\n")
    (root / "defaults" / "playlist.yml").write_text("playlists:\n  Marvel:\n    libraries: Movies, TV Shows\n")
    config = root / "config"
    (config / "overlays").mkdir(parents=True)
    (config / "config.yml").write_text(CONFIG)
    (config / "Movies.yml").write_text(MOVIES)
    (config / "overlays" / "Movies Overlays.yml").write_text(OVERLAYS)
    (config / ".studio" / "backups" / "20261030").mkdir(parents=True)
    (config / ".studio" / "backups" / "20261030" / "config.yml").write_text("plex:\n  token: unmasked-backup\n")
    return root


def reader(root: Path) -> ConfigReader:
    return ConfigReader(root / "config" / "config.yml", root)


def test_libraries_and_their_files(kometa):
    config = reader(kometa).read()
    movies, tv = config.libraries
    assert (movies.name, tv.name) == ("Movies", "TV Shows")

    basic, own, remote = movies.collection_files
    assert (basic.kind, basic.value, basic.template_variables) == ("default", "basic", {"sep_style": "purple"})
    [default_file] = basic.files
    assert (default_file.path, default_file.title, default_file.docs_url) == (
        "defaults/chart/basic.yml",
        "Basic Charts Collections",
        "https://kometa.wiki/en/latest/defaults/chart/basic",
    )
    assert (own.kind, own.options, own.files[0].path) == ("file", {"schedule": "weekly(sunday)"}, "Movies.yml")
    assert (remote.kind, remote.files, remote.error) == ("url", [], None)

    assert movies.operations == {"mass_genre_update": "tmdb", "delete_collections": {"configured": False}}
    assert movies.template_variables == {"use_separator": False}
    assert movies.settings == {"remove_overlays": False}
    assert [p.files[0].playlists[0]["name"] for p in config.playlist_files] == ["Marvel"]


def test_collections_are_summarised_with_their_builders(kometa):
    [summary] = reader(kometa).read().libraries[0].collection_files[1].files
    assert summary.templates == ["Studio"]
    assert summary.collections == [
        {"name": "Trending", "dynamic": False, "type": None, "builders": ["tmdb_trending_weekly"], "templates": [], "sync_mode": "sync", "schedule": None},
        {"name": "Pixar", "dynamic": False, "type": None, "builders": [], "templates": ["Studio"], "sync_mode": None, "schedule": None},
        {"name": "Best of 2024", "dynamic": False, "type": None, "builders": ["plex_search", "smart_label"], "templates": [], "sync_mode": None, "schedule": None},
        {"name": "Genres", "dynamic": True, "type": "genre", "builders": [], "templates": [], "sync_mode": None, "schedule": None},
    ]


def test_folders_and_overlays(kometa):
    ribbon, folder = reader(kometa).read().libraries[0].overlay_files
    assert ribbon.files[0].path == "defaults/overlays/ribbon.yml"
    [summary] = folder.files
    assert summary.path == "overlays/Movies Overlays.yml"
    assert summary.overlays == [
        {"name": "4K", "overlay": "4K", "position": {"horizontal_align": "left", "vertical_align": "top"}, "builders": ["plex_search"], "templates": []},
        {"name": "IMDb Top 250", "overlay": "IMDb Top 250", "position": {}, "builders": ["imdb_chart"], "templates": []},
    ]


def test_missing_files_are_reported_not_fatal(kometa):
    tv = reader(kometa).read().libraries[1]
    assert [ref.error for ref in tv.collection_files] == [
        f"Not found: {'missing_default'}",
        f"Not found: {kometa / 'config' / 'Nope.yml'}",
    ]


def test_broken_config(kometa):
    (kometa / "config" / "config.yml").write_text("libraries: [oops\n")
    with pytest.raises(ValueError, match="isn't valid YAML"):
        reader(kometa).read()


def test_secrets_are_masked_with_numbered_placeholders():
    masked, secrets = mask_secrets(CONFIG)
    for secret in ("abcdefgh12345678", "tmdb-secret", "studio-secret", "discord-secret"):
        assert secret not in masked
    assert secrets == ["abcdefgh12345678", "tmdb-secret", "studio-secret", "123/discord-secret"]
    assert "  token: ••••(1)\n" in masked
    assert "  apikey: ••••(2)   # from themoviedb.org\n" in masked
    assert "events?token=••••(3)  # managed by Kometa Studio" in masked
    assert "https://discord.com/api/webhooks/••••(4)\n" in masked  # the whole path after /webhooks/
    assert "url: http://plex:32400" in masked


def test_placeholders_are_put_back():
    masked, secrets = mask_secrets(CONFIG)
    assert unmask_secrets(masked, secrets) == CONFIG
    # Moving lines around keeps each secret with its own placeholder.
    moved = masked.replace("tmdb:\n  apikey: ••••(2)", "tmdb:\n  language: en\n  apikey: ••••(2)")
    assert "  apikey: tmdb-secret" in unmask_secrets(moved, secrets)
    # A new value typed over a placeholder is kept.
    assert "  token: new-token\n" in unmask_secrets(masked.replace("token: ••••(1)", "token: new-token"), secrets)


@pytest.mark.parametrize("bad", ["token: ••••(9)", "token: ••••", "token: ab••••(1)cd"])
def test_damaged_placeholders_are_refused(bad):
    masked, secrets = mask_secrets(CONFIG)
    with pytest.raises(ValueError):
        unmask_secrets(masked.replace("token: ••••(1)", bad), secrets)


# --- API ---------------------------------------------------------------------


def make_client(tmp_path, kometa):
    settings = Settings(data_dir=kometa / "config" / ".studio", kometa_config=kometa / "config" / "config.yml", kometa_entry=kometa / "kometa.py")
    return TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000))


def test_library_cards(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        body = client.get("/api/v1/config").json()
    movies, tv = body["libraries"]
    assert movies | {"problems": None} == {
        "name": "Movies",
        "plex_name": "Movies",
        "collection_files": 3,
        "overlay_files": 2,
        "metadata_files": 0,
        "defaults": 2,
        "collections": 4,
        "overlays": 2,
        "operations": 2,
        "problems": None,
    }
    assert movies["problems"] == []
    assert len(tv["problems"]) == 2


def test_library_name_maps_a_config_entry_to_another_plex_library(tmp_path, kometa):
    config = kometa / "config" / "config.yml"
    config.write_text(config.read_text().replace("  TV Shows:\n", "  TV Shows:\n    library_name: Series\n"))
    with make_client(tmp_path, kometa) as client:
        tv = client.get("/api/v1/config").json()["libraries"][1]
    assert (tv["name"], tv["plex_name"]) == ("TV Shows", "Series")


def test_one_library(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        body = client.get("/api/v1/config/libraries/TV Shows").json()
        missing = client.get("/api/v1/config/libraries/Music")
    assert body["name"] == "TV Shows"
    assert body["collection_files"][1]["kind"] == "file"
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("config.yml", 200),
        ("Movies.yml", 200),
        ("overlays/Movies Overlays.yml", 200),
        ("defaults/chart/basic.yml", 200),
        (".studio/backups/20261030/config.yml", 404),  # Studio's own data stays private
        ("../../../etc/passwd", 404),
        ("../kometa.py", 404),
    ],
)
def test_viewing_files(tmp_path, kometa, path, status):
    with make_client(tmp_path, kometa) as client:
        response = client.get("/api/v1/config/file", params={"path": path})
    assert response.status_code == status
    if path == "config.yml":
        assert "abcdefgh12345678" not in response.json()["text"]


def test_no_config_yet(tmp_path, kometa):
    (kometa / "config" / "config.yml").unlink()
    with make_client(tmp_path, kometa) as client:
        response = client.get("/api/v1/config")
    assert response.status_code == 404
    assert "Connect Plex" in response.json()["detail"]


def test_history_lists_changes_newest_first_and_filters(tmp_path, kometa):
    with make_client(tmp_path, kometa):
        pass
    db = sqlite3.connect(kometa / "config" / ".studio" / "studio.db")
    events = [
        ("changes", {"library_name": "Movies", "collection": "Trending", "created": True, "additions": [{"title": "Dune", "tmdb_id": 438631}], "removals": []}),
        ("error", {"error": "nope"}),
        ("changes", {"library_name": "TV Shows", "collection": "Popular_50%", "additions": [], "removals": [{"title": "Lost", "tvdb_id": 73739}]}),
        ("delete", {"library_name": "Movies", "message": "Collection Old Stuff Deleted"}),
        ("changes", {"library_name": "Movies", "collection": "Pixar", "radarr_adds": [{"title": "Elio", "id": 1022787}]}),
    ]
    with db:
        db.executemany("INSERT INTO run_events (event, payload) VALUES (?, ?)", [(e, json.dumps(p)) for e, p in events])
    db.close()

    with make_client(tmp_path, kometa) as client:
        everything = client.get("/api/v1/history").json()
        movies = client.get("/api/v1/history", params={"library": "Movies"}).json()
        search = client.get("/api/v1/history", params={"q": "50%"}).json()
        page = client.get("/api/v1/history", params={"limit": 2}).json()
        rest = client.get("/api/v1/history", params={"limit": 2, "before": page["next"]}).json()

    assert [e["collection"] or e["message"] for e in everything["events"]] == ["Pixar", "Collection Old Stuff Deleted", "Popular_50%", "Trending"]
    assert everything["libraries"] == ["Movies", "TV Shows"]
    assert everything["events"][0]["radarr_adds"] == [{"title": "Elio", "tmdb_id": 1022787, "tvdb_id": None}]
    assert everything["events"][3]["created"] is True
    assert [e["collection"] for e in movies["events"] if e["event"] == "changes"] == ["Pixar", "Trending"]
    assert [e["collection"] for e in search["events"]] == ["Popular_50%"]  # % is literal, not a wildcard
    assert len(page["events"]) == 2 and page["next"] is not None
    assert [e["collection"] or e["message"] for e in rest["events"]] == ["Popular_50%", "Trending"]
    assert rest["next"] is None
