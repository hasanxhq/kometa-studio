import pytest
from fakeplex import REMOTE_URI, SERVER_TOKEN, FakePlex
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.settings import Settings


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config" / "config.yml"
    path.parent.mkdir()
    path.write_text(f"plex:\n  url: {REMOTE_URI}\n  token: {SERVER_TOKEN}\n")
    return path


def make_client(tmp_path, fake, **settings):
    settings.setdefault("kometa_config", tmp_path / "config" / "config.yml")
    app = create_app(Settings(data_dir=tmp_path / "data", **settings), static_dir=tmp_path / "no-static", http_transport=fake.transport())
    return TestClient(app, client=("127.0.0.1", 50000))


def test_libraries_with_collection_counts(tmp_path, config):
    with make_client(tmp_path, FakePlex()) as client:
        body = client.get("/api/v1/plex/libraries").json()
    assert body["libraries"] == [
        {"key": "1", "title": "Movies", "type": "movie", "collections": 3, "managed": 2, "maintainerr": 0},
        {"key": "2", "title": "TV Shows", "type": "show", "collections": 0, "managed": 0, "maintainerr": 0},
    ]


def test_collections_are_marked_managed_by_kometas_labels(tmp_path, config):
    with make_client(tmp_path, FakePlex()) as client:
        body = client.get("/api/v1/plex/libraries/1/collections").json()
    assert body["library"] == {"key": "1", "title": "Movies", "type": "movie"}
    assert [(c["title"], c["items"], c["managed"], c["smart"], c["thumb"]) for c in body["collections"]] == [
        ("Marvel", 11, True, False, "/library/collections/101/composite/1700000001"),
        ("Old PMM collection", 2, True, True, None),  # PMM is Kometa's old label
        ("Spy Kids", 3, False, False, "/library/collections/102/composite/1700000002"),  # labelled, but not by Kometa
    ]


def test_posters_go_through_studio(tmp_path, config):
    fake = FakePlex()
    with make_client(tmp_path, fake) as client:
        image = client.get("/api/v1/plex/image", params={"path": "/library/collections/101/composite/1700000001", "width": 120, "height": 180})
        refused = client.get("/api/v1/plex/image", params={"path": "/:/prefs"})
        escaped = client.get("/api/v1/plex/image", params={"path": "/library/collections/101/composite/1/../../../../system"})
    assert (image.status_code, image.headers["content-type"], image.content) == (200, "image/jpeg", b"\xff\xd8poster")
    assert SERVER_TOKEN not in str(image.headers)
    assert fake.requests[-1].url.params["width"] == "120"
    assert (refused.status_code, escaped.status_code) == (404, 404)


def test_unknown_library(tmp_path, config):
    with make_client(tmp_path, FakePlex()) as client:
        assert client.get("/api/v1/plex/libraries/9/collections").status_code == 404


def test_no_plex_connection_yet(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text("libraries: {}\n")
    with make_client(tmp_path, FakePlex()) as client:
        response = client.get("/api/v1/plex/libraries")
    assert response.status_code == 409
    assert "Settings → Plex" in response.json()["detail"]


def test_plex_unreachable_or_token_rejected(tmp_path, config):
    fake = FakePlex()
    fake.reachable = set()
    with make_client(tmp_path, fake) as client:
        down = client.get("/api/v1/plex/libraries")
    config.write_text(f"plex:\n  url: {REMOTE_URI}\n  token: wrong\n")
    with make_client(tmp_path, FakePlex()) as client:
        rejected = client.get("/api/v1/plex/libraries")
    assert (down.status_code, rejected.status_code) == (502, 502)
    assert "Can't reach Plex" in down.json()["detail"]
    assert "rejected the token" in rejected.json()["detail"]
