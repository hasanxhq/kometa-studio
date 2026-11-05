"""Generate Kometa collection files from Studio's ready-made picks.

Studio writes a patched copy of each Kometa default into ``studio/<library>/<category>.yml``
so every generated collection can carry the ``Studio`` Plex label (Kometa's defaults have no
variable for extra labels). Saves go through ``ConfigWriter`` like any other edit.
"""

from __future__ import annotations

import io
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import collections as col
from .collections import Ref
from .config_sections import with_library_file, without_library_file
from .config_write import ConfigWriter, Edit, SaveRefused, file_hash
from .kometa_config import TEMPLATE_INDENT, _parse, render as render_yaml

STUDIO_FOLDER = "studio"
HEADER = (
    'Written by Starr Studio from Kometa\'s "{category}" default. '
    "Studio rewrites this file on every save: change these collections in Studio."
)
# Kometa's Default resolution order for a library type (modules/meta.py load_file).
DEFAULT_FOLDERS = ("both", "chart", "award")  # after <library_type>/
UNSAFE = re.compile(r"[^A-Za-z0-9 _\-]+")
ARR_MISSING = ("radarr_add_missing", "sonarr_add_missing")


def _safe_folder(name: str) -> str:
    cleaned = UNSAFE.sub("_", name).strip()
    return cleaned or "_"


def library_folders(all_libraries: list[str]) -> dict[str, str]:
    """Map each library name to a deterministic folder under ``studio/`` (``-2``, ``-3`` on clashes)."""
    used: dict[str, int] = {}
    folders: dict[str, str] = {}
    for name in sorted(all_libraries):
        base = _safe_folder(name)
        n = used.get(base, 0) + 1
        used[base] = n
        folders[name] = base if n == 1 else f"{base}-{n}"
    return folders


def relative_path(library: str, category: str, all_libraries: list[str]) -> str:
    """Path of the generated file relative to the config dir (for ``ConfigWriter.resolve``)."""
    folder = library_folders(all_libraries)[library]
    return f"{STUDIO_FOLDER}/{folder}/{category}.yml"


def default_file(kometa_root: Path, category: str, library_type: str) -> Path | None:
    """The default Kometa would load for ``default: <category>`` in a ``movie`` or ``show`` library.

    Order matches ``modules/meta.py`` ``load_file`` for ``Default``: a file directly under
    ``defaults/``, else ``<type>/``, then ``both/``, ``chart/``, ``award/``.
    """
    name = category if category.endswith((".yml", ".yaml")) else f"{category}.yml"
    defaults = kometa_root / "defaults"
    candidates = [defaults / name] + [defaults / folder / name for folder in (library_type, *DEFAULT_FOLDERS)]
    return next((path for path in candidates if path.is_file()), None)


def _template_names(value: object) -> list[str]:
    if value is None:
        return []
    entries = value if isinstance(value, list) else [value]
    names: list[str] = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") is not None:
            names.append(str(entry["name"]))
        elif entry is not None and not isinstance(entry, dict):
            names.append(str(entry))
    return names


def _is_separator(body: object) -> bool:
    return isinstance(body, dict) and "separator" in _template_names(body.get("template"))


def _merge_append_label(body: CommentedMap) -> None:
    """Add ``Studio`` to ``append_label``, keeping any existing value(s)."""
    current = body.get("append_label")
    if current is None:
        body["append_label"] = "Studio"
        return
    if isinstance(current, list):
        labels = [str(item) for item in current]
        if "Studio" not in labels:
            current.append("Studio")
        return
    if str(current) == "Studio":
        return
    body["append_label"] = CommentedSeq([str(current), "Studio"])


def _add_studio_template(block: CommentedMap) -> None:
    """Append ``studio_label`` to a dynamic block's ``template`` list, keeping existing entries."""
    current = block.get("template")
    if current is None:
        block["template"] = CommentedSeq(["studio_label"])
        return
    if isinstance(current, str):
        if current != "studio_label":
            block["template"] = CommentedSeq([current, "studio_label"])
        return
    if not isinstance(current, list):
        block["template"] = CommentedSeq(["studio_label"])
        return
    if "studio_label" in _template_names(current):
        return
    current.append("studio_label")


