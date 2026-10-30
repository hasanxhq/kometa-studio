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
    set_setting(db, arr.RUNS, {"enabled": True, "mode": "all", "wait_minutes": 10, "libraries": {"radarr": ["Movies"], "sonarr": ["TV Shows"]}})
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
        assert service.pending()["titles"] == ["Dune: Part Two (2024)"]
        assert service.tick(T0 + timedelta(minutes=11)) is None
        assert service.tick(T0 + timedelta(minutes=12)) == 1
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
        return service.pending()["titles"]

    assert run(scenario, fake) == ["Flow (2024)"]


def test_a_connection_entered_in_studio_wins_and_its_key_stays_secret(setup):
    db, fake, config, tmp_path = setup
    box = SecretBox.load_or_create(tmp_path / "data")
    set_setting(db, arr.CONNECTIONS, {"sonarr": {"source": "studio", "url": SONARR_URL, "api_key": box.encrypt(SONARR_KEY)}, "radarr": {"source": "off"}})

    async def scenario(http):
        service = Arr(db, RecordingRunner(), http, box, config)
        await service.poll(T0)
        fake.imported("sonarr", "Avatar: The Last Airbender", 2024, T0 + timedelta(minutes=1))
        return await service.poll(T0 + timedelta(minutes=2))

    assert run(scenario, fake) == {"sonarr": 1}  # radarr is off, though config.yml has it
    assert SONARR_KEY not in str(get_setting(db, arr.CONNECTIONS))


def test_problems_are_kept_for_the_page_and_health(setup):
    db, fake, config, tmp_path = setup
    fake.down.add("radarr")
    run(lambda http: make_arr(db, http, config, tmp_path).poll(T0), fake)
    status = get_setting(db, "arr.status.radarr")
    assert status["ok"] is False and "Can't connect" in status["error"]


def test_switched_off_doesnt_poll(setup):
    db, fake, config, tmp_path = setup
    set_setting(db, arr.RUNS, {"enabled": False})
    assert run(lambda http: make_arr(db, http, config, tmp_path).poll(T0), fake) == {}
    assert fake.requests == []


def test_radarr_and_sonarr_together_run_both_their_libraries(setup):
    db, _, config, tmp_path = setup
    service = Arr(db, RecordingRunner(), None, None, config)
    service.record("radarr", ["Dune: Part Two (2024)"], T0)
    service.record("sonarr", ["Avatar: The Last Airbender (2024)"], T0 + timedelta(minutes=1))
    assert service.pending()["due_at"] == "2026-10-30T20:11:00Z"
    service.tick(T0 + timedelta(minutes=11))
    assert service.runner.queued[0][0].libraries == ["Movies", "TV Shows"]


def test_a_steady_stream_still_runs_within_an_hour(setup):
    db, _, config, tmp_path = setup
    service = Arr(db, RecordingRunner(), None, None, config)
    for minute in range(0, 70, 5):
        service.record("radarr", ["Something"], T0 + timedelta(minutes=minute))
        service.tick(T0 + timedelta(minutes=minute, seconds=30))
    assert len(service.runner.queued) == 1


def test_no_libraries_chosen_means_every_library(setup):
    db, _, config, tmp_path = setup
    set_setting(db, arr.RUNS, {"enabled": True, "mode": "overlays", "libraries": {"radarr": [], "sonarr": []}})
    service = Arr(db, RecordingRunner(), None, None, config)
    service.record("radarr", ["Dune"], T0)
    service.tick(T0 + timedelta(minutes=10))
    assert service.runner.queued[0][0] == RunRequest(mode="overlays")


# --- API ----------------------------------------------------------------------------


def make_client(tmp_path, fake):
    (tmp_path / "config.yml").write_text(CONFIG)
    app = create_app(
        Settings(data_dir=tmp_path / "data", kometa_config=tmp_path / "config.yml"), static_dir=tmp_path / "no-static", http_transport=fake.transport()
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def test_connect_page_uses_config_yml_and_tests_a_connection_entered_by_hand(tmp_path):
    fake = FakeArr()
    with make_client(tmp_path, fake) as client:
        state = client.get("/api/v1/settings/arr").json()
        assert state["connections"]["radarr"] == {"source": "config", "url": None, "has_key": False, "config_url": RADARR_URL, "status": None}
        assert state["connections"]["sonarr"]["config_url"] is None

        assert client.post("/api/v1/settings/arr/radarr/test", json={"source": "config"}).json() == {"ok": True, "app": "Radarr", "version": "5.14.0.9383"}
        wrong = client.post("/api/v1/settings/arr/sonarr/test", json={"source": "studio", "url": SONARR_URL, "api_key": "nope"}).json()
        assert wrong == {"ok": False, "error": "The API key was rejected"}
        swapped = client.post("/api/v1/settings/arr/sonarr/test", json={"source": "studio", "url": RADARR_URL, "api_key": RADARR_KEY}).json()
        assert swapped == {"ok": False, "error": "That's Radarr, not Sonarr"}

        saved = client.put("/api/v1/settings/arr/sonarr", json={"source": "studio", "url": SONARR_URL, "api_key": SONARR_KEY}).json()
        assert saved["connections"]["sonarr"] | {"status": None} == {"source": "studio", "url": SONARR_URL, "has_key": True, "config_url": None, "status": None}
        assert SONARR_KEY not in client.get("/api/v1/settings/arr").text
        # Saving again without the key keeps it.
        assert client.put("/api/v1/settings/arr/sonarr", json={"source": "studio", "url": SONARR_URL}).status_code == 200
        assert client.post("/api/v1/settings/arr/sonarr/test", json={"source": "studio", "url": SONARR_URL}).json()["ok"] is True
        assert client.put("/api/v1/settings/arr/lidarr", json={"source": "off"}).status_code == 404


def test_the_webhook_is_gone(tmp_path):
    with make_client(tmp_path, FakeArr()) as client:
        assert client.post("/api/v1/hooks/arr?token=x", json={}).status_code in (401, 404, 405)
