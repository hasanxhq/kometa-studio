import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakearr import RADARR_KEY, RADARR_URL, SONARR_KEY, SONARR_URL, FakeArr
from fastapi.testclient import TestClient

from kometa_studio import arr
from kometa_studio.app import create_app
from kometa_studio.arr import Arr
from kometa_studio.crypto import SecretBox
from kometa_studio.db import get_setting, open_database, set_setting
from kometa_studio.kometa_command import RunRequest
from kometa_studio.settings import Settings

T0 = datetime(2026, 10, 30, 20, 0, tzinfo=UTC)

CONFIG = f"""\
libraries:
  Movies: {{}}
radarr:
  url: {RADARR_URL}
  token: {RADARR_KEY}
"""


class RecordingRunner:
    def __init__(self) -> None:
        self.queued: list[tuple[RunRequest, str]] = []

    def enqueue(self, request: RunRequest, trigger: str = "manual") -> int:
        self.queued.append((request, trigger))
        return len(self.queued)


@pytest.fixture
def setup(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(CONFIG)
    db = open_database(tmp_path / "studio.db")
    set_setting(
        db,
        arr.RUNS,
        {"radarr": {"enabled": True, "mode": "all", "wait_minutes": 10, "libraries": ["Movies"]}, "sonarr": {"enabled": True, "wait_minutes": 30, "libraries": ["TV Shows"]}},
    )
    fake = FakeArr()
    yield db, fake, config, tmp_path
    db.close()


def run(coro_factory, fake):
    async def go():
        async with httpx.AsyncClient(transport=fake.transport()) as http:
            return await coro_factory(http)

    return asyncio.run(go())


def make_arr(db, http, config, tmp_path) -> Arr:
    return Arr(db, RecordingRunner(), http, SecretBox.load_or_create(tmp_path / "data"), config)


def test_imports_found_in_radarrs_history_queue_one_run_after_it_goes_quiet(setup):
    db, fake, config, tmp_path = setup

    async def scenario(http):
        service = make_arr(db, http, config, tmp_path)
        assert await service.poll(T0) == {"radarr": 0}  # first look: history before now isn't news
        fake.imported("radarr", "Dune: Part Two", 2024, T0 + timedelta(minutes=1))
        fake.imported("radarr", "Dune: Part Two", 2024, T0 + timedelta(minutes=1, seconds=5))  # an upgrade, say
        assert await service.poll(T0 + timedelta(minutes=2)) == {"radarr": 2}
        assert await service.poll(T0 + timedelta(minutes=4)) == {"radarr": 0}  # the same records aren't counted twice
        assert service.pending()["radarr"]["titles"] == ["Dune: Part Two (2024)"]
        assert service.tick(T0 + timedelta(minutes=11)) == []
        assert service.tick(T0 + timedelta(minutes=12)) == [1]
        return service.runner.queued

    assert run(scenario, fake) == [(RunRequest(mode="all", libraries=["Movies"]), "arr")]


def test_imports_made_while_studio_was_off_are_found(setup):
    db, fake, config, tmp_path = setup

    async def scenario(http):
        service = make_arr(db, http, config, tmp_path)
        await service.poll(T0)
        fake.imported("radarr", "Old News", 2020, T0 - timedelta(hours=1))
        fake.imported("radarr", "Flow", 2024, T0 + timedelta(hours=5))  # Studio was off then
        fake.imported("radarr", "Too Long Ago", 2024, T0 - timedelta(days=3))
        await service.poll(T0 + timedelta(hours=8))
        return service.pending()["radarr"]["titles"]

    assert run(scenario, fake) == ["Flow (2024)"]


def test_the_connection_is_kometas_with_studios_proxy_login(setup):
    db, fake, config, tmp_path = setup
    fake.proxy_login = ("hasan", "seedbox-pass")
    config.write_text(CONFIG + f"sonarr:\n  url: {SONARR_URL}\n  token: {SONARR_KEY}\n")
    box = SecretBox.load_or_create(tmp_path / "data")
    set_setting(db, arr.CONNECTIONS, {"sonarr": {"username": "hasan", "password": box.encrypt("seedbox-pass")}})

    async def scenario(http):
        service = Arr(db, RecordingRunner(), http, box, config)
        await service.poll(T0)
        fake.imported("sonarr", "Avatar: The Last Airbender", 2024, T0 + timedelta(minutes=1))
        return await service.poll(T0 + timedelta(minutes=2))

    assert run(scenario, fake) == {"radarr": 0, "sonarr": 1}
    assert "seedbox-pass" not in str(get_setting(db, arr.CONNECTIONS))


def test_problems_are_kept_for_the_page_and_health(setup):
    db, fake, config, tmp_path = setup
    fake.down.add("radarr")
    run(lambda http: make_arr(db, http, config, tmp_path).poll(T0), fake)
    status = get_setting(db, "arr.status.radarr")
    assert status["ok"] is False and "Can't connect" in status["error"]


def test_switched_off_doesnt_poll(setup):
    db, fake, config, tmp_path = setup
    set_setting(db, arr.RUNS, {"radarr": {"enabled": False}, "sonarr": {"enabled": False}})
    assert run(lambda http: make_arr(db, http, config, tmp_path).poll(T0), fake) == {}
    assert fake.requests == []


def test_radarr_and_sonarr_each_run_with_their_own_settings(setup):
    db, _, config, tmp_path = setup
    service = Arr(db, RecordingRunner(), None, None, config)
    service.record("radarr", ["Dune: Part Two (2024)"], T0)
    service.record("sonarr", ["Avatar: The Last Airbender (2024)"], T0 + timedelta(minutes=1))
    assert service.pending()["radarr"]["due_at"] == "2026-10-30T20:10:00Z"
    assert service.pending()["sonarr"]["due_at"] == "2026-10-30T20:31:00Z"
    service.tick(T0 + timedelta(minutes=11))
    service.tick(T0 + timedelta(minutes=31))
    assert [request for request, _ in service.runner.queued] == [
        RunRequest(mode="all", libraries=["Movies"]),
        RunRequest(mode="all", libraries=["TV Shows"]),
    ]


def test_a_steady_stream_still_runs_within_an_hour(setup):
    db, _, config, tmp_path = setup
    service = Arr(db, RecordingRunner(), None, None, config)
    for minute in range(0, 70, 5):
        service.record("radarr", ["Something"], T0 + timedelta(minutes=minute))
        service.tick(T0 + timedelta(minutes=minute, seconds=30))
    assert len(service.runner.queued) == 1


def test_no_libraries_chosen_means_every_library(setup):
    db, _, config, tmp_path = setup
    set_setting(db, arr.RUNS, {"radarr": {"enabled": True, "mode": "overlays", "libraries": []}})
    service = Arr(db, RecordingRunner(), None, None, config)
    service.record("radarr", ["Dune"], T0)
    service.tick(T0 + timedelta(minutes=10))
    assert service.runner.queued[0][0] == RunRequest(mode="overlays")


def test_settings_and_a_pending_run_from_before_each_app_had_its_own_carry_over(setup):
    db, _, config, tmp_path = setup
    set_setting(db, arr.RUNS, {"enabled": True, "mode": "overlays", "wait_minutes": 5, "libraries": {"radarr": ["Movies"], "sonarr": []}})
    set_setting(db, arr.PENDING, {"first_at": "2026-10-30T20:00:00Z", "last_at": "2026-10-30T20:00:00Z", "imports": 2, "titles": ["Flow (2024)"], "kinds": ["radarr"]})
    settings = arr.load_settings(db)
    assert settings.radarr == arr.AppRuns(enabled=True, mode="overlays", wait_minutes=5, libraries=["Movies"])
    assert settings.sonarr == arr.AppRuns(enabled=True, mode="overlays", wait_minutes=5, libraries=[])
    service = Arr(db, RecordingRunner(), None, None, config)
    assert list(service.pending()) == ["radarr"] and get_setting(db, arr.PENDING) is None


# --- API ----------------------------------------------------------------------------


def make_client(tmp_path, fake):
    (tmp_path / "config.yml").write_text(CONFIG)
    app = create_app(
        Settings(data_dir=tmp_path / "data", kometa_config=tmp_path / "config.yml"), static_dir=tmp_path / "no-static", http_transport=fake.transport()
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def test_the_connect_page_reads_config_yml(tmp_path):
    with make_client(tmp_path, FakeArr()) as client:
        state = client.get("/api/v1/settings/arr").json()
    assert state["connections"]["radarr"] == {
        "url": RADARR_URL,
        "token": "…-key",
        "root_folder_path": None,
        "quality_profile": None,
        "username": None,
        "has_password": False,
        "status": None,
    }
    assert state["connections"]["sonarr"]["url"] is None
    assert RADARR_KEY not in str(state)


def test_a_test_says_what_answered_with_its_folders_and_profiles(tmp_path):
    with make_client(tmp_path, FakeArr()) as client:
        kept_key = client.post("/api/v1/settings/arr/radarr/test", json={"url": RADARR_URL}).json()
        wrong = client.post("/api/v1/settings/arr/sonarr/test", json={"url": SONARR_URL, "api_key": "nope"}).json()
        swapped = client.post("/api/v1/settings/arr/sonarr/test", json={"url": RADARR_URL, "api_key": RADARR_KEY}).json()
    assert kept_key == {"ok": True, "app": "Radarr", "version": "5.14.0.9383", "root_folders": ["/movies"], "quality_profiles": ["HD-1080p", "Ultra-HD"]}
    assert wrong == {"ok": False, "error": "The API key was rejected"}
    assert swapped == {"ok": False, "error": "That's Radarr, not Sonarr"}


def test_saving_tests_again_then_writes_kometas_section(tmp_path):
    entered = {"url": SONARR_URL, "api_key": SONARR_KEY, "root_folder_path": "/tv", "quality_profile": "HD-1080p"}
    with make_client(tmp_path, FakeArr()) as client:
        refused = client.put("/api/v1/settings/arr/sonarr", json=entered | {"api_key": "nope"})
        unknown = client.put("/api/v1/settings/arr/sonarr", json=entered | {"root_folder_path": "/films"})
        assert "sonarr" not in (tmp_path / "config.yml").read_text()
        saved = client.put("/api/v1/settings/arr/sonarr", json=entered)
        page = client.get("/api/v1/settings/arr").text
    assert refused.status_code == 422 and "API key was rejected" in refused.json()["detail"]
    assert unknown.status_code == 422 and "no root folder /films" in unknown.json()["detail"]
    assert saved.status_code == 200
    section = arr.config_section(tmp_path / "config.yml", "sonarr")
    assert section == {"url": SONARR_URL, "token": SONARR_KEY, "root_folder_path": "/tv", "quality_profile": "HD-1080p"}
    assert "radarr:" in (tmp_path / "config.yml").read_text()  # the rest of the file is kept
    assert SONARR_KEY not in page
    assert list((tmp_path / "data" / "backups").glob("*/config.yml"))


def test_each_app_has_its_own_run_settings(tmp_path):
    with make_client(tmp_path, FakeArr()) as client:
        state = client.put("/api/v1/settings/arr/sonarr/runs", json={"enabled": True, "mode": "overlays", "wait_minutes": 20, "libraries": ["TV Shows"]}).json()
        assert client.put("/api/v1/settings/arr/lidarr/runs", json={}).status_code == 404
    assert state["settings"]["sonarr"] == {"enabled": True, "trigger": "any", "mode": "overlays", "wait_minutes": 20, "libraries": ["TV Shows"]}
    assert state["settings"]["radarr"]["enabled"] is False


def test_removing_an_app_takes_it_out_of_config_yml(tmp_path):
    with make_client(tmp_path, FakeArr()) as client:
        state = client.delete("/api/v1/settings/arr/radarr").json()
    assert state["connections"]["radarr"]["url"] is None
    assert "radarr" not in (tmp_path / "config.yml").read_text()


def test_the_webhook_is_gone(tmp_path):
    with make_client(tmp_path, FakeArr()) as client:
        assert client.post("/api/v1/hooks/arr?token=x", json={}).status_code in (401, 404, 405)


def test_a_sonarr_behind_a_seedbox_proxy(tmp_path):
    fake = FakeArr()
    fake.proxy_login = ("hasan", "seedbox-pass")
    entered = {"url": SONARR_URL, "api_key": SONARR_KEY}
    with make_client(tmp_path, fake) as client:
        missing = client.post("/api/v1/settings/arr/sonarr/test", json=entered).json()
        refused = client.post("/api/v1/settings/arr/sonarr/test", json=entered | {"username": "hasan", "password": "wrong"}).json()
        saved = client.put("/api/v1/settings/arr/sonarr", json=entered | {"username": "hasan", "password": "seedbox-pass"}).json()
        assert "seedbox-pass" not in client.get("/api/v1/settings/arr").text
        kept = client.post("/api/v1/settings/arr/sonarr/test", json={"url": SONARR_URL, "username": "hasan"}).json()
    assert missing == {"ok": False, "error": "The proxy in front of it wants a username and password"}
    assert refused == {"ok": False, "error": "The proxy in front of it wants a username and password (these were refused)"}
    assert saved["connections"]["sonarr"]["username"] == "hasan" and saved["connections"]["sonarr"]["has_password"] is True
    assert kept["ok"] is True
