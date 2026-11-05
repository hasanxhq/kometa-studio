"""Schedules: when they're due, what to queue, and what to do about runs missed while Studio was off (handoff v2 §6).

Every ``TICK`` seconds, and once at start-up, each enabled schedule's occurrences since
``last_fired_at`` are collected. An occurrence that is at most ``GRACE`` old is on time and
queues a normal run. An older one was missed (Studio was stopped, the PC slept): with
``catch_up = run_once`` the schedule runs once, tagged ``catch_up``, however many occurrences
it missed, as long as the latest is less than ``CATCH_UP_WINDOW`` old; with ``skip`` it doesn't
run. Either way ``last_fired_at`` moves to the latest occurrence in the same transaction as the
queueing, so nothing fires twice.
"""

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .kometa_command import RunRequest
from .runner import Runner

log = logging.getLogger(__name__)

TICK = 30.0
GRACE = timedelta(minutes=5)
CATCH_UP_WINDOW = timedelta(hours=24)

# Order for runs that fire together: library operations first, playlists last (handoff v1 §4.2).
MODE_ORDER = ["all", "operations", "metadata", "collections", "overlays", "playlists"]
OPTIONS = ("ignore_schedules", "no_missing", "tests", "timings", "low_priority")


def utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def default_timezone(configured: str | None = None) -> str:
    """STUDIO_TIMEZONE, else the container's TZ, else UTC."""
    for name in (configured, os.environ.get("TZ")):
        if name:
            try:
                ZoneInfo(name)
                return name
            except (ZoneInfoNotFoundError, ValueError):
                log.warning("Unknown timezone %r, ignoring it", name)
    return "UTC"


# --- Schedule maths ------------------------------------------------------------


@dataclass(frozen=True)
class When:
    days: int  # bit 0 = Monday ... bit 6 = Sunday
    time: str  # HH:MM, local
    timezone: str

    def occurrences(self, after: datetime, until: datetime) -> list[datetime]:
        """UTC times in (after, until] at which this fires.

        A time that doesn't exist on a DST spring-forward day runs at the same wall-clock
        offset (02:30 becomes 03:30); a time that happens twice on a fall-back day runs
        once, the first time.
        """
        zone = ZoneInfo(self.timezone)
        hour, minute = map(int, self.time.split(":"))
        first: date = after.astimezone(zone).date() - timedelta(days=1)
        last: date = until.astimezone(zone).date() + timedelta(days=1)
        found = []
        day = first
        while day <= last:
            if self.days & (1 << day.weekday()):
                local = datetime.combine(day, time(hour, minute), tzinfo=zone)  # fold=0: first of two
                moment = local.astimezone(UTC)
                # Round-trip through UTC to normalise a time that falls in a DST gap.
                if after < moment <= until:
                    found.append(moment)
            day += timedelta(days=1)
        return sorted(set(found))

    def next_after(self, moment: datetime) -> datetime | None:
        upcoming = self.occurrences(moment, moment + timedelta(days=8))
        return upcoming[0] if upcoming else None


# --- Coalescing ----------------------------------------------------------------


def covers(wide: RunRequest, narrow: RunRequest) -> bool:
    """Whether running ``wide`` also does everything ``narrow`` would."""
    if wide.mode != "all" or wide.collections or wide.files:
        return False
    if any(getattr(wide, option) != getattr(narrow, option) for option in OPTIONS):
        return False
    if not wide.libraries:
        return True
    return bool(narrow.libraries) and set(narrow.libraries) <= set(wide.libraries)


@dataclass
class Due:
    schedule_id: int
    request: RunRequest
    trigger: str  # schedule or catch_up


def coalesce(due: list[Due]) -> list[Due]:
    """Drop runs another due run covers, then order them operations → … → playlists."""
    kept: list[Due] = []
    for item in due:
        if any(covers(other.request, item.request) for other in kept):
            continue
        kept = [other for other in kept if not covers(item.request, other.request)]
        kept.append(item)
    return sorted(kept, key=lambda item: MODE_ORDER.index(item.request.mode))


# --- The loop ------------------------------------------------------------------


class Scheduler:
    def __init__(self, db: sqlite3.Connection, runner: Runner, also: tuple = ()):
        self.db = db
        self.runner = runner
        self.also = also  # more things with a tick(now): Studio's built-in tasks, the arr webhook's pending run
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="kometa-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            now = datetime.now(UTC)
            try:
                self.tick(now)
            except Exception:  # a bad row must not stop every other schedule for good
                log.exception("Scheduler tick failed")
            for other in self.also:
                try:
                    other.tick(now)
                except Exception:
                    log.exception("%s tick failed", type(other).__name__)
            await asyncio.sleep(TICK)

    def tick(self, now: datetime) -> list[int]:
        """Queue whatever is due at ``now`` and return the queued run IDs."""
        rows = self.db.execute(
            "SELECT id, request, days, time, timezone, catch_up, last_fired_at FROM schedules WHERE enabled = 1 ORDER BY id"
        ).fetchall()
        due: list[Due] = []
        fired: list[tuple[str, int]] = []
        for row in rows:
            when = When(row["days"], row["time"], row["timezone"])
            occurrences = when.occurrences(parse_utc(row["last_fired_at"]), now)
            if not occurrences:
                continue
            latest = occurrences[-1]
            fired.append((utc_text(latest), row["id"]))
            age = now - latest
            if age <= GRACE:
                trigger = "schedule"
            elif row["catch_up"] == "run_once" and age <= CATCH_UP_WINDOW:
                trigger = "catch_up"
            else:
                log.info("Schedule %s missed %d run(s) and is set not to catch up", row["id"], len(occurrences))
                continue
            due.append(Due(row["id"], RunRequest.model_validate_json(row["request"]), trigger))

        if not fired:
            return []
        queued = []
        with self.db:  # queue the runs and mark the occurrences handled together
            for item in coalesce(due):
                queued.append(self.runner.insert_run(item.request, item.trigger, item.schedule_id))
            self.db.executemany("UPDATE schedules SET last_fired_at = ? WHERE id = ?", fired)
        if queued:
            self.runner.wake()
        return queued


def days_to_mask(days: list[int]) -> int:
    return sum(1 << day for day in set(days))


def mask_to_days(mask: int) -> list[int]:
    return [day for day in range(7) if mask & (1 << day)]
