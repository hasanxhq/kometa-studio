"""Moving over from Kometa (phase 4), steps 3: Switch over, Undo and Export.

Switch over acts on the import report (``kometa_import``):

1. A full backup first, copied to ``<data dir>/switch-over/`` so pruning never removes it (Undo is kept for good).
2. Imported collections become builder rows, and ``default:`` entries become Ready-made picks.
3. One ``ConfigWriter.save`` for every library: the replaced entries leave config.yml, Studio's generated files and
   their entries come in. Kometa's check runs on the result; if it refuses, the rows are taken back and nothing
   changed on disk.
4. One Kometa run of just those collections. Kometa adopts each existing Plex collection by its title, so nothing is
   rebuilt from scratch: the collections gain the ``Studio`` label.

Undo puts Kometa's files back exactly as they were at the backup, and Studio's collection rows with them (so
``generated_sync`` doesn't write Studio's files back). What it would throw away is shown first. Collections Studio
built in Plex after the switch-over can be deleted too (only ``Studio``-labelled ones, by the caller). A full backup
is taken before Undo as well, so Undo itself can be undone from System → Backup.

Export is a zip of a working Kometa setup: config.yml and every local file it lists, including Studio's own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import shutil
import sqlite3
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import collections as col
from . import full_backup, studio_files
from .config_sections import without_library_entry
from .config_write import ConfigWriter, SaveRefused
from .kometa_files import ConfigReader
from .runner import now

log = logging.getLogger(__name__)

FOLDER = "switch-over"
EXPORTS = "exports"
KEEP_EXPORTS = 3
POSTERS = "studio/posters"
RESTORED_TABLES = ("collections", "generated_files")
# The full backup Switch over and Undo take leaves the normal rotation alone: the scheduled task prunes as usual.
NO_PRUNE = 10_000
EXPORT_README = """Starr Studio export, made {created}.

A working Kometa setup: config.yml and every local file it lists, including the
files Studio writes (studio/). Files from outside Kometa's config folder are
under outside/. Put them in a Kometa config folder to run Kometa without Studio.

config.yml holds your Plex token and other API keys. Keep this zip private.
"""


class SwitchRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --- What the report asks for -----------------------------------------------------------------------


@dataclass
class LibraryPlan:
    name: str
    type: str
    imported: list[tuple[str, dict]] = field(default_factory=list)  # (title, definition)
    picks: list[col.Pick] = field(default_factory=list)  # Ready-made
    drop: list[tuple[str, str]] = field(default_factory=list)  # config.yml entries to take out: (kind, value)

    @property
    def empty(self) -> bool:
        return not self.imported and not self.picks


def plan(report: dict) -> list[LibraryPlan]:
    """The libraries Switch over changes, from the import report: only files whose action is ``replace``."""
    out = []
    for library in report.get("libraries", []):
        if library.get("error") or library.get("type") not in ("movie", "show"):
            continue
        item = LibraryPlan(library["name"], library["type"])
        for entry in library.get("files", []):
            if entry.get("action") != "replace":
                continue
            if entry["kind"] == "default" and entry.get("ready_made"):
                category = entry["ready_made"]["category"]
                for pick in entry["ready_made"].get("entries", []):
                    item.picks.append(col.Pick(col.Ref(category, pick["block"], pick["key"]), pick["kometa_name"], pick["title"]))
            elif entry["kind"] == "file":
                for landing in entry.get("collections", []):
                    if landing["result"] == "imported" and landing.get("definition"):
                        item.imported.append((landing["name"], landing["definition"]))
            else:
                continue
            item.drop.append((entry["kind"], entry["value"]))
        if not item.empty:
            out.append(item)
    return out


# --- Switch over --------------------------------------------------------------------------------------


def active(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM switch_overs WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()


def describe(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    summary = json.loads(row["summary"])
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "backup": row["backup"],
        "imported": summary.get("imported", 0),
        "ready_made": summary.get("ready_made", 0),
        "kept": summary.get("kept", 0),
        "libraries": summary.get("libraries", []),
        "run_id": row["run_id"],
    }


def _image_ext(data: bytes) -> str | None:
    from .builder_routes import _image_type

    found = _image_type(data)
    return found[0] if found else None


def _materialise_poster(definition: dict, config_dir: Path, copied: list[Path]) -> dict:
    """A poster file from the user's setup becomes one of Studio's own (``studio/posters/<sha16>.<ext>``)."""
    poster = definition.get("poster")
    if not isinstance(poster, dict) or poster.get("kind") != "import":
        return definition
    try:
        data = Path(poster["path"]).read_bytes()
    except OSError:
        return {**definition, "poster": None}
    ext = _image_ext(data)
    if ext is None:
        return {**definition, "poster": None}
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    target = config_dir / POSTERS / name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        copied.append(target)
    return {**definition, "poster": {"kind": "file", "path": f"{POSTERS}/{name}"}}


def insert_imported(
    db: sqlite3.Connection,
    config_dir: Path,
    library: str,
    imported: list[tuple[str, dict]],
    copied: list[Path] | None = None,
) -> list[int]:
    """Builder rows for imported ``(title, definition)`` pairs; posters become Studio's. Returns new row ids."""
    created: list[int] = []
    paths = copied if copied is not None else []
    for title, definition in imported:
        definition = _materialise_poster(definition, config_dir, paths)
        created.append(col.insert_built(db, library, secrets.token_hex(6), title, definition))
    return created


