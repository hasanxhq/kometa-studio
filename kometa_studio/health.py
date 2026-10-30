"""Health checks for System → Status, and what Kometa's version webhook said (handoff v2 §8).

Each check is cheap except Plex's, which asks the server who it is and is remembered for
``PLEX_CHECK_TTL`` seconds so the sidebar's polling doesn't hammer it.
"""

import json
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from ruamel.yaml import YAMLError

from . import full_backup, plex
from .auth import auth_settings
from .config_routes import FULL_CHECK
from .db import get_setting
from .kometa_config import read_plex
from .settings import Settings

PLEX_CHECK_TTL = 300
LOW_DISK = 1024**3  # warn below 1 GiB free
VERY_LOW_DISK = 200 * 1024**2
BACKUP_AGE = timedelta(days=14)  # Original Posters older than this in the newest full backup: warn


@dataclass
class Check:
    source: str  # stable id, e.g. "plex"
    level: str  # error, warning or info
    message: str
    link: str | None = None  # the page that fixes it


def kometa_version(settings: Settings) -> str | None:
    """Read the installed Kometa's VERSION file, which sits next to kometa.py."""
    if settings.kometa_entry is None:
        return None
    try:
        return (settings.kometa_entry.parent / "VERSION").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def kometa_updates(db: sqlite3.Connection, installed: str | None) -> dict:
    """What the newest Kometa run learned about Kometa versions.

    Kometa checks for a new version as it starts each run, and sends the ``version`` webhook
    only when there is one. So: a version event from the latest run that got going means an
    update is out; a run without one means this version was the latest then.
    """
    started = db.execute("SELECT id, received_at FROM run_events WHERE event = 'run_start' ORDER BY id DESC LIMIT 1").fetchone()
    event = db.execute("SELECT id, payload FROM run_events WHERE event = 'version' ORDER BY id DESC LIMIT 1").fetchone()
    result = {"installed": installed, "checked_at": started["received_at"] if started else None, "latest": None, "notes": None, "available": False}
    # Kometa sends run_start, then version: a version event older than the last run_start is old news.
    if event is None or started is None or event["id"] < started["id"]:
        return result
    payload = json.loads(event["payload"])
    latest = str(payload.get("latest") or "") or None
    result |= {"latest": latest, "notes": payload.get("notes"), "available": bool(latest) and latest != installed}
    return result


class PlexCheck:
    """Whether the Plex server in config.yml answers with its token, remembered for a few minutes."""

    def __init__(self) -> None:
        self._at = 0.0
        self._key: tuple[str, str] | None = None
        self._result: Check | None = None

    async def run(self, http: httpx.AsyncClient, config: Path | None) -> Check | None:
        try:
            current = read_plex(config) if config else None
        except (OSError, ValueError, YAMLError):
            current = None
        if current is None or not current.url or not current.token:
            return None  # the config check says what's missing
        key = (current.url, current.token)
        if key == self._key and time.monotonic() - self._at < PLEX_CHECK_TTL:
            return self._result
        try:
            await plex.probe(http, current.url, current.token)
            result = None
        except plex.TokenRejected:
            result = Check("plex", "error", "Plex rejected the token in config.yml. Sign in again in Settings → Plex.", "/settings/plex")
        except plex.PlexError as error:
            result = Check("plex", "error", f"Can't reach Plex at the address in config.yml: {error}", "/settings/plex")
        self._key, self._at, self._result = key, time.monotonic(), result
        return result


def _config_checks(settings: Settings, flags_error: str | None) -> list[Check]:
    if settings.kometa_python is None or settings.kometa_entry is None or settings.kometa_config is None:
        return [Check("kometa", "error", "Studio doesn't know where Kometa is. Set STUDIO_KOMETA_PYTHON, STUDIO_KOMETA_ENTRY and STUDIO_KOMETA_CONFIG.")]
    checks = []
    if not settings.kometa_config.exists():
        checks.append(Check("config", "warning", "Kometa's config.yml doesn't exist yet. Connect Plex to create it.", "/settings/plex"))
    if flags_error:
        checks.append(Check("kometa", "error", f"Kometa doesn't start: {flags_error}"))
    return checks


