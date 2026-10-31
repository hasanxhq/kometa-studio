import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_items import ItemProblem, apply_item, new_file, read_item, schema_kind
from kometa_studio.config_sections import with_library, with_library_file, with_playlist_file
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"

# Shaped like a hand-written collection file: aligned end-of-line comments, quoted values, list builders.
FILE = """\
## Builders are combined: anything matched by ANY of them goes in.

collections:
  Heroes:
    plex_search:
      any:
        studio:
          - Hero Studios
          - Hero Animation
    imdb_list:
      - https://www.imdb.com/list/ls000000001/   # Main universe
      - https://www.imdb.com/list/ls000000002/   # Spin-offs
    tmdb_collection:
      - 556                                      # Trilogy
    collection_order: release
    sort_title: "!020_Heroes"
    summary: "Everything Heroes: in release order."
  Villains:
    tmdb_collection: 9999
"""


def test_reading_an_item():
    value = read_item(FILE, "collections", "Heroes")
    assert value["plex_search"] == {"any": {"studio": ["Hero Studios", "Hero Animation"]}}
    assert value["tmdb_collection"] == [556]
    assert value["sort_title"] == "!020_Heroes"


def test_changing_one_setting_touches_only_its_line():
    value = read_item(FILE, "collections", "Heroes") | {"summary": "Everything Heroes, newest first.", "collection_order": "release.desc"}
    assert apply_item(FILE, "collections", "Heroes", value) == FILE.replace(
        '    summary: "Everything Heroes: in release order."', '    summary: "Everything Heroes, newest first."'
    ).replace("collection_order: release\n", "collection_order: release.desc\n")


def test_adding_and_removing_settings_and_list_entries():
    value = read_item(FILE, "collections", "Heroes")
    del value["sort_title"]
    value["sync_mode"] = "sync"
    value["plex_search"]["any"]["studio"].append("Hero Television")
    out = apply_item(FILE, "collections", "Heroes", value)
    assert '    sort_title: "!020_Heroes"\n' not in out
    assert out.endswith("  Villains:\n    tmdb_collection: 9999\n")
    assert "    sync_mode: sync\n  Villains:" in out
    assert "          - Hero Animation\n          - Hero Television\n" in out
    assert "      - https://www.imdb.com/list/ls000000002/   # Spin-offs\n" in out  # untouched lines keep their comments
    assert read_item(out, "collections", "Heroes") == value


def test_creating_renaming_and_removing_items():
    created = apply_item(FILE, "collections", "Sidekicks", {"tmdb_collection": [1], "sync_mode": "sync"}, create=True)
    assert created.endswith("  Sidekicks:\n    tmdb_collection:\n      - 1\n    sync_mode: sync\n")

    renamed = apply_item(FILE, "collections", "Heroes", read_item(FILE, "collections", "Heroes"), rename="Superheroes")
    assert renamed == FILE.replace("  Heroes:\n", "  Superheroes:\n")  # same place, same contents

    removed = apply_item(FILE, "collections", "Villains", None)
    assert removed == FILE.replace("  Villains:\n    tmdb_collection: 9999\n", "")


@pytest.mark.parametrize(
    ("call", "status"),
    [
        (lambda: apply_item(FILE, "collections", "Nobody", {"a": 1}), 404),
        (lambda: apply_item(FILE, "collections", "Villains", {"a": 1}, create=True), 409),
        (lambda: apply_item(FILE, "collections", "Heroes", {}, rename="Villains"), 409),
        (lambda: apply_item(FILE, "settings", "x", {}), 422),
        (lambda: apply_item("overlays:\n  - a\n", "overlays", "a", {}), 422),
    ],
)
def test_impossible_edits(call, status):
    with pytest.raises(ItemProblem) as problem:
        call()
    assert problem.value.status == status


@pytest.mark.parametrize(
    ("path", "text", "kind"),
    [
        ("config.yml", "plex: {}\n", "config"),
        ("Movies.yml", FILE, "collection"),
        ("overlays/Ribbon.yml", "overlays:\n  a: {}\n", "overlay"),
        ("Playlists.yml", "templates: {}\nplaylists:\n  a: {}\n", "playlist"),
        ("Meta.yml", "metadata:\n  a: {}\n", "metadata"),
        ("Broken.yml", "collections: [\n", "collection"),
    ],
)
def test_schema_kind(path, text, kind):
    assert schema_kind(text, path) == kind


# --- API ---------------------------------------------------------------------------


