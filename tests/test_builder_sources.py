"""Builder collections with several sources: lists, single titles and a Plex search, written as one Kometa collection."""

from __future__ import annotations

import json

import pytest
from ruamel.yaml import YAML

from starr_studio import collections as col
from starr_studio import list_sources as ls
from starr_studio import smart_filters
from starr_studio.studio_files import render_built
from test_builder_routes import body as filter_body
from test_builder_routes import built_file
from test_collection_requests import record_requests, requests_on
from test_list_sources import tmdb_client
from test_ready_made_routes import root, wait_for_flags, wait_for_run  # noqa: F401 (root is a fixture)

# The maintainer's own collections, which combine sources (config/marvel*.yml, atla_*.yml).
MARVEL_STUDIOS = {"any": {"studio": ["Marvel Studios", "Marvel Entertainment", "Marvel Television", "Marvel Animation", "Marvel Enterprises"]}}
MARVEL_MOVIES = {
    "plex_search": MARVEL_STUDIOS,
    "imdb_list": ["https://www.imdb.com/list/ls539646485/", "https://www.imdb.com/list/ls567618635/"],
    "mdblist_list": "https://mdblist.com/lists/k0meta/external/15110",
    "tmdb_collection": [556],
    "collection_order": "release",
    "sort_title": "!020_Marvel",
    "summary": "Everything Marvel in this library, in release order.",
}
MARVEL_SHOWS = {key: value for key, value in MARVEL_MOVIES.items() if key != "tmdb_collection"}
AVATAR_MOVIES = {
    "tmdb_collection": [1136366],
    "tmdb_movie": [10196],
    "collection_order": "release",
    "sort_title": "!010_Avatar",
    "summary": "Movies set in the Avatar: The Last Airbender universe.",
}
AVATAR_SHOWS = {
    "tmdb_show": [246, 33880, 82452],
    "tvdb_show": [460458],
    "plex_search": {"any": {"studio": ["Avatar Studios"]}},
    "collection_order": "release",
    "sort_title": "!010_Avatar",
    "summary": "Every series in the Avatar: The Last Airbender universe.",
}
SEARCH_MARVEL = {"kind": "search", "filters": {"match": "any", "rules": [{"field": "studio", "modifier": "", "value": MARVEL_STUDIOS["any"]["studio"]}]}}
IMDB_LISTS = [
    {"kind": "list", "builder": "imdb_list", "value": "https://www.imdb.com/list/ls539646485/", "label": "IMDb list ls539646485"},
    {"kind": "list", "builder": "imdb_list", "value": "https://www.imdb.com/list/ls567618635/", "label": "IMDb list ls567618635"},
]
MDBLIST = {"kind": "list", "builder": "mdblist_list", "value": "https://mdblist.com/lists/k0meta/external/15110", "label": "15110"}
REAL = {
    ("Marvel", "movie"): (MARVEL_MOVIES, [SEARCH_MARVEL, *IMDB_LISTS, MDBLIST, {"kind": "list", "builder": "tmdb_collection", "value": "556", "label": None}]),
    ("Marvel", "show"): (MARVEL_SHOWS, [SEARCH_MARVEL, *IMDB_LISTS, MDBLIST]),
    ("Avatar - The Last Airbender", "movie"): (AVATAR_MOVIES, [
        {"kind": "list", "builder": "tmdb_collection", "value": "1136366", "label": None},
        {"kind": "titles", "builder": "tmdb_movie", "ids": ["10196"], "label": None},
    ]),
    ("Avatar - The Last Airbender", "show"): (AVATAR_SHOWS, [
        {"kind": "titles", "builder": "tmdb_show", "ids": ["246", "33880", "82452"], "label": None},
        {"kind": "titles", "builder": "tvdb_show", "ids": ["460458"], "label": None},
        {"kind": "search", "filters": {"match": "any", "rules": [{"field": "studio", "modifier": "", "value": ["Avatar Studios"]}]}},
    ]),
}

NO_RULES = {"match": "all", "rules": []}
DUNE = {"kind": "list", "builder": "tmdb_collection", "value": "131296", "label": None}
IMDB = {"kind": "list", "builder": "imdb_list", "value": "https://www.imdb.com/list/ls539646485/", "label": "IMDb list ls539646485"}
TITLES = {"kind": "titles", "builder": "tmdb_movie", "ids": ["949", "10196"], "label": None}
SEARCH = {"kind": "search", "filters": {"match": "any", "rules": [{"field": "studio", "modifier": "", "value": ["Legendary"]}]}}


def several(title: str = "Mixed", sources: list | None = None, **extra) -> dict:
    return filter_body(title, filters=NO_RULES, sort_by="release") | {"sources": sources if sources is not None else [DUNE, IMDB, TITLES, SEARCH]} | extra


