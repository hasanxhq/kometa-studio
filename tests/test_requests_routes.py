"""Tests for requests API routes (/api/v1/requests)."""

import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex
from fastapi.testclient import TestClient

from starr_studio.app import create_app
from starr_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
DEFAULTS_SRC = Path(__file__).parent / "fixtures" / "ready_made_defaults" / "defaults"

RADARR_URL = "http://radarr.test:7878"
SONARR_URL = "http://sonarr.test:8989"
SEERR_URL = "http://seerr.test:5055"
RADARR_KEY = "radarr-key"
SONARR_KEY = "sonarr-key"
SEERR_KEY = "seerr-key"
TMDB_KEY = "tmdb-key"


class FakeRouteEnvironment:
    def __init__(self) -> None:
        self.radarr_tags = [{"id": 1, "label": "other"}]
        self.radarr_movies: dict[int, dict] = {}
        self.radarr_queue: list[dict] = []

        self.sonarr_tags = [{"id": 1, "label": "other"}]
        self.sonarr_series: dict[int, dict] = {}
        self.sonarr_queue: list[dict] = []

        self.seerr_requests: dict[int, dict] = {}
        self.plex = FakePlex()
        self.requests: list[httpx.Request] = []
        self._next_id = 100

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url_str = str(request.url)
        path = request.url.path

        if url_str.startswith(REMOTE_URI):
            return self.plex.handle(request)

        if "api.themoviedb.org" in request.url.host:
            if "/tv/" in path and path.endswith("/external_ids"):
                return httpx.Response(200, json={"id": 1399, "tvdb_id": 121361})
            if path.startswith("/3/find/") or path.startswith("/find/"):
                return httpx.Response(200, json={"tv_results": [{"id": 1399}]})
            return httpx.Response(404)

        if url_str.startswith(RADARR_URL):
            if request.headers.get("X-Api-Key") != RADARR_KEY:
                return httpx.Response(401)
            if path == "/api/v3/system/status":
                return httpx.Response(200, json={"appName": "Radarr", "version": "5.14.0"})
            if path == "/api/v3/rootfolder":
                return httpx.Response(200, json=[{"id": 1, "path": "/movies"}])
            if path == "/api/v3/qualityprofile":
                return httpx.Response(200, json=[{"id": 4, "name": "HD-1080p"}])
            if path == "/api/v3/tag":
                if request.method == "GET":
                    return httpx.Response(200, json=self.radarr_tags)
                if request.method == "POST":
                    self._next_id += 1
                    tag = {"id": self._next_id, "label": "starr"}
                    self.radarr_tags.append(tag)
                    return httpx.Response(201, json=tag)
            if path == "/api/v3/movie":
                if request.method == "GET":
                    tmdb_id = int(request.url.params.get("tmdbId", 0))
                    matching = [m for m in self.radarr_movies.values() if m.get("tmdbId") == tmdb_id]
                    return httpx.Response(200, json=matching)
                if request.method == "POST":
                    body = json.loads(request.read().decode())
                    self._next_id += 1
                    movie = {"id": self._next_id, **body}
                    self.radarr_movies[self._next_id] = movie
                    return httpx.Response(201, json=movie)
            if path.startswith("/api/v3/movie/lookup/tmdb"):
                tmdb_id = int(request.url.params.get("tmdbId", 0))
                return httpx.Response(200, json=[{"title": f"Movie {tmdb_id}", "tmdbId": tmdb_id, "year": 2024}])
            if path.startswith("/api/v3/movie/"):
                mid = int(path.rsplit("/", 1)[-1])
                if request.method == "GET":
                    if mid in self.radarr_movies:
                        return httpx.Response(200, json=self.radarr_movies[mid])
                    return httpx.Response(404)
                if request.method == "PUT":
                    body = json.loads(request.read().decode())
                    if mid in self.radarr_movies:
                        self.radarr_movies[mid].update(body)
                    return httpx.Response(200, json=body)
            if path == "/api/v3/queue":
                return httpx.Response(200, json={"records": self.radarr_queue})
            return httpx.Response(404)

        if url_str.startswith(SONARR_URL):
            if request.headers.get("X-Api-Key") != SONARR_KEY:
                return httpx.Response(401)
            if path == "/api/v3/system/status":
                return httpx.Response(200, json={"appName": "Sonarr", "version": "4.0.11"})
            if path == "/api/v3/rootfolder":
                return httpx.Response(200, json=[{"id": 1, "path": "/tv"}])
            if path == "/api/v3/qualityprofile":
                return httpx.Response(200, json=[{"id": 4, "name": "HD-1080p"}])
            if path == "/api/v3/tag":
                if request.method == "GET":
                    return httpx.Response(200, json=self.sonarr_tags)
                if request.method == "POST":
                    self._next_id += 1
                    tag = {"id": self._next_id, "label": "starr"}
                    self.sonarr_tags.append(tag)
                    return httpx.Response(201, json=tag)
            if path == "/api/v3/series":
                if request.method == "GET":
                    tvdb_id = int(request.url.params.get("tvdbId", 0))
                    matching = [s for s in self.sonarr_series.values() if s.get("tvdbId") == tvdb_id]
                    return httpx.Response(200, json=matching)
                if request.method == "POST":
                    body = json.loads(request.read().decode())
                    self._next_id += 1
                    series = {"id": self._next_id, **body}
                    self.sonarr_series[self._next_id] = series
                    return httpx.Response(201, json=series)
            if path.startswith("/api/v3/series/lookup"):
                term = request.url.params.get("term", "")
                tvdb_id = int(term.split(":")[-1]) if ":" in term else 0
                return httpx.Response(200, json=[{"title": f"Series {tvdb_id}", "tvdbId": tvdb_id, "year": 2024}])
            if path.startswith("/api/v3/series/"):
                sid = int(path.rsplit("/", 1)[-1])
                if request.method == "GET":
                    if sid in self.sonarr_series:
                        return httpx.Response(200, json=self.sonarr_series[sid])
                    return httpx.Response(404)
                if request.method == "PUT":
                    body = json.loads(request.read().decode())
                    if sid in self.sonarr_series:
                        self.sonarr_series[sid].update(body)
                    return httpx.Response(200, json=body)
            if path == "/api/v3/queue":
                return httpx.Response(200, json={"records": self.sonarr_queue})
            return httpx.Response(404)

        if url_str.startswith(SEERR_URL):
            if path == "/api/v1/status":
                return httpx.Response(200, json={"version": "1.33.2"})
            if path == "/api/v1/settings/public":
                return httpx.Response(200, json={"applicationTitle": "Overseerr"})
            if path == "/api/v1/auth/me":
                if request.headers.get("X-Api-Key") == SEERR_KEY:
                    return httpx.Response(200, json={"id": 1})
                return httpx.Response(401, json={"message": "Unauthorized"})
            if path == "/api/v1/request":
                if request.headers.get("X-Api-Key") != SEERR_KEY:
                    return httpx.Response(401)
                body = json.loads(request.read().decode())
                self._next_id += 1
                req = {"id": self._next_id, **body}
                self.seerr_requests[self._next_id] = req
                return httpx.Response(201, json=req)
            if path.startswith("/api/v1/request/"):
                req_id = int(path.rsplit("/", 1)[-1])
                if request.method == "DELETE":
                    self.seerr_requests.pop(req_id, None)
                    return httpx.Response(204)
            return httpx.Response(404)

        return httpx.Response(404)


