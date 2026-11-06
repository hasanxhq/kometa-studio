"""The collection builder: collections from a library's own data (phase 2) or from a list (phase 3).

A builder collection is a row in ``collections`` (category ``built``, origin ``built``) with the user's definition as
JSON. Its ``sources`` (rows from before hold one ``source``; ``list_sources.sources_of`` reads either) are one
``{"kind": "filters"}`` (a Kometa ``smart_filter``, which Kometa takes only on its own), or up to twenty of: ``{"kind":
"list", "builder", "value", "label"}`` (one of Kometa's list builders, see ``list_sources``), ``{"kind": "titles",
"builder", "ids", "label"}`` (single titles by TMDb, TVDb or IMDb id) and one ``{"kind": "search", "filters"}`` (a Kometa
``plex_search``). Kometa adds up what a collection's builders find. Studio writes it into ``studio/<library>/built.yml``
labelled ``Studio``, checks the save with Kometa, and runs just that collection. The filter preview asks Plex directly
with the query Kometa's smart collection would use (``smart_filters.plex_query``); the list preview reads the lists and
titles and splits them into what the library has and what it's missing. Both show before anything is saved.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import secrets
import sqlite3
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from . import collections as col
from . import collection_requests, list_sources, ready_made, ready_made_lists, ready_made_posters, smart_filters, studio_files
from .config_sections import read_section
from .config_write import SaveRefused
from .default_covers import DEFAULT_IMAGES
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
LIST_PREVIEW_SIZE = 60  # posters per half of a list preview
# The smart_filter sort Kometa's default templates use (defaults/templates.yml, smart_filter: sort_by: release.desc).
TEMPLATE_SORT = "release.desc"

POSTER_MAX_BYTES = 10 * 1024 * 1024
POSTER_GRACE = 3600  # seconds an unreferenced upload is kept, for editors still open
POSTER_FOLDER = "studio/posters"
POSTER_NAME = re.compile(r"^[0-9a-f]{16}\.(jpg|jpeg|png|webp)$")
# Magic bytes, not the filename: a renamed text file must not pass.
_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
)


class Visible(BaseModel):
    """Where the collection shows in Plex. None leaves Plex's setting alone (collections imported from a file that didn't set it)."""

    library: bool | None = True
    home: bool | None = False
    shared: bool | None = False


class RuleIn(BaseModel):
    field: str
    modifier: str = ""
    value: bool | int | float | str | list[str]


class FiltersIn(BaseModel):
    match: Literal["all", "any"] = "all"
    rules: list[RuleIn] = Field(default_factory=list)


class PosterIn(BaseModel):
    """null in JSON means Plex's own mosaic; a file or url is what Kometa applies on the next run."""

    kind: Literal["file", "url"]
    path: str | None = None
    url: str | None = None


class SourceIn(BaseModel):
    """Where titles come from: Plex filters (a smart collection, alone), one of Kometa's list builders, single titles by
    id, or a Plex search (Kometa's ``plex_search``, which can sit beside lists)."""

    kind: Literal["filters", "list", "titles", "search"] = "filters"
    builder: str | None = None
    value: str | int | None = None
    ids: list[str | int] | str | None = None  # titles: TMDb/TVDb numbers or IMDb tt ids
    filters: FiltersIn | None = None  # search: its rules
    label: str | None = None


class CollectionIn(BaseModel):
    library: str
    title: str = Field(min_length=1, max_length=200)
    source: SourceIn = Field(default_factory=SourceIn)
    sources: list[SourceIn] | None = None  # when given, wins over source
    filters: FiltersIn = Field(default_factory=FiltersIn)
    sort_by: str | None = None
    limit: int | None = Field(default=None, ge=1)
    visible: Visible = Field(default_factory=Visible)
    minimum_items: int = Field(default=1, ge=1)
    summary: str | None = None
    sort_title: str | None = None
    poster: PosterIn | None = None
    download_missing: bool = False  # request the titles a list collection lacks (Settings → Requests must be on)
    request_cap: int | None = Field(default=None, ge=1)  # most per day for this collection; None = the setting's
    request_profile: str | None = Field(default=None, max_length=200)  # Radarr/Sonarr quality profile; None = the setting's
    confirm_requests: bool = False  # the user saw how many titles this requests now and said yes


class DownloadMissingIn(BaseModel):
    download_missing: bool


