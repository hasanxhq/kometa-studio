import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_sections import read_section
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
FINISHED = {"succeeded", "failed", "cancelled", "interrupted", "timed_out"}


def make_client(tmp_path):
    root = tmp_path / "kometa"
    config = root / "config"
    config.mkdir(parents=True)
    (root / "kometa.py").symlink_to(FAKE_KOMETA)
    (config / "config.yml").write_text(
        "libraries:\n"
        "  Movies:  # the big one\n    overlay_files:\n      - file: config/overlays.yml\n"
        "  TV Shows:\n    library_name: Series\n    collection_files:\n      - file: config/overlays.yml\n"
    )
    (config / "overlays.yml").write_text("overlays:\n  4K:\n    overlay: {name: 4K}\n    plex_search: {all: {resolution: 4K}}\n")
    (config / "fake.json").write_text(json.dumps({"lines": ["Kometa ran"]}))
    posters = config / "overlays" / "Movies Original Posters"
    posters.mkdir(parents=True)
    (posters / "101.jpg").write_bytes(b"x" * 100)
    (posters / "102.png").write_bytes(b"y" * 50)
    settings = Settings(
        data_dir=config / ".studio", kometa_python=Path(sys.executable), kometa_entry=root / "kometa.py", kometa_config=config / "config.yml", kill_after=0.5
    )
    return TestClient(create_app(settings, static_dir=tmp_path / "no-static"), client=("127.0.0.1", 50000)), config


def finished(client, run_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in FINISHED:
            return run
        time.sleep(0.05)
    raise AssertionError("still running")


def test_each_library_says_what_draws_overlays_and_how_its_backup_is(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        before = {entry["library"]: entry for entry in client.get("/api/v1/overlays").json()["libraries"]}
        run = finished(client, client.post("/api/v1/overlays/Movies/apply").json()["run_id"])
        after = {entry["library"]: entry for entry in client.get("/api/v1/overlays").json()["libraries"]}
    movies = before["Movies"]
    assert movies["off"] is False
    assert movies["files"] == [{"kind": "file", "value": "config/overlays.yml", "error": None, "files": [{"path": "overlays.yml", "title": None, "docs_url": None, "overlays": ["4K"]}]}]
    assert movies["backup"] == {"posters": 2, "bytes": 150}
    assert (movies["last_pass"], movies["maintainerr"]) == (None, None)
    assert (before["TV Shows"]["plex_name"], before["TV Shows"]["files"], before["TV Shows"]["backup"]) == ("Series", [], None)
    assert run["request"] == {**run["request"], "mode": "overlays", "libraries": ["Movies"]}
    assert after["Movies"]["last_pass"]["run_id"] == run["id"]
    assert after["TV Shows"]["last_pass"] is None  # that run was only for Movies


def test_turning_overlays_off_and_on_again(tmp_path):
    client, config = make_client(tmp_path)
    with client:
        no_backup = client.post("/api/v1/overlays/TV Shows/off")
        unknown = client.post("/api/v1/overlays/Music/off")
        off = client.post("/api/v1/overlays/Movies/off").json()
        finished(client, off["run_id"])
        assert read_section(config / "config.yml", "libraries")["Movies"]["remove_overlays"] is True
        assert client.get("/api/v1/overlays").json()["libraries"][0]["off"] is True
        on = client.post("/api/v1/overlays/Movies/on").json()
        run = finished(client, on["run_id"])
    assert no_backup.status_code == 409 and "no Original Posters backup" in no_backup.json()["detail"]
    assert unknown.status_code == 404
    assert "remove_overlays" not in read_section(config / "config.yml", "libraries")["Movies"]
    assert "# the big one" in (config / "config.yml").read_text()  # the rest of the file is kept
    assert run["request"]["mode"] == "overlays" and run["request"]["libraries"] == ["Movies"]
