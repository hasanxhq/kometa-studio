"""Moving over from Kometa (phase 4): read an existing Kometa setup and say how each collection would land in Studio.

Read-only. Nothing here writes a file or a row: the setup wizard shows the report, and Switch over acts on it.

Each collection lands one of three ways (the plan's "How each collection lands"):

- **imported**: Studio can describe it fully as a builder collection (a ``smart_filter``, or one list source), with
  the settings the builder has (summary, sort title, visibility, minimum items, a poster).
- **ready_made**: a ``- default:`` entry, which becomes the matching Ready-made category.
- **kept**: anything else. The file stays listed in config.yml and runs exactly as before, read-only in Studio,
  with the reason it was kept.

The unit that is kept or replaced is a **file**, never part of one: Studio never edits a user's file, and a file's
collections can share its templates. A file is replaced only when every collection in it is imported; otherwise the
whole file is kept, and its importable collections say they were kept with their file.

Studio's own generated files (``studio/…``) are already Studio's, and are left out of the counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import list_sources, smart_filters
from .kometa_files import ConfigReader, Library, Reference, _is_builder

STUDIO_FOLDER = "studio/"
STUDIO_HEADER = re.compile(r"^#\s*Written by (Starr|Kometa) Studio", re.MULTILINE)

# Keys a collection can have that the builder describes. Anything else keeps the collection.
DESCRIBED = {
    "summary", "sort_title", "visible_library", "visible_home", "visible_shared", "minimum_items",
    "url_poster", "file_poster", "collection_order", "sync_mode", "label",
    "radarr_add_missing", "sonarr_add_missing", "seerr_add_missing",
}
LIST_ORDERS = ("custom", "release", "alpha")  # the orders a list collection offers in the builder
ADD_MISSING = ("radarr_add_missing", "sonarr_add_missing", "seerr_add_missing")
# Template variables of a default that only shape what Studio drops anyway (separators) or picks (use_<key>).
SEPARATOR_VARIABLES = {"use_separator", "sep_style", "sep_name", "sep_summary", "sep_image"}

IMPORTED, READY_MADE, KEPT, STUDIO = "imported", "ready_made", "kept", "studio"


@dataclass
class Landing:
    """How one collection lands."""

    name: str
    result: str  # imported | ready_made | kept | studio
    reason: str | None = None  # why it was kept (or why it's already Studio's)
    notes: list[str] = field(default_factory=list)  # what changes on the way in, in plain words
    definition: dict | None = None  # imported: the builder definition (as builder_routes._definition makes it)
    kept_with_file: bool = False  # importable, but its file is kept for another collection

    def json(self) -> dict:
        return {
            "name": self.name,
            "result": self.result,
            "reason": self.reason,
            "notes": self.notes,
            "definition": self.definition,
            "kept_with_file": self.kept_with_file,
        }


@dataclass
class FileLanding:
    """One entry of a library's collection_files, and what Switch over would do with it."""

    kind: str  # file, folder, default, url, git, repo, unknown
    value: str  # the entry's path, name or address
    path: str | None  # the file Studio read (config-relative where it can be), None for remote entries
    action: str  # replace | keep | studio
    reason: str | None = None  # why the file is kept
    collections: list[Landing] = field(default_factory=list)
    ready_made: dict | None = None  # a default: entry: {"category", "exclude": [keys], "variables": {...}}

    def json(self) -> dict:
        return {
            "kind": self.kind,
            "value": self.value,
            "path": self.path,
            "action": self.action,
            "reason": self.reason,
            "collections": [landing.json() for landing in self.collections],
            "ready_made": self.ready_made,
        }


# --- One collection ---------------------------------------------------------------------------------


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def _bool(value: Any, default: bool) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "1"):
        return True
    if text in ("false", "no", "0"):
        return False
    return None


def _list(value: Any) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _names(keys: list[str]) -> str:
    keys = [f"`{key}`" for key in keys]
    if len(keys) <= 1:
        return "".join(keys)
    if len(keys) > 3:
        return ", ".join(keys[:3]) + f" and {len(keys) - 3} more"
    return ", ".join(keys[:-1]) + " and " + keys[-1]


