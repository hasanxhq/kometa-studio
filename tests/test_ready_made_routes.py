"""Ready-made gallery, build/remove, Plex state after runs, and the counting task."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import httpx
import pytest
from fakemaintainerr import MAINTAINERR_URL, FakeMaintainerr
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex
from fastapi.testclient import TestClient

from starr_studio import collections as col
from starr_studio.app import create_app
from starr_studio.kometa_command import RunRequest
from starr_studio.ready_made_runs import ReadyMadeRecorder
from starr_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
DEFAULTS_SRC = Path(__file__).parent / "fixtures" / "ready_made_defaults" / "defaults"
FINISHED = {"succeeded", "failed", "cancelled", "interrupted", "timed_out"}


@pytest.fixture
def root(tmp_path: Path):
    """Kometa root with fake entry + ready-made defaults, and a Movies library in config.yml."""
    kometa = tmp_path / "kometa"
    kometa.mkdir()
    shutil.copy(FAKE_KOMETA, kometa / "kometa.py")
    shutil.copytree(DEFAULTS_SRC, kometa / "defaults")
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yml").write_text(
        f"plex:\n  url: {REMOTE_URI}\n  token: {SERVER_TOKEN}\n"
        "tmdb:\n  apikey: k\n"
        "libraries:\n  Movies: {}\n"
    )
    (config / "fake.json").write_text(json.dumps({"lines": ["ok"], "exit": 0}))
    return tmp_path


def make_client(root: Path, plex: FakePlex | None = None, maintainerr: FakeMaintainerr | None = None):
    plex = plex or FakePlex()
    maintainerr = maintainerr or FakeMaintainerr()

    def handle(request: httpx.Request) -> httpx.Response:
        return maintainerr.handle(request) if request.url.host == "maintainerr.test" else plex.handle(request)

    settings = Settings(
        data_dir=root / "data",
        kometa_python=Path(sys.executable),
        kometa_entry=root / "kometa" / "kometa.py",
        kometa_config=root / "config" / "config.yml",
        kill_after=0.5,
    )
    app = create_app(settings, static_dir=root / "no-static", http_transport=httpx.MockTransport(handle))
    client = TestClient(app, client=("127.0.0.1", 50000))
    return client, plex, maintainerr


def wait_for_flags(client):
    deadline = time.monotonic() + 15
    while client.get("/api/v1/kometa").json()["flags"] is None:
        assert time.monotonic() < deadline
        time.sleep(0.05)


def wait_for_run(client, run_id, statuses=FINISHED, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} still {run['status']}")


def wait_for_task(client, name, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = next(t for t in client.get("/api/v1/tasks").json()["tasks"] if t["name"] == name)
        if not task["running"] and task["last"] and task["last"]["status"] != "running":
            return task
        time.sleep(0.05)
    raise AssertionError(f"{name} still running")


def test_gallery_and_category_shapes(root):
    with make_client(root)[0] as client:
        wait_for_task(client, "ready_made_counts")  # startup count
        gallery = client.get("/api/v1/ready-made/libraries/Movies").json()
        assert gallery["library"] == "Movies"
        assert gallery["library_type"] == "movie"
        assert gallery["counting"] is False
        assert gallery["counted_at"]
        basic = next(c for c in gallery["categories"] if c["name"] == "basic")
        assert basic["kind"] == "fixed" and basic["count"] == 1 and basic["picked"] == 0
        genre = next(c for c in gallery["categories"] if c["name"] == "genre")
        assert genre["count"] is not None and genre["count"] >= 1

        detail = client.get("/api/v1/ready-made/libraries/Movies/categories/basic").json()
        assert detail["name"] == "basic"
        assert len(detail["collections"]) == 1
        entry = detail["collections"][0]
        assert entry["key"] == "Newly Released"
        assert entry["state"] == "none"
        assert entry["id"] is None and entry["desired"] is None


def test_dry_run_changes_nothing(root):
    client, plex, _ = make_client(root)
    with client:
        wait_for_flags(client)
        before_files = list((root / "config").rglob("*.yml"))
        before_deletes = list(plex.deletions)
        body = {
            "library": "Movies",
            "add": [{"category": "basic", "block": "", "key": "Newly Released"}],
            "remove": [],
            "dry_run": True,
        }
        plan = client.post("/api/v1/ready-made/build", json=body).json()
        assert plan["build"] == [{"category": "basic", "title": "Newly Released"}]
        assert plan["run"]["libraries"] == ["Movies"]
        assert "Newly Released" in plan["run"]["collections"]
        assert "run_id" not in plan
        assert col.rows(client.app.state.db, "Movies") == []
        assert list((root / "config").rglob("*.yml")) == before_files
        assert plex.deletions == before_deletes
        assert client.get("/api/v1/runs").json()["runs"] == []


def test_build_writes_files_queues_run_and_marks_rows(root):
    client, plex, _ = make_client(root)
    with client:
        wait_for_flags(client)
        # Cancel any startup count so it doesn't fight the queue.
        body = {
            "library": "Movies",
            "add": [{"category": "basic", "block": "", "key": "Newly Released"}],
            "remove": [],
            "dry_run": False,
        }
        result = client.post("/api/v1/ready-made/build", json=body).json()
        assert result["run_id"] is not None
        assert result["removed"] == [] and result["kept"] == []
        studio = root / "config" / "studio" / "Movies" / "basic.yml"
        assert studio.is_file()
        text = (root / "config" / "config.yml").read_text()
        assert "studio/Movies/basic.yml" in text or "studio/Movies/basic" in text
        rows = col.rows(client.app.state.db, "Movies", "basic")
        assert len(rows) == 1 and rows[0]["desired"] == 1 and rows[0]["last_run_id"] == result["run_id"]
        run = wait_for_run(client, result["run_id"])
        assert run["trigger"] == "ready-made"
        assert run["request"]["mode"] == "collections"
        assert run["request"]["libraries"] == ["Movies"]
        assert run["request"]["collections"] == ["Newly Released"]
        assert "--run-libraries" in run["command"] and "--run-collections" in run["command"]
        assert "--collections-only" in run["command"]
        # Only one ready-made run was queued for this build.
        ready = [r for r in client.get("/api/v1/runs").json()["runs"] if r["trigger"] == "ready-made"]
        assert len(ready) == 1


def test_refused_save_rolls_rows_back(root):
    # Inject a default whose body makes fake Kometa refuse validation.
    broken = root / "kometa" / "defaults" / "chart" / "broken.yml"
    broken.write_text(
        "#####\n# Broken #\n#####\n\ncollections:\n  Broken Pick:\n    tmdb_movie: BROKEN\n"
    )
    client, _, _ = make_client(root)
    with client:
        wait_for_flags(client)
        before = col.rows(client.app.state.db, "Movies")
        response = client.post(
            "/api/v1/ready-made/build",
            json={
                "library": "Movies",
                "add": [{"category": "broken", "block": "", "key": "Broken Pick"}],
                "remove": [],
                "dry_run": False,
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "message" in detail and detail.get("validation") is not None
        assert col.rows(client.app.state.db, "Movies") == before
        assert not (root / "config" / "studio" / "Movies" / "broken.yml").exists()


def test_remove_only_studio_labelled_never_maintainerr_or_unlabelled(root):
    plex = FakePlex()
    # Unlabelled same title as a Studio pick we'll try to remove.
    plex.add_collection("1", "Hand Made Twin", labels=[], items=1)
    maintainerr = FakeMaintainerr()
    # Spy Kids is Maintainerr's; Studio Chart is Studio-labelled.
    client, plex, maintainerr = make_client(root, plex, maintainerr)
    with client:
        wait_for_flags(client)
        connect = client.put("/api/v1/settings/maintainerr", json={"url": MAINTAINERR_URL, "leave_overlays_alone": False})
        assert connect.status_code == 200, connect.text

        db = client.app.state.db
        with db:
            ids = col.mark_present(
                db,
                "Movies",
                [
                    col.Pick(col.Ref("basic", "", "Studio Chart"), "Studio Chart", "Studio Chart"),
                    col.Pick(col.Ref("basic", "", "Spy Kids"), "Spy Kids", "Spy Kids"),
                    col.Pick(col.Ref("basic", "", "Hand Made Twin"), "Hand Made Twin", "Hand Made Twin"),
                    col.Pick(col.Ref("basic", "", "Gone Already"), "Gone Already", "Gone Already"),
                ],
            )
            # Pretend they're in Plex (except Gone Already).
            for row_id, key in zip(ids[:3], ["104", "102", None], strict=False):
                if key:
                    col.record_plex_state(db, row_id, exists=True, rating_key=key, items=1, thumb=None, built=True, error=None)

        # Hand Made Twin: same title in Plex without Studio label (we added it).
        twin_key = next(c["ratingKey"] for c in plex.COLLECTIONS["1"] if c["title"] == "Hand Made Twin")
        with db:
            col.record_plex_state(db, ids[2], exists=True, rating_key=twin_key, items=1, thumb=None, built=True, error=None)

        result = client.post(
            "/api/v1/ready-made/build",
            json={
                "library": "Movies",
                "add": [],
                "remove": [
                    {"category": "basic", "block": "", "key": "Studio Chart"},
                    {"category": "basic", "block": "", "key": "Spy Kids"},
                    {"category": "basic", "block": "", "key": "Hand Made Twin"},
                    {"category": "basic", "block": "", "key": "Gone Already"},
                ],
                "dry_run": False,
            },
        ).json()

        assert "Studio Chart" in result["removed"]
        assert "Gone Already" in result["removed"]
        kept = {k["title"]: k["reason"] for k in result["kept"]}
        assert kept["Spy Kids"] == "Maintainerr's collection"
        assert "Studio label" in kept["Hand Made Twin"]
        assert "104" in plex.deletions
        assert "102" not in plex.deletions
        assert twin_key not in plex.deletions
        # Re-check: every DELETE was preceded by a metadata GET for labels.
        meta_gets = [r for r in plex.requests if r.method == "GET" and "/library/metadata/" in r.url.path]
        assert any(r.url.path.endswith("/104") for r in meta_gets)
        remaining = {r["key"]: r["desired"] for r in col.rows(db, "Movies")}
        assert "Studio Chart" not in remaining and "Gone Already" not in remaining
        assert remaining["Spy Kids"] == 0 and remaining["Hand Made Twin"] == 0


def test_run_hook_records_only_after_run_end(root):
    import asyncio

    client, plex, _ = make_client(root)
    with client:
        db = client.app.state.db
        with db:
            ids = col.mark_present(
                db, "Movies", [col.Pick(col.Ref("basic", "", "Studio Chart"), "Studio Chart", "Studio Chart")]
            )
            col.set_run(db, ids, 1)
            db.execute(
                "INSERT INTO runs (id, request, status, trigger, queued_at, started_at) VALUES (1, ?, 'running', 'ready-made', '2026-11-03T00:00:00Z', '2026-11-03T00:00:01Z')",
                (RunRequest(mode="collections", libraries=["Movies"], collections=["Studio Chart"]).model_dump_json(),),
            )

        class Runner:
            current_run_id = 1

        recorder = ReadyMadeRecorder(db, Runner(), client.app.state.settings, client.app.state.http, client.app.state.tasks)
        said: list[str] = []
        request = RunRequest(mode="collections", libraries=["Movies"], collections=["Studio Chart"])

        async def no_end():
            after = await recorder.before_run(request, said.append)
            assert after is not None
            await after()

        asyncio.run(no_end())
        row = col.rows(db, "Movies")[0]
        assert "no run_end" in (row["last_error"] or "")
        assert row["plex_exists"] == 0

        with db:
            db.execute("INSERT INTO run_events (run_id, event, payload) VALUES (1, 'run_end', '{}')")
            db.execute("UPDATE collections SET last_error = NULL WHERE id = ?", (ids[0],))

        async def with_end():
            after = await recorder.before_run(request, said.append)
            await after()

        asyncio.run(with_end())
        row = col.rows(db, "Movies")[0]
        assert row["plex_exists"] == 1 and row["plex_rating_key"] == "104"
        assert row["last_error"] is None and row["last_built_at"]
        assert any("Plex state" in line for line in said)


def test_counting_task_stores_counts_and_shows_in_jobs(root):
    client, _, _ = make_client(root)
    with client:
        # Startup may already be counting; wait, then start again and watch jobs.
        wait_for_task(client, "ready_made_counts")
        # Clear counts and run again so we can catch it in /jobs while running.
        with client.app.state.db:
            client.app.state.db.execute("DELETE FROM preview_counts")

        # Slow the task by pausing notes observation: start and poll jobs immediately.
        started = client.post("/api/v1/ready-made/count")
        assert started.status_code == 202 and started.json()["started"] is True
        # While running (or just after), jobs should mention it at some point.
        seen = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            jobs = client.get("/api/v1/jobs").json()["jobs"]
            if any(j["id"] == "task-ready_made_counts" for j in jobs):
                seen = True
                break
            time.sleep(0.05)
        assert seen
        task = wait_for_task(client, "ready_made_counts")
        assert task["last"]["status"] == "succeeded", task
        cached = col.counts(client.app.state.db, "Movies")
        assert "basic" in cached and "genre" in cached
        assert isinstance(cached["genre"]["data"]["entries"], list)
        again = client.post("/api/v1/ready-made/count")
        # Not running now, so it should start.
        assert again.status_code == 202
        wait_for_task(client, "ready_made_counts")


def test_a_file_scoped_category_sends_the_whole_run_by_file(root):
    # Kometa ANDs --run-files with --run-collections, so a mixed run would skip the collection-scoped picks.
    client, _, _ = make_client(root)
    with client:
        wait_for_task(client, "ready_made_counts")
        genre = client.get("/api/v1/ready-made/libraries/Movies/categories/genre").json()["collections"][0]
        db = client.app.state.db
        with db:
            col.mark_present(db, "Movies", [col.Pick(col.Ref("genre", genre["block"], genre["key"]), genre["title"], genre["title"])])
            col.set_run_scope(db, "Movies", "genre", "file")
        plan = client.post(
            "/api/v1/ready-made/build",
            json={
                "library": "Movies",
                "add": [{"category": "basic", "block": "", "key": "Newly Released"}, {"category": "genre", "block": genre["block"], "key": genre["key"]}],
                "remove": [],
                "dry_run": True,
            },
        ).json()
        assert plan["run"] == {"libraries": ["Movies"], "collections": [], "files": ["basic", "genre"]}


def test_remove_keeps_everything_while_plex_cant_be_reached(root):
    client, plex, _ = make_client(root)
    with client:
        wait_for_flags(client)
        db = client.app.state.db
        with db:
            [row_id] = col.mark_present(db, "Movies", [col.Pick(col.Ref("basic", "", "Studio Chart"), "Studio Chart", "Studio Chart")])
            col.record_plex_state(db, row_id, exists=True, rating_key="104", items=4, thumb=None, built=True, error=None)
        plex.reachable = set()
        result = client.post(
            "/api/v1/ready-made/build",
            json={"library": "Movies", "add": [], "remove": [{"category": "basic", "block": "", "key": "Studio Chart"}], "dry_run": False},
        ).json()
        assert result["removed"] == []
        assert [k["title"] for k in result["kept"]] == ["Studio Chart"] and "Plex" in result["kept"][0]["reason"]
        assert plex.deletions == []
        assert [r["desired"] for r in col.rows(db, "Movies")] == [0]  # kept, marked for removal, for a later try


def test_every_run_puts_studios_generated_files_back_without_asking(root):
    # A fully managed install: hand edits, a deleted file and a dropped config.yml entry are undone before Kometa runs.
    client, _, _ = make_client(root)
    with client:
        wait_for_flags(client)
        add = {"library": "Movies", "add": [{"category": "basic", "block": "", "key": "Newly Released"}], "remove": []}
        first = client.post("/api/v1/ready-made/build", json=add).json()
        wait_for_run(client, first["run_id"])
        gallery = client.get("/api/v1/ready-made/libraries/Movies").json()
        assert "hand_edited" not in gallery  # no warnings: Studio just corrects it

        studio = root / "config" / "studio" / "Movies" / "basic.yml"
        config = root / "config" / "config.yml"
        original, original_config = studio.read_text(), config.read_text()
        studio.write_text(original + "# changed by hand\n")
        run = wait_for_run(client, client.post("/api/v1/runs", json={"mode": "operations"}).json()["id"])
        assert studio.read_text() == original
        log = client.get(f"/api/v1/runs/{run['id']}/log").text
        assert "studio/Movies/basic.yml had been changed by hand: put Studio's version back" in log
        assert not any(c["source"] == "generated_files" for c in client.get("/api/v1/status").json()["health"])

        # Deleted, and its entry taken out of config.yml: both come back on the next run.
        studio.unlink()
        config.write_text(original_config.replace("studio/Movies/basic.yml", "studio/Movies/gone.yml"))
        run = wait_for_run(client, client.post("/api/v1/runs", json={"mode": "operations"}).json()["id"])
        assert studio.read_text() == original
        assert "studio/Movies/basic.yml" in config.read_text()
        assert "brought Studio's generated files for Movies up to date" in client.get(f"/api/v1/runs/{run['id']}/log").text

        # Nothing to put right: no save, nothing in the log.
        backups = len(client.get("/api/v1/backups").json()["backups"])
        run = wait_for_run(client, client.post("/api/v1/runs", json={"mode": "operations"}).json()["id"])
        assert len(client.get("/api/v1/backups").json()["backups"]) == backups
        assert "generated files" not in client.get(f"/api/v1/runs/{run['id']}/log").text


def test_removing_a_categorys_last_pick_removes_its_file(root):
    client, _, _ = make_client(root)
    with client:
        wait_for_flags(client)
        ref = {"category": "basic", "block": "", "key": "Newly Released"}
        built = client.post("/api/v1/ready-made/build", json={"library": "Movies", "add": [ref], "remove": []}).json()
        wait_for_run(client, built["run_id"])
        studio = root / "config" / "studio" / "Movies" / "basic.yml"
        assert studio.is_file()
        client.post("/api/v1/ready-made/build", json={"library": "Movies", "add": [], "remove": [ref]}).json()
        assert not studio.exists()
        assert "studio/Movies/basic" not in (root / "config" / "config.yml").read_text()
        assert col.generated(client.app.state.db) == {}


def test_a_category_the_count_couldnt_list_shows_why(root):
    # E.g. language categories when Studio couldn't get TMDb's language names.
    with make_client(root)[0] as client:
        wait_for_task(client, "ready_made_counts")
        with client.app.state.db:
            col.save_counts(client.app.state.db, "Movies", "genre", {"entries": []}, "Kometa names these with TMDb's names")
        gallery = client.get("/api/v1/ready-made/libraries/Movies").json()
        genre = next(c for c in gallery["categories"] if c["name"] == "genre")
        assert genre["listable"] is False and genre["reason"] == "Kometa names these with TMDb's names"
        detail = client.get("/api/v1/ready-made/libraries/Movies/categories/genre").json()
        assert detail["listable"] is False and detail["reason"] == "Kometa names these with TMDb's names"
        basic = next(c for c in gallery["categories"] if c["name"] == "basic")
        assert basic["listable"] is True and basic["reason"] is None


def test_a_pick_whose_name_is_taken_by_someone_elses_collection_isnt_built(root):
    # Kometa takes over a collection with the same title; the Studio label would land on the user's own.
    plex = FakePlex()
    plex.add_collection("1", "Newly Released", labels=[], items=3)
    client, _, _ = make_client(root, plex)
    with client:
        wait_for_flags(client)
        add = {"library": "Movies", "add": [{"category": "basic", "block": "", "key": "Newly Released"}], "remove": []}
        plan = client.post("/api/v1/ready-made/build", json=add | {"dry_run": True}).json()
        assert plan["build"] == [] and plan["run"] is None
        assert plan["blocked"] == [
            {"category": "basic", "title": "Newly Released", "reason": "a collection with this name that Studio didn't make is already in Plex"}
        ]
        result = client.post("/api/v1/ready-made/build", json=add).json()
        assert result["run_id"] is None and result["blocked"] == plan["blocked"]
        assert col.rows(client.app.state.db, "Movies", "basic") == []
        assert not (root / "config" / "studio" / "Movies" / "basic.yml").exists()


def test_a_studio_collection_with_the_name_is_built_again(root):
    plex = FakePlex()
    plex.add_collection("1", "Newly Released", labels=["Studio"], items=3)
    client, _, _ = make_client(root, plex)
    with client:
        wait_for_flags(client)
        add = {"library": "Movies", "add": [{"category": "basic", "block": "", "key": "Newly Released"}], "remove": []}
        plan = client.post("/api/v1/ready-made/build", json=add | {"dry_run": True}).json()
        assert plan["blocked"] == [] and plan["run"]["collections"] == ["Newly Released"]


class PosterPlex(FakePlex):
    """FakePlex that also answers for Kometa's image repos, the way GitHub would: nothing called Nope is there."""

    def __init__(self) -> None:
        super().__init__()
        self.posters: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "raw.githubusercontent.com":
            self.posters.append(str(request.url))
            if "Nope" in str(request.url):
                return httpx.Response(404)
            import io

            from PIL import Image

            out = io.BytesIO()
            Image.new("RGB", (600, 900), (10, 10, 10)).save(out, "JPEG")
            return httpx.Response(200, content=out.getvalue())
        return super().handle(request)