@pytest.fixture
def kometa(tmp_path) -> Path:
    root = tmp_path / "kometa"
    config = root / "config"
    config.mkdir(parents=True)
    (config / "config.yml").write_text("libraries:\n  Movies:\n    collection_files:\n      - file: config/Heroes.yml\n")
    (config / "Heroes.yml").write_text(FILE)
    (config / "fake.json").write_text("{}")
    schemas = root / "json-schema"
    schemas.mkdir()
    (schemas / "collection-schema.json").write_text('{"type": "object"}')
    return root


def make_client(tmp_path, kometa):
    settings = Settings(
        data_dir=kometa / "config" / ".studio",
        kometa_config=kometa / "config" / "config.yml",
        kometa_entry=FAKE_KOMETA,
        kometa_python=Path(sys.executable),
        kometa_schemas=kometa / "json-schema",
    )
    return TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000))


def test_editing_an_item_through_the_api(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        item = client.get("/api/v1/config/item", params={"path": "Heroes.yml", "section": "collections", "name": "Heroes"}).json()
        assert item["kind"] == "collection" and item["value"]["tmdb_collection"] == [556]
        value = item["value"] | {"sync_mode": "sync"}
        saved = client.post("/api/v1/config/item", json={"path": "Heroes.yml", "base_hash": item["hash"], "section": "collections", "name": "Heroes", "value": value})
        backups = client.get("/api/v1/backups").json()["backups"]
    assert saved.status_code == 200 and saved.json()["validation"]["ok"]
    assert (kometa / "config" / "Heroes.yml").read_text() == FILE.replace('    summary: "Everything Heroes: in release order."\n', '    summary: "Everything Heroes: in release order."\n    sync_mode: sync\n')
    assert backups[0]["reason"] == "Edited 'Heroes' in Heroes.yml"


def test_a_form_edit_kometa_refuses_changes_nothing(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        item = client.get("/api/v1/config/item", params={"path": "Heroes.yml", "section": "collections", "name": "Villains"}).json()
        response = client.post(
            "/api/v1/config/item",
            json={"path": "Heroes.yml", "base_hash": item["hash"], "section": "collections", "name": "Villains", "value": {"BROKEN": 1}},
        )
    assert response.status_code == 422
    assert "BROKEN" in response.json()["detail"]["validation"]["errors"][0]
    assert (kometa / "config" / "Heroes.yml").read_text() == FILE


def test_item_edits_need_the_current_hash_and_never_touch_config_yml(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        stale = client.post("/api/v1/config/item", json={"path": "Heroes.yml", "base_hash": "old", "section": "collections", "name": "Heroes", "value": {}})
        config = client.get("/api/v1/config/edit", params={"path": "config.yml"}).json()
        whole = client.post("/api/v1/config/item", json={"path": "config.yml", "base_hash": config["hash"], "section": "collections", "name": "x", "value": {}})
    assert stale.status_code == 409
    assert whole.status_code == 422


def test_schemas_are_served_from_the_installed_kometa(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        found = client.get("/api/v1/config/schemas/collection")
        missing = client.get("/api/v1/config/schemas/overlay")
        unknown = client.get("/api/v1/config/schemas/../../etc/passwd")
    assert (found.status_code, found.json()) == (200, {"type": "object"})
    assert missing.status_code == 404
    assert unknown.status_code == 404


# --- New libraries and new files -------------------------------------------------------


def test_adding_a_library_keeps_the_rest_of_config_yml():
    text = "plex:\n  url: http://plex:32400   # the seedbox\nlibraries:\n  Movies:\n    collection_files:\n      - default: basic\n"
    assert with_library(text, "TV Shows") == text + "  TV Shows:\n"
    assert with_library("plex:\n  url: x\n", "Movies") == "plex:\n  url: x\nlibraries:\n  Movies:\n"
    with pytest.raises(ValueError, match="already has a library called Movies"):
        with_library(text, "Movies")
    with pytest.raises(ValueError, match="already has"):  # another key pointing at that Plex library
        with_library("libraries:\n  Films:\n    library_name: Movies\n", "Movies")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("  Movies:\n", "  Movies:\n    collection_files:\n      - file: config/New.yml\n"),
        ("  Movies:\n    collection_files:\n      - default: basic\n", "  Movies:\n    collection_files:\n      - default: basic\n      - file: config/New.yml\n"),
        ("  Movies:\n    collection_files:\n      default: basic\n", "  Movies:\n    collection_files:\n      - default: basic\n      - file: config/New.yml\n"),
    ],
)
def test_a_new_file_is_added_to_the_library(body, expected):
    assert with_library_file("libraries:\n" + body, "Movies", "collection_files", "config/New.yml") == "libraries:\n" + expected


def test_a_new_file_never_hides_the_old_metadata_path():
    with pytest.raises(ValueError, match="old metadata_path"):
        with_library_file("libraries:\n  Movies:\n    metadata_path:\n      - file: config/Old.yml\n", "Movies", "collection_files", "config/New.yml")
    with pytest.raises(ValueError, match="no library called Shows"):
        with_library_file("libraries:\n  Movies:\n", "Shows", "collection_files", "config/New.yml")


def test_new_file_text():
    assert new_file("collections", "Pixar", {"tmdb_company": 3, "sync_mode": "sync"}) == "collections:\n  Pixar:\n    tmdb_company: 3\n    sync_mode: sync\n"
    with pytest.raises(ItemProblem):
        new_file("templates", "x", {})


def test_adding_a_library_through_the_api(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        added = client.post("/api/v1/config/libraries", json={"name": "TV Shows"})
        again = client.post("/api/v1/config/libraries", json={"name": "TV Shows"})
        libraries = client.get("/api/v1/config").json()["libraries"]
    assert added.status_code == 200 and added.json()["validation"]["ok"]
    assert (kometa / "config" / "config.yml").read_text().endswith("  TV Shows:\n")
    assert again.status_code == 409
    assert [library["name"] for library in libraries] == ["Movies", "TV Shows"]


def test_a_collection_in_a_new_file_is_one_checked_save(tmp_path, kometa):
    item = {"path": "Pixar.yml", "base_hash": None, "section": "collections", "name": "Pixar", "value": {"tmdb_company": 3}, "create": True, "library": "Movies"}
    with make_client(tmp_path, kometa) as client:
        saved = client.post("/api/v1/config/item", json=item)
        library = client.get("/api/v1/config/libraries/Movies").json()
        exists = client.post("/api/v1/config/item", json=item)
        broken = client.post("/api/v1/config/item", json=item | {"path": "Broken.yml", "value": {"BROKEN": 1}})
        no_library = client.post("/api/v1/config/item", json=item | {"path": "Other.yml", "library": None})
    assert saved.status_code == 200, saved.text
    assert sorted(f["path"] for f in saved.json()["files"]) == ["Pixar.yml", "config.yml"]
    assert (kometa / "config" / "Pixar.yml").read_text() == "collections:\n  Pixar:\n    tmdb_company: 3\n"
    reference = (kometa / "config" / "Pixar.yml").resolve().as_posix()  # outside the fake Kometa's folder, so in full
    assert (kometa / "config" / "config.yml").read_text().endswith(f"      - file: config/Heroes.yml\n      - file: {reference}\n")
    assert library["collection_files"][-1]["files"][0]["path"] == "Pixar.yml"  # Studio reads it back as the library's
    assert exists.status_code == 409
    assert broken.status_code == 422 and not (kometa / "config" / "Broken.yml").exists()
    assert "Broken.yml" not in (kometa / "config" / "config.yml").read_text()
    assert no_library.status_code == 422


def test_a_playlist_file_goes_in_playlist_files():
    text = "libraries:\n  Movies: {}\n"
    once = with_playlist_file(text, "config/Playlists.yml")
    assert once == text + "playlist_files:\n  - file: config/Playlists.yml\n"
    assert with_playlist_file(once, "config/More.yml").endswith("  - file: config/Playlists.yml\n  - file: config/More.yml\n")
    single = "playlist_files:\n  file: config/Old.yml\n"
    assert with_playlist_file(single, "config/New.yml") == "playlist_files:\n  - file: config/Old.yml\n  - file: config/New.yml\n"


def test_a_playlist_in_a_new_file_needs_no_library(tmp_path, kometa):
    item = {"path": "Playlists.yml", "base_hash": None, "section": "playlists", "name": "Heroes Marathon", "value": {"libraries": "Movies", "tmdb_collection": 556}, "create": True}
    with make_client(tmp_path, kometa) as client:
        saved = client.post("/api/v1/config/item", json=item)
        overview = client.get("/api/v1/config").json()
        backups = client.get("/api/v1/backups").json()["backups"]
    assert saved.status_code == 200, saved.text
    assert (kometa / "config" / "Playlists.yml").read_text() == "playlists:\n  Heroes Marathon:\n    libraries: Movies\n    tmdb_collection: 556\n"
    assert "playlist_files:\n  - file: " in (kometa / "config" / "config.yml").read_text()
    files = [f for reference in overview["playlist_files"] for f in reference["files"]]
    assert [(f["path"], [p["name"] for p in f["playlists"]]) for f in files] == [("Playlists.yml", ["Heroes Marathon"])]
    assert backups[0]["reason"] == "Added the playlist 'Heroes Marathon' in a new file, Playlists.yml"