def _load(text: str) -> dict:
    return YAML(typ="safe").load(text)["collections"]


# --- Definitions and what Kometa gets ---------------------------------------------------------------


def test_sources_of_reads_old_rows_and_new():
    assert ls.sources_of({"source": DUNE}) == [DUNE]
    assert ls.sources_of({}) == [{"kind": "filters"}]
    assert ls.sources_of({"source": DUNE, "sources": [DUNE, IMDB]}) == [DUNE, IMDB]
    assert ls.has_missing([SEARCH]) is False and ls.has_missing([SEARCH, TITLES]) is True


def test_several_sources_render_as_one_kometa_collection():
    base = {"filters": NO_RULES, "sort_by": "release", "visible": {"library": True}, "minimum_items": 1, "summary": "All of it"}
    for (name, library_type), (_body, sources) in REAL.items():
        written = _load(render_built([(name, base | {"source": sources[0], "sources": sources})], library_type=library_type))[name]
        assert written["sync_mode"] == "sync" and written["collection_order"] == "release" and written["label"] == "Studio"
        assert written["radarr_add_missing" if library_type == "movie" else "sonarr_add_missing"] is False
        assert "smart_filter" not in written
    movie = _load(render_built([("Marvel", base | {"sources": REAL[("Marvel", "movie")][1]})]))["Marvel"]
    assert list(movie)[:4] == ["plex_search", "imdb_list", "mdblist_list", "tmdb_collection"]
    assert movie["plex_search"] == {"any": {"studio": ["Marvel Studios", "Marvel Entertainment", "Marvel Television", "Marvel Animation", "Marvel Enterprises"]}}
    assert movie["imdb_list"] == ["https://www.imdb.com/list/ls539646485/", "https://www.imdb.com/list/ls567618635/"]
    assert movie["mdblist_list"] == "https://mdblist.com/lists/k0meta/external/15110" and movie["tmdb_collection"] == 556
    shows = _load(render_built([("Avatar", base | {"sources": REAL[("Avatar - The Last Airbender", "show")][1]})], library_type="show"))["Avatar"]
    assert shows["tmdb_show"] == [246, 33880, 82452] and shows["tvdb_show"] == [460458]
    assert shows["plex_search"] == {"any": {"studio": ["Avatar Studios"]}}

    # Titles of one builder merge into one list; the same list twice is written once.
    merged = base | {"sources": [TITLES, {**TITLES, "ids": ["10196", "603"]}, DUNE, DUNE, {"kind": "titles", "builder": "imdb_id", "ids": ["tt0113277"]}]}
    written = _load(render_built([("M", merged)]))["M"]
    assert written["tmdb_movie"] == [949, 10196, 603] and written["tmdb_collection"] == 131296 and written["imdb_id"] == ["tt0113277"]


def test_a_smart_filter_alone_renders_as_before():
    spec = {"match": "all", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}]}
    old = {"source": {"kind": "filters"}, "filters": spec, "sort_by": "title.asc", "limit": 5}
    new = old | {"sources": [{"kind": "filters"}]}
    assert render_built([("A", old)]) == render_built([("A", new)])
    assert _load(render_built([("A", new)]))["A"]["smart_filter"] == {"all": {"genre": ["Action"]}, "sort_by": "title.asc", "limit": 5}


def test_title_ids_are_checked():
    assert ls.normalise_ids("tmdb_movie", ["10196", 949, " 10196 "], "movie") == ["10196", "949"]
    assert ls.normalise_ids("imdb_id", "TT0113277, tt1", "show") == ["tt0113277", "tt1"]
    assert ls.normalise_ids("tvdb_show", [460458], "show") == ["460458"]
    for builder, ids, library_type, says in (
        ("tmdb_movie", ["dune"], "movie", "isn't a TMDb movie id"),
        ("imdb_id", ["0113277"], "movie", "isn't an IMDb id"),
        ("tmdb_movie", [], "movie", "at least one"),
        ("tmdb_movie", ["1"], "show", "can't be in a TV library"),
        ("tmdb_show", ["1"], "movie", "can't be in a movie library"),
        ("tvdb_show", ["1"], "movie", "can't be in a movie library"),
        ("tvdb_movie", ["1"], "movie", "doesn't add titles"),
    ):
        with pytest.raises(ls.SourceError, match=says):
            ls.normalise_ids(builder, ids, library_type)