class PreviewIn(BaseModel):
    library: str
    filters: FiltersIn
    sort_by: str | None = None


class ListSourceIn(BaseModel):
    builder: str
    value: str | int


class ListPreviewIn(BaseModel):
    library: str
    source: ListSourceIn | None = None
    sources: list[SourceIn] | None = None  # when given, the preview is their union


class LinkIn(BaseModel):
    library: str
    url: str = Field(min_length=1, max_length=2000)


LIST_ORDERS = ("custom", "release", "alpha")  # Kometa's collection_order for a list collection


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


def _image_type(data: bytes) -> tuple[str, str] | None:
    """(extension, media type) from the file's bytes, or None if it isn't a JPEG, PNG or WebP."""
    for magic, ext, media in _IMAGE_MAGIC:
        if data.startswith(magic):
            return ext, media
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _config_dir(settings) -> Path:
    if settings.kometa_config is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config is. Set STUDIO_KOMETA_CONFIG.")
    return settings.kometa_config.parent


def _poster_path(config_dir: Path, name: str) -> Path | None:
    """Absolute path of a stored poster, or None if the name isn't allowed."""
    if not POSTER_NAME.fullmatch(name):
        return None
    path = (config_dir / POSTER_FOLDER / name).resolve()
    folder = (config_dir / POSTER_FOLDER).resolve()
    try:
        path.relative_to(folder)
    except ValueError:
        return None
    return path


def _poster_dict(poster: PosterIn | None) -> dict | None:
    if poster is None:
        return None
    if poster.kind == "file":
        return {"kind": "file", "path": poster.path}
    return {"kind": "url", "url": poster.url}


def _check_poster(settings, poster: PosterIn | None) -> None:
    """Raise 422 if the poster reference isn't usable."""
    if poster is None:
        return
    if poster.kind == "url":
        url = (poster.url or "").strip()
        if not url or urlparse(url).scheme not in ("http", "https"):
            raise HTTPException(422, "A poster link must be an http(s) URL")
        return
    path = (poster.path or "").strip()
    if not path.startswith(f"{POSTER_FOLDER}/") or path != path.replace("\\", "/"):
        raise HTTPException(422, "An uploaded poster must live under studio/posters/")
    name = path.removeprefix(f"{POSTER_FOLDER}/")
    stored = _poster_path(_config_dir(settings), name)
    if stored is None or not stored.is_file():
        raise HTTPException(422, "That poster file isn't on the server. Upload it again.")


def _cleanup_posters(config_dir: Path, db: sqlite3.Connection) -> None:
    """Remove poster files under studio/posters/ that no builder collection references any more."""
    folder = config_dir / POSTER_FOLDER
    if not folder.is_dir():
        return
    referenced: set[str] = set()
    for row in col.built_rows(db):
        poster = (json.loads(row["definition"] or "{}") or {}).get("poster")
        if isinstance(poster, dict) and poster.get("kind") == "file":
            path = poster.get("path")
            if isinstance(path, str) and path.startswith(f"{POSTER_FOLDER}/"):
                referenced.add(Path(path).name)
    young = time.time() - POSTER_GRACE
    for path in folder.iterdir():
        # An upload not saved yet belongs to an editor still open (maybe another tab): keep it for a while.
        if path.is_file() and path.name not in referenced and not path.name.endswith(".part") and path.stat().st_mtime < young:
            try:
                path.unlink()
            except OSError:
                log.warning("Couldn't remove unused poster %s", path)


def _fill_image_path(template: str, key: str, tvs: dict) -> str | None:
    """Substitute the placeholders Kometa's default image paths use. None if any stay unresolved."""
    style = tvs.get("style")
    if isinstance(style, dict):
        style = style.get("default")
    style = str(style) if style else "white"
    encoded = quote(key, safe="")
    out = template
    for placeholder, value in (
        ("<<original_key_name_encoded>>", encoded),
        ("<<key_name_encoded>>", encoded),
        ("<<key_encoded>>", encoded),
        ("<<key_name>>", key),
        ("<<key>>", key),
        ("<<style>>", style),
    ):
        out = out.replace(placeholder, value)
    return None if "<<" in out else out


