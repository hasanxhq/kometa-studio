"""Maintainerr: Kometa leaves its collections alone, and optionally its overlays (handoff v2 §4.5).

Studio reads Maintainerr's collections over its API (``/api/collections``) and keeps a snapshot,
refreshed every ``REFRESH`` and before each run. With that it:

- shows Maintainerr's collections as Maintainerr's in Libraries (matched by Plex rating key);
- refuses a save that adds a way for Kometa to touch them (maintainerr_guard), and holds a run that
  would, saying why;
- with "Leave Maintainerr overlays alone" on, decides when Maintainerr draws, so its overlay always
  goes on last: original poster, then Kometa's overlay, then Maintainerr's. Maintainerr's revert
  then hands back exactly Kometa's poster.
  1. Studio takes over Maintainerr's overlay schedule: its job's cron becomes Maintainerr's own
     "never" (``NEVER``), and the schedule it had is kept, to give back when the setting is turned
     off or Maintainerr is disconnected. Its overlays stay enabled, because every pass, including
     one asked for, checks ``enabled`` first.
  2. Before a Kometa run that can change posters, Maintainerr reverts its overlays (``POST
     /api/overlays/revert/{id}``: its saved poster goes back), so Kometa only ever sees its own
     posters and never backs up a countdown as an "original".
  3. After the run, Maintainerr draws again (``POST /api/overlays/process``), on top of Kometa's.
     Retried every few minutes until it works, including after a restart.
  4. Once a day (``DAILY``) Maintainerr redraws, for its countdowns. If anything was added to a
     library that has Kometa overlays since Kometa's last overlay pass there, Kometa's overlays run
     first (wrapped as above), so a new item never gets Maintainerr's overlay before Kometa's.

If Maintainerr doesn't answer when a poster-changing run starts and the setting is on, the run is held:
running Kometa then could bake the countdown into Kometa's Original Posters.

Maintainerr's API has no key; on a seedbox it usually sits behind a proxy asking for a username and
password (HTTP Basic), which Studio sends when they're set. The password is kept encrypted.
"""

import asyncio
import contextlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from . import maintainerr_guard, wanted
from .crypto import SecretBox
from .db import delete_setting, get_setting, set_setting
from .kometa_command import RunRequest
from .kometa_config import read_plex
from .kometa_files import load_yaml
from .maintainerr_guard import Risk
from .plex_library import PlexServer, PlexUnavailable
from .runner import After, RunHeld, Say

log = logging.getLogger(__name__)

SETTINGS = "maintainerr"  # {url, username, password (encrypted), leave_overlays_alone}
PAUSED = "maintainerr.paused"  # an older Studio switched Maintainerr's overlays off for a run; switched back on by _resume
PENDING_PROCESS = "maintainerr.pending_process"  # an after step that didn't reach Maintainerr
REFRESH = 300.0
TIMEOUT = 15.0
BUSY_WAIT = 600.0  # how long to wait for Maintainerr's own overlay run to finish
REVERT_WAIT = 3600.0  # how long a revert may take: it walks every show, season and episode (~1 s each)
RETRY = 60.0  # how soon the loop tries again while a switch-back or redraw is pending
POLL = 5.0
POSTER_MODES = frozenset({"all", "overlays", "operations", "metadata"})  # runs that can change posters
NEVER = "0 0 0 1 1 *"  # what Maintainerr itself sets its overlay job to when it's off: once a year, 1 January
OWN_CRON = "maintainerr.own_cron"  # {cron}: Maintainerr's overlay schedule before Studio took it over, to give back
LAST_REDRAW = "maintainerr.last_redraw"  # Unix time Maintainerr last drew, at Studio's request
DAILY = 24 * 3600.0


class MaintainerrSettings(BaseModel):
    url: str | None = None
    username: str | None = None  # for a proxy in front of Maintainerr
    password: str | None = None  # encrypted
    leave_overlays_alone: bool = True


class MaintainerrProblem(Exception):
    pass


class Busy(MaintainerrProblem):
    """409: an overlay run (or a revert) is already going."""


class StillGoing(MaintainerrProblem):
    """No answer in time, but the request may well be running: Maintainerr answers a revert only when it's done,
    and a proxy in front of it may give up first (502/504)."""


