"""The collection builder (phase 2): smart collections from a library's own data.

A builder collection is a row in ``collections`` (category ``built``, origin ``built``) with the user's definition as
JSON. Studio writes it into ``studio/<library>/built.yml`` as a Kometa ``smart_filter`` collection labelled ``Studio``,
checks the save with Kometa, and runs just that collection. The preview asks Plex directly with the query Kometa's smart
collection would use (``smart_filters.plex_query``), so it shows before anything is saved.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from . import collections as col
from . import smart_filters, studio_files
from .config_write import SaveRefused
from .kometa_command import RunRequest
from .plex_library import PlexNotFound, PlexServer, PlexUnavailable
from .plex_routes import kometa_plex
from .ready_made_routes import (
    STUDIO_LABEL,
    AppRunner,
    AppSettings,
    Db,
    Writer,
    _config_library,
    _entry_state,
    _kometa_root,
    _library_types,
    _plex_title,
    _run_status,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["builder"])

PREVIEW_SIZE = 30
# The smart_filter sort Kometa's default templates use (defaults/templates.yml, smart_filter: sort_by: release.desc).
TEMPLATE_SORT = "release.desc"


class Visible(BaseModel):
    library: bool = True
    home: bool = False
    shared: bool = False


class RuleIn(BaseModel):
    field: str
    modifier: str = ""
    value: bool | int | float | str | list[str]


class FiltersIn(BaseModel):
    match: Literal["all", "any"] = "all"
    rules: list[RuleIn] = Field(default_factory=list)


class CollectionIn(BaseModel):
    library: str
    title: str = Field(min_length=1, max_length=200)
    filters: FiltersIn
    sort_by: str | None = None
    limit: int | None = Field(default=None, ge=1)
    visible: Visible = Field(default_factory=Visible)
    minimum_items: int = Field(default=1, ge=1)
    summary: str | None = None
    sort_title: str | None = None


class PreviewIn(BaseModel):
    library: str
    filters: FiltersIn
    sort_by: str | None = None


class Context:
    """A config.yml library and its Plex section."""

    def __init__(self, library, all_libraries: list[str], server: PlexServer, section: str, library_type: str):
        self.library = library
        self.all_libraries = all_libraries
        self.server = server
        self.section = section
        self.library_type = library_type


async def _context(request: Request, settings, name: str) -> Context:
    library, all_libraries = _config_library(settings, name)
    server = kometa_plex(settings, request.app.state.http)
    try:
        types = await _library_types.types(server)
        section = await _library_types.key_for(server, _plex_title(library))
    except PlexUnavailable as error:
        raise HTTPException(503, f"Plex can't be reached: {error}") from None
    library_type = types.get(_plex_title(library).casefold())
    if section is None or library_type is None:
        raise HTTPException(404, f"Plex has no library called {_plex_title(library)!r}")
    if library_type not in ("movie", "show"):
        raise HTTPException(422, "The builder makes collections in movie and show libraries")
    return Context(library, all_libraries, server, section, library_type)


def _definition(body: CollectionIn) -> dict:
    return {
        "filters": body.filters.model_dump(),
        "sort_by": body.sort_by,
        "limit": body.limit,
        "visible": body.visible.model_dump(),
        "minimum_items": body.minimum_items,
        "summary": (body.summary or "").strip() or None,
        "sort_title": (body.sort_title or "").strip() or None,
    }


def _built_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    definition = json.loads(row["definition"] or "{}")
    run_status = _run_status(db, row["last_run_id"])
    return {
        "id": int(row["id"]),
        "library": row["library"],
        "title": row["title"],
        "filters": definition.get("filters") or {"match": "all", "rules": []},
        "sort_by": definition.get("sort_by"),
        "limit": definition.get("limit"),
        "visible": definition.get("visible") or {"library": True, "home": False, "shared": False},
        "minimum_items": definition.get("minimum_items") or 1,
        "summary": definition.get("summary"),
        "sort_title": definition.get("sort_title"),
        "state": _entry_state(row, run_status),
        "plex_items": int(row["plex_items"]) if row["plex_items"] is not None else None,
        "thumb": row["plex_thumb"],
        "last_built_at": row["last_built_at"],
        "last_error": row["last_error"],
        "run_id": row["last_run_id"],
    }


def _problems(context: Context, filters: FiltersIn, sort_by: str | None) -> list[str]:
    return smart_filters.validate(context.library_type, filters.model_dump(), sort_by)


async def _title_taken(db: sqlite3.Connection, request: Request, context: Context, title: str, own_id: int | None) -> str | None:
    """Why ``title`` can't be used in this library, or None. Kometa takes over any collection with the same title."""
    key = title.casefold()
    for row in col.rows(db, context.library.name):
        if row["title"].casefold() == key and int(row["id"]) != own_id:
            return f"Studio already has a collection called {row['title']} in {context.library.name}"
    service = getattr(request.app.state, "maintainerr", None)
    if service is not None and service.connected():
        owned = service.snapshot.owned_by_title().get(_plex_title(context.library).casefold(), [])
        if key in {t.casefold() for t in owned}:
            return f"Maintainerr has a collection called {title}"
    try:
        studio = {c.title.casefold() for c in await context.server.labelled_collections(context.section, STUDIO_LABEL)}
        everyone = {c.title.casefold() for c in await context.server.collections(context.section)}
    except PlexUnavailable as error:
        return f"Plex can't be checked ({error}), so Studio can't tell whether the name is free"
    if key in everyone and key not in studio:
        return f"A collection called {title} that Studio didn't make is already in Plex"
    return None