def _backup(config_dir: Path, data_dir: Path, db_path: Path) -> str:
    """A full backup, copied where pruning can't reach it. Returns the copy's name."""
    entry = full_backup.create(config_dir, data_dir, db_path, NO_PRUNE)
    source = data_dir / full_backup.FOLDER / entry["name"]
    dest = data_dir / FOLDER
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest / entry["name"])
    return entry["name"]


async def switch_over(
    db: sqlite3.Connection,
    writer: ConfigWriter,
    kometa_root: Path,
    data_dir: Path,
    db_path: Path,
    report: dict,
    all_libraries: list[str],
) -> tuple[dict, list[tuple[str, list[str]]], list[int]]:
    """Do it. Returns (the switch-over as ``describe`` gives it, [(library, kometa names to run)], row ids).

    Raises SwitchRefused when there's nothing to do or a switch-over is already active, and SaveRefused when
    Kometa's check refuses the result (nothing is changed then, apart from the backup).
    """
    if active(db) is not None:
        raise SwitchRefused(409, "Studio has already switched over. Undo it on System → Backup first.")
    libraries = plan(report)
    if not libraries:
        raise SwitchRefused(409, "Nothing to move over: no collection in Kometa's files can be imported yet.")

    backup = await asyncio.to_thread(_backup, writer.config_dir, data_dir, db_path)

    created: list[int] = []
    copied: list[Path] = []
    try:
        with db:
            for library in libraries:
                created += insert_imported(db, writer.config_dir, library.name, library.imported, copied)
                if library.picks:
                    existing = {
                        (row["category"], row["block"], row["key"])
                        for row in db.execute("SELECT category, block, key FROM collections WHERE library = ?", (library.name,))
                    }
                    ids = col.mark_present(db, library.name, library.picks)
                    created += [row_id for row_id, pick in zip(ids, library.picks) if (pick.ref.category, pick.ref.block, pick.ref.key) not in existing]

        original = studio_files.read_config(writer)
        text = original
        for library in libraries:
            for kind, value in library.drop:
                text = without_library_entry(text, library.name, "collection_files", kind, value)
        edits = []
        written = studio_files.Written(None)
        for library in libraries:
            planned = studio_files.plan_library(
                writer, kometa_root, library.name, library.type, col.desired(db, library.name), all_libraries, text, built=col.built_definitions(db, library.name)
            )
            text = planned.config_text
            edits += planned.edits
            written.generated.update(planned.generated)
            written.removed += planned.removed
        change = studio_files.config_edit(writer, original, text)
        if change is not None:
            edits.append(change)
        imported = sum(len(library.imported) for library in libraries)
        ready = sum(len(library.picks) for library in libraries)
        written.saved = await writer.save(edits, f"Switched over from Kometa: {imported} collections imported, {ready} Ready-made")
    except BaseException:
        with db:
            col.delete_rows(db, created)
        for path in copied:
            path.unlink(missing_ok=True)
        raise

    summary = {
        "imported": imported,
        "ready_made": ready,
        "kept": report.get("summary", {}).get("kept", 0),
        "libraries": [library.name for library in libraries],
    }
    with db:
        studio_files.record(db, written)
        cursor = db.execute(
            "INSERT INTO switch_overs (created_at, backup, summary, created_rows) VALUES (?, ?, ?, ?)",
            (now(), backup, json.dumps(summary), json.dumps(created)),
        )
    row = db.execute("SELECT * FROM switch_overs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    runs = []
    for library in libraries:
        names = [title for title, _ in library.imported] + [pick.kometa_name for pick in library.picks]
        runs.append((library.name, names))
    log.info("Switched over from Kometa: %s imported, %s Ready-made, backup %s", imported, ready, backup)
    return describe(row), runs, created


def set_run(db: sqlite3.Connection, switch_id: int, run_id: int) -> None:
    db.execute("UPDATE switch_overs SET run_id = ? WHERE id = ?", (run_id, switch_id))


# --- Undo ---------------------------------------------------------------------------------------------


def _backup_path(data_dir: Path, name: str) -> Path:
    path = data_dir / FOLDER / name
    if not path.is_file() or not full_backup.NAME.match(name):
        raise SwitchRefused(409, f"The backup taken at the switch-over ({name}) is missing, so Undo can't put the files back")
    return path


def _backup_rows(archive: zipfile.ZipFile, scratch: Path) -> sqlite3.Connection:
    target = scratch / "studio.db"
    with archive.open("studio/studio.db") as source, open(target, "wb") as out:
        shutil.copyfileobj(source, out)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def _key(row: sqlite3.Row) -> tuple:
    return (row["library"], row["category"], row["block"], row["key"])


# What someone sets on a collection. The rest (plex_*, last_*, updated_at …) is Studio's own bookkeeping, which moves
# every time a run finishes or Plex is checked: a change there isn't something Undo would lose.
USER_COLUMNS = ("kometa_name", "title", "origin", "desired", "run_scope", "definition", "download_missing", "request_cap", "request_profile")


def _settings(row: sqlite3.Row, columns: list[str]) -> tuple:
    return tuple(row[name] for name in columns)


def adopted(db: sqlite3.Connection, row: sqlite3.Row) -> list[dict]:
    """The collections the switch-over moved into Studio ({library, title}): its run labelled them Studio in Plex."""
    created = json.loads(row["created_rows"])
    if not created:
        return []
    marks = ",".join("?" * len(created))
    return [
        {"library": r["library"], "title": r["kometa_name"]}
        for r in db.execute(f"SELECT library, kometa_name FROM collections WHERE id IN ({marks}) ORDER BY library, kometa_name", created)
    ]


def preview(db: sqlite3.Connection, data_dir: Path, config_dir: Path, row: sqlite3.Row) -> dict:
    """What Undo would throw away, the files it would put back (only those that changed) and Studio's files it removes."""
    path = _backup_path(data_dir, row["backup"])
    created = set(json.loads(row["created_rows"]))
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as scratch:
        then_db = _backup_rows(archive, Path(scratch))
        try:
            had = {r[1] for r in then_db.execute("PRAGMA table_info(collections)")}
            columns = [name for name in USER_COLUMNS if name in had]  # a backup from before a column existed
            then = {_key(r): _settings(r, columns) for r in then_db.execute("SELECT * FROM collections")}
        finally:
            then_db.close()
        files = sorted(
            info.filename[len("config/"):]
            for info in archive.infolist()
            if info.filename.startswith("config/") and not info.is_dir() and _differs(config_dir / info.filename[len("config/"):], info)
        )
    added, changed, plex = [], [], []
    for current in db.execute("SELECT * FROM collections ORDER BY library, title"):
        key = _key(current)
        entry = {"library": current["library"], "title": current["title"]}
        if key not in then:
            if current["id"] in created:
                continue  # what the switch-over itself added: that's what Undo takes away
            added.append(entry)
            if current["plex_exists"]:
                plex.append(entry)
        elif _settings(current, columns) != then[key]:
            changed.append(entry)
    removed = [
        rel for rel in _studio_files(config_dir) if rel not in set(files)
    ]
    return {"loses": {"added": added, "changed": changed}, "plex": plex, "unlabels": adopted(db, row), "files": files, "removes": removed}


def _differs(path: Path, info: zipfile.ZipInfo) -> bool:
    """Whether Undo would change ``path``: it's gone, or its bytes aren't the backup's (size, then CRC-32)."""
    try:
        if path.stat().st_size != info.file_size:
            return True
        crc = 0
        with open(path, "rb") as handle:
            while chunk := handle.read(1 << 20):
                crc = zlib.crc32(chunk, crc)
        return crc != info.CRC
    except OSError:
        return True


def _studio_files(config_dir: Path) -> list[str]:
    folder = config_dir / "studio"
    if not folder.is_dir():
        return []
    return sorted(path.relative_to(config_dir).as_posix() for path in folder.rglob("*") if path.is_file())


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _restore_rows(db: sqlite3.Connection, then_db_path: Path) -> None:
    """Studio's collection rows and generated-file hashes as they were at the backup (columns both schemas have)."""
    db.commit()  # ATTACH can't run inside a transaction
    db.execute("ATTACH DATABASE ? AS before_switch", (str(then_db_path),))
    try:
        for table in RESTORED_TABLES:
            now_cols = [r["name"] for r in db.execute(f"PRAGMA main.table_info({table})")]
            then_cols = {r["name"] for r in db.execute(f"PRAGMA before_switch.table_info({table})")}
            cols = ", ".join(c for c in now_cols if c in then_cols)
            db.execute(f"DELETE FROM main.{table}")
            if cols:
                db.execute(f"INSERT INTO main.{table} ({cols}) SELECT {cols} FROM before_switch.{table}")
    finally:
        db.commit()
        db.execute("DETACH DATABASE before_switch")


def restore_files(data_dir: Path, config_dir: Path, db_path: Path, backup: str, scratch: Path) -> tuple[int, str, Path]:
    """Undo's file half (blocking: run it in a thread): a full backup first, then Kometa's files as they were at
    ``backup``. Returns (files put back or removed, the safety backup's name, the backup's studio.db in ``scratch``).
    Studio's database is restored by ``restore_rows`` on the event loop, where the shared connection lives."""
    path = _backup_path(data_dir, backup)
    safety = full_backup.create(config_dir, data_dir, db_path, NO_PRUNE)
    restored = 0
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.startswith("config/") and not name.endswith("/")]
        keep = {name[len("config/"):] for name in names}
        for name in names:
            rel = name[len("config/"):]
            target = (config_dir / rel).resolve()
            if not target.is_relative_to(config_dir.resolve()):
                continue  # never write outside Kometa's config folder
            data = archive.read(name)
            if target.is_file() and target.read_bytes() == data:
                continue
            _write_atomic(target, data)
            restored += 1
        for rel in _studio_files(config_dir):
            if rel not in keep:
                (config_dir / rel).unlink(missing_ok=True)
                restored += 1
        then_db = scratch / "studio.db"
        with archive.open("studio/studio.db") as source, open(then_db, "wb") as out:
            shutil.copyfileobj(source, out)
    return restored, safety["name"], then_db


