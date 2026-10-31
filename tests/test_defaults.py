import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_sections import with_library_default, with_library_variables
from kometa_studio.kometa_files import ConfigReader
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"


def banner(title: str, wiki: str) -> str:
    return f"#####\n#  {title}  #\n#  Created by Someone  #\n#  EDITING THIS FILE MAY CAUSE PULLING NEW UPDATES TO FAIL  #\n#  https://kometa.wiki/en/latest/defaults/{wiki}  #\n#####\n\ncollections: {{}}\n"


@pytest.fixture
def kometa(tmp_path) -> Path:
    """A Kometa folder with a few defaults, laid out as the installed Kometa's are."""
    root = tmp_path / "kometa"
    for path, title in {
        "chart/basic.yml": "Basic Charts Collections",
        "award/oscars.yml": "Oscars Collections",
        "both/streaming.yml": "Streaming Collections",
        "movie/decade.yml": "Decade Collections",
        "show/decade.yml": "Decade Collections",
        "show/network.yml": "Network Collections",
        "overlays/resolution.yml": "Resolution Overlays",
        "overlays/content_rating_us_movie.yml": "US Movie Content Rating Overlays",
        "overlays/templates.yml": "Overlay Templates",
    }.items():
        file = root / "defaults" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(banner(title, path.removesuffix(".yml")))
    (root / "defaults" / "templates.yml").write_text("templates: {}\n")
    config = root / "config"
    config.mkdir()
    (config / "config.yml").write_text(
        "libraries:\n  Movies:\n    collection_files:\n      - default: basic   # charts\n      - default: streaming\n        template_variables:\n          region: GB   # where we are\n          use_all: false\n"
        "  TV Shows:\n"
    )
    (config / "fake.json").write_text("{}")
    shutil.copy(FAKE_KOMETA, root / "kometa.py")
    return root


def test_the_catalogue_of_installed_defaults(kometa):
    catalogue = ConfigReader(kometa / "config" / "config.yml", kometa).catalogue()
    collections = {entry["name"]: entry for entry in catalogue["collections"]}
    assert collections["basic"] == {
        "name": "basic", "group": "chart", "types": ["movie", "show"], "title": "Basic Charts Collections", "docs_url": "https://kometa.wiki/en/latest/defaults/chart/basic",
    }
    assert (collections["decade"]["group"], collections["decade"]["types"]) == ("both", ["movie", "show"])  # in movie/ and show/
    assert (collections["network"]["group"], collections["network"]["types"]) == ("show", ["show"])
    assert [(o["name"], o["types"]) for o in catalogue["overlays"]] == [("content_rating_us_movie", ["movie"]), ("resolution", ["movie", "show"])]


TEXT = """\
libraries:
  Movies:
    collection_files:
      - default: basic   # charts
      - default: streaming
        template_variables:
          region: GB   # where we are
          use_all: false
"""


def test_turning_a_default_on_with_its_variables():
    on = with_library_default(TEXT, "Movies", "collection_files", "imdb", {"use_all": False})
    assert on == TEXT + "      - default: imdb\n        template_variables:\n          use_all: false\n"
    overlay = with_library_default(TEXT, "Movies", "overlay_files", "resolution", {})
    assert overlay == TEXT + "    overlay_files:\n      - default: resolution\n"


def test_changing_a_defaults_variables_keeps_the_rest_as_written():
    changed = with_library_default(TEXT, "Movies", "collection_files", "streaming", {"region": "GB", "use_all": True, "originals_only": True})
    assert changed == TEXT.replace("          use_all: false\n", "          use_all: true\n          originals_only: true\n")
    cleared = with_library_default(TEXT, "Movies", "collection_files", "streaming", {})
    assert cleared == TEXT.replace("        template_variables:\n          region: GB   # where we are\n          use_all: false\n", "")


def test_turning_a_default_off():
    off = with_library_default(TEXT, "Movies", "collection_files", "streaming", None)
    assert off == "libraries:\n  Movies:\n    collection_files:\n      - default: basic   # charts\n"
    last = with_library_default(off, "Movies", "collection_files", "basic", None)
    assert last == "libraries:\n  Movies: {}\n" or last == "libraries:\n  Movies:\n"  # Kometa refuses an empty list, so the list goes
    old_style = "libraries:\n  Movies:\n    collection_files:\n      - pmm: basic\n      - git: PMM/imdb\n"
    assert with_library_default(old_style, "Movies", "collection_files", "imdb", None) == "libraries:\n  Movies:\n    collection_files:\n      - pmm: basic\n"
    with pytest.raises(ValueError, match="doesn't use the oscars default"):
        with_library_default(TEXT, "Movies", "collection_files", "oscars", None)
    with pytest.raises(ValueError, match="old metadata_path"):
        with_library_default("libraries:\n  Movies:\n    metadata_path:\n      - default: basic\n", "Movies", "collection_files", "imdb", {})


def test_a_librarys_own_variables():
    text = "libraries:\n  TV Shows:\n"
    with_vars = with_library_variables(text, "TV Shows", {"sep_style": "blue", "collection_mode": "hide"})
    assert with_vars == "libraries:\n  TV Shows:\n    template_variables:\n      sep_style: blue\n      collection_mode: hide\n"
    assert with_library_variables(with_vars, "TV Shows", {}) in ("libraries:\n  TV Shows: {}\n", "libraries:\n  TV Shows:\n")


def make_client(tmp_path, kometa):
    settings = Settings(
        data_dir=kometa / "config" / ".studio", kometa_config=kometa / "config" / "config.yml", kometa_entry=kometa / "kometa.py", kometa_python=Path(sys.executable)
    )
    return TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000))


def test_the_gallery_through_the_api(tmp_path, kometa):
    config = kometa / "config" / "config.yml"
    with make_client(tmp_path, kometa) as client:
        catalogue = client.get("/api/v1/config/defaults").json()
        on = client.put("/api/v1/config/libraries/TV Shows/defaults/collection/network", json={"template_variables": {"sep_style": "blue"}})
        overlay = client.put("/api/v1/config/libraries/TV Shows/defaults/overlay/resolution", json={})
        unknown = client.put("/api/v1/config/libraries/TV Shows/defaults/collection/flixpatrol", json={})
        library = client.get("/api/v1/config/libraries/TV Shows").json()
        off = client.delete("/api/v1/config/libraries/Movies/defaults/collection/basic")
        variables = client.put("/api/v1/config/libraries/Movies/template-variables", json={"template_variables": {"collection_mode": "hide"}})
        backups = client.get("/api/v1/backups").json()["backups"]
    assert {entry["name"] for entry in catalogue["collections"]} >= {"basic", "network", "decade"}
    assert on.status_code == 200 and overlay.status_code == 200
    assert unknown.status_code == 404
    assert [(ref["kind"], ref["value"], ref["template_variables"]) for ref in library["collection_files"]] == [("default", "network", {"sep_style": "blue"})]
    assert [ref["value"] for ref in library["overlay_files"]] == ["resolution"]
    assert off.status_code == 200 and variables.status_code == 200
    text = config.read_text()
    assert "- default: basic" not in text and "      - default: streaming\n" in text and "region: GB   # where we are" in text
    assert "    template_variables:\n      collection_mode: hide\n" in text
    assert [backup["reason"] for backup in backups][:3] == ["Set the template variables for Movies", "Turned off the basic default for Movies", "Set the resolution default for TV Shows"]
