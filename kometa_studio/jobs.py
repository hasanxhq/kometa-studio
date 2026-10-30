"""/api/v1/jobs: everything Studio is doing or waiting to do, for the header's jobs drawer.

Modelled on Bazarr's Jobs Manager: jobs grouped as running, pending, failed and completed, the
finished ones capped at the newest ``KEEP_FINISHED``. Here a job is a Kometa run, one of Studio's
built-in tasks (full backup, full check), imports from Radarr/Sonarr waiting to become a run, or
Maintainerr overlays waiting to be switched back on.

A running Kometa run's message is the latest line of its log, and its progress the latest
``(12/230) Title`` line Kometa writes while it works through items, if a recent one is there.
"""

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

from . import maintainerr as maintainerr_module
from .db import get_setting
from .runner import read_tail
from .tasks import DEFAULTS

router = APIRouter(prefix="/api/v1", tags=["jobs"])

KEEP_FINISHED = 10
PROGRESS = re.compile(r"\((\d+)/(\d+)\)")
PROGRESS_RECENT = 60  # lines: older progress belongs to an earlier step
BORDER = re.compile(r"^[|=\-_~\s]*$")
MODES = {
    "all": "Everything",
    "collections": "Collections",
    "overlays": "Overlays",
    "operations": "Operations",
    "metadata": "Metadata",
    "playlists": "Playlists",
}
STATES = {  # run status → (job status, label)
    "queued": ("pending", "Queued"),
    "running": ("running", "Running"),
    "succeeded": ("completed", "Succeeded"),
    "cancelled": ("completed", "Cancelled"),
    "failed": ("failed", "Failed"),
    "timed_out": ("failed", "Timed out"),
    "interrupted": ("failed", "Interrupted"),
}


def run_title(request: dict) -> str:
    parts = [f"Kometa: {MODES.get(request.get('mode', 'all'), 'Everything')}"]
    for key in ("libraries", "collections", "files"):
        if request.get(key):
            parts.append(", ".join(request[key]))
    return " · ".join(parts)


def _clean(line: str) -> str:
    """A log line without Kometa's | … | border."""
    return line.strip().strip("|").strip()


def live_state(lines: list[str]) -> tuple[str | None, dict | None]:
    """The latest meaningful line, and the latest recent (value/max) progress."""
    message = None
    progress = None
    for age, line in enumerate(reversed(lines)):
        text = _clean(line)
        if message is None and text and not BORDER.match(text):
            message = text
        if progress is None and age < PROGRESS_RECENT:
            match = PROGRESS.search(text)
            if match and 0 < int(match.group(2)):
                progress = {"value": int(match.group(1)), "max": int(match.group(2))}
        if message is not None and (progress is not None or age >= PROGRESS_RECENT):
            break
    return message, progress


def _run_job(runner, row: sqlite3.Row, position: int | None) -> dict:
    request = json.loads(row["request"])
    status, label = STATES[row["status"]]
    message, progress = None, None
    if row["status"] == "running":
        lines, _ = read_tail(runner.log_path(row["id"]), 64 * 1024)
        message, progress = live_state(lines)
    elif row["status"] == "queued":
        message = "Next in the queue" if position == 1 else f"Number {position} in the queue"
    elif row["error"]:
        message = row["error"]
    elif row["summary"]:
        summary = json.loads(row["summary"])
        added, removed = summary.get("items_added"), summary.get("items_removed")
        if added is not None or removed is not None:
            message = f"{added or 0} items added, {removed or 0} removed"
    return {
        "id": f"run-{row['id']}",
        "kind": "run",
        "title": run_title(request),
        "status": status,
        "label": label,
        "message": message,
        "progress": progress,
        "started_at": row["started_at"] or row["queued_at"],
        "finished_at": row["finished_at"],
        "link": f"/activity/queue/{row['id']}",
        "run_id": row["id"],
        "cancellable": row["status"] in ("queued", "running"),
    }


