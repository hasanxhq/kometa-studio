"""Which imports matter to Kometa: Studio's copy of what Kometa's collections want (feedback round 1).

An import from Radarr or Sonarr needs a Kometa run only if something in its library could change.
For each library, Studio reads the files config.yml points at (locally, no network) and sorts the
collections, looking inside their templates too:

- smart: built only with ``smart_filter``. Plex keeps these up to date by itself.
- rule-based: built from Plex searches (``plex_search``, ``plex_all``, …), or Studio can't see what
  they're built from. Any new item may match, and nobody can say which beforehand, so every import counts.
- list-based: everything else (TMDb, IMDb, MDBList, Letterboxd, charts, …). Kometa works out who is
  on each list during a run, and with ``save_report`` on it writes ``<library>_report.yml``: per
  collection, the items it wants that Plex doesn't have yet. Kometa starts that file afresh on every
  run, so Studio keeps its own merged copy (the ``wanted`` table), updated after each run that went
  through to ``run_end``.
- IDs written in a collection (``tmdb_movie``, ``tmdb_show``, ``tvdb_show``) are read directly.

An import is relevant to a library when the run would touch every item anyway (overlays, operations
or metadata files are part of it), when a rule-based collection could catch it, when Studio can't
tell (a file it can't read, the report off, or the collection files changed since Kometa last
reported on all of them), or when a collection wants it. Only the last lets the run be narrowed to
the collections that want it.

Items are keyed by where their ID comes from: ``tmdb-movie:603``, ``tmdb-show:1399``, ``tvdb:81189``.
"""

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .kometa_command import RunRequest
from .kometa_files import ConfigReader, Reference, _is_builder

RULE_BUILDERS = {"plex_search", "plex_all", "plex_pilots", "plex_collectionless"}
ID_BUILDERS = {"tmdb_movie": "tmdb-movie", "tmdb_show": "tmdb-show", "tvdb_show": "tvdb"}
REPORT_SECTIONS = {"Movies Missing (TMDb IDs)": "tmdb-movie", "Shows Missing (TVDb IDs)": "tvdb"}
MODE_PARTS = {
    "all": {"collections", "overlays", "operations", "metadata"},
    "collections": {"collections"},
    "overlays": {"overlays"},
    "operations": {"operations"},
    "metadata": {"metadata"},
    "playlists": set(),
}
BAD_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')  # what Kometa strips from a library's name for its files


def _load(path: Path) -> Any:
    try:
        return YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError, UnicodeDecodeError):
        return None


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


@dataclass
class LibraryPlan:
    """What Studio can tell about one library from its files."""

    name: str
    plex_name: str  # the Plex library's title (config.yml's `library_name`, else the name)
    overlays: bool = False
    operations: bool = False
    metadata: bool = False
    rule: list[str] = field(default_factory=list)  # collections an import may join without being on a list
    lists: list[str] = field(default_factory=list)  # collections whose members Kometa's report tells
    scheduled: set[str] = field(default_factory=set)  # collections with their own schedule: a run may skip them
    ids: dict[str, list[str]] = field(default_factory=dict)  # item -> collections that name it by ID
    unreadable: list[str] = field(default_factory=list)
    reports: bool = False  # save_report is on for this library
    report_path: Path | None = None
    fingerprint: str = ""


def _template_names(body: dict) -> list[str]:
    templates = body.get("template")
    if templates is None:
        return []
    if not isinstance(templates, list):
        templates = [templates]
    return [str(t.get("name")) if isinstance(t, dict) else str(t) for t in templates if t]


def classify(body: Any, templates: dict) -> str:
    """smart, rule or list, from the collection's keys and those of the templates it uses."""
    body = _mapping(body)
    keys = {str(key) for key in body}
    for name in _template_names(body):
        keys |= {str(key) for key in _mapping(templates.get(name))}
    if keys & RULE_BUILDERS:
        return "rule"
    builders = {key for key in keys if _is_builder(key)}
    if not builders:
        return "rule"  # built from something Studio can't see (a dynamic collection's default, an unknown template)
    if builders <= {"smart_filter"}:
        return "smart"
    return "list"


