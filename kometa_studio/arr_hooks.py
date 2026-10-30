"""Radarr and Sonarr's webhook: run Kometa after new imports, once things go quiet (handoff v2 §8, §9).

Radarr and Sonarr send a ``Download`` event for every import and upgrade. A season pack or a
big search sends dozens in a row, so each one only pushes back a pending run: it's queued once
no import has arrived for ``wait_minutes``, or ``MAX_WAIT`` after the first, whichever comes
first. The pending run lives in SQLite, so a restart doesn't lose it, and the scheduler's tick
queues it. An equal run already waiting in the queue is enough; no second one is added.
"""

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .db import delete_setting, get_setting, set_setting
from .kometa_command import Mode, RunRequest
from .runner import Runner
from .scheduler import parse_utc, utc_text

SETTINGS = "arr.settings"
TOKEN = "arr.webhook_token"
PENDING = "arr.pending"
LAST_EVENT = "arr.last_event"
MAX_WAIT = timedelta(hours=1)
KEEP_TITLES = 10

Kind = Literal["radarr", "sonarr"]


class ArrSettings(BaseModel):
    enabled: bool = False
    mode: Mode = "all"
    wait_minutes: int = Field(default=10, ge=1, le=240)
    # Kometa library names (config.yml) to run for each app's imports; empty means every library.
    libraries: dict[Kind, list[str]] = Field(default_factory=lambda: {"radarr": [], "sonarr": []})


def load_settings(db: sqlite3.Connection) -> ArrSettings:
    return ArrSettings.model_validate(get_setting(db, SETTINGS) or {})


def token(db: sqlite3.Connection) -> str:
    value = get_setting(db, TOKEN)
    if not value:
        value = new_token(db)
    return value


def new_token(db: sqlite3.Connection) -> str:
    value = secrets.token_urlsafe(24)
    set_setting(db, TOKEN, value)
    return value


def _kind(payload: dict) -> Kind | None:
    """Radarr's events carry a movie, Sonarr's a series; a test event may carry neither, only the instance's name."""
    if isinstance(payload.get("movie"), dict):
        return "radarr"
    if isinstance(payload.get("series"), dict):
        return "sonarr"
    instance = str(payload.get("instanceName") or "").lower()
    return "radarr" if "radarr" in instance else "sonarr" if "sonarr" in instance else None


def _title(payload: dict) -> str | None:
    item = payload.get("movie") or payload.get("series") or {}
    title = item.get("title") if isinstance(item, dict) else None
    if not title:
        return None
    year = item.get("year")
    return f"{title} ({year})" if year else str(title)


class ArrHooks:
    def __init__(self, db: sqlite3.Connection, runner: Runner):
        self.db = db
        self.runner = runner

    def receive(self, payload: dict[str, Any], now: datetime) -> dict:
        """One webhook from Radarr or Sonarr. Returns what Studio did with it."""
        event = str(payload.get("eventType") or "")
        kind = _kind(payload)
        title = _title(payload)
        set_setting(self.db, LAST_EVENT, {"at": utc_text(now), "kind": kind, "event": event, "title": title})
        if event == "Test":
            return {"action": "test"}
        settings = load_settings(self.db)
        if event != "Download" or kind is None:
            return {"action": "ignored", "reason": f"Studio only acts on imports, not {event or 'this event'}"}
        if not settings.enabled:
            return {"action": "ignored", "reason": "Runs after imports are switched off in Settings → Connect"}

        pending = get_setting(self.db, PENDING) or {"first_at": utc_text(now), "imports": 0, "titles": [], "kinds": []}
        pending["last_at"] = utc_text(now)
        pending["imports"] += 1
        if title and title not in pending["titles"]:
            pending["titles"] = (pending["titles"] + [title])[-KEEP_TITLES:]
        if kind not in pending["kinds"]:
            pending["kinds"].append(kind)
        set_setting(self.db, PENDING, pending)
        return {"action": "pending", "due_at": utc_text(self.due_at(pending, settings))}

    @staticmethod
    def due_at(pending: dict, settings: ArrSettings) -> datetime:
        quiet = parse_utc(pending["last_at"]) + timedelta(minutes=settings.wait_minutes)
        return min(quiet, parse_utc(pending["first_at"]) + MAX_WAIT)

    def request(self, pending: dict, settings: ArrSettings) -> RunRequest:
        libraries: list[str] = []
        for kind in pending["kinds"]:
            chosen = settings.libraries.get(kind, [])
            if not chosen:
                return RunRequest(mode=settings.mode)  # this app's imports may be in any library
            libraries += [name for name in chosen if name not in libraries]
        return RunRequest(mode=settings.mode, libraries=libraries)

    def tick(self, now: datetime) -> int | None:
        """Queue the pending run if it's due; returns its run ID (or the equal one already queued)."""
        pending = get_setting(self.db, PENDING)
        if not pending:
            return None
        settings = load_settings(self.db)
        if now < self.due_at(pending, settings):
            return None
        request = self.request(pending, settings)
        delete_setting(self.db, PENDING)
        for row in self.db.execute("SELECT id, request FROM runs WHERE status = 'queued' ORDER BY id").fetchall():
            if RunRequest.model_validate_json(row["request"]) == request:
                return row["id"]
        return self.runner.enqueue(request, trigger="arr")

    def pending(self) -> dict | None:
        pending = get_setting(self.db, PENDING)
        if not pending:
            return None
        return pending | {"due_at": utc_text(self.due_at(pending, load_settings(self.db)))}
