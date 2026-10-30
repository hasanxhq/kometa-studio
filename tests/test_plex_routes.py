import sqlite3

import pytest
from fakeplex import ACCOUNT_TOKEN, RELAY_URI, REMOTE_URI, SERVER_ID, SERVER_TOKEN, FakePlex
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.kometa_config import read_plex
from kometa_studio.settings import Settings


@pytest.fixture
def fake():
    return FakePlex()


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config" / "config.yml"
    path.parent.mkdir()
    path.write_text("plex:\n  url: http://old:32400\n  token: old-token-1234\n")
    return path


def make_client(tmp_path, fake, **settings):
    settings.setdefault("kometa_config", tmp_path / "config" / "config.yml")
    app = create_app(Settings(data_dir=tmp_path / "data", **settings), static_dir=tmp_path / "no-static", http_transport=fake.transport())
    return TestClient(app)


def sign_in(client, fake):
    pin = client.post("/api/v1/plex/pin").json()
    fake.pin_approved = True
    return client.get(f"/api/v1/plex/pin/{pin['id']}").json()


def test_sign_in_keeps_the_account_token_on_the_server(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        pin = client.post("/api/v1/plex/pin").json()
        assert pin["id"] == 42
        assert "code=abcd1234" in pin["auth_url"]
        assert client.get("/api/v1/plex/pin/42").json() == {"status": "waiting"}

        fake.pin_approved = True
        response = client.get("/api/v1/plex/pin/42")
        assert response.json() == {"status": "signed_in", "account": {"name": "hasan"}}
        assert ACCOUNT_TOKEN not in response.text

        state = client.get("/api/v1/plex")
        assert state.json()["account"] == {"name": "hasan"}
        assert ACCOUNT_TOKEN not in state.text

    stored = sqlite3.connect(tmp_path / "data" / "studio.db").execute("SELECT value FROM settings").fetchall()
    assert stored and all(ACCOUNT_TOKEN not in value for (value,) in stored)


def test_client_identifier_is_stable(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        client.post("/api/v1/plex/pin")
        client.post("/api/v1/plex/pin")
    ids = {r.headers["X-Plex-Client-Identifier"] for r in fake.requests}
    assert len(ids) == 1


def test_expired_pin(tmp_path, fake, config):
    fake.pin_expired = True
    with make_client(tmp_path, fake) as client:
        assert client.get("/api/v1/plex/pin/42").json() == {"status": "expired"}


def test_current_config_masks_the_token(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        body = client.get("/api/v1/plex").json()
    assert body == {
        "config": {"path": str(config), "url": "http://old:32400", "token": "…1234", "error": None},
        "account": None,
    }


def test_servers_need_sign_in(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        assert client.get("/api/v1/plex/servers").status_code == 409


def test_discovered_servers_are_probed_and_ranked(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        body = client.get("/api/v1/plex/servers").json()

    [server] = body["servers"]
    assert (server["id"], server["name"], server["best"]) == (SERVER_ID, "Seedbox", REMOTE_URI)
    assert [(c["uri"], c["ok"], c["relay"]) for c in server["connections"][:2]] == [(REMOTE_URI, True, False), (RELAY_URI, True, True)]
    assert SERVER_TOKEN not in str(body)


def test_relay_is_best_only_when_nothing_else_works(tmp_path, fake, config):
    fake.reachable = {RELAY_URI}
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        [server] = client.get("/api/v1/plex/servers").json()["servers"]
    assert server["best"] == RELAY_URI


def test_revoked_sign_in_signs_out(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        fake.account_token = "revoked"
        assert client.get("/api/v1/plex/servers").status_code == 401
        assert client.get("/api/v1/plex").json()["account"] is None


def test_connecting_a_discovered_server_writes_its_token(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        response = client.post("/api/v1/plex/connect", json={"server_id": SERVER_ID, "uri": REMOTE_URI})

    assert response.status_code == 200
    assert response.json()["config"]["url"] == REMOTE_URI
    assert SERVER_TOKEN not in response.text
    assert read_plex(config).token == SERVER_TOKEN
    assert list((tmp_path / "data" / "backups").glob("*/config.yml"))


def test_connect_refuses_an_address_the_server_does_not_have(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        response = client.post("/api/v1/plex/connect", json={"server_id": SERVER_ID, "uri": "http://evil.example:80"})
    assert response.status_code == 422
    assert read_plex(config).url == "http://old:32400"


def test_connect_refuses_an_unreachable_address(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        response = client.post("/api/v1/plex/connect", json={"server_id": SERVER_ID, "uri": "http://172.17.0.2:32400"})
    assert response.status_code == 422
    assert "Can't connect" in response.json()["detail"]
    assert read_plex(config).url == "http://old:32400"


def test_manual_test_and_connect(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        bad = client.post("/api/v1/plex/test", json={"url": REMOTE_URI, "token": "wrong"}).json()
        good = client.post("/api/v1/plex/test", json={"url": REMOTE_URI + "/", "token": SERVER_TOKEN}).json()
        saved = client.post("/api/v1/plex/connect", json={"url": REMOTE_URI, "token": SERVER_TOKEN})

    assert bad == {"ok": False, "error": "The server rejected the token"}
    assert good == {"ok": True, "name": "Seedbox", "version": "1.41.2.9200", "url": REMOTE_URI}
    assert saved.status_code == 200
    assert read_plex(config).url == REMOTE_URI


def test_manual_url_is_checked(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        response = client.post("/api/v1/plex/test", json={"url": "203.0.113.7:32400", "token": SERVER_TOKEN})
    assert response.status_code == 422
    assert "http://" in response.json()["detail"]


def test_connect_without_a_config_path(tmp_path, fake):
    with make_client(tmp_path, fake, kometa_config=None) as client:
        response = client.post("/api/v1/plex/connect", json={"url": REMOTE_URI, "token": SERVER_TOKEN})
    assert response.status_code == 409
    assert "STUDIO_KOMETA_CONFIG" in response.json()["detail"]


def test_connect_needs_one_kind_of_server(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        assert client.post("/api/v1/plex/connect", json={"server_id": SERVER_ID}).status_code == 422
        assert client.post("/api/v1/plex/connect", json={}).status_code == 422


def test_sign_out(tmp_path, fake, config):
    with make_client(tmp_path, fake) as client:
        sign_in(client, fake)
        assert client.delete("/api/v1/plex/account").status_code == 204
        assert client.get("/api/v1/plex").json()["account"] is None