def _kometa_poster(category: str, key: str, attrs: dict) -> dict | None:
    """Kometa's poster URL for this ready-made key, or None when the path isn't reliable."""
    tvs = attrs.get("template_variables") if isinstance(attrs.get("template_variables"), dict) else {}
    if str(attrs.get("type", "")).lower() in ready_made_posters.PEOPLE_TYPES:
        url = ready_made_posters.people_url(key, tvs)  # the tmdb_person template's People-Images poster
        return {"kind": "url", "url": url} if url else None
    image = tvs.get("image")
    path: str | None = None
    if isinstance(image, dict):
        raw = image.get(key, image.get("default"))
        if isinstance(raw, str):
            path = _fill_image_path(raw, key, tvs)
    elif isinstance(image, str):
        path = _fill_image_path(image, key, tvs)
    # Genre's default is genre/<<original_key_name_encoded>> (default_covers / templates.yml); the test fixture
    # omits template_variables.image, so fall back only for that unambiguous case.
    if path is None and category == "genre":
        path = f"genre/{quote(key, safe='')}"
    if not path:
        return None
    return {"kind": "url", "url": f"{DEFAULT_IMAGES}/{path}.jpg"}


def _sources(body: CollectionIn) -> list[SourceIn]:
    return body.sources if body.sources is not None else [body.source]


def _source_dict(source: SourceIn) -> dict:
    label = (source.label or "").strip() or None
    if source.kind == "filters":
        return {"kind": "filters"}
    if source.kind == "titles":
        ids = source.ids if isinstance(source.ids, list) else [source.ids] if source.ids else []
        return {"kind": "titles", "builder": source.builder, "ids": [str(i) for i in ids], "label": label}
    if source.kind == "search":
        return {"kind": "search", "filters": (source.filters or FiltersIn()).model_dump()}
    return {"kind": "list", "builder": source.builder, "value": str(source.value), "label": label}


def _definition(body: CollectionIn) -> dict:
    sources = [_source_dict(source) for source in _sources(body)]
    return {
        "source": sources[0],  # what Studio before several sources reads
        "sources": sources,
        "filters": body.filters.model_dump(),
        "sort_by": body.sort_by,
        "limit": body.limit,
        "visible": body.visible.model_dump(),
        "minimum_items": body.minimum_items,
        "summary": (body.summary or "").strip() or None,
        "sort_title": (body.sort_title or "").strip() or None,
        "poster": _poster_dict(body.poster),
    }


def _requests_service(request: Request):
    service = getattr(request.app.state, "requests", None)
    if service is None:
        raise HTTPException(503, "Studio's requests aren't running")
    return service


async def _missing_now(request: Request, settings, context: Context, body: CollectionIn, db: sqlite3.Connection) -> list:
    """The titles a list collection with Download missing would request right away: what its preview misses, never asked for before."""
    sources = [_source_dict(source) for source in _sources(body)]
    if not body.download_missing or not list_sources.has_missing(sources):
        return []
    # Sources Studio can't read now are left out: Kometa's missing report covers them after the build.
    items, _skipped, _problems, _read = await _read_sources(_lists(request, settings), sources, context.library_type)
    if not items:
        return []
    try:
        library = await context.server.all_items(context.section, context.library_type)
    except PlexUnavailable:
        return []
    _have, missing = list_sources.split(items, library)
    asked = {r[0] for r in db.execute("SELECT item FROM requests")}
    out, seen = [], set()
    for m in missing:
        key = list_sources.missing_key(m, context.library_type)
        if key.startswith(("tmdb-", "tvdb:")) and key not in asked and key not in seen:
            seen.add(key)
            out.append(collection_requests.Item(item=key, title=m.title, year=m.year))
    return out


def _check_requests(request: Request, db: sqlite3.Connection, body: CollectionIn, missing: list, already_on: bool = False) -> None:
    """Refuse turning Download missing on while requests are off, and ask first when it would request more than the setting allows."""
    if not body.download_missing:
        return
    settings = collection_requests.load_settings(db)
    if not settings.enabled:
        if already_on:
            return  # requests were turned off since: the collection keeps its choice, and nothing is requested
        raise HTTPException(422, {"message": "Turn on requests in Settings → Requests first", "problems": ["Requests are off"]})
    _requests_service(request)
    if len(missing) > settings.confirm_over and not body.confirm_requests:
        raise HTTPException(
            409,
            {"message": f"This would request {len(missing)} titles now", "needs_confirm": True, "count": len(missing)},
        )


