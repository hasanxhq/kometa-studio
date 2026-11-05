"""Backups of Kometa's YAML files, taken before Studio writes any of them (handoff v2 §7.4).

Each backup is a folder ``<data dir>/backups/<UTC timestamp>/`` holding the files as they were,
at their paths relative to the config folder, plus ``manifest.json`` saying why it was taken
and which files didn't exist yet (so restoring removes them). The newest ``KEEP`` are kept.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

KEEP = 30
MANIFEST = "manifest.json"


def take_backup(backup_root: Path, base: Path, paths: list[Path], reason: str) -> Path:
    """Copy the current versions of ``paths`` (all under ``base``) into a new backup and return its folder."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    folder = backup_root / stamp
    folder.mkdir(parents=True)
    saved, absent = [], []
    for path in paths:
        relative = path.relative_to(base).as_posix()
        if path.exists():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            saved.append(relative)
        else:
            absent.append(relative)
    manifest = {"created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "reason": reason, "files": saved, "new_files": absent}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2))
    prune(backup_root)
    return folder


def prune(backup_root: Path, keep: int = KEEP) -> None:
    for folder in sorted(_folders(backup_root))[:-keep]:
        shutil.rmtree(folder, ignore_errors=True)


def _folders(backup_root: Path) -> list[Path]:
    if not backup_root.is_dir():
        return []
    return [folder for folder in backup_root.iterdir() if folder.is_dir()]


def list_backups(backup_root: Path) -> list[dict]:
    """Newest first. Backups from before manifests existed are described from their contents."""
    found = []
    for folder in sorted(_folders(backup_root), reverse=True):
        manifest_path = folder / MANIFEST
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except ValueError:
                manifest = {}
        else:
            manifest = {}
        files = manifest.get("files") or sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.name != MANIFEST)
        found.append(
            {
                "id": folder.name,
                "created": manifest.get("created") or _created_from_name(folder.name),
                "reason": manifest.get("reason") or "Saved by Studio",
                "files": files,
                "new_files": manifest.get("new_files", []),
            }
        )
    return found


def backup_folder(backup_root: Path, backup_id: str) -> Path | None:
    """The folder for ``backup_id``, if it is one of the backups (never a path outside them)."""
    return next((folder for folder in _folders(backup_root) if folder.name == backup_id), None)


def _created_from_name(name: str) -> str | None:
    try:
        return datetime.strptime(name, "%Y%m%dT%H%M%S.%fZ").strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
