import json
import time
from pathlib import Path

import httpx
import pytest
from fakemaintainerr import MAINTAINERR_URL, FakeMaintainerr
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.maintainerr_guard import reaches, risks
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
FINISHED = {"succeeded", "failed", "cancelled", "interrupted", "timed_out"}

# --- The guard, from config alone ---------------------------------------------------------

OWNED = {"movies": ["Spy Kids", "Leaving Soon"]}


def guard(tmp_path, config: str, files: dict[str, str] | None = None):
    root = tmp_path / "kometa"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.yml").write_text(config)
    for name, text in (files or {}).items():
        (root / "config" / name).write_text(text)
    return risks(root / "config" / "config.yml", root, OWNED)


@pytest.mark.parametrize(
    ("operations", "kinds"),
    [
        ("delete_collections: {managed: false}", ["delete"]),
        ("delete_collections: {less: 5}", ["delete"]),  # Maintainerr's collections are often small
        ("delete_collections: {configured: false}", ["delete"]),
        ("delete_collections: {managed: true, less: 5}", []),  # only Kometa's own
        ("delete_collections: {configured: true}", []),
        ("delete_collections: {}", []),  # Kometa deletes nothing
        ("delete_unmanaged_collections: true", ["delete"]),  # the old names
        ("delete_collections_with_less: 3", ["delete"]),
        ("mass_collection_mode: hide", ["mode"]),
        ("mass_metadata_update: {collections: {mode: hide}}", ["mode"]),
        ("mass_genre_update: tmdb", []),
    ],
)
def test_operations_that_reach_maintainerrs_collections(tmp_path, operations, kinds):
    found = guard(tmp_path, f"libraries:\n  Movies:\n    operations:\n      {operations}\n")
    assert [r.kind for r in found] == kinds


def test_operations_as_a_list_and_a_renamed_library(tmp_path):
    config = "libraries:\n  Films:\n    library_name: Movies\n    operations:\n      - mass_genre_update: tmdb\n      - delete_collections: {less: 2}\n"
    found = guard(tmp_path, config)
    assert [(r.library, r.kind) for r in found] == [("Films", "delete")]
    assert "“Spy Kids”" in found[0].message and "managed: true" in found[0].message
    assert guard(tmp_path, "libraries:\n  TV Shows:\n    operations: {delete_collections: {less: 2}}\n") == []  # Maintainerr has none there


def test_a_kometa_collection_with_maintainerrs_name(tmp_path):
    config = "libraries:\n  Movies:\n    collection_files:\n      - file: config/Movies.yml\n"
    found = guard(tmp_path, config, {"Movies.yml": "collections:\n  spy kids:\n    tmdb_collection: 1\n  Marvel:\n    tmdb_collection: 2\n"})
    assert [(r.kind, r.collection) for r in found] == [("name", "spy kids")]


def test_which_runs_a_risk_reaches(tmp_path):
    config = "libraries:\n  Movies:\n    operations: {mass_collection_mode: hide}\n    collection_files:\n      - file: config/Movies.yml\n"
    mode, name = guard(tmp_path, config, {"Movies.yml": "collections:\n  Spy Kids: {tmdb_collection: 1}\n"})
    assert reaches(mode, "all", [], []) and reaches(mode, "operations", ["Movies"], [])
    assert not reaches(mode, "collections", [], []) and not reaches(mode, "all", ["TV Shows"], [])
    assert not reaches(mode, "all", [], ["Marvel"])  # only named collections run: no operations
    assert reaches(name, "collections", [], []) and reaches(name, "all", [], ["Spy Kids"])
    assert not reaches(name, "overlays", [], []) and not reaches(name, "all", [], ["Marvel"])


# --- Studio with a Maintainerr ---------------------------------------------------------


@pytest.fixture
def setup(tmp_path):
    """Kometa's folder as in Docker: kometa.py with config/ beside it."""
    root = tmp_path / "kometa"
    config = root / "config"
    config.mkdir(parents=True)
    (root / "kometa.py").symlink_to(FAKE_KOMETA)
    (config / "config.yml").write_text(
        f"libraries:\n  Movies:\n    collection_files:\n      - file: config/Movies.yml\n  TV Shows: {{}}\nplex:\n  url: {REMOTE_URI}\n  token: {SERVER_TOKEN}\n"
    )
    (config / "Movies.yml").write_text("collections:\n  Marvel:\n    tmdb_collection: 2\n")
    (config / "fake.json").write_text(json.dumps({"lines": ["Kometa ran"]}))
    return root, FakePlex(), FakeMaintainerr()


