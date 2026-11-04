import json

import httpx
import pytest

from kometa_studio.tmdb_details import TMDbDetails, TMDbUnavailable

ANSWERS = {
    "/3/movie/348": {"id": 348, "belongs_to_collection": {"id": 8091, "name": "Alien Collection"}, "original_language": "en"},
    "/3/movie/1": {"id": 1, "belongs_to_collection": None, "original_language": "fr"},
    "/3/tv/1396": {"id": 1396, "origin_country": ["US"], "original_language": "en"},
    "/3/find/81189": {"movie_results": [], "tv_results": [{"id": 1396}]},
    "/3/find/tt0078748": {"movie_results": [{"id": 348}], "tv_results": []},
}


def client(calls: list[httpx.Request], status: int | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if status is not None:
            return httpx.Response(status)
        answer = ANSWERS.get(request.url.path)
        return httpx.Response(200, json=answer) if answer is not None else httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_reads_what_kometa_reads_and_finds_missing_tmdb_ids(tmp_path):
    calls: list[httpx.Request] = []
    details = TMDbDetails(client(calls), "key", tmp_path)
    movies = await details.library([("a", {"tmdb": "348"}), ("b", {"imdb": "tt0078748"}), ("c", {"tmdb": "1"}), ("d", {"tmdb": "404"}), ("e", {})], True)
    assert movies == [
        ("a", {"collection": ("8091", "Alien Collection"), "countries": [], "language": "en"}),
        ("b", {"collection": ("8091", "Alien Collection"), "countries": [], "language": "en"}),
        ("c", {"collection": None, "countries": [], "language": "fr"}),
        ("d", {"collection": None, "countries": [], "language": None}),  # TMDb has nothing: no keys from it
    ]
    shows = await details.library([("s", {"tvdb": "81189"})], False)
    assert shows == [("s", {"collection": None, "countries": ["us"], "language": "en"})]
    assert all(r.url.params["api_key"] == "key" for r in calls)
    assert any(r.url.path == "/3/find/81189" and r.url.params["external_source"] == "tvdb_id" for r in calls)

    # Kept for 30 days: a second read asks TMDb nothing.
    again: list[httpx.Request] = []
    await TMDbDetails(client(again), "key", tmp_path).library([("a", {"tmdb": "348"})], True)
    assert again == []
    assert "movie:348" in json.loads((tmp_path / "tmdb-details.json").read_text())


@pytest.mark.anyio
async def test_tmdb_down_is_an_error_not_an_empty_list(tmp_path):
    with pytest.raises(TMDbUnavailable):
        await TMDbDetails(client([], 503), "key", tmp_path).library([("a", {"tmdb": "348"})], True)
