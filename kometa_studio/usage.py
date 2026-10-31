"""How much Kometa's runs use TMDb, MDBList and the other services, and keeping runs after imports
within MDBList's daily allowance (feedback round 1).

With ``--timings``, Kometa writes ``logs/timings-<time>.json`` with its calls per service (``source``:
tmdb, mdblist, imdb, …). A run hook adds them up and keeps them on the run (``runs.api_calls``), which
gives the day's totals. Runs don't pass it for now: Kometa 2.5.3 crashes on it at startup, because
``modules/timings.py`` takes ``util.logger`` on import, before ``kometa.py`` has set it. Until a Kometa
that's fixed, there are no totals, and MDBList's allowance comes from ``/user`` alone.

A free MDBList key allows 1000 requests a day, and the count resets at midnight UTC. Studio asks
MDBList's ``/user`` how much of today's allowance the key has used (at most every
``MDBLIST_EVERY``, and only while a run after imports is waiting), adds the MDBList calls its own runs
made since, and holds runs after imports while that's ``LIMIT_SHARE`` of the allowance or more.
Scheduled and manual runs always go.
"""

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Request

from .db import get_setting, set_setting
from .services import mdblist_usage

LIMIT_SHARE = 0.8
MDBLIST_EVERY = 900.0
USAGE = "mdblist.usage"  # {limit, used, checked_at}: MDBList's own answer

router = APIRouter(prefix="/api/v1", tags=["usage"])


def _utc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_timings(logs: Path, since: float) -> dict[str, int] | None:
    """Calls per service from the newest timings file written at or after ``since``, or None if there isn't one."""
    found = [path for path in logs.glob("timings-*.json") if path.stat().st_mtime >= since] if logs.is_dir() else []
    if not found:
        return None
    try:
        data = json.loads(max(found, key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    calls: dict[str, int] = {}
    for bucket in data.get("buckets", []) if isinstance(data, dict) else []:
        if isinstance(bucket, dict) and isinstance(bucket.get("calls"), int):
            source = str(bucket.get("source") or "other")
            calls[source] = calls.get(source, 0) + bucket["calls"]
    return calls


class ApiCalls:
    """Run hook: once Kometa has finished, keep its calls per service on the run."""

    def __init__(self, db: sqlite3.Connection, runner, config: Path | None):
        self.db = db
        self.runner = runner
        self.config = config

    async def before_run(self, request, say):
        run_id = self.runner.current_run_id
        started = time.time() - 1

        async def after() -> None:
            if self.config is None:
                return
            calls = read_timings(self.config.parent / "logs", started)
            if calls is not None:
                with self.db:
                    self.db.execute("UPDATE runs SET api_calls = ? WHERE id = ?", (json.dumps(calls), run_id))

        return after


def calls_since(db: sqlite3.Connection, since: str) -> dict[str, int]:
    """Calls per service by runs that finished at or after ``since`` (UTC text)."""
    totals: dict[str, int] = {}
    for (text,) in db.execute("SELECT api_calls FROM runs WHERE api_calls IS NOT NULL AND finished_at >= ?", (since,)):
        for source, count in json.loads(text).items():
            totals[source] = totals.get(source, 0) + int(count)
    return totals


def today(db: sqlite3.Connection, now: datetime) -> dict[str, int]:
    return calls_since(db, now.strftime("%Y-%m-%dT00:00:00Z"))


async def refresh_mdblist(db: sqlite3.Connection, http: httpx.AsyncClient, config: Path | None, now: datetime) -> None:
    """Ask MDBList how much of today's allowance is used, unless Studio asked recently."""
    cached = get_setting(db, USAGE)
    if cached and (now - datetime.fromisoformat(cached["checked_at"].replace("Z", "+00:00"))).total_seconds() < MDBLIST_EVERY:
        return
    found = await mdblist_usage(http, config)
    if found is not None:
        set_setting(db, USAGE, found | {"checked_at": _utc(now)})


def mdblist_estimate(db: sqlite3.Connection, now: datetime) -> dict[str, Any] | None:
    """Today's MDBList use: MDBList's last answer plus what Studio's runs used since. None if MDBList hasn't said today."""
    cached = get_setting(db, USAGE)
    if not cached or not cached.get("limit") or cached["checked_at"][:10] != now.strftime("%Y-%m-%d"):
        return None
    used = int(cached["used"]) + calls_since(db, cached["checked_at"]).get("mdblist", 0)
    return {"limit": int(cached["limit"]), "used": used, "checked_at": cached["checked_at"]}


def held(db: sqlite3.Connection, now: datetime) -> str | None:
    """Why runs after imports must wait now, or None."""
    estimate = mdblist_estimate(db, now)
    if estimate is None or estimate["used"] < LIMIT_SHARE * estimate["limit"]:
        return None
    return (
        f"MDBList has used {estimate['used']} of today's {estimate['limit']} requests "
        f"({LIMIT_SHARE:.0%} is Studio's limit for runs after imports); waiting until it resets at midnight UTC"
    )


@router.get("/usage")
async def get_usage(request: Request) -> dict:
    db = request.app.state.db
    now = datetime.now(UTC)
    return {"today": today(db, now), "mdblist": mdblist_estimate(db, now), "limit_share": LIMIT_SHARE, "held": held(db, now)}
