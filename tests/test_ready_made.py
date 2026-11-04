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

    # People: ranked from Plex's credits
    for t in ("actor", "director", "producer", "writer"):
        assert DYNAMIC_TYPE_SOURCES[t].source == "people"
        assert DYNAMIC_TYPE_SOURCES[t].listable is True

    # TMDb: every title looked up, as Kometa does
    for t in ("tmdb_collection", "origin_country", "original_language"):
        assert DYNAMIC_TYPE_SOURCES[t].source == "tmdb"
        assert DYNAMIC_TYPE_SOURCES[t].listable is True

    # Unlistable / external
    for t in ("tmdb_popular_people", "letterboxd_user_lists", "edition", "episode_year"):
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

    # Director: listable, expanded by count() from Plex's credits
    director = cat_by_name["director"]
    assert director.group == "movie"
    assert director.kind == "per_value"
    assert director.listable is True
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


AUDIO_DEFAULT = """dynamic_collections:
  Audio Language:
    type: audio_language
    title_format: <<key_name>> Audio
    include:
      - en
      - fr
      - ko
"""
NAMES = {"en": "English", "fr": "French", "ko": "Korean"}


def _audio_default(root: Path) -> Path:
    path = root / "defaults" / "both" / "audio_language.yml"
    path.parent.mkdir(parents=True)
    path.write_text(AUDIO_DEFAULT)
    return root


@pytest.mark.anyio
async def test_count_names_languages_as_kometa_does(plex_server, tmp_path):
    # Plex titles a language in itself ("Français"); Kometa uses TMDb's English name for the key.
    fake, server = plex_server
    fake.TAGS["1"]["audioLanguage"] = [{"key": "en", "title": "English"}, {"key": "fr", "title": "Français"}, {"key": "ko", "title": "한국어"}]
    fake.TAG_COUNTS["1"][("audioLanguage", "ko")] = 2
    counted = await count(server, "1", "movie", _audio_default(tmp_path), NAMES)
    cat = next(c for c in counted if c.name == "audio_language")
    assert cat.count_error is None
    assert {e.key: e.kometa_name for e in cat.collections} == {"en": "English Audio", "fr": "French Audio", "ko": "Korean Audio"}
    assert {e.key: e.title for e in cat.collections}["fr"] == "French Audio"


@pytest.mark.anyio
async def test_count_falls_back_to_plex_title_for_keys_tmdb_lacks(plex_server, tmp_path):
    fake, server = plex_server
    fake.TAGS["1"]["audioLanguage"] = [{"key": "fr", "title": "Français"}]
    counted = await count(server, "1", "movie", _audio_default(tmp_path), {"en": "English"})
    cat = next(c for c in counted if c.name == "audio_language")
    assert [e.kometa_name for e in cat.collections] == ["Français Audio"]


@pytest.mark.anyio
async def test_count_without_language_names_says_why(plex_server, tmp_path):
    fake, server = plex_server
    counted = await count(server, "1", "movie", _audio_default(tmp_path), None)
    cat = next(c for c in counted if c.name == "audio_language")
    assert cat.collections == []
    assert "TMDb" in (cat.count_error or "")


@pytest.mark.anyio
async def test_count_reads_show_languages_from_episodes(plex_server, tmp_path):
    # In a show library Kometa lists and filters these by episode (episode.audioLanguage).
    fake, server = plex_server
    fake.TAGS["2"]["audioLanguage"] = [{"key": "en", "title": "English"}, {"key": "fr", "title": "Français"}]
    fake.TAG_COUNTS["2"][("episode.audioLanguage", "en")] = 4
    fake.TAG_COUNTS["2"][("episode.audioLanguage", "fr")] = 1
    counted = await count(server, "2", "show", _audio_default(tmp_path), NAMES)
    cat = next(c for c in counted if c.name == "audio_language")
    assert {e.kometa_name: e.items for e in cat.collections} == {"English Audio": 4, "French Audio": 1}
    listing = [r for r in fake.requests if r.url.path.endswith("/library/sections/2/audioLanguage")]
    assert listing and all(r.url.params.get("type") == "4" for r in listing)
    counts = [r for r in fake.requests if r.url.path.endswith("/library/sections/2/all")]
    assert counts and all("episode.audioLanguage" in r.url.params for r in counts)


PEOPLE_DEFAULT = """dynamic_collections:
  Top Directors:
    type: director
    data:
      depth: 5
      limit: 25
    title_format: <<key_name>> (Director)
"""


