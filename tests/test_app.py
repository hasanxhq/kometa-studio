from fastapi.testclient import TestClient

from kometa_studio import __version__
from kometa_studio.app import create_app
from kometa_studio.db import load_migrations
from kometa_studio.settings import Settings


def make_client(tmp_path, static_dir=None, **settings):
    app = create_app(Settings(data_dir=tmp_path / "data", **settings), static_dir=static_dir or tmp_path / "no-static")
    return TestClient(app, client=("127.0.0.1", 50000))  # a local address, so no sign-in is needed


def test_status_reports_versions(tmp_path):
    kometa_dir = tmp_path / "kometa"
    kometa_dir.mkdir()
    (kometa_dir / "VERSION").write_text("2.5.3\n")

    with make_client(tmp_path, kometa_entry=kometa_dir / "kometa.py") as client:
        body = client.get("/api/v1/status").json()

    assert body["version"] == __version__
    assert body["kometa"]["version"] == "2.5.3"
    assert body["database"]["schema_version"] == len(load_migrations())


def test_status_without_kometa_configured(tmp_path):
    with make_client(tmp_path) as client:
        kometa = client.get("/api/v1/status").json()["kometa"]
    assert (kometa["version"], kometa["config"], kometa["updates"]["available"]) == (None, None, False)


def test_spa_routes_fall_back_to_index(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id=root></div>")
    (static / "assets" / "app.js").write_text("console.log(1)")

    with make_client(tmp_path, static_dir=static) as client:
        assert client.get("/").text == "<div id=root></div>"
        assert client.get("/system/tasks").text == "<div id=root></div>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/v1/does-not-exist").status_code == 404
