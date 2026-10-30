import json
import os
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kometa_studio import full_backup
from kometa_studio.app import create_app
from kometa_studio.db import open_database
from kometa_studio.scheduler import utc_text
from kometa_studio.settings import Settings
from kometa_studio.tasks import Tasks

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"


@pytest.fixture
def config(tmp_path) -> Path:
    """A config folder shaped like a real one, with Studio's data folder inside it as in Docker."""
    config = tmp_path / "config"
    (config / "logs").mkdir(parents=True)
    (config / "overlays" / "Movies Original Posters").mkdir(parents=True)
    (config / "config.yml").write_text("libraries:\n  Movies: {}\n")
    (config / "Movies.yml").write_text("collections: {}\n")
    (config / "fake.json").write_text("{}")
    (config / "logs" / "meta.log").write_text("a log\n")
    (config / "config.cache").write_bytes(b"cache")
    (config / "overlays" / "Movies Original Posters" / "1234.jpg").write_bytes(b"\xff\xd8poster")
    studio = config / ".studio"
    (studio / "runs").mkdir(parents=True)
    (studio / "runs" / "1.log").write_text("run log\n")
    (studio / "backups" / "20261030T000000.000000Z").mkdir(parents=True)
    os.symlink(tmp_path, config / "elsewhere")
    return config


def make_db(config: Path):
    return open_database(config / ".studio" / "studio.db")


def test_a_full_backup_holds_config_original_posters_and_the_database(config):
    (config / ".studio" / "secret.key").write_bytes(b"key")
    db = make_db(config)
    db.execute("INSERT INTO settings (key, value) VALUES ('marker', '1')")
    db.commit()
    result = full_backup.create(config, config / ".studio", config / ".studio" / "studio.db", keep=4)
    db.close()

    assert result["notes"] == ["1 symbolic link(s) left out"]
    path = config / ".studio" / "full-backups" / result["name"]
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert names == {
            "README.txt",
            "config/config.yml",
            "config/Movies.yml",
            "config/fake.json",
            "config/overlays/Movies Original Posters/1234.jpg",
            "studio/studio.db",
            "studio/secret.key",
        }
        assert archive.getinfo("config/overlays/Movies Original Posters/1234.jpg").compress_type == zipfile.ZIP_STORED
        archive.extract("studio/studio.db", config.parent / "restored")
    restored = open_database(config.parent / "restored" / "studio" / "studio.db")
    assert restored.execute("SELECT value FROM settings WHERE key = 'marker'").fetchone()[0] == "1"
    restored.close()
    assert full_backup.list_full(config / ".studio")[0]["name"] == result["name"]


def test_only_the_newest_are_kept(config):
    dest = config / ".studio" / "full-backups"
    dest.mkdir(parents=True)
    for day in range(1, 6):
        (dest / f"kometa-studio-202610{day:02d}-040000.zip").write_bytes(b"old")
    (dest / "notes.txt").write_text("not a backup")
    full_backup.prune(dest, keep=2)
    assert sorted(p.name for p in dest.iterdir()) == ["kometa-studio-20261004-040000.zip", "kometa-studio-20261005-040000.zip", "notes.txt"]


def test_a_backup_that_wont_fit_isnt_started(config, monkeypatch):
    monkeypatch.setattr(full_backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=10))
    with pytest.raises(full_backup.BackupFailed, match="Not enough disk space"):
        full_backup.create(config, config / ".studio", config / ".studio" / "studio.db", keep=4)
    assert full_backup.list_full(config / ".studio") == []
    assert not list((config / ".studio" / "full-backups").glob("*.partial"))


def test_names_outside_the_backups_are_refused(config):
    assert full_backup.find(config / ".studio", "../studio.db") is None
    assert full_backup.find(config / ".studio", "kometa-studio-20261030-040000.zip") is None  # well-formed, but not there


# --- Scheduling ---------------------------------------------------------------------


class IdleRunner:
    current_run_id = None


