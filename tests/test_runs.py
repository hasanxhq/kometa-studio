import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
FINISHED = {"succeeded", "failed", "cancelled", "interrupted", "timed_out"}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config" / "config.yml"
    path.parent.mkdir()
    path.write_text("plex:\n  url: http://plex:32400\n  token: t\n")
    return path


def plan(config: Path, **behaviour) -> None:
    (config.parent / "fake.json").write_text(json.dumps(behaviour))


def make_client(tmp_path, **settings):
    defaults = {
        "data_dir": tmp_path / "data",
        "kometa_python": Path(sys.executable),
        "kometa_entry": FAKE_KOMETA,
        "kometa_config": tmp_path / "config" / "config.yml",
        "kill_after": 0.5,
    }
    app = create_app(Settings(**(defaults | settings)), static_dir=tmp_path / "no-static")
    return TestClient(app)


def wait_for(client, run_id, statuses=FINISHED, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} still {run['status']}")


def wait_for_flags(client):
    deadline = time.monotonic() + 15
    while client.get("/api/v1/kometa").json()["flags"] is None:
        assert time.monotonic() < deadline, "the --help probe never finished"
        time.sleep(0.05)


def post_event(client, payload, token=None):
    token = token or client.app.state.runner.webhook_url.split("token=")[1]
    return client.post(f"/api/v1/kometa/events?token={token}", json=payload)


def test_a_run_streams_its_output_to_a_log(tmp_path, config):
    plan(config, lines=["Starting Kometa", "Finished"])
    with make_client(tmp_path) as client:
        wait_for_flags(client)
        created = client.post("/api/v1/runs", json={"mode": "collections", "libraries": ["Movies", "TV Shows"]})
        assert created.status_code == 201
        run = wait_for(client, created.json()["id"])
        log = client.get(f"/api/v1/runs/{run['id']}/log").text

    assert run["status"] == "succeeded"
    assert run["exit_code"] == 0
    assert "--run --no-countdown --read-only-config --ignore-ghost --collections-only" in run["command"]
    assert "--run-libraries 'Movies|TV Shows'" in run["command"]
    assert "Starting Kometa\nFinished\n" in log
    assert log.endswith("Kometa Studio: run succeeded (exit code 0)\n")
    # Kometa's webhooks now reach Studio, and the user's settings are untouched.
    text = config.read_text()
    assert "api/v1/kometa/events?token=" in text and "url: http://plex:32400" in text


def test_kometa_flags_come_from_its_help(tmp_path, config):
    with make_client(tmp_path) as client:
        wait_for_flags(client)
        info = client.get("/api/v1/kometa").json()
    assert "--overlays-only" in info["flags"]
    assert info["problem"] is None


def test_a_failing_run(tmp_path, config):
    plan(config, lines=["Config Error: tmdb apikey is required"], exit=1)
    with make_client(tmp_path) as client:
        run = wait_for(client, client.post("/api/v1/runs", json={}).json()["id"])
    assert (run["status"], run["exit_code"], run["error"]) == ("failed", 1, "Kometa exited with code 1")


def test_missing_config_fails_with_a_reason(tmp_path):
    with make_client(tmp_path) as client:
        run = wait_for(client, client.post("/api/v1/runs", json={}).json()["id"])
        log = client.get(f"/api/v1/runs/{run['id']}/log").text
    assert run["status"] == "failed"
    assert "Connect Plex in Settings → Plex first" in run["error"]
    assert "Connect Plex" in log


def test_runs_queue_one_at_a_time_without_duplicates(tmp_path, config):
    release = tmp_path / "release"
    plan(config, lines=["working"], wait_for=str(release))
    with make_client(tmp_path) as client:
        first = client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"]
        wait_for(client, first, {"running"})
        second = client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"]
        again = client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"]
        assert again == second
        listed = client.get("/api/v1/runs").json()
        assert listed["current"] == first
        assert [r["status"] for r in listed["runs"][:2]] == ["running", "queued"]

        release.touch()
        assert wait_for(client, first)["status"] == "succeeded"
        assert wait_for(client, second)["status"] == "succeeded"


def test_cancelling_a_queued_run(tmp_path, config):
    release = tmp_path / "release"
    plan(config, wait_for=str(release))
    with make_client(tmp_path) as client:
        first = client.post("/api/v1/runs", json={}).json()["id"]
        wait_for(client, first, {"running"})
        queued = client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"]
        assert client.post(f"/api/v1/runs/{queued}/cancel").json()["status"] == "cancelled"
        release.touch()
        wait_for(client, first)
        assert client.post(f"/api/v1/runs/{queued}/cancel").status_code == 409


def test_cancelling_stops_kometa_and_its_worker(tmp_path, config):
    child_pid = tmp_path / "child.pid"
    plan(config, lines=["working"], wait_for=str(tmp_path / "never"), child_pid=str(child_pid))
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        wait_for(client, run_id, {"running"})
        deadline = time.monotonic() + 10
        while not child_pid.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        client.post(f"/api/v1/runs/{run_id}/cancel")
        run = wait_for(client, run_id)

    assert run["status"] == "cancelled"
    assert not _alive(int(child_pid.read_text()))


def test_kometa_ignoring_sigterm_is_killed(tmp_path, config):
    plan(config, lines=["stubborn"], wait_for=str(tmp_path / "never"), ignore_term=True)
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        _wait_for_line(client, run_id, "stubborn")
        client.post(f"/api/v1/runs/{run_id}/cancel")
        run = wait_for(client, run_id)
    assert run["status"] == "cancelled"
    assert run["exit_code"] == -9


