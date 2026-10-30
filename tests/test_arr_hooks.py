from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kometa_studio import arr_hooks
from kometa_studio.app import create_app
from kometa_studio.arr_hooks import ArrHooks
from kometa_studio.db import open_database, set_setting
from kometa_studio.kometa_command import RunRequest
from kometa_studio.settings import Settings

T0 = datetime(2026, 10, 30, 20, 0, tzinfo=UTC)

# Shaped like Radarr v5 and Sonarr v4's webhook bodies (trimmed).
RADARR_IMPORT = {"eventType": "Download", "instanceName": "Radarr", "movie": {"id": 1, "title": "Dune: Part Two", "year": 2024}, "isUpgrade": False}
SONARR_IMPORT = {"eventType": "Download", "instanceName": "Sonarr", "series": {"id": 7, "title": "Avatar: The Last Airbender", "year": 2024}}
RADARR_TEST = {"eventType": "Test", "instanceName": "Radarr", "movie": {"id": 1, "title": "Test Title", "year": 1970}}


class RecordingRunner:
    def __init__(self, db):
        self.db = db
        self.queued: list[tuple[RunRequest, str]] = []

    def enqueue(self, request: RunRequest, trigger: str = "manual") -> int:
        self.queued.append((request, trigger))
        with self.db:
            return self.db.execute("INSERT INTO runs (request, trigger) VALUES (?, ?)", (request.model_dump_json(), trigger)).lastrowid


@pytest.fixture
def hooks(tmp_path):
    db = open_database(tmp_path / "studio.db")
    set_setting(db, arr_hooks.SETTINGS, {"enabled": True, "mode": "all", "wait_minutes": 10, "libraries": {"radarr": ["Movies"], "sonarr": ["TV Shows", "Anime"]}})
    yield ArrHooks(db, RecordingRunner(db))
    db.close()


def test_a_burst_of_imports_becomes_one_run_after_it_goes_quiet(hooks):
    for minute in range(5):
        assert hooks.receive(RADARR_IMPORT, T0 + timedelta(minutes=minute))["action"] == "pending"
    assert hooks.tick(T0 + timedelta(minutes=13)) is None  # 9 minutes after the last import
    run_id = hooks.tick(T0 + timedelta(minutes=14))
    assert run_id is not None
    assert hooks.runner.queued == [(RunRequest(mode="all", libraries=["Movies"]), "arr")]
    assert hooks.tick(T0 + timedelta(minutes=15)) is None  # nothing pending any more


def test_a_steady_stream_still_runs_within_an_hour(hooks):
    for minute in range(0, 70, 5):
        hooks.receive(RADARR_IMPORT, T0 + timedelta(minutes=minute))
        hooks.tick(T0 + timedelta(minutes=minute, seconds=30))
    assert len(hooks.runner.queued) == 1  # at the hour, though imports kept coming


def test_radarr_and_sonarr_together_run_both_their_libraries(hooks):
    hooks.receive(RADARR_IMPORT, T0)
    hooks.receive(SONARR_IMPORT, T0 + timedelta(minutes=1))
    pending = hooks.pending()
    assert pending["titles"] == ["Dune: Part Two (2024)", "Avatar: The Last Airbender (2024)"]
    assert pending["due_at"] == "2026-10-30T20:11:00Z"
    hooks.tick(T0 + timedelta(minutes=11))
    assert hooks.runner.queued[0][0].libraries == ["Movies", "TV Shows", "Anime"]


def test_no_libraries_chosen_means_every_library(hooks):
    set_setting(hooks.db, arr_hooks.SETTINGS, {"enabled": True, "mode": "overlays", "libraries": {"radarr": [], "sonarr": ["TV Shows"]}})
    hooks.receive(RADARR_IMPORT, T0)
    hooks.tick(T0 + timedelta(minutes=10))
    assert hooks.runner.queued[0][0] == RunRequest(mode="overlays")


def test_an_equal_run_already_queued_is_enough(hooks):
    queued = hooks.runner.enqueue(RunRequest(mode="all", libraries=["Movies"]), "manual")
    hooks.receive(RADARR_IMPORT, T0)
    assert hooks.tick(T0 + timedelta(minutes=10)) == queued
    assert len(hooks.runner.queued) == 1


@pytest.mark.parametrize(
    ("payload", "action"),
    [
        (RADARR_TEST, "test"),
        ({"eventType": "Grab", "movie": {"title": "Dune"}}, "ignored"),
        ({"eventType": "Download"}, "ignored"),  # neither a movie nor a series
    ],
)
def test_only_imports_queue_runs(hooks, payload, action):
    assert hooks.receive(payload, T0)["action"] == action
    assert hooks.pending() is None


def test_switched_off_ignores_imports(hooks):
    set_setting(hooks.db, arr_hooks.SETTINGS, {"enabled": False})
    assert hooks.receive(RADARR_IMPORT, T0)["action"] == "ignored"
    assert hooks.pending() is None


# --- API ----------------------------------------------------------------------------


def make_client(tmp_path, client=("127.0.0.1", 50000)):
    return TestClient(create_app(Settings(data_dir=tmp_path / "data"), static_dir=tmp_path / "no-static"), client=client)


def test_the_webhook_checks_its_token_and_works_without_sign_in(tmp_path):
    with make_client(tmp_path) as local:
        settings = local.get("/api/v1/settings/arr").json()
        local.put("/api/v1/settings/arr", json=settings["settings"] | {"enabled": True})
        path = settings["path"]
    with make_client(tmp_path, ("8.8.8.8", 50000)) as remote:  # Radarr on the seedbox, say
        assert remote.post("/api/v1/hooks/arr?token=wrong", json=RADARR_IMPORT).status_code == 403
        assert remote.post(path, json=RADARR_IMPORT).json()["action"] == "pending"
        assert remote.get("/api/v1/settings/arr").status_code == 401  # the settings themselves need sign-in
    with make_client(tmp_path) as local:
        body = local.get("/api/v1/settings/arr").json()
        assert body["pending"]["titles"] == ["Dune: Part Two (2024)"]
        assert body["last_event"]["event"] == "Download"
        new_path = local.post("/api/v1/settings/arr/token").json()["path"]
        assert new_path != path
        assert local.post(path, json=RADARR_TEST).status_code == 403
