"""Tests for smart filter catalogue, validation, Kometa mapping, and Plex query translation."""

import ast
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex

from starr_studio.plex_library import PlexServer
from starr_studio.smart_filters import (
    Field,
    SmartFilterError,
    fields,
    plex_query,
    sorts,
    to_kometa,
    validate,
)


@pytest.fixture
def plex_server():
    fake = FakePlex()
    client = httpx.AsyncClient(transport=fake.transport())
    server = PlexServer(client, REMOTE_URI, SERVER_TOKEN)
    return fake, server


# ══════════════════════════════════════════════════════════════════════════════
# Catalogue: fields() and sorts()
# ══════════════════════════════════════════════════════════════════════════════


def test_fields_movie_covers_core_attributes():
    movie_fields = fields("movie")
    by_key = {f.key: f for f in movie_fields}

    # genre: tag with is and is not, plex_tag is "genre"
    assert "genre" in by_key
    assert by_key["genre"].kind == "tag"
    assert by_key["genre"].plex_tag == "genre"
    assert by_key["genre"].modifiers == (("", "is"), ("not", "is not"))
    assert by_key["genre"].episode is False

    # year: year with gte/lte, gt/lt, is/not
    assert "year" in by_key
    assert by_key["year"].kind == "year"
    year_mods = [m[0] for m in by_key["year"].modifiers]
    assert set(year_mods) == {"", "not", "gt", "gte", "lt", "lte"}

    # decade: movie-only, no .not modifier
    assert "decade" in by_key
    assert by_key["decade"].kind == "year"
    assert by_key["decade"].modifiers == (("", "is"),)

    # added: date with before, after, in the last, not in the last
    assert "added" in by_key
    assert by_key["added"].kind == "date"
    added_mods = [m[0] for m in by_key["added"].modifiers]
    assert set(added_mods) == {"", "not", "before", "after"}

    # resolution: tag in no_not_mods
    assert "resolution" in by_key
    assert by_key["resolution"].kind == "tag"
    assert by_key["resolution"].plex_tag == "resolution"
    assert by_key["resolution"].modifiers == (("", "is"),)
    assert by_key["resolution"].episode is False

    # audio_language: tag
    assert "audio_language" in by_key
    assert by_key["audio_language"].kind == "tag"
    assert by_key["audio_language"].plex_tag == "audioLanguage"
    assert by_key["audio_language"].modifiers == (("", "is"), ("not", "is not"))

    # actor: tag
    assert "actor" in by_key
    assert by_key["actor"].kind == "tag"
    assert by_key["actor"].plex_tag == "actor"

    # content_rating: tag
    assert "content_rating" in by_key
    assert by_key["content_rating"].kind == "tag"
    assert by_key["content_rating"].plex_tag == "contentRating"

    # user_rating: float with rated modifier
    assert "user_rating" in by_key
    assert by_key["user_rating"].kind == "float"
    user_rating_mods = [m[0] for m in by_key["user_rating"].modifiers]
    assert set(user_rating_mods) == {"gt", "gte", "lt", "lte", "rated"}

    # unplayed: boolean (movie only)
    assert "unplayed" in by_key
    assert by_key["unplayed"].kind == "boolean"
    assert by_key["unplayed"].modifiers == (("", "is"),)

    # director, producer, writer, duration: movie only
    for key in ("director", "producer", "writer", "duration"):
        assert key in by_key