def test_due_tasks_start_once_and_missed_ones_catch_up(config):
    db = make_db(config)
    tasks = Tasks(db, Settings(data_dir=config / ".studio", kometa_config=config / "config.yml"), IdleRunner(), None)
    tasks.setup("UTC")
    tasks.start = lambda name: True  # record what would start, without running it
    sunday = datetime(2026, 11, 1, 4, 30, tzinfo=UTC)
    with db:
        db.execute("UPDATE tasks SET last_fired_at = ?", (utc_text(sunday - timedelta(days=1)),))
    assert tasks.tick(sunday + timedelta(minutes=1)) == ["full_backup"]  # full_check is off by default
    assert tasks.tick(sunday + timedelta(minutes=2)) == []
    # Studio was off for the next Sunday's backup and comes back within a day: it runs once.
    assert tasks.tick(sunday + timedelta(days=7, hours=5)) == ["full_backup"]
    # Off for longer than a day: skipped.
    assert tasks.tick(sunday + timedelta(days=16)) == []
    db.close()


def test_a_backup_cut_off_by_a_restart_is_marked_and_its_partial_removed(config):
    db = make_db(config)
    tasks = Tasks(db, Settings(data_dir=config / ".studio"), IdleRunner(), None)
    tasks.setup("UTC")
    with db:
        db.execute("UPDATE tasks SET last_status = 'running', last_started_at = '2026-10-30T04:30:00Z' WHERE name = 'full_backup'")
    partial = config / ".studio" / "full-backups" / "kometa-studio-20261030-043000.zip.partial"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"half")
    tasks.setup("UTC")
    assert db.execute("SELECT last_status FROM tasks WHERE name = 'full_backup'").fetchone()[0] == "interrupted"
    assert not partial.exists()
    db.close()


# --- API ----------------------------------------------------------------------------


def make_client(tmp_path, config):
    settings = Settings(
        data_dir=config / ".studio", kometa_config=config / "config.yml", kometa_entry=FAKE_KOMETA, kometa_python=Path(sys.executable)
    )
    return TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000))


def wait_for_task(client, name, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = next(t for t in client.get("/api/v1/tasks").json()["tasks"] if t["name"] == name)
        if not task["running"] and task["last"] and task["last"]["status"] != "running":
            return task
        time.sleep(0.05)
    raise AssertionError(f"{name} still running")


def test_running_a_full_backup_and_downloading_it(tmp_path, config):
    with make_client(tmp_path, config) as client:
        tasks = client.get("/api/v1/tasks").json()["tasks"]
        assert [(t["name"], t["enabled"], t["days"], t["time"]) for t in tasks] == [("full_backup", True, [6], "04:30"), ("full_check", False, list(range(7)), "04:00")]
        assert client.post("/api/v1/tasks/full_backup/run").status_code == 202
        task = wait_for_task(client, "full_backup")
        assert task["last"]["status"] == "succeeded", task
        name = client.get("/api/v1/backups/full").json()["backups"][0]["name"]
        assert name in task["last"]["message"]
        download = client.get(f"/api/v1/backups/full/{name}")
        assert download.headers["content-type"] == "application/zip"
        assert client.delete(f"/api/v1/backups/full/{name}").status_code == 204
        assert client.get("/api/v1/backups/full").json()["backups"] == []
        assert client.get("/api/v1/backups/full/..%2Fstudio.db").status_code == 404


def test_the_full_check_task_keeps_kometas_verdict(tmp_path, config):
    with make_client(tmp_path, config) as client:
        client.post("/api/v1/tasks/full_check/run")
        task = wait_for_task(client, "full_check")
        last = client.get("/api/v1/kometa/full-check").json()["last"]
    assert task["last"]["status"] == "succeeded", task
    assert last["ok"] is True


def test_changing_a_tasks_schedule(tmp_path, config):
    with make_client(tmp_path, config) as client:
        bad = client.put("/api/v1/tasks/full_backup", json={"enabled": True, "days": [], "time": "04:30", "timezone": "UTC"})
        changed = client.put(
            "/api/v1/tasks/full_backup", json={"enabled": True, "days": [0, 3], "time": "02:15", "timezone": "Asia/Kolkata", "options": {"keep": 10}}
        )
        missing = client.put("/api/v1/tasks/nothing", json={"enabled": True, "days": [0], "time": "02:15", "timezone": "UTC"})
    assert bad.status_code == 422
    assert missing.status_code == 404
    body = changed.json()
    assert (body["days"], body["time"], body["timezone"], body["options"]) == ([0, 3], "02:15", "Asia/Kolkata", {"keep": 10})
    assert body["next_run"] is not None
    assert json.loads(json.dumps(body))["running"] is False
