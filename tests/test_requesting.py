"""Unit and integration tests for kometa_studio.requesting (RequestService)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex

from kometa_studio import arr
from kometa_studio.arr import Connection
from kometa_studio.crypto import SecretBox
from kometa_studio.db import open_database
from kometa_studio.plex_library import PlexServer
from kometa_studio.requesting import (
    Item,
    RequestOutcome,
    RequestService,
    RequestSettings,
    RequestsDisabled,
    SeerrConnection,
    SeerrConnectionIn,
    delete_seerr_connection,
    load_seerr_connection,
    load_settings,
    probe_seerr_connection,
    save_seerr_connection,
    save_settings,
    seerr_json,
)

RADARR_URL = "http://radarr.test:7878"
SONARR_URL = "http://sonarr.test:8989"
SEERR_URL = "http://seerr.test:5055"
RADARR_KEY = "radarr-key"
SONARR_KEY = "sonarr-key"
SEERR_KEY = "seerr-key"
TMDB_KEY = "tmdb-key"

T0 = datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)


class FakeMockEnvironment:
    """Simulates Radarr, Sonarr, Seerr, TMDb, and Plex."""

    def __init__(self) -> None:
        self.radarr_tags = [{"id": 1, "label": "other"}]
        self.radarr_movies: dict[int, dict] = {}
        self.radarr_queue: list[dict] = []

        self.sonarr_tags = [{"id": 1, "label": "other"}]
        self.sonarr_series: dict[int, dict] = {}
        self.sonarr_queue: list[dict] = []

        self.seerr_requests: dict[int, dict] = {}
        self.seerr_fail_409 = False

        self.plex = FakePlex()
        self.requests: list[httpx.Request] = []
        self._next_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url_str = str(request.url)
        path = request.url.path

        # Plex
        if url_str.startswith(REMOTE_URI):
            return self.plex.handle(request)

        # TMDb
        if "api.themoviedb.org" in request.url.host:
            if "/tv/" in path and path.endswith("/external_ids"):
                tv_id = path.split("/")[-2]
                if tv_id == "999999":  # simulate unmapped
                    return httpx.Response(200, json={"id": int(tv_id), "tvdb_id": None})
                if tv_id == "1399":
                    return httpx.Response(200, json={"id": int(tv_id), "tvdb_id": 121361})
                return httpx.Response(200, json={"id": int(tv_id), "tvdb_id": 81189})
            if path.startswith("/3/find/") or path.startswith("/find/"):
                val = path.rsplit("/", 1)[-1]
                if val == "999999":
                    return httpx.Response(200, json={"tv_results": []})
                return httpx.Response(200, json={"tv_results": [{"id": 1399}]})
            return httpx.Response(404)

        # Radarr
        if url_str.startswith(RADARR_URL):
            if request.headers.get("X-Api-Key") != RADARR_KEY:
                return httpx.Response(401)
            if path == "/api/v3/system/status":
                return httpx.Response(200, json={"appName": "Radarr", "version": "5.14.0"})
            if path == "/api/v3/rootfolder":
                return httpx.Response(200, json=[{"id": 1, "path": "/movies"}])
            if path == "/api/v3/qualityprofile":
                return httpx.Response(200, json=[{"id": 4, "name": "HD-1080p"}, {"id": 6, "name": "Ultra-HD"}])
            if path == "/api/v3/tag":
                if request.method == "GET":
                    return httpx.Response(200, json=self.radarr_tags)
                if request.method == "POST":
                    self._next_id += 1
                    body = request.read().decode()
                    tag = {"id": self._next_id, "label": "starr"}
                    self.radarr_tags.append(tag)
                    return httpx.Response(201, json=tag)
            if path == "/api/v3/movie":
                if request.method == "GET":
                    tmdb_id = int(request.url.params.get("tmdbId", 0))
                    matching = [m for m in self.radarr_movies.values() if m.get("tmdbId") == tmdb_id]
                    return httpx.Response(200, json=matching)
                if request.method == "POST":
                    import json
                    body = json.loads(request.read().decode())
                    self._next_id += 1
                    movie = {"id": self._next_id, **body}
                    self.radarr_movies[self._next_id] = movie
                    return httpx.Response(201, json=movie)
                if request.method == "PUT":
                    import json
                    body = json.loads(request.read().decode())
                    mid = int(body.get("id", 0))
                    if mid in self.radarr_movies:
                        self.radarr_movies[mid].update(body)
                    return httpx.Response(200, json=body)
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
                    import json
                    body = json.loads(request.read().decode())
                    if mid in self.radarr_movies:
                        self.radarr_movies[mid].update(body)
                    return httpx.Response(200, json=body)
            if path == "/api/v3/queue":
                return httpx.Response(200, json={"records": self.radarr_queue})
            return httpx.Response(404)

        # Sonarr
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
                    import json
                    body = json.loads(request.read().decode())
                    self._next_id += 1
                    series = {"id": self._next_id, **body}
                    self.sonarr_series[self._next_id] = series
                    return httpx.Response(201, json=series)
                if request.method == "PUT":
                    import json
                    body = json.loads(request.read().decode())
                    sid = int(body.get("id", 0))
                    if sid in self.sonarr_series:
                        self.sonarr_series[sid].update(body)
                    return httpx.Response(200, json=body)
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
                    import json
                    body = json.loads(request.read().decode())
                    if sid in self.sonarr_series:
                        self.sonarr_series[sid].update(body)
                    return httpx.Response(200, json=body)
            if path == "/api/v3/queue":
                return httpx.Response(200, json={"records": self.sonarr_queue})
            return httpx.Response(404)

        # Seerr
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
                if self.seerr_fail_409:
                    return httpx.Response(409, json={"message": "Media already requested"})
                import json
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
def env(tmp_path: Path):
    config = tmp_path / "config.yml"
    config.write_text(
        f"plex:\n  url: {REMOTE_URI}\n  token: {SERVER_TOKEN}\n"
        f"tmdb:\n  apikey: {TMDB_KEY}\n"
        f"radarr:\n  url: {RADARR_URL}\n  token: {RADARR_KEY}\n"
        f"sonarr:\n  url: {SONARR_URL}\n  token: {SONARR_KEY}\n"
        "libraries:\n  Movies: {}\n  TV Shows: {}\n"
    )
    db = open_database(tmp_path / "studio.db")
    box = SecretBox.load_or_create(tmp_path / "data")
    mock = FakeMockEnvironment()
    client = httpx.AsyncClient(transport=mock.transport())
    service = RequestService(db, client, box, config, tmp_path / "data")
    yield service, mock, db, box, config, client
    db.close()
    asyncio.run(client.aclose())


def test_settings_storage(env):
    service, mock, db, box, config, client = env
    default_settings = service.load_settings()
    assert default_settings.enabled is False
    assert default_settings.via == "auto"
    assert default_settings.daily_cap is None
    assert default_settings.confirm_over == 25

    default_settings.enabled = True
    default_settings.daily_cap = 10
    service.save_settings(default_settings)

    reloaded = service.load_settings()
    assert reloaded.enabled is True
    assert reloaded.daily_cap == 10


def test_seerr_connection_storage_and_masking(env):
    service, mock, db, box, config, client = env
    assert service.load_seerr_connection() is None
    assert service.seerr_json() is None

    conn = SeerrConnection(
        kind="overseerr",
        url="http://seerr.test:5055",
        api_key="1234567890abcdef",
        login=("admin", "secretpass"),
    )
    service.save_seerr(conn)

    loaded = service.load_seerr_connection()
    assert loaded is not None
    assert loaded.kind == "overseerr"
    assert loaded.url == "http://seerr.test:5055"
    assert loaded.api_key == "1234567890abcdef"
    assert loaded.login == ("admin", "secretpass")

    json_info = service.seerr_json()
    assert json_info["api_key"] == "…cdef"
    assert "secretpass" not in str(json_info)
    assert json_info["has_password"] is True

    service.delete_seerr()
    assert service.load_seerr_connection() is None


@pytest.mark.anyio
async def test_seerr_connection_test(env):
    service, mock, db, box, config, client = env
    conn = SeerrConnection(kind="overseerr", url=SEERR_URL, api_key=SEERR_KEY)
    res = await service.test_seerr(conn)
    assert res["app"] == "overseerr"
    assert res["version"] == "1.33.2"

    bad_conn = SeerrConnection(kind="overseerr", url=SEERR_URL, api_key="wrong-key")
    with pytest.raises(arr.ArrProblem, match="rejected"):
        await service.test_seerr(bad_conn)


@pytest.mark.anyio
async def test_requests_disabled_refuses_requests(env):
    service, mock, db, box, config, client = env
    # By default enabled is False
    with pytest.raises(RequestsDisabled):
        await service.request(
            [Item(item="tmdb-movie:603", title="The Matrix", year=1999)],
            library="Movies",
            collection_id=1,
            now=T0,
        )
    # Assert no request reached Radarr
    assert not any(str(r.url).startswith(RADARR_URL) for r in mock.requests)


@pytest.mark.anyio
async def test_movie_request_to_radarr(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    service.save_settings(settings)

    outcome = await service.request(
        [Item(item="tmdb-movie:603", title="The Matrix", year=1999)],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    assert outcome.requested == 1
    assert outcome.exists == 0
    assert outcome.failed == 0
    assert outcome.items[0].status == "requested"

    # Check Radarr received the add with starr tag
    assert any(t["label"] == "starr" for t in mock.radarr_tags)
    created_movie = next(iter(mock.radarr_movies.values()))
    assert created_movie["tmdbId"] == 603
    assert created_movie["qualityProfileId"] == 4
    assert created_movie["rootFolderPath"] == "/movies"
    assert created_movie["monitored"] is True
    assert created_movie["tags"] == [next(t["id"] for t in mock.radarr_tags if t["label"] == "starr")]

    # Check DB row
    row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    assert row["status"] == "requested"
    assert row["via"] == "radarr"
    assert row["external_id"] == str(created_movie["id"])


@pytest.mark.anyio
async def test_existing_movie_in_radarr_not_tagged(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    service.save_settings(settings)

    # Pre-populate Radarr
    mock.radarr_movies[50] = {"id": 50, "tmdbId": 603, "tags": [1]}

    outcome = await service.request(
        [Item(item="tmdb-movie:603", title="The Matrix", year=1999)],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    assert outcome.exists == 1
    assert outcome.requested == 0
    # Make sure starr tag was not added to existing movie
    assert mock.radarr_movies[50]["tags"] == [1]

    row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    assert row["status"] == "exists"

    # The next run asks again: skipped, no second row, and it doesn't use up the collection's daily cap.
    again = await service.request([Item(item="tmdb-movie:603", title="The Matrix", year=1999)], library="Movies", collection_id=1, now=T0, cap=1)
    assert again.skipped == 1 and again.exists == 0
    assert db.execute("SELECT count(*) FROM requests WHERE item = 'tmdb-movie:603'").fetchone()[0] == 1


@pytest.mark.anyio
async def test_show_request_to_sonarr(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    service.save_settings(settings)

    # 1. By tvdb
    outcome1 = await service.request(
        [Item(item="tvdb:81189", title="Breaking Bad", year=2008)],
        library="TV Shows",
        collection_id=2,
        now=T0,
    )
    assert outcome1.requested == 1
    created_series = next(iter(mock.sonarr_series.values()))
    assert created_series["tvdbId"] == 81189

    # 2. By tmdb-show mapped to tvdb
    outcome2 = await service.request(
        [Item(item="tmdb-show:1399", title="Game of Thrones", year=2011)],
        library="TV Shows",
        collection_id=2,
        now=T0,
    )
    assert outcome2.requested == 1

    # 3. Unmapped show fails with clear message
    outcome3 = await service.request(
        [Item(item="tmdb-show:999999", title="Unknown Show", year=2024)],
        library="TV Shows",
        collection_id=2,
        now=T0,
    )
    assert outcome3.failed == 1
    assert "No TVDb ID found" in outcome3.items[0].error


@pytest.mark.anyio
async def test_requests_via_seerr(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    settings.via = "seerr"
    service.save_settings(settings)

    service.save_seerr(SeerrConnection(kind="overseerr", url=SEERR_URL, api_key=SEERR_KEY))

    outcome = await service.request(
        [
            Item(item="tmdb-movie:603", title="The Matrix", year=1999),
            Item(item="tvdb:81189", title="Breaking Bad", year=2008),
        ],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    assert outcome.requested == 2
    assert len(mock.seerr_requests) == 2

    # Check tvdb mapped to tmdb for tv request
    tv_req = [r for r in mock.seerr_requests.values() if r["mediaType"] == "tv"][0]
    assert tv_req["mediaId"] == 1399
    assert tv_req["seasons"] == "all"


@pytest.mark.anyio
async def test_seerr_already_requested_becomes_exists(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    settings.via = "seerr"
    service.save_settings(settings)
    service.save_seerr(SeerrConnection(kind="overseerr", url=SEERR_URL, api_key=SEERR_KEY))

    mock.seerr_fail_409 = True

    outcome = await service.request(
        [Item(item="tmdb-movie:603", title="The Matrix", year=1999)],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    assert outcome.exists == 1
    row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    assert row["status"] == "exists"


@pytest.mark.anyio
async def test_deduplication_and_daily_cap(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    settings.daily_cap = 2
    service.save_settings(settings)

    # First batch: 2 items reach daily cap
    outcome1 = await service.request(
        [
            Item(item="tmdb-movie:1", title="M1"),
            Item(item="tmdb-movie:2", title="M2"),
            Item(item="tmdb-movie:3", title="M3"),  # capped!
        ],
        library="Movies",
        collection_id=10,
        now=T0,
    )
    assert outcome1.requested == 2
    assert outcome1.capped == 1

    # Second batch: same collection today -> all capped
    outcome2 = await service.request(
        [Item(item="tmdb-movie:4", title="M4")],
        library="Movies",
        collection_id=10,
        now=T0,
    )
    assert outcome2.capped == 1

    # Different collection has its own cap
    outcome3 = await service.request(
        [Item(item="tmdb-movie:5", title="M5")],
        library="Movies",
        collection_id=20,
        now=T0,
    )
    assert outcome3.requested == 1

    # Deduplication of active item
    outcome4 = await service.request(
        [Item(item="tmdb-movie:1", title="M1 duplicate")],
        library="Movies",
        collection_id=20,
        now=T0,
    )
    assert outcome4.skipped == 1


@pytest.mark.anyio
async def test_refresh_status_transitions(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    service.save_settings(settings)

    # 1. Request a movie and a show
    await service.request(
        [
            Item(item="tmdb-movie:603", title="The Matrix"),
            Item(item="tvdb:81189", title="Breaking Bad"),
        ],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    m_row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    s_row = db.execute("SELECT * FROM requests WHERE item = 'tvdb:81189'").fetchone()
    assert m_row["status"] == "requested"
    assert s_row["status"] == "requested"

    # 2. Put movie in Radarr queue -> refresh moves to downloading
    mid = int(m_row["external_id"])
    mock.radarr_queue.append({"movieId": mid})
    counts = await service.refresh(T0 + timedelta(minutes=5))
    assert counts["downloading"] == 1

    m_row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    assert m_row["status"] == "downloading"

    # 3. Mark movie hasFile=True -> refresh moves to imported
    mock.radarr_queue.clear()
    mock.radarr_movies[mid]["hasFile"] = True
    counts = await service.refresh(T0 + timedelta(minutes=10))
    assert counts["imported"] == 1

    m_row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    assert m_row["status"] == "imported"
    assert m_row["imported_at"] is not None


@pytest.mark.anyio
async def test_refresh_tags_seerr_items_in_arr(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    settings.via = "seerr"
    service.save_settings(settings)
    service.save_seerr(SeerrConnection(kind="overseerr", url=SEERR_URL, api_key=SEERR_KEY))

    await service.request(
        [Item(item="tmdb-movie:603", title="The Matrix")],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    # Title appears in Radarr without starr tag
    mock.radarr_movies[101] = {"id": 101, "tmdbId": 603, "tags": [1]}

    # Refresh should tag it
    await service.refresh(T0 + timedelta(minutes=2))
    starr_id = next(t["id"] for t in mock.radarr_tags if t["label"] == "starr")
    assert starr_id in mock.radarr_movies[101]["tags"]


def test_on_imports_hook(env):
    service, mock, db, box, config, client = env
    # Pre-insert a requested movie row
    db.execute(
        """
        INSERT INTO requests (item, media, title, library, via, status, requested_at, updated_at)
        VALUES ('tmdb-movie:603', 'movie', 'The Matrix', 'Movies', 'radarr', 'requested', '2026-11-05T12:00:00Z', '2026-11-05T12:00:00Z')
        """
    )
    db.commit()

    record = {"id": 1, "movie": {"tmdbId": 603, "title": "The Matrix"}}
    updated = service.on_imports("radarr", [record], T0)
    assert updated == 1

    row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:603'").fetchone()
    assert row["status"] == "imported"
    assert row["imported_at"] is not None


@pytest.mark.anyio
async def test_label_imported_in_plex(env):
    service, mock, db, box, config, client = env
    # Insert an imported movie
    db.execute(
        """
        INSERT INTO requests (item, media, title, library, via, status, requested_at, updated_at, imported_at)
        VALUES ('tmdb-movie:1726', 'movie', 'Marvel film 1', 'Movies', 'radarr', 'imported', '2026-11-05T12:00:00Z', '2026-11-05T12:00:00Z', '2026-11-05T12:10:00Z')
        """
    )
    db.commit()

    # In fake plex, item 201 in Movies has Guid tmdb://1726
    # Let's ensure TITLES in FakePlex has item 201 with Guid
    mock.plex.TITLES["1"].append({
        "ratingKey": "201",
        "title": "Marvel film 1",
        "type": "movie",
        "Guid": [{"id": "tmdb://1726"}],
        "Label": [{"tag": "ExistingLabel"}],
    })

    server = service.plex_server()
    assert server is not None

    labelled = await service.label_imported(server, T0)
    assert labelled == 1

    # Verify FakePlex received PUT with label=starr and preserved existing label
    movie = next(m for m in mock.plex.TITLES["1"] if m["ratingKey"] == "201")
    tags = [lab["tag"] for lab in movie.get("Label", [])]
    assert tags == ["ExistingLabel", "starr"]  # Plex's edit sets the whole list, so the old label is sent back with the new one

    # Already labelled: no second edit.
    assert await server.add_label("201", "starr", "movie", "1") is False

    row = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:1726'").fetchone()
    assert row["labelled_at"] is not None


@pytest.mark.anyio
async def test_cancel_request(env):
    service, mock, db, box, config, client = env
    # 1. Cancel Radarr movie
    mock.radarr_movies[10] = {"id": 10, "monitored": True}
    db.execute(
        """
        INSERT INTO requests (id, item, media, title, library, via, external_id, status, requested_at, updated_at)
        VALUES (1, 'tmdb-movie:10', 'movie', 'M10', 'Movies', 'radarr', '10', 'requested', '2026-11-05T12:00:00Z', '2026-11-05T12:00:00Z')
        """
    )
    # 2. Cancel Seerr request
    mock.seerr_requests[20] = {"id": 20}
    service.save_seerr(SeerrConnection(kind="overseerr", url=SEERR_URL, api_key=SEERR_KEY))
    db.execute(
        """
        INSERT INTO requests (id, item, media, title, library, via, external_id, status, requested_at, updated_at)
        VALUES (2, 'tmdb-movie:20', 'movie', 'M20', 'Movies', 'overseerr', '20', 'downloading', '2026-11-05T12:00:00Z', '2026-11-05T12:00:00Z')
        """
    )
    # 3. Imported row
    db.execute(
        """
        INSERT INTO requests (id, item, media, title, library, via, external_id, status, requested_at, updated_at)
        VALUES (3, 'tmdb-movie:30', 'movie', 'M30', 'Movies', 'radarr', '30', 'imported', '2026-11-05T12:00:00Z', '2026-11-05T12:00:00Z')
        """
    )
    db.commit()

    # Cancel row 1
    res1 = await service.cancel(1, T0)
    assert res1["status"] == "cancelled"
    assert mock.radarr_movies[10]["monitored"] is False

    # Cancel row 2
    res2 = await service.cancel(2, T0)
    assert res2["status"] == "cancelled"
    assert 20 not in mock.seerr_requests

    # Cancel row 3 raises ValueError
    with pytest.raises(ValueError, match="Can't cancel"):
        await service.cancel(3, T0)


@pytest.mark.anyio
async def test_one_failing_item_does_not_stop_others(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    service.save_settings(settings)

    outcome = await service.request(
        [
            Item(item="tmdb-show:999999", title="Broken Show"),  # fails (no TVDb ID)
            Item(item="tmdb-movie:603", title="The Matrix"),     # succeeds
        ],
        library="Movies",
        collection_id=1,
        now=T0,
    )

    assert outcome.failed == 1
    assert outcome.requested == 1
    assert outcome.items[0].status == "failed"
    assert outcome.items[1].status == "requested"


@pytest.mark.anyio
async def test_auto_via_selection(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    settings.via = "auto"
    service.save_settings(settings)

    # Without Seerr connected -> goes to Radarr
    outcome1 = await service.request(
        [Item(item="tmdb-movie:101", title="Movie 101")],
        library="Movies",
        collection_id=1,
        now=T0,
    )
    assert outcome1.requested == 1
    row1 = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:101'").fetchone()
    assert row1["via"] == "radarr"

    # With Seerr connected -> goes to Seerr
    service.save_seerr(SeerrConnection(kind="overseerr", url=SEERR_URL, api_key=SEERR_KEY))
    outcome2 = await service.request(
        [Item(item="tmdb-movie:102", title="Movie 102")],
        library="Movies",
        collection_id=1,
        now=T0,
    )
    assert outcome2.requested == 1
    row2 = db.execute("SELECT * FROM requests WHERE item = 'tmdb-movie:102'").fetchone()
    assert row2["via"] == "overseerr"



@pytest.mark.anyio
async def test_a_collection_profile_overrides_the_default_and_falls_back_when_gone(env):
    service, mock, db, box, config, client = env
    settings = service.load_settings()
    settings.enabled = True
    settings.radarr.quality_profile = "HD-1080p"
    service.save_settings(settings)

    await service.request([Item(item="tmdb-movie:603", title="The Matrix", year=1999)], library="Movies", collection_id=1, now=T0, profile="Ultra-HD")
    await service.request([Item(item="tmdb-movie:604", title="The Matrix Reloaded", year=2003)], library="Movies", collection_id=1, now=T0, profile="Deleted profile")

    by_tmdb = {m["tmdbId"]: m for m in mock.radarr_movies.values()}
    assert by_tmdb[603]["qualityProfileId"] == 6  # the collection's choice
    assert by_tmdb[604]["qualityProfileId"] == 4  # no longer in Radarr: the default from Settings → Requests