def _run_checks(db: sqlite3.Connection) -> list[Check]:
    checks = []
    last = db.execute(
        "SELECT id, status, error FROM runs WHERE status NOT IN ('queued', 'running', 'cancelled') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last is not None and last["status"] in ("failed", "timed_out", "interrupted"):
        what = {"failed": "failed", "timed_out": "ran out of time", "interrupted": "was cut off"}[last["status"]]
        reason = f": {last['error']}" if last["error"] else ""
        checks.append(Check("runs", "warning", f"The last Kometa run (#{last['id']}) {what}{reason}", f"/activity/queue/{last['id']}"))
    full = get_setting(db, FULL_CHECK)
    if isinstance(full, dict) and not full.get("ok"):
        checks.append(Check("full_check", "warning", "The last full check found problems in Kometa's config.", "/system/status"))
    return checks


def _arr_checks(db: sqlite3.Connection) -> list[Check]:
    if not get_setting(db, "arr.settings", {}).get("enabled"):
        return []
    checks = []
    for kind, name in (("radarr", "Radarr"), ("sonarr", "Sonarr")):
        status = get_setting(db, f"arr.status.{kind}")
        if isinstance(status, dict) and not status.get("ok"):
            checks.append(Check(kind, "warning", f"Studio can't read {name}'s imports: {status.get('error')}", "/settings/connect"))
    return checks


def _backup_checks(db: sqlite3.Connection, settings: Settings) -> list[Check]:
    row = db.execute("SELECT enabled, last_status, last_message FROM tasks WHERE name = 'full_backup'").fetchone()
    if row is not None and row["last_status"] == "failed":
        return [Check("full_backup", "warning", f"The last full backup failed: {row['last_message']}", "/system/backup")]
    if settings.kometa_config is None:
        return []
    posters = list((settings.kometa_config.parent / "overlays").glob("* Original Posters"))
    newest = full_backup.list_full(settings.data_dir)[:1]
    stale = not newest or datetime.now(UTC) - datetime.fromisoformat(newest[0]["created"]) > BACKUP_AGE
    if posters and stale:
        return [
            Check(
                "full_backup",
                "warning",
                f"Kometa's Original Posters aren't in a full backup from the last {BACKUP_AGE.days} days. Without them, Kometa can't cleanly remove its overlays.",
                "/system/backup",
            )
        ]
    return []


def _disk_check(settings: Settings) -> list[Check]:
    folder = settings.kometa_config.parent if settings.kometa_config else settings.data_dir
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return []
    if free < LOW_DISK:
        level = "error" if free < VERY_LOW_DISK else "warning"
        return [Check("disk", level, f"Only {free / 1024**2:.0f} MB free where Kometa's config folder is. Runs, logs and backups need room.")]
    return []


def _maintainerr_checks(service) -> list[Check]:
    if service is None or not service.connected():
        return []
    checks = [Check(f"maintainerr-{index}", "error", risk.message, "/settings/connect") for index, risk in enumerate(service.risks(), 1)]
    if service.snapshot.error:
        checks.append(Check("maintainerr", "warning", f"Studio can't read Maintainerr: {service.snapshot.error}", "/settings/connect"))
    return checks


async def health(
    db: sqlite3.Connection, settings: Settings, http: httpx.AsyncClient, plex_check: PlexCheck, flags_error: str | None, maintainerr=None
) -> list[dict]:
    checks = _config_checks(settings, flags_error)
    if settings.kometa_config and settings.kometa_config.exists():
        plex_result = await plex_check.run(http, settings.kometa_config)
        if plex_result:
            checks.append(plex_result)
    checks += _run_checks(db)
    checks += _arr_checks(db)
    checks += _maintainerr_checks(maintainerr)
    checks += _backup_checks(db, settings)
    checks += _disk_check(settings)
    if auth_settings(db) is None:
        checks.append(Check("sign_in", "warning", "Sign-in isn't set up, so anyone on your local network can use Studio.", "/settings/general"))
    updates = kometa_updates(db, kometa_version(settings))
    if updates["available"]:
        checks.append(Check("updates", "info", f"Kometa {updates['latest']} is out (you have {updates['installed']}).", "/system/updates"))
    order = {"error": 0, "warning": 1, "info": 2}
    return [asdict(check) for check in sorted(checks, key=lambda check: order[check.level])]
