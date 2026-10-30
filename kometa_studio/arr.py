"""Radarr and Sonarr over their API: run Kometa after new imports, once things go quiet (handoff v2 §4.5, §8).

Studio polls each app's import history (``GET /api/v3/history/since``, event type 3, "download folder
imported", in both apps) every ``POLL_EVERY``. Studio reaches out to them, so nothing has to reach Studio,
and imports made while Studio was off are found when it starts again (up to ``CATCH_UP`` back).

The connection is Kometa's own: ``radarr:``/``sonarr:`` in config.yml, which Settings → Connect edits.
A seedbox's proxy login in front of an app (HTTP Basic) is Studio's alone, kept encrypted, since
Kometa can't send one.

Each app has its own settings (``AppRuns``). A season pack or a big search imports dozens of files,
so each import only pushes back that app's pending run: it's queued once no import has arrived for
``wait_minutes``, or ``MAX_WAIT`` after the first, whichever is sooner. Pending runs live in SQLite
and the scheduler's tick queues them.
"""

import asyncio
import contextlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field
from ruamel.yaml import YAML, YAMLError

from .crypto import SecretBox
from .db import delete_setting, get_setting, set_setting
from .kometa_command import Mode, RunRequest
from .runner import Runner
from .scheduler import parse_utc, utc_text

log = logging.getLogger(__name__)

RUNS = "arr.settings"  # when to run Kometa after each app's imports
CONNECTIONS = "arr.connections"  # each app's proxy login, if any (url and key are in config.yml)
PENDING = "arr.pending"  # before per-app settings: one pending run for both apps
POLL_EVERY = 120.0
CATCH_UP = timedelta(hours=24)
MAX_WAIT = timedelta(hours=1)
TIMEOUT = 10.0
KEEP_TITLES = 10
IMPORTED = 3  # DownloadFolderImported, in Radarr's MovieHistoryEventType and Sonarr's EpisodeHistoryEventType

Kind = Literal["radarr", "sonarr"]
KINDS: tuple[Kind, ...] = ("radarr", "sonarr")
NAMES = {"radarr": "Radarr", "sonarr": "Sonarr"}


class AppRuns(BaseModel):
    """When to run Kometa after one app's imports."""

    enabled: bool = False
    mode: Mode = "all"
    wait_minutes: int = Field(default=10, ge=1, le=240)
    # Kometa library names (config.yml) to run for; empty means every library.
    libraries: list[str] = Field(default_factory=list)


class ArrSettings(BaseModel):
    radarr: AppRuns = Field(default_factory=AppRuns)
    sonarr: AppRuns = Field(default_factory=AppRuns)

    def app(self, kind: "Kind") -> AppRuns:
        return getattr(self, kind)


def load_settings(db: sqlite3.Connection) -> ArrSettings:
    raw = get_setting(db, RUNS) or {}
    if "enabled" in raw:  # saved before each app had its own settings: one set for both
        shared = {key: raw[key] for key in ("enabled", "mode", "wait_minutes") if key in raw}
        libraries = raw.get("libraries") or {}
        raw = {kind: shared | {"libraries": libraries.get(kind, [])} for kind in KINDS}
    return ArrSettings.model_validate(raw)


def pending_key(kind: "Kind") -> str:
    return f"arr.pending.{kind}"


class ArrProblem(Exception):
    pass


@dataclass
class Connection:
    url: str
    api_key: str
    login: tuple[str, str] | None = None  # for a proxy in front of the app (HTTP Basic), as on a seedbox


