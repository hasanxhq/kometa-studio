import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.db import open_database
from kometa_studio.kometa_command import RunRequest
from kometa_studio.runner import Runner
from kometa_studio.scheduler import Due, Scheduler, When, coalesce, covers, days_to_mask, utc_text
from kometa_studio.settings import Settings

EVERY_DAY = 0b1111111
KOLKATA = "Asia/Kolkata"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# --- Schedule maths ------------------------------------------------------------


def test_every_day_at_three_in_kolkata():
    when = When(EVERY_DAY, "03:00", KOLKATA)
    found = when.occurrences(utc("2026-10-29 00:00"), utc("2026-11-01 00:00"))
    # 03:00 IST is 21:30 UTC the day before.
    assert found == [utc("2026-10-29 21:30"), utc("2026-10-30 21:30"), utc("2026-10-31 21:30")]


def test_only_on_chosen_days():
    when = When(days_to_mask([1, 5]), "05:30", "UTC")  # Tuesday and Saturday
    found = when.occurrences(utc("2026-10-26 00:00"), utc("2026-11-02 00:00"))  # Monday to Monday
    assert found == [utc("2026-10-27 05:30"), utc("2026-10-31 05:30")]


def test_a_time_skipped_by_spring_forward_runs_an_hour_later():
    when = When(EVERY_DAY, "02:30", "America/New_York")
    [found] = when.occurrences(utc("2026-03-08 00:00"), utc("2026-03-08 23:59"))
    assert found == utc("2026-03-08 07:30")  # 03:30 EDT: 02:30 doesn't exist that night


def test_a_time_repeated_by_fall_back_runs_once():
    when = When(EVERY_DAY, "01:30", "America/New_York")
    assert when.occurrences(utc("2026-11-01 00:00"), utc("2026-11-01 23:59")) == [utc("2026-11-01 05:30")]  # the first 01:30, EDT


def test_occurrences_exclude_the_start_and_include_the_end():
    when = When(EVERY_DAY, "03:00", "UTC")
    assert when.occurrences(utc("2026-10-30 03:00"), utc("2026-10-31 03:00")) == [utc("2026-10-31 03:00")]


def test_next_run():
    when = When(days_to_mask([6]), "04:00", "UTC")  # Sundays
    assert when.next_after(utc("2026-10-30 12:00")) == utc("2026-11-01 04:00")


# --- Coalescing ----------------------------------------------------------------


def due(schedule_id, **request):
    return Due(schedule_id, RunRequest(**request), "schedule")


def test_everything_replaces_what_it_covers_and_the_rest_keeps_kometas_order():
    kept = coalesce(
        [
            due(1, mode="playlists"),
            due(2, mode="collections", libraries=["Movies"]),
            due(3, mode="all", libraries=["Movies"]),
            due(4, mode="overlays", libraries=["TV Shows"]),
            due(5, mode="operations"),
        ]
    )
    assert [(d.schedule_id, d.request.mode) for d in kept] == [(3, "all"), (5, "operations"), (4, "overlays"), (1, "playlists")]


def test_everything_for_all_libraries_replaces_every_plain_run():
    kept = coalesce([due(1, mode="collections"), due(2, mode="all"), due(3, mode="overlays", libraries=["Movies"])])
    assert [d.schedule_id for d in kept] == [2]


@pytest.mark.parametrize(
    "narrow",
    [
        {"mode": "collections", "libraries": ["TV Shows"]},  # another library
        {"mode": "collections"},  # every library, wider than Movies
        {"mode": "collections", "libraries": ["Movies"], "timings": True},  # different options
    ],
)
def test_everything_for_one_library_does_not_swallow_other_work(narrow):
    assert not covers(RunRequest(mode="all", libraries=["Movies"]), RunRequest(**narrow))


def test_a_filtered_everything_run_covers_nothing():
    assert not covers(RunRequest(mode="all", collections=["Trending"]), RunRequest(mode="collections"))


# --- Ticks ---------------------------------------------------------------------


@pytest.fixture
def world(tmp_path):
    db = open_database(tmp_path / "studio.db")
    runner = Runner(db, Settings(data_dir=tmp_path), "http://127.0.0.1:8484/api/v1/kometa/events?token=t")
    return db, runner, Scheduler(db, runner)


def add_schedule(db, *, time="03:00", timezone="UTC", days=EVERY_DAY, last_fired="2026-10-29 12:00", catch_up="run_once", enabled=True, **request):
    with db:
        return db.execute(
            "INSERT INTO schedules (name, request, days, time, timezone, enabled, catch_up, last_fired_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test", RunRequest(**request).model_dump_json(), days, time, timezone, enabled, catch_up, utc_text(utc(last_fired))),
        ).lastrowid


def queued(db):
    return [(r["trigger"], r["schedule_id"], json.loads(r["request"])["mode"]) for r in db.execute("SELECT * FROM runs ORDER BY id")]


def test_an_on_time_run_fires_once(world):
    db, _, scheduler = world
    schedule = add_schedule(db, mode="collections")
    assert scheduler.tick(utc("2026-10-30 02:59:50")) == []
    assert len(scheduler.tick(utc("2026-10-30 03:00:20"))) == 1
    assert scheduler.tick(utc("2026-10-30 03:00:50")) == []
    assert queued(db) == [("schedule", schedule, "collections")]
    assert db.execute("SELECT last_fired_at FROM schedules").fetchone()[0] == "2026-10-30T03:00:00Z"