@pytest.fixture
def test_setup(tmp_path: Path):
    kometa = tmp_path / "kometa"
    kometa.mkdir()
    shutil.copy(FAKE_KOMETA, kometa / "kometa.py")
    shutil.copytree(DEFAULTS_SRC, kometa / "defaults")
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yml").write_text(
        f"plex:\n  url: {REMOTE_URI}\n  token: {SERVER_TOKEN}\n"
        f"tmdb:\n  apikey: {TMDB_KEY}\n"
        f"radarr:\n  url: {RADARR_URL}\n  token: {RADARR_KEY}\n"
        f"sonarr:\n  url: {SONARR_URL}\n  token: {SONARR_KEY}\n"
        "libraries:\n  Movies: {}\n  TV Shows: {}\n"
    )
    (config / "fake.json").write_text(json.dumps({"lines": ["ok"], "exit": 0}))

    mock = FakeRouteEnvironment()
    settings = Settings(
        data_dir=tmp_path / "data",
        kometa_python=Path(sys.executable),
        kometa_entry=tmp_path / "kometa" / "kometa.py",
        kometa_config=tmp_path / "config" / "config.yml",
        kill_after=0.5,
    )
    app = create_app(settings, static_dir=tmp_path / "no-static", http_transport=httpx.MockTransport(mock.handle))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, mock, app, tmp_path


