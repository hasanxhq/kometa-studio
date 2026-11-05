"""Running Kometa: one process at a time, queued in SQLite, output streamed live (handoff v2 §5.3).

Kometa forks a worker process for the run itself, so each run gets its own process
group and cancelling signals the whole group: SIGTERM, then SIGKILL if it hasn't
exited after ``kill_after`` seconds.
"""

import asyncio
import json
import os
import re
import signal
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import kometa_command
from .kometa_command import RunRequest
from .kometa_config import ensure_studio_webhooks
from .settings import Settings

FINISHED = ("succeeded", "failed", "cancelled", "interrupted", "timed_out")
# What makes a log line an error or a warning: the same words as the log's colours and filter (frontend's RunLog.tsx).
LOG_ERROR = re.compile(r"\b(error|critical|traceback)\b", re.IGNORECASE)
LOG_WARNING = re.compile(r"\bwarning\b", re.IGNORECASE)
KOMETA_CRITICAL = re.compile(r"\[CRITICAL\]\s*\|\s*(.*?)\s*\|?\s*$", re.MULTILINE)  # a line of Kometa's logs/meta.log
SUBSCRIBER_BACKLOG = 10_000  # lines a slow browser may fall behind before it's dropped (it reconnects)
LINE_LIMIT = 1024 * 1024  # longest single output line Studio reads


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Subscriber:
    """One browser following a run's log. Gets lines, then None when the run ends or it fell too far behind."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.dropped = False

    def send(self, line: str | None) -> None:
        if self.dropped:
            return
        if line is not None and self.queue.qsize() >= SUBSCRIBER_BACKLOG:
            self.dropped = True
            line = None
        self.queue.put_nowait(line)


class RunHeld(Exception):
    """A run hook says this run mustn't start; the message says why."""


# A run hook: ``await hook.before_run(request, say)`` runs before Kometa starts. It may raise RunHeld, and
# may return an ``after`` coroutine function, awaited once Kometa has finished (however it finished).
# ``say`` writes a line to the run's log, live.
Say = Callable[[str], None]
After = Callable[[], Awaitable[None]]


@dataclass
class Active:
    run_id: int
    process: asyncio.subprocess.Process | None  # None while run hooks go, before Kometa starts
    subscribers: set[Subscriber] = field(default_factory=set)
    cancel_requested: bool = False
    timed_out: bool = False
    started: float = 0.0  # when Kometa was started
    warnings: int = 0  # log lines so far that are warnings