def make_client(tmp_path, setup):
    root, plex, fake = setup

    def handle(request: httpx.Request) -> httpx.Response:
        return fake.handle(request) if request.url.host == "maintainerr.test" else plex.handle(request)

    settings = Settings(
        data_dir=root / "config" / ".studio",
        kometa_python=Path(__import__("sys").executable),
        kometa_entry=root / "kometa.py",
        kometa_config=root / "config" / "config.yml",
        kill_after=0.5,
    )
    app = create_app(settings, static_dir=tmp_path / "no-static", http_transport=httpx.MockTransport(handle))
    return TestClient(app, client=("127.0.0.1", 50000))


def connect(client, **extra):
    response = client.put("/api/v1/settings/maintainerr", json={"url": MAINTAINERR_URL, "leave_overlays_alone": True} | extra)
    assert response.status_code == 200, response.text
    return response.json()


def finished(client, run_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in FINISHED:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} still {run['status']}")


def log_of(client, run_id) -> str:
    return client.get(f"/api/v1/runs/{run_id}/log").text


def test_connecting_lists_its_collections_and_libraries_mark_them(tmp_path, setup):
    with make_client(tmp_path, setup) as client:
        state = connect(client)
        collections = client.get("/api/v1/plex/libraries/1/collections").json()["collections"]
        libraries = client.get("/api/v1/plex/libraries").json()["libraries"]
    assert state["collections"] == [
        {"title": "Leaving Soon Shows", "library": "TV Shows", "overlays": False},
        {"title": "Spy Kids", "library": "Movies", "overlays": True},
    ]
    assert state["overlays_enabled"] is True and state["risks"] == [] and state["error"] is None
    assert {c["title"]: c["maintainerr"] for c in collections} == {"Marvel": False, "Old PMM collection": False, "Spy Kids": True}
    assert libraries[0]["maintainerr"] == 1


def test_testing_a_maintainerr(tmp_path, setup):
    _, _, fake = setup
    with make_client(tmp_path, setup) as client:
        ok = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL}).json()
        fake.media_server = False
        no_media_server = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL}).json()
        fake.collections = [c | {"overlayEnabled": False} for c in fake.collections]
        no_overlays = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL}).json()
        fake.down = True
        down = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL}).json()
    assert ok == {"ok": True, "collections": 2, "overlays_enabled": True}
    assert no_media_server == {"ok": False, "error": "Maintainerr can't reach its media server right now, so its overlays can't be managed"}
    assert no_overlays == {"ok": True, "collections": 2, "overlays_enabled": False}  # overlays not asked about
    assert down["ok"] is False and "Can't reach Maintainerr" in down["error"]


def test_a_save_that_would_let_kometa_delete_its_collections_is_refused(tmp_path, setup):
    root, _, _ = setup
    config = root / "config" / "config.yml"
    with make_client(tmp_path, setup) as client:
        connect(client)
        opened = client.get("/api/v1/config/edit", params={"path": "config.yml"}).json()
        risky = opened["text"].replace("  TV Shows: {}\n", "    operations:\n      delete_collections:\n        less: 3\n  TV Shows: {}\n")
        refused = client.put("/api/v1/config/files", json={"files": [{"path": "config.yml", "text": risky, "base_hash": opened["hash"]}]})
        # A clash made by editing a collection file is caught too.
        movies = client.get("/api/v1/config/edit", params={"path": "Movies.yml"}).json()
        clash = client.put(
            "/api/v1/config/files",
            json={"files": [{"path": "Movies.yml", "text": movies["text"] + "  Spy Kids:\n    tmdb_collection: 3\n", "base_hash": movies["hash"]}]},
        )
        fine = client.put(
            "/api/v1/config/files",
            json={"files": [{"path": "Movies.yml", "text": movies["text"] + "  Heroes:\n    tmdb_collection: 3\n", "base_hash": movies["hash"]}]},
        )
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["message"] == "This would let Kometa touch Maintainerr's collections, so nothing was saved."
    assert "Limit it with managed: true" in detail["validation"]["errors"][0]
    assert "delete_collections" not in config.read_text()
    assert clash.status_code == 422 and "same name as Maintainerr's" in clash.json()["detail"]["validation"]["errors"][0]
    assert fine.status_code == 200


