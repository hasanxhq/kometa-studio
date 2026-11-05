"""Collections from a list: links, values, the preview's split, and what Studio writes for Kometa."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from ruamel.yaml import YAML

from fakeplex import FakePlex
from starr_studio import list_sources as ls
from starr_studio.app import create_app
from starr_studio.settings import Settings
from starr_studio.plex_library import PlexItem
from starr_studio.studio_files import render_built
from test_builder_routes import body as filter_body
from test_builder_routes import built_file
from test_ready_made_routes import root, wait_for_flags, wait_for_run  # noqa: F401 (root is a fixture)


@pytest.mark.parametrize(
    ("link", "library_type", "expected"),
    [
        ("https://www.themoviedb.org/collection/131296-dune-collection", "movie", ("tmdb_collection", "131296", None)),
        ("themoviedb.org/list/8136?language=en", "movie", ("tmdb_list", "8136", None)),
        ("https://m.imdb.com/list/ls055592025/?ref_=x", "movie", ("imdb_list", "https://www.imdb.com/list/ls055592025/", "IMDb list ls055592025")),
        ("https://www.imdb.com/chart/top/", "movie", ("imdb_chart", "top_movies", "IMDb Top 250 Movies")),
        ("https://www.imdb.com/chart/toptv", "show", ("imdb_chart", "top_shows", "IMDb Top 250 TV Shows")),
        ("https://letterboxd.com/dave/list/official-top-250-narrative-feature-films", "movie", ("letterboxd_list", "https://letterboxd.com/dave/list/official-top-250-narrative-feature-films/", "Official top 250 narrative feature films")),
        ("https://mdblist.com/lists/linaspurinis/top-watched-movies-of-the-week/", "movie", ("mdblist_list", "https://mdblist.com/lists/linaspurinis/top-watched-movies-of-the-week", "Top watched movies of the week")),
    ],
)
def test_links_become_kometa_builders(link, library_type, expected):
    assert ls.from_link(link, library_type) == expected


@pytest.mark.parametrize(
    ("link", "library_type", "says"),
    [
        ("https://trakt.tv/users/x/lists/y", "movie", "no longer reads Trakt"),
        ("https://example.com/list/1", "movie", "doesn't recognise"),
        ("https://www.themoviedb.org/collection/131296", "show", "can't be a collection in a TV library"),
        ("https://www.imdb.com/chart/top/", "show", "and this is a TV library"),
        ("https://letterboxd.com/dave/list/x/", "show", "can't be a collection in a TV library"),
    ],
)
def test_links_studio_cant_use_say_why(link, library_type, says):
    with pytest.raises(ls.SourceError, match=says):
        ls.from_link(link, library_type)


def test_values_are_normalised_and_checked():
    assert ls.normalise("tmdb_collection", " 131296 ", "movie") == ("131296", None)
    assert ls.normalise("tmdb_collection", "https://www.themoviedb.org/collection/131296", "movie") == ("131296", None)
    assert ls.normalise("tmdb_popular", "20", "show") == ("20", None)
    assert ls.normalise("imdb_chart", "popular_movies", "movie") == ("popular_movies", "IMDb Most Popular Movies")
    for builder, raw, says in (
        ("tmdb_popular", "0", "1 to 500"),
        ("tmdb_popular", "501", "1 to 500"),
        ("imdb_chart", "top_shows", "no chart"),
        ("imdb_list", "https://www.themoviedb.org/list/1", "not a IMDb list"),
        ("nope", "1", "doesn't make collections"),
        ("tmdb_now_playing", "20", "can't be a collection"),
    ):
        with pytest.raises(ls.SourceError, match=says):
            ls.normalise(builder, raw, "show" if builder == "tmdb_now_playing" else "movie")
    assert ls.kometa_value("tmdb_collection", "131296") == 131296
    assert ls.kometa_value("imdb_chart", "top_movies") == "top_movies"


def test_catalogue_fits_the_library_and_its_connections():
    movie = {k["builder"]: k for k in ls.catalogue("movie", {"tmdb"})}
    show = {k["builder"]: k for k in ls.catalogue("show", {"tmdb", "mdblist"})}
    assert "tmdb_collection" in movie and "tmdb_collection" not in show
    assert "letterboxd_list" in movie and "letterboxd_list" not in show
    assert "tmdb_airing_today" in show and "tmdb_now_playing" not in show
    assert movie["mdblist_list"]["available"] is False and "MDBList" in movie["mdblist_list"]["why"]
    assert show["mdblist_list"]["available"] is True
    assert [c["value"] for c in show["imdb_chart"]["choices"]] == ["top_shows", "popular_shows"]
    assert movie["tmdb_collection"]["input"] == "search" and movie["tmdb_collection"]["previewable"] is True
    assert movie["imdb_list"]["previewable"] is False


def _plex(key: str, tmdb: str | None = None, imdb: str | None = None) -> PlexItem:
    ids = {k: v for k, v in (("tmdb", tmdb), ("imdb", imdb)) if v}
    return PlexItem(key, f"T{key}", "movie", 2000, None, ids, None, None, None, None)


def test_split_matches_on_tmdb_then_imdb_in_list_order():
    library = [_plex("1", tmdb="10"), _plex("2", imdb="tt2"), _plex("3", tmdb="30")]
    items = [ls.ListItem("30", None, "c", 2001, None), ls.ListItem("99", None, "gone", 1999, None), ls.ListItem(None, "tt2", "b", None, None), ls.ListItem("30", None, "c again", None, None)]
    have, missing = ls.split(items, library)
    assert [i.rating_key for i in have] == ["3", "2"]
    assert [m.title for m in missing] == ["gone"]
    assert ls.missing_key(missing[0], "movie") == "tmdb-movie:99" and ls.missing_key(ls.ListItem("5", None, "", None, None), "show") == "tmdb-show:5"


def test_render_built_writes_a_list_collection_with_kometa_requests_off():
    definition = {
        "source": {"kind": "list", "builder": "tmdb_collection", "value": "131296", "label": "Dune Collection"},
        "filters": {"match": "all", "rules": []},
        "sort_by": "release",
        "visible": {"library": True},
        "minimum_items": 1,
    }
    movie = YAML(typ="safe").load(render_built([("Dune", definition)]))["collections"]["Dune"]
    assert movie["tmdb_collection"] == 131296 and movie["sync_mode"] == "sync" and movie["collection_order"] == "release"
    assert movie["radarr_add_missing"] is False and "smart_filter" not in movie and movie["label"] == "Studio"
    show_def = definition | {"source": {"kind": "list", "builder": "imdb_chart", "value": "top_shows"}, "sort_by": None}
    show = YAML(typ="safe").load(render_built([("Top", show_def)], library_type="show"))["collections"]["Top"]
    assert show["imdb_chart"] == "top_shows" and show["sonarr_add_missing"] is False and "collection_order" not in show


# --- Routes ---------------------------------------------------------------------------------------------

DUNE = {
    "id": 131296,
    "name": "Dune Collection",
    "parts": [
        {"id": 693134, "title": "Dune: Part Two", "release_date": "2024-02-27", "poster_path": "/two.jpg"},
        {"id": 438631, "title": "Dune", "release_date": "2021-09-15", "poster_path": "/one.jpg"},
    ],
}


def tmdb_client(root, tmdb_calls: list):
    plex = FakePlex()
    plex.TITLES = {"1": [{**m, "Guid": [{"id": f"tmdb://{tmdb}"}]} for m, tmdb in zip(FakePlex.TITLES["1"], ("438631", "1000", "949"), strict=True)]}

    def tmdb(request: httpx.Request) -> httpx.Response:
        tmdb_calls.append(request.url)
        path = request.url.path.removeprefix("/3")
        if path == "/collection/131296":
            return httpx.Response(200, json=DUNE)
        if path == "/search/collection":
            return httpx.Response(200, json={"results": [{"id": 131296, "name": "Dune Collection", "poster_path": "/d.jpg"}, {"id": 1, "name": None}]})
        if path == "/movie/popular":
            page = int(request.url.params["page"])
            return httpx.Response(200, json={"total_pages": 9, "results": [{"id": 1726 + page * 100 + n, "title": f"P{page}-{n}"} for n in range(20)]})
        return httpx.Response(404, json={})

    def route(request: httpx.Request) -> httpx.Response:
        return tmdb(request) if request.url.host == "api.themoviedb.org" else plex.handle(request)

    settings = Settings(
        data_dir=root / "data",
        kometa_python=Path(sys.executable),
        kometa_entry=root / "kometa" / "kometa.py",
        kometa_config=root / "config" / "config.yml",
        kill_after=0.5,
    )
    app = create_app(settings, static_dir=root / "no-static", http_transport=httpx.MockTransport(route))
    return TestClient(app, client=("127.0.0.1", 50000))


def test_sources_link_search_and_preview_routes(root):
    calls: list = []
    with tmdb_client(root, calls) as client:
        sources = client.get("/api/v1/builder/sources", params={"library": "Movies"}).json()["sources"]
        assert {s["builder"] for s in sources} >= {"tmdb_collection", "imdb_chart", "letterboxd_list", "mdblist_list"}
        assert next(s for s in sources if s["builder"] == "mdblist_list")["available"] is False

        link = client.post("/api/v1/builder/sources/link", json={"library": "Movies", "url": "https://www.themoviedb.org/collection/131296-dune"})
        assert link.json() == {"builder": "tmdb_collection", "value": "131296", "label": "Dune Collection"}
        bad = client.post("/api/v1/builder/sources/link", json={"library": "Movies", "url": "https://trakt.tv/users/a/lists/b"})
        assert bad.status_code == 422 and "MDBList" in bad.json()["detail"]

        found = client.get("/api/v1/builder/sources/search", params={"library": "Movies", "builder": "tmdb_collection", "q": "dune"}).json()["results"]
        assert found == [{"value": "131296", "title": "Dune Collection", "year": None, "poster": "https://image.tmdb.org/t/p/w342/d.jpg"}]
        assert client.get("/api/v1/builder/sources/search", params={"library": "Movies", "builder": "imdb_list", "q": "dune"}).status_code == 422

        preview = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "source": {"builder": "tmdb_collection", "value": "131296"}}).json()
        assert preview["previewable"] is True and preview["total"] == 2 and preview["problems"] == []
        assert preview["in_library_count"] == 1 and preview["in_library"][0]["title"] == "Dune"
        assert preview["missing"] == [{"id": "tmdb-movie:693134", "title": "Dune: Part Two", "year": 2024, "poster": "https://image.tmdb.org/t/p/w342/two.jpg"}]

        # A chart reads only the pages it needs.
        before = len(calls)
        chart = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "source": {"builder": "tmdb_popular", "value": "30"}}).json()
        assert chart["total"] == 30 and len(calls) - before == 2

        imdb = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "source": {"builder": "imdb_chart", "value": "top_movies"}}).json()
        assert imdb["previewable"] is False and "once it has been built" in imdb["why"]
        wrong = client.post("/api/v1/builder/sources/preview", json={"library": "Movies", "source": {"builder": "tmdb_collection", "value": "424242"}}).json()
        assert wrong["problems"] == ["TMDb has no such list"]


def test_a_list_collection_is_written_as_its_kometa_builder(root):
    calls: list = []
    with tmdb_client(root, calls) as client:
        wait_for_flags(client)
        made = client.post(
            "/api/v1/collections",
            json=filter_body("Dune", filters={"match": "all", "rules": []}, sort_by="release")
            | {"source": {"kind": "list", "builder": "tmdb_collection", "value": "https://www.themoviedb.org/collection/131296", "label": None}},
        )
        assert made.status_code == 201, made.text
        built = made.json()
        assert built["source"] == {"kind": "list", "builder": "tmdb_collection", "value": "131296", "label": None}
        written = built_file(root)["collections"]["Dune"]
        assert written["tmdb_collection"] == 131296 and written["collection_order"] == "release" and "smart_filter" not in written
        assert wait_for_run(client, built["run_id"])["request"]["collections"] == ["Dune"]

        refused = client.post(
            "/api/v1/collections",
            json=filter_body("Charts", sort_by="title.asc", limit=5) | {"source": {"kind": "list", "builder": "imdb_chart", "value": "top_shows"}},
        )
        problems = refused.json()["detail"]["problems"]
        assert refused.status_code == 422 and len(problems) == 4
        no_key = client.post("/api/v1/collections", json=filter_body("M", filters={"match": "all", "rules": []}) | {"source": {"kind": "list", "builder": "mdblist_list", "value": "https://mdblist.com/lists/a/b"}})
        assert no_key.status_code == 422 and "needs MDBList connected" in no_key.json()["detail"]["problems"][0]
        # Filter collections still come back with their source.
        smart = client.post("/api/v1/collections", json=filter_body("Smart")).json()
        assert smart["source"] == {"kind": "filters"}
