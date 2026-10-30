import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from test_services import MDBLIST_KEY, FakeServices

from kometa_studio import arr, usage
from kometa_studio.app import create_app
from kometa_studio.arr import Arr
from kometa_studio.db import get_setting, open_database, set_setting
from kometa_studio.kometa_command import RunRequest
from kometa_studio.settings import Settings

T0 = datetime(2026, 10, 30, 20, 0, tzinfo=UTC)
FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"


def timings(logs: Path, buckets: list[tuple[str, int]]) -> Path:
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"timings-{time.time_ns()}.json"
    path.write_text(json.dumps({"meta": {}, "buckets": [{"library": "Movies", "source": source, "calls": calls} for source, calls in buckets]}))
    return path


def test_kometas_timings_add_up_per_service(tmp_path):
    timings(tmp_path / "logs", [("tmdb", 40), ("mdblist", 3), ("tmdb", 2)])
    assert usage.read_timings(tmp_path / "logs", time.time() - 5) == {"tmdb": 42, "mdblist": 3}
    assert usage.read_timings(tmp_path / "logs", time.time() + 5) is None  # older than the run
    assert usage.read_timings(tmp_path / "nowhere", 0) is None


def finished_run(db, run_id, at: datetime, calls: dict | None):
    with db:
        db.execute(
            "INSERT INTO runs (id, request, status, trigger, queued_at, finished_at, api_calls) VALUES (?, '{}', 'succeeded', 'manual', ?, ?, ?)",
            (run_id, at.strftime("%Y-%m-%dT%H:%M:%SZ"), at.strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(calls) if calls else None),
        )


def test_runs_after_imports_wait_at_80_percent_of_mdblists_allowance(tmp_path):
    db = open_database(tmp_path / "studio.db")
    set_setting(db, usage.USAGE, {"limit": 1000, "used": 770, "checked_at": "2026-10-30T19:00:00Z"})
    finished_run(db, 1, T0 - timedelta(hours=3), {"mdblist": 500})  # before MDBList's answer: already in it
    assert usage.held(db, T0) is None
    finished_run(db, 2, T0 - timedelta(minutes=30), {"mdblist": 30, "tmdb": 900})
    assert usage.mdblist_estimate(db, T0)["used"] == 800
    assert usage.held(db, T0).startswith("MDBList has used 800 of today's 1000 requests")
    assert usage.today(db, T0) == {"mdblist": 530, "tmdb": 900}
    # A new day: yesterday's answer says nothing.
    assert usage.held(db, T0 + timedelta(hours=5)) is None

    class Runner:
        queued: list = []

        def enqueue(self, request, trigger="manual"):
            self.queued.append(request)
            return 1

    set_setting(db, arr.RUNS, {"radarr": {"enabled": True}})
    service = Arr(db, Runner(), None, None, None)
    service.record("radarr", ["Flow (2024)"], T0 - timedelta(minutes=20))
    assert service.tick(T0) == []
    assert service.pending()["radarr"]["held"].startswith("MDBList has used 800")
    set_setting(db, usage.USAGE, {"limit": 1000, "used": 100, "checked_at": "2026-10-30T19:59:00Z"})
    assert service.tick(T0) == [1]
    db.close()


def test_mdblist_is_asked_at_most_every_15_minutes(tmp_path):
    db = open_database(tmp_path / "studio.db")
    config = tmp_path / "config.yml"
    config.write_text(f"mdblist:\n  apikey: {MDBLIST_KEY}\n")
    fake = FakeServices()

    async def scenario():
        async with httpx.AsyncClient(transport=fake.transport()) as http:
            await usage.refresh_mdblist(db, http, config, T0)
            await usage.refresh_mdblist(db, http, config, T0 + timedelta(minutes=10))
            await usage.refresh_mdblist(db, http, config, T0 + timedelta(minutes=16))

    asyncio.run(scenario())
    assert len(fake.requests) == 2
    assert get_setting(db, usage.USAGE) == {"limit": 1000, "used": 312, "checked_at": "2026-10-30T20:16:00Z"}
    db.close()


def test_every_run_records_its_calls_per_service(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yml").write_text("libraries: {}\n")
    settings = Settings(data_dir=tmp_path / "data", kometa_python=Path(sys.executable), kometa_entry=FAKE_KOMETA, kometa_config=config / "config.yml", kill_after=0.5)
    (config / "fake.json").write_text(json.dumps({"lines": ["Kometa ran"]}))
    with TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000)) as client:
        runner = client.app.state.runner
        hook = next(h for h in runner.hooks if isinstance(h, usage.ApiCalls))

        async def write_timings_during_the_run(request, say):
            after = await usage.ApiCalls.before_run(hook, request, say)
            timings(config / "logs", [("tmdb", 12), ("mdblist", 2)])
            return after

        hook.before_run = write_timings_during_the_run
        run_id = client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"]
        deadline = time.monotonic() + 15
        while client.get(f"/api/v1/runs/{run_id}").json()["status"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(0.05)
        run = client.get(f"/api/v1/runs/{run_id}").json()
        page = client.get("/api/v1/usage").json()
    assert "--timings" in run["command"]
    assert page["today"] == {"tmdb": 12, "mdblist": 2}
    assert page["mdblist"] is None and page["limit_share"] == 0.8
