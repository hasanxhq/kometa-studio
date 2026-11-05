"""Download missing: collections that request the titles they lack, now and after later runs.

A collection row (builder or ready-made) with ``download_missing`` on asks ``RequestService`` for its missing titles.
What it's missing comes from the list preview when it's saved (builder lists Studio can read), and after every run from
Kometa's missing report (the ``wanted`` table, keyed by the collection's Kometa name). Studio turns that report on
(``settings.save_report``) by itself when any collection needs it: Studio fully manages Kometa's config.

A title is asked for once: anything already in ``requests`` for it (requested, imported, already in the app, failed or
cancelled) isn't asked for again. After a run, up to ``confirm_over`` new titles are requested on their own; more than
that wait for the user's go-ahead (``waiting`` on the card, and ``POST /collections/{id}/request-missing``).

When a requested title reaches Plex (``RequestService`` labels it ``starr``), ``rebuild_arrived`` queues a run of just
the collection that asked for it, so the collection fills itself without waiting for a scheduled run.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from .config_sections import read_section, save_section
from .config_write import ConfigWriter, SaveRefused
from . import collections as col
from .kometa_command import RunRequest
from .requesting import Item, RequestOutcome, RequestService, RequestsDisabled, load_settings

log = logging.getLogger(__name__)

SUMMARY_STATUSES = ("requested", "downloading", "imported", "failed")


def _row(db: sqlite3.Connection, row_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM collections WHERE id = ?", (row_id,)).fetchone()


def waiting(db: sqlite3.Connection, row: sqlite3.Row) -> list[Item]:
    """What Kometa last reported this collection missing that Studio has never asked for."""
    found = db.execute(
        """
        SELECT w.item, w.title FROM wanted w
        WHERE w.library = ? AND w.collection = ? AND NOT EXISTS (SELECT 1 FROM requests r WHERE r.item = w.item)
        ORDER BY w.item
        """,
        (row["library"], row["kometa_name"]),
    ).fetchall()
    return [Item(item=r["item"], title=r["title"]) for r in found]


def summary(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, int]:
    """Counts for the card: titles waiting for a go-ahead, and this collection's requests by status."""
    counts = dict.fromkeys(SUMMARY_STATUSES, 0)
    for status, count in db.execute("SELECT status, count(*) FROM requests WHERE collection_id = ? GROUP BY status", (int(row["id"]),)):
        if status in counts:
            counts[status] = int(count)
    wants = len(waiting(db, row)) if row["download_missing"] else 0
    return {"waiting": wants, **counts}


def set_download_missing(
    db: sqlite3.Connection, ids: list[int], on: bool, cap: int | None = None, profile: str | None = None, *, keep_cap: bool = False
) -> None:
    """Turn Download missing on or off. ``keep_cap`` leaves the collection's cap and quality profile as they are."""
    for row_id in ids:
        if keep_cap:
            db.execute("UPDATE collections SET download_missing = ? WHERE id = ?", (int(on), row_id))
        else:
            db.execute(
                "UPDATE collections SET download_missing = ?, request_cap = ?, request_profile = ? WHERE id = ?",
                (int(on), cap, profile or None, row_id),
            )


def reports_on(writer: ConfigWriter) -> bool:
    return bool((read_section(writer.config_path, "settings") or {}).get("save_report"))


async def ensure_reports(writer: ConfigWriter) -> bool:
    """Turn on Kometa's missing report if it's off. True if Studio changed config.yml."""
    if reports_on(writer):
        return False
    await save_section(writer, "settings", {"save_report": True}, "Turned on Kometa's missing report, for collections that download what they're missing")
    return True


async def request_items(service: RequestService, db: sqlite3.Connection, row: sqlite3.Row, items: list[Item]) -> RequestOutcome:
    cap = row["request_cap"]
    return await service.request(
        items, row["library"], int(row["id"]), datetime.now(UTC), cap=int(cap) if cap is not None else None, profile=row["request_profile"]
    )


def arrived(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Collections a requested title reached Plex for after their last run was queued (or that never ran).

    Keyed on the last run rather than a flag, so a restart doesn't lose one, and a run that fails isn't retried
    every few minutes: the next import or the user's Retry builds it again.
    """
    return db.execute(
        """
        SELECT c.*, MAX(r.labelled_at) AS arrived_at
        FROM requests r
        JOIN collections c ON c.id = r.collection_id
        LEFT JOIN runs ON runs.id = c.last_run_id
        WHERE r.labelled_at IS NOT NULL AND c.desired = 1
        GROUP BY c.id
        HAVING MAX(runs.queued_at) IS NULL OR MAX(r.labelled_at) > MAX(runs.queued_at)
        ORDER BY c.library, c.id
        """
    ).fetchall()


def rebuild_arrived(db: sqlite3.Connection, runner) -> list[int]:
    """Queue one run per library for the collections whose requested titles are now in Plex. Returns the run ids."""
    by_library: dict[str, list[sqlite3.Row]] = {}
    for row in arrived(db):
        by_library.setdefault(row["library"], []).append(row)
    run_ids = []
    for library, rows in by_library.items():
        run_id = runner.enqueue(
            RunRequest(mode="collections", libraries=[library], collections=[r["kometa_name"] for r in rows]), trigger="requests"
        )
        with db:
            col.set_run(db, [int(r["id"]) for r in rows], run_id)
        log.info("Requested titles reached Plex; rebuilding %s in %s", ", ".join(repr(r["title"]) for r in rows), library)
        run_ids.append(run_id)
    return run_ids


class MissingRequester:
    """Run hook: make sure Kometa writes its missing report, then request what collections with Download missing lack.

    Goes after ``WantedRecorder``, whose after step fills ``wanted`` from the report.
    """

    def __init__(self, db: sqlite3.Connection, writer: ConfigWriter | None, service: RequestService):
        self.db = db
        self.writer = writer
        self.service = service

    def _rows(self, request: RunRequest) -> list[sqlite3.Row]:
        rows = self.db.execute("SELECT * FROM collections WHERE download_missing = 1 AND desired = 1").fetchall()
        return [r for r in rows if not request.libraries or r["library"] in request.libraries]

    async def before_run(self, request: RunRequest, say):
        if not load_settings(self.db).enabled or not self._rows(request):
            return None
        if self.writer is not None:
            try:
                if await ensure_reports(self.writer):
                    say("turned on Kometa's missing report, so collections can download what they're missing")
            except SaveRefused as refused:
                log.warning("Couldn't turn on Kometa's missing report: %s", refused.detail())

        async def after() -> None:
            settings = load_settings(self.db)
            if not settings.enabled:
                return
            for row in self._rows(request):
                items = waiting(self.db, row)
                if not items:
                    continue
                if len(items) > settings.confirm_over:
                    say(f"{row['title']} is missing {len(items)} titles; they wait for your go-ahead on its card")
                    continue
                try:
                    outcome = await request_items(self.service, self.db, row, items)
                except RequestsDisabled:
                    return
                if outcome.requested:
                    say(f"requested {outcome.requested} missing title{'s' if outcome.requested != 1 else ''} for {row['title']}")

        return after