def _drop_arr_missing(node: object) -> None:
    if isinstance(node, dict):
        for key in list(node):
            if key in ARR_MISSING:
                del node[key]
            else:
                _drop_arr_missing(node[key])
    elif isinstance(node, list):
        for item in node:
            _drop_arr_missing(item)


def _ensure_studio_label_template(document: CommentedMap) -> None:
    templates = document.get("templates")
    if not isinstance(templates, CommentedMap):
        templates = CommentedMap()
        document["templates"] = templates
    if "studio_label" not in templates:
        # ``label:`` adds without sync; works alongside dynamic collections' ``append_label: <block>``
        # (which would block a second ``append_label`` from a template — see .agent-notes.md).
        templates["studio_label"] = CommentedMap([("label", "Studio")])


def _set_use_separator_false(document: CommentedMap) -> None:
    external = document.get("external_templates")
    if not isinstance(external, CommentedMap):
        return
    variables = external.get("template_variables")
    if not isinstance(variables, CommentedMap):
        variables = CommentedMap()
        external["template_variables"] = variables
    variables["use_separator"] = False


def render(default_text: str, category: str, picks: list[Ref]) -> str | None:
    """A patched copy of a Kometa default kept to ``picks``. ``None`` if nothing remains."""
    document, indent = _parse(default_text) if default_text.strip() else (CommentedMap(), TEMPLATE_INDENT)

    static_keys = {ref.key for ref in picks if ref.block == ""}
    dynamic_keys: dict[str, set[str]] = {}
    for ref in picks:
        if ref.block:
            dynamic_keys.setdefault(ref.block, set()).add(ref.key)

    collections = document.get("collections")
    if isinstance(collections, CommentedMap):
        for name in list(collections):
            body = collections[name]
            if _is_separator(body) or name not in static_keys:
                del collections[name]
            elif isinstance(body, CommentedMap):
                _merge_append_label(body)
        if not collections:
            document.pop("collections", None)
    else:
        document.pop("collections", None)

    dynamic = document.get("dynamic_collections")
    if isinstance(dynamic, CommentedMap):
        for name in list(dynamic):
            if name not in dynamic_keys:
                del dynamic[name]
                continue
            block = dynamic[name]
            if not isinstance(block, CommentedMap):
                del dynamic[name]
                continue
            keys = sorted(dynamic_keys[name], key=str)
            block["include"] = CommentedSeq(keys)
            block.pop("sync", None)
            _add_studio_template(block)
        if not dynamic:
            document.pop("dynamic_collections", None)
    else:
        document.pop("dynamic_collections", None)

    kept_static = isinstance(document.get("collections"), CommentedMap) and bool(document["collections"])
    kept_dynamic = isinstance(document.get("dynamic_collections"), CommentedMap) and bool(document["dynamic_collections"])
    if not kept_static and not kept_dynamic:
        return None

    _set_use_separator_false(document)
    _ensure_studio_label_template(document)
    _drop_arr_missing(document)

    text = render_yaml(default_text, document, indent)
    header = f"# {HEADER.format(category=category)}\n"
    if text.startswith("---\n"):
        return f"---\n{header}{text[4:]}"
    return header + text


def _studio_prefix(library: str, all_libraries: list[str]) -> str:
    return f"{STUDIO_FOLDER}/{library_folders(all_libraries)[library]}/"


# The old name stays recognised: files written before the rename are still Studio's, and get the new header on their next save.
GENERATED_MARKS = ("Written by Starr Studio", "Written by Kometa Studio")


def is_generated(text: str) -> bool:
    """True for a file Studio wrote: its header is in the first lines."""
    return any(mark in line for line in text.splitlines()[:3] for mark in GENERATED_MARKS)


