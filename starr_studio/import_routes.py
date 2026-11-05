"""Moving over from Kometa: ``GET /api/v1/import``, the read-only report of how each collection would land.

Nothing here writes anything. The setup wizard shows it; Switch over acts on it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import collections as col
from . import kometa_import
from .plex_library import PlexUnavailable
from .plex_routes import kometa_plex
from .ready_made_routes import AppSettings, Db, _kometa_root, _library_types, _plex_title, _reader

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
