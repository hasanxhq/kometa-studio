"""Moving over from Kometa: ``GET /api/v1/import`` (the read-only report of how each collection would land), and
Switch over, Undo and Export (``switch_over``).
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import collections as col
from . import full_backup, kometa_import, switch_over
from .builder_routes import _context, _delete_from_plex
from .config_write import SaveRefused
from .kometa_command import RunRequest
from .plex_library import PlexUnavailable
from .plex_routes import kometa_plex
from .ready_made_routes import AppRunner, AppSettings, Db, Writer, _kometa_root, _library_types, _plex_title, _reader

router = APIRouter(prefix="/api/v1", tags=["import"])


async def library_types(request: Request, settings, libraries) -> dict[str, str | None]:
    """config.yml library name → Plex section type ('movie', 'show', …), or None for all when Plex can't be reached."""
    try:
        server = kometa_plex(settings, request.app.state.http)
        types = await _library_types.types(server)
    except (HTTPException, PlexUnavailable):
        return {library.name: None for library in libraries}
    return {library.name: types.get(_plex_title(library).casefold(), "") for library in libraries}


def taken_titles(db, libraries) -> dict[str, set[str]]:
    """Titles Studio already has per library (builder collections and ready-made picks), casefolded."""
    out: dict[str, set[str]] = {library.name: set() for library in libraries}
    for row in db.execute("SELECT library, title FROM collections"):
        out.setdefault(row["library"], set()).add(str(row["title"]).casefold())
    return out


def maintainerr_titles(request: Request, libraries) -> dict[str, dict[str, str]]:
    """Titles Maintainerr owns, per config.yml library: Studio never takes one over (Kometa adopts by title)."""
    service = getattr(request.app.state, "maintainerr", None)
    if service is None or not service.connected():
        return {}
    owned = service.snapshot.owned_by_title()
    return {
        library.name: {title.casefold(): "Maintainerr has a collection with this title, and Studio never takes one over" for title in owned.get(_plex_title(library).casefold(), [])}
        for library in libraries
    }


async def build_report(request: Request, settings, db) -> dict:
    reader = _reader(settings)
    try:
        config = reader.read()
    except FileNotFoundError:
        return {"summary": kometa_import.summarise([]), "libraries": [], "playlist_files": [], "config": False}
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    types = await library_types(request, settings, config.libraries)
    out = kometa_import.report(
        reader, types, taken_titles(db, config.libraries), set(col.generated(db)), _kometa_root(settings), maintainerr_titles(request, config.libraries)
    )
    out["config"] = True
    return out


@router.get("/import")
async def import_report(request: Request, settings: AppSettings, db: Db) -> dict:
    """How each collection in Kometa's files would land in Studio: imported, ready-made or kept, with reasons."""
    return await build_report(request, settings, db)


# --- Switch over, Undo, Export (step 3) ----------------------------------------------------------------


class SwitchIn(BaseModel):
    confirm: bool = False


class UndoIn(BaseModel):
    confirm: bool = False
    delete_from_plex: bool = False


def _active_or_409(db) -> sqlite3.Row:
    row = switch_over.active(db)
    if row is None:
        raise HTTPException(409, "Studio hasn't switched over from Kometa, so there's nothing to undo")
    return row


@router.get("/import/switch-over")
async def get_switch_over(db: Db) -> dict:
    return {"active": switch_over.describe(switch_over.active(db))}