def test_a_run_that_would_touch_its_collections_is_held(tmp_path, setup):
    root, _, fake = setup
    config = root / "config" / "config.yml"
    config.write_text(config.read_text().replace("  TV Shows: {}\n", "    operations: {mass_collection_mode: hide}\n  TV Shows: {}\n"))
    with make_client(tmp_path, setup) as client:
        state = connect(client, leave_overlays_alone=False)
        held = finished(client, client.post("/api/v1/runs", json={"mode": "operations"}).json()["id"])
        held_log = log_of(client, held["id"])
        other_library = finished(client, client.post("/api/v1/runs", json={"mode": "operations", "libraries": ["TV Shows"]}).json()["id"])
        collections = finished(client, client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"])
        health = [c["message"] for c in client.get("/api/v1/status").json()["health"] if c["source"].startswith("maintainerr")]
    assert state["risks"] == [health[0]]
    assert held["status"] == "failed" and held["error"].startswith("Held, so Kometa doesn't touch Maintainerr's collections")
    assert "Kometa ran" not in held_log
    assert other_library["status"] == "succeeded"
    assert collections["status"] == "succeeded"  # mass_collection_mode is an operation; this run doesn't do any
    assert not any("revert" in call for call in fake.calls)


def test_maintainerrs_overlays_take_precedence(tmp_path, setup):
    _, _, fake = setup
    with make_client(tmp_path, setup) as client:
        connect(client)
        fake.calls.clear()
        run = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
        log = log_of(client, run["id"])
        collections_only = finished(client, client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"])
    assert run["status"] == "succeeded"
    changes = [call for call in fake.calls if call.startswith(("POST", "PUT"))]
    # Maintainerr's overlays are paused, only the collection with overlays is reverted, then they're back on and drawn again.
    assert changes == ["PUT /api/overlays/settings", "POST /api/overlays/revert/7", "PUT /api/overlays/settings", "POST /api/overlays/process"]
    assert fake.overlays_enabled is True
    lines = log.splitlines()
    put_back = next(i for i, line in enumerate(lines) if "puts back the posters under its overlays" in line)
    kometa = next(i for i, line in enumerate(lines) if "Kometa ran" in line)
    again = next(i for i, line in enumerate(lines) if "drawing them again, on top of Kometa" in line)
    assert put_back < kometa < again
    assert collections_only["status"] == "succeeded"
    assert len([c for c in fake.calls if c.startswith(("POST", "PUT"))]) == 4  # a collections run changes no posters


def test_a_run_for_another_library_leaves_its_overlays_alone(tmp_path, setup):
    _, _, fake = setup
    with make_client(tmp_path, setup) as client:
        connect(client)
        finished(client, client.post("/api/v1/runs", json={"mode": "all", "libraries": ["TV Shows"]}).json()["id"])
    assert not any(call.startswith("POST") for call in fake.calls)


def test_waits_for_maintainerrs_own_overlay_run(tmp_path, setup, monkeypatch):
    from kometa_studio import maintainerr

    _, _, fake = setup
    monkeypatch.setattr(maintainerr, "BUSY_WAIT", 0.3)
    monkeypatch.setattr(maintainerr, "POLL", 0.05)
    fake.status = "running"
    with make_client(tmp_path, setup) as client:
        connect(client)
        run = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
    assert run["status"] == "failed" and "still busy" in run["error"]
    assert not any("revert" in call for call in fake.calls)


def test_a_maintainerr_without_overlays_never_holds_a_run(tmp_path, setup):
    _, _, fake = setup
    fake.collections = [c | {"overlayEnabled": False} for c in fake.collections]
    with make_client(tmp_path, setup) as client:
        connect(client)
        fake.down = True
        run = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
    assert run["status"] == "succeeded"


def test_maintainerr_down_holds_poster_runs_only_while_the_setting_is_on(tmp_path, setup):
    _, _, fake = setup
    with make_client(tmp_path, setup) as client:
        connect(client)
        fake.down = True
        held = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
        collections = finished(client, client.post("/api/v1/runs", json={"mode": "collections"}).json()["id"])
        fake.down = False
        connect(client, leave_overlays_alone=False)
        fake.down = True
        off = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
    assert held["status"] == "failed" and "Leave Maintainerr overlays alone" in held["error"]
    assert collections["status"] == "succeeded"
    assert off["status"] == "succeeded"


def test_switching_overlays_back_on_is_retried_until_it_works(tmp_path, setup, monkeypatch):
    from kometa_studio import maintainerr

    _, _, fake = setup
    real_handle = fake.handle
    failing = {"on": False}

    def flaky(request):
        # Maintainerr goes away just as Kometa finishes.
        if failing["on"] and request.method == "PUT":
            raise httpx.ConnectError("Connection refused", request=request)
        return real_handle(request)

    fake.handle = flaky
    with make_client(tmp_path, setup) as client:
        connect(client)
        service = client.app.state.maintainerr

        async def before_and_break(request, say):
            after = await maintainerr.Maintainerr.before_run(service, request, say)
            failing["on"] = True
            return after

        monkeypatch.setattr(service, "before_run", before_and_break)
        run = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
        assert run["status"] == "succeeded"
        assert "keeps trying" in log_of(client, run["id"])
        assert fake.overlays_enabled is False
        assert client.get("/api/v1/settings/maintainerr").json()["overlays_enabled"] is True  # its real setting

        failing["on"] = False
        client.portal.call(service._resume, lambda line: None)  # what the loop does every few minutes
    assert fake.overlays_enabled is True
    assert fake.calls[-1] == "POST /api/overlays/process"


def test_a_seedbox_proxy_login(tmp_path, setup):
    _, _, fake = setup
    fake.proxy_login = ("hasan", "seedbox-pass")
    with make_client(tmp_path, setup) as client:
        missing = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL}).json()
        wrong = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL, "username": "hasan", "password": "nope"}).json()
        right = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL, "username": "hasan", "password": "seedbox-pass"}).json()
        state = connect(client, username="hasan", password="seedbox-pass")
        assert "seedbox-pass" not in client.get("/api/v1/settings/maintainerr").text
        again = connect(client, username="hasan")  # saved without a password: kept
        tested_with_saved = client.post("/api/v1/settings/maintainerr/test", json={"url": MAINTAINERR_URL, "username": "hasan"}).json()
    assert missing == {"ok": False, "error": "The proxy in front of Maintainerr wants a username and password"}
    assert wrong == {"ok": False, "error": "The proxy in front of Maintainerr wants a username and password (these were refused)"}
    assert right["ok"] is True
    assert (state["username"], state["has_password"], len(state["collections"])) == ("hasan", True, 2)
    assert again["has_password"] is True and again["error"] is None
    assert tested_with_saved["ok"] is True


