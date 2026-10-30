"""/api/v1/config (Libraries, read-only) and /api/v1/history (what Kometa's runs changed)."""

import json
import sqlite3
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .kometa_files import ConfigReader, KometaConfig, Library, Reference, mask_secrets
from .runs_routes import get_db
from .settings import Settings

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
            return {"path": reader.display_path(candidate), "text": mask_secrets(text)}
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
