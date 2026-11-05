"""/api/v1/logs: Kometa's own log files (meta.log, and per library and collection), for System → Logs.

Kometa writes lines like ``[2026-10-30 04:00:01,123] kometa.py   INFO       | message |``; lines that
continue an entry (wrapped tables, tracebacks) start with spaces and belong to the entry above,
so they take its level when filtering. Only the end of a big file is read.
"""

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .settings import Settings

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LINE_LEVEL = re.compile(r"^\[\d{4}-\d\d-\d\d [\d:,.]+\] \S+\s+\[?(TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)\]?\s")
LOG_NAME = re.compile(r"\.log(\.\d+)?$")
TAIL_BYTES = 2 * 1024 * 1024


def logs_dir(request: Request) -> Path:
    settings: Settings = request.app.state.settings
    if settings.kometa_config is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config folder is. Set STUDIO_KOMETA_CONFIG.")
    return settings.kometa_config.parent / "logs"


def _resolve(folder: Path, path: str) -> Path:
    target = (folder / path).resolve()
    if not target.is_relative_to(folder.resolve()) or not target.is_file() or not LOG_NAME.search(target.name):
        raise HTTPException(404, "No such log")
    return target


@router.get("")
async def list_logs(request: Request) -> dict:
    folder = logs_dir(request)
    if not folder.is_dir():
        return {"files": []}
    found = []
    for path in folder.rglob("*"):
        if path.is_file() and not path.is_symlink() and LOG_NAME.search(path.name):
            stat = path.stat()
            found.append({"path": path.relative_to(folder).as_posix(), "size": stat.st_size, "modified": stat.st_mtime})
    # meta.log first (it's the one people want), then the rest, newest first.
    found.sort(key=lambda f: (f["path"] != "meta.log", -f["modified"]))
    return {"files": found}


def read_entries(path: Path) -> tuple[list[tuple[str, str]], bool]:
    """(level, line) for the end of a log, and whether the start was cut off."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > TAIL_BYTES:
            handle.seek(size - TAIL_BYTES)
            handle.readline()  # drop the partial first line
        text = handle.read().decode("utf-8", errors="replace")
    entries, level = [], "INFO"
    for line in text.splitlines():
        match = LINE_LEVEL.match(line)
        if match:
            level = match.group(1)
        entries.append((level, line))
    return entries, size > TAIL_BYTES


@router.get("/file")
async def read_log(
    request: Request,
    path: str,
    level: str = "INFO",
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=20_000)] = 2000,
) -> dict:
    if level not in LEVELS:
        raise HTTPException(422, f"level is one of {', '.join(LEVELS)}")
    target = _resolve(logs_dir(request), path)
    entries, truncated = read_entries(target)
    floor = LEVELS.index(level)
    needle = q.lower()
    kept = [{"level": lvl, "text": text} for lvl, text in entries if LEVELS.index(lvl) >= floor and needle in text.lower()]
    return {"path": path, "lines": kept[-limit:], "truncated": truncated or len(kept) > limit, "size": target.stat().st_size}


@router.get("/download")
async def download_log(request: Request, path: str) -> FileResponse:
    target = _resolve(logs_dir(request), path)
    return FileResponse(target, media_type="text/plain; charset=utf-8", filename=target.name)
