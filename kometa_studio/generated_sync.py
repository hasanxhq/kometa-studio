"""Run hook: before every Kometa run, Studio's generated files are put back to what Studio wants.

Studio fully manages ``config/studio/``. A hand edit, a deleted file or a dropped ``- file:`` entry in
config.yml is undone before Kometa reads them, without asking: the files are rendered from Studio's picks
and saved through ``ConfigWriter`` (Kometa's check, a backup) only when something differs. The run's log
says what was put back.
"""

from __future__ import annotations

import logging
import sqlite3

import httpx

from . import collections as col
from . import studio_files
from .config_write import ConfigWriter, SaveRefused
from .kometa_command import RunRequest
from .kometa_config import read_plex
from .kometa_files import ConfigReader
from .plex_library import PlexServer, PlexUnavailable
from .runner import After, Say
from .settings import Settings

log = logging.getLogger(__name__)


class GeneratedFiles:
    def __init__(self, db: sqlite3.Connection, settings: Settings, writer: ConfigWriter | None, http: httpx.AsyncClient):
        self.db = db
        self.settings = settings
        self.writer = writer
        self.http = http

    async def before_run(self, request: RunRequest, say: Say) -> After | None:
        try:
            await self.sync(say)
        except Exception as error:  # never stop a run over this
            log.exception("Putting Studio's generated files back")
            say(f"couldn't check Studio's generated files: {error}")
        return None

    def _libraries(self) -> list:
        """config.yml's libraries that have picks, or a generated folder still on disk."""
        assert self.settings.kometa_config is not None
        root = self.settings.kometa_entry.parent if self.settings.kometa_entry else None
        libraries = ConfigReader(self.settings.kometa_config, root).read().libraries
        names = [lib.name for lib in libraries]
        folders = studio_files.library_folders(names)
        studio = self.settings.kometa_config.parent / studio_files.STUDIO_FOLDER
        return [lib for lib in libraries if col.desired(self.db, lib.name) or (studio / folders[lib.name]).is_dir()]

    async def sync(self, say: Say) -> list[str]:
        """Put every library's generated files right; returns the config-relative paths that were saved or removed."""
        settings, writer = self.settings, self.writer
        if writer is None or settings.kometa_config is None or settings.kometa_entry is None or not settings.kometa_config.is_file():
            return []
        try:
            libraries = self._libraries()
        except (FileNotFoundError, ValueError, OSError):
            return []
        if not libraries:
            return []
        current = read_plex(settings.kometa_config)
        if not current.url or not current.token:
            return []
        try:
            types = {lib.title.casefold(): lib.type for lib in await PlexServer(self.http, current.url, current.token).libraries()}
        except PlexUnavailable as error:
            say(f"didn't check Studio's generated files: {error}")
            return []
        all_names = [lib.name for lib in ConfigReader(settings.kometa_config, settings.kometa_entry.parent).read().libraries]
        changed: list[str] = []
        for library in libraries:
            library_type = types.get(str(library.settings.get("library_name") or library.name).casefold())
            if library_type not in ("movie", "show"):
                continue
            edited = studio_files.hand_edited(self.db, settings.kometa_config.parent, library.name, all_names)
            try:
                written = await studio_files.write_library(
                    writer,
                    settings.kometa_entry.parent,
                    library.name,
                    library_type,
                    col.desired(self.db, library.name),
                    all_names,
                    f"Put Studio's generated files for {library.name} back before a run",
                )
            except SaveRefused as refused:
                say(f"couldn't put Studio's generated files for {library.name} back: {refused.message}")
                continue
            with self.db:
                studio_files.record(self.db, written)
            if written.saved is None:
                continue
            paths = [f["path"] for f in written.saved["files"]] + written.saved.get("removed", [])
            changed += paths
            if edited:
                say(f"{', '.join(edited)} had been changed by hand: put Studio's version back")
            else:
                say(f"brought Studio's generated files for {library.name} up to date: {', '.join(paths)}")
        return changed