def test_fields_show_covers_show_specific_attributes():
    show_fields = fields("show")
    by_key = {f.key: f for f in show_fields}

    # network: show only tag
    assert "network" in by_key
    assert by_key["network"].kind == "tag"
    assert by_key["network"].plex_tag == "network"
    assert by_key["network"].modifiers == (("", "is"), ("not", "is not"))

    # unplayed_episodes & episode_unplayed in show (not movie's unplayed)
    assert "unplayed_episodes" in by_key
    assert by_key["unplayed_episodes"].kind == "boolean"
    assert "episode_unplayed" in by_key
    assert by_key["episode_unplayed"].kind == "boolean"
    assert by_key["episode_unplayed"].episode is True
    assert "unplayed" not in by_key

    # episode-level attributes have episode=True
    assert by_key["resolution"].episode is True
    assert by_key["audio_language"].episode is True
    assert by_key["subtitle_language"].episode is True
    assert by_key["hdr"].episode is True
    assert by_key["dovi"].episode is True
    assert by_key["episode_actor"].episode is True
    assert by_key["episode_title"].episode is True
    assert by_key["episode_year"].episode is True
    assert by_key["episode_added"].episode is True
    assert by_key["episode_air_date"].episode is True
    assert by_key["episode_user_rating"].episode is True

    # movie-only fields must NOT be in show fields
    for movie_only in ("director", "producer", "writer", "decade", "duration", "unplayed", "progress", "duplicate"):
        assert movie_only not in by_key


def test_fields_ordering_places_most_used_first():
    movie_keys = [f.key for f in fields("movie")]
    # Verify the most common fields are listed at the start
    expected_head = [
        "genre",
        "year",
        "decade",
        "content_rating",
        "studio",
        "actor",
        "director",
        "resolution",
        "unplayed",
        "added",
        "user_rating",
        "critic_rating",
        "audience_rating",
    ]
    assert movie_keys[: len(expected_head)] == expected_head

    show_keys = [f.key for f in fields("show")]
    expected_show_head = [
        "genre",
        "year",
        "content_rating",
        "network",
        "studio",
        "actor",
        "resolution",
        "unplayed_episodes",
        "added",
        "user_rating",
        "critic_rating",
        "audience_rating",
    ]
    assert show_keys[: len(expected_show_head)] == expected_show_head


def test_sorts_lists_valid_options_with_labels():
    movie_sort_list = sorts("movie")
    movie_sort_dict = dict(movie_sort_list)
    assert "title.asc" in movie_sort_dict
    assert "release.desc" in movie_sort_dict
    assert "user_rating.desc" in movie_sort_dict
    assert "random" in movie_sort_dict

    show_sort_list = sorts("show")
    show_sort_dict = dict(show_sort_list)
    assert "title.asc" in show_sort_dict
    assert "episode_added.desc" in show_sort_dict
    assert "unplayed.asc" in show_sort_dict

    assert fields("music") == []
    assert sorts("unknown") == []


# ══════════════════════════════════════════════════════════════════════════════
# Validation: validate()
# ══════════════════════════════════════════════════════════════════════════════


def test_validate_accepts_valid_spec():
    spec = {
        "match": "all",
        "rules": [
            {"field": "genre", "modifier": "", "value": ["Action", "Comedy"]},
            {"field": "year", "modifier": "gte", "value": 2000},
            {"field": "unplayed", "modifier": "", "value": True},
        ],
    }
    assert validate("movie", spec, sort_by="release.desc") == []


def test_validate_catches_unknown_field():
    spec = {"match": "all", "rules": [{"field": "nonexistent_field", "modifier": "", "value": "val"}]}
    errors = validate("movie", spec)
    assert any("Unknown field 'nonexistent_field'" in e for e in errors)


def test_validate_catches_movie_only_in_show():
    spec = {"match": "all", "rules": [{"field": "director", "modifier": "", "value": "Spielberg"}]}
    errors = validate("show", spec)
    assert any("Field 'director' only works for movie libraries" in e for e in errors)


def test_validate_catches_show_only_in_movie():
    spec = {"match": "all", "rules": [{"field": "network", "modifier": "", "value": "HBO"}]}
    errors = validate("movie", spec)
    assert any("Field 'network' only works for show libraries" in e for e in errors)


def test_validate_catches_invalid_modifier():
    # genre does not take gte
    spec = {"match": "all", "rules": [{"field": "genre", "modifier": "gte", "value": "Action"}]}
    errors = validate("movie", spec)
    assert any("Field 'genre' does not support modifier 'gte'" in e for e in errors)

    # resolution does not take not (in no_not_mods)
    spec_res = {"match": "all", "rules": [{"field": "resolution", "modifier": "not", "value": "4k"}]}
    assert any("Field 'resolution' does not support modifier 'not'" in e for e in validate("movie", spec_res))


