"""Studio's built-in tasks: full backups and Kometa's full check, each on its own schedule (handoff v2 §8).

They share the schedules' maths and catch-up rule (scheduler.py): a time missed while Studio was
off runs once when it starts again, if that's within a day. A full backup waits while Kometa runs,
so the Original Posters it copies aren't being rewritten under it. Each task runs at most once at
a time; its outcome is kept on its row.
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime

from . import full_backup
from .config_routes import FULL_CHECK
from .config_write import ConfigWriter, SaveRefused
from .db import set_setting
from .runner import Runner
from .scheduler import CATCH_UP_WINDOW, When, parse_utc, utc_text
from .settings import Settings

log = logging.getLogger(__name__)

BUSY_WAIT = 30.0  # how often a backup looks again while Kometa is running

# name: (label, days, time, enabled, options)
DEFAULTS = {
    "full_backup": ("Full backup", 1 << 6, "04:30", True, {"keep": 4}),  # Sundays
    "full_check": ("Full check", 127, "04:00", False, {}),
}


def now_text() -> str:
    return utc_text(datetime.now(UTC))


class Tasks:
    def __init__(self, db: sqlite3.Connection, settings: Settings, runner: Runner, writer: ConfigWriter | None):
        self.db = db
        self.settings = settings
        self.runner = runner
        self.writer = writer
        self._running: dict[str, asyncio.Task] = {}
        self.notes: dict[str, str] = {}  # what a running task is doing right now, for the jobs drawer

    def setup(self, timezone: str) -> None:
        """Add rows for tasks this version has and the database doesn't, and close off runs a restart cut short."""
        now = now_text()
        with self.db:
            for name, (_, days, time, enabled, options) in DEFAULTS.items():
                self.db.execute(
                    "INSERT OR IGNORE INTO tasks (name, enabled, days, time, timezone, options, last_fired_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, int(enabled), days, time, timezone, json.dumps(options), now),
                )
            self.db.execute(
                "UPDATE tasks SET last_status = 'interrupted', last_finished_at = ?, last_message = 'Studio stopped while this was going' "
                "WHERE last_status = 'running'",
                (now,),
            )
        full_backup.clean_partials(self.settings.data_dir)

    def running(self, name: str) -> bool:
        return name in self._running

    def tick(self, now: datetime) -> list[str]:
        """Start whatever is due at ``now``; returns the names started."""
        started = []
        for row in self.db.execute("SELECT name, days, time, timezone, last_fired_at FROM tasks WHERE enabled = 1").fetchall():
            occurrences = When(row["days"], row["time"], row["timezone"]).occurrences(parse_utc(row["last_fired_at"]), now)
            if not occurrences:
                continue
            with self.db:
                self.db.execute("UPDATE tasks SET last_fired_at = ? WHERE name = ?", (utc_text(occurrences[-1]), row["name"]))
            if now - occurrences[-1] <= CATCH_UP_WINDOW and self.start(row["name"]):
                started.append(row["name"])
        return started

    def start(self, name: str) -> bool:
        """Run a task now, unless it's already going."""
        if name not in DEFAULTS or name in self._running:
            return False
        work: Callable[[dict], Awaitable[str]] = {"full_backup": self._full_backup, "full_check": self._full_check}[name]
        self._running[name] = asyncio.create_task(self._execute(name, work), name=f"task-{name}")
        return True

    async def stop(self) -> None:
        for task in list(self._running.values()):
            task.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)

    async def _execute(self, name: str, work: Callable[[dict], Awaitable[str]]) -> None:
        try:
            options = json.loads(self.db.execute("SELECT options FROM tasks WHERE name = ?", (name,)).fetchone()["options"])
            with self.db:
                self.db.execute(
                    "UPDATE tasks SET last_status = 'running', last_started_at = ?, last_finished_at = NULL, last_message = NULL WHERE name = ?",
                    (now_text(), name),
                )
            try:
                status, message = "succeeded", await work(options)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # the outcome is reported on the task; Studio carries on
                log.exception("Task %s failed", name)
                status, message = "failed", str(error) or type(error).__name__
            with self.db:
                self.db.execute(
                    "UPDATE tasks SET last_status = ?, last_finished_at = ?, last_message = ? WHERE name = ?", (status, now_text(), message, name)
                )
        finally:
            self._running.pop(name, None)
            self.notes.pop(name, None)

    async def _full_backup(self, options: dict) -> str:
        if self.settings.kometa_config is None:
            raise full_backup.BackupFailed("Studio doesn't know where Kometa's config folder is")
        while self.runner.current_run_id is not None:
            self.notes["full_backup"] = f"Waiting for Kometa's run #{self.runner.current_run_id} to finish"
            await asyncio.sleep(BUSY_WAIT)
        self.notes["full_backup"] = "Zipping the config folder and Original Posters"
        result = await asyncio.to_thread(
            full_backup.create, self.settings.kometa_config.parent, self.settings.data_dir, self.settings.db_path, int(options.get("keep", 4))
        )
        notes = f" ({'; '.join(result['notes'])})" if result["notes"] else ""
        return f"{result['name']}: {result['files']} files, {result['size'] / 1024**2:,.1f} MB{notes}"

    async def _full_check(self, options: dict) -> str:
        if self.writer is None:
            raise RuntimeError("Studio doesn't know where Kometa's config.yml is")
        try:
            validation = await self.writer.full_check()
        except SaveRefused as refused:
            raise RuntimeError(refused.message) from None
        set_setting(self.db, FULL_CHECK, asdict(validation) | {"at": now_text()})
        if not validation.ok:
            raise RuntimeError(f"Kometa found {len(validation.errors) or 'some'} problem(s); see System → Status")
        return "Kometa's config passed"


def task_json(row: sqlite3.Row, running: bool, now: datetime) -> dict:
    when = When(row["days"], row["time"], row["timezone"])
    next_run = when.next_after(now) if row["enabled"] else None
    return {
        "name": row["name"],
        "label": DEFAULTS[row["name"]][0],
        "enabled": bool(row["enabled"]),
        "days": [day for day in range(7) if row["days"] & (1 << day)],
        "time": row["time"],
        "timezone": row["timezone"],
        "options": json.loads(row["options"]),
        "next_run": utc_text(next_run) if next_run else None,
        "running": running,
        "last": {
            "started_at": row["last_started_at"],
            "finished_at": row["last_finished_at"],
            "status": row["last_status"],
            "message": row["last_message"],
        }
        if row["last_started_at"]
        else None,
    }


def last_fired_reset(db: sqlite3.Connection, name: str) -> None:
    """After a schedule change, count from now, so the change doesn't fire past times."""
    with db:
        db.execute("UPDATE tasks SET last_fired_at = ? WHERE name = ?", (now_text(), name))

