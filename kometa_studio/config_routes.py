"""/api/v1/config (Libraries, read-only) and /api/v1/history (what Kometa's runs changed)."""

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints

from . import backups
from .config_items import ItemProblem, read_item, schema_kind
from .config_sections import add_library, new_file_for_library, set_library_default, set_library_variables
from .config_write import ConfigWriter, Edit, SaveRefused
from .db import get_setting, set_setting
from .kometa_files import ConfigReader, KometaConfig, Library, Reference, mask_secrets
from .runs_routes import get_db
from .settings import Settings

FULL_CHECK = "kometa.full_check"

router = APIRouter(prefix="/api/v1", tags=["config"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def get_reader(request: Request) -> ConfigReader:
    settings: Settings = request.app.state.settings
    if settings.kometa_config is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG.")
    return ConfigReader(settings.kometa_config, settings.kometa_entry.parent if settings.kometa_entry else None)


Reader = Annotated[ConfigReader, Depends(get_reader)]


def read_config(reader: ConfigReader) -> KometaConfig:
    try:
        return reader.read()
    except FileNotFoundError:
        raise HTTPException(404, "Kometa's config.yml doesn't exist yet. Connect Plex in Settings → Plex first.") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def _counts(library: Library) -> dict:
    def files(refs: list[Reference]):
        return [summary for ref in refs for summary in ref.files]

    problems = [ref.error for refs in (library.collection_files, library.overlay_files, library.metadata_files) for ref in refs if ref.error]
    problems += [f.error for refs in (library.collection_files, library.overlay_files) for f in files(refs) if f.error]
    return {
        "name": library.name,
        # Kometa's library_name points a config entry at a Plex library with another title.
        "plex_name": str(library.settings.get("library_name") or library.name),
        "collection_files": len(library.collection_files),
        "overlay_files": len(library.overlay_files),
        "metadata_files": len(library.metadata_files),
        "defaults": sum(ref.kind == "default" for ref in library.collection_files + library.overlay_files),
        "collections": sum(len(f.collections) for f in files([r for r in library.collection_files if r.kind != "default"])),
        "overlays": sum(len(f.overlays) for f in files([r for r in library.overlay_files if r.kind != "default"])),
        "operations": len(library.operations),
        "problems": problems,
    }


@router.get("/config")
async def config_overview(reader: Reader) -> dict:
    config = read_config(reader)
    return {
        "path": str(config.path),
        "libraries": [_counts(library) for library in config.libraries],
        "playlist_files": [asdict(ref) for ref in config.playlist_files],
    }


@router.get("/config/libraries/{name}")
async def config_library(name: str, reader: Reader) -> dict:
    config = read_config(reader)
    library = next((lib for lib in config.libraries if lib.name == name), None)
    if library is None:
        raise HTTPException(404, f"There's no library called {name!r} in config.yml")
    return asdict(library) | {"counts": _counts(library)}


@router.get("/config/file")
async def config_file(path: str, request: Request, reader: Reader) -> dict:
    """A YAML file from Kometa's config or defaults folder, with secrets masked."""
    settings: Settings = request.app.state.settings
    allowed = [reader.config_path.parent.resolve(), reader.defaults.resolve()]
    hidden = settings.data_dir.resolve()  # Studio's own data, including unmasked backups
    for base in (reader.config_path.parent, reader.root):
        candidate = (base / path).resolve()
        if (
            candidate.suffix in (".yml", ".yaml")
            and any(candidate.is_relative_to(root) for root in allowed)
            and not candidate.is_relative_to(hidden)
            and candidate.is_file()
        ):
            try:
                text = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise HTTPException(422, f"Can't read {path}: {error}") from None
            masked, _ = mask_secrets(text)
            return {"path": reader.display_path(candidate), "text": masked}
    raise HTTPException(404, "Studio only shows .yml files from Kometa's config and defaults folders")


# --- History -------------------------------------------------------------------


@router.get("/history")
async def history(
    db: Db,
    library: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Kometa's `changes` and `delete` webhook events, newest first; page with ``before``."""
    where = ["event IN ('changes', 'delete')"]
    params: list = []
    if library:
        where.append("json_extract(payload, '$.library_name') = ?")
        params.append(library)
    if q:
        where.append(
            "(coalesce(json_extract(payload, '$.collection'), json_extract(payload, '$.playlist'), json_extract(payload, '$.message'), '') LIKE ? ESCAPE '\\')"
        )
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if before is not None:
        where.append("id < ?")
        params.append(before)
    rows = db.execute(
        f"SELECT id, run_id, event, received_at, payload FROM run_events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    events = [_history_event(row) for row in rows[:limit]]
    libraries = [
        row[0]
        for row in db.execute(
            "SELECT DISTINCT json_extract(payload, '$.library_name') AS name FROM run_events "
            "WHERE event IN ('changes', 'delete') AND name IS NOT NULL ORDER BY name"
        )
    ]
    return {"events": events, "libraries": libraries, "next": events[-1]["id"] if len(rows) > limit else None}


def _history_event(row: sqlite3.Row) -> dict:
    payload = json.loads(row["payload"])

    def items(key: str) -> list[dict]:
        # Radarr and Sonarr adds carry their TMDb or TVDb ID as plain `id`.
        result = []
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                result.append(
                    {
                        "title": item.get("title"),
                        "tmdb_id": item.get("tmdb_id", item.get("id") if key == "radarr_adds" else None),
                        "tvdb_id": item.get("tvdb_id", item.get("id") if key == "sonarr_adds" else None),
                    }
                )
        return result

    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "event": row["event"],
        "received_at": row["received_at"],
        "library": payload.get("library_name"),
        "collection": payload.get("collection"),
        "playlist": payload.get("playlist"),
        "message": payload.get("message"),
        "created": bool(payload.get("created")),
        "poster_url": payload.get("poster_url"),
        "additions": items("additions"),
        "removals": items("removals"),
        "radarr_adds": items("radarr_adds"),
        "sonarr_adds": items("sonarr_adds"),
    }


# --- Editing, backups and Kometa's full check ----------------------------------------


class EditIn(BaseModel):
    path: str
    text: str
    base_hash: str | None = None


class SaveIn(BaseModel):
    files: list[EditIn]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = "Edited in Studio"


def get_writer(request: Request) -> ConfigWriter:
    writer = request.app.state.writer
    if writer is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG.")
    return writer


Writer = Annotated[ConfigWriter, Depends(get_writer)]


async def _write_call(awaitable):
    try:
        return await awaitable
    except SaveRefused as refused:
        raise HTTPException(refused.status, refused.detail()) from None


def _edits(files: list[EditIn]) -> list[Edit]:
    return [Edit(f.path, f.text, f.base_hash) for f in files]


class LibraryIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


@router.post("/config/libraries")
async def add_config_library(body: LibraryIn, writer: Writer) -> dict:
    """Add a Plex library to config.yml, empty: its files come next (new collection files, Kometa's defaults)."""
    return await _write_call(add_library(writer, body.name))


@router.get("/config/defaults")
async def defaults_catalogue(reader: Reader) -> dict:
    """Every default the installed Kometa has, for the Defaults gallery."""
    return reader.catalogue()


class VariablesIn(BaseModel):
    template_variables: dict = {}


def _known_default(reader: ConfigReader, kind: str, name: str) -> None:
    catalogue = reader.catalogue()
    if kind not in ("collection", "overlay"):
        raise HTTPException(404, "Defaults are collection or overlay defaults")
    if name not in {entry["name"] for entry in catalogue["collections" if kind == "collection" else "overlays"]}:
        raise HTTPException(404, f"The installed Kometa has no {kind} default called {name}")


@router.put("/config/libraries/{library}/defaults/{kind}/{name}")
async def use_default(library: str, kind: str, name: str, body: VariablesIn, reader: Reader, writer: Writer) -> dict:
    """Turn a default on for a library, or change its template variables (all of them: missing ones are removed)."""
    _known_default(reader, kind, name)
    return await _write_call(set_library_default(writer, library, kind, name, body.template_variables))


@router.delete("/config/libraries/{library}/defaults/{kind}/{name}")
async def drop_default(library: str, kind: str, name: str, writer: Writer) -> dict:
    if kind not in ("collection", "overlay"):
        raise HTTPException(404, "Defaults are collection or overlay defaults")
    return await _write_call(set_library_default(writer, library, kind, name, None))


@router.put("/config/libraries/{library}/template-variables")
async def library_variables(library: str, body: VariablesIn, writer: Writer) -> dict:
    """The library's own template variables, which every file in it gets (sep_style, collection_mode, …)."""
    return await _write_call(set_library_variables(writer, library, body.template_variables))


@router.get("/config/edit")
async def edit_file(path: str, writer: Writer) -> dict:
    """A file to edit, with secrets as ••••(n) placeholders, the hash a save must match, and which schema it follows."""
    opened = edit_file_or_raise(writer, path)
    return opened | {"kind": schema_kind(writer.resolve(path).read_text(encoding="utf-8"), path)}


@router.post("/config/check")
async def check_files(body: SaveIn, writer: Writer) -> dict:
    return asdict(await _write_call(writer.check(_edits(body.files))))


@router.put("/config/files")
async def save_files(body: SaveIn, writer: Writer) -> dict:
    return await _write_call(writer.save(_edits(body.files), body.reason))


@router.get("/backups")
async def list_all_backups(writer: Writer) -> dict:
    return {"backups": backups.list_backups(writer.backup_root), "keep": backups.KEEP}


@router.get("/backups/{backup_id}/file")
async def backup_file(backup_id: str, path: str, writer: Writer) -> dict:
    """One file from a backup next to the current version, both masked, for comparing."""
    folder = backups.backup_folder(writer.backup_root, backup_id)
    if folder is None:
        raise HTTPException(404, "No such backup")
    try:
        current = writer.resolve(path)
    except SaveRefused as refused:
        raise HTTPException(refused.status, refused.detail()) from None
    saved = (folder / writer.relative(current)).resolve()
    if not saved.is_relative_to(folder.resolve()) or not saved.is_file():
        raise HTTPException(404, "That file isn't in this backup")
    return {
        "path": writer.relative(current),
        "backup": mask_secrets(saved.read_text(encoding="utf-8"))[0],
        "current": mask_secrets(current.read_text(encoding="utf-8"))[0] if current.is_file() else None,
    }


@router.post("/backups/{backup_id}/restore")
async def restore_backup(backup_id: str, writer: Writer) -> dict:
    return await _write_call(writer.restore(backup_id))


@router.post("/kometa/full-check")
async def full_check(db: Db, writer: Writer) -> dict:
    result = asdict(await _write_call(writer.full_check())) | {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    set_setting(db, FULL_CHECK, result)
    return result


@router.get("/kometa/full-check")
async def last_full_check(db: Db) -> dict:
    return {"last": get_setting(db, FULL_CHECK)}


# --- Designed forms: one item at a time, and Kometa's schemas -------------------------

SCHEMA_FILES = {
    "config": "config-schema.json",
    "collection": "collection-schema.json",
    "overlay": "overlay-schema.json",
    "metadata": "metadata-schema.json",
    "playlist": "playlist-schema.json",
    "template": "template-schema.json",
}


class ItemIn(BaseModel):
    path: str
    base_hash: str | None  # None: a new file, started with this item and added to ``library`` in config.yml
    section: str
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    value: dict | None  # None removes the item
    create: bool = False
    rename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    library: str | None = None


@router.get("/config/schemas/{kind}")
async def kometa_schema(kind: str, request: Request) -> FileResponse:
    """The JSON schema the installed Kometa validates this kind of file with (handoff v2 §7.2)."""
    settings: Settings = request.app.state.settings
    folder = settings.kometa_schemas or (settings.kometa_entry.parent / "json-schema" if settings.kometa_entry else None)
    if kind not in SCHEMA_FILES or folder is None or not (folder / SCHEMA_FILES[kind]).is_file():
        raise HTTPException(404, f"No Kometa schema for {kind!r}")
    return FileResponse(folder / SCHEMA_FILES[kind], media_type="application/json", headers={"Cache-Control": "no-cache"})


@router.get("/config/item")
async def config_item(path: str, section: str, name: str, writer: Writer) -> dict:
    opened = edit_file_or_raise(writer, path)
    file_path = writer.resolve(path)
    text = file_path.read_text(encoding="utf-8")
    try:
        value = read_item(text, section, name)
    except ItemProblem as problem:
        raise HTTPException(problem.status, problem.message) from None
    return {"path": opened["path"], "hash": opened["hash"], "section": section, "name": name, "value": value, "kind": schema_kind(text, path)}


@router.post("/config/item")
async def save_config_item(body: ItemIn, writer: Writer) -> dict:
    if body.base_hash is None:
        if not (body.create and body.library and body.value is not None):
            raise HTTPException(422, "A new file needs a new item and the library it's for")
        return await _write_call(new_file_for_library(writer, body.path, body.library, body.section, body.name, body.value))
    action = "Removed" if body.value is None else "Added" if body.create else "Edited"
    return await _write_call(
        writer.edit_item(
            body.path,
            body.base_hash,
            body.section,
            body.name,
            body.value,
            create=body.create,
            rename=body.rename,
            reason=f"{action} {body.name!r} in {body.path}",
        )
    )


def edit_file_or_raise(writer: ConfigWriter, path: str) -> dict:
    try:
        return writer.read(path)
    except SaveRefused as refused:
        raise HTTPException(refused.status, refused.detail()) from None
