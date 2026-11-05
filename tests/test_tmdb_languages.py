import json
import time

import httpx
import pytest

from starr_studio import tmdb_languages

CONFIG = "tmdb:\n  apikey: tmdb-key\n"
ANSWER = [
    {"iso_639_1": "fr", "english_name": "French", "name": "Français"},
    {"iso_639_1": "ko", "english_name": "Korean", "name": "한국어/조선말"},
    {"iso_639_1": "xx", "english_name": "No Language", "name": ""},
]


def _client(calls: list[httpx.Request], status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=ANSWER if status == 200 else {"status_message": "no"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(CONFIG)
    return path


@pytest.mark.anyio
async def test_fetches_with_the_saved_key_and_keeps_a_copy(config, tmp_path):
    calls: list[httpx.Request] = []
    names = await tmdb_languages.english_names(_client(calls), config, tmp_path / "data")
    assert names == {"fr": "French", "ko": "Korean", "xx": "No Language"}
    assert calls[0].url.path == "/3/configuration/languages" and calls[0].url.params["api_key"] == "tmdb-key"
    # A fresh copy is used without asking TMDb again.
    again = await tmdb_languages.english_names(_client(calls), config, tmp_path / "data")
    assert again == names and len(calls) == 1


@pytest.mark.anyio
async def test_stale_copy_when_tmdb_fails(config, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / tmdb_languages.CACHE).write_text(json.dumps({"fetched_at": time.time() - tmdb_languages.MAX_AGE - 1, "names": {"fr": "French"}}))
    calls: list[httpx.Request] = []
    assert await tmdb_languages.english_names(_client(calls, 401), config, data) == {"fr": "French"}
    assert len(calls) == 1


@pytest.mark.anyio
async def test_none_without_a_key_or_a_copy(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("plex: {}\n")
    calls: list[httpx.Request] = []
    assert await tmdb_languages.english_names(_client(calls), path, tmp_path / "data") is None
    assert calls == []


def test_kometa_title_looks_up_the_key_as_plex_has_it():
    names = {"en": "English", "fr": "French"}
    assert tmdb_languages.kometa_title(names, "fr", "Français") == "French"
    # Kometa doesn't lower-case Plex's key, so "en-US" isn't found and keeps Plex's title.
    assert tmdb_languages.kometa_title(names, "en-US", "English (US)") == "English (US)"