def finish_undo(db: sqlite3.Connection, row: sqlite3.Row, then_db: Path, restored: int, safety: str) -> dict:
    """Undo's database half: Studio's collection rows as they were, and the switch-over marked undone."""
    _restore_rows(db, then_db)
    with db:
        db.execute("UPDATE switch_overs SET undone_at = ?, undo_backup = ? WHERE id = ?", (now(), safety, row["id"]))
    log.info("Undid the switch-over from %s: %s files put back; backup before Undo %s", row["created_at"], restored, safety)
    return {"restored_files": restored, "backup": safety}


# --- Export -------------------------------------------------------------------------------------------


def export(reader: ConfigReader, data_dir: Path) -> Path:
    """A zip of a working Kometa setup: config.yml, every local file it lists, and Studio's own files."""
    config_dir = reader.config_path.parent
    config = reader.read()
    paths: set[Path] = {reader.config_path}
    references = [*config.playlist_files]
    for library in config.libraries:
        references += [*library.collection_files, *library.overlay_files, *library.metadata_files]
    for reference in references:
        if reference.kind == "file":
            paths.add(reader._local(reference.value))
        elif reference.kind == "folder":
            folder = reader._local(reference.value)
            if folder.is_dir():
                paths.update(p for p in folder.rglob("*") if p.is_file())
    studio = config_dir / "studio"
    if studio.is_dir():
        paths.update(p for p in studio.rglob("*") if p.is_file())

    dest = data_dir / EXPORTS
    dest.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC)
    target = dest / f"starr-studio-export-{created:%Y%m%d-%H%M%S}.zip"
    partial = target.with_name(target.name + ".partial")
    used: set[str] = set()
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", EXPORT_README.format(created=created.strftime("%Y-%m-%d %H:%M UTC")))
            for path in sorted(paths):
                if not path.is_file():
                    continue
                try:
                    arcname = path.resolve().relative_to(config_dir.resolve()).as_posix()
                except ValueError:
                    arcname = f"outside/{path.name}"
                    stem, n = arcname, 2
                    while arcname in used:
                        arcname = f"{stem}.{n}"
                        n += 1
                used.add(arcname)
                archive.write(path, arcname)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    for old in sorted(dest.glob("starr-studio-export-*.zip"))[:-KEEP_EXPORTS]:
        old.unlink(missing_ok=True)
    return target


def history(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return [describe(row) | {"undone_at": row["undone_at"]} for row in db.execute("SELECT * FROM switch_overs ORDER BY id DESC")]
