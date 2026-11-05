import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ruamel.yaml import YAML

from starr_studio.app import create_app
from starr_studio.config_sections import with_library_default, with_library_variables, with_overlay_order
from starr_studio.kometa_files import ConfigReader, _overlay_layout
from starr_studio.settings import Settings

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
        "name": "basic", "group": "chart", "types": ["movie", "show"], "title": "Basic Charts Collections", "docs_url": "https://kometa.wiki/en/latest/defaults/chart/basic", "toggles": [],
    }
    assert (collections["decade"]["group"], collections["decade"]["types"]) == ("both", ["movie", "show"])  # in movie/ and show/
    assert (collections["network"]["group"], collections["network"]["types"]) == ("show", ["show"])
    assert [(o["name"], o["types"]) for o in catalogue["overlays"]] == [("content_rating_us_movie", ["movie"]), ("resolution", ["movie", "show"])]


def test_toggles_come_from_the_default_itself(kometa):
    defaults = kometa / "defaults"
    (defaults / "chart" / "basic.yml").write_text(
        "collections:\n"
        "  Newly Released:\n    variables: {key: released}\n    template: [name: smart_filter, name: shared]\n"
        "  Hidden Gem:\n    variables: {key: gem}\n    template:\n      - name: shared\n        use_gem: false\n"
        "  Basic Separator:\n    template: {name: separator}\n"  # no shared template: no use_<key>
    )
    (defaults / "both" / "streaming.yml").write_text("dynamic_collections:\n  Streaming:\n    type: custom\n    data: {netflix: Netflix, disney: Disney+}\n    template: [streaming, shared]\n")
    (defaults / "movie" / "decade.yml").write_text("dynamic_collections:\n  Decade:\n    type: decade\n    template: [shared]\n")  # from the library at run time
    (defaults / "show" / "decade.yml").write_text("dynamic_collections:\n  Decade:\n    type: custom\n    data: {old: Old shows}\n    template: [shared]\n")
    (defaults / "overlays" / "resolution.yml").write_text("templates:\n  x:\n    optional: [use_<<key>>]\noverlays:\n  Netflix:\n    variables: {key: netflix}\n    template: [name: standard]\n")

    catalogue = ConfigReader(kometa / "config" / "config.yml", kometa).catalogue()
    collections = {entry["name"]: entry["toggles"] for entry in catalogue["collections"]}
    both = ["movie", "show"]
    assert collections["basic"] == [{"key": "released", "label": "Newly Released", "on": True, "types": both}, {"key": "gem", "label": "Hidden Gem", "on": False, "types": both}]
    assert [t["key"] for t in collections["streaming"]] == ["netflix", "disney"]
    assert collections["decade"] == [{"key": "old", "label": "Old shows", "on": True, "types": ["show"]}]  # only show/ lists any
    assert catalogue["overlays"][1]["toggles"] == [{"key": "netflix", "label": "Netflix", "on": True, "types": both}]


@pytest.mark.parametrize(
    "overlays",
    [
        "  Plain:\n    variables: {key: 4k}\n",  # the file has no use_<key>
        "  A:\n    variables: {key: a}\n  B:\n    variables: {key: 200}\n",  # not every overlay has a key: Network's use_ variables are elsewhere
        "  A:\n    variables: {key: 4k, alt: hdr}\n",  # use_<key>_<alt>
    ],
)
def test_overlays_without_one_list_of_switches_have_no_toggles(kometa, overlays):
    use = "" if "Plain" in overlays else "templates:\n  x:\n    optional: [use_<<key>>]\n"
    (kometa / "defaults" / "overlays" / "resolution.yml").write_text(f"{use}overlays:\n{overlays}")
    catalogue = ConfigReader(kometa / "config" / "config.yml", kometa).catalogue()
    assert catalogue["overlays"][1]["toggles"] == []


def test_overlays_on_kometas_standard_template_have_toggles(kometa):
    (kometa / "defaults" / "overlays" / "resolution.yml").write_text("overlays:\n  Airing:\n    variables: {key: airing, weight: 100}\n    template: [name: standard, name: status]\n")
    catalogue = ConfigReader(kometa / "config" / "config.yml", kometa).catalogue()
    assert [(t["key"], t["label"]) for t in catalogue["overlays"][1]["toggles"]] == [("airing", "Airing")]