async def _delete_from_plex(context: Context, title: str) -> tuple[bool, str | None]:
    """Delete Studio's own collection called ``title``; (gone, why not)."""
    try:
        labelled = await context.server.labelled_collections(context.section, STUDIO_LABEL)
        match = next((c for c in labelled if c.title.casefold() == title.casefold()), None)
        if match is None:
            everyone = await context.server.collections(context.section)
            if any(c.title.casefold() == title.casefold() for c in everyone):
                return False, "the collection in Plex has no Studio label, so Studio didn't make it"
            return True, None
        if STUDIO_LABEL not in await context.server.collection_labels(match.rating_key):
            return False, "the collection in Plex has no Studio label, so Studio didn't make it"
        await context.server.delete_collection(match.rating_key)
        return True, None
    except (PlexUnavailable, PlexNotFound) as error:
        return False, f"Plex can't be reached ({error})"


async def _save_and_run(db: sqlite3.Connection, settings, writer, runner, context: Context, row_id: int, reason: str) -> int:
    root = _kometa_root(settings)
    if root is None:
        raise HTTPException(409, "Studio doesn't know where Kometa is. Set STUDIO_KOMETA_ENTRY.")
    written = await studio_files.write_from_db(writer, root, db, context.library.name, context.library_type, context.all_libraries, reason)
    with db:
        studio_files.record(db, written)
    row = col.built_row(db, row_id)
    run_id = runner.enqueue(RunRequest(mode="collections", libraries=[context.library.name], collections=[row["kometa_name"]]), trigger="builder")
    with db:
        col.set_run(db, [row_id], run_id)
    return run_id


# --- Fields, values and the preview ------------------------------------------------------------


@router.get("/builder/fields")
async def builder_fields(library: str, request: Request, settings: AppSettings) -> dict:
    context = await _context(request, settings, library)
    return {
        "library": library,
        "library_type": context.library_type,
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "kind": field.kind,
                "modifiers": [{"key": key, "label": label} for key, label in field.modifiers],
                "group": field.group,
                "listable": field.plex_tag is not None,
            }
            for field in smart_filters.fields(context.library_type)
        ],
        "sorts": [{"key": key, "label": label} for key, label in smart_filters.sorts(context.library_type)],
    }


@router.get("/builder/values")
async def builder_values(library: str, field: str, request: Request, settings: AppSettings) -> dict:
    context = await _context(request, settings, library)
    found = next((f for f in smart_filters.fields(context.library_type) if f.key == field), None)
    if found is None or found.plex_tag is None:
        raise HTTPException(422, f"Studio can't list the values of {field!r}")
    try:
        values = await context.server.tag_values(context.section, found.plex_tag, context.library_type, episode=found.episode)
    except PlexUnavailable as error:
        raise HTTPException(503, f"Plex can't be reached: {error}") from None
    seen: set[str] = set()
    out = []
    for title, _key in values:
        if title and title not in seen:  # Kometa's smart_filter takes the title
            seen.add(title)
            out.append({"key": title, "title": title})
    return {"values": out}


