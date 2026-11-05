"""Moving over from Kometa: how each collection in a user's files would land (read-only)."""

from __future__ import annotations

from pathlib import Path

from starr_studio import collections as col
from starr_studio import kometa_import
from starr_studio.db import connect
from starr_studio.kometa_files import ConfigReader
from starr_studio.kometa_import import IMPORTED, KEPT, STUDIO, describe, describe_file
from test_ready_made_routes import make_client, root  # noqa: F401 (root is a fixture)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "ready_made_defaults"


def test_a_smart_filter_collection_is_imported_with_its_settings():
    landing = describe(
        "Action",
        {
            "smart_filter": {"all": {"genre": ["Action"], "year.gte": 2000}, "sort_by": "release.desc", "limit": 50},
            "summary": "Things that explode",
            "sort_title": "!01 Action",
            "visible_home": True,
            "minimum_items": 3,
            "url_poster": "https://example.org/a.jpg",
            "label": "Studio",
        },
        "movie",
    )
    assert landing.result == IMPORTED, landing.reason
    definition = landing.definition
    assert definition["source"] == {"kind": "filters"}
    assert definition["filters"] == {"match": "all", "rules": [
        {"field": "genre", "modifier": "", "value": ["Action"]},
        {"field": "year", "modifier": "gte", "value": 2000},
    ]}
    assert (definition["sort_by"], definition["limit"]) == ("release.desc", 50)
    assert definition["visible"] == {"library": True, "home": True, "shared": False}
    assert definition["minimum_items"] == 3
    assert definition["summary"] == "Things that explode" and definition["sort_title"] == "!01 Action"
    assert definition["poster"] == {"kind": "url", "url": "https://example.org/a.jpg"}


def test_a_list_collection_is_imported_and_kometas_requests_are_turned_off():
    landing = describe(
        "Dune",
        {"tmdb_collection": [726871], "collection_order": "release", "sync_mode": "append", "radarr_add_missing": True},
        "movie",
    )
    assert landing.result == IMPORTED, landing.reason
    assert landing.definition["source"] == {"kind": "list", "builder": "tmdb_collection", "value": "726871", "label": None}
    assert landing.definition["sort_by"] == "release"
    assert any("sync" in note for note in landing.notes)
    assert any("radarr_add_missing" in note and "Download missing" in note for note in landing.notes)

    imdb = describe("Top", {"imdb_list": "https://www.imdb.com/list/ls539646485/"}, "movie")
    assert imdb.result == IMPORTED and imdb.definition["source"]["value"] == "https://www.imdb.com/list/ls539646485/"


def test_what_the_builder_cant_describe_is_kept_with_the_reason():
    cases = {
        "combined": ({"plex_search": {"any": {"studio": ["Marvel Studios"]}}, "imdb_list": "https://www.imdb.com/list/ls1/"}, "combines 2 sources"),
        "two lists": ({"imdb_list": ["https://www.imdb.com/list/ls1/", "https://www.imdb.com/list/ls2/"]}, "reads 2 IMDb lists"),
        "search": ({"plex_search": {"any": {"studio": ["A24"]}}}, "`plex_search` isn't one the builder offers"),
        "template": ({"template": {"name": "x"}, "tmdb_collection": 1}, "template"),
        "label": ({"tmdb_collection": 1, "label": ["Kids"]}, "label Kids"),
        "other key": ({"tmdb_collection": 1, "schedule": "weekly(sunday)"}, "`schedule`"),
        "nested": ({"smart_filter": {"all": {"any": {"genre": ["Action"]}}}}, "nests"),
        "bad field": ({"smart_filter": {"all": {"nonsense": "x"}}}, "can't show its `smart_filter`"),
        "order": ({"tmdb_collection": 1, "collection_order": "audience_rating.desc"}, "collection_order"),
        "show source in movies": ({"tmdb_list": "https://www.themoviedb.org/collection/1"}, "TMDb collection"),
        "empty": ({}, "no source"),
    }
    for name, (body, words) in cases.items():
        landing = describe(name, body, "movie")
        assert landing.result == KEPT, name
        assert words in landing.reason, (name, landing.reason)


def test_a_file_poster_is_imported_only_when_studio_can_read_it(tmp_path):
    poster = tmp_path / "poster.png"
    poster.write_bytes(b"x")
    body = {"tmdb_collection": 1, "file_poster": "poster.png"}
    landing = describe("Dune", body, "movie", lambda value: tmp_path / value)
    assert landing.result == IMPORTED
    assert landing.definition["poster"] == {"kind": "import", "path": str(poster)}
    assert describe("Dune", {**body, "file_poster": "gone.png"}, "movie", lambda value: tmp_path / value).result == KEPT
    assert describe("Dune", body, "movie").result == KEPT


