"""Full backups: one zip of Kometa's config folder and Studio's own data (handoff v2 §3.2, §8).

The zip holds ``config/`` (everything in Kometa's config folder, including each library's
``overlays/<library> Original Posters/``, Kometa's copy of the posters before overlays) and
``studio/`` (a consistent copy of studio.db and the key that decrypts its secrets). Left out:
Kometa's logs and cache (both rebuild themselves), Studio's data folder apart from the database
and key (run logs, the YAML backups, earlier full backups), and symbolic links.

Zips are written as ``*.partial`` and renamed when complete, into ``<data dir>/full-backups/``,
and the newest ``keep`` are kept. Posters are stored as they are; recompressing JPEGs gains nothing.
"""

import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .crypto import KEY_FILE

FOLDER = "full-backups"
NAME = re.compile(r"^kometa-studio-\d{8}-\d{6}\.zip$")
SKIP_TOP = {"logs"}  # Kometa's logs, at the top of its config folder
SKIP_SUFFIXES = (".cache", ".cache-journal", ".cache-wal", ".cache-shm")  # Kometa's cache database
STORED = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".zip", ".gz"}
SPARE = 50 * 1024**2  # room to leave on the disk besides the zip itself

README = """Kometa Studio full backup, made {created}.

config/  Kometa's config folder: config.yml, your collection and overlay files,
         and overlays/<library> Original Posters/ (Kometa's copies of posters
         from before its overlays). Kometa's logs and cache are left out; they
         rebuild themselves.
studio/  Studio's database (schedules, run history, settings) and secret.key,
         which decrypts the secrets in it.

This zip holds your Plex token and other API keys. Keep it somewhere private.

To restore: stop Studio, copy config/ back into Kometa's config folder and
studio/ into its .studio folder, and start Studio again.
"""


class BackupFailed(Exception):
    pass


@dataclass
class Plan:
    files: list[tuple[Path, str]]  # (path, name in the zip)
    size: int
    skipped_links: int


def plan(config_dir: Path, data_dir: Path) -> Plan:
    data = data_dir.resolve()
    files, size, links = [], 0, 0
    for root, dirs, names in os.walk(config_dir):
        here = Path(root)
        keep_dirs = []
        for name in sorted(dirs):
            path = here / name
            if path.is_symlink():
                links += 1
            elif not (here == config_dir and name in SKIP_TOP) and path.resolve() != data:
                keep_dirs.append(name)
        dirs[:] = keep_dirs
        for name in sorted(names):
            path = here / name
            if path.is_symlink():
                links += 1
                continue
            if name.endswith(SKIP_SUFFIXES):
                continue
            try:
                size += path.stat().st_size
            except OSError:
                continue
            files.append((path, "config/" + path.relative_to(config_dir).as_posix()))
    return Plan(files, size, links)


def create(config_dir: Path, data_dir: Path, db_path: Path, keep: int) -> dict:
    """Write a full backup and return its listing entry. Raises BackupFailed."""
    dest = data_dir / FOLDER
    dest.mkdir(parents=True, exist_ok=True)
    work = plan(config_dir, data_dir)
    free = shutil.disk_usage(dest).free
    if free < work.size + SPARE:
        raise BackupFailed(f"Not enough disk space: the backup needs about {_mb(work.size + SPARE)}, and {_mb(free)} is free")

    now = datetime.now(UTC)
    name = f"kometa-studio-{now:%Y%m%d-%H%M%S}.zip"
    partial = dest / (name + ".partial")
    missing = 0
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr("README.txt", README.format(created=now.strftime("%Y-%m-%d %H:%M UTC")))
            for path, arcname in work.files:
                method = zipfile.ZIP_STORED if path.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
                try:
                    archive.write(path, arcname, compress_type=method)
                except FileNotFoundError:
                    missing += 1  # Kometa removed it while the backup ran
            with tempfile.TemporaryDirectory(dir=dest) as scratch:
                copy = Path(scratch) / "studio.db"
                _copy_database(db_path, copy)
                archive.write(copy, "studio/studio.db")
            if (data_dir / KEY_FILE).is_file():
                archive.write(data_dir / KEY_FILE, "studio/" + KEY_FILE)
        os.replace(partial, dest / name)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    prune(dest, keep)
    notes = []
    if missing:
        notes.append(f"{missing} file(s) disappeared while it ran")
    if work.skipped_links:
        notes.append(f"{work.skipped_links} symbolic link(s) left out")
    entry = describe(dest / name)
    return entry | {"files": len(work.files) - missing, "notes": notes}


def _copy_database(source: Path, target: Path) -> None:
    """SQLite's own online backup: consistent even while Studio writes to it."""
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def prune(dest: Path, keep: int) -> None:
    for path in sorted(_zips(dest))[:-keep] if keep > 0 else []:
        path.unlink(missing_ok=True)


def _zips(dest: Path) -> list[Path]:
    if not dest.is_dir():
        return []
    return [path for path in dest.iterdir() if NAME.match(path.name) and path.is_file()]


def describe(path: Path) -> dict:
    created = datetime.strptime(path.name, "kometa-studio-%Y%m%d-%H%M%S.zip").replace(tzinfo=UTC)
    return {"name": path.name, "size": path.stat().st_size, "created": created.strftime("%Y-%m-%dT%H:%M:%SZ")}


def list_full(data_dir: Path) -> list[dict]:
    return [describe(path) for path in sorted(_zips(data_dir / FOLDER), reverse=True)]


def find(data_dir: Path, name: str) -> Path | None:
    """The backup called ``name``, never a path outside the folder."""
    if not NAME.match(name):
        return None
    path = data_dir / FOLDER / name
    return path if path.is_file() else None


def clean_partials(data_dir: Path) -> None:
    """Zips a restart cut off half-way."""
    folder = data_dir / FOLDER
    if folder.is_dir():
        for path in folder.glob("*.partial"):
            path.unlink(missing_ok=True)


def _mb(size: int) -> str:
    return f"{size / 1024**2:,.0f} MB"