def test_runs_stop_at_the_time_limit(tmp_path, config):
    plan(config, wait_for=str(tmp_path / "never"))
    with make_client(tmp_path, run_timeout=1) as client:
        run = wait_for(client, client.post("/api/v1/runs", json={}).json()["id"])
    assert run["status"] == "timed_out"


def test_runs_cut_off_by_a_restart_are_marked_interrupted(tmp_path, config):
    with make_client(tmp_path):
        pass
    db = sqlite3.connect(tmp_path / "data" / "studio.db")
    with db:
        db.execute("INSERT INTO runs (status, request, started_at) VALUES ('running', '{}', '2026-10-30T01:00:00Z')")
    db.close()
    with make_client(tmp_path) as client:
        run = client.get("/api/v1/runs/1").json()
    assert run["status"] == "interrupted"


def test_webhook_events_belong_to_the_running_run(tmp_path, config):
    release = tmp_path / "release"
    plan(config, wait_for=str(release))
    with make_client(tmp_path) as client:
        assert post_event(client, {"event": "version", "current": "2.5.3", "latest": "2.6.0"}).json() == {"ok": True, "run": None}

        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        wait_for(client, run_id, {"running"})
        post_event(client, {"event": "run_start", "start_time": "2026-10-30 03:00:00"})
        post_event(
            client,
            {
                "event": "changes",
                "library_name": "Movies",
                "collection": "Trending",
                "created": True,
                "poster": "iVBORw0KGgo" * 10000,
                "additions": [{"title": "Dune", "tmdb_id": 438631}],
                "removals": [],
            },
        )
        post_event(client, {"event": "error", "error": "TMDb is down", "critical": False, "library_name": "Movies"})
        summary = {"event": "run_end", "collections_created": 1, "collections_modified": 2, "items_added": 5, "items_removed": 1}
        assert post_event(client, summary).json() == {"ok": True, "run": run_id}
        release.touch()
        run = wait_for(client, run_id)

    assert run["summary"]["items_added"] == 5
    assert run["error_events"] == 1
    assert [e["event"] for e in run["events"]] == ["changes", "error"]
    assert run["events"][0] | {"received_at": None} == {
        "event": "changes",
        "received_at": None,
        "library_name": "Movies",
        "collection": "Trending",
        "created": True,
        "additions": 1,
        "removals": 0,
    }
    stored = sqlite3.connect(tmp_path / "data" / "studio.db").execute("SELECT payload FROM run_events WHERE event = 'changes'").fetchone()[0]
    assert "iVBORw0KGgo" not in stored


def test_a_critical_error_fails_the_run_even_when_kometa_exits_0(tmp_path, config):
    release = tmp_path / "release"
    plan(config, wait_for=str(release))
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        wait_for(client, run_id, {"running"})
        post_event(client, {"event": "error", "error": "Libraries: TV is not a valid library", "critical": False})
        post_event(client, {"event": "error", "error": "Config Error: tmdb sub-attribute apikey not found", "critical": True})
        release.touch()
        run = wait_for(client, run_id)
    assert (run["status"], run["exit_code"]) == ("failed", 0)
    assert run["error"] == "Config Error: tmdb sub-attribute apikey not found"


def test_non_critical_errors_leave_the_run_finished(tmp_path, config):
    release = tmp_path / "release"
    plan(config, wait_for=str(release))
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        wait_for(client, run_id, {"running"})
        post_event(client, {"event": "error", "error": "IMDb list not found", "critical": False})
        release.touch()
        run = wait_for(client, run_id)
    assert (run["status"], run["error_events"]) == ("succeeded", 1)


def test_webhooks_need_the_token(tmp_path, config):
    with make_client(tmp_path) as client:
        assert post_event(client, {"event": "run_start"}, token="wrong").status_code == 403


def test_the_log_stream_sends_the_whole_log_once(tmp_path, config):
    release = tmp_path / "release"
    plan(config, lines=[f"before {i}" for i in range(50)], wait_for=str(release), after=[f"after {i}" for i in range(50)])
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        _wait_for_line(client, run_id, "before 49")
        threading.Timer(0.5, release.touch).start()  # finish the run while the stream is open
        body = client.get(f"/api/v1/runs/{run_id}/stream").text

    lines, end = _parse_sse(body)
    expected = [f"before {i}" for i in range(50)] + [f"after {i}" for i in range(50)]
    assert [line for line in lines if line.startswith(("before", "after"))] == expected
    assert end == {"status": "succeeded", "dropped": False}


def test_the_stream_of_a_finished_run(tmp_path, config):
    plan(config, lines=["only line"])
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json={}).json()["id"]
        wait_for(client, run_id)
        lines, end = _parse_sse(client.get(f"/api/v1/runs/{run_id}/stream").text)
    assert "only line" in lines
    assert end["status"] == "succeeded"


def test_bad_names_are_refused(tmp_path, config):
    with make_client(tmp_path) as client:
        response = client.post("/api/v1/runs", json={"libraries": ["Movies|TV"]})
    assert response.status_code == 422


def _wait_for_line(client, run_id, line, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}/log")
        if response.status_code == 200 and line in response.text:
            return
        time.sleep(0.05)
    raise AssertionError(f"{line!r} never appeared")


def _parse_sse(body):
    lines, end = [], None
    for block in body.strip().split("\n\n"):
        fields = dict(part.split(": ", 1) for part in block.split("\n"))
        if fields["event"] == "lines":
            lines += json.loads(fields["data"])
        elif fields["event"] == "end":
            end = json.loads(fields["data"])
    return lines, end


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child of an exited parent may linger as a zombie until init reaps it.
    try:
        with open(f"/proc/{pid}/status") as status:
            return "zombie" not in status.read()
    except FileNotFoundError:
        return False
