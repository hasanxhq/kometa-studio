import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from kometa_studio import arr, maintainerr
from kometa_studio.app import create_app
from kometa_studio.db import set_setting
from kometa_studio.jobs import live_state, run_title
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"


def test_the_live_message_and_progress_come_from_the_log():
    lines = [
        "|====================================|",
        "| TV Shows Library Overlays          |",
        "| (3/230) Westworld                  |",
        "|   Overlay Update Not Needed        |",
        "|------------------------------------|",
    ]
    assert live_state(lines) == ("Overlay Update Not Needed", {"value": 3, "max": 230})
    # Progress from long ago belongs to an earlier step.
    assert live_state(lines[:3] + ["| Reading config |"] * 80) == ("Reading config", None)
    assert live_state([]) == (None, None)


def test_run_titles():
    assert run_title({"mode": "overlays", "libraries": ["TV Shows"]}) == "Kometa: Overlays · TV Shows"
    assert run_title({"mode": "all"}) == "Kometa: Everything"


def make_client(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yml").write_text("libraries: {}\n")
    settings = Settings(
        data_dir=tmp_path / "data", kometa_python=Path(sys.executable), kometa_entry=FAKE_KOMETA, kometa_config=config / "config.yml", kill_after=0.5
    )
    return TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000)), config


def jobs(client) -> dict[str, dict]:
    return {job["id"]: job for job in client.get("/api/v1/jobs").json()["jobs"]}


def wait_until(check, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError("never happened")


def test_running_queued_and_finished_runs(tmp_path):
    client, config = make_client(tmp_path)
    release = tmp_path / "go"
    (config / "fake.json").write_text(json.dumps({"lines": ["TV Shows Library Overlays", "(3/10) Westworld"], "wait_for": str(release)}))
    with client:
        first = client.post("/api/v1/runs", json={"mode": "overlays", "libraries": ["TV Shows"]}).json()["id"]
        second = client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"]
        running = wait_until(lambda: (j := jobs(client).get(f"run-{first}")) and j["progress"] and j)
        queued = jobs(client)[f"run-{second}"]
        client.post("/api/v1/tasks/full_backup/run")
        backup = wait_until(lambda: (j := jobs(client).get("task-full_backup")) and j["message"] and j)
        release.touch()
        done = wait_until(lambda: (j := jobs(client).get(f"run-{first}")) and j["status"] == "completed" and j)
    assert running | {"started_at": None} == {
        "id": f"run-{first}",
        "kind": "run",
        "title": "Kometa: Overlays · TV Shows",
        "status": "running",
        "label": "Running",
        "message": "(3/10) Westworld",
        "progress": {"value": 3, "max": 10},
        "started_at": None,
        "finished_at": None,
        "link": f"/activity/queue/{first}",
        "run_id": first,
        "cancellable": True,
    }
    assert (queued["status"], queued["message"], queued["cancellable"]) == ("pending", "Next in the queue", True)
    assert (backup["status"], backup["message"]) == ("running", f"Waiting for Kometa's run #{first} to finish")
    assert (done["label"], done["cancellable"], done["progress"]) == ("Succeeded", False, None)


def test_waiting_imports_tasks_and_maintainerr(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        db = client.app.state.db
        set_setting(db, arr.PENDING, {"first_at": "2026-10-30T20:00:00Z", "last_at": "2026-10-30T20:01:00Z", "imports": 2, "titles": ["Flow (2024)"], "kinds": ["radarr"]})
        with db:
            db.execute(
                "UPDATE tasks SET last_status = 'failed', last_started_at = '2026-10-30T04:30:00Z', "
                "last_finished_at = '2026-10-30T04:30:05Z', last_message = 'Not enough disk space' WHERE name = 'full_backup'"
            )
        set_setting(db, maintainerr.SETTINGS, {"url": "http://maintainerr.test"})
        set_setting(db, maintainerr.PENDING_PROCESS, True)
        found = jobs(client)
    assert found["arr-pending"]["status"] == "pending" and "2 imports (Flow (2024))" in found["arr-pending"]["message"]
    assert (found["task-full_backup"]["status"], found["task-full_backup"]["message"]) == ("failed", "Not enough disk space")
    assert "task-full_check" not in found  # never run
    assert found["maintainerr-resume"]["label"] == "Retrying"