def test_validate_catches_wrong_value_kind():
    # boolean field given string
    spec_bool = {"match": "all", "rules": [{"field": "unplayed", "modifier": "", "value": "yes"}]}
    assert any("must be a boolean" in e for e in validate("movie", spec_bool))

    # number field given string
    spec_num = {"match": "all", "rules": [{"field": "plays", "modifier": "gte", "value": "ten"}]}
    assert any("must be an integer" in e for e in validate("movie", spec_num))

    # rating float given out of range (> 10)
    spec_float = {"match": "all", "rules": [{"field": "user_rating", "modifier": "gte", "value": 15.0}]}
    assert any("must be between 0 and 10" in e for e in validate("movie", spec_float))

    # date before given invalid date string
    spec_date = {"match": "all", "rules": [{"field": "added", "modifier": "before", "value": "not-a-date"}]}
    assert any("must be a valid date" in e for e in validate("movie", spec_date))


def test_validate_catches_empty_rules_or_invalid_match():
    assert any("cannot be empty" in e for e in validate("movie", {"match": "all", "rules": []}))
    assert any("cannot be empty" in e for e in validate("movie", {"match": "all"}))
    assert any("Invalid match" in e for e in validate("movie", {"match": "either", "rules": [{"field": "year", "value": 2000}]}))


