"""/api/v1/schedules: the schedules on System → Tasks."""

import re
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator

from .kometa_command import RunRequest
from .runner import Runner
from .runs_routes import get_db, get_runner, get_run_row, run_json
from .scheduler import CATCH_UP_WINDOW, When, days_to_mask, mask_to_days, parse_utc, utc_text

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RunnerDep = Annotated[Runner, Depends(get_runner)]


class ScheduleIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    request: RunRequest = Field(default_factory=RunRequest)
    days: list[int] = Field(min_length=1)  # 0 = Monday ... 6 = Sunday
    time: str
    timezone: str | None = None  # None: Studio's default
    enabled: bool = True
    catch_up: Literal["run_once", "skip"] = "run_once"

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


def schedule_json(db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict:
    when = When(row["days"], row["time"], row["timezone"])
    last = db.execute(
        "SELECT id, status, trigger, started_at, finished_at FROM runs WHERE schedule_id = ? ORDER BY id DESC LIMIT 1", (row["id"],)
    ).fetchone()
    next_run = when.next_after(max(now, parse_utc(row["last_fired_at"]))) if row["enabled"] else None
    return {
        "id": row["id"],
        "name": row["name"],
        "request": RunRequest.model_validate_json(row["request"]).model_dump(),
        "days": mask_to_days(row["days"]),
        "time": row["time"],
        "timezone": row["timezone"],
        "enabled": bool(row["enabled"]),
        "catch_up": row["catch_up"],
        "next_run": utc_text(next_run) if next_run else None,
        "last_run": dict(last) if last else None,
    }


def get_schedule_row(db: sqlite3.Connection, schedule_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such schedule")
    return row


def default_tz(request: Request) -> str:
    return request.app.state.timezone


@router.get("")
async def list_schedules(request: Request, db: Db) -> dict:
    now = datetime.now(UTC)
    rows = db.execute("SELECT * FROM schedules ORDER BY time, id").fetchall()
    catch_ups = db.execute(
        "SELECT runs.id, runs.status, runs.queued_at, schedules.name FROM runs JOIN schedules ON schedules.id = runs.schedule_id "
        "WHERE runs.trigger = 'catch_up' AND runs.queued_at >= ? ORDER BY runs.id DESC",
        (utc_text(now - CATCH_UP_WINDOW),),
    ).fetchall()
    return {
        "schedules": [schedule_json(db, row, now) for row in rows],
        "timezone": default_tz(request),
        "catch_ups": [dict(row) for row in catch_ups],
    }


@router.post("", status_code=201)
async def create_schedule(body: ScheduleIn, request: Request, db: Db) -> dict:
    now = datetime.now(UTC)
    with db:
        schedule_id = db.execute(
            "INSERT INTO schedules (name, request, days, time, timezone, enabled, catch_up, last_fired_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                body.name,
                body.request.model_dump_json(),
                days_to_mask(body.days),
                body.time,
                body.timezone or default_tz(request),
                body.enabled,
                body.catch_up,
                utc_text(now),  # nothing before now counts as missed
            ),
        ).lastrowid
    return schedule_json(db, get_schedule_row(db, schedule_id), now)


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: int, body: ScheduleIn, request: Request, db: Db) -> dict:
    now = datetime.now(UTC)
    old = get_schedule_row(db, schedule_id)
    timezone = body.timezone or default_tz(request)
    timing = (days_to_mask(body.days), body.time, timezone, int(body.enabled))
    # A new time, or switching back on, starts from now: what the old timing "missed" isn't owed.
    restart = timing != (old["days"], old["time"], old["timezone"], old["enabled"])
    with db:
        db.execute(
            "UPDATE schedules SET name = ?, request = ?, days = ?, time = ?, timezone = ?, enabled = ?, catch_up = ?, "
            "last_fired_at = ? WHERE id = ?",
            (
                body.name,
                body.request.model_dump_json(),
                *timing,
                body.catch_up,
                utc_text(now) if restart else old["last_fired_at"],
                schedule_id,
            ),
        )
    return schedule_json(db, get_schedule_row(db, schedule_id), now)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: int, db: Db) -> Response:
    get_schedule_row(db, schedule_id)
    with db:
        db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    return Response(status_code=204)


@router.post("/{schedule_id}/run", status_code=201)
async def run_schedule_now(schedule_id: int, db: Db, runner: RunnerDep) -> dict:
    row = get_schedule_row(db, schedule_id)
    run_id = runner.enqueue(RunRequest.model_validate_json(row["request"]), "manual", schedule_id)
    return run_json(db, get_run_row(db, run_id))


def next_scheduled(db: sqlite3.Connection, now: datetime) -> dict | None:
    """The next schedule to fire, for /status."""
    best = None
    for row in db.execute("SELECT id, name, days, time, timezone, last_fired_at FROM schedules WHERE enabled = 1"):
        moment = When(row["days"], row["time"], row["timezone"]).next_after(max(now, parse_utc(row["last_fired_at"])))
        if moment and (best is None or moment < best[0]):
            best = (moment, row["id"], row["name"])
    return {"at": utc_text(best[0]), "schedule_id": best[1], "name": best[2]} if best else None