async def _request_now(request: Request, db: sqlite3.Connection, row_id: int, missing: list) -> None:
    if not missing:
        return
    row = col.built_row(db, row_id)
    try:
        outcome = await collection_requests.request_items(_requests_service(request), db, row, missing)
        log.info("Requested %d of %d missing titles for %r", outcome.requested, len(missing), row["title"])
    except collection_requests.RequestsDisabled:
        pass


def _built_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    definition = json.loads(row["definition"] or "{}")
    sources = list_sources.sources_of(definition)
    run_status = _run_status(db, row["last_run_id"])
    return {
        "id": int(row["id"]),
        "library": row["library"],
        "title": row["title"],
        "source": sources[0],  # the first, for the builder before several sources
        "sources": sources,
        "filters": definition.get("filters") or {"match": "all", "rules": []},
        "sort_by": definition.get("sort_by"),
        "limit": definition.get("limit"),
        "visible": definition.get("visible") or {"library": True, "home": False, "shared": False},
        "minimum_items": definition.get("minimum_items") or 1,
        "summary": definition.get("summary"),
        "sort_title": definition.get("sort_title"),
        "poster": definition.get("poster"),
        "state": _entry_state(row, run_status),
        "plex_items": int(row["plex_items"]) if row["plex_items"] is not None else None,
        "thumb": row["plex_thumb"],
        "last_built_at": row["last_built_at"],
        "last_error": row["last_error"],
        "run_id": row["last_run_id"],
        "download_missing": bool(row["download_missing"]),
        "request_cap": row["request_cap"],
        "request_profile": row["request_profile"],
        "requests": collection_requests.summary(db, row),
    }


def _problems(context: Context, filters: FiltersIn, sort_by: str | None) -> list[str]:
    return smart_filters.validate(context.library_type, filters.model_dump(), sort_by)


def _connected(settings) -> set[str]:
    return {name for name in ("tmdb", "mdblist") if (read_section(settings.kometa_config, name) or {}).get("apikey")}


def _body_problems(context: Context, body: CollectionIn, settings) -> list[str]:
    """What's wrong with a collection as given. Sources are normalised in place (a pasted link becomes Kometa's value, ids are tidied)."""
    sources = _sources(body)
    if not sources:
        return ["Give the collection at least one source"]
    if any(source.kind == "filters" for source in sources):
        if len(sources) > 1:
            return ["A smart filter can't be combined with other sources (Kometa takes a smart_filter only on its own). Use a Plex search beside lists instead"]
        problems = _problems(context, body.filters, body.sort_by)
        if body.download_missing:
            problems.append("A smart collection only holds what you have, so it has no missing titles to download")
        return problems
    problems = []
    if len(sources) > list_sources.MAX_SOURCES:
        problems.append(f"A collection takes at most {list_sources.MAX_SOURCES} sources")
    counted: set[str] = set()
    searches = 0
    for source in sources:
        try:
            if source.kind == "list":
                kind = list_sources.kind_for(source.builder or "", context.library_type)
                source.value, label = list_sources.normalise(kind.builder, str(source.value or ""), context.library_type)
                source.label = (source.label or "").strip() or label
                if kind.needs and kind.needs not in _connected(settings):
                    problems.append(f"A {kind.label} needs {list_sources.SERVICE_NAMES[kind.needs]} connected in Settings → Connect")
                if kind.input == "count":
                    if kind.builder in counted:
                        problems.append(f"{kind.label} can be a source only once")
                    counted.add(kind.builder)
            elif source.kind == "titles":
                source.ids = list_sources.normalise_ids(source.builder or "", source.ids, context.library_type)
            elif source.kind == "search":
                searches += 1
                if source.filters is None:
                    problems.append("A Plex search needs rules")
                else:
                    problems += smart_filters.validate_search(context.library_type, source.filters.model_dump())
        except list_sources.SourceError as error:
            problems.append(str(error))
    if searches > 1:
        problems.append("A collection takes one Plex search; put all its rules in that one (match any adds them up)")
    if body.download_missing and not list_sources.has_missing([{"kind": source.kind} for source in sources]):
        problems.append("A Plex search only holds what you have, so it has no missing titles to download")
    if body.filters.rules:
        problems.append("A collection from a list can't have filter rules yet")
    if body.sort_by not in (None, *LIST_ORDERS):
        problems.append("A list collection's order is list order, release date or title")
    elif body.sort_by == "custom" and (why := list_sources.custom_order_problem([_source_dict(source) for source in sources])):
        problems.append(why)
    if body.limit is not None:
        problems.append("A list collection takes the whole list; set how many titles in the source instead")
    return problems


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


