"""Ready-made collections: gallery, build/remove, and the counting trigger (Phase 1)."""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import collections as col
from . import ready_made, studio_files
from .config_write import ConfigWriter, SaveRefused
from .health import PLEX_CHECK_TTL
from .kometa_command import RunRequest
from .kometa_config import read_plex
from .kometa_files import ConfigReader
from .plex_library import PlexNotFound, PlexServer, PlexUnavailable
from .plex_routes import kometa_plex
from .runner import Runner
from .settings import Settings
from .tasks import Tasks

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ready-made", tags=["ready-made"])

STUDIO_LABEL = "Studio"


class LibraryTypeCache:
    """Plex library types by section title, remembered for a few minutes like ``PlexCheck``."""

    def __init__(self) -> None:
        self._at = 0.0
        self._key: tuple[str, str] | None = None
        self._types: dict[str, str] = {}  # plex title lower → type
        self._keys: dict[str, str] = {}  # plex title lower → section key

    async def types(self, server: PlexServer) -> dict[str, str]:
        key = (server.url, server.token)
        if key == self._key and time.monotonic() - self._at < PLEX_CHECK_TTL:
            return self._types
        libraries = await server.libraries()
        self._types = {lib.title.casefold(): lib.type for lib in libraries}
        self._keys = {lib.title.casefold(): lib.key for lib in libraries}
        self._key, self._at = key, time.monotonic()
        return self._types

    async def key_for(self, server: PlexServer, plex_title: str) -> str | None:
        await self.types(server)
        return self._keys.get(plex_title.casefold())


_library_types = LibraryTypeCache()


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_runner(request: Request) -> Runner:
    return request.app.state.runner


def get_tasks(request: Request) -> Tasks:
    return request.app.state.tasks


def get_writer(request: Request) -> ConfigWriter:
    writer = request.app.state.writer
    if writer is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG.")
    return writer


