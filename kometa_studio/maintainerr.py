"""Maintainerr: Kometa leaves its collections alone, and optionally its overlays (handoff v2 §4.5).

Studio reads Maintainerr's collections over its API (``/api/collections``) and keeps a snapshot,
refreshed every ``REFRESH`` and before each run. With that it:

- shows Maintainerr's collections as Maintainerr's in Libraries (matched by Plex rating key);
- refuses a save that adds a way for Kometa to touch them (maintainerr_guard), and holds a run that
  would, saying why;
- with "Leave Maintainerr overlays alone" on, wraps every Kometa run that can change posters: first
  Maintainerr reverts its overlays (``POST /api/overlays/revert/{id}``: its saved poster goes back and
  its overlay state is dropped), so Kometa only ever sees, and backs up as "original", posters without
  Maintainerr's countdown; afterwards Maintainerr processes again (``POST /api/overlays/process``),
  saving Kometa's fresh poster as its original and drawing its countdown on top. Maintainerr's
  overlay is applied last, so it's the one that shows.

If Maintainerr doesn't answer when a poster-changing run starts and the setting is on, the run is held:
running Kometa then could bake the countdown into Kometa's Original Posters.
"""

import asyncio
import contextlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from . import maintainerr_guard
from .crypto import SecretBox
from .db import get_setting, set_setting
from .kometa_command import RunRequest
from .kometa_config import read_plex
from .kometa_files import load_yaml
from .maintainerr_guard import Risk
from .plex_library import PlexServer, PlexUnavailable
from .runner import After, RunHeld, Say

log = logging.getLogger(__name__)

SETTINGS = "maintainerr"  # {url, api_key (encrypted, optional), leave_overlays_alone}
PENDING_PROCESS = "maintainerr.pending_process"  # an after step that didn't reach Maintainerr
REFRESH = 300.0
TIMEOUT = 15.0
BUSY_WAIT = 600.0  # how long to wait for Maintainerr's own overlay run to finish
POSTER_MODES = frozenset({"all", "overlays", "operations", "metadata"})  # runs that can change posters


class MaintainerrSettings(BaseModel):
    url: str | None = None
    api_key: str | None = None  # encrypted
    leave_overlays_alone: bool = True


class MaintainerrProblem(Exception):
    pass


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
        self.config = config
        self.kometa_root = kometa_root
        self.snapshot = Snapshot()
        self._task: asyncio.Task | None = None

    # --- API ---------------------------------------------------------------------------

    def connected(self) -> bool:
        return bool(load(self.db).url)

    def _key(self, settings: MaintainerrSettings) -> str | None:
        return self.box.decrypt(settings.api_key) if settings.api_key else None

    async def _call(self, method: str, path: str, url: str | None = None, key: str | None = None, json: Any = None) -> Any:
        settings = load(self.db)
        base = (url or settings.url or "").rstrip("/")
        if not base:
            raise MaintainerrProblem("Maintainerr isn't connected")
        api_key = key if url else self._key(settings)
        headers = {"Accept": "application/json"} | ({"X-Api-Key": api_key} if api_key else {})
        try:
            response = await self.http.request(method, base + path, headers=headers, json=json, timeout=TIMEOUT)
        except httpx.TimeoutException:
            raise MaintainerrProblem(f"Maintainerr didn't answer within {TIMEOUT:g} s") from None
        except httpx.HTTPError as error:
            raise MaintainerrProblem(f"Can't reach Maintainerr: {error}") from None
        if response.status_code in (401, 403):
            raise MaintainerrProblem("Maintainerr refused the request (check the API key)")
        if response.status_code >= 400:
            raise MaintainerrProblem(f"Maintainerr answered HTTP {response.status_code} for {path}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise MaintainerrProblem("That address answered, but not like Maintainerr") from None

    async def test(self, url: str, key: str | None) -> dict:
        collections = parse_collections(await self._call("GET", "/api/collections", url, key))
        overlays = await self._call("GET", "/api/overlays/settings", url, key)
        return {"collections": len(collections), "overlays_enabled": bool(isinstance(overlays, dict) and overlays.get("enabled"))}

    # --- The snapshot ------------------------------------------------------------------

    async def refresh(self) -> Snapshot:
        if not self.connected():
            self.snapshot = Snapshot(at=time.monotonic())
            return self.snapshot
        try:
            collections = parse_collections(await self._call("GET", "/api/collections"))
            overlays = await self._call("GET", "/api/overlays/settings")
            titles = await self._plex_titles()
            self.snapshot = Snapshot(collections, titles, bool(isinstance(overlays, dict) and overlays.get("enabled")), time.monotonic())
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
                if get_setting(self.db, PENDING_PROCESS) and self.connected():
                    await self._call("POST", "/api/overlays/process", json={})
                    set_setting(self.db, PENDING_PROCESS, False)
            except MaintainerrProblem:
                pass  # kept on the snapshot / retried next time
            except Exception:
                log.exception("Maintainerr refresh failed")
            await asyncio.sleep(REFRESH)

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
        if self.snapshot.error:
            raise RunHeld(
                f"Held: {self.snapshot.error}. With “Leave Maintainerr overlays alone” on, Kometa only changes posters "
                "after Maintainerr has put its own back."
            )
        overlaid = self._overlaid(request.libraries)
        if not self.snapshot.overlays_enabled or not overlaid:
            return None
        await self._wait_until_idle(say)
        say(f"Maintainerr puts back the posters under its overlays first ({len(overlaid)} collection(s)), so its countdowns stay out of Kometa's originals.")
        reverted = []
        try:
            for collection in overlaid:
                await self._call("POST", f"/api/overlays/revert/{collection.id}")
                reverted.append(collection)
        except MaintainerrProblem as problem:
            if reverted:
                await self._process(say)
            raise RunHeld(f"Held: {problem}") from None

        async def after() -> None:
            await self._process(say)

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

    async def _wait_until_idle(self, say: Say) -> None:
        deadline = time.monotonic() + BUSY_WAIT
        said = False
        while time.monotonic() < deadline:
            status = await self._call("GET", "/api/overlays/status")
            if not (isinstance(status, dict) and status.get("status") == "running"):
                return
            if not said:
                say("Waiting for Maintainerr's own overlay run to finish…")
                said = True
            await asyncio.sleep(5)
        raise RunHeld("Held: Maintainerr's overlay run is still going after 10 minutes")

    async def _process(self, say: Say) -> None:
        try:
            await self._call("POST", "/api/overlays/process", json={})
            set_setting(self.db, PENDING_PROCESS, False)
            say("Maintainerr is drawing its overlays again, on top of Kometa's.")
        except MaintainerrProblem as problem:
            set_setting(self.db, PENDING_PROCESS, True)  # retried every few minutes until it works
            say(f"Couldn't ask Maintainerr to draw its overlays again ({problem}); Studio keeps trying.")