def _ids(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [found for item in values for found in re.findall(r"\d+", str(item))]


def _paths(reader: ConfigReader, reference: Reference) -> list[Path] | None:
    """The local files of a collection_files entry, or None if Studio can't read them."""
    if reference.error or reference.kind in ("url", "git", "repo"):
        return None
    if reference.kind == "folder":
        folder = reader._local(reference.value)
        return sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")])
    path = reader._default(reference.value, False) if reference.kind == "default" else reader._local(reference.value)
    return [path] if path is not None and path.is_file() else None


def plan(config: Path, kometa_root: Path | None) -> dict[str, LibraryPlan]:
    """Every library in config.yml, sorted out. Raises FileNotFoundError or ValueError like ConfigReader."""
    reader = ConfigReader(config, kometa_root)
    kometa = reader.read()
    raw = _mapping(_load(config))
    settings = _mapping(raw.get("settings"))
    report_default = bool(settings.get("save_report", settings.get("save_missing", False)))
    shared = _mapping(_mapping(_load(reader.defaults / "templates.yml")).get("templates"))
    plans = {}
    for library in kometa.libraries:
        body = _mapping(_mapping(raw.get("libraries")).get(library.name))
        own_settings = _mapping(body.get("settings"))
        found = LibraryPlan(
            library.name,
            str(body.get("library_name") or library.name),
            overlays=bool(library.overlay_files),
            operations=bool(library.operations),
            metadata=bool(library.metadata_files),
            reports=bool(own_settings.get("save_report", own_settings.get("save_missing", report_default))),
            report_path=Path(str(body["report_path"])) if body.get("report_path") else config.parent / f"{BAD_FILENAME.sub('', library.name)}_report.yml",
        )
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode())
        for reference in library.collection_files:
            paths = _paths(reader, reference)
            if paths is None:
                found.unreadable.append(f"{reference.kind}: {reference.value}")
                continue
            for path in paths:
                data = _load(path)
                if not isinstance(data, dict):
                    found.unreadable.append(str(path.name))
                    continue
                digest.update(path.read_bytes())
                templates = shared | _mapping(data.get("templates"))
                for key in ("collections", "dynamic_collections"):
                    for name, collection in _mapping(data.get(key)).items():
                        name = str(name)
                        kind = classify(collection, templates)
                        if kind == "rule":
                            found.rule.append(name)
                        elif kind == "list":
                            found.lists.append(name)
                        if _mapping(collection).get("schedule"):
                            found.scheduled.add(name)
                        for builder, prefix in ID_BUILDERS.items():
                            for item_id in _ids(_mapping(collection).get(builder)):
                                found.ids.setdefault(f"{prefix}:{item_id}", []).append(name)
        found.fingerprint = digest.hexdigest()
        plans[library.name] = found
    return plans


# --- Deciding -----------------------------------------------------------------------


@dataclass
class Decision:
    library: str
    whole: bool  # the whole library needs a run, not only the collections that want the item
    collections: list[str]  # collections that want it
    reason: str


def _names(names: Iterable[str], most: int = 3) -> str:
    names = list(names)
    shown = ", ".join(f"“{name}”" for name in names[:most])
    return shown + (f" and {len(names) - most} more" if len(names) > most else "")


def wanting(db: sqlite3.Connection, library: LibraryPlan, items: list[str]) -> list[str]:
    """Collections of the library that want any of these items."""
    names = {name for item in items for name in library.ids.get(item, [])}
    if items:
        marks = ",".join("?" * len(items))
        rows = db.execute(f"SELECT DISTINCT collection FROM wanted WHERE library = ? AND item IN ({marks})", (library.name, *items))
        names |= {row[0] for row in rows}
    return sorted(names)


def decide(db: sqlite3.Connection, library: LibraryPlan, mode: str, items: list[str]) -> Decision | None:
    """Whether an import of ``items`` matters to this library in a run of ``mode``; None if it doesn't."""
    parts = MODE_PARTS.get(mode, MODE_PARTS["all"])
    reasons = []
    if "overlays" in parts and library.overlays:
        reasons.append("its overlays need drawing")
    if "operations" in parts and library.operations:
        reasons.append("its operations apply to new items")
    if "metadata" in parts and library.metadata:
        reasons.append("its metadata files may name it")
    if "collections" in parts:
        if library.unreadable:
            reasons.append(f"Studio can't read {library.unreadable[0]}")
        if library.rule:
            reasons.append(f"{_names(library.rule)} {'search' if len(library.rule) > 1 else 'searches'} Plex")
        if library.lists:
            row = db.execute("SELECT fingerprint FROM wanted_libraries WHERE library = ?", (library.name,)).fetchone()
            if not library.reports:
                reasons.append("Kometa's missing report is off")
            elif row is None:
                reasons.append("Kometa hasn't reported on its collections yet")
            elif row[0] != library.fingerprint:
                reasons.append("its collection files changed since Kometa's last report")
    wants = wanting(db, library, items) if "collections" in parts else []
    if reasons:
        return Decision(library.name, True, wants, "; ".join(reasons))
    if wants:
        return Decision(library.name, False, wants, f"wanted by {_names(wants)}")
    return None


