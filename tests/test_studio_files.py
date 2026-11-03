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
    relative_path,
    render,
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
    assert first is not None
    genre_path = config / "studio" / "Movies" / "genre.yml"
    imdb_path = config / "studio" / "Movies" / "imdb.yml"
    assert genre_path.is_file() and imdb_path.is_file()
    config_text = (config / "config.yml").read_text()
    assert "studio/Movies/genre.yml" in config_text
    assert "studio/Movies/imdb.yml" in config_text
    assert len(first["files"]) >= 2

    second = asyncio.run(
        write_library(writer, kometa_root, "Movies", "movie", picks, ["Movies"], "Studio picks again")
    )
    assert second is None

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
    assert cleared is not None
    config_text = (config / "config.yml").read_text()
    assert "studio/Movies/genre.yml" in config_text
    assert "studio/Movies/imdb.yml" not in config_text
    assert imdb_path.is_file()  # ConfigWriter doesn't delete files


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