@router.post("/builder/preview")
async def builder_preview(body: PreviewIn, request: Request, settings: AppSettings) -> dict:
    context = await _context(request, settings, body.library)
    problems = _problems(context, body.filters, body.sort_by)
    if problems:
        return {"count": 0, "items": [], "problems": problems}
    try:
        params = await smart_filters.plex_query(context.server, context.section, context.library_type, body.filters.model_dump(), body.sort_by)
        items, total = await context.server.query(context.section, params, PREVIEW_SIZE)
    except smart_filters.SmartFilterError as error:
        return {"count": 0, "items": [], "problems": [str(error)]}
    except PlexUnavailable as error:
        raise HTTPException(503, f"Plex can't be reached: {error}") from None
    return {
        "count": total,
        "items": [{"rating_key": i.rating_key, "title": i.title, "year": i.year, "thumb": i.thumb} for i in items],
        "problems": [],
    }


# --- Collections ---------------------------------------------------------------------------------


@router.get("/collections")
async def list_collections(library: str, db: Db) -> dict:
    return {"collections": [_built_json(db, row) for row in col.built_rows(db, library)]}


@router.get("/collections/{row_id}")
async def get_collection(row_id: int, db: Db) -> dict:
    row = col.built_row(db, row_id)
    if row is None:
        raise HTTPException(404, "No such collection")
    return _built_json(db, row)


@router.post("/collections", status_code=201)
async def create_collection(body: CollectionIn, request: Request, db: Db, settings: AppSettings, writer: Writer, runner: AppRunner) -> dict:
    context = await _context(request, settings, body.library)
    title = body.title.strip()
    problems = _problems(context, body.filters, body.sort_by)
    if problems:
        raise HTTPException(422, {"message": "The collection can't be made like this", "problems": problems})
    taken = await _title_taken(db, request, context, title, None)
    if taken:
        raise HTTPException(409, {"message": taken})
    with db:
        row_id = col.insert_built(db, body.library, secrets.token_hex(6), title, _definition(body))
    try:
        await _save_and_run(db, settings, writer, runner, context, row_id, f"Built the collection {title!r} in {body.library}")
    except SaveRefused as refused:
        with db:
            col.delete_rows(db, [row_id])
        raise HTTPException(refused.status, refused.detail()) from None
    except Exception:
        with db:
            col.delete_rows(db, [row_id])
        raise
    return _built_json(db, col.built_row(db, row_id))


@router.put("/collections/{row_id}")
async def update_collection(row_id: int, body: CollectionIn, request: Request, db: Db, settings: AppSettings, writer: Writer, runner: AppRunner) -> dict:
    row = col.built_row(db, row_id)
    if row is None:
        raise HTTPException(404, "No such collection")
    if body.library != row["library"]:
        raise HTTPException(422, {"message": "A collection can't move to another library", "problems": []})
    context = await _context(request, settings, body.library)
    title = body.title.strip()
    problems = _problems(context, body.filters, body.sort_by)
    if problems:
        raise HTTPException(422, {"message": "The collection can't be made like this", "problems": problems})
    taken = await _title_taken(db, request, context, title, row_id)
    if taken:
        raise HTTPException(409, {"message": taken})
    old_title, old_definition = row["title"], row["definition"]
    with db:
        col.update_built(db, row_id, title, _definition(body))
    try:
        await _save_and_run(db, settings, writer, runner, context, row_id, f"Changed the collection {title!r} in {body.library}")
    except SaveRefused as refused:
        with db:
            col.update_built(db, row_id, old_title, json.loads(old_definition or "{}"))
        raise HTTPException(refused.status, refused.detail()) from None
    if old_title.casefold() != title.casefold():
        # Kometa finds collections by title, so the old one would stay in Plex under its old name.
        gone, why = await _delete_from_plex(context, old_title)
        if not gone:
            log.warning("Renamed %r to %r, but the old collection stays in Plex: %s", old_title, title, why)
    return _built_json(db, col.built_row(db, row_id))


