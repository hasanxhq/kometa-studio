"""Studio-generated Kometa collection files."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from kometa_studio.collections import Ref
from kometa_studio.config_write import ConfigWriter, SaveRefused
from kometa_studio.settings import Settings
from kometa_studio.studio_files import (
    default_file,
    library_folders,
    hand_edited,
    record,
    relative_path,
    render,
    render_built,
    write_library,
)

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
FIXTURES = Path(__file__).parent / "fixtures" / "studio_defaults"
REAL_DEFAULTS = Path(__file__).resolve().parents[1] / "kometa" / "defaults"
if not REAL_DEFAULTS.is_dir():
    REAL_DEFAULTS = Path("/home/hasan/starrstudio/kometa/defaults")


def parse(text: str) -> dict:
    return YAML(typ="safe").load(text)


def test_library_folders_are_safe_and_disambiguated():
    assert library_folders(["Movies", "TV Shows"]) == {"Movies": "Movies", "TV Shows": "TV Shows"}
    assert library_folders(["A/B", "A:B", "Z"]) == {"A/B": "A_B", "A:B": "A_B-2", "Z": "Z"}
    assert relative_path("A/B", "genre", ["A/B", "A:B"]) == "studio/A_B/genre.yml"
    assert relative_path("A:B", "genre", ["A/B", "A:B"]) == "studio/A_B-2/genre.yml"


def test_render_static_only_fixture():
    text = render(
        (FIXTURES / "static_only.yml").read_text(),
        "static_only",
        [Ref("static_only", "", "Popular")],
    )
    assert text is not None
    assert text.startswith("# Written by Kometa Studio from Kometa's \"static_only\" default.")
    data = parse(text)
    assert data["external_templates"]["template_variables"]["use_separator"] is False
    assert "Chart Separator" not in data["collections"]
    assert set(data["collections"]) == {"Popular"}
    assert data["collections"]["Popular"]["append_label"] == "Studio"
    assert "radarr_add_missing" not in data["collections"]["Popular"]
    assert data["templates"]["studio_label"] == {"label": "Studio"}
    assert "dynamic_collections" not in data


def test_render_dynamic_sync_fixture():
    text = render(
        (FIXTURES / "dynamic_sync.yml").read_text(),
        "dynamic_sync",
        [Ref("dynamic_sync", "Genre", "Action"), Ref("dynamic_sync", "Genre", "Comedy")],
    )
    assert text is not None
    data = parse(text)
    assert "collections" not in data  # separator dropped, nothing else static
    block = data["dynamic_collections"]["Genre"]
    assert block["include"] == ["Action", "Comedy"]
    assert "sync" not in block
    assert block["exclude"] == ["Talk-Show", "Reality"]
    assert block["addons"] == {"Action": ["Adventure"]}
    assert "sonarr_add_missing" not in block
    assert block["template"][-1] == "studio_label"
    assert data["templates"]["studio_label"]["label"] == "Studio"


def test_render_award_both_fixture():
    text = render(
        (FIXTURES / "award_both.yml").read_text(),
        "award_both",
        [
            Ref("award_both", "", "Best Picture"),
            Ref("award_both", "Oscars Years", "2024"),
            Ref("award_both", "Oscars Years", "2023"),
        ],
    )
    assert text is not None
    data = parse(text)
    assert set(data["collections"]) == {"Best Picture"}
    assert "Oscars Separator" not in data.get("collections", {})
    assert data["collections"]["Best Picture"]["append_label"] == ["Awards", "Studio"]
    years = data["dynamic_collections"]["Oscars Years"]
    assert years["include"] == ["2023", "2024"]
    assert "sync" not in years
    assert "studio_label" in years["template"][-1] or years["template"][-1] == "studio_label"


def test_render_returns_none_when_nothing_kept():
    assert render((FIXTURES / "static_only.yml").read_text(), "static_only", []) is None
    assert (
        render(
            (FIXTURES / "static_only.yml").read_text(),
            "static_only",
            [Ref("static_only", "", "Chart Separator")],
        )
        is None
    )


@pytest.mark.skipif(not REAL_DEFAULTS.is_dir(), reason="kometa/defaults not present")
def test_render_real_imdb_and_genre_defaults():
    imdb = (REAL_DEFAULTS / "chart" / "imdb.yml").read_text()
    text = render(imdb, "imdb", [Ref("imdb", "", "IMDb Popular"), Ref("imdb", "", "IMDb Top 250")])
    assert text is not None
    data = parse(text)
    assert set(data["collections"]) == {"IMDb Popular", "IMDb Top 250"}
    assert data["external_templates"]["template_variables"]["use_separator"] is False
    for name in data["collections"]:
        assert data["collections"][name]["append_label"] == "Studio"

    genre = (REAL_DEFAULTS / "both" / "genre.yml").read_text()
    text = render(genre, "genre", [Ref("genre", "Genre", "Action"), Ref("genre", "Genre", "Drama")])
    assert text is not None
    data = parse(text)
    assert "Genre Collections" not in data.get("collections", {})
    assert data["dynamic_collections"]["Genre"]["include"] == ["Action", "Drama"]
    assert "sync" not in data["dynamic_collections"]["Genre"]
    assert data["dynamic_collections"]["Genre"]["template"][-1] == "studio_label"


@pytest.mark.skipif(not REAL_DEFAULTS.is_dir(), reason="kometa/defaults not present")
def test_default_file_order_matches_kometa():
    root = REAL_DEFAULTS.parent
    assert default_file(root, "imdb", "movie") == REAL_DEFAULTS / "chart" / "imdb.yml"
    assert default_file(root, "genre", "show") == REAL_DEFAULTS / "both" / "genre.yml"
    assert default_file(root, "decade", "movie") == REAL_DEFAULTS / "movie" / "decade.yml"
    assert default_file(root, "decade", "show") == REAL_DEFAULTS / "show" / "decade.yml"
    assert default_file(root, "oscars", "movie") == REAL_DEFAULTS / "award" / "oscars.yml"
    assert default_file(root, "missing-default", "movie") is None


CONFIG = """\
libraries:
  Movies:
    collection_files:
      - file: config/Movies.yml