def _filters(raw: Any, library_type: str) -> tuple[dict | None, str | None, int | None, str | None]:
    """(spec, sort_by, limit, problem) for a ``smart_filter`` mapping, as the builder would hold it."""
    if not isinstance(raw, dict):
        return None, None, None, "Its `smart_filter` isn't a mapping"
    matches = [key for key in ("all", "any") if key in raw]
    extra = [str(key) for key in raw if key not in ("all", "any", "sort_by", "limit", "validate")]
    if len(matches) != 1 or extra:
        return None, None, None, "Its `smart_filter` uses " + (_names(extra) if extra else "both `all` and `any`") + ", which the builder doesn't have"
    match = matches[0]
    inner = raw[match]
    if not isinstance(inner, dict):
        return None, None, None, f"Its `smart_filter` `{match}` isn't a mapping"
    rules = []
    for key, value in inner.items():
        key = str(key)
        if key in ("all", "any"):
            return None, None, None, "Its `smart_filter` nests `all`/`any` groups, which the builder doesn't have"
        field_name, _, modifier = key.partition(".")
        modifier = modifier.lstrip(".")
        if isinstance(value, (list, tuple)):
            value = [str(item) for item in value]
        elif not isinstance(value, (bool, int, float, str)):
            return None, None, None, f"Its `smart_filter` rule `{key}` has a value the builder can't show"
        rules.append({"field": field_name, "modifier": modifier, "value": value})
    spec = {"match": match, "rules": rules}
    sort_by = str(raw["sort_by"]) if raw.get("sort_by") is not None else None
    limit = raw.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return None, None, None, "Its `smart_filter` `limit` isn't a number"
        if limit < 1:
            return None, None, None, "Its `smart_filter` `limit` isn't a positive number"
    problems = smart_filters.validate(library_type, spec, sort_by)
    if problems:
        return None, None, None, "The builder can't show its `smart_filter`: " + problems[0]
    return spec, sort_by, limit, None


def _list_source(builder: str, raw: Any, library_type: str) -> tuple[dict | None, str | None]:
    values = _list(raw)
    kind = list_sources.BY_BUILDER[builder]
    if len(values) != 1:
        return None, f"It reads {len(values)} {kind.label}s; the builder takes one" if values else f"Its `{builder}` is blank"
    try:
        value, label = list_sources.normalise(builder, str(values[0]), library_type)
    except list_sources.SourceError as error:
        return None, str(error)
    return {"kind": "list", "builder": builder, "value": value, "label": label}, None


