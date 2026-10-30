import asyncio
import os
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakearr import RADARR_KEY, RADARR_URL, FakeArr

from kometa_studio import arr, wanted
from kometa_studio.arr import Arr
from kometa_studio.crypto import SecretBox
from kometa_studio.db import get_setting, open_database, set_setting
from kometa_studio.kometa_command import RunRequest

T0 = datetime(2026, 10, 30, 20, 0, tzinfo=UTC)

COLLECTIONS = """\
templates:
  filter:
    plex_all: true
    filters:
      country: <<key>>
collections:
  Unwatched:
    smart_filter:
      all:
        unplayed: true
  Recently Added:
    plex_search:
      all:
        added: 30
  Oscar Winners:
    tmdb_list: 8204
  Trilogy:
    tmdb_movie: 603, 604
  Norway:
    template: {name: filter, key: Norway}
  Weekly Picks:
    mdblist_list: https://mdblist.com/lists/me/picks
    schedule: weekly(sunday)
dynamic_collections:
  Genres:
    type: genre
"""


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "kometa"
    (root / "config").mkdir(parents=True)
    (root / "config" / "movies.yml").write_text(COLLECTIONS)
    (root / "config" / "lists.yml").write_text("collections:\n  Oscar Winners:\n    tmdb_list: 8204\n")
    path = root / "config" / "config.yml"
    path.write_text(
        "settings:\n  save_report: true\n"
        "libraries:\n"
        "  Movies:\n    collection_files:\n      - file: config/movies.yml\n"
        "  Lists Only:\n    library_name: Films\n    collection_files:\n      - file: config/lists.yml\n"
        "  Posters:\n    overlay_files:\n      - default: resolution\n"
        f"radarr:\n  url: {RADARR_URL}\n  token: {RADARR_KEY}\n"
    )
    return path


@pytest.fixture
def db(tmp_path):
    connection = open_database(tmp_path / "studio.db")
    yield connection
    connection.close()


def test_collections_are_sorted_by_what_they_are_built_from(config):
    plans = wanted.plan(config, config.parent.parent)
    movies = plans["Movies"]
    # Smart collections update themselves; Plex searches (also through a template, or a dynamic default) catch anything.
    assert movies.rule == ["Recently Added", "Norway", "Genres"]
    assert movies.lists == ["Oscar Winners", "Trilogy", "Weekly Picks"]
    assert movies.ids == {"tmdb-movie:603": ["Trilogy"], "tmdb-movie:604": ["Trilogy"]}
    assert movies.scheduled == {"Weekly Picks"}
    assert movies.reports is True and movies.report_path == config.parent / "Movies_report.yml"
    assert (plans["Lists Only"].plex_name, plans["Posters"].overlays) == ("Films", True)


def rows(db, sql):
    return [tuple(row) for row in db.execute(sql).fetchall()]


def report(config, library, text):
    path = config.parent / f"{library}_report.yml"
    path.write_text(text)
    return path


def test_a_library_is_unknown_until_kometa_reports_on_all_its_collections(config, db):
    plans = wanted.plan(config, config.parent.parent)
    lists = plans["Lists Only"]
    assert wanted.decide(db, lists, "all", ["tmdb-movie:1"]).reason == "Kometa hasn't reported on its collections yet"

    started = time.time() - 1
    report(config, "Lists Only", "Oscar Winners:\n  Movies Missing (TMDb IDs):\n    872585: Oppenheimer\n")
    assert wanted.ingest(db, plans, RunRequest(mode="collections"), started, 7, T0) == ["Movies", "Lists Only"]

    hit = wanted.decide(db, lists, "all", ["tmdb-movie:872585"])
    assert (hit.whole, hit.collections, hit.reason) == (False, ["Oscar Winners"], "wanted by “Oscar Winners”")
    assert wanted.decide(db, lists, "all", ["tmdb-movie:1"]) is None  # nobody wants it

    # Change the files and Studio stops trusting its copy.
    (config.parent / "lists.yml").write_text("collections:\n  Oscar Winners:\n    tmdb_list: 9999\n")
    changed = wanted.plan(config, config.parent.parent)["Lists Only"]
    assert wanted.decide(db, changed, "all", ["tmdb-movie:1"]).reason == "its collection files changed since Kometa's last report"


def test_overlays_and_plex_searches_need_the_whole_library(config, db):
    plans = wanted.plan(config, config.parent.parent)
    assert wanted.decide(db, plans["Posters"], "all", ["tmdb-movie:1"]).reason == "its overlays need drawing"
    assert wanted.decide(db, plans["Posters"], "collections", ["tmdb-movie:1"]) is None  # no collections there
    movies = wanted.decide(db, plans["Movies"], "collections", ["tmdb-movie:603"])
    assert movies.whole is True and movies.collections == ["Trilogy"]
    assert "“Recently Added”, “Norway”, “Genres” search Plex" in movies.reason


def test_a_full_pass_clears_what_isnt_missing_any_more_but_keeps_scheduled_collections(config, db):
    plans = wanted.plan(config, config.parent.parent)
    first = time.time() - 1
    report(config, "Movies", "Oscar Winners:\n  Movies Missing (TMDb IDs):\n    1: One\nWeekly Picks:\n  Movies Missing (TMDb IDs):\n    2: Two\n")
    wanted.ingest(db, plans, RunRequest(mode="all", libraries=["Movies"]), first, 1, T0)
    assert rows(db, "SELECT collection, item FROM wanted ORDER BY item") == [("Oscar Winners", "tmdb-movie:1"), ("Weekly Picks", "tmdb-movie:2")]

    # The next run writes no report: nothing is missing. "Weekly Picks" may not have run (its own schedule), so it's kept.
    os.utime(config.parent / "Movies_report.yml", (first - 60, first - 60))
    wanted.ingest(db, plans, RunRequest(mode="all", libraries=["Movies"]), time.time() - 1, 2, T0)
    assert rows(db, "SELECT collection FROM wanted") == [("Weekly Picks",)]

    # A run of one collection replaces only that one.
    report(config, "Movies", "Weekly Picks:\n  Movies Missing (TMDb IDs):\n    3: Three\n")
    wanted.ingest(db, plans, RunRequest(mode="collections", collections=["Weekly Picks"]), time.time() - 1, 3, T0)
    assert rows(db, "SELECT item FROM wanted") == [("tmdb-movie:3",)]