@pytest.mark.anyio
async def test_count_ranks_people_from_credits(plex_server, tmp_path):
    from kometa_studio.plex_people import PeopleScan

    fake, server = plex_server
    path = tmp_path / "kometa" / "defaults" / "movie" / "director.yml"
    path.parent.mkdir(parents=True)
    path.write_text(PEOPLE_DEFAULT)
    scan = PeopleScan(server, tmp_path / "data")
    counted = await count(server, "1", "movie", tmp_path / "kometa", None, scan)
    director = next(c for c in counted if c.name == "director")
    assert director.count_error is None
    # limit given, so the minimum is 1: both directors, the most frequent first.
    assert [(e.key, e.kometa_name, e.items) for e in director.collections] == [
        ("Denis Villeneuve", "Denis Villeneuve (Director)", 2),
        ("Michael Mann", "Michael Mann (Director)", 1),
    ]
    # Credits are kept, and read again only for titles Plex has changed.
    fetched = [r for r in fake.requests if r.url.path.startswith("/library/metadata/")]
    assert len(fetched) == 3
    again = await count(server, "1", "movie", tmp_path / "kometa", None, PeopleScan(server, tmp_path / "data"))
    assert [e.key for e in next(c for c in again if c.name == "director").collections] == ["Denis Villeneuve", "Michael Mann"]
    assert len([r for r in fake.requests if r.url.path.startswith("/library/metadata/")]) == 3


@pytest.mark.anyio
async def test_count_without_a_people_scan_says_why(plex_server, tmp_path):
    fake, server = plex_server
    path = tmp_path / "defaults" / "movie" / "director.yml"
    path.parent.mkdir(parents=True)
    path.write_text(PEOPLE_DEFAULT)
    counted = await count(server, "1", "movie", tmp_path, None, None)
    director = next(c for c in counted if c.name == "director")
    assert director.collections == [] and "credits" in (director.count_error or "")


FRANCHISE_DEFAULT = """dynamic_collections:
  TMDb Collections:
    type: tmdb_collection
    remove_suffix: "Collection"
    custom_keys: false
    addons:
      8091:
        - 135416
    title_override:
      10: "Star Wars: Skywalker Saga"
"""
SHOW_COUNTRY_DEFAULT = """dynamic_collections:
  Country:
    type: origin_country
    title_format: <<key_name>>
    include:
      - gb
      - kr
"""


class StubLookup:
    def __init__(self, found, countries=None, languages=None):
        self.found, self.countries, self.languages = found, countries, languages

    async def items(self, library_key, library_type):
        return self.found


def _default(root: Path, folder: str, name: str, text: str) -> Path:
    path = root / "defaults" / folder / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return root


@pytest.mark.anyio
async def test_count_lists_franchises_as_kometa_does(plex_server, tmp_path):
    fake, server = plex_server
    movie = lambda cid, name: {"collection": (cid, name), "countries": [], "language": "en"}  # noqa: E731
    found = [
        ("1", movie("8091", "Alien Collection")), ("2", movie("8091", "Alien Collection")),
        ("3", movie("135416", "Prometheus Collection")),  # an addon of Alien: counted there, not on its own
        ("4", movie("10", "Star Wars Collection")), ("5", movie("10", "Star Wars Collection")),
        ("6", movie("99", "Lonely Collection")),  # one title: minimum_items 2 keeps it out
        ("7", {"collection": None, "countries": [], "language": "en"}),
    ]
    counted = await count(server, "1", "movie", _default(tmp_path, "movie", "franchise", FRANCHISE_DEFAULT), tmdb=StubLookup(found))
    franchise = next(c for c in counted if c.name == "franchise")
    assert [(e.key, e.kometa_name, e.items) for e in franchise.collections] == [
        ("8091", "Alien", 3),
        ("10", "Star Wars: Skywalker Saga", 2),
    ]


@pytest.mark.anyio
async def test_count_names_show_countries_with_tmdbs_english_names(plex_server, tmp_path):
    fake, server = plex_server
    show = lambda *codes: {"collection": None, "countries": list(codes), "language": "en"}  # noqa: E731
    found = [("1", show("gb")), ("2", show("kr")), ("3", show("kr", "us")), ("4", show("us"))]
    lookup = StubLookup(found, countries={"gb": "United Kingdom", "kr": "South Korea", "us": "United States of America"})
    counted = await count(server, "2", "show", _default(tmp_path, "show", "country", SHOW_COUNTRY_DEFAULT), tmdb=lookup)
    country = next(c for c in counted if c.name == "country")
    assert [(e.key, e.kometa_name, e.items) for e in country.collections] == [("gb", "United Kingdom", 1), ("kr", "South Korea", 2)]


@pytest.mark.anyio
async def test_count_without_tmdb_says_why(plex_server, tmp_path):
    fake, server = plex_server
    counted = await count(server, "1", "movie", _default(tmp_path, "movie", "franchise", FRANCHISE_DEFAULT), tmdb=None)
    franchise = next(c for c in counted if c.name == "franchise")
    assert franchise.collections == [] and "TMDb" in (franchise.count_error or "")