BUILT_HEADER = "Written by Starr Studio from its collection builder. Studio rewrites this file on every save: change these collections in Studio."


def render_built(
    definitions: list[tuple[str, dict]],
    file_ref: Callable[[str], str] | None = None,
    library_type: str = "movie",
) -> str | None:
    """Kometa's file for the library's builder collections, each labelled Studio. None if there are none.

    A filter collection is a ``smart_filter``. Any other collection has each of its sources as its Kometa builder
    (``tmdb_collection: 1234``, ``imdb_list: [a, b]``, ``tmdb_movie: [10196]``, ``plex_search: {any: …}``; Kometa adds
    up what they find) with ``sync_mode: sync``, so titles leaving the list leave the collection, and with Kometa's own Radarr/Sonarr
    requests off: only Studio requests missing titles.

    ``file_ref`` turns a config-relative poster path (``studio/posters/…``) into the path Kometa's working directory
    uses for ``file_poster`` (``ConfigWriter.reference``). Without it, a file poster is skipped.
    """
    from . import list_sources, smart_filters

    if not definitions:
        return None
    collections = CommentedMap()
    for title, definition in sorted(definitions, key=lambda pair: pair[0].casefold()):
        body = CommentedMap()
        sources = list_sources.sources_of(definition)
        if any(source.get("kind") != "filters" for source in sources):
            body.update(_builders(sources))
            body["sync_mode"] = "sync"
            if definition.get("sort_by") in ("custom", "release", "alpha"):
                body["collection_order"] = str(definition["sort_by"])
            body["radarr_add_missing" if library_type == "movie" else "sonarr_add_missing"] = False
        else:
            body["smart_filter"] = smart_filters.to_kometa(definition.get("filters") or {}, definition.get("sort_by"), definition.get("limit"))
        body["label"] = "Studio"  # adds the label without replacing others (Kometa's label, not label.sync)
        visible = definition.get("visible") or {}
        for setting, key, default in (("library", "visible_library", True), ("home", "visible_home", False), ("shared", "visible_shared", False)):
            value = visible.get(setting, default)
            if value is not None:  # None (an imported collection whose file didn't say): Plex keeps what it has
                body[key] = bool(value)
        body["minimum_items"] = int(definition.get("minimum_items") or 1)
        if definition.get("summary"):
            body["summary"] = str(definition["summary"])
        if definition.get("sort_title"):
            body["sort_title"] = str(definition["sort_title"])
        poster = definition.get("poster")
        if isinstance(poster, dict):
            if poster.get("kind") == "file" and poster.get("path") and file_ref is not None:
                body["file_poster"] = file_ref(str(poster["path"]))
            elif poster.get("kind") == "url" and poster.get("url"):
                body["url_poster"] = str(poster["url"])
        collections[title] = body
    document = CommentedMap([("collections", collections)])
    stream = io.StringIO()
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    yaml.dump(document, stream)
    return f"# {BUILT_HEADER}\n" + stream.getvalue()


def _builders(sources: list[dict]) -> dict:
    """Kometa builder keys for a collection's non-filter sources, in the order they first appear. Several sources of one
    list builder become a YAML list; several titles sources of one builder become one list of ids."""
    from . import list_sources, smart_filters

    out: dict[str, list] = {}
    search: dict | None = None
    for source in sources:
        kind, builder = source.get("kind"), str(source.get("builder") or "")
        if kind == "list" and builder:
            values = out.setdefault(builder, [])
            value = list_sources.kometa_value(builder, str(source.get("value") or ""))
            if value not in values:
                values.append(value)
        elif kind == "titles" and builder:
            values = out.setdefault(builder, [])
            values += [i for i in list_sources.titles_value(builder, [str(i) for i in source.get("ids") or []]) if i not in values]
        elif kind == "search" and search is None:
            search = smart_filters.to_plex_search(source.get("filters") or {})
            out["plex_search"] = []  # keeps its place in the order
    body: dict = {}
    for key, values in out.items():
        if key == "plex_search":
            body[key] = search
        elif key in list_sources.TITLE_BUILDERS:
            body[key] = values
        else:
            body[key] = values[0] if len(values) == 1 else values
    return body