def test_a_long_list_of_toggles_is_left_out(kometa):
    data = "".join(f"      k{n}: Name {n}\n" for n in range(61))
    (kometa / "defaults" / "both" / "streaming.yml").write_text(f"dynamic_collections:\n  Many:\n    type: custom\n    template: [shared]\n    data:\n{data}")
    catalogue = ConfigReader(kometa / "config" / "config.yml", kometa).catalogue()
    assert next(e for e in catalogue["collections"] if e["name"] == "streaming")["toggles"] == []


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


# --- the overlay designer -----------------------------------------------------------

ALIGNED = """
external_templates:
  default: templates
  template_variables:
    default:
      horizontal_align: center
      vertical_align: top
      style: compact
    conditionals:
      vertical_offset:
        default: 15
        conditions:
          - vertical_align: center
            value: 0
      back_height:
        default: 105
    group: audio_codec
    back_color: "#00000099"
    back_width: <<width>>

overlays:
  a: {}
"""

POSITIONED = """
templates:
  Rating:
    default:
      back_color: "#00000099"
      back_radius: 30
      horizontal_position: left
      vertical_position: center

overlays:
  a: {}
"""


def test_an_overlay_default_says_where_it_starts_and_what_moves_it():
    layout = _overlay_layout(ALIGNED)
    assert layout["moved_by"] == "align"
    assert layout["variables"] == {"horizontal_align": "center", "vertical_align": "top", "back_color": "#00000099"}  # <<width>> isn't a value
    assert layout["conditionals"] == {
        "vertical_offset": {"default": 15, "conditions": [{"vertical_align": "center", "value": 0}]},
        "back_height": {"default": 105, "conditions": []},
    }


def test_ratings_place_themselves_from_position_variables():
    layout = _overlay_layout(POSITIONED)
    assert layout["moved_by"] == "position"
    assert layout["variables"] == {"horizontal_position": "left", "vertical_position": "center", "back_color": "#00000099", "back_radius": 30}


def test_a_default_with_no_layout_still_lists():
    assert _overlay_layout("not: [valid") == {"moved_by": "align", "variables": {}, "conditionals": {}}


OVERLAYS = """libraries:
  Movies:
    overlay_files:
      - default: resolution  # first
        template_variables:
          horizontal_align: right
      - file: config/mine.yml
      - default: ribbon
      - default: ratings
"""


def test_overlay_order_moves_only_the_defaults():
    moved = with_overlay_order(OVERLAYS, "Movies", ["ratings", "resolution", "ribbon"])
    data = YAML(typ="safe").load(moved)["libraries"]["Movies"]["overlay_files"]
    assert [entry.get("default") or entry["file"] for entry in data] == ["ratings", "config/mine.yml", "resolution", "ribbon"]
    assert data[2]["template_variables"] == {"horizontal_align": "right"}


def test_overlay_order_keeps_a_default_listed_twice_together():
    text = "libraries:\n  Movies:\n    overlay_files:\n      - default: ratings\n      - default: ribbon\n      - default: ratings\n"
    data = YAML(typ="safe").load(with_overlay_order(text, "Movies", ["ribbon", "ratings"]))["libraries"]["Movies"]["overlay_files"]
    assert [entry["default"] for entry in data] == ["ribbon", "ratings", "ratings"]


@pytest.mark.parametrize("names", [["ratings", "ribbon"], ["ratings", "resolution", "ribbon", "status"], ["ratings", "ratings", "ribbon"]])
def test_overlay_order_refuses_a_list_that_isnt_the_librarys(names):
    with pytest.raises(ValueError, match="have changed"):
        with_overlay_order(OVERLAYS, "Movies", names)


def test_overlay_order_through_the_api(tmp_path, kometa):
    config = kometa / "config" / "config.yml"
    config.write_text("libraries:\n  Movies:\n    overlay_files:\n      - default: resolution\n      - default: ribbon\n")
    with make_client(tmp_path, kometa) as client:
        assert client.put("/api/v1/config/libraries/Movies/overlay-order", json={"names": ["ribbon", "resolution"]}).status_code == 200
        assert YAML(typ="safe").load(config.read_text())["libraries"]["Movies"]["overlay_files"] == [{"default": "ribbon"}, {"default": "resolution"}]
        stale = client.put("/api/v1/config/libraries/Movies/overlay-order", json={"names": ["ribbon"]})
        assert stale.status_code == 409
        assert "have changed" in stale.text
