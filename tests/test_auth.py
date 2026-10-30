import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.auth import check_password, hash_password, is_local
from kometa_studio.settings import Settings

LOCAL = ("192.168.1.20", 50000)
REMOTE = ("8.8.8.8", 50000)


def make_client(tmp_path, client=LOCAL):
    app = create_app(Settings(data_dir=tmp_path / "data"), static_dir=tmp_path / "no-static")
    return TestClient(app, client=client)


def set_up_sign_in(client, required="enabled"):
    response = client.put("/api/v1/settings/auth", json={"username": "hasan", "password": "correct horse", "required": required})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("host", "proxied", "local"),
    [
        ("127.0.0.1", False, True),
        ("::1", False, True),
        ("10.0.0.5", False, True),
        ("172.17.0.1", False, True),  # Docker's bridge: the PC's own browser, through the port mapping
        ("192.168.1.20", False, True),
        ("::ffff:192.168.1.20", False, True),
        ("fe80::1%eth0", False, True),
        ("8.8.8.8", False, False),
        ("100.101.102.103", False, False),  # carrier-grade NAT (Tailscale) isn't the local network
        ("127.0.0.1", True, False),  # a proxy on the same host relays the internet
        ("testclient", False, False),
        (None, False, False),
    ],
)
def test_local_addresses(host, proxied, local):
    assert is_local(host, proxied) is local


def test_passwords_are_hashed():
    stored = hash_password("correct horse")
    assert "correct horse" not in stored
    assert check_password("correct horse", stored)
    assert not check_password("wrong", stored)
    assert not check_password("correct horse", "garbage")


def test_before_sign_in_is_set_up_only_local_addresses_get_in(tmp_path):
    with make_client(tmp_path) as local:
        assert local.get("/api/v1/status").status_code == 200
        assert local.get("/api/v1/auth").json() | {"message": None} == {
            "allowed": True,
            "reason": None,
            "message": None,
            "configured": False,
            "signed_in": False,
            "local": True,
        }
        # Through a reverse proxy, the same address is the internet.
        assert local.get("/api/v1/status", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 401
    with make_client(tmp_path, REMOTE) as remote:
        refused = remote.get("/api/v1/status")
        status = remote.get("/api/v1/auth").json()
    assert refused.status_code == 401
    assert refused.json()["detail"]["reason"] == "setup"
    assert (status["allowed"], status["reason"]) == (False, "setup")


def test_signing_in_and_out(tmp_path):
    with make_client(tmp_path) as client:
        set_up_sign_in(client)
        assert client.get("/api/v1/status").status_code == 200  # setting it up signed this browser in
        client.post("/api/v1/auth/logout")
        assert client.get("/api/v1/status").status_code == 401  # "enabled" means local addresses sign in too

        wrong = client.post("/api/v1/auth/login", json={"username": "hasan", "password": "nope"})
        assert wrong.status_code == 401
        right = client.post("/api/v1/auth/login", json={"username": "hasan", "password": "correct horse"})
        assert right.status_code == 200
        cookie = right.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert client.get("/api/v1/status").status_code == 200
        assert client.get("/api/v1/auth").json()["signed_in"] is True


def test_disabled_for_local_addresses(tmp_path):
    with make_client(tmp_path) as local:
        set_up_sign_in(local, required="disabled_for_local")
        local.post("/api/v1/auth/logout")
        assert local.get("/api/v1/status").status_code == 200
    with make_client(tmp_path, REMOTE) as remote:
        assert remote.get("/api/v1/status").json()["detail"]["reason"] == "login"
        remote.post("/api/v1/auth/login", json={"username": "hasan", "password": "correct horse"})
        assert remote.get("/api/v1/status").status_code == 200


def test_the_api_key_opens_everything_and_can_be_replaced(tmp_path):
    with make_client(tmp_path) as local:
        key = set_up_sign_in(local)["api_key"]
        assert len(key) == 32
    with make_client(tmp_path, REMOTE) as remote:
        assert remote.get("/api/v1/status", headers={"X-Api-Key": key}).status_code == 200
        assert remote.get(f"/api/v1/status?apikey={key}").status_code == 200
        assert remote.get("/api/v1/status", headers={"X-Api-Key": "wrong"}).status_code == 401
        new_key = remote.post("/api/v1/settings/api-key", headers={"X-Api-Key": key}).json()["api_key"]
        assert new_key != key
        assert remote.get("/api/v1/status", headers={"X-Api-Key": key}).status_code == 401


def test_changing_sign_in_needs_the_current_password_and_signs_others_out(tmp_path):
    with make_client(tmp_path) as first, make_client(tmp_path) as second:
        set_up_sign_in(first)
        second.post("/api/v1/auth/login", json={"username": "hasan", "password": "correct horse"})
        assert second.get("/api/v1/status").status_code == 200

        change = {"username": "hasan", "password": "battery staple", "required": "enabled"}
        assert first.put("/api/v1/settings/auth", json=change).status_code == 403
        assert first.put("/api/v1/settings/auth", json=change | {"current_password": "correct horse"}).status_code == 200
        assert first.get("/api/v1/status").status_code == 200
        assert second.get("/api/v1/status").status_code == 401


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"username": "hasan", "required": "enabled"}, 422),  # no password
        ({"username": "hasan", "password": "short", "required": "enabled"}, 422),
        ({"username": "  ", "password": "long enough", "required": "enabled"}, 422),
    ],
)
def test_sign_in_needs_a_username_and_a_real_password(tmp_path, body, status):
    with make_client(tmp_path) as client:
        assert client.put("/api/v1/settings/auth", json=body).status_code == status


def test_changes_from_other_websites_are_refused(tmp_path):
    with make_client(tmp_path) as client:
        evil = client.post("/api/v1/runs", json={}, headers={"Origin": "https://evil.example"})
        fetch_metadata = client.post("/api/v1/runs", json={}, headers={"Sec-Fetch-Site": "cross-site"})
        reading = client.get("/api/v1/status", headers={"Origin": "https://evil.example"})
        same_site = client.put("/api/v1/settings/timezone", json={"timezone": "Asia/Kolkata"}, headers={"Origin": "http://testserver"})
    assert evil.status_code == fetch_metadata.status_code == 403
    assert evil.json()["detail"]["reason"] == "cross_site"
    assert reading.status_code == 200  # another site can't read the answer anyway
    assert same_site.status_code == 200 and same_site.json()["timezone"] == "Asia/Kolkata"


def test_too_many_failed_sign_ins_wait(tmp_path):
    with make_client(tmp_path) as client:
        set_up_sign_in(client)
        for _ in range(10):
            client.post("/api/v1/auth/login", json={"username": "hasan", "password": "nope"})
        blocked = client.post("/api/v1/auth/login", json={"username": "hasan", "password": "correct horse"})
    assert blocked.status_code == 429


def test_webhooks_check_their_own_token_not_sign_in(tmp_path):
    with make_client(tmp_path) as local:
        set_up_sign_in(local)
    with make_client(tmp_path, REMOTE) as remote:
        response = remote.post("/api/v1/kometa/events?token=wrong", json={"event": "run_start"})
    assert response.status_code == 403  # reached the receiver, which refused the token


def test_the_timezone_setting_survives_a_restart(tmp_path):
    with make_client(tmp_path) as client:
        assert client.put("/api/v1/settings/timezone", json={"timezone": "Nowhere/Special"}).status_code == 422
        client.put("/api/v1/settings/timezone", json={"timezone": "Asia/Kolkata"})
    with make_client(tmp_path) as client:
        assert client.get("/api/v1/schedules").json()["timezone"] == "Asia/Kolkata"