@dataclass
class Written:
    saved: dict | None  # ConfigWriter.save's result; None when nothing changed
    generated: dict[str, str] = field(default_factory=dict)  # config-relative path → sha256 of Studio's text there now
    removed: list[str] = field(default_factory=list)  # generated files removed because their category has no picks left


def record(db: sqlite3.Connection, written: Written) -> None:
    """Remember what Studio wrote, so a later hand edit can be told apart (``hand_edited``)."""
    col.record_generated(db, written.generated)
    col.forget_generated(db, written.removed)


def hand_edited(db: sqlite3.Connection, config_dir: Path, library: str | None = None, all_libraries: list[str] | None = None) -> list[str]:
    """Generated files whose text isn't what Studio last wrote there (config-relative), for one library or all.

    Files Studio hasn't recorded (written before it kept hashes) and files that are gone don't count.
    """
    prefix = f"{STUDIO_FOLDER}/"
    if library:
        libraries = all_libraries or []
        prefix = _studio_prefix(library, libraries if library in libraries else [*libraries, library])
    found = []
    for rel, digest in sorted(col.generated(db).items()):
        if not rel.startswith(prefix):
            continue
        try:
            data = (config_dir / rel).read_bytes()
        except OSError:
            continue
        if file_hash(data) != digest:
            found.append(rel)
    return found


def _file_entries(text: str, library: str) -> list[str]:
    """``file:`` references currently listed under the library's ``collection_files``."""
    document, _ = _parse(text)
    libraries = document.get("libraries")
    if not isinstance(libraries, CommentedMap) or library not in libraries:
        return []
    body = libraries[library]
    if not isinstance(body, dict):
        return []
    entries = body.get("collection_files")
    if entries is None:
        return []
    if not isinstance(entries, list):
        entries = [entries]
    found: list[str] = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("file") is not None:
            found.append(str(entry["file"]))
    return found


def _listed(references: list[str], reference: str) -> bool:
    return any(item == reference or item.endswith("/" + reference) or item.endswith(reference) for item in references)


@dataclass
class Planned:
    """What one library's generated files need: the file edits, config.yml's text after its entries, and the hashes."""

    edits: list[Edit]  # generated files only; config.yml is the caller's
    config_text: str
    generated: dict[str, str] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)