def test_a_revert_slower_than_the_request_is_waited_for(tmp_path, setup, monkeypatch):
    """As on the real seedbox: the revert walks ~230 shows, seasons and episodes and answers only when done."""
    from kometa_studio import maintainerr

    _, _, fake = setup
    monkeypatch.setattr(maintainerr, "POLL", 0.05)
    fake.slow_revert_polls = 5  # the revert outlasts the request, and status says "running" meanwhile
    fake.busy_process_polls = 3  # then a redraw asked too soon gets 409
    with make_client(tmp_path, setup) as client:
        connect(client)
        fake.calls.clear()
        run = finished(client, client.post("/api/v1/runs", json={"mode": "overlays"}).json()["id"])
        log = log_of(client, run["id"])
        pending = client.app.state.maintainerr.db.execute("SELECT value FROM settings WHERE key = 'maintainerr.pending_process'").fetchone()[0]
    assert run["status"] == "succeeded", log
    assert "still putting posters back" in log and "Kometa ran" in log
    assert log.index("still putting posters back") < log.index("Kometa ran") < log.index("drawing them again")
    assert [c for c in fake.calls if c.startswith("POST")] == ["POST /api/overlays/revert/7", "POST /api/overlays/process", "POST /api/overlays/process"]
    assert fake.overlays_enabled is True and pending == "false"


def test_a_new_address_or_login_is_saved_only_after_it_passes_a_test(tmp_path, setup):
    _, _, fake = setup
    fake.proxy_login = ("hasan", "seedbox-pass")
    with make_client(tmp_path, setup) as client:
        refused = client.put("/api/v1/settings/maintainerr", json={"url": MAINTAINERR_URL, "username": "hasan", "password": "nope", "leave_overlays_alone": True})
        assert client.get("/api/v1/settings/maintainerr").json()["url"] is None
        connect(client, username="hasan", password="seedbox-pass")
        fake.proxy_login = ("hasan", "changed-since")  # the overlay choice alone is saved without a test
        toggled = connect(client, username="hasan", leave_overlays_alone=False)
    assert refused.status_code == 422 and refused.json()["detail"].startswith("Not saved: The proxy in front of Maintainerr")
    assert toggled["leave_overlays_alone"] is False