@router.delete("/collections/{row_id}")
async def delete_collection(row_id: int, request: Request, db: Db, settings: AppSettings, writer: Writer) -> dict:
    row = col.built_row(db, row_id)
    if row is None:
        raise HTTPException(404, "No such collection")
    context = await _context(request, settings, row["library"])
    gone, why = await _delete_from_plex(context, row["title"])
    if not gone and why and why.startswith("Plex can't"):
        raise HTTPException(503, {"message": f"Not deleted: {why}. Try again when Plex is back."})
    snapshot = dict(row)
    with db:
        col.delete_rows(db, [row_id])
    root = _kometa_root(settings)
    try:
        if root is not None:
            written = await studio_files.write_from_db(
                writer, root, db, context.library.name, context.library_type, context.all_libraries, f"Deleted the collection {row['title']!r}"
            )
            with db:
                studio_files.record(db, written)
    except SaveRefused as refused:
        with db:
            db.execute(
                f"INSERT INTO collections ({', '.join(snapshot)}) VALUES ({', '.join('?' * len(snapshot))})",
                list(snapshot.values()),
            )
        raise HTTPException(refused.status, refused.detail()) from None
    return {"removed": gone, "reason": why}


# --- Ready-made templates open in the builder ----------------------------------------------------


@router.get("/ready-made/libraries/{library}/categories/{category}/customise")
async def customise_ready_made(library: str, category: str, block: str, key: str, request: Request, db: Db, settings: AppSettings) -> dict:
    """A builder draft (not saved) for one ready-made collection that's a Plex filter, such as Action Movies."""
    context = await _context(request, settings, library)
    root = _kometa_root(settings)
    source = studio_files.default_file(root, category, context.library_type) if root else None
    if source is None or not block:
        raise HTTPException(422, {"message": "This ready-made comes from a list, which the builder can't use yet"})
    data = YAML(typ="safe", pure=True).load(source.read_text(encoding="utf-8")) or {}
    attrs = (data.get("dynamic_collections") or {}).get(block)
    if not isinstance(attrs, dict):
        raise HTTPException(422, {"message": f"Kometa's {category} default has no {block!r}"})
    # The default's own smart_filter search term (template_variables.search_term), else its dynamic type.
    term = (attrs.get("template_variables") or {}).get("search_term")
    term = term.get("default") if isinstance(term, dict) else term
    field_key = str(term or attrs.get("type") or "")
    field = next((f for f in smart_filters.fields(context.library_type) if f.key == field_key), None)
    if field is None:
        raise HTTPException(422, {"message": "This ready-made comes from a list, which the builder can't use yet"})
    addons = {str(k): [str(v) for v in (vs if isinstance(vs, list) else [vs])] for k, vs in (attrs.get("addons") or {}).items()}
    extra = [v for v in addons.get(key, []) if v != key]
    if extra and field.plex_tag:
        # Kometa uses only the add-ons the library has (meta.py: `a in all_keys`).
        try:
            have = {name for pair in await context.server.tag_values(context.section, field.plex_tag, context.library_type, episode=field.episode) for name in pair}
        except PlexUnavailable as error:
            raise HTTPException(503, f"Plex can't be reached: {error}") from None
        extra = [v for v in extra if v in have]
    values = [key] + extra
    cached = col.counts(db, library).get(category) or {}
    entry = next((e for e in (cached.get("data") or {}).get("entries", []) if str(e.get("block")) == block and str(e.get("key")) == key), None)
    title = str(entry.get("title")) if entry else key
    value: object = values if field.kind in ("tag", "string") else (int(key) if key.isdigit() else key)
    return {
        "library": library,
        "title": title,
        # Kometa's smart_filter template puts the value in an `any:` block, so a key with addons (G with TV-G)
        # matches either; in an `all:` block Kometa would AND them.
        "filters": {"match": "any", "rules": [{"field": field.key, "modifier": "", "value": value}]},
        "sort_by": TEMPLATE_SORT,
        "limit": None,
        "visible": {"library": True, "home": False, "shared": False},
        "minimum_items": 1,
        "summary": None,
        "sort_title": None,
    }