def test_days_of_downtime_give_one_catch_up_run(world):
    db, _, scheduler = world
    schedule = add_schedule(db, last_fired="2026-10-27 12:00")  # missed the 28th, 29th and 30th
    scheduler.tick(utc("2026-10-30 09:00"))
    scheduler.tick(utc("2026-10-30 09:00:30"))
    assert queued(db) == [("catch_up", schedule, "all")]


def test_catch_up_can_be_switched_off(world):
    db, _, scheduler = world
    add_schedule(db, catch_up="skip")
    scheduler.tick(utc("2026-10-30 09:00"))
    assert queued(db) == []
    scheduler.tick(utc("2026-10-31 03:00:10"))  # the next one still runs
    assert queued(db) == [("schedule", 1, "all")]


def test_missed_runs_older_than_a_day_are_dropped(world):
    db, _, scheduler = world
    add_schedule(db, days=days_to_mask([0]), last_fired="2026-10-25 12:00")  # Mondays; the 26th was missed
    scheduler.tick(utc("2026-10-30 09:00"))
    assert queued(db) == []
    assert db.execute("SELECT last_fired_at FROM schedules").fetchone()[0] == "2026-10-26T03:00:00Z"


def test_disabled_schedules_do_nothing(world):
    db, _, scheduler = world
    add_schedule(db, enabled=False)
    assert scheduler.tick(utc("2026-10-30 03:00:10")) == []


def test_schedules_firing_together_are_coalesced(world):
    db, _, scheduler = world
    add_schedule(db, mode="overlays")
    add_schedule(db, mode="operations")
    add_schedule(db, mode="collections", libraries=["Movies"])
    scheduler.tick(utc("2026-10-30 03:00:10"))
    assert [mode for _, _, mode in queued(db)] == ["operations", "collections", "overlays"]


def test_a_request_already_waiting_is_not_queued_again(world):
    db, runner, scheduler = world
    runner.enqueue(RunRequest(mode="collections"))
    add_schedule(db, mode="collections")
    scheduler.tick(utc("2026-10-30 03:00:10"))
    assert queued(db) == [("manual", None, "collections")]


# --- API and start-up ----------------------------------------------------------


def make_client(tmp_path, **settings):
    app = create_app(Settings(data_dir=tmp_path / "data", timezone=KOLKATA, **settings), static_dir=tmp_path / "no-static")
    return TestClient(app)


def test_creating_and_editing_schedules(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/v1/schedules", json={"name": "Nightly collections", "request": {"mode": "collections"}, "days": [6, 0, 0], "time": "03:00"}
        )
        assert created.status_code == 201
        schedule = created.json()
        assert (schedule["days"], schedule["timezone"], schedule["catch_up"], schedule["enabled"]) == ([0, 6], KOLKATA, "run_once", True)
        assert schedule["next_run"] is not None

        listed = client.get("/api/v1/schedules").json()
        assert listed["timezone"] == KOLKATA
        assert [s["name"] for s in listed["schedules"]] == ["Nightly collections"]

        edited = client.put(f"/api/v1/schedules/{schedule['id']}", json={**schedule, "time": "04:15", "enabled": False}).json()
        assert (edited["time"], edited["next_run"]) == ("04:15", None)

        run = client.post(f"/api/v1/schedules/{schedule['id']}/run").json()
        assert (run["trigger"], run["schedule_id"], run["request"]["mode"]) == ("manual", schedule["id"], "collections")

        assert client.delete(f"/api/v1/schedules/{schedule['id']}").status_code == 204
        assert client.get("/api/v1/schedules").json()["schedules"] == []
        assert client.get(f"/api/v1/runs/{run['id']}").json()["schedule_id"] is None


@pytest.mark.parametrize(
    "bad",
    [{"time": "3am"}, {"time": "24:00"}, {"days": []}, {"days": [7]}, {"timezone": "Mars/Olympus"}, {"name": "  "}],
)
def test_bad_schedules_are_refused(tmp_path, bad):
    body = {"name": "x", "days": [0], "time": "03:00"} | bad
    with make_client(tmp_path) as client:
        assert client.post("/api/v1/schedules", json=body).status_code == 422


def test_status_shows_the_next_scheduled_run(tmp_path):
    with make_client(tmp_path) as client:
        client.post("/api/v1/schedules", json={"name": "Nightly", "days": list(range(7)), "time": "03:00"})
        next_run = client.get("/api/v1/status").json()["runs"]["next_scheduled"]
    assert next_run["name"] == "Nightly"
    assert next_run["at"].endswith(":30:00Z")  # 03:00 in Kolkata


def test_restarting_across_a_scheduled_time_gives_exactly_one_catch_up_run(tmp_path):
    """Milestone 4's "done when", with the downtime faked by moving last_fired_at back."""
    now = datetime.now(UTC)
    an_hour_ago = (now - timedelta(hours=1)).strftime("%H:%M")
    with make_client(tmp_path) as client:
        client.post("/api/v1/schedules", json={"name": "Hourly test", "days": list(range(7)), "time": an_hour_ago, "timezone": "UTC"})
    db = open_database(tmp_path / "data" / "studio.db")
    with db:  # Studio "stopped" two hours ago, before the scheduled time
        db.execute("UPDATE schedules SET last_fired_at = ?", (utc_text(now - timedelta(hours=2)),))
    db.close()

    for _ in range(2):  # starting twice must not queue a second catch-up
        with make_client(tmp_path) as client:
            runs = client.get("/api/v1/runs").json()["runs"]
            catch_ups = client.get("/api/v1/schedules").json()["catch_ups"]

    assert [r["trigger"] for r in runs] == ["catch_up"]
    assert [c["name"] for c in catch_ups] == ["Hourly test"]