def test_unbuilt_tiles_get_the_poster_kometa_will_apply(root):
    basic = root / "kometa" / "defaults" / "chart" / "basic.yml"
    basic.write_text(
        "external_templates:\n  default: templates\n  template_variables:\n    image: chart/<<style>>/<<mapping_name_encoded>>\n"
        + basic.read_text().replace("  Newly Released:\n", "  Newly Released:\n    variables:\n      style: color\n")
    )
    plex = PosterPlex()
    with make_client(root, plex)[0] as client:
        wait_for_task(client, "ready_made_counts")
        entry = client.get("/api/v1/ready-made/libraries/Movies/categories/basic").json()["collections"][0]
        assert entry["thumb"] is None and entry["state"] == "none"
        assert entry["poster"] == "ready-made/posters/movie/basic?block=&key=Newly+Released"

        image = client.get(f"/api/v1/{entry['poster']}")
        assert image.status_code == 200 and image.headers["content-type"] == "image/webp"
        assert plex.posters == ["https://raw.githubusercontent.com/Kometa-Team/Default-Images/master/chart/color/Newly%20Released.jpg"]
        assert client.get(f"/api/v1/{entry['poster']}").status_code == 200
        assert len(plex.posters) == 1  # kept in the data folder

        # People: the director default's People-Images poster, worked out from the default file alone.
        person = client.get("/api/v1/ready-made/posters/movie/director", params={"block": "Directors", "key": "Denis Villeneuve"})
        assert person.status_code == 200
        assert plex.posters[-1] == "https://raw.githubusercontent.com/Kometa-Team/People-Images-bw/master/D/Images/Denis%20Villeneuve.jpg"

        # Only a default, block and key come in. One Kometa names no image for is a 404 without fetching anything.
        fetched = len(plex.posters)
        assert client.get("/api/v1/ready-made/posters/movie/genre", params={"block": "Genre", "key": "Action"}).status_code == 404
        assert client.get("/api/v1/ready-made/posters/music/director", params={"block": "Directors", "key": "x"}).status_code == 422
        assert len(plex.posters) == fetched
        # A poster the image repo doesn't have is a 404 too.
        assert client.get("/api/v1/ready-made/posters/movie/director", params={"block": "Directors", "key": "Nope"}).status_code == 404