@dataclass
class OwnedCollection:
    id: int  # Maintainerr's own id
    title: str  # the Plex collection's name (a manual collection's linked name)
    library_key: str  # Plex section key
    rating_key: str | None  # the Plex collection's ratingKey
    active: bool
    overlays: bool  # Maintainerr draws overlays on its items


@dataclass
class Snapshot:
    collections: list[OwnedCollection] = field(default_factory=list)
    library_titles: dict[str, str] = field(default_factory=dict)  # Plex section key → title
    overlays_enabled: bool = False
    at: float = 0.0
    error: str | None = None

    def owned_by_title(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for collection in self.collections:
            title = self.library_titles.get(collection.library_key)
            if title:
                found.setdefault(title.lower(), []).append(collection.title)
        return found


def load(db: sqlite3.Connection) -> MaintainerrSettings:
    return MaintainerrSettings.model_validate(get_setting(db, SETTINGS) or {})


def parse_collections(data: Any) -> list[OwnedCollection]:
    if not isinstance(data, list):
        raise MaintainerrProblem("Unexpected answer from Maintainerr's /api/collections")
    found = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            continue
        manual = bool(item.get("manualCollection")) and item.get("manualCollectionName")
        found.append(
            OwnedCollection(
                id=int(item["id"]),
                title=str(item.get("manualCollectionName") if manual else item.get("title") or ""),
                library_key=str(item.get("libraryId") or ""),
                rating_key=str(item["mediaServerId"]) if item.get("mediaServerId") else None,
                active=bool(item.get("isActive", True)),
                overlays=bool(item.get("overlayEnabled")),
            )
        )
    return found


class Maintainerr:
    def __init__(self, db: sqlite3.Connection, http: httpx.AsyncClient, box: SecretBox, config: Path | None, kometa_root: Path | None):
        self.db = db
        self.http = http
        self.box = box
        self._wrapping = False  # a run is between Maintainerr reverting its overlays and drawing them again
        self.runner = None  # set by the app: queues Kometa's overlays before a daily redraw when they're needed first
        self.config = config
        self.kometa_root = kometa_root
        self.snapshot = Snapshot()
        self._task: asyncio.Task | None = None

    # --- API ---------------------------------------------------------------------------

    def connected(self) -> bool:
        return bool(load(self.db).url)

    def login(self, settings: MaintainerrSettings) -> tuple[str, str] | None:
        if not settings.username:
            return None
        return settings.username, (self.box.decrypt(settings.password) or "") if settings.password else ""

    async def _call(self, method: str, path: str, url: str | None = None, json: Any = None, auth: tuple[str, str] | None = None) -> Any:
        settings = load(self.db)
        base = (url or settings.url or "").rstrip("/")
        if not base:
            raise MaintainerrProblem("Maintainerr isn't connected")
        login = auth if url else self.login(settings)
        try:
            response = await self.http.request(
                method, base + path, headers={"Accept": "application/json"}, json=json, timeout=TIMEOUT, auth=login or httpx.USE_CLIENT_DEFAULT
            )
        except httpx.TimeoutException:
            raise StillGoing(f"Maintainerr didn't answer within {TIMEOUT:g} s") from None
        except httpx.HTTPError as error:
            raise MaintainerrProblem(f"Can't reach Maintainerr: {error}") from None
        if response.status_code == 403 and path.startswith("/api/overlays"):
            # Maintainerr guards its overlay endpoints with a check that its media server answers.
            raise MaintainerrProblem("Maintainerr can't reach its media server right now, so its overlays can't be managed")
        if response.status_code == 401:
            if "maintainerr" not in response.headers.get("content-type", "") and response.headers.get("www-authenticate", "").lower().startswith("basic"):
                raise MaintainerrProblem("The proxy in front of Maintainerr wants a username and password" + (" (these were refused)" if login else ""))
            raise MaintainerrProblem("Maintainerr refused the request (HTTP 401)")
        if response.status_code == 403:
            raise MaintainerrProblem("Maintainerr refused the request (HTTP 403)")
        if response.status_code in (502, 504):
            raise StillGoing(f"The proxy in front of Maintainerr gave up waiting (HTTP {response.status_code})")
        if response.status_code == 409:
            raise Busy("Maintainerr is in the middle of an overlay run")
        if response.status_code >= 400:
            raise MaintainerrProblem(f"Maintainerr answered HTTP {response.status_code} for {path}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise MaintainerrProblem("That address answered, but not like Maintainerr") from None

    async def _overlays_enabled(self, collections: list[OwnedCollection], url: str | None = None, auth: tuple[str, str] | None = None) -> bool:
        """Whether Maintainerr draws overlays at all. Only asked when a collection has them on.

        While Studio has them switched off for a run, they count as on: that's their real setting.
        """
        if not any(c.active and c.overlays for c in collections):
            return False
        if url is None and get_setting(self.db, PAUSED):
            return True
        settings = await self._call("GET", "/api/overlays/settings", url, auth=auth)
        return bool(isinstance(settings, dict) and settings.get("enabled"))

    async def test(self, url: str, auth: tuple[str, str] | None) -> dict:
        collections = parse_collections(await self._call("GET", "/api/collections", url, auth=auth))
        return {"collections": len(collections), "overlays_enabled": await self._overlays_enabled(collections, url, auth)}

    # --- The snapshot ------------------------------------------------------------------

    async def refresh(self) -> Snapshot:
        if not self.connected():
            self.snapshot = Snapshot(at=time.monotonic())
            return self.snapshot
        try:
            collections = parse_collections(await self._call("GET", "/api/collections"))
            overlays = await self._overlays_enabled(collections)
            titles = await self._plex_titles()
            self.snapshot = Snapshot(collections, titles, overlays, time.monotonic())
        except MaintainerrProblem as problem:
            # Keep what was known: a Maintainerr that's briefly down mustn't unprotect its collections.
            self.snapshot = Snapshot(self.snapshot.collections, self.snapshot.library_titles, self.snapshot.overlays_enabled, time.monotonic(), str(problem))
        return self.snapshot

    async def _plex_titles(self) -> dict[str, str]:
        try:
            plex = read_plex(self.config) if self.config else None
        except Exception:  # config.yml unreadable: the config checks say so
            plex = None
        if plex is None or not plex.url or not plex.token:
            return self.snapshot.library_titles
        try:
            return {library.key: library.title for library in await PlexServer(self.http, plex.url, plex.token).libraries()}
        except PlexUnavailable:
            return self.snapshot.library_titles

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="maintainerr")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
                if not self._wrapping and self.connected():
                    await self._resume(lambda line: log.info(line))
                    if self.controls():
                        await self.take_over()
                        await self._daily(time.time())
                    elif not load(self.db).leave_overlays_alone:
                        await self.hand_back()  # owed since the setting was turned off while Maintainerr didn't answer
            except MaintainerrProblem:
                pass  # kept on the snapshot / retried next time
            except Exception:
                log.exception("Maintainerr refresh failed")
            pending = get_setting(self.db, PAUSED) or get_setting(self.db, PENDING_PROCESS)
            await asyncio.sleep(RETRY if pending else REFRESH)

    # --- Who decides when Maintainerr draws ---------------------------------------------

    def controls(self) -> bool:
        """Whether Studio decides when Maintainerr draws: the setting is on and Maintainerr has overlays at all."""
        return self.connected() and load(self.db).leave_overlays_alone and self.snapshot.overlays_enabled and not self.snapshot.error

    async def take_over(self) -> None:
        """Set Maintainerr's overlay job to never run on its own, keeping its schedule to give back."""
        current = await self._call("GET", "/api/overlays/settings")
        cron = current.get("cronSchedule") if isinstance(current, dict) else None
        if cron == NEVER:
            return
        if get_setting(self.db, OWN_CRON) is None:
            set_setting(self.db, OWN_CRON, {"cron": cron})
        await self._call("PUT", "/api/overlays/settings", json={"cronSchedule": NEVER})
        if get_setting(self.db, LAST_REDRAW) is None:
            set_setting(self.db, LAST_REDRAW, time.time())  # it has just drawn on its own schedule; the daily redraw counts from now

    async def hand_back(self) -> None:
        """Give Maintainerr its own overlay schedule back."""
        own = get_setting(self.db, OWN_CRON)
        if own is None:
            return
        await self._call("PUT", "/api/overlays/settings", json={"cronSchedule": own.get("cron")})
        delete_setting(self.db, OWN_CRON)
        delete_setting(self.db, LAST_REDRAW)

    def schedule(self) -> dict:
        """For Settings → Connect: Maintainerr's own schedule, if Studio holds it, and the daily redraws."""
        own = get_setting(self.db, OWN_CRON)
        last = get_setting(self.db, LAST_REDRAW)
        return {
            "taken_over": own is not None,
            "own_cron": own.get("cron") if own else None,
            "last_redraw": _utc(last) if last else None,
            "next_redraw": _utc(last + DAILY) if last else None,
        }

    async def _daily(self, now: float) -> None:
        last = get_setting(self.db, LAST_REDRAW)
        if last is not None and now - last < DAILY:
            return
        set_setting(self.db, LAST_REDRAW, now)
        first = await self._kometa_first()
        if first and self.runner is not None:
            # Kometa's overlays go on first; the run's after step has Maintainerr draw.
            self.runner.enqueue(RunRequest(mode="overlays", libraries=first), trigger="maintainerr")
            log.info("Daily Maintainerr redraw: Kometa's overlays run first for %s", ", ".join(first))
            return
        set_setting(self.db, PENDING_PROCESS, True)
        await self._resume(lambda line: log.info(line))

    async def _kometa_first(self) -> list[str]:
        """Kometa libraries with overlays and Maintainerr overlay collections that got something since Kometa's last overlay pass there."""
        try:
            plans = wanted.plan(self.config, self.kometa_root) if self.config else {}
        except (FileNotFoundError, ValueError):
            return []
        by_title = {plan.plex_name.lower(): plan.name for plan in plans.values() if plan.overlays}
        try:
            current = read_plex(self.config) if self.config else None
            plex = PlexServer(self.http, current.url, current.token) if current and current.url and current.token else None
            types = {library.key: library.type for library in await plex.libraries()} if plex else {}
        except (PlexUnavailable, OSError, ValueError):
            plex, types = None, {}
        first: list[str] = []
        for collection in self._overlaid([]):
            name = by_title.get(self.snapshot.library_titles.get(collection.library_key, "").lower())
            if name is None or name in first:
                continue
            since = self._last_overlay_pass(name)
            try:
                added = await plex.added_since(collection.library_key, types.get(collection.library_key, "movie"), since) if plex and since else 1
            except PlexUnavailable:
                added = 1  # can't tell: Kometa first
            if added:
                first.append(name)
        return first

    def _last_overlay_pass(self, library: str) -> int | None:
        """When Kometa's last finished overlay pass over this library started (Unix time)."""
        for row in self.db.execute("SELECT request, started_at FROM runs WHERE status = 'succeeded' AND started_at IS NOT NULL ORDER BY id DESC"):
            request = RunRequest.model_validate_json(row[0])
            if request.mode in ("all", "overlays") and not request.collections and (not request.libraries or library in request.libraries):
                return int(datetime.fromisoformat(row[1].replace("Z", "+00:00")).timestamp())
        return None

    # --- Kometa's config ------------------------------------------------------------

    def risks(self, config_path: Path | None = None, kometa_root: Path | None = None) -> list[Risk]:
        path = config_path or self.config
        if path is None or not self.snapshot.collections:
            return []
        return maintainerr_guard.risks(path, kometa_root or self.kometa_root, self.snapshot.owned_by_title())

    # --- Runs -------------------------------------------------------------------------

    async def before_run(self, request: RunRequest, say: Say) -> After | None:
        if not self.connected():
            return None
        await self.refresh()
        reached = [r for r in self.risks() if maintainerr_guard.reaches(r, request.mode, request.libraries, request.collections)]
        if reached:
            raise RunHeld("Held, so Kometa doesn't touch Maintainerr's collections: " + " ".join(r.message for r in reached))
        if not load(self.db).leave_overlays_alone or request.mode not in POSTER_MODES or request.collections:
            return None
        overlaid = self._overlaid(request.libraries)
        if not overlaid:
            return None
        if self.snapshot.error:
            raise RunHeld(
                f"Held: {self.snapshot.error}. With “Leave Maintainerr overlays alone” on, Kometa only changes posters "
                "after Maintainerr has put its own back."
            )
        if not self.snapshot.overlays_enabled:
            return None
        await self._wait_until_idle(say)
        self._wrapping = True
        try:
            await self.take_over()  # its own schedule can't draw while Kometa runs
            say(f"Maintainerr puts back the posters under its overlays ({len(overlaid)} collection(s)), so Kometa only sees its own posters.")
            for collection in overlaid:
                try:
                    await self._call("POST", f"/api/overlays/revert/{collection.id}")
                except StillGoing:
                    say("Maintainerr is still putting posters back (it goes through every show, season and episode); waiting for it…")
                await self._wait_until_idle(say, REVERT_WAIT, quiet=True)
        except (MaintainerrProblem, RunHeld) as problem:
            set_setting(self.db, PENDING_PROCESS, True)
            await self._resume(say)
            self._wrapping = False
            raise RunHeld(str(problem) if isinstance(problem, RunHeld) else f"Held: {problem}") from None

        async def after() -> None:
            try:
                set_setting(self.db, PENDING_PROCESS, True)
                await self._resume(say)
            finally:
                self._wrapping = False

        return after

    def _overlaid(self, libraries: list[str]) -> list[OwnedCollection]:
        """Maintainerr's collections with overlays, in the run's libraries (every library if none are named)."""
        wanted = None
        if libraries:
            wanted = {self._plex_title(name).lower() for name in libraries}
        return [
            c
            for c in self.snapshot.collections
            if c.active and c.overlays and (wanted is None or self.snapshot.library_titles.get(c.library_key, "").lower() in wanted)
        ]

    def _plex_title(self, kometa_name: str) -> str:
        try:
            data = load_yaml(self.config) if self.config else {}
            body = (data or {}).get("libraries", {}).get(kometa_name) or {}
            return str(body.get("library_name") or kometa_name) if isinstance(body, dict) else kometa_name
        except Exception:
            return kometa_name

    async def _wait_until_idle(self, say: Say, limit: float | None = None, quiet: bool = False) -> None:
        """Until Maintainerr's overlay processor is idle: its status says "running" during runs and reverts."""
        limit = BUSY_WAIT if limit is None else limit
        deadline = time.monotonic() + limit
        said = quiet
        while time.monotonic() < deadline:
            status = await self._call("GET", "/api/overlays/status")
            if not (isinstance(status, dict) and status.get("status") == "running"):
                return
            if not said:
                say("Waiting for Maintainerr's own overlay run to finish…")
                said = True
            await asyncio.sleep(POLL)
        raise RunHeld(f"Held: Maintainerr's overlay processor is still busy after {limit / 60:.0f} minutes")

    async def _resume(self, say: Say) -> None:
        """Have Maintainerr draw, if a run left that undone. (Also switches its overlays back on if an older Studio paused them.)

        Each step's flag is cleared only once Maintainerr has done it, so the loop retries what's left.
        """
        try:
            if get_setting(self.db, PAUSED):
                await self._call("PUT", "/api/overlays/settings", json={"enabled": True})
                set_setting(self.db, PAUSED, False)
            if get_setting(self.db, PENDING_PROCESS):
                try:
                    await self._call("POST", "/api/overlays/process", json={})
                except Busy:
                    say("Maintainerr is busy; asking again once it's done…")
                    try:
                        await self._wait_until_idle(say, quiet=True)
                    except RunHeld:
                        raise Busy("Maintainerr stayed busy") from None
                    await self._call("POST", "/api/overlays/process", json={})
                set_setting(self.db, PENDING_PROCESS, False)
                set_setting(self.db, LAST_REDRAW, time.time())
                say("Maintainerr is drawing its overlays again, on top of Kometa's.")
        except MaintainerrProblem as problem:
            say(f"Couldn't have Maintainerr draw its overlays again ({problem}); Studio keeps trying every few minutes.")


def _utc(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