def test_validate_catches_unknown_sort():
    spec = {"match": "all", "rules": [{"field": "year", "modifier": "", "value": 2000}]}
    errors = validate("movie", spec, sort_by="invalid_sort_key")
    assert any("Unknown sort 'invalid_sort_key'" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# Kometa Mapping: to_kometa()
# ══════════════════════════════════════════════════════════════════════════════


def test_to_kometa_example_spec():
    spec = {
        "match": "all",
        "rules": [
            {"field": "genre", "modifier": "", "value": ["Action", "Comedy"]},
            {"field": "year", "modifier": "gte", "value": 2000},
            {"field": "unplayed", "modifier": "", "value": True},
        ],
    }
    expected = {
        "all": {
            "genre": ["Action", "Comedy"],
            "year.gte": 2000,
            "unplayed": True,
        }
    }
    assert to_kometa(spec) == expected


def test_to_kometa_with_sort_and_limit():
    spec = {
        "match": "all",
        "rules": [
            {"field": "genre", "modifier": "", "value": "Drama"},
            {"field": "year", "modifier": "lte", "value": 1999},
        ],
    }
    out = to_kometa(spec, sort_by="release.desc", limit=50)
    assert out == {
        "all": {
            "genre": "Drama",
            "year.lte": 1999,
        },
        "sort_by": "release.desc",
        "limit": 50,
    }


def test_to_kometa_merges_two_rules_on_same_tag_and_modifier():
    spec = {
        "match": "all",
        "rules": [
            {"field": "genre", "modifier": "", "value": ["Action"]},
            {"field": "genre", "modifier": "", "value": ["Comedy"]},
            {"field": "genre", "modifier": "not", "value": "Horror"},
            {"field": "genre", "modifier": "not", "value": "Romance"},
        ],
    }
    out = to_kometa(spec)
    assert out == {
        "all": {
            "genre": ["Action", "Comedy"],
            "genre.not": ["Horror", "Romance"],
        }
    }


def test_to_kometa_any_match():
    spec = {
        "match": "any",
        "rules": [
            {"field": "genre", "modifier": "", "value": "Action"},
            {"field": "genre", "modifier": "", "value": "Sci-Fi"},
        ],
    }
    out = to_kometa(spec)
    assert out == {
        "any": {
            "genre": ["Action", "Sci-Fi"],
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# Plex Query Translation: plex_query()
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_plex_query_spec1_all_tags_year_unplayed(plex_server):
    """Spec 1: Match 'all' with tag list, year.gte, and boolean unplayed.

    Kometa builder.py lines 4340-4490:
    - type=1 (movie)
    - default sort is 'titleSort'
    - genre is resolved via tag_values('1', 'genre') -> 'Action', 'Sci-Fi'
    - year.gte produces 'year%3E=2000'
    - unplayed (True) translates via search_translation['unplayed']='unwatched' to 'unwatched=1'
    - all items are joined with 'and=1'
    - no outer push/pop because base is 'all'
    Expected URI: ?type=1&sort=titleSort&genre=Action&and=1&genre=Sci-Fi&and=1&year%3E=2000&and=1&unwatched=1
    """
    _, server = plex_server
    spec = {
        "match": "all",
        "rules": [
            {"field": "genre", "modifier": "", "value": ["Action", "Sci-Fi"]},
            {"field": "year", "modifier": "gte", "value": 2000},
            {"field": "unplayed", "modifier": "", "value": True},
        ],
    }
    params = await plex_query(server, "1", "movie", spec)
    assert params == [
        ("type", "1"),
        ("sort", "titleSort"),
        ("genre", "Action"),
        ("and", "1"),
        ("genre", "Sci-Fi"),
        ("and", "1"),
        ("year>", "2000"),
        ("and", "1"),
        ("unwatched", "1"),
    ]


@pytest.mark.anyio
async def test_plex_query_spec2_any_with_push_pop(plex_server):
    """Spec 2: Match 'any' with genre picks and explicit sort_by='release.desc'.

    Kometa builder.py lines 4460-4490:
    - type=1 (movie)
    - sort='originallyAvailableAt:desc' (from movie_sorts['release.desc'])
    - base is 'any', so final_filter is push=1&<inside>&pop=1
    - inside items joined with 'or=1'
    Expected URI: ?type=1&sort=originallyAvailableAt:desc&push=1&genre=Action&or=1&genre=Sci-Fi&pop=1
    """
    _, server = plex_server
    spec = {
        "match": "any",
        "rules": [
            {"field": "genre", "modifier": "", "value": "Action"},
            {"field": "genre", "modifier": "", "value": "Sci-Fi"},
        ],
    }
    params = await plex_query(server, "1", "movie", spec, sort_by="release.desc")
    assert params == [
        ("type", "1"),
        ("sort", "originallyAvailableAt:desc"),
        ("push", "1"),
        ("genre", "Action"),
        ("or", "1"),
        ("genre", "Sci-Fi"),
        ("pop", "1"),
    ]


@pytest.mark.anyio
async def test_plex_query_spec3_dates_ratings_duration(plex_server):
    """Spec 3: Match 'all' with date (in last 30 days), float rating, and duration.

    Kometa builder.py lines 4402-4415:
    - added (in the last 30d): search_translation['added']='addedAt'.
      modifier '' on date means 'in the last N days', giving last_mod='%3E%3E' and value '-30d'.
      Param: ('addedAt%3E%3E', '-30d')
    - user_rating.gte 7.5: search_translation['user_rating']='userRating', mod='%3E'.
      Param: ('userRating%3E', '7.5')
    - duration.gte 90: duration in minutes converted to milliseconds (90 * 60000 = 5400000), mod='%3E'.
      Param: ('duration%3E', '5400000')
    Expected URI: ?type=1&sort=titleSort&addedAt%3E%3E=-30d&and=1&userRating%3E=7.5&and=1&duration%3E=5400000
    """
    _, server = plex_server
    spec = {
        "match": "all",
        "rules": [
            {"field": "added", "modifier": "", "value": 30},
            {"field": "user_rating", "modifier": "gte", "value": 7.5},
            {"field": "duration", "modifier": "gte", "value": 90},
        ],
    }
    params = await plex_query(server, "1", "movie", spec)
    assert params == [
        ("type", "1"),
        ("sort", "titleSort"),
        ("addedAt>>", "-30d"),
        ("and", "1"),
        ("userRating>", "7.5"),
        ("and", "1"),
        ("duration>", "5400000"),
    ]


@pytest.mark.anyio
async def test_plex_query_spec4_show_library(plex_server):
    """Spec 4: Show library with network, show-level year, and episode-level resolution.

    Kometa builder.py and plex.py:
    - type=2 (show)
    - default sort is 'titleSort'
    - network: search_translation['network']='show.network'. Tag resolved via tag_values('2', 'network') -> 'HBO'
    - year.gte: show_translation['year']='show.year', mod='%3E'. Param: ('show.year%3E', '2020')
    - resolution: episode=True in show, show_translation['resolution']='episode.resolution'.
      Tag resolved via tag_values('2', 'resolution', episode=True) -> '4k'.
      Param: ('episode.resolution', '4k')
    Expected URI: ?type=2&sort=titleSort&show.network=HBO&and=1&show.year%3E=2020&and=1&episode.resolution=4k
    """
    fake, server = plex_server
    # Ensure section 2 has resolution tag for episode in FakePlex
    fake.TAGS["2"]["resolution"] = [{"key": "4k", "title": "4k"}]

    spec = {
        "match": "all",
        "rules": [
            {"field": "network", "modifier": "", "value": "HBO"},
            {"field": "year", "modifier": "gte", "value": 2020},
            {"field": "resolution", "modifier": "", "value": "4k"},
        ],
    }
    params = await plex_query(server, "2", "show", spec)
    assert params == [
        ("type", "2"),
        ("sort", "titleSort"),
        ("show.network", "HBO"),
        ("and", "1"),
        ("show.year>", "2020"),
        ("and", "1"),
        ("episode.resolution", "4k"),
    ]


@pytest.mark.anyio
async def test_plex_query_spec5_negated_tags_and_booleans(plex_server):
    """Spec 5: Negated tags and boolean flags.

    Kometa builder.py lines 4424-4447:
    - genre.not 'Action': modifier 'not' gives mod='!'. Param: ('genre!', 'Action')
    - content_rating.not 'R': search_translation['content_rating']='contentRating', mod='!'.
      Param: ('contentRating!', 'R')
    - hdr (True): boolean attribute with value 1, mod=''. Param: ('hdr', '1')
    Expected URI: ?type=1&sort=titleSort&genre!=Action&and=1&contentRating!=R&and=1&hdr=1
    """
    _, server = plex_server
    spec = {
        "match": "all",
        "rules": [
            {"field": "genre", "modifier": "not", "value": "Action"},
            {"field": "content_rating", "modifier": "not", "value": "R"},
            {"field": "hdr", "modifier": "", "value": True},
        ],
    }
    params = await plex_query(server, "1", "movie", spec)
    assert params == [
        ("type", "1"),
        ("sort", "titleSort"),
        ("genre!", "Action"),
        ("and", "1"),
        ("contentRating!", "R"),
        ("and", "1"),
        ("hdr", "1"),
    ]


@pytest.mark.anyio
async def test_plex_query_spec6_language_resolution_and_rated(plex_server):
    """Spec 6: Audio language resolution and .rated modifier.

    - audio_language 'English': FakePlex tags have key='en', title='English'.
      Resolves title 'English' to key 'en'.
      search_translation['audio_language']='audioLanguage'.
      Param: ('audioLanguage', 'en')
    - user_rating.rated True:
      kometa builder.py line 4422: results = build_url_arg(-1, mod='!' if validation else '')
      Param: ('userRating!', '-1')
    """
    _, server = plex_server
    spec = {
        "match": "all",
        "rules": [
            {"field": "audio_language", "modifier": "", "value": "English"},
            {"field": "user_rating", "modifier": "rated", "value": True},
        ],
    }
    params = await plex_query(server, "1", "movie", spec)
    assert params == [
        ("type", "1"),
        ("sort", "titleSort"),
        ("audioLanguage", "en"),
        ("and", "1"),
        ("userRating!", "-1"),
    ]


@pytest.mark.anyio
async def test_plex_query_raises_on_unknown_tag_value(plex_server):
    _, server = plex_server
    spec = {
        "match": "all",
        "rules": [{"field": "genre", "modifier": "", "value": "NonexistentGenre"}],
    }
    with pytest.raises(SmartFilterError, match="Tag value 'NonexistentGenre' not found"):
        await plex_query(server, "1", "movie", spec)


@pytest.mark.anyio
async def test_plex_query_raises_on_validation_failure(plex_server):
    _, server = plex_server
    spec = {
        "match": "all",
        "rules": [{"field": "director", "modifier": "", "value": "Nolan"}],
    }
    # director is movie-only; fails in show library
    with pytest.raises(SmartFilterError, match="only works for movie libraries"):
        await plex_query(server, "2", "show", spec)


# ══════════════════════════════════════════════════════════════════════════════
# Kometa 2.5.4: HDR10+ and Dolby Atmos
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("library_type", ["movie", "show"])
def test_hdr10plus_and_atmos_are_media_booleans(library_type):
    by_key = {f.key: f for f in fields(library_type)}
    for key, label in (("hdr10plus", "HDR10+"), ("atmos", "Dolby Atmos")):
        assert by_key[key].kind == "boolean"
        assert by_key[key].label == label
        assert by_key[key].group == "Media"
        assert by_key[key].modifiers == (("", "is"),)
        assert by_key[key].episode is (library_type == "show")  # Kometa reads them from episodes in a show library


def test_hdr10plus_and_atmos_go_to_kometa_as_written():
    spec = {"match": "all", "rules": [{"field": "hdr10plus", "modifier": "", "value": True}, {"field": "atmos", "modifier": "", "value": False}]}
    assert validate("movie", spec) == []
    assert validate("show", spec) == []
    assert to_kometa(spec) == {"all": {"hdr10plus": True, "atmos": False}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("section", "library_type", "type_key", "prefix"),
    [("1", "movie", "1", ""), ("2", "show", "2", "episode.")],
)
async def test_plex_query_hdr10plus_and_atmos(plex_server, section, library_type, type_key, prefix):
    """Kometa 2.5.4 (builder.py line 4866) uses ``hdr10plus``/``atmos`` for a movie search and ``episode.hdr10plus``/
    ``episode.atmos`` for a show search; true is ``=1``, false ``!=1``, like the other booleans."""
    _, server = plex_server
    spec = {"match": "all", "rules": [{"field": "hdr10plus", "modifier": "", "value": True}, {"field": "atmos", "modifier": "", "value": False}]}
    params = await plex_query(server, section, library_type, spec)
    assert params == [
        ("type", type_key),
        ("sort", "titleSort"),
        (f"{prefix}hdr10plus", "1"),
        ("and", "1"),
        (f"{prefix}atmos!", "1"),
    ]


KOMETA_PLEX = Path(__file__).resolve().parents[1] / "kometa" / "modules" / "plex.py"


def _kometa_tables() -> dict:
    """plex.py's module-level lists and dicts, worked out from its source in order (no imports, no builtins)."""
    tables: dict = {}
    for node in ast.parse(KOMETA_PLEX.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                tables[node.targets[0].id] = eval(compile(ast.Expression(node.value), str(KOMETA_PLEX), "eval"), {"__builtins__": {}}, tables)  # noqa: S307
            except Exception:  # noqa: BLE001 - anything that needs more than plain lists isn't one of the tables
                pass
    return tables


@pytest.mark.skipif(not KOMETA_PLEX.is_file(), reason="needs the reference clone of Kometa in kometa/")
@pytest.mark.parametrize("library_type", ["movie", "show"])
def test_every_field_and_modifier_is_a_kometa_search(library_type):
    """Every attribute and modifier Studio offers is a search Kometa's plex.py accepts in that type of library, so a
    Kometa update that drops or renames one fails here (builder.py build_filter's checks)."""
    tables = _kometa_tables()
    allowed = set(tables["searches"]) - set(tables["music_searches"])
    allowed -= set(tables["show_only_searches" if library_type == "movie" else "movie_only_searches"])
    for field in fields(library_type):
        for modifier, _ in field.modifiers:
            name = f"{field.key}.{modifier}" if modifier else field.key
            if field.key == "folder_location":
                continue  # Kometa finds Plex's own filter for it (plex.py get_search_key)
            assert name in allowed, name