Db = Annotated[sqlite3.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
AppRunner = Annotated[Runner, Depends(get_runner)]
AppTasks = Annotated[Tasks, Depends(get_tasks)]
Writer = Annotated[ConfigWriter, Depends(get_writer)]


def _kometa_root(settings: Settings) -> Path | None:
    return settings.kometa_entry.parent if settings.kometa_entry else None


def _reader(settings: Settings) -> ConfigReader:
    if settings.kometa_config is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG.")
    return ConfigReader(settings.kometa_config, _kometa_root(settings))


def _config_library(settings: Settings, name: str):
    try:
        kometa = _reader(settings).read()
    except FileNotFoundError:
        raise HTTPException(409, "Kometa's config.yml doesn't exist yet. Connect Plex in Settings → Plex.") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    library = next((lib for lib in kometa.libraries if lib.name == name), None)
    if library is None:
        raise HTTPException(404, f"No library called {name!r} in config.yml")
    return library, [lib.name for lib in kometa.libraries]


def _plex_title(library) -> str:
    return str(library.settings.get("library_name") or library.name)


async def _library_type(request: Request, settings: Settings, library) -> str | None:
    """The Plex section type for this config library, or None when Plex isn't available."""
    try:
        server = kometa_plex(settings, request.app.state.http)
        types = await _library_types.types(server)
    except (HTTPException, PlexUnavailable):
        return None
    return types.get(_plex_title(library).casefold()) or None


def _plex_valued(category: ready_made.Category) -> bool:
    """True when the category's collections come from Plex tags and need a count pass."""
    if not category.listable:
        return False
    # categories() leaves plex-sourced dynamics unexpanded, so an empty list on a per_value
    # (or award/both) category that isn't helper/fixed from files alone means "not counted yet".
    if category.collections:
        return False
    return category.kind == "per_value"


def _entry_dicts(cached: dict[str, Any] | None, category: ready_made.Category) -> list[dict]:
    if cached and isinstance(cached.get("data"), dict):
        entries = cached["data"].get("entries")
        if isinstance(entries, list):
            return [e for e in entries if isinstance(e, dict)]
    return [
        {"block": e.block, "key": e.key, "title": e.title, "kometa_name": e.kometa_name, "items": e.items}
        for e in category.collections
    ]


def _summary(
    category: ready_made.Category,
    rows: list[sqlite3.Row],
    cached: dict[str, Any] | None,
) -> dict:
    entries = _entry_dicts(cached, category)
    if cached is None and _plex_valued(category):
        count: int | None = None
    else:
        count = len(entries)
    run_scope: Literal["collection", "file"] = "file" if any(r["run_scope"] == "file" for r in rows) else "collection"
    return {
        "name": category.name,
        "title": category.title,
        "group": category.group,
        "kind": category.kind,
        "listable": category.listable,
        "reason": category.reason,
        "count": count,
        "in_plex": sum(1 for r in rows if r["plex_exists"]),
        "picked": sum(1 for r in rows if r["desired"]),
        "run_scope": run_scope,
    }


def _run_status(db: sqlite3.Connection, run_id: int | None) -> str | None:
    if run_id is None:
        return None
    row = db.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    return row["status"] if row else None


def _build_seconds(db: sqlite3.Connection, run_id: int | None) -> int | None:
    if run_id is None:
        return None
    row = db.execute(
        "SELECT started_at, finished_at FROM runs WHERE id = ? AND started_at IS NOT NULL AND finished_at IS NOT NULL",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    ended = db.execute("SELECT 1 FROM run_events WHERE run_id = ? AND event = 'run_end'", (run_id,)).fetchone()
    if ended is None:
        return None
    try:
        start = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
        finish = datetime.fromisoformat(row["finished_at"].replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((finish - start).total_seconds()))


def _entry_state(row: sqlite3.Row | None, run_status: str | None) -> str:
    if row is None:
        return "none"
    if run_status == "queued":
        return "queued"
    if run_status == "running":
        return "building"
    if row["desired"] == 0 and row["plex_exists"]:
        return "removing"
    if row["plex_exists"]:
        return "in_plex"
    if row["last_error"]:
        return "failed"
    return "missing"


def _row_key(row: sqlite3.Row) -> tuple[str, str]:
    return (row["block"], row["key"])


@router.get("/libraries/{library}")
async def library_gallery(library: str, request: Request, db: Db, settings: AppSettings, tasks: AppTasks) -> dict:
    lib, _ = _config_library(settings, library)
    library_type = await _library_type(request, settings, lib)
    root = _kometa_root(settings)
    cats = ready_made.categories(root, library_type or "movie") if root else []
    cached = col.counts(db, library)
    counted_at = None
    for info in cached.values():
        at = info.get("counted_at")
        if at and (counted_at is None or at > counted_at):
            counted_at = at
    rows_by_cat: dict[str, list[sqlite3.Row]] = {}
    for row in col.rows(db, library):
        rows_by_cat.setdefault(row["category"], []).append(row)
    return {
        "library": library,
        "library_type": library_type if library_type in ("movie", "show") else None,
        "counted_at": counted_at,
        "counting": tasks.running("ready_made_counts"),
        "categories": [_summary(cat, rows_by_cat.get(cat.name, []), cached.get(cat.name)) for cat in cats],
    }


@router.get("/libraries/{library}/categories/{name}")
async def category_detail(library: str, name: str, request: Request, db: Db, settings: AppSettings) -> dict:
    lib, _ = _config_library(settings, library)
    library_type = await _library_type(request, settings, lib)
    root = _kometa_root(settings)
    cats = ready_made.categories(root, library_type or "movie") if root else []
    category = next((c for c in cats if c.name == name), None)
    if category is None:
        # Still show a shell when only orphan rows remain for a removed default.
        rows = col.rows(db, library, name)
        if not rows:
            raise HTTPException(404, f"No ready-made category called {name!r}")
        category = ready_made.Category(
            name=name, title=name, group="both", kind="fixed", listable=True, reason=None, collections=[]
        )
    cached = col.counts(db, library).get(name)
    rows = col.rows(db, library, name)
    by_ref = {_row_key(r): r for r in rows}
    entries_src = _entry_dicts(cached, category)
    seen: set[tuple[str, str]] = set()
    collections_out: list[dict] = []
    for entry in entries_src:
        block, key = str(entry.get("block", "")), str(entry.get("key", ""))
        seen.add((block, key))
        row = by_ref.get((block, key))
        run_status = _run_status(db, row["last_run_id"] if row else None)
        collections_out.append(
            {
                "block": block,
                "key": key,
                "title": str(entry.get("title") or (row["title"] if row else key)),
                "items": entry.get("items"),
                "id": int(row["id"]) if row else None,
                "desired": bool(row["desired"]) if row else None,
                "state": _entry_state(row, run_status),
                "plex_items": int(row["plex_items"]) if row and row["plex_items"] is not None else None,
                "thumb": row["plex_thumb"] if row else None,
                "last_built_at": row["last_built_at"] if row else None,
                "last_error": row["last_error"] if row else None,
                "build_seconds": _build_seconds(db, row["last_run_id"]) if row else None,
            }
        )
    # Rows no longer in the catalogue: still listed so they can be removed.
    for row in rows:
        if _row_key(row) in seen:
            continue
        run_status = _run_status(db, row["last_run_id"])
        collections_out.append(
            {
                "block": row["block"],
                "key": row["key"],
                "title": row["title"],
                "items": None,
                "id": int(row["id"]),
                "desired": bool(row["desired"]),
                "state": _entry_state(row, run_status),
                "plex_items": int(row["plex_items"]) if row["plex_items"] is not None else None,
                "thumb": row["plex_thumb"],
                "last_built_at": row["last_built_at"],
                "last_error": row["last_error"],
                "build_seconds": _build_seconds(db, row["last_run_id"]),
            }
        )
    summary = _summary(category, rows, cached)
    return {**summary, "counted_at": cached["counted_at"] if cached else None, "collections": collections_out}


class RefIn(BaseModel):
    category: str
    block: str = ""
    key: str


class BuildIn(BaseModel):
    library: str
    add: list[RefIn] = Field(default_factory=list)
    remove: list[RefIn] = Field(default_factory=list)
    dry_run: bool = False


def _catalogue_index(cats: list[ready_made.Category]) -> dict[tuple[str, str, str], ready_made.Entry]:
    found: dict[tuple[str, str, str], ready_made.Entry] = {}
    for cat in cats:
        for entry in cat.collections:
            found[(cat.name, entry.block, entry.key)] = entry
        # Also index from cached counts later in build.
    return found


def _snapshot_rows(db: sqlite3.Connection, library: str) -> list[dict]:
    return [dict(row) for row in col.rows(db, library)]


def _restore_rows(db: sqlite3.Connection, library: str, snapshot: list[dict]) -> None:
    db.execute("DELETE FROM collections WHERE library = ?", (library,))
    for row in snapshot:
        db.execute(
            """
            INSERT INTO collections (
                id, library, category, block, key, kometa_name, title, origin, desired, run_scope,
                plex_rating_key, plex_exists, plex_items, plex_thumb, plex_checked_at,
                last_built_at, last_run_id, last_error, created_at, updated_at
            ) VALUES (
                :id, :library, :category, :block, :key, :kometa_name, :title, :origin, :desired, :run_scope,
                :plex_rating_key, :plex_exists, :plex_items, :plex_thumb, :plex_checked_at,
                :last_built_at, :last_run_id, :last_error, :created_at, :updated_at
            )
            """,
            row,
        )


async def _remove_plan(
    server: PlexServer | None,
    library_key: str | None,
    rows: list[sqlite3.Row],
    maintainerr_titles: set[str],
) -> list[dict]:
    studio_by_title: dict[str, Any] = {}
    all_by_title: dict[str, Any] = {}
    if server is not None and library_key is not None:
        try:
            labelled = await server.labelled_collections(library_key, STUDIO_LABEL)
            all_cols = await server.collections(library_key)
        except PlexUnavailable:
            labelled, all_cols = [], []
        studio_by_title = {c.title.casefold(): c for c in labelled}
        all_by_title = {c.title.casefold(): c for c in all_cols}

    planned = []
    for row in rows:
        title = row["title"]
        key = title.casefold()
        if key in maintainerr_titles:
            planned.append({"category": row["category"], "title": title, "deletable": False, "reason": "Maintainerr's collection"})
            continue
        if key in studio_by_title:
            planned.append({"category": row["category"], "title": title, "deletable": True, "reason": None})
            continue
        if key in all_by_title:
            planned.append(
                {
                    "category": row["category"],
                    "title": title,
                    "deletable": False,
                    "reason": "has no Studio label, so Studio didn't make it",
                }
            )
            continue
        # Nothing in Plex: deletable (the row just goes).
        planned.append({"category": row["category"], "title": title, "deletable": True, "reason": None})
    return planned


@router.post("/build")
async def build(
    body: BuildIn,
    request: Request,
    db: Db,
    settings: AppSettings,
    runner: AppRunner,
    writer: Writer,
) -> dict:
    library, all_libraries = _config_library(settings, body.library)
    library_type = await _library_type(request, settings, library) or "movie"
    root = _kometa_root(settings)
    if root is None:
        raise HTTPException(409, "Studio doesn't know where Kometa is. Set STUDIO_KOMETA_ENTRY.")

    cats = ready_made.categories(root, library_type)
    # Merge counted plex entries into the catalogue index so dynamic picks validate.
    cached = col.counts(db, body.library)
    index = _catalogue_index(cats)
    for cat in cats:
        for entry in _entry_dicts(cached.get(cat.name), cat):
            key = (cat.name, str(entry.get("block", "")), str(entry.get("key", "")))
            if key not in index:
                index[key] = ready_made.Entry(
                    block=str(entry.get("block", "")),
                    key=str(entry.get("key", "")),
                    kometa_name=str(entry.get("kometa_name") or entry.get("title") or entry.get("key")),
                    title=str(entry.get("title") or entry.get("key")),
                    items=entry.get("items"),
                )

    bad_add = []
    add_entries: list[tuple[col.Ref, ready_made.Entry]] = []
    for ref in body.add:
        entry = index.get((ref.category, ref.block, ref.key))
        if entry is None:
            bad_add.append(ref)
        else:
            add_entries.append((col.Ref(ref.category, ref.block, ref.key), entry))
    if bad_add:
        raise HTTPException(
            422,
            {
                "message": "Unknown collection to add",
                "refs": [{"category": r.category, "block": r.block, "key": r.key} for r in bad_add],
            },
        )

    remove_refs = [col.Ref(r.category, r.block, r.key) for r in body.remove]
    remove_rows: list[sqlite3.Row] = []
    bad_remove = []
    for ref in remove_refs:
        row = db.execute(
            "SELECT * FROM collections WHERE library = ? AND category = ? AND block = ? AND key = ?",
            (body.library, ref.category, ref.block, ref.key),
        ).fetchone()
        if row is None:
            bad_remove.append(ref)
        else:
            remove_rows.append(row)
    if bad_remove:
        raise HTTPException(
            422,
            {
                "message": "Unknown collection to remove",
                "refs": [{"category": r.category, "block": r.block, "key": r.key} for r in bad_remove],
            },
        )

    # Maintainerr titles for this Plex library (case-insensitive).
    maintainerr_titles: set[str] = set()
    service = getattr(request.app.state, "maintainerr", None)
    plex_title = _plex_title(library)
    if service is not None and service.connected():
        owned = service.snapshot.owned_by_title()
        maintainerr_titles = {t.casefold() for t in owned.get(plex_title.casefold(), [])}

    server: PlexServer | None = None
    library_key: str | None = None
    try:
        server = kometa_plex(settings, request.app.state.http)
        await _library_types.types(server)
        library_key = await _library_types.key_for(server, plex_title)
    except (HTTPException, PlexUnavailable):
        server = None

    remove_plan = await _remove_plan(server, library_key, remove_rows, maintainerr_titles)

    # Run plan for adds.
    rows_by_cat = {name: col.rows(db, body.library, name) for name in {r.category for r, _ in add_entries}}
    file_cats: set[str] = set()
    collection_names: list[str] = []
    for ref, entry in add_entries:
        scope = "file" if any(r["run_scope"] == "file" for r in rows_by_cat.get(ref.category, [])) else "collection"
        if scope == "file":
            file_cats.add(ref.category)
        else:
            collection_names.append(entry.kometa_name)
    # Categories that already need --run-files: their adds go as file stems, not collection names.
    files = sorted(file_cats)
    # Drop collection names that belong to file-scoped categories.
    if file_cats:
        collection_names = [entry.kometa_name for ref, entry in add_entries if ref.category not in file_cats]

    run_plan = None
    if add_entries:
        run_plan = {"libraries": [body.library], "collections": collection_names, "files": files}

    plan = {
        "build": [{"category": ref.category, "title": entry.title} for ref, entry in add_entries],
        "remove": remove_plan,
        "run": run_plan,
    }
    if body.dry_run:
        return plan

    snapshot = _snapshot_rows(db, body.library)
    picks = [
        col.Pick(ref, entry.kometa_name, entry.title) for ref, entry in add_entries
    ]
    try:
        with db:
            if picks:
                col.mark_present(db, body.library, picks)
            col.mark_absent(db, body.library, remove_refs)
            desired = col.desired(db, body.library)
        await studio_files.write_library(
            writer, root, body.library, library_type, desired, all_libraries, "Ready-made collections"
        )
    except SaveRefused as refused:
        with db:
            _restore_rows(db, body.library, snapshot)
        raise HTTPException(refused.status, refused.detail()) from None
    except Exception:
        with db:
            _restore_rows(db, body.library, snapshot)
        raise

    removed: list[str] = []
    kept: list[dict] = []
    for item, row in zip(remove_plan, remove_rows, strict=True):
        if not item["deletable"]:
            kept.append({"title": item["title"], "reason": item["reason"] or ""})
            continue
        # Delete from Plex only when a Studio-labelled collection is there; re-check labels first.
        title_key = item["title"].casefold()
        if server is not None and library_key is not None:
            try:
                labelled = await server.labelled_collections(library_key, STUDIO_LABEL)
                match = next((c for c in labelled if c.title.casefold() == title_key), None)
                if match is not None:
                    labels = await server.collection_labels(match.rating_key)
                    if STUDIO_LABEL in labels:
                        await server.delete_collection(match.rating_key)
            except (PlexUnavailable, PlexNotFound) as error:
                log.warning("Couldn't delete %r from Plex: %s", item["title"], error)
                kept.append({"title": item["title"], "reason": str(error)})
                continue
        with db:
            col.delete_rows(db, [int(row["id"])])
        removed.append(item["title"])

    run_id = None
    if add_entries and run_plan is not None:
        request_run = RunRequest(
            mode="collections",
            libraries=run_plan["libraries"],
            collections=run_plan["collections"],
            files=run_plan["files"],
        )
        run_id = runner.enqueue(request_run, trigger="ready-made")
        with db:
            # Re-read added ids (mark_present already returned them).
            if picks:
                ids = []
                for ref, _ in add_entries:
                    found = db.execute(
                        "SELECT id FROM collections WHERE library = ? AND category = ? AND block = ? AND key = ?",
                        (body.library, ref.category, ref.block, ref.key),
                    ).fetchone()
                    if found:
                        ids.append(int(found["id"]))
                col.set_run(db, ids, run_id)

    return {**plan, "run_id": run_id, "removed": removed, "kept": kept}


@router.post("/count")
async def start_count(tasks: AppTasks, response: Response) -> dict:
    if tasks.running("ready_made_counts"):
        response.status_code = 200
        return {"started": False}
    started = tasks.start("ready_made_counts")
    response.status_code = 202 if started else 200
    return {"started": started}


def needs_count(db: sqlite3.Connection) -> bool:
    """True when preview_counts is empty or older than a day."""
    row = db.execute("SELECT COUNT(*) AS n, MIN(counted_at) AS oldest FROM preview_counts").fetchone()
    if not row or row["n"] == 0:
        return True
    try:
        oldest = datetime.fromisoformat(str(row["oldest"]).replace("Z", "+00:00"))
    except ValueError:
        return True
    from datetime import UTC, timedelta

    return datetime.now(UTC) - oldest > timedelta(days=1)


def plex_is_configured(settings: Settings) -> bool:
    if settings.kometa_config is None or not settings.kometa_config.is_file():
        return False
    try:
        current = read_plex(settings.kometa_config)
    except (OSError, ValueError):
        return False
    return bool(current.url and current.token)