def plan_library(
    writer: ConfigWriter,
    kometa_root: Path,
    library: str,
    library_type: str,
    picks: dict[str, list[Ref]],
    all_libraries: list[str],
    config_text: str,
    built: list[tuple[str, dict]] | None = None,
) -> Planned:
    """``write_library`` without the save: the generated-file edits for ``library``, and ``config_text`` with its entries.

    Several libraries can be planned one after another, each from the last one's ``config_text``, and saved in one go
    (Switch over does this, so a move from Kometa lands whole or not at all).
    """
    if library not in all_libraries:
        all_libraries = [*all_libraries, library]
    prefix = _studio_prefix(library, all_libraries)
    edits: list[Edit] = []
    active_rels: dict[str, str] = {}  # category → relative path still referenced
    generated: dict[str, str] = {}
    removed: list[str] = []

    for category, refs in sorted(picks.items()):
        if not refs or category == col.BUILT:
            continue
        source = default_file(kometa_root, category, library_type)
        if source is None:
            raise SaveRefused(409, f"Kometa has no {category!r} default for {library_type} libraries")
        text = render(source.read_text(encoding="utf-8"), category, refs)
        if text is None:
            continue
        rel = relative_path(library, category, all_libraries)
        active_rels[category] = rel
        generated[rel] = file_hash(text.encode("utf-8"))
        path = writer.config_dir / rel
        current = path.read_bytes() if path.is_file() else None
        if current is not None and current.decode("utf-8") == text:
            continue
        edits.append(Edit(rel, text, file_hash(current) if current is not None else None))

    built_text = render_built(built or [], file_ref=lambda path: writer.reference(writer.config_dir / path), library_type=library_type)
    if built_text is not None:
        rel = relative_path(library, col.BUILT, all_libraries)
        active_rels[col.BUILT] = rel
        generated[rel] = file_hash(built_text.encode("utf-8"))
        path = writer.config_dir / rel
        current = path.read_bytes() if path.is_file() else None
        if current is None or current.decode("utf-8") != built_text:
            edits.append(Edit(rel, built_text, file_hash(current) if current is not None else None))

    new_config = config_text
    listed = _file_entries(new_config, library)

    for category, rel in active_rels.items():
        reference = writer.reference(writer.config_dir / rel)
        if not _listed(listed, reference) and not _listed(listed, rel):
            new_config = with_library_file(new_config, library, "collection_files", reference)
            listed.append(reference)

    # Drop studio-folder entries whose category no longer has picks (file stays on disk).
    for reference in list(_file_entries(new_config, library)):
        # Match paths that point at this library's studio folder, by relative or Kometa-root form.
        if f"/{prefix}" not in f"/{reference}" and not reference.startswith(prefix):
            continue
        name = Path(reference).stem
        if name in active_rels:
            continue
        new_config = without_library_file(new_config, library, "collection_files", reference)

    # Generated files of categories with no picks left: config.yml no longer lists them, so they go.
    folder = writer.config_dir / prefix
    if folder.is_dir():
        for path in sorted(folder.glob("*.yml")):
            if path.stem in active_rels:
                continue
            data = path.read_bytes()
            if not is_generated(data.decode("utf-8", errors="replace")):
                continue
            rel = writer.relative(path)
            edits.append(Edit(rel, None, file_hash(data)))
            removed.append(rel)
    return Planned(edits, new_config, generated, removed)


def config_edit(writer: ConfigWriter, original: str, text: str) -> Edit | None:
    """The config.yml edit from ``original`` (as read) to ``text``, or None when nothing changed."""
    if text == original:
        return None
    return Edit(writer.relative(writer.config_path), text, file_hash(original.encode("utf-8")))


def read_config(writer: ConfigWriter) -> str:
    if not writer.config_path.is_file():
        raise SaveRefused(409, "config.yml doesn't exist yet")
    return writer.config_path.read_text(encoding="utf-8")


async def write_library(
    writer: ConfigWriter,
    kometa_root: Path,
    library: str,
    library_type: str,
    picks: dict[str, list[Ref]],
    all_libraries: list[str],
    reason: str,
    built: list[tuple[str, dict]] | None = None,
) -> Written:
    """Write every category file for ``library`` and update config.yml in one ``ConfigWriter.save``.

    A hand-edited generated file is replaced like any other. A generated file whose category has no picks
    left is removed (backed up first, like every save); files in the folder that Studio didn't write stay.
    """
    original = read_config(writer)
    planned = plan_library(writer, kometa_root, library, library_type, picks, all_libraries, original, built)
    edits = list(planned.edits)
    change = config_edit(writer, original, planned.config_text)
    if change is not None:
        edits.append(change)
    if not edits:
        return Written(None, planned.generated, planned.removed)
    return Written(await writer.save(edits, reason), planned.generated, planned.removed)


async def write_from_db(
    writer: ConfigWriter,
    kometa_root: Path,
    db: sqlite3.Connection,
    library: str,
    library_type: str,
    all_libraries: list[str],
    reason: str,
) -> Written:
    """``write_library`` with everything Studio wants for ``library``: ready-made picks and builder collections."""
    return await write_library(
        writer, kometa_root, library, library_type, col.desired(db, library), all_libraries, reason, built=col.built_definitions(db, library)
    )