def test_a_plex_search_takes_what_kometas_plex_search_takes():
    good = {"match": "any", "rules": [{"field": "studio", "modifier": "", "value": ["A24"]}]}
    assert smart_filters.validate_search("movie", good) == []
    assert smart_filters.to_plex_search(good) == {"any": {"studio": ["A24"]}}
    assert "Unknown field 'imdb_rating'" in smart_filters.validate_search("movie", {"match": "all", "rules": [{"field": "imdb_rating", "value": 7}]})[0]
    assert "only works for show libraries" in smart_filters.validate_search("movie", {"match": "all", "rules": [{"field": "network", "value": "HBO"}]})[0]
    assert smart_filters.validate_search("movie", good | {"sort_by": "title.asc"}) == ["A Plex search can't have sort_by"]


# --- Through the API ----------------------------------------------------------------------------------


def test_a_collection_with_several_sources_is_made_read_back_and_changed(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        made = client.post("/api/v1/collections", json=several(sources=[DUNE, {**IMDB, "label": None, "value": "https://m.imdb.com/list/ls539646485/?ref_=x"}, {**TITLES, "ids": ["949", " 10196", "949"]}, SEARCH]))
        assert made.status_code == 201, made.text
        built = made.json()
        assert built["sources"] == [DUNE, IMDB, TITLES, SEARCH] and built["source"] == DUNE
        written = built_file(root)["collections"]["Mixed"]
        assert written["tmdb_collection"] == 131296 and written["imdb_list"] == IMDB["value"] and written["tmdb_movie"] == [949, 10196]
        assert written["plex_search"] == {"any": {"studio": ["Legendary"]}} and written["sync_mode"] == "sync" and written["radarr_add_missing"] is False
        assert wait_for_run(client, built["run_id"])["status"] == "succeeded"  # the fake Kometa check passed, and it ran
        assert client.get(f"/api/v1/collections/{built['id']}").json()["sources"] == built["sources"]

        changed = client.put(f"/api/v1/collections/{built['id']}", json=several(sources=[IMDB, {"kind": "titles", "builder": "imdb_id", "ids": ["tt0113277"]}]))
        assert changed.status_code == 200, changed.text
        written = built_file(root)["collections"]["Mixed"]
        assert written["imdb_id"] == ["tt0113277"] and "tmdb_collection" not in written and "plex_search" not in written
        stored = json.loads(col.built_row(client.app.state.db, built["id"])["definition"])
        assert stored["source"] == IMDB and len(stored["sources"]) == 2


def test_old_single_source_rows_still_read_and_render(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        db = client.app.state.db
        with db:
            row_id = col.insert_built(db, "Movies", "abc123", "Old Dune", {"source": DUNE, "filters": NO_RULES, "sort_by": "release", "limit": None})
        shown = client.get(f"/api/v1/collections/{row_id}").json()
        assert shown["source"] == DUNE and shown["sources"] == [DUNE]
        retried = client.post(f"/api/v1/collections/{row_id}/retry")
        assert retried.status_code == 200, retried.text
        assert built_file(root)["collections"]["Old Dune"]["tmdb_collection"] == 131296


def test_sources_that_cant_be_used_are_refused(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)

        def problems(sources: list, **extra) -> list[str]:
            response = client.post("/api/v1/collections", json=several("Bad", sources, **extra))
            assert response.status_code == 422, response.text
            return response.json()["detail"]["problems"]

        assert "can't be combined" in problems([{"kind": "filters"}, DUNE])[0]
        assert "isn't a TMDb movie id" in problems([{"kind": "titles", "builder": "tmdb_movie", "ids": ["dune"]}])[0]
        assert "can't be in a movie library" in problems([{"kind": "titles", "builder": "tvdb_show", "ids": ["1"]}])[0]
        assert "Unknown field 'nonsense'" in problems([SEARCH, {"kind": "search", "filters": {"match": "all", "rules": [{"field": "nonsense", "value": "x"}]}}])[0]
        assert any("one Plex search" in p for p in problems([SEARCH, SEARCH]))
        assert "at most 20 sources" in problems([{**TITLES, "ids": [str(n)]} for n in range(1, 22)])[0]
        assert "at least one source" in problems([])[0]
        assert "only once" in problems([{"kind": "list", "builder": "tmdb_popular", "value": "10"}, {"kind": "list", "builder": "tmdb_popular", "value": "20"}])[0]
        requests_on(client)
        assert "no missing titles" in problems([SEARCH], download_missing=True)[0]
        assert col.built_rows(client.app.state.db, "Movies") == []


def test_the_preview_is_the_union_of_lists_and_titles(root):
    with tmdb_client(root, []) as client:
        preview = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "sources": [DUNE, IMDB, TITLES, {**TITLES, "ids": ["949"]}, SEARCH]}).json()
        assert preview["previewable"] is True and preview["problems"] == []
        assert preview["total"] == 4  # Dune's two parts, Heat and The Last Airbender; Heat once
        assert [i["title"] for i in preview["in_library"]] == ["Dune", "Heat"]
        assert [m["id"] for m in preview["missing"]] == ["tmdb-movie:693134", "tmdb-movie:10196"]
        assert [s["label"] for s in preview["skipped"]] == ["IMDb list ls539646485", "Plex search"]

        imdb_title = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "sources": [{"kind": "titles", "builder": "imdb_id", "ids": ["tt0113277", "tt0000404"]}]}).json()
        assert [i["title"] for i in imdb_title["in_library"]] == ["Heat"] and [m["id"] for m in imdb_title["missing"]] == ["imdb:tt0000404"]

        only_imdb = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "sources": [IMDB, SEARCH]}).json()
        assert only_imdb["previewable"] is False and "once it has been built" in only_imdb["why"]
        broken = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "sources": [DUNE, {**DUNE, "value": "424242"}]}).json()
        assert broken["problems"] == ["TMDb collection (franchise): TMDb has no such list"] and broken["in_library_count"] == 1