def config_section(config: Path | None, kind: Kind) -> dict:
    """config.yml's radarr:/sonarr: section, or {}."""
    if config is None or not config.is_file():
        return {}
    try:
        document = YAML(typ="safe").load(config.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return {}
    section = document.get(kind) if isinstance(document, dict) else None
    return section if isinstance(section, dict) else {}


def kometa_connection(config: Path | None, kind: Kind) -> tuple[str | None, str | None]:
    """The url and token in config.yml's radarr:/sonarr: section, if there are both."""
    section = config_section(config, kind)
    url, token = section.get("url"), section.get("token")
    return (str(url) if url else None, str(token) if token else None)


def proxy_login(db: sqlite3.Connection, box: SecretBox, kind: Kind) -> tuple[str, str] | None:
    saved = (get_setting(db, CONNECTIONS) or {}).get(kind) or {}
    if not saved.get("username"):
        return None
    return saved["username"], (box.decrypt(saved["password"]) or "") if saved.get("password") else ""


def connection(db: sqlite3.Connection, box: SecretBox, config: Path | None, kind: Kind) -> Connection | None:
    url, token = kometa_connection(config, kind)
    return Connection(url, token, proxy_login(db, box, kind)) if url and token else None


async def _get(http: httpx.AsyncClient, conn: Connection, path: str, params: dict | None = None) -> Any:
    try:
        response = await http.get(
            conn.url.rstrip("/") + path,
            params=params,
            headers={"X-Api-Key": conn.api_key, "Accept": "application/json"},
            timeout=TIMEOUT,
            auth=conn.login or httpx.USE_CLIENT_DEFAULT,
        )
    except httpx.TimeoutException:
        raise ArrProblem(f"No answer within {TIMEOUT:g} s") from None
    except httpx.HTTPError as error:
        raise ArrProblem(f"Can't connect: {error}") from None
    if response.status_code == 401:
        if response.headers.get("www-authenticate", "").lower().startswith("basic"):
            raise ArrProblem("The proxy in front of it wants a username and password" + (" (these were refused)" if conn.login else ""))
        raise ArrProblem("The API key was rejected")
    if response.status_code != 200:
        raise ArrProblem(f"It answered HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise ArrProblem("That address answered, but not like Radarr or Sonarr") from None


async def test_connection(http: httpx.AsyncClient, conn: Connection, kind: Kind) -> dict:
    """Whether ``conn`` is this kind of app, with its root folders and quality profiles for Kometa's settings."""
    status = await _get(http, conn, "/api/v3/system/status")
    app = str(status.get("appName") or "") if isinstance(status, dict) else ""
    if app.lower() != kind:
        raise ArrProblem(f"That's {app or 'not Radarr or Sonarr'}, not {NAMES[kind]}")
    folders = await _get(http, conn, "/api/v3/rootfolder")
    profiles = await _get(http, conn, "/api/v3/qualityprofile")
    return {
        "app": app,
        "version": str(status.get("version") or ""),
        "root_folders": [str(f["path"]) for f in folders if isinstance(f, dict) and f.get("path")] if isinstance(folders, list) else [],
        "quality_profiles": [str(p["name"]) for p in profiles if isinstance(p, dict) and p.get("name")] if isinstance(profiles, list) else [],
    }


async def imports_since(http: httpx.AsyncClient, conn: Connection, kind: Kind, since: datetime) -> list[dict]:
    """Import history records at or after ``since``, oldest first."""
    params = {"date": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "eventType": IMPORTED}
    params["includeMovie" if kind == "radarr" else "includeSeries"] = "true"
    records = await _get(http, conn, "/api/v3/history/since", params)
    if not isinstance(records, list):
        raise ArrProblem("Unexpected answer to the history request")
    return sorted((r for r in records if isinstance(r, dict) and isinstance(r.get("id"), int)), key=lambda r: r["id"])


def _title(record: dict) -> str | None:
    item = record.get("movie") or record.get("series") or {}
    title = item.get("title") if isinstance(item, dict) else None
    if not title:
        return record.get("sourceTitle")
    year = item.get("year")
    return f"{title} ({year})" if year else str(title)


class Arr:
    """The polling, the pending run, and queueing it."""

    def __init__(self, db: sqlite3.Connection, runner: Runner, http: httpx.AsyncClient, box: SecretBox, config: Path | None):
        self.db = db
        self.runner = runner
        self.http = http
        self.box = box
        self.config = config
        self._task: asyncio.Task | None = None
        shared = get_setting(db, PENDING)
        if shared:  # one pending run for both apps, from before each app had its own
            for kind in shared.get("kinds", []):
                set_setting(db, pending_key(kind), {key: shared[key] for key in ("first_at", "last_at", "imports", "titles")})
            delete_setting(db, PENDING)

    # --- Polling ---------------------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="arr-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll(datetime.now(UTC))
            except Exception:  # a bad answer must not stop polling for good
                log.exception("Polling Radarr/Sonarr failed")
            await asyncio.sleep(POLL_EVERY)

    async def poll(self, now: datetime) -> dict[str, int]:
        """Look for new imports in each connected app that runs Kometa; returns how many each had."""
        found = {}
        settings = load_settings(self.db)
        for kind in KINDS:
            conn = connection(self.db, self.box, self.config, kind)
            if conn is None or not settings.app(kind).enabled:
                continue
            cursor = get_setting(self.db, f"arr.cursor.{kind}") or {"date": utc_text(now), "id": 0}
            since = max(parse_utc(cursor["date"]), now - CATCH_UP)
            try:
                records = [r for r in await imports_since(self.http, conn, kind, since) if r["id"] > cursor["id"]]
            except ArrProblem as problem:
                set_setting(self.db, f"arr.status.{kind}", {"checked_at": utc_text(now), "ok": False, "error": str(problem)})
                continue
            set_setting(self.db, f"arr.status.{kind}", {"checked_at": utc_text(now), "ok": True, "error": None})
            if records:
                self.record(kind, [_title(r) for r in records], now)
                last = records[-1]
                cursor = {"date": str(last.get("date") or utc_text(now))[:19] + "Z", "id": last["id"]}
            elif cursor["id"] == 0:
                cursor = {"date": utc_text(now), "id": 0}
            set_setting(self.db, f"arr.cursor.{kind}", cursor)
            found[kind] = len(records)
        return found

    def reset_cursor(self, kind: Kind) -> None:
        """Start from now: a newly connected app's history isn't news."""
        delete_setting(self.db, f"arr.cursor.{kind}")
        delete_setting(self.db, f"arr.status.{kind}")

    # --- The pending runs --------------------------------------------------------------

    def record(self, kind: Kind, titles: list[str | None], now: datetime) -> None:
        pending = get_setting(self.db, pending_key(kind)) or {"first_at": utc_text(now), "imports": 0, "titles": []}
        pending["last_at"] = utc_text(now)
        pending["imports"] += len(titles)
        for title in titles:
            if title and title not in pending["titles"]:
                pending["titles"] = (pending["titles"] + [title])[-KEEP_TITLES:]
        set_setting(self.db, pending_key(kind), pending)

    @staticmethod
    def due_at(pending: dict, runs: AppRuns) -> datetime:
        quiet = parse_utc(pending["last_at"]) + timedelta(minutes=runs.wait_minutes)
        return min(quiet, parse_utc(pending["first_at"]) + MAX_WAIT)

    @staticmethod
    def request(runs: AppRuns) -> RunRequest:
        return RunRequest(mode=runs.mode, libraries=list(runs.libraries))

    def tick(self, now: datetime) -> list[int]:
        """Queue each app's pending run that's due; returns their run IDs (an equal queued run is reused)."""
        queued = []
        settings = load_settings(self.db)
        for kind in KINDS:
            pending = get_setting(self.db, pending_key(kind))
            if not pending or now < self.due_at(pending, settings.app(kind)):
                continue
            delete_setting(self.db, pending_key(kind))
            queued.append(self.runner.enqueue(self.request(settings.app(kind)), trigger="arr"))
        return queued

    def pending(self) -> dict[str, dict]:
        """Each app's pending run, with when it's due."""
        settings = load_settings(self.db)
        found = {}
        for kind in KINDS:
            pending = get_setting(self.db, pending_key(kind))
            if pending:
                found[kind] = pending | {"due_at": utc_text(self.due_at(pending, settings.app(kind)))}
        return found