# --- List sources --------------------------------------------------------------------------------


def _lists(request: Request, settings) -> list_sources.Lists:
    cache = getattr(request.app.state, "list_cache", None)
    if cache is None:
        cache = request.app.state.list_cache = {}
    keys = {name: (read_section(settings.kometa_config, name) or {}).get("apikey") for name in ("tmdb", "mdblist")}
    return list_sources.Lists(request.app.state.http, keys["tmdb"], keys["mdblist"], cache)


@router.get("/builder/sources")
async def builder_sources(library: str, request: Request, settings: AppSettings) -> dict:
    context = await _context(request, settings, library)
    return {"sources": list_sources.catalogue(context.library_type, _connected(settings))}


@router.post("/builder/sources/link")
async def builder_source_from_link(body: LinkIn, request: Request, settings: AppSettings) -> dict:
    context = await _context(request, settings, body.library)
    try:
        builder, value, label = list_sources.from_link(body.url, context.library_type)
    except list_sources.SourceError as error:
        raise HTTPException(422, str(error)) from None
    if label is None:
        try:
            label = await _lists(request, settings).label(builder, value)
        except list_sources.SourceError:
            label = None  # the name is a nicety; the link is still good
    return {"builder": builder, "value": value, "label": label}


@router.get("/builder/sources/search")
async def builder_source_search(library: str, builder: str, q: str, request: Request, settings: AppSettings) -> dict:
    context = await _context(request, settings, library)
    try:
        kind = list_sources.kind_for(builder, context.library_type)
    except list_sources.SourceError as error:
        raise HTTPException(422, str(error)) from None
    if kind.input != "search":
        raise HTTPException(422, f"Studio can't search for a {kind.label}")
    if len(q.strip()) < 2:
        return {"results": []}
    try:
        return {"results": await _lists(request, settings).search_collections(q.strip())}
    except list_sources.SourceError as error:
        raise HTTPException(503, str(error)) from None


def _source_label(source: dict) -> str:
    if source.get("label"):
        return str(source["label"])
    builder = str(source.get("builder") or "")
    if source.get("kind") == "titles":
        return list_sources.TITLE_BUILDERS.get(builder, (builder,))[0]
    if source.get("kind") == "search":
        return "Plex search"
    kind = list_sources.BY_BUILDER.get(builder)
    return kind.label if kind else builder


async def _read_sources(lists: list_sources.Lists, sources: list[dict], library_type: str) -> tuple[list[list_sources.ListItem], list[dict], list[str], int]:
    """The union of what a collection's list and titles sources name, in order, each title once; the sources Studio can't
    read itself ({label, why}); the problems reading the rest; and how many were read. A Plex search is Plex-side: it never has missing
    titles, and shows once built."""
    readable = [source for source in sources if source.get("kind") in ("list", "titles")]
    items: list[list_sources.ListItem] = []
    skipped: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    read = 0
    for source in sources:
        if source.get("kind") == "search":
            skipped.append({"label": _source_label(source), "why": "Studio shows what a Plex search finds once it has been built."})
            continue
        if source not in readable:
            continue
        try:
            if source["kind"] == "titles":
                found = await lists.titles(str(source.get("builder")), [str(i) for i in source.get("ids") or []], library_type)
            else:
                found = await lists.items(str(source.get("builder")), str(source.get("value")), library_type)
        except list_sources.NotPreviewable as why:
            skipped.append({"label": _source_label(source), "why": str(why)})
            continue
        except list_sources.SourceError as error:
            problems.append(str(error) if len(readable) == 1 else f"{_source_label(source)}: {error}")
            continue
        read += 1
        for item in found:
            key = list_sources.missing_key(item, library_type)
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items, skipped, problems, read


def _preview_sources(body: ListPreviewIn, library_type: str) -> tuple[list[dict], list[str]]:
    """The preview's sources as definitions (normalised), and the problems with any that can't be used."""
    if body.sources is None:
        if body.source is None:
            return [], ["Give a source to preview"]
        try:
            value, label = list_sources.normalise(body.source.builder, str(body.source.value), library_type)
        except list_sources.SourceError as error:
            return [], [str(error)]
        return [{"kind": "list", "builder": body.source.builder, "value": value, "label": label}], []
    out, problems = [], []
    for source in body.sources:
        try:
            if source.kind == "list":
                source.value, label = list_sources.normalise(source.builder or "", str(source.value or ""), library_type)
                source.label = (source.label or "").strip() or label
            elif source.kind == "titles":
                source.ids = list_sources.normalise_ids(source.builder or "", source.ids, library_type)
            elif source.kind != "search":
                continue
        except list_sources.SourceError as error:
            problems.append(str(error))
            continue
        out.append(_source_dict(source))
    return out, problems