def describe(name: str, body: Any, library_type: str, poster_path: Any = None) -> Landing:
    """How a static collection from a user's file would land, given its library's type ('movie' or 'show').

    ``poster_path`` turns a ``file_poster`` value into a path Studio can read (``ConfigReader._local``); without it a
    file poster keeps the collection.
    """
    if not isinstance(body, dict):
        return Landing(name, KEPT, "It isn't a mapping of settings")
    keys = [str(key) for key in body]
    if "template" in body:
        return Landing(name, KEPT, "It uses a template, which the builder doesn't have yet")
    builders = [key for key in keys if key == "smart_filter" or key in list_sources.BY_BUILDER or _is_other_builder(key)]
    if not builders:
        return Landing(name, KEPT, "It has no source the builder knows (" + (_names(keys) if keys else "it's empty") + ")")
    if len(builders) > 1:
        return Landing(name, KEPT, f"It combines {len(builders)} sources ({_names(builders)}); a builder collection takes one")
    builder = builders[0]
    if builder != "smart_filter" and builder not in list_sources.BY_BUILDER:
        return Landing(name, KEPT, f"Its source `{builder}` isn't one the builder offers")
    other = [key for key in keys if key != builder and key not in DESCRIBED]
    if other:
        return Landing(name, KEPT, f"It uses {_names(other)}, which the builder doesn't have")

    notes: list[str] = []
    definition: dict[str, Any] = {
        "source": {"kind": "filters"},
        "filters": {"match": "all", "rules": []},
        "sort_by": None,
        "limit": None,
        "visible": {"library": True, "home": False, "shared": False},
        "minimum_items": 1,
        "summary": None,
        "sort_title": None,
        "poster": None,
    }
    if builder == "smart_filter":
        spec, sort_by, limit, problem = _filters(body["smart_filter"], library_type)
        if problem:
            return Landing(name, KEPT, problem)
        definition.update(filters=spec, sort_by=sort_by, limit=limit)
        if body.get("collection_order") is not None:
            notes.append("`collection_order` is dropped: a smart collection is ordered by its filter's sort")
        if body.get("sync_mode") is not None:
            notes.append("`sync_mode` is dropped: a smart collection always matches its filter")
    else:
        source, problem = _list_source(builder, body[builder], library_type)
        if problem:
            return Landing(name, KEPT, problem)
        definition["source"] = source
        order = body.get("collection_order")
        if order is not None:
            if str(order) not in LIST_ORDERS:
                return Landing(name, KEPT, f"Its `collection_order: {order}` isn't one the builder offers (custom, release or alpha)")
            definition["sort_by"] = str(order)
        if body.get("sync_mode") is not None and str(body["sync_mode"]).lower() != "sync":
            notes.append(f"`sync_mode: {body['sync_mode']}` becomes sync: titles that leave the list leave the collection")

    for key, setting in (("visible_library", "library"), ("visible_home", "home"), ("visible_shared", "shared")):
        value = _bool(body.get(key), definition["visible"][setting])
        if value is None:
            return Landing(name, KEPT, f"Its `{key}` isn't true or false")
        definition["visible"][setting] = value
    if body.get("minimum_items") is not None:
        try:
            definition["minimum_items"] = max(1, int(body["minimum_items"]))
        except (TypeError, ValueError):
            return Landing(name, KEPT, "Its `minimum_items` isn't a number")
    for key in ("summary", "sort_title"):
        if body.get(key) is not None and str(body[key]).strip():
            definition[key] = str(body[key])

    labels = [str(label).strip() for label in _list(body.get("label")) if str(label).strip()]
    if any(label.casefold() != "studio" for label in labels):
        return Landing(name, KEPT, f"It adds the label{'s' if len(labels) > 1 else ''} {', '.join(labels)}, and the builder doesn't set labels")

    if body.get("url_poster") is not None and body.get("file_poster") is not None:
        return Landing(name, KEPT, "It sets both `url_poster` and `file_poster`")
    if body.get("url_poster") is not None:
        url = str(body["url_poster"]).strip()
        if not url.startswith(("http://", "https://")):
            return Landing(name, KEPT, "Its `url_poster` isn't a web address")
        definition["poster"] = {"kind": "url", "url": url}
    elif body.get("file_poster") is not None:
        if poster_path is None:
            return Landing(name, KEPT, "It has a `file_poster`, which Studio can't read here")
        path = poster_path(str(body["file_poster"]))
        if not Path(path).is_file():
            return Landing(name, KEPT, f"Its `file_poster` {body['file_poster']} isn't there")
        definition["poster"] = {"kind": "import", "path": str(path)}  # Switch over copies it into studio/posters/
        notes.append("Its poster file is copied into Studio's posters")

    wanted = [key for key in ADD_MISSING if _truthy(body.get(key))]
    if wanted:
        notes.append(
            f"Kometa's `{wanted[0]}` is turned off: Studio requests missing titles itself. Tick Download missing on it to keep requesting"
            if builder != "smart_filter" else f"`{wanted[0]}` is dropped: a smart collection has no missing titles"
        )
    return Landing(name, IMPORTED, notes=notes, definition=definition)


def _is_other_builder(key: str) -> bool:
    """A Kometa builder the import doesn't describe (plex_search, tmdb_movie, …)."""
    return _is_builder(key)


# --- One file ---------------------------------------------------------------------------------------


def _yaml() -> YAML:
    return YAML(typ="safe", pure=True)


