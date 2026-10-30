"""/api/v1/tasks and /api/v1/backups/full: Studio's built-in tasks and the full backups they make."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from . import full_backup
from .runs_routes import get_db
from .scheduler import days_to_mask
from .settings import Settings
from .tasks import DEFAULTS, Tasks, last_fired_reset, task_json

router = APIRouter(prefix="/api/v1", tags=["tasks"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def get_tasks(request: Request) -> Tasks:
    return request.app.state.tasks


TasksDep = Annotated[Tasks, Depends(get_tasks)]


def _row(db: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM tasks WHERE name = ?", (name,)).fetchone()
    if row is None or name not in DEFAULTS:
        raise HTTPException(404, "No such task")
    return row


class TaskOptions(BaseModel):
    keep: int | None = Field(default=None, ge=1, le=100)  # full backups to keep


class TaskIn(BaseModel):
    enabled: bool
    days: list[int] = Field(min_length=1)
    time: str
    timezone: str | None = None  # None: Settings → General
    options: TaskOptions = Field(default_factory=TaskOptions)

    @field_validator("days")
    @classmethod
    def check_days(cls, days: list[int]) -> list[int]:
        if any(day not in range(7) for day in days):
            raise ValueError("Days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(days))

    @field_validator("time")
    @classmethod
    def check_time(cls, value: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Use a 24-hour time like 03:00")
        return value

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"Unknown timezone: {value}") from None
        return value


@router.get("/tasks")
async def list_tasks(db: Db, tasks: TasksDep) -> dict:
    now = datetime.now(UTC)
    rows = db.execute("SELECT * FROM tasks").fetchall()
    order = list(DEFAULTS)
    return {"tasks": [task_json(row, tasks.running(row["name"]), now) for row in sorted(rows, key=lambda r: order.index(r["name"])) if row["name"] in DEFAULTS]}


@router.put("/tasks/{name}")
async def update_task(name: str, body: TaskIn, request: Request, db: Db, tasks: TasksDep) -> dict:
    _row(db, name)
    options = {"keep": body.options.keep or 4} if name == "full_backup" else {}
    timezone = body.timezone or request.app.state.timezone
    with db:
        db.execute(
            "UPDATE tasks SET enabled = ?, days = ?, time = ?, timezone = ?, options = ? WHERE name = ?",
            (int(body.enabled), days_to_mask(body.days), body.time, timezone, json.dumps(options), name),
        )
    last_fired_reset(db, name)
    return task_json(_row(db, name), tasks.running(name), datetime.now(UTC))


@router.post("/tasks/{name}/run", status_code=202)
async def run_task(name: str, db: Db, tasks: TasksDep) -> dict:
    _row(db, name)
    if not tasks.start(name):
        raise HTTPException(409, "It's already running")
    return task_json(_row(db, name), True, datetime.now(UTC))


# --- Full backups --------------------------------------------------------------------


def _data_dir(request: Request):
    settings: Settings = request.app.state.settings
    return settings.data_dir


@router.get("/backups/full")
async def list_full_backups(request: Request) -> dict:
    return {"backups": full_backup.list_full(_data_dir(request))}


@router.get("/backups/full/{name}")
async def download_full_backup(name: str, request: Request) -> FileResponse:
    path = full_backup.find(_data_dir(request), name)
    if path is None:
        raise HTTPException(404, "No such backup")
    return FileResponse(path, media_type="application/zip", filename=name)


@router.delete("/backups/full/{name}", status_code=204)
async def delete_full_backup(name: str, request: Request) -> Response:
    path = full_backup.find(_data_dir(request), name)
    if path is None:
        raise HTTPException(404, "No such backup")
    path.unlink()
    return Response(status_code=204)