@router.post("/builder/sources/preview")
async def builder_source_preview(body: ListPreviewIn, request: Request, settings: AppSettings) -> dict:
    """What a collection's lists and titles hold: the union, split into what the library has and what it's missing.
    ``skipped`` names the sources Studio can't read itself (IMDb, Letterboxd, a Plex search), which show once built."""
    context = await _context(request, settings, body.library)
    sources, problems = _preview_sources(body, context.library_type)
    return await _list_preview(context, _lists(request, settings), sources, problems)


async def _list_preview(context: Context, lists: list_sources.Lists, sources: list[dict], problems: list[str]) -> dict:
    """What list and titles sources hold, split into what the library has and what it's missing (the source preview)."""
    empty = {"total": None, "in_library": [], "in_library_count": 0, "missing": [], "missing_count": 0}
    items, skipped, read_problems, read = await _read_sources(lists, sources, context.library_type)
    problems += read_problems
    if not read:
        if skipped and not problems:
            return {"previewable": False, "why": skipped[0]["why"], **empty, "problems": [], "skipped": skipped}
        return {"previewable": True, "why": None, **empty, "problems": problems, "skipped": skipped}
    try:
        library = await context.server.all_items(context.section, context.library_type)
    except PlexUnavailable as error:
        raise HTTPException(503, f"Plex can't be reached: {error}") from None
    have, missing = list_sources.split(items, library)
    return {
        "previewable": True,
        "why": None,
        "skipped": skipped,
        "total": len(items),
        "in_library": [{"rating_key": i.rating_key, "title": i.title, "year": i.year, "thumb": i.thumb} for i in have[:LIST_PREVIEW_SIZE]],
        "in_library_count": len(have),
        "missing": [
            {"id": list_sources.missing_key(m, context.library_type), "title": m.title, "year": m.year, "poster": m.poster} for m in missing[:LIST_PREVIEW_SIZE]
        ],
        "missing_count": len(missing),
        "problems": problems,
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
    problems = _body_problems(context, body, settings)
    if problems:
        raise HTTPException(422, {"message": "The collection can't be made like this", "problems": problems})
    _check_poster(settings, body.poster)
    taken = await _title_taken(db, request, context, title, None)
    if taken:
        raise HTTPException(409, {"message": taken})
    missing = await _missing_now(request, settings, context, body, db)
    _check_requests(request, db, body, missing)
    with db:
        row_id = col.insert_built(db, body.library, secrets.token_hex(6), title, _definition(body))
        collection_requests.set_download_missing(db, [row_id], body.download_missing, body.request_cap, body.request_profile)
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
    _cleanup_posters(_config_dir(settings), db)
    await _request_now(request, db, row_id, missing)
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
    problems = _body_problems(context, body, settings)
    if problems:
        raise HTTPException(422, {"message": "The collection can't be made like this", "problems": problems})
    _check_poster(settings, body.poster)
    taken = await _title_taken(db, request, context, title, row_id)
    if taken:
        raise HTTPException(409, {"message": taken})
    old_title, old_definition = row["title"], row["definition"]
    old_flags = (row["download_missing"], row["request_cap"], row["request_profile"])
    missing = await _missing_now(request, settings, context, body, db) if collection_requests.load_settings(db).enabled else []
    _check_requests(request, db, body, missing, already_on=bool(row["download_missing"]))
    with db:
        col.update_built(db, row_id, title, _definition(body))
        collection_requests.set_download_missing(db, [row_id], body.download_missing, body.request_cap, body.request_profile)
    try:
        await _save_and_run(db, settings, writer, runner, context, row_id, f"Changed the collection {title!r} in {body.library}")
    except SaveRefused as refused:
        with db:
            col.update_built(db, row_id, old_title, json.loads(old_definition or "{}"))
            collection_requests.set_download_missing(db, [row_id], bool(old_flags[0]), old_flags[1], old_flags[2])
        raise HTTPException(refused.status, refused.detail()) from None
    if old_title.casefold() != title.casefold():
        # Kometa finds collections by title, so the old one would stay in Plex under its old name.
        gone, why = await _delete_from_plex(context, old_title)
        if not gone:
            log.warning("Renamed %r to %r, but the old collection stays in Plex: %s", old_title, title, why)
    _cleanup_posters(_config_dir(settings), db)
    await _request_now(request, db, row_id, missing)
    return _built_json(db, col.built_row(db, row_id))


@router.post("/collections/{row_id}/retry")
async def retry_collection(row_id: int, request: Request, db: Db, settings: AppSettings, writer: Writer, runner: AppRunner) -> dict:
    """Build the collection again as it stands, e.g. after a run failed on a network blip."""
    row = col.built_row(db, row_id)
    if row is None:
        raise HTTPException(404, "No such collection")
    if _run_status(db, row["last_run_id"]) in ("queued", "running"):
        raise HTTPException(409, {"message": f"{row['title']} is already being built"})
    context = await _context(request, settings, row["library"])
    try:
        await _save_and_run(db, settings, writer, runner, context, row_id, f"Built the collection {row['title']!r} again")
    except SaveRefused as refused:
        raise HTTPException(refused.status, refused.detail()) from None
    return _built_json(db, col.built_row(db, row_id))


@router.post("/collections/{row_id}/request-missing")
async def request_missing(row_id: int, request: Request, db: Db) -> dict:
    """Request the titles a collection (builder or ready-made) is waiting on: the go-ahead for more than the setting allows."""
    row = db.execute("SELECT * FROM collections WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such collection")
    items = collection_requests.waiting(db, row)
    try:
        outcome = await collection_requests.request_items(_requests_service(request), db, row, items)
    except collection_requests.RequestsDisabled:
        raise HTTPException(409, {"message": "Turn on requests in Settings → Requests first"}) from None
    return outcome.model_dump()


@router.put("/collections/{row_id}/download-missing")
async def put_download_missing(row_id: int, body: DownloadMissingIn, request: Request, db: Db, writer: Writer) -> dict:
    """Turn Download missing on or off for one collection, builder or ready-made."""
    row = db.execute("SELECT * FROM collections WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such collection")
    if body.download_missing:
        if not collection_requests.load_settings(db).enabled:
            raise HTTPException(422, {"message": "Turn on requests in Settings → Requests first"})
        if row["category"] == col.BUILT and not list_sources.has_missing(list_sources.sources_of(json.loads(row["definition"] or "{}"))):
            raise HTTPException(422, {"message": "A smart collection only holds what you have, so it has no missing titles to download"})
    with db:
        collection_requests.set_download_missing(db, [row_id], body.download_missing, keep_cap=True)
    if body.download_missing:
        try:
            await collection_requests.ensure_reports(writer)
        except SaveRefused as refused:
            log.warning("Couldn't turn on Kometa's missing report: %s", refused.detail())
    row = db.execute("SELECT * FROM collections WHERE id = ?", (row_id,)).fetchone()
    if row["category"] == col.BUILT:
        return _built_json(db, row)
    return {"id": row_id, "download_missing": bool(row["download_missing"]), "requests": collection_requests.summary(db, row)}


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
    _cleanup_posters(_config_dir(settings), db)
    return {"removed": gone, "reason": why}


# --- Posters -------------------------------------------------------------------------------------


@router.post("/builder/posters")
async def upload_poster(request: Request, settings: AppSettings) -> dict:
    """Store an uploaded JPEG/PNG/WebP under ``studio/posters/`` (content-addressed). Body is the image bytes."""
    # python-multipart isn't a dependency; the image is the request body (Content-Type: image/…).
    data = await request.body()
    if not data:
        raise HTTPException(422, "Send an image in the request body")
    if len(data) > POSTER_MAX_BYTES:
        raise HTTPException(422, "Image must be 10 MB or smaller")
    kind = _image_type(data)
    if kind is None:
        raise HTTPException(422, "Send a JPEG, PNG or WebP image")
    ext, _media = kind
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    folder = _config_dir(settings) / POSTER_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if not path.is_file():
        partial = path.with_suffix(path.suffix + ".part")
        partial.write_bytes(data)
        partial.replace(path)
    return {"kind": "file", "path": f"{POSTER_FOLDER}/{name}"}


@router.get("/builder/posters/{name}")
async def get_poster(name: str, settings: AppSettings) -> FileResponse:
    path = _poster_path(_config_dir(settings), name)
    if path is None or not path.is_file():
        raise HTTPException(404, "No such poster")
    media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[path.suffix.lower()]
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


# --- Ready-made templates open in the builder ----------------------------------------------------


NOT_A_FILTER = "This ready-made comes from a list, which the builder can't use yet"


async def _ready_made_filter(context: Context, settings, db: sqlite3.Connection, library: str, category: str, block: str, key: str) -> tuple[str, dict, dict]:
    """(title, filters, the block's attrs) for a ready-made collection that's a Plex filter. 422 when it isn't one."""
    root = _kometa_root(settings)
    source = studio_files.default_file(root, category, context.library_type) if root else None
    if source is None or not block:
        raise HTTPException(422, {"message": NOT_A_FILTER})
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
        raise HTTPException(422, {"message": NOT_A_FILTER})
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
    # Kometa's smart_filter template puts the value in an `any:` block, so a key with addons (G with TV-G)
    # matches either; in an `all:` block Kometa would AND them.
    return title, {"match": "any", "rules": [{"field": field.key, "modifier": "", "value": value}]}, attrs


# What the preview says for ready-mades Studio can't read before they're built.
NOT_PREVIEWABLE = "Kometa works out what goes in this one when it builds it. Build it to see what it holds."
NOT_PREVIEWABLE_TMDB = "Kometa looks these up on TMDb when it builds them. Build it to see what it holds."


@router.get("/ready-made/libraries/{library}/categories/{category}/preview")
async def preview_ready_made(library: str, category: str, key: str, request: Request, db: Db, settings: AppSettings, block: str = "") -> dict:
    """What one ready-made collection would hold, before it's built: the same shape as the builder's source preview.

    A Plex filter (genre, decade, a director …) is run against Plex; a chart that reads a list Studio knows (TMDb, IMDb,
    Letterboxd, MDBList) is read like a builder list, with what's missing. Anything else says why it can't be shown yet.
    """
    context = await _context(request, settings, library)
    empty = {"total": None, "in_library": [], "in_library_count": 0, "missing": [], "missing_count": 0, "skipped": []}
    try:
        _, filters, _ = await _ready_made_filter(context, settings, db, library, category, block, key)
    except HTTPException as error:
        if error.status_code != 422:
            raise
        filters = None
    if filters is not None:
        try:
            params = await smart_filters.plex_query(context.server, context.section, context.library_type, filters, TEMPLATE_SORT)
            items, total = await context.server.query(context.section, params, LIST_PREVIEW_SIZE)
        except smart_filters.SmartFilterError as error:
            return {"previewable": True, "why": None, **empty, "problems": [str(error)]}
        except PlexUnavailable as error:
            raise HTTPException(503, f"Plex can't be reached: {error}") from None
        return {
            "previewable": True,
            "why": None,
            **empty,
            "total": total,
            "in_library": [{"rating_key": i.rating_key, "title": i.title, "year": i.year, "thumb": i.thumb} for i in items],
            "in_library_count": total,
            "problems": [],
        }
    root = _kometa_root(settings)
    sources = ready_made_lists.sources(root, context.library_type, category, key) if root and not block else []
    if sources:
        return await _list_preview(context, _lists(request, settings), sources, [])
    tmdb = block and root and ready_made.dynamic_source(root, category, block, context.library_type) == "tmdb"
    return {"previewable": False, "why": NOT_PREVIEWABLE_TMDB if tmdb else NOT_PREVIEWABLE, **empty, "problems": []}


@router.get("/ready-made/libraries/{library}/categories/{category}/customise")
async def customise_ready_made(library: str, category: str, block: str, key: str, request: Request, db: Db, settings: AppSettings) -> dict:
    """A builder draft (not saved) for one ready-made collection that's a Plex filter, such as Action Movies."""
    context = await _context(request, settings, library)
    title, filters, attrs = await _ready_made_filter(context, settings, db, library, category, block, key)
    return {
        "library": library,
        "title": title,
        "filters": filters,
        "sort_by": TEMPLATE_SORT,
        "limit": None,
        "visible": {"library": True, "home": False, "shared": False},
        "minimum_items": 1,
        "summary": None,
        "sort_title": None,
        "poster": _kometa_poster(category, key, attrs),
    }