plex:
  url: http://plex:32400
  token: real-plex-token
"""
MOVIES = "collections:\n  Trending:\n    tmdb_trending_weekly: 30\n"


@pytest.fixture
def writer_env(tmp_path: Path):
    """ConfigWriter over a fake Kometa install with a Movies library."""
    root = tmp_path / "kometa"
    config = root / "config"
    (config / "logs").mkdir(parents=True)
    (config / "config.yml").write_text(CONFIG)
    (config / "Movies.yml").write_text(MOVIES)
    (config / "fake.json").write_text("{}")
    defaults = root / "defaults" / "both"
    defaults.mkdir(parents=True)
    (defaults / "genre.yml").write_text((FIXTURES / "dynamic_sync.yml").read_text())
    chart = root / "defaults" / "chart"
    chart.mkdir(parents=True)
    (chart / "imdb.yml").write_text((FIXTURES / "static_only.yml").read_text())
    settings = Settings(
        data_dir=config / ".studio",
        kometa_config=config / "config.yml",
        kometa_entry=FAKE_KOMETA,
        kometa_python=Path(sys.executable),
    )
    return ConfigWriter(settings), root, config


def test_write_library_one_save_idempotent_and_removes_entry(writer_env):
    writer, kometa_root, config = writer_env
    picks = {
        "genre": [Ref("genre", "Genre", "Action"), Ref("genre", "Genre", "Comedy")],
        "imdb": [Ref("imdb", "", "Popular")],
    }

    first = asyncio.run(
        write_library(writer, kometa_root, "Movies", "movie", picks, ["Movies"], "Studio picks")
    )
    assert first.saved is not None
    genre_path = config / "studio" / "Movies" / "genre.yml"
    imdb_path = config / "studio" / "Movies" / "imdb.yml"
    assert genre_path.is_file() and imdb_path.is_file()
    config_text = (config / "config.yml").read_text()
    assert "studio/Movies/genre.yml" in config_text
    assert "studio/Movies/imdb.yml" in config_text
    assert len(first.saved["files"]) >= 2
    assert set(first.generated) == {"studio/Movies/genre.yml", "studio/Movies/imdb.yml"}

    second = asyncio.run(
        write_library(writer, kometa_root, "Movies", "movie", picks, ["Movies"], "Studio picks again")
    )
    assert second.saved is None
    assert second.generated == first.generated  # unchanged files still report what Studio's text is

    cleared = asyncio.run(
        write_library(
            writer,
            kometa_root,
            "Movies",
            "movie",
            {"genre": picks["genre"], "imdb": []},
            ["Movies"],
            "Dropped imdb",
        )
    )
    assert cleared.saved is not None
    config_text = (config / "config.yml").read_text()
    assert "studio/Movies/genre.yml" in config_text
    assert "studio/Movies/imdb.yml" not in config_text
    # The file of a category with no picks left goes, backed up like any save.
    assert not imdb_path.exists()
    assert cleared.removed == ["studio/Movies/imdb.yml"] and cleared.saved["removed"] == ["studio/Movies/imdb.yml"]
    backup = config / ".studio" / "backups" / cleared.saved["backup"] / "studio" / "Movies" / "imdb.yml"
    assert backup.is_file()


def test_write_library_missing_default_refused(writer_env):
    writer, kometa_root, _ = writer_env
    with pytest.raises(SaveRefused) as raised:
        asyncio.run(
            write_library(
                writer,
                kometa_root,
                "Movies",
                "movie",
                {"nope": [Ref("nope", "", "X")]},
                ["Movies"],
                "missing",
            )
        )
    assert raised.value.status == 409


def test_write_library_keeps_files_studio_didnt_write(writer_env):
    writer, kometa_root, config = writer_env
    folder = config / "studio" / "Movies"
    folder.mkdir(parents=True)
    (folder / "mine.yml").write_text("collections:\n  Mine:\n    plex_all: true\n")
    written = asyncio.run(
        write_library(writer, kometa_root, "Movies", "movie", {"genre": [Ref("genre", "Genre", "Action")]}, ["Movies"], "picks")
    )
    assert (folder / "mine.yml").is_file() and written.removed == []


def test_render_built_writes_file_or_url_poster():
    base = {
        "filters": {"match": "all", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}]},
        "sort_by": None,
        "limit": None,
        "visible": {"library": True, "home": False, "shared": False},
        "minimum_items": 1,
    }
    none = parse(render_built([("No Poster", base)]))
    assert "file_poster" not in none["collections"]["No Poster"]
    assert "url_poster" not in none["collections"]["No Poster"]

    file_def = {**base, "poster": {"kind": "file", "path": "studio/posters/abcd1234abcd1234.png"}}
    with_file = parse(render_built([("File", file_def)], file_ref=lambda p: f"config/{p}"))
    assert with_file["collections"]["File"]["file_poster"] == "config/studio/posters/abcd1234abcd1234.png"
    assert "url_poster" not in with_file["collections"]["File"]

    url_def = {**base, "poster": {"kind": "url", "url": "https://example.com/p.jpg"}}
    with_url = parse(render_built([("Url", url_def)]))
    assert with_url["collections"]["Url"]["url_poster"] == "https://example.com/p.jpg"
    assert "file_poster" not in with_url["collections"]["Url"]


def test_hand_edits_are_noticed_and_replaced_on_the_next_save(writer_env):
    from kometa_studio import db as studio_db

    writer, kometa_root, config = writer_env
    (config / ".studio").mkdir(exist_ok=True)
    database = studio_db.open_database(config / ".studio" / "studio.db")
    picks = {"genre": [Ref("genre", "Genre", "Action")]}
    written = asyncio.run(write_library(writer, kometa_root, "Movies", "movie", picks, ["Movies"], "picks"))
    with database:
        record(database, written)
    assert hand_edited(database, config) == []

    genre = config / "studio" / "Movies" / "genre.yml"
    original = genre.read_text()
    genre.write_text(original + "# my own note\n")
    assert hand_edited(database, config) == ["studio/Movies/genre.yml"]
    assert hand_edited(database, config, "Movies", ["Movies"]) == ["studio/Movies/genre.yml"]
    assert hand_edited(database, config, "TV Shows", ["Movies", "TV Shows"]) == []

    again = asyncio.run(write_library(writer, kometa_root, "Movies", "movie", picks, ["Movies"], "picks again"))
    with database:
        record(database, again)
    assert genre.read_text() == original
    assert hand_edited(database, config) == []