def test_a_file_is_replaced_only_when_every_collection_in_it_imports():
    good = "collections:\n  A:\n    tmdb_collection: 1\n  B:\n    smart_filter:\n      any:\n        genre: Drama\n"
    action, reason, landings = describe_file(good, "movie")
    assert (action, reason) == ("replace", None)
    assert [landing.result for landing in landings] == [IMPORTED, IMPORTED]

    mixed = good + "  C:\n    plex_search:\n      any:\n        studio: A24\n"
    action, reason, landings = describe_file(mixed, "movie")
    assert action == "keep" and reason == "C can't be imported"
    assert [(landing.result, landing.kept_with_file) for landing in landings] == [(IMPORTED, True), (IMPORTED, True), (KEPT, False)]

    with_templates = "templates:\n  t:\n    sync_mode: sync\n" + good
    assert describe_file(with_templates, "movie")[:2] == ("keep", "It holds `templates`, which stay with Kometa")
    dynamic = "dynamic_collections:\n  Genres:\n    type: genre\n"
    action, _reason, landings = describe_file(dynamic, "movie")
    assert action == "keep" and landings[0].result == KEPT and "dynamic" in landings[0].reason
    assert describe_file("collections: [", "movie")[0] == "keep"
    assert describe_file("# Written by Starr Studio from its collection builder.\ncollections: {}\n", "movie")[0] == "studio"


def test_a_title_studio_already_has_lands_as_studio():
    _action, _reason, landings = describe_file("collections:\n  Action Picks:\n    tmdb_collection: 1\n", "movie", {"action picks"})
    assert landings[0].result == STUDIO


def _reader(tmp_path: Path, libraries: str) -> ConfigReader:
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "config.yml").write_text(libraries)
    return ConfigReader(config / "config.yml", tmp_path)


def test_report_covers_files_folders_defaults_remote_and_studios_own(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "lists.yml").write_text("collections:\n  Dune:\n    tmdb_collection: 726871\n")
    (config / "mixed.yml").write_text("collections:\n  Dune 2:\n    tmdb_collection: 1\n  Search:\n    plex_search:\n      any:\n        studio: A24\n")
    (config / "folder").mkdir()
    (config / "folder" / "one.yml").write_text("collections:\n  One:\n    tmdb_collection: 2\n")
    (config / "studio" / "Movies").mkdir(parents=True)
    (config / "studio" / "Movies" / "built.yml").write_text("# Written by Starr Studio\ncollections: {}\n")
    reader = _reader(tmp_path, (
        "libraries:\n  Movies:\n    collection_files:\n"
        "    - file: config/lists.yml\n"
        "    - file: config/mixed.yml\n"
        "    - folder: config/folder\n"
        "    - file: config/studio/Movies/built.yml\n"
        "    - url: https://example.org/x.yml\n"
        "    - default: basic\n"
        "    - default: genre\n      template_variables:\n        use_separator: false\n"
        "    - default: oscars\n      template_variables:\n        sort_by: title.asc\n"
        "    overlay_files:\n    - default: ribbon\n"
        "  Music:\n    collection_files:\n    - file: config/lists.yml\n"
    ))
    report = kometa_import.report(reader, {"Movies": "movie", "Music": "artist"}, kometa_root=FIXTURES_ROOT)
    movies, music = report["libraries"]
    by_value = {entry["value"]: entry for entry in movies["files"]}
    assert by_value["config/lists.yml"]["action"] == "replace"
    assert by_value["config/mixed.yml"]["action"] == "keep"
    assert by_value["config/folder"]["action"] == "keep" and "folder" in by_value["config/folder"]["reason"]
    assert by_value["config/studio/Movies/built.yml"]["action"] == "studio"
    assert by_value["https://example.org/x.yml"]["action"] == "keep" and "url" in by_value["https://example.org/x.yml"]["reason"]
    assert by_value["basic"]["action"] == "replace" and by_value["basic"]["ready_made"]["category"] == "basic"
    assert by_value["genre"]["action"] == "replace"
    assert by_value["oscars"]["action"] == "keep" and "`sort_by`" in by_value["oscars"]["reason"]
    assert movies["overlay_files"] == ["ribbon"]
    assert music["error"] and music["files"] == []

    summary = report["summary"]
    # lists.yml's Dune; mixed.yml's two (one kept with its file); folder's One (kept with its folder); 3 defaults
    assert summary["imported"] == 1
    assert summary["ready_made"] == 2
    assert summary["kept"] == 4  # Dune 2 and One with their files, Search, and oscars
    assert summary["kept_with_file"] == 2
    assert summary["files"]["studio"] == 1


def test_report_without_plex_says_why(tmp_path):
    (tmp_path / "config").mkdir()
    reader = _reader(tmp_path, "libraries:\n  Movies:\n    collection_files:\n    - file: config/x.yml\n")
    report = kometa_import.report(reader, {"Movies": None})
    assert "Plex can't be reached" in report["libraries"][0]["error"]


def test_import_route_reads_and_writes_nothing(root):
    config = root / "config"
    (config / "lists.yml").write_text("collections:\n  Dune:\n    tmdb_collection: 726871\n  Taken:\n    tmdb_collection: 2\n")
    (config / "config.yml").write_text((config / "config.yml").read_text().replace("Movies: {}", f"Movies:\n    collection_files:\n    - file: {config / 'lists.yml'}"))
    before = {path: path.read_bytes() for path in config.rglob("*") if path.is_file()}
    client, _plex, _m = make_client(root)
    with client:
        db = connect(root / "data" / "studio.db")
        col.insert_built(db, "Movies", "k1", "Taken", {"source": {"kind": "filters"}})
        db.commit()
        db.close()
        response = client.get("/api/v1/import")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["config"] is True
    files = report["libraries"][0]["files"]
    assert report["libraries"][0]["type"] == "movie"
    assert [(c["name"], c["result"]) for c in files[0]["collections"]] == [("Dune", "imported"), ("Taken", "studio")]
    assert {path: path.read_bytes() for path in config.rglob("*") if path.is_file()} == before
