"""Run hook: record Plex state for ready-made picks after Kometa finishes."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import httpx

from . import collections as col
from .kometa_command import RunRequest
from .kometa_config import read_plex
from .kometa_files import ConfigReader
from .plex_library import PlexServer, PlexUnavailable
from .runner import KOMETA_CRITICAL, After, Say
from .settings import Settings
from .tasks import Tasks

log = logging.getLogger(__name__)

STUDIO_LABEL = "Studio"


def _critical_lines(config: Path | None) -> list[str]:
    if config is None:
        return []
    path = config.parent / "logs" / "meta.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m.group(1).strip() for m in KOMETA_CRITICAL.finditer(text) if m.group(1).strip()]


def _plex_title(library) -> str:
    return str(library.settings.get("library_name") or library.name)


class ReadyMadeRecorder:
    """After a run that touches ready-made rows, sync their Plex state (only if ``run_end`` arrived)."""

    def __init__(
        self,
        db: sqlite3.Connection,
        runner,
        settings: Settings,
        http: httpx.AsyncClient,
        tasks: Tasks | None = None,
    ):
        self.db = db
        self.runner = runner
        self.settings = settings
        self.http = http
        self.tasks = tasks

    def _tracked_rows(self, request: RunRequest, run_id: int, trigger: str) -> list[sqlite3.Row]:
        by_run = list(self.db.execute("SELECT * FROM collections WHERE last_run_id = ?", (run_id,)))
        if by_run or trigger == "ready-made":
            return by_run
        if trigger in ("schedule", "catch_up") and request.mode in ("all", "collections") and not request.collections and not request.files:
            if self.settings.kometa_config is None:
                return []
            try:
                libraries = ConfigReader(
                    self.settings.kometa_config,
                    self.settings.kometa_entry.parent if self.settings.kometa_entry else None,
                ).read().libraries
            except (FileNotFoundError, ValueError, OSError):
                return []
            names = request.libraries or [lib.name for lib in libraries]
            rows: list[sqlite3.Row] = []
            for name in names:
                rows.extend(self.db.execute("SELECT * FROM collections WHERE library = ? AND desired = 1", (name,)))
            return rows
        if request.collections:
            placeholders = ",".join("?" * len(request.collections))
            params: list = list(request.collections)
            sql = f"SELECT * FROM collections WHERE kometa_name IN ({placeholders})"
            if request.libraries:
                lib_ph = ",".join("?" * len(request.libraries))
                sql += f" AND library IN ({lib_ph})"
                params.extend(request.libraries)
            return list(self.db.execute(sql, params))
        return []

    async def before_run(self, request: RunRequest, say: Say) -> After | None:
        run_id = self.runner.current_run_id
        if run_id is None:
            return None
        row = self.db.execute("SELECT trigger FROM runs WHERE id = ?", (run_id,)).fetchone()
        trigger = row["trigger"] if row else "manual"
        tracked = self._tracked_rows(request, run_id, trigger)
        if not tracked and trigger != "ready-made":
            return None
        libraries = sorted({r["library"] for r in tracked}) or list(request.libraries)

        async def after() -> None:
            try:
                await self._after(run_id, tracked, libraries, say)
            except Exception as error:  # never raise into the runner
                log.exception("Ready-made Plex state after run #%s", run_id)
                say(f"couldn't update ready-made Plex state: {error}")

        return after

    async def _after(self, run_id: int, tracked: list[sqlite3.Row], libraries: list[str], say: Say) -> None:
        ended = self.db.execute("SELECT 1 FROM run_events WHERE run_id = ? AND event = 'run_end'", (run_id,)).fetchone()
        if not ended:
            critical = _critical_lines(self.settings.kometa_config)
            message = "Kometa's run didn't finish (no run_end)"
            if critical:
                message = message + "\n" + "\n".join(critical)
            with self.db:
                for row in tracked:
                    self.db.execute(
                        "UPDATE collections SET last_error = ?, updated_at = datetime('now') WHERE id = ?",
                        (message, row["id"]),
                    )
            say("ready-made: Kometa's run didn't finish (no run_end)")
            return

        if self.settings.kometa_config is None:
            return
        try:
            current = read_plex(self.settings.kometa_config)
        except (OSError, ValueError):
            return
        if not current.url or not current.token:
            return
        server = PlexServer(self.http, current.url, current.token)

        try:
            reader = ConfigReader(
                self.settings.kometa_config,
                self.settings.kometa_entry.parent if self.settings.kometa_entry else None,
            )
            config_libs = {lib.name: lib for lib in reader.read().libraries}
        except (FileNotFoundError, ValueError, OSError) as error:
            say(f"ready-made: couldn't read config.yml ({error})")
            return

        try:
            plex_libs = {lib.title.casefold(): lib for lib in await server.libraries()}
        except PlexUnavailable as error:
            say(f"ready-made: Plex unavailable ({error})")
            return

        tracked_ids = {int(r["id"]) for r in tracked}
        for name in libraries:
            lib = config_libs.get(name)
            if lib is None:
                continue
            plex = plex_libs.get(_plex_title(lib).casefold())
            if plex is None:
                continue
            try:
                labelled = await server.labelled_collections(plex.key, STUDIO_LABEL)
            except PlexUnavailable as error:
                say(f"ready-made: couldn't list Studio collections in {name}: {error}")
                continue
            by_title = {c.title.casefold(): c for c in labelled}
            with self.db:
                for row in col.rows(self.db, name):
                    match = by_title.get(row["title"].casefold())
                    exists = match is not None
                    if int(row["id"]) in tracked_ids:
                        error = None if exists else f"Kometa finished, but Plex has no collection called {row['title']}"
                        col.record_plex_state(
                            self.db,
                            int(row["id"]),
                            exists=exists,
                            rating_key=match.rating_key if match else None,
                            items=match.items if match else None,
                            thumb=match.thumb if match else None,
                            built=exists,
                            error=error,
                        )
                    else:
                        col.record_plex_state(
                            self.db,
                            int(row["id"]),
                            exists=exists,
                            rating_key=match.rating_key if match else None,
                            items=match.items if match else None,
                            thumb=match.thumb if match else None,
                            built=False,
                            error=row["last_error"],
                        )
        say("ready-made: updated Plex state for Studio collections")
        if self.tasks is not None:
            self.tasks.start("ready_made_counts")