@router.post("/import/switch-over")
async def do_switch_over(body: SwitchIn, request: Request, settings: AppSettings, db: Db, writer: Writer, runner: AppRunner) -> dict:
    """Move Kometa's importable collections into Studio, after a full backup, and build them in one run."""
    if not body.confirm:
        raise HTTPException(422, "Tick the box to confirm the switch-over")
    root = _kometa_root(settings)
    if root is None:
        raise HTTPException(409, "Studio doesn't know where Kometa is. Set STUDIO_KOMETA_ENTRY.")
    report = await build_report(request, settings, db)
    if not report.get("config"):
        raise HTTPException(409, "Kometa's config.yml doesn't exist yet. Connect Plex first.")
    all_libraries = [library["name"] for library in report["libraries"]]
    try:
        described, runs, created = await switch_over.switch_over(db, writer, root, settings.data_dir, settings.db_path, report, all_libraries)
    except switch_over.SwitchRefused as refused:
        raise HTTPException(refused.status, refused.message) from None
    except SaveRefused as refused:
        raise HTTPException(refused.status, refused.detail()) from None
    except full_backup.BackupFailed as error:
        raise HTTPException(507, f"Not switched over: the backup failed. {error}") from None
    names = sorted({name for _library, titles in runs for name in titles})
    run_id = runner.enqueue(RunRequest(mode="collections", libraries=[library for library, _ in runs], collections=names), trigger="switch_over")
    with db:
        col.set_run(db, created, run_id)
        switch_over.set_run(db, described["id"], run_id)
    described["run_id"] = run_id
    return {"switch_over": described, "run_id": run_id}


@router.get("/import/undo")
async def undo_preview(settings: AppSettings, db: Db, writer: Writer) -> dict:
    """What Undo would throw away (collections added or changed since) and put back."""
    row = _active_or_409(db)
    try:
        return switch_over.preview(db, settings.data_dir, writer.config_dir, row)
    except switch_over.SwitchRefused as refused:
        raise HTTPException(refused.status, refused.message) from None


@router.post("/import/undo")
async def do_undo(body: UndoIn, request: Request, settings: AppSettings, db: Db, writer: Writer, runner: AppRunner) -> dict:
    """Put Kometa's files and Studio's collections back as they were at the switch-over (after a full backup)."""
    if not body.confirm:
        raise HTTPException(422, "Tick the box to confirm Undo")
    row = _active_or_409(db)
    if runner.current_run_id is not None:
        raise HTTPException(409, "A Kometa run is going. Wait for it to finish, then undo.")
    try:
        before = switch_over.preview(db, settings.data_dir, writer.config_dir, row)
    except switch_over.SwitchRefused as refused:
        raise HTTPException(refused.status, refused.message) from None
    with tempfile.TemporaryDirectory() as scratch:
        async with writer.lock:  # no save lands while the files go back
            try:
                restored, safety, then_db = await asyncio.to_thread(
                    switch_over.restore_files, settings.data_dir, writer.config_dir, settings.db_path, row["backup"], Path(scratch)
                )
            except switch_over.SwitchRefused as refused:
                raise HTTPException(refused.status, refused.message) from None
            except full_backup.BackupFailed as error:
                raise HTTPException(507, f"Not undone: the backup before Undo failed. {error}") from None
            result = switch_over.finish_undo(db, row, then_db, restored, safety)
    deleted: list[str] = []
    problems: list[str] = []
    if body.delete_from_plex:
        for entry in before["plex"]:
            try:
                context = await _context(request, settings, entry["library"])
            except HTTPException as error:
                problems.append(f"{entry['title']}: {error.detail}")
                continue
            gone, why = await _delete_from_plex(context, entry["title"])
            if gone:
                deleted.append(entry["title"])
            elif why:
                problems.append(f"{entry['title']}: {why}")
    return result | {"deleted_from_plex": deleted, "problems": problems}


@router.get("/import/export")
async def export_setup(settings: AppSettings) -> FileResponse:
    """A zip of a working Kometa setup (config.yml, every file it lists, Studio's own files)."""
    reader = _reader(settings)
    try:
        path = await asyncio.to_thread(switch_over.export, reader, settings.data_dir)
    except FileNotFoundError:
        raise HTTPException(409, "Kometa's config.yml doesn't exist yet") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return FileResponse(path, media_type="application/zip", filename=path.name)