def describe_file(
    text: str, library_type: str, taken: set[str] = frozenset(), poster_path: Any = None, blocked: dict[str, str] | None = None
) -> tuple[str, str | None, list[Landing]]:
    """(action, reason, landings) for one collection file's text: replace when every collection in it is imported.

    ``taken`` holds titles (casefolded) of the library's collections that Studio already has: those land as ``studio``.
    ``blocked`` maps titles (casefolded) Studio must never take over to the reason (Maintainerr's collections): kept.
    The same import runs for a file uploaded later (step 4).
    """
    if STUDIO_HEADER.search(text.split("\n", 3)[0] if text else ""):
        return "studio", "Studio writes this file", []
    try:
        data = _yaml().load(text) or {}
    except YAMLError as error:
        return "keep", f"It isn't valid YAML: {str(error).splitlines()[0]}", []
    if not isinstance(data, dict):
        return "keep", "It doesn't hold a mapping at the top level", []
    landings: list[Landing] = []
    collections = data.get("collections") if isinstance(data.get("collections"), dict) else {}
    for name, body in collections.items():
        name = str(name)
        if name.casefold() in taken:
            landings.append(Landing(name, STUDIO, "Studio already has a collection with this title in this library"))
        elif blocked and name.casefold() in blocked:
            landings.append(Landing(name, KEPT, blocked[name.casefold()]))
        else:
            landings.append(describe(name, body, library_type, poster_path))
    dynamic = data.get("dynamic_collections") if isinstance(data.get("dynamic_collections"), dict) else {}
    for name in dynamic:
        landings.append(Landing(str(name), KEPT, "It's a dynamic collection (one per value); Ready-made has categories like it"))

    blockers = []
    for key in ("templates", "external_templates", "overlays", "metadata", "playlists"):
        if data.get(key):
            blockers.append(key)
    if blockers:
        reason = f"It holds {_names(blockers)}, which stay with Kometa"
    elif not landings:
        reason = "It has no collections"
    else:
        kept = [landing for landing in landings if landing.result == KEPT]
        reason = None if not kept else (
            f"{kept[0].name} can't be imported" if len(kept) == 1 else f"{len(kept)} of its collections can't be imported"
        )
    if reason is None:
        return "replace", None, landings
    for landing in landings:
        if landing.result == IMPORTED:
            landing.kept_with_file = True
    return "keep", reason, landings


# --- A whole config.yml -----------------------------------------------------------------------------


def _ready_made(reference: Reference, library_type: str, kometa_root: Path | None) -> FileLanding:
    from . import ready_made

    landing = FileLanding("default", reference.value, None, "keep")
    if kometa_root is None:
        landing.reason = "Studio doesn't know where Kometa is installed, so it can't read its defaults"
        return landing
    name = reference.value.removesuffix(".yml").removesuffix(".yaml").split("/")[-1]
    category = next((cat for cat in ready_made.categories(kometa_root, library_type) if cat.name == name), None)
    if category is None:
        landing.reason = f"Ready-made has no {name!r} category for this library"
        return landing
    if not category.listable:
        landing.reason = category.reason or "Ready-made can't list this category's collections yet"
        return landing
    exclude: list[str] = []
    unknown: list[str] = []
    for key, value in reference.template_variables.items():
        key = str(key)
        if key in SEPARATOR_VARIABLES:
            continue
        if key.startswith("use_") and _bool(value, True) is False:
            exclude.append(key[4:])
            continue
        if key.startswith("use_") and _bool(value, True) is True:
            continue
        unknown.append(key)
    options = [str(key) for key in reference.options if key != "template_variables"]
    if unknown or options:
        landing.reason = f"Its {_names(unknown + options)} {'is' if len(unknown + options) == 1 else 'are'}n't something Ready-made carries yet"
        return landing
    if not category.collections:
        landing.reason = f"Ready-made finds {category.title}'s collections in your library: pick them in Ready-made → {category.title}"
        return landing
    excluded = {_toggle(key) for key in exclude}
    entries = [entry for entry in category.collections if _toggle(entry.key) not in excluded and _toggle(entry.title) not in excluded]
    if not entries:
        landing.reason = "Its template variables turn every collection off"
        return landing
    landing.action = "replace"
    landing.ready_made = {
        "category": category.name,
        "title": category.title,
        "exclude": exclude,
        "entries": [{"block": e.block, "key": e.key, "kometa_name": e.kometa_name, "title": e.title} for e in entries],
    }
    return landing


def _toggle(text: str) -> str:
    """A collection key as Kometa's ``use_<key>`` variables spell it: lower case, underscores."""
    return re.sub(r"[^a-z0-9]+", "_", str(text).casefold()).strip("_")


def _config_relative(reader: ConfigReader, path: Path) -> str:
    try:
        return path.resolve().relative_to(reader.config_path.parent.resolve()).as_posix()
    except ValueError:
        return reader.display_path(path)


