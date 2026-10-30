import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex

from kometa_studio.auth import AUTH
from kometa_studio.db import open_database, set_setting
from kometa_studio.health import PlexCheck, health, kometa_updates
from kometa_studio.settings import Settings


@pytest.fixture
def db(tmp_path):
    conn = open_database(tmp_path / "studio.db")
    yield conn
    conn.close()


@pytest.fixture
def kometa(tmp_path) -> Settings:
    entry = tmp_path / "kometa" / "kometa.py"
    entry.parent.mkdir()
    entry.write_text("")
    (entry.parent / "VERSION").write_text("2.5.3\n")
    config = tmp_path / "config" / "config.yml"
    config.parent.mkdir()
    config.write_text(f"plex:\n  url: {REMOTE_URI}\n  token: {SERVER_TOKEN}\n")
    return Settings(data_dir=tmp_path / "data", kometa_python=Path("/usr/bin/python3"), kometa_entry=entry, kometa_config=config)


def event(db, run_id, name, **payload):
    with db:
        db.execute("INSERT INTO run_events (run_id, event, payload) VALUES (?, ?, ?)", (run_id, name, json.dumps({"event": name} | payload)))


def add_run(db, status, error=None) -> int:
    with db:
        return db.execute("INSERT INTO runs (status, request, error) VALUES (?, '{}', ?)", (status, error)).lastrowid


def check(db, settings, fake=None, plex_check=None, flags_error=None):
    async def go():
        async with httpx.AsyncClient(transport=(fake or FakePlex()).transport()) as http:
            return await health(db, settings, http, plex_check or PlexCheck(), flags_error)

    return asyncio.run(go())


def sources(checks):
    return {c["source"]: c["level"] for c in checks}


def test_a_healthy_setup_reports_only_missing_sign_in(db, kometa):
    assert sources(check(db, kometa)) == {"sign_in": "warning"}
    set_setting(db, AUTH, {"username": "hasan", "password": "scrypt$x$y", "required": "enabled"})
    assert check(db, kometa) == []


def test_plex_problems_link_to_settings(db, kometa):
    fake = FakePlex()
    fake.reachable = set()
    problems = [c for c in check(db, kometa, fake) if c["source"] == "plex"]
    assert problems[0]["level"] == "error" and problems[0]["link"] == "/settings/plex"
    assert "Can't reach Plex" in problems[0]["message"]

    kometa.kometa_config.write_text(f"plex:\n  url: {REMOTE_URI}\n  token: wrong\n")
    assert "rejected the token" in next(c for c in check(db, kometa) if c["source"] == "plex")["message"]


def test_the_plex_answer_is_remembered(db, kometa):
    fake, remembered = FakePlex(), PlexCheck()
    check(db, kometa, fake, remembered)
    check(db, kometa, fake, remembered)
    assert len(fake.requests) == 1
    kometa.kometa_config.write_text(f"plex:\n  url: {REMOTE_URI}/\n  token: {SERVER_TOKEN}\n")  # a new address: ask again
    check(db, kometa, fake, remembered)
    assert len(fake.requests) == 2


def test_setup_problems(db, kometa, tmp_path):
    kometa.kometa_config.unlink()
    assert sources(check(db, kometa, flags_error="ModuleNotFoundError: No module named 'plexapi'")) == {
        "kometa": "error",
        "config": "warning",
        "sign_in": "warning",
    }
    assert sources(check(db, Settings(data_dir=tmp_path / "data")))["kometa"] == "error"


def test_the_last_run_and_full_check(db, kometa):
    add_run(db, "failed", "Kometa stopped with exit code 1")
    run_id = add_run(db, "timed_out")
    add_run(db, "queued")
    set_setting(db, "kometa.full_check", {"ok": False})
    checks = {c["source"]: c for c in check(db, kometa)}
    assert checks["runs"]["message"] == f"The last Kometa run (#{run_id}) ran out of time"
    assert checks["runs"]["link"] == f"/activity/queue/{run_id}"
    assert checks["full_check"]["level"] == "warning"

    add_run(db, "succeeded")
    set_setting(db, "kometa.full_check", {"ok": True})
    assert "runs" not in sources(check(db, kometa)) and "full_check" not in sources(check(db, kometa))


def test_kometa_updates_come_from_the_latest_run(db):
    assert kometa_updates(db, "2.5.3") | {"checked_at": None} == {
        "installed": "2.5.3",
        "checked_at": None,
        "latest": None,
        "notes": None,
        "available": False,
    }
    first = add_run(db, "succeeded")
    event(db, first, "run_start")
    event(db, first, "version", current="2.5.3", latest="2.6.0", notes="New things")
    updates = kometa_updates(db, "2.5.3")
    assert (updates["available"], updates["latest"], updates["notes"]) == (True, "2.6.0", "New things")
    assert updates["checked_at"] is not None

    # After upgrading, the next run sends no version event: up to date.
    second = add_run(db, "succeeded")
    event(db, second, "run_start")
    assert kometa_updates(db, "2.6.0")["available"] is False


def test_an_update_shows_as_info(db, kometa):
    run = add_run(db, "succeeded")
    event(db, run, "run_start")
    event(db, run, "version", current="2.5.3", latest="2.6.0")
    update = next(c for c in check(db, kometa) if c["source"] == "updates")
    assert update == {"source": "updates", "level": "info", "message": "Kometa 2.6.0 is out (you have 2.5.3).", "link": "/system/updates"}


def test_original_posters_need_a_recent_full_backup(db, kometa):
    posters = kometa.kometa_config.parent / "overlays" / "Movies Original Posters"
    posters.mkdir(parents=True)
    warning = next(c for c in check(db, kometa) if c["source"] == "full_backup")
    assert "Original Posters" in warning["message"] and warning["link"] == "/system/backup"

    backups = kometa.data_dir / "full-backups"
    backups.mkdir(parents=True)
    (backups / f"kometa-studio-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip").write_bytes(b"zip")
    assert "full_backup" not in sources(check(db, kometa))

    with db:
        db.execute(
            "INSERT INTO tasks (name, enabled, days, time, timezone, last_fired_at, last_status, last_message) "
            "VALUES ('full_backup', 1, 64, '04:30', 'UTC', '2026-10-30T00:00:00Z', 'failed', 'Not enough disk space')"
        )
    assert "Not enough disk space" in next(c for c in check(db, kometa) if c["source"] == "full_backup")["message"]


def test_radarr_problems_show_when_runs_after_imports_are_on(db, kometa):
    set_setting(db, "arr.status.radarr", {"checked_at": "2026-10-30T20:00:00Z", "ok": False, "error": "The API key was rejected"})
    assert "radarr" not in sources(check(db, kometa))  # switched off: not a problem
    set_setting(db, "arr.settings", {"enabled": True})
    radarr = next(c for c in check(db, kometa) if c["source"] == "radarr")
    assert radarr["message"] == "Studio can't read Radarr's imports: The API key was rejected"