def test_runs_that_skip_collections_or_missing_items_change_nothing(config, db):
    plans = wanted.plan(config, config.parent.parent)
    report(config, "Movies", "Oscar Winners:\n  Movies Missing (TMDb IDs):\n    1: One\n")
    assert wanted.ingest(db, plans, RunRequest(mode="overlays"), time.time() - 1, 1, T0) == []
    assert wanted.ingest(db, plans, RunRequest(mode="all", no_missing=True), time.time() - 1, 1, T0) == []


def test_the_recorder_waits_for_run_end(config, db):
    class Runner:
        current_run_id = 5

    recorder = wanted.WantedRecorder(db, Runner(), config, config.parent.parent)
    said = []

    async def scenario():
        after = await recorder.before_run(RunRequest(mode="collections", libraries=["Lists Only"]), said.append)
        report(config, "Lists Only", "Oscar Winners:\n  Movies Missing (TMDb IDs):\n    872585: Oppenheimer\n")
        await after()  # no run_end: the run didn't go through
        assert db.execute("SELECT COUNT(*) FROM wanted").fetchone()[0] == 0
        db.execute("INSERT INTO runs (id, request, status, trigger, queued_at) VALUES (5, '{}', 'running', 'manual', '2026-10-30T20:00:00Z')")
        db.execute("INSERT INTO run_events (run_id, event, payload) VALUES (5, 'run_end', '{}')")
        await after()

    asyncio.run(scenario())
    assert rows(db, "SELECT item FROM wanted") == [("tmdb-movie:872585",)]
    assert said == ["noted what the collections in Lists Only want, for runs after imports"]


# --- With Radarr ---------------------------------------------------------------------


class RecordingRunner:
    def __init__(self) -> None:
        self.queued: list[RunRequest] = []

    def enqueue(self, request: RunRequest, trigger: str = "manual") -> int:
        self.queued.append(request)
        return len(self.queued)


def test_only_relevant_imports_run_kometa_and_only_for_the_collections_that_want_them(config, db, tmp_path):
    plans = wanted.plan(config, config.parent.parent)
    report(config, "Lists Only", "Oscar Winners:\n  Movies Missing (TMDb IDs):\n    872585: Oppenheimer\n")
    wanted.ingest(db, plans, RunRequest(mode="collections", libraries=["Lists Only"]), time.time() - 1, 1, T0)
    set_setting(db, arr.RUNS, {"radarr": {"enabled": True, "trigger": "relevant", "libraries": ["Lists Only"]}})
    fake = FakeArr()

    async def scenario():
        async with httpx.AsyncClient(transport=fake.transport()) as http:
            service = Arr(db, RecordingRunner(), http, SecretBox.load_or_create(tmp_path / "data"), config, config.parent.parent)
            await service.poll(T0)
            fake.imported("radarr", "Oppenheimer", 2023, T0 + timedelta(minutes=1), tmdbId=872585)
            fake.imported("radarr", "Paddington 2", 2017, T0 + timedelta(minutes=1), tmdbId=346648)
            await service.poll(T0 + timedelta(minutes=2))
            service.tick(T0 + timedelta(minutes=20))
            return service

    service = asyncio.run(scenario())
    assert service.runner.queued == [RunRequest(mode="collections", libraries=["Lists Only"], collections=["Oscar Winners"])]
    assert get_setting(db, arr.skipped_key("radarr")) == [{"at": "2026-10-30T20:02:00Z", "title": "Paddington 2 (2017)", "libraries": "Lists Only"}]


def test_every_import_counts_when_studio_cant_read_the_config(db, tmp_path):
    set_setting(db, arr.RUNS, {"radarr": {"enabled": True, "trigger": "relevant"}})
    service = Arr(db, RecordingRunner(), None, None, tmp_path / "missing.yml")
    asyncio.run(service._count("radarr", arr.load_settings(db).radarr, [{"id": 1, "movie": {"title": "Flow", "year": 2024, "tmdbId": 1}}], T0))
    service.tick(T0 + timedelta(minutes=20))
    assert service.runner.queued == [RunRequest(mode="all")]


def test_the_connect_page_says_what_studio_knows_and_can_turn_on_the_report(tmp_path):
    from fastapi.testclient import TestClient

    from kometa_studio.app import create_app
    from kometa_studio.settings import Settings

    config = tmp_path / "config.yml"
    config.write_text("libraries:\n  Movies:\n    collection_files:\n      - file: lists.yml\n")
    (tmp_path / "lists.yml").write_text("collections:\n  Oscar Winners:\n    tmdb_list: 8204\n")
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config, kometa_entry=tmp_path / "kometa.py"), static_dir=tmp_path / "no-static")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        before = client.get("/api/v1/settings/arr").json()["libraries"]
        after = client.post("/api/v1/settings/arr/reports").json()["libraries"]
    assert before == [
        {"library": "Movies", "reports": False, "reported_at": None, "changed": False, "wanted": 0, "ids": 0, "lists": 1, "rule": [], "unreadable": [], "overlays": False}
    ]
    assert after[0]["reports"] is True
    assert "save_report: true" in config.read_text()