class Runner:
    def __init__(self, db: sqlite3.Connection, settings: Settings, webhook_url: str):
        self.db = db
        self.settings = settings
        self.webhook_url = webhook_url
        self.runs_dir = settings.data_dir / "runs"
        self.flags: set[str] | None = None  # from kometa.py --help; None means "not known", so nothing is checked
        self.flags_error: str | None = None
        self.hooks: list = []  # run hooks (see RunHeld): the Maintainerr integration
        self.extra_env: Callable[[], dict[str, str]] = dict  # more environment for Kometa: Settings → Network's proxy and DNS (network.kometa_env)
        self._wake = asyncio.Event()
        self._active: Active | None = None
        self._task: asyncio.Task | None = None

    # --- Lifecycle --------------------------------------------------------------

    def recover(self) -> int:
        """Runs still marked running were cut off by a restart or power cut."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE runs SET status = 'interrupted', finished_at = ?, "
                "error = 'Studio stopped while this run was going' WHERE status = 'running'",
                (now(),),
            )
        return cursor.rowcount

    def start(self) -> None:
        self.recover()
        self._task = asyncio.create_task(self._loop(), name="kometa-runner")

    async def stop(self) -> None:
        if self._active is not None:
            self._active.cancel_requested = True
            await self._terminate(self._active)
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def probe_flags(self) -> None:
        if self.settings.kometa_python is None or self.settings.kometa_entry is None:
            self.flags_error = "Studio doesn't know where Kometa is (STUDIO_KOMETA_PYTHON and STUDIO_KOMETA_ENTRY)."
            return
        try:
            self.flags = await kometa_command.probe_flags(self.settings.kometa_python, self.settings.kometa_entry)
            self.flags_error = None
        except RuntimeError as error:
            self.flags_error = str(error)

    # --- Queue ------------------------------------------------------------------

    @property
    def current_run_id(self) -> int | None:
        return self._active.run_id if self._active else None

    def enqueue(self, request: RunRequest, trigger: str = "manual", schedule_id: int | None = None) -> int:
        """Queue a run. An identical request that's already waiting is reused rather than queued twice."""
        with self.db:
            run_id = self.insert_run(request, trigger, schedule_id)
        self.wake()
        return run_id

    def insert_run(self, request: RunRequest, trigger: str, schedule_id: int | None = None) -> int:
        """Queue a run inside the caller's transaction; call wake() once it's committed."""
        payload = request.model_dump_json()
        existing = self.db.execute("SELECT id FROM runs WHERE status = 'queued' AND request = ? ORDER BY id LIMIT 1", (payload,)).fetchone()
        if existing:
            return existing[0]
        return self.db.execute(
            "INSERT INTO runs (request, trigger, schedule_id) VALUES (?, ?, ?)", (payload, trigger, schedule_id)
        ).lastrowid

    def wake(self) -> None:
        self._wake.set()

    def cancel(self, run_id: int) -> bool:
        """Cancel a queued or running run. Returns False if it had already finished."""
        if self._active is not None and self._active.run_id == run_id:
            if not self._active.cancel_requested:
                self._active.cancel_requested = True
                asyncio.create_task(self._terminate(self._active))
            return True
        with self.db:
            cursor = self.db.execute(
                "UPDATE runs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status = 'queued'", (now(), run_id)
            )
        return cursor.rowcount == 1

    def subscribe(self, run_id: int) -> Subscriber | None:
        """Follow the live output of the running run, or None if that run isn't running."""
        if self._active is None or self._active.run_id != run_id:
            return None
        subscriber = Subscriber()
        self._active.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, run_id: int, subscriber: Subscriber) -> None:
        if self._active is not None and self._active.run_id == run_id:
            self._active.subscribers.discard(subscriber)

    def log_path(self, run_id: int) -> Path:
        return self.runs_dir / f"{run_id}.log"

    # --- Webhook events ---------------------------------------------------------

    def record_event(self, payload: dict[str, Any]) -> int | None:
        """Store a Kometa webhook event against the running run (None if no run is going) and return that run's ID.

        Webhooks carry no run ID, but only one Kometa runs at a time, so whatever arrives now belongs to it.
        """
        event = str(payload.get("event") or "unknown")
        # Base64 images can be megabytes; the *_url fields are enough.
        payload = {key: value for key, value in payload.items() if key not in ("poster", "background")}
        run_id = self.current_run_id
        with self.db:
            self.db.execute("INSERT INTO run_events (run_id, event, payload) VALUES (?, ?, ?)", (run_id, event, json.dumps(payload)))
            if event == "run_end" and run_id is not None:
                self.db.execute("UPDATE runs SET summary = ? WHERE id = ?", (json.dumps(payload), run_id))
        return run_id

    # --- Running ----------------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            row = self.db.execute("SELECT id, request FROM runs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self._wake.clear()
                await self._wake.wait()
                continue
            await self._run(row[0], RunRequest.model_validate_json(row[1]))

    def _finish(self, run_id: int, status: str, *, exit_code: int | None = None, error: str | None = None) -> None:
        warnings = self._active.warnings if self._active else 0
        with self.db:
            self.db.execute(
                "UPDATE runs SET status = ?, finished_at = ?, exit_code = ?, error = ?, warnings = ? WHERE id = ?",
                (status, now(), exit_code, error, warnings, run_id),
            )

    def _prepare(self, request: RunRequest) -> tuple[list[str], Path]:
        """Check Kometa can run, make sure its webhooks reach Studio, and build the command. Raises ValueError with the reason."""
        s = self.settings
        if s.kometa_python is None or s.kometa_entry is None or s.kometa_config is None:
            raise ValueError("Studio doesn't know where Kometa is. Set STUDIO_KOMETA_PYTHON, STUDIO_KOMETA_ENTRY and STUDIO_KOMETA_CONFIG.")
        if not s.kometa_config.exists():
            raise ValueError(f"{s.kometa_config} doesn't exist yet. Connect Plex in Settings → Plex first.")
        try:
            ensure_studio_webhooks(s.kometa_config, self.webhook_url, s.data_dir / "backups")
        except OSError as error:
            raise ValueError(f"Couldn't add Studio's webhooks to {s.kometa_config}: {error}") from None
        argv = kometa_command.build_command(s.kometa_python, s.kometa_entry, s.kometa_config, request, self.flags)
        return argv, s.kometa_entry.parent

    async def _run(self, run_id: int, request: RunRequest) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        with self.db:
            self.db.execute("UPDATE runs SET status = 'running', started_at = ? WHERE id = ?", (now(), run_id))
        active = Active(run_id, None)
        self._active = active
        afters: list[After] = []
        with open(self.log_path(run_id), "w", encoding="utf-8", buffering=1) as log:
            try:
                try:
                    argv, cwd = self._prepare(request)
                    with self.db:
                        self.db.execute("UPDATE runs SET command = ? WHERE id = ?", (kometa_command.display(argv), run_id))
                    for hook in self.hooks:
                        after = await hook.before_run(request, lambda line: self._emit(active, log, f"Kometa Studio: {line}"))
                        if after is not None:
                            afters.append(after)
                    if active.cancel_requested:
                        await self._afters(active, log, afters)
                        self._emit(active, log, "Kometa Studio: run cancelled before Kometa started")
                        self._finish(run_id, "cancelled")
                        return
                    active.started = time.time()
                    active.process = await asyncio.create_subprocess_exec(
                        *argv,
                        cwd=cwd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env=os.environ | {"PYTHONUNBUFFERED": "1"} | self.extra_env(),
                        start_new_session=True,  # its own process group, so cancelling reaches Kometa's worker too
                        limit=LINE_LIMIT,
                    )
                except (RunHeld, ValueError, OSError) as error:  # UnsupportedFlag is a ValueError
                    await self._afters(active, log, afters)
                    self._emit(active, log, f"Kometa Studio: {error}")
                    self._finish(run_id, "failed", error=str(error))
                    return

                try:
                    await asyncio.wait_for(self._pump(active, log), self.settings.run_timeout)
                except TimeoutError:
                    active.timed_out = True
                    await self._terminate(active)
                exit_code = await active.process.wait()
                await self._afters(active, log, afters)
                status, error = self._outcome(run_id, active, exit_code)
                reason = f": {error}" if error and status == "failed" and exit_code == 0 else ""
                self._emit(active, log, f"Kometa Studio: run {status.replace('_', ' ')} (exit code {exit_code}){reason}")
                # Record the outcome before ending the streams: their closing event reports it.
                self._finish(run_id, status, exit_code=exit_code, error=error)
            finally:
                self._active = None
                for subscriber in active.subscribers:
                    subscriber.send(None)

    async def _afters(self, active: Active, log, afters: list[After]) -> None:
        """Run hooks' after steps; a failing one is logged, and the others still run."""
        for after in afters:
            try:
                await after()
            except Exception as error:  # the run's outcome is Kometa's; this only gets a log line
                self._emit(active, log, f"Kometa Studio: {error}")
        afters.clear()

    def _outcome(self, run_id: int, active: Active, exit_code: int) -> tuple[str, str | None]:
        if active.timed_out:
            return "timed_out", f"Stopped after the {self.settings.run_timeout // 60} minute time limit"
        if active.cancel_requested:
            return "cancelled", None
        if exit_code != 0:
            return "failed", f"Kometa exited with code {exit_code}"
        critical = self._first_critical_error(run_id)
        if critical is None and not self._reported_finishing(run_id):
            critical = self._crash_in_kometas_log(active.started)
        if critical is not None:
            # Kometa exits 0 even when a critical error (a config error, say) stopped it doing anything.
            return "failed", critical
        return "succeeded", None

    def _reported_finishing(self, run_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM run_events WHERE run_id = ? AND event = 'run_end' LIMIT 1", (run_id,)).fetchone() is not None

    def _crash_in_kometas_log(self, since: float) -> str | None:
        """A crash before Kometa's webhooks are set up reaches only its own log, and it still exits 0."""
        assert self.settings.kometa_config is not None
        log = self.settings.kometa_config.parent / "logs" / "meta.log"
        try:
            if log.stat().st_mtime < since:
                return None  # left by an earlier run
            match = KOMETA_CRITICAL.search(log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None
        return match.group(1) if match else None

    def _first_critical_error(self, run_id: int) -> str | None:
        for (payload,) in self.db.execute("SELECT payload FROM run_events WHERE run_id = ? AND event = 'error' ORDER BY id", (run_id,)):
            data = json.loads(payload)
            if data.get("critical"):
                return str(data.get("error") or "Kometa reported a critical error")
        return None

    async def _pump(self, active: Active, log) -> None:
        assert active.process.stdout is not None
        while True:
            try:
                raw = await active.process.stdout.readline()
            except ValueError:  # a single line longer than LINE_LIMIT; skip the rest of it
                raw = b"[line too long, cut]\n"
            if not raw:
                return
            self._emit(active, log, raw.decode("utf-8", errors="replace").rstrip("\r\n"))

    def _emit(self, active: Active, log, line: str) -> None:
        """Write a line to the run's log and to everyone following it live."""
        log.write(line + "\n")
        if LOG_WARNING.search(line) and not LOG_ERROR.search(line):
            active.warnings += 1
        for subscriber in list(active.subscribers):
            subscriber.send(line)
            if subscriber.dropped:
                active.subscribers.discard(subscriber)

    async def _terminate(self, active: Active) -> None:
        process = active.process
        if process is None or process.returncode is not None:  # not started yet: the cancel flag stops it starting
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), self.settings.kill_after)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def read_tail(path: Path, max_bytes: int = 256 * 1024) -> tuple[list[str], bool]:
    """The last lines of a log, and whether earlier ones were left out."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()  # drop the partial first line
            data = handle.read()
    except FileNotFoundError:
        return [], False
    return data.decode("utf-8", errors="replace").splitlines(), size > max_bytes
