"""/api/v1/runs and /api/v1/kometa: queueing runs, following them, and Kometa's webhooks."""

import json
import secrets
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from .db import get_setting, set_setting
from .kometa_command import RunRequest
from .kometa_config import EVENTS_PATH
from .runner import Runner, read_tail
from .settings import Settings

WEBHOOK_TOKEN = "kometa.webhook_token"

router = APIRouter(prefix="/api/v1", tags=["runs"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_runner(request: Request) -> Runner:
    return request.app.state.runner


Db = Annotated[sqlite3.Connection, Depends(get_db)]
RunnerDep = Annotated[Runner, Depends(get_runner)]


def webhook_token(db: sqlite3.Connection) -> str:
    token = get_setting(db, WEBHOOK_TOKEN)
    if not token:
        token = secrets.token_urlsafe(24)
        set_setting(db, WEBHOOK_TOKEN, token)
    return token


def webhook_url(settings: Settings, token: str) -> str:
    """Where Kometa, running beside Studio, sends its webhooks."""
    host = "127.0.0.1" if settings.host in ("0.0.0.0", "::", "") else settings.host
    return f"http://{host}:{settings.port}{EVENTS_PATH}?token={token}"


# --- Runs --------------------------------------------------------------------


def run_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    errors = db.execute("SELECT count(*) FROM run_events WHERE run_id = ? AND event = 'error'", (row["id"],)).fetchone()[0]
    return {
        "id": row["id"],
        "status": row["status"],
        "trigger": row["trigger"],
        "schedule_id": row["schedule_id"],
        "request": json.loads(row["request"]),
        "command": row["command"],
        "queued_at": row["queued_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "exit_code": row["exit_code"],
        "error": row["error"],
        "summary": json.loads(row["summary"]) if row["summary"] else None,
        "error_events": errors,
        "warnings": row["warnings"],
    }


def get_run_row(db: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such run")
    return row


# These endpoints are async so they run on the event loop with the runner, never in a thread, sharing one SQLite connection safely.


@router.get("/runs")
async def list_runs(db: Db, runner: RunnerDep, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict:
    rows = db.execute(
        "SELECT * FROM runs ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, "
        "CASE WHEN status = 'queued' THEN id END, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {"runs": [run_json(db, row) for row in rows], "current": runner.current_run_id}


@router.post("/runs", status_code=201)
async def create_run(body: RunRequest, db: Db, runner: RunnerDep) -> dict:
    run_id = runner.enqueue(body)
    return run_json(db, get_run_row(db, run_id))


@router.get("/runs/{run_id}")
async def get_run(run_id: int, db: Db) -> dict:
    run = run_json(db, get_run_row(db, run_id))
    events = db.execute("SELECT event, received_at, payload FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    run["events"] = [
        {"event": e["event"], "received_at": e["received_at"], **_event_fields(json.loads(e["payload"]))}
        for e in events
        if e["event"] in ("error", "changes", "delete", "version")
    ]
    return run


def _event_fields(payload: dict) -> dict:
    """The parts of an event the run page shows; full payloads stay in the database."""
    keep = ("error", "critical", "library_name", "collection", "playlist", "created", "message", "current", "latest", "poster_url")
    fields = {key: payload[key] for key in keep if key in payload}
    for key in ("additions", "removals"):
        if key in payload:
            fields[key] = len(payload[key] or [])
    return fields


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, db: Db, runner: RunnerDep) -> dict:
    get_run_row(db, run_id)
    if not runner.cancel(run_id):
        raise HTTPException(409, "That run has already finished")
    return run_json(db, get_run_row(db, run_id))


@router.get("/runs/{run_id}/log")
async def run_log(run_id: int, db: Db, runner: RunnerDep) -> FileResponse:
    get_run_row(db, run_id)
    path = runner.log_path(run_id)
    if not path.exists():
        raise HTTPException(404, "This run has no log yet")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=f"kometa-run-{run_id}.log")


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int, db: Db, runner: RunnerDep) -> StreamingResponse:
    """Server-sent events: the log so far ("lines", possibly "truncated"), new lines as they come, then "end"."""
    get_run_row(db, run_id)
    # Subscribe and read the log in one step with no await between, so no line is missed or repeated:
    # the runner writes lines on this same event loop.
    subscriber = runner.subscribe(run_id)
    tail, truncated = read_tail(runner.log_path(run_id))

    async def events():
        try:
            if truncated:
                yield _sse("truncated", True)
            for start in range(0, len(tail), 500):
                yield _sse("lines", tail[start : start + 500])
            ended = subscriber is None
            while not ended:
                # Wait for one line, then send it with whatever else is already waiting.
                batch: list[str] = []
                item = await subscriber.queue.get()
                while True:
                    if item is None:
                        ended = True
                        break
                    batch.append(item)
                    if subscriber.queue.empty() or len(batch) >= 500:
                        break
                    item = subscriber.queue.get_nowait()
                if batch:
                    yield _sse("lines", batch)
            row = get_run_row(db, run_id)
            yield _sse("end", {"status": row["status"], "dropped": bool(subscriber and subscriber.dropped)})
        finally:
            if subscriber is not None:
                runner.unsubscribe(run_id, subscriber)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# --- Kometa ------------------------------------------------------------------


@router.get("/kometa")
async def kometa_info(request: Request, runner: RunnerDep) -> dict:
    settings: Settings = request.app.state.settings
    problem = None
    if settings.kometa_python is None or settings.kometa_entry is None or settings.kometa_config is None:
        problem = "Studio doesn't know where Kometa is. Set STUDIO_KOMETA_PYTHON, STUDIO_KOMETA_ENTRY and STUDIO_KOMETA_CONFIG."
    elif not settings.kometa_config.exists():
        problem = "Kometa's config.yml doesn't exist yet. Connect Plex in Settings → Plex first."
    return {
        "flags": sorted(runner.flags) if runner.flags is not None else None,
        "flags_error": runner.flags_error,
        "problem": problem,
        "paths": {
            "python": str(settings.kometa_python) if settings.kometa_python else None,
            "entry": str(settings.kometa_entry) if settings.kometa_entry else None,
            "config": str(settings.kometa_config) if settings.kometa_config else None,
            "schemas": str(settings.kometa_schemas) if settings.kometa_schemas else None,
        },
        "run_timeout": settings.run_timeout,
        "kill_after": settings.kill_after,
    }


@router.post(EVENTS_PATH.removeprefix("/api/v1"))
async def kometa_event(request: Request, db: Db, runner: RunnerDep, token: str = "") -> dict:
    """Kometa's webhooks land here (handoff v2 §5.2)."""
    if not secrets.compare_digest(token, webhook_token(db)):
        raise HTTPException(403, "Wrong token")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Expected a JSON body") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "Expected a JSON object")
    run_id = runner.record_event(payload)
    return {"ok": True, "run": run_id}
