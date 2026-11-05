"""Moving over from Kometa: ``GET /api/v1/import`` (the read-only report of how each collection would land),
Switch over, Undo and Export (``switch_over``), and uploading a collection file for a library.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import collections as col
from . import full_backup, kometa_import, studio_files, switch_over
from .builder_routes import _context, _delete_from_plex
from .config_sections import with_library_file
from .config_write import Edit, SaveRefused
from .kometa_command import RunRequest
from .plex_library import PlexUnavailable
from .plex_routes import kometa_plex
from .ready_made_routes import AppRunner, AppSettings, Db, Writer, _kometa_root, _library_types, _plex_title, _reader

router = APIRouter(prefix="/api/v1", tags=["import"])

UPLOAD_MAX_BYTES = 1024 * 1024
UPLOAD_TTL_SECONDS = 24 * 60 * 60
UPLOADS_DIR = "uploads"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


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


# --- Upload a collection file -----------------------------------------------------------------


class AddUploadIn(BaseModel):
    library: str
    confirm: bool = False


def _uploads_dir(data_dir: Path) -> Path:
    folder = data_dir / UPLOADS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _clean_uploads(folder: Path) -> None:
    """Drop staged uploads older than a day (yml + sidecar)."""
    cutoff = time.time() - UPLOAD_TTL_SECONDS
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.suffix not in (".yml", ".json"):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_filename(name: str) -> str:
    base = Path(name).name.strip() or "upload.yml"
    if not base.lower().endswith((".yml", ".yaml")):
        base = f"{base}.yml"
    stem = SAFE_NAME.sub("-", Path(base).stem).strip(".-") or "upload"
    suffix = Path(base).suffix.lower() or ".yml"
    return f"{stem}{suffix}"


def _unique_config_path(folder: Path, name: str, taken_stems: set[str] = frozenset()) -> Path:
    """A free path in ``folder`` whose stem no other file of the library uses: Kometa's ``--run-files`` matches by
    stem (``meta.py`` ``get_file_name``), so a shared stem would run the other file too."""
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = folder / name, 2
    while candidate.exists() or candidate.stem in taken_stems:
        candidate = folder / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def _read_upload(data_dir: Path, token: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"[0-9a-f]{16}", token):
        raise HTTPException(404, "No such upload")
    folder = _uploads_dir(data_dir)
    path = folder / f"{token}.yml"
    meta_path = folder / f"{token}.json"
    if not path.is_file() or not meta_path.is_file():
        raise HTTPException(404, "No such upload (it may have expired)")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "No such upload (it may have expired)") from None
    return path, meta


def _delete_upload(data_dir: Path, token: str) -> None:
    folder = _uploads_dir(data_dir)
    (folder / f"{token}.yml").unlink(missing_ok=True)
    (folder / f"{token}.json").unlink(missing_ok=True)


async def _library_for_upload(request: Request, settings, name: str):
    """config.yml library + Plex type ('movie'/'show'), or 4xx."""
    reader = _reader(settings)
    try:
        config = reader.read()
    except FileNotFoundError:
        raise HTTPException(409, "Kometa's config.yml doesn't exist yet. Connect Plex first.") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    library = next((lib for lib in config.libraries if lib.name == name), None)
    if library is None:
        raise HTTPException(404, f"No library called {name!r} in config.yml")
    types = await library_types(request, settings, config.libraries)
    library_type = types.get(name) or None
    if library_type not in ("movie", "show"):
        raise HTTPException(422, f"Studio can only import collection files into movie and show libraries (Plex type for {name!r} is {library_type!r})")
    return library, library_type, [lib.name for lib in config.libraries]


@router.post("/import/upload")
async def upload_collection_file(
    request: Request,
    settings: AppSettings,
    db: Db,
    library: str = Query(..., min_length=1),
) -> dict:
    """Stage a collection YAML file: same import as Move over, stored under ``<data dir>/uploads/``."""
    data = await request.body()
    if not data:
        raise HTTPException(422, "Send the YAML file as the request body")
    if len(data) > UPLOAD_MAX_BYTES:
        raise HTTPException(422, "File must be 1 MB or smaller")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "File must be UTF-8 text") from None
    try:
        parsed = YAML(typ="safe", pure=True).load(text)
    except YAMLError as error:
        raise HTTPException(422, f"File isn't valid YAML: {str(error).splitlines()[0]}") from None
    if not isinstance(parsed, dict):
        raise HTTPException(422, "File must hold a mapping at the top level (a Kometa collection file)")

    lib, library_type, _names = await _library_for_upload(request, settings, library)
    libraries = [lib]
    taken = taken_titles(db, libraries).get(library, set())
    blocked = maintainerr_titles(request, libraries).get(library)
    action, reason, landings = kometa_import.describe_file(text, library_type, taken, None, blocked)
    filename = request.headers.get("x-filename") or "upload.yml"
    filename = Path(filename).name.strip() or "upload.yml"
    file = kometa_import.FileLanding("file", filename, None, action, reason, landings)

    folder = _uploads_dir(settings.data_dir)
    _clean_uploads(folder)
    token = hashlib.sha256(data).hexdigest()[:16]
    (folder / f"{token}.yml").write_bytes(data)
    (folder / f"{token}.json").write_text(
        json.dumps({"filename": filename, "library": library, "created_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    return {"token": token, "library": library, "file": file.json()}


@router.post("/import/upload/{token}/add")
async def add_uploaded_file(
    token: str,
    body: AddUploadIn,
    request: Request,
    settings: AppSettings,
    db: Db,
    writer: Writer,
    runner: AppRunner,
) -> dict:
    """Commit a staged upload: import as builder collections, or keep the file unchanged under ``uploads/``."""
    if not body.confirm:
        raise HTTPException(422, "Confirm to add the uploaded file")
    path, meta = _read_upload(settings.data_dir, token)
    library = body.library
    if library != meta.get("library"):
        raise HTTPException(422, f"This upload was for {meta.get('library')!r}, not {library!r}")
    text = path.read_text(encoding="utf-8")
    filename = str(meta.get("filename") or "upload.yml")

    _lib, library_type, all_libraries = await _library_for_upload(request, settings, library)
    libraries = [_lib]
    taken = taken_titles(db, libraries).get(library, set())
    blocked = maintainerr_titles(request, libraries).get(library)
    action, _reason, landings = kometa_import.describe_file(text, library_type, taken, None, blocked)

    root = _kometa_root(settings)
    if root is None:
        raise HTTPException(409, "Studio doesn't know where Kometa is. Set STUDIO_KOMETA_ENTRY.")

    studio_kept = [landing.name for landing in landings if landing.result == kometa_import.STUDIO]

    if action == "replace":
        result = await _add_replace(db, writer, runner, root, library, library_type, all_libraries, landings, studio_kept)
        _delete_upload(settings.data_dir, token)
        return result

    if action == "keep":
        stems = {Path(ref.value).stem for ref in _lib.collection_files if ref.kind in ("file", "default")}
        result = await _add_keep(writer, runner, path, library, filename, studio_kept, stems)
        _delete_upload(settings.data_dir, token)
        return result

    raise HTTPException(409, f"This file can't be added (action {action!r})")


async def _add_replace(
    db, writer, runner, root: Path, library: str, library_type: str, all_libraries: list[str], landings, studio_kept: list[str]
) -> dict:
    imported = [(landing.name, landing.definition) for landing in landings if landing.result == kometa_import.IMPORTED and landing.definition]
    if not imported:
        raise HTTPException(409, "Nothing new to import from this file")
    created: list[int] = []
    copied: list[Path] = []
    try:
        with db:
            created = switch_over.insert_imported(db, writer.config_dir, library, imported, copied)
        written = await studio_files.write_library(
            writer,
            root,
            library,
            library_type,
            col.desired(db, library),
            all_libraries,
            f"Imported {len(imported)} collection{'s' if len(imported) != 1 else ''} from an upload",
            built=col.built_definitions(db, library),
        )
    except SaveRefused as refused:
        with db:
            col.delete_rows(db, created)
        for poster in copied:
            poster.unlink(missing_ok=True)
        raise HTTPException(refused.status, refused.detail()) from None
    except BaseException:
        with db:
            col.delete_rows(db, created)
        for poster in copied:
            poster.unlink(missing_ok=True)
        raise
    with db:
        studio_files.record(db, written)
    titles = [title for title, _ in imported]
    run_id = runner.enqueue(RunRequest(mode="collections", libraries=[library], collections=sorted(titles)), trigger="upload")
    with db:
        col.set_run(db, created, run_id)
    return {"action": "replace", "imported": titles, "kept_file": None, "run_id": run_id, "studio": studio_kept}


async def _add_keep(writer, runner, path: Path, library: str, filename: str, studio_kept: list[str], taken_stems: set[str]) -> dict:
    """Copy the file into Kometa's ``uploads/`` and list it, in one checked save (so a refusal leaves nothing)."""
    dest_folder = writer.config_dir / UPLOADS_DIR
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest = _unique_config_path(dest_folder, _safe_filename(filename), taken_stems)
    rel = writer.relative(dest)
    reference = writer.reference(dest)
    original = studio_files.read_config(writer)
    changed = with_library_file(original, library, "collection_files", reference)
    config_edit = studio_files.config_edit(writer, original, changed)
    if config_edit is None:
        raise HTTPException(409, "config.yml already lists this file")
    # The file is an Edit (not written first): otherwise Kometa's check would see it before the
    # config.yml entry and treat a BROKEN body as an error the files already had.
    try:
        await writer.save(
            [Edit(rel, path.read_text(encoding="utf-8"), None), config_edit],
            f"Added uploaded collection file {rel} for {library}",
        )
    except SaveRefused as refused:
        dest.unlink(missing_ok=True)  # save never wrote it; belt-and-braces if a partial landed
        raise HTTPException(refused.status, refused.detail()) from None
    run_id = runner.enqueue(
        RunRequest(mode="collections", libraries=[library], files=[dest.stem], ignore_schedules=True),  # Kometa matches the stem
        trigger="upload",
    )
    return {
        "action": "keep",
        "imported": [],
        "kept_file": rel,
        "run_id": run_id,
        "studio": studio_kept,
    }