def describe_library(
    reader: ConfigReader,
    library: Library,
    library_type: str | None,
    taken: set[str] = frozenset(),
    generated: set[str] = frozenset(),
    kometa_root: Path | None = None,
    blocked: dict[str, str] | None = None,
) -> dict:
    """One config.yml library: each collection_files entry and how it lands, plus what stays as it is."""
    out: dict[str, Any] = {
        "name": library.name,
        "type": library_type,
        "error": None,
        "files": [],
        "overlay_files": [ref.value for ref in library.overlay_files],
        "metadata_files": [ref.value for ref in library.metadata_files],
    }
    if library_type not in ("movie", "show"):
        out["error"] = (
            "Plex has no movie or show library by this name, so Studio can't tell what its collections hold"
            if library_type else "Plex can't be reached, so Studio can't tell this library's type"
        )
        return out
    for reference in library.collection_files:
        if reference.kind == "default":
            out["files"].append(_ready_made(reference, library_type, kometa_root).json())
            continue
        if reference.kind in ("url", "git", "repo"):
            out["files"].append(FileLanding(reference.kind, reference.value, None, "keep", f"It's loaded from {reference.kind}, so Studio can't read it").json())
            continue
        if reference.error or reference.kind not in ("file", "folder"):
            out["files"].append(FileLanding(reference.kind, reference.value, None, "keep", reference.error or "Studio can't read this entry").json())
            continue
        if reference.kind == "file":
            paths = [reader._local(reference.value)]
        else:
            folder = reader._local(reference.value)
            paths = sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")])
        for path in paths:
            relative = _config_relative(reader, path)
            if relative.startswith(STUDIO_FOLDER) or relative in generated:
                out["files"].append(FileLanding(reference.kind, reference.value, relative, "studio", "Studio writes this file").json())
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                out["files"].append(FileLanding(reference.kind, reference.value, relative, "keep", f"Studio can't read it: {error}").json())
                continue
            action, reason, landings = describe_file(text, library_type, taken, reader._local, blocked)
            if reference.kind == "folder" and action == "replace":
                action, reason = "keep", "It's part of a folder entry, which Switch over keeps whole"
                for landing in landings:
                    if landing.result == IMPORTED:
                        landing.kept_with_file = True
            if reference.options and action == "replace":
                action, reason = "keep", f"Its entry sets {_names([str(key) for key in reference.options])}, which Studio doesn't carry yet"
                for landing in landings:
                    if landing.result == IMPORTED:
                        landing.kept_with_file = True
            landing = FileLanding(reference.kind, reference.value, relative, action, reason, landings)
            out["files"].append(landing.json())
    return out


def summarise(libraries: list[dict]) -> dict:
    """The counts the wizard shows, and the plan's one number: how many collections avoid Kept."""
    counts = {IMPORTED: 0, READY_MADE: 0, KEPT: 0, STUDIO: 0, "kept_with_file": 0}
    files = {"replace": 0, "keep": 0, "studio": 0}
    for library in libraries:
        for entry in library["files"]:
            files[entry["action"]] = files.get(entry["action"], 0) + 1
            if entry["kind"] == "default":
                counts[READY_MADE if entry["action"] == "replace" else KEPT] += 1
                continue
            for landing in entry["collections"]:
                if landing["result"] == IMPORTED and landing["kept_with_file"]:
                    counts["kept_with_file"] += 1
                    counts[KEPT] += 1
                else:
                    counts[landing["result"]] += 1
    considered = counts[IMPORTED] + counts[READY_MADE] + counts[KEPT]
    return {
        "collections": considered,
        "imported": counts[IMPORTED],
        "ready_made": counts[READY_MADE],
        "kept": counts[KEPT],
        "kept_with_file": counts["kept_with_file"],
        "already_studio": counts[STUDIO],
        "files": files,
    }


def report(
    reader: ConfigReader,
    library_types: dict[str, str | None],
    taken: dict[str, set[str]] | None = None,
    generated: set[str] = frozenset(),
    kometa_root: Path | None = None,
    blocked: dict[str, dict[str, str]] | None = None,
) -> dict:
    """The whole import: every library, its files and collections, and the counts. Raises like ConfigReader.read.

    ``taken`` and ``blocked`` are per config.yml library name (see ``describe_file``).
    """
    config = reader.read()
    libraries = [
        describe_library(
            reader, library, library_types.get(library.name), (taken or {}).get(library.name, set()), generated, kometa_root, (blocked or {}).get(library.name)
        )
        for library in config.libraries
    ]
    return {
        "summary": summarise(libraries),
        "libraries": libraries,
        "playlist_files": [ref.value for ref in config.playlist_files],
    }