def _task_job(row: sqlite3.Row, running: bool, note: str | None = None) -> dict | None:
    last = row["last_status"]
    if not running and last in (None, "running"):
        return None
    status = "running" if running else {"succeeded": "completed", "failed": "failed", "interrupted": "failed"}[last]
    return {
        "id": f"task-{row['name']}",
        "kind": "task",
        "title": DEFAULTS[row["name"]][0],
        "status": status,
        "label": "Running" if running else last.capitalize(),
        "message": note if running else row["last_message"],
        "progress": None,
        "started_at": row["last_started_at"],
        "finished_at": None if running else row["last_finished_at"],
        "link": "/system/backup" if row["name"] == "full_backup" else "/system/status",
        "run_id": None,
        "cancellable": False,
    }


def collect(db: sqlite3.Connection, runner, tasks, arr, maintainerr) -> list[dict]:
    found: list[dict] = []
    active = db.execute("SELECT * FROM runs WHERE status IN ('running', 'queued') ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, id").fetchall()
    position = 0
    for row in active:
        position += row["status"] == "queued"
        found.append(_run_job(runner, row, position if row["status"] == "queued" else None))
    for row in db.execute("SELECT * FROM runs WHERE status NOT IN ('running', 'queued') ORDER BY id DESC LIMIT ?", (KEEP_FINISHED,)):
        found.append(_run_job(runner, row, None))

    for row in db.execute("SELECT * FROM tasks").fetchall():
        if row["name"] in DEFAULTS:
            job = _task_job(row, tasks.running(row["name"]) if tasks else False, tasks.notes.get(row["name"]) if tasks else None)
            if job:
                found.append(job)

    for kind, pending in (arr.pending() if arr else {}).items():
        name = "Radarr" if kind == "radarr" else "Sonarr"
        found.append(
            {
                "id": f"arr-pending-{kind}",
                "kind": "arr",
                "title": f"Kometa after {name} imports",
                "status": "pending",
                "label": "Waiting",
                "message": f"{pending['imports']} import{'s' if pending['imports'] != 1 else ''} ({', '.join(pending['titles'])}); "
                "runs once no more arrive",
                "progress": None,
                "started_at": pending["first_at"],
                "finished_at": None,
                "due_at": pending["due_at"],
                "link": "/settings/connect",
                "run_id": None,
                "cancellable": False,
            }
        )

    for kind in ("radarr", "sonarr"):
        skipped = get_setting(db, f"arr.skipped.{kind}") or []
        if arr and skipped:
            last = skipped[-1]
            name = "Radarr" if kind == "radarr" else "Sonarr"
            found.append(
                {
                    "id": f"arr-skipped-{kind}",
                    "kind": "arr",
                    "title": f"Kometa after {name} imports",
                    "status": "completed",
                    "label": "Skipped",
                    "message": f"{last['title']}: no collection in {last['libraries']} wants it",
                    "progress": None,
                    "started_at": last["at"],
                    "finished_at": last["at"],
                    "link": "/settings/connect",
                    "run_id": None,
                    "cancellable": False,
                }
            )

    if maintainerr is not None and maintainerr.connected():
        paused = get_setting(db, maintainerr_module.PAUSED)
        redraw = get_setting(db, maintainerr_module.PENDING_PROCESS)
        if (paused or redraw) and not getattr(maintainerr, "_wrapping", False):
            found.append(
                {
                    "id": "maintainerr-resume",
                    "kind": "maintainerr",
                    "title": "Maintainerr overlays",
                    "status": "pending",
                    "label": "Retrying",
                    "message": ("Switching them back on and redrawing" if paused else "Asking Maintainerr to redraw them")
                    + "; Studio tries again every minute",
                    "progress": None,
                    "started_at": None,
                    "finished_at": None,
                    "link": "/settings/connect",
                    "run_id": None,
                    "cancellable": False,
                }
            )
    return found


@router.get("/jobs")
async def list_jobs(request: Request) -> dict[str, Any]:
    state = request.app.state
    jobs = collect(state.db, state.runner, getattr(state, "tasks", None), getattr(state, "arr", None), getattr(state, "maintainerr", None))
    return {"jobs": jobs, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