def test_download_missing_requests_the_union_of_several_lists(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        requests_on(client, confirm_over=5)
        calls = record_requests(client)
        made = client.post("/api/v1/collections", json=several(sources=[DUNE, IMDB, TITLES, SEARCH], download_missing=True))
        assert made.status_code == 201, made.text
        assert calls == [{"items": ["tmdb-movie:693134", "tmdb-movie:10196"], "library": "Movies", "collection_id": made.json()["id"], "cap": None}]
        wait_for_run(client, made.json()["run_id"])

        search = client.post("/api/v1/collections", json=several("Searched", sources=[SEARCH])).json()
        refused = client.put(f"/api/v1/collections/{search['id']}/download-missing", json={"download_missing": True})
        assert refused.status_code == 422 and "no missing titles" in refused.json()["detail"]["message"]
        titles = client.post("/api/v1/collections", json=several("Titles", sources=[SEARCH, {**TITLES, "ids": ["949"]}])).json()
        assert client.put(f"/api/v1/collections/{titles['id']}/download-missing", json={"download_missing": True}).status_code == 200


def test_the_maintainers_imported_collections_save_and_run(root):
    config = root / "config" / "config.yml"
    config.write_text(config.read_text().replace("libraries:\n  Movies: {}\n", "mdblist:\n  apikey: m\nlibraries:\n  Movies: {}\n  TV Shows: {}\n"))
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        for (name, library_type), (body, sources) in REAL.items():
            library = "Movies" if library_type == "movie" else "TV Shows"
            name = f"My {name}"  # FakePlex has a Marvel collection Studio didn't make
            made = client.post(
                "/api/v1/collections",
                json=several(name, sources, library=library, summary=body["summary"], sort_title=body["sort_title"], minimum_items=1),
            )
            assert made.status_code == 201, (name, library, made.text)
            assert made.json()["sources"] == sources
            assert wait_for_run(client, made.json()["run_id"])["status"] == "succeeded"
            written = YAML(typ="safe").load((root / "config" / "studio" / library / "built.yml").read_text())["collections"][name]
            assert written["sort_title"] == body["sort_title"] and written["collection_order"] == "release"
            assert {key for key in body if key not in ("collection_order", "sort_title", "summary")} <= set(written)


def test_list_order_only_where_kometa_keeps_it(root):
    """Kometa refuses collection_order: custom when it builds (not when it checks the config) unless the collection has
    one source from its custom_sort_builders. That's how a Harry Potter TMDb collection never got built (2026-11-06)."""
    with tmdb_client(root, []) as client:
        wait_for_flags(client)

        def save(title: str, sources: list) -> tuple[int, list[str]]:
            response = client.post("/api/v1/collections", json=several(title, sources, sort_by="custom"))
            return response.status_code, (response.json().get("detail") or {}).get("problems", []) if response.status_code == 422 else []

        status, problems = save("Harry Potter Collection", [{"kind": "list", "builder": "tmdb_collection", "value": "1241", "label": None}])
        assert status == 422 and "Kometa can't keep the order of a TMDb collection" in problems[0]
        status, problems = save("Picked", [TITLES])
        assert status == 422 and "Individual titles have no order of their own" in problems[0]
        status, problems = save("Two lists", [IMDB, {**IMDB, "value": "https://www.imdb.com/list/ls567618635/"}])
        assert status == 422 and "one source" in problems[0]
        assert col.built_rows(client.app.state.db, "Movies") == []

        assert save("IMDb ranked", [IMDB])[0] == 201  # one ranked list: Kometa keeps its order
        assert save("Searched", [SEARCH])[0] == 201  # plex_search is one of Kometa's too
        release = client.post("/api/v1/collections", json=several("Harry Potter", [{"kind": "list", "builder": "tmdb_collection", "value": "1241", "label": None}]))
        assert release.status_code == 201, release.text  # release date always works