def test_settings_routes(test_setup):
    client, mock, app, tmp_path = test_setup

    # 1. GET /settings
    res = client.get("/api/v1/requests/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["settings"]["enabled"] is False
    assert data["seerr"] is None
    assert data["connected"]["radarr"] is True
    assert data["connected"]["sonarr"] is True
    assert data["connected"]["seerr"] is False

    # 2. PUT /settings
    new_settings = data["settings"]
    new_settings["enabled"] = True
    new_settings["daily_cap"] = 5
    put_res = client.put("/api/v1/requests/settings", json=new_settings)
    assert put_res.status_code == 200
    assert put_res.json()["settings"]["enabled"] is True
    assert put_res.json()["settings"]["daily_cap"] == 5


def test_options_route(test_setup):
    client, mock, app, tmp_path = test_setup
    res = client.get("/api/v1/requests/options")
    assert res.status_code == 200
    data = res.json()
    assert data["radarr"]["quality_profiles"] == ["HD-1080p"]
    assert data["radarr"]["root_folders"] == ["/movies"]
    assert data["sonarr"]["quality_profiles"] == ["HD-1080p"]
    assert data["sonarr"]["root_folders"] == ["/tv"]


def test_seerr_routes(test_setup):
    client, mock, app, tmp_path = test_setup

    # 1. Test invalid connection
    test_bad = client.post("/api/v1/requests/seerr/test", json={"kind": "overseerr", "url": SEERR_URL, "api_key": "wrong"})
    assert test_bad.status_code == 200
    assert test_bad.json()["ok"] is False

    # 2. Test valid connection
    test_ok = client.post("/api/v1/requests/seerr/test", json={"kind": "overseerr", "url": SEERR_URL, "api_key": SEERR_KEY})
    assert test_ok.status_code == 200
    assert test_ok.json()["ok"] is True
    assert test_ok.json()["app"] == "overseerr"
    assert test_ok.json()["version"] == "1.33.2"

    # 3. Save connection (PUT)
    save_res = client.put("/api/v1/requests/seerr", json={"kind": "overseerr", "url": SEERR_URL, "api_key": SEERR_KEY})
    assert save_res.status_code == 200
    saved_data = save_res.json()
    assert saved_data["connected"]["seerr"] is True
    assert saved_data["seerr"]["api_key"] == "…-key"

    # Key should never appear in GET /settings
    get_res = client.get("/api/v1/requests/settings")
    assert get_res.json()["seerr"]["api_key"] == "…-key"

    # 4. DELETE /seerr
    del_res = client.delete("/api/v1/requests/seerr")
    assert del_res.status_code == 200
    assert del_res.json()["connected"]["seerr"] is False
    assert del_res.json()["seerr"] is None


def test_disabled_requests_return_409(test_setup):
    client, mock, app, tmp_path = test_setup
    res = client.post(
        "/api/v1/requests",
        json={"library": "Movies", "items": [{"item": "tmdb-movie:603", "title": "The Matrix"}]},
    )
    assert res.status_code == 409
    assert "disabled" in res.json()["detail"].lower()
    # Confirm no external HTTP requests made to Radarr
    assert not any(str(r.url).startswith(RADARR_URL) for r in mock.requests)


def test_create_and_list_requests(test_setup):
    client, mock, app, tmp_path = test_setup
    # Enable requests
    client.put("/api/v1/requests/settings", json={"enabled": True, "via": "arr"})

    # Post request
    post_res = client.post(
        "/api/v1/requests",
        json={
            "library": "Movies",
            "collection_id": 10,
            "items": [
                {"item": "tmdb-movie:603", "title": "The Matrix", "year": 1999},
                {"item": "tmdb-movie:604", "title": "The Matrix Reloaded", "year": 2003},
            ],
        },
    )
    assert post_res.status_code == 200
    outcome = post_res.json()
    assert outcome["requested"] == 2
    assert outcome["exists"] == 0

    # List requests
    list_res = client.get("/api/v1/requests")
    assert list_res.status_code == 200
    body = list_res.json()
    assert len(body["requests"]) == 2
    assert body["counts"]["requested"] == 2

    # Filter by collection_id
    filtered = client.get("/api/v1/requests?collection_id=10")
    assert len(filtered.json()["requests"]) == 2
    empty = client.get("/api/v1/requests?collection_id=999")
    assert len(empty.json()["requests"]) == 0


def test_cancel_and_refresh_routes(test_setup):
    client, mock, app, tmp_path = test_setup
    client.put("/api/v1/requests/settings", json={"enabled": True, "via": "arr"})

    post_res = client.post(
        "/api/v1/requests",
        json={"library": "Movies", "items": [{"item": "tmdb-movie:603", "title": "The Matrix"}]},
    )
    assert post_res.status_code == 200

    row_id = client.get("/api/v1/requests").json()["requests"][0]["id"]

    # Cancel request
    cancel_res = client.post(f"/api/v1/requests/{row_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # Cannot cancel already cancelled
    cancel_again = client.post(f"/api/v1/requests/{row_id}/cancel")
    assert cancel_again.status_code == 409

    # 404 for non-existent row
    assert client.post("/api/v1/requests/9999/cancel").status_code == 404

    # Refresh endpoint
    ref_res = client.post("/api/v1/requests/refresh")
    assert ref_res.status_code == 200
    assert "requested" in ref_res.json()
    assert "downloading" in ref_res.json()