def narrowed(mode: str, libraries: dict[str, dict]) -> RunRequest:
    """The run for pending decisions ({library: {whole, collections}}): whole libraries, or just the collections that want something."""
    names = sorted(libraries)
    if any(entry["whole"] for entry in libraries.values()):
        return RunRequest(mode=mode, libraries=names)
    collections = sorted({name for entry in libraries.values() for name in entry["collections"]})
    return RunRequest(mode="collections", libraries=names, collections=collections)


# --- Kometa's report ----------------------------------------------------------------


def read_report(path: Path) -> dict[str, dict[str, str]]:
    """{collection: {item: title}} from Kometa's report: what each collection wants that Plex doesn't have."""
    found: dict[str, dict[str, str]] = {}
    for collection, sections in _mapping(_load(path)).items():
        for section, prefix in REPORT_SECTIONS.items():
            for item_id, title in _mapping(_mapping(sections).get(section)).items():
                found.setdefault(str(collection), {})[f"{prefix}:{item_id}"] = str(title)
    return found


def ingest(db: sqlite3.Connection, plans: dict[str, LibraryPlan], request: RunRequest, started: float, run_id: int | None, now: datetime) -> list[str]:
    """Merge the reports of a run that went through into Studio's copy. Returns the libraries it updated.

    A collection that ran and isn't in the report wants nothing. A full pass over a library's
    collections (no collection filter) also records the files' fingerprint, so later imports trust
    the copy until the files change.
    """
    if "collections" not in MODE_PARTS.get(request.mode, set()) or request.no_missing:
        return []
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = []
    for library in plans.values():
        if (request.libraries and library.name not in request.libraries) or not library.lists or not library.reports or library.report_path is None:
            continue
        fresh = library.report_path.is_file() and library.report_path.stat().st_mtime >= started
        report = read_report(library.report_path) if fresh else {}  # not rewritten: nothing was missing
        full = not request.collections
        with db:
            if full:
                kept = set() if request.ignore_schedules else library.scheduled
                rows = db.execute("SELECT DISTINCT collection FROM wanted WHERE library = ?", (library.name,))
                cleared = {row[0] for row in rows} - kept
            else:
                cleared = set(request.collections)
            for collection in cleared | set(report):
                db.execute("DELETE FROM wanted WHERE library = ? AND collection = ?", (library.name, collection))
            for collection, items in report.items():
                db.executemany(
                    "INSERT OR REPLACE INTO wanted (library, collection, item, title, seen_at) VALUES (?, ?, ?, ?, ?)",
                    [(library.name, collection, item, title, stamp) for item, title in items.items()],
                )
            if full:
                db.execute(
                    "INSERT OR REPLACE INTO wanted_libraries (library, fingerprint, reported_at, run_id) VALUES (?, ?, ?, ?)",
                    (library.name, library.fingerprint, stamp, run_id),
                )
        updated.append(library.name)
    return updated


def summary(db: sqlite3.Connection, plans: dict[str, LibraryPlan]) -> list[dict]:
    """What Studio knows per library, for Settings → Connect."""
    rows = []
    for library in plans.values():
        known = db.execute("SELECT fingerprint, reported_at FROM wanted_libraries WHERE library = ?", (library.name,)).fetchone()
        count = db.execute("SELECT COUNT(DISTINCT item) FROM wanted WHERE library = ?", (library.name,)).fetchone()[0]
        rows.append(
            {
                "library": library.name,
                "reports": library.reports,
                "reported_at": known[1] if known else None,
                "changed": bool(known) and known[0] != library.fingerprint,
                "wanted": count,
                "ids": len(library.ids),
                "lists": len(library.lists),
                "rule": library.rule,
                "unreadable": library.unreadable,
                "overlays": library.overlays,
            }
        )
    return rows


class WantedRecorder:
    """Run hook: once a run has gone through to Kometa's run_end, merge its reports into Studio's copy."""

    def __init__(self, db: sqlite3.Connection, runner, config: Path | None, kometa_root: Path | None):
        self.db = db
        self.runner = runner
        self.config = config
        self.kometa_root = kometa_root

    async def before_run(self, request: RunRequest, say):
        run_id = self.runner.current_run_id
        started = time.time() - 1  # file times can be a little coarse

        async def after() -> None:
            ended = self.db.execute("SELECT 1 FROM run_events WHERE run_id = ? AND event = 'run_end'", (run_id,)).fetchone()
            if not ended or self.config is None:
                return
            try:
                plans = plan(self.config, self.kometa_root)
            except (FileNotFoundError, ValueError):
                return
            updated = ingest(self.db, plans, request, started, run_id, datetime.now(UTC))
            if updated:
                say(f"noted what the collections in {', '.join(updated)} want, for runs after imports")

        return after
