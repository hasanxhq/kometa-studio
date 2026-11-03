import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from fakeplex import SERVER_TOKEN, FakePlex
from kometa_studio.plex_library import PlexServer
from kometa_studio.ready_made import (
    DYNAMIC_TYPE_SOURCES,
    Category,
    Entry,
    categories,
    count,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "ready_made_defaults"
REAL_KOMETA_ROOT = Path(__file__).parent.parent / "kometa"


@pytest.fixture
def plex_server():
    fake = FakePlex()
    client = httpx.AsyncClient(transport=fake.transport())
    server = PlexServer(client, "https://203-0-113-7.abc123.plex.direct:32400", SERVER_TOKEN)
    return fake, server


def test_type_to_source_table_completeness():
    """Verify that key dynamic types from meta.py are defined and classified."""
    # File-based
    for t in ("custom", "number", "imdb_awards"):
        assert DYNAMIC_TYPE_SOURCES[t].source == "file"
        assert DYNAMIC_TYPE_SOURCES[t].listable is True

    # Plex-based
    for t in ("genre", "decade", "year", "content_rating", "studio", "country", "network", "resolution", "audio_language", "subtitle_language"):
        assert DYNAMIC_TYPE_SOURCES[t].source == "plex"
        assert DYNAMIC_TYPE_SOURCES[t].tag is not None
        assert DYNAMIC_TYPE_SOURCES[t].listable is True

    # Unlistable / external
    for t in ("tmdb_collection", "actor", "director", "producer", "writer", "origin_country", "original_language"):
        assert DYNAMIC_TYPE_SOURCES[t].listable is False
        assert bool(DYNAMIC_TYPE_SOURCES[t].reason)


def test_categories_on_fixtures_for_movie():
    cats = categories(FIXTURES_ROOT, "movie")
    cat_by_name = {c.name: c for c in cats}

    # Separators must never be offered as categories
    assert "separator_chart" not in cat_by_name
    assert "separator_award" not in cat_by_name

    # Network in show/ must not appear for movie
    assert "network" not in cat_by_name

    # Basic charts: fixed, static entry present, separator collection dropped
    basic = cat_by_name["basic"]
    assert basic.group == "chart"
    assert basic.kind == "fixed"
    assert basic.listable is True
    assert basic.reason is None
    assert basic.title == "Basic Charts"
    assert len(basic.collections) == 1
    assert basic.collections[0] == Entry(
        block="",
        key="Newly Released",
        kometa_name="Newly Released",
        title="Newly Released",
    )

    # Collectionless: helper kind
    colless = cat_by_name["collectionless"]
    assert colless.group == "both"
    assert colless.kind == "helper"
    assert colless.listable is True
    assert len(colless.collections) == 1
    assert colless.collections[0].kometa_name == "Collectionless"

    # Oscars: award kind, static + yearly imdb_awards dynamic
    oscars = cat_by_name["oscars"]
    assert oscars.group == "award"
    assert oscars.kind == "award"
    assert oscars.listable is True
    curr_year = datetime.now().year
    expected_years = [str(curr_year - 2), str(curr_year - 1), str(curr_year)]
    assert oscars.collections[0] == Entry(
        block="",
        key="Oscars Best Picture",
        kometa_name="Oscars Best Picture",
        title="Oscars Best Picture",
    )
    award_entries = oscars.collections[1:]
    assert [e.key for e in award_entries] == expected_years
    for e in award_entries:
        assert e.block == "Oscars Winners"
        assert e.kometa_name == f"Oscars Winners {e.key}"
        assert e.title == f"Oscars Winners {e.key}"

    # Streaming: custom-data dynamic entries
    streaming = cat_by_name["streaming"]
    assert streaming.group == "both"
    assert streaming.kind == "per_value"
    assert streaming.listable is True
    # hayu has allowed_libraries: show, so excluded from movie
    assert len(streaming.collections) == 2
    assert streaming.collections[0] == Entry(
        block="Streaming",
        key="netflix",
        kometa_name="Netflix Movies",
        title="Netflix Movies",
    )
    assert streaming.collections[1] == Entry(
        block="Streaming",
        key="disney",
        kometa_name="Disney+ Movies",
        title="Disney+ Movies",
    )

    # Genre: Plex-typed, empty collections in categories()
    genre = cat_by_name["genre"]
    assert genre.group == "both"
    assert genre.kind == "per_value"
    assert genre.listable is True
    assert genre.collections == []

    # Director: unlistable with plain reason
    director = cat_by_name["director"]
    assert director.group == "movie"
    assert director.kind == "per_value"
    assert director.listable is False
    assert director.reason == "Requires scanning the library and ranking directors by appearances"
    assert director.collections == []


def test_categories_on_fixtures_for_show():
    cats = categories(FIXTURES_ROOT, "show")
    cat_by_name = {c.name: c for c in cats}

    # Director in movie/ must not appear for show
    assert "director" not in cat_by_name

    # Network in show/ appears
    assert "network" in cat_by_name
    network = cat_by_name["network"]
    assert network.group == "show"
    assert network.kind == "per_value"
    assert network.listable is True
    assert network.collections == []

    # Streaming in show includes hayu
    streaming = cat_by_name["streaming"]
    keys = [e.key for e in streaming.collections]
    assert "hayu" in keys
    hayu_entry = next(e for e in streaming.collections if e.key == "hayu")
    assert hayu_entry.kometa_name == "hayu Shows"


@pytest.mark.anyio
async def test_count_on_fixtures(plex_server):
    fake, server = plex_server
    counted = await count(server, "1", "movie", FIXTURES_ROOT)
    cat_by_name = {c.name: c for c in counted}

    # Genre collections populated and counted
    genre = cat_by_name["genre"]
    assert genre.listable is True
    genre_keys = {e.key: e for e in genre.collections}
    assert "Action" in genre_keys
    assert genre_keys["Action"].items == 5
    assert genre_keys["Action"].kometa_name == "Action Movies"
    assert "Sci-Fi" in genre_keys
    assert genre_keys["Sci-Fi"].items == 2
    assert "Drama" in genre_keys
    assert genre_keys["Drama"].items == 1

    # Content Rating: test exclude, addons, include, empty value dropping
    # Config has:
    #   addons: G -> [TV-G]
    #   exclude: [R]
    #   include: [G, PG-13, EmptyRating]
    # FakePlex has counts: G=1, TV-G=2, PG-13=3, R=1, EmptyRating=0
    cr = cat_by_name["content_rating"]
    cr_keys = {e.key: e for e in cr.collections}
    # R is excluded
    assert "R" not in cr_keys
    # TV-G is an addon under G, not its own collection
    assert "TV-G" not in cr_keys
    # EmptyRating had 0 items, so dropped
    assert "EmptyRating" not in cr_keys
    # G has 1 (G) + 2 (TV-G) = 3 items
    assert "G" in cr_keys
    assert cr_keys["G"].items == 3
    assert cr_keys["G"].kometa_name == "G Movies"
    # PG-13 has 3 items
    assert "PG-13" in cr_keys
    assert cr_keys["PG-13"].items == 3
    assert cr_keys["PG-13"].kometa_name == "PG-13 Movies"


@pytest.mark.anyio
async def test_count_skips_counting_items_when_more_than_60_values(plex_server, tmp_path):
    fake, server = plex_server
    # Create a fixture with > 60 values
    genre_file = tmp_path / "defaults" / "both" / "genre.yml"
    genre_file.parent.mkdir(parents=True)
    genre_file.write_text("dynamic_collections:\n  Genre:\n    type: genre\n    title_format: '<<key_name>>'\n")

    # Set FakePlex to return 65 genre tags
    fake.TAGS["1"]["genre"] = [{"key": f"Genre{i}", "title": f"Genre{i}"} for i in range(65)]

    counted = await count(server, "1", "movie", tmp_path)
    cat = next(c for c in counted if c.name == "genre")
    assert len(cat.collections) == 65
    # When > 60 values, items count is skipped (None)
    for e in cat.collections:
        assert e.items is None


def test_real_kometa_defaults_categories():
    defaults_folder = REAL_KOMETA_ROOT / "defaults"
    if not defaults_folder.is_dir():
        pytest.skip("kometa/defaults not present")

    cats = categories(REAL_KOMETA_ROOT, "movie")
    names = [c.name for c in cats]

    # Exactly every default except the two separators appears for movies
    assert "separator_chart" not in names
    assert "separator_award" not in names
    assert len(cats) == 54

    # No listable entry has an empty kometa_name
    for cat in cats:
        if cat.listable:
            for entry in cat.collections:
                assert bool(entry.kometa_name), f"Empty kometa_name in {cat.name}: {entry}"


@pytest.mark.anyio
async def test_real_kometa_defaults_count(plex_server):
    defaults_folder = REAL_KOMETA_ROOT / "defaults"
    if not defaults_folder.is_dir():
        pytest.skip("kometa/defaults not present")

    fake, server = plex_server
    counted = await count(server, "1", "movie", REAL_KOMETA_ROOT)
    names = [c.name for c in counted]

    assert "separator_chart" not in names
    assert "separator_award" not in names
    assert len(counted) == 54

    for cat in counted:
        if cat.listable:
            for entry in cat.collections:
                assert bool(entry.kometa_name), f"Empty kometa_name in {cat.name}: {entry}"

    # Verify Plex-valued categories have populated entries with items
    cat_by_name = {c.name: c for c in counted}
    genre = cat_by_name["genre"]
    assert len(genre.collections) > 0
    assert all(e.items is not None and e.items > 0 for e in genre.collections)

    resolution = cat_by_name["resolution"]
    assert len(resolution.collections) > 0
    assert all(e.items is not None and e.items > 0 for e in resolution.collections)
