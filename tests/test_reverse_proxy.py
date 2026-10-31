import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.reverse_proxy import ReverseProxySettings, visitor
from kometa_studio.settings import Settings

PROXY = ("127.0.0.1", 50000)  # a reverse proxy on the same host
TRUSTED = ["127.0.0.1", "172.18.0.0/16"]


def headers(**values: str) -> dict[bytes, bytes]:
    return {name.replace("_", "-").encode(): value.encode() for name, value in values.items()}


@pytest.mark.parametrize(
    ("peer", "sent", "trusted", "expected"),
    [
        ("192.168.1.20", {}, [], ("192.168.1.20", False)),  # no proxy
        ("127.0.0.1", {"x_forwarded_for": "192.168.1.20"}, [], ("127.0.0.1", True)),  # a proxy nobody trusts: never local
        ("127.0.0.1", {"x_forwarded_for": "192.168.1.20"}, TRUSTED, ("192.168.1.20", False)),
        ("127.0.0.1", {"x_forwarded_for": "203.0.113.9"}, TRUSTED, ("203.0.113.9", False)),
        # The visitor wrote the first entry; the proxy appended the real one. Only the right-most untrusted entry counts.
        ("127.0.0.1", {"x_forwarded_for": "192.168.1.50, 203.0.113.9"}, TRUSTED, ("203.0.113.9", False)),
        ("127.0.0.1", {"x_forwarded_for": "192.168.1.20, 172.18.0.4"}, TRUSTED, ("192.168.1.20", False)),  # through two trusted proxies
        ("127.0.0.1", {"x_forwarded_for": "192.168.1.20:51234"}, TRUSTED, ("192.168.1.20", False)),
        ("127.0.0.1", {"x_forwarded_for": "unknown"}, TRUSTED, ("127.0.0.1", True)),  # can't read it: don't guess
        ("127.0.0.1", {"forwarded": 'for="[2001:db8::1]:4711";proto=https'}, TRUSTED, ("2001:db8::1", False)),
        ("127.0.0.1", {"x_real_ip": "10.0.0.7"}, TRUSTED, ("10.0.0.7", False)),
        ("8.8.8.8", {"x_forwarded_for": "192.168.1.20"}, TRUSTED, ("8.8.8.8", True)),  # not from a trusted proxy
    ],
)
def test_the_visitor_behind_trusted_proxies(peer, sent, trusted, expected):
    assert visitor(peer, headers(**sent), trusted) == expected


def test_settings_are_tidied_and_checked():
    settings = ReverseProxySettings.model_validate({"url_base": " kometa/ ", "trusted": ["127.0.0.1, 172.18.0.0/16", "::1"]})
    assert (settings.url_base, settings.trusted) == ("/kometa", ["127.0.0.1", "172.18.0.0/16", "::1"])
    assert ReverseProxySettings.model_validate({"url_base": "/"}).url_base == ""
    for bad in ({"url_base": "/my studio"}, {"url_base": "/api"}, {"url_base": "/assets/x"}, {"trusted": ["proxy.lan"]}, {"trusted": ["0.0.0.0/0"]}):
        with pytest.raises(ValueError):
            ReverseProxySettings.model_validate(bad)


def make_client(tmp_path, client=PROXY, static_dir=None):
    app = create_app(Settings(data_dir=tmp_path / "data"), static_dir=static_dir or tmp_path / "no-static")
    return TestClient(app, client=client)


def test_local_visitors_behind_a_trusted_proxy_skip_sign_in(tmp_path):
    with make_client(tmp_path, client=("192.168.1.20", 50000)) as lan:
        assert lan.put("/api/v1/settings/auth", json={"username": "hasan", "password": "correct horse", "required": "disabled_for_local"}).status_code == 200
        lan.post("/api/v1/auth/logout")
    with make_client(tmp_path) as proxy:
        from_lan = {"X-Forwarded-For": "192.168.1.20"}
        assert proxy.get("/api/v1/status", headers=from_lan).status_code == 401  # not trusted yet
        assert proxy.get("/api/v1/settings/general", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 401
    with make_client(tmp_path, client=("192.168.1.20", 50000)) as lan:
        saved = lan.put("/api/v1/settings/reverse-proxy", json={"url_base": "", "trusted": ["127.0.0.1"]}).json()
        bad = lan.put("/api/v1/settings/reverse-proxy", json={"trusted": ["0.0.0.0/0"]})
    assert saved["reverse_proxy"] == {"url_base": "", "trusted": ["127.0.0.1"]}
    assert saved["you"] == {"address": "192.168.1.20", "peer": "192.168.1.20", "proxied": False, "trusted_proxy": False, "local": True}
    assert bad.status_code == 422 and "every address" in bad.json()["detail"]
    with make_client(tmp_path) as proxy:
        general = proxy.get("/api/v1/settings/general", headers={"X-Forwarded-For": "192.168.1.20"})
        spoofed = proxy.get("/api/v1/status", headers={"X-Forwarded-For": "192.168.1.20, 8.8.8.8"})
    assert general.status_code == 200
    assert general.json()["you"] == {"address": "192.168.1.20", "peer": "127.0.0.1", "proxied": True, "trusted_proxy": True, "local": True}
    assert spoofed.status_code == 401


def test_failed_sign_ins_are_counted_per_visitor_behind_a_trusted_proxy(tmp_path):
    with make_client(tmp_path, client=("192.168.1.20", 50000)) as lan:
        lan.put("/api/v1/settings/auth", json={"username": "hasan", "password": "correct horse"})
        lan.put("/api/v1/settings/reverse-proxy", json={"trusted": ["127.0.0.1"]})
    with make_client(tmp_path) as proxy:
        for _ in range(10):
            proxy.post("/api/v1/auth/login", json={"username": "hasan", "password": "nope"}, headers={"X-Forwarded-For": "203.0.113.9"})
        attacker = proxy.post("/api/v1/auth/login", json={"username": "hasan", "password": "correct horse"}, headers={"X-Forwarded-For": "203.0.113.9"})
        someone_else = proxy.post("/api/v1/auth/login", json={"username": "hasan", "password": "correct horse"}, headers={"X-Forwarded-For": "198.51.100.4"})
    assert attacker.status_code == 429
    assert someone_else.status_code == 200


def test_studio_answers_under_its_url_base_and_without_it(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text('<html><head><script src="./assets/app.js"></script></head><body></body></html>')
    (static / "assets" / "app.js").write_text("console.log(1)")
    with make_client(tmp_path, client=("192.168.1.20", 50000), static_dir=static) as client:
        assert '<base href="/" />' in client.get("/libraries").text
        assert client.put("/api/v1/settings/reverse-proxy", json={"url_base": "/kometa"}).status_code == 200

        page = client.get("/kometa/libraries/Movies")
        assert page.status_code == 200 and '<head>\n    <base href="/kometa/" />' in page.text
        assert client.get("/kometa").status_code == 200
        assert client.get("/kometa/assets/app.js").text == "console.log(1)"
        assert client.get("/kometa/api/v1/ping").status_code == 200
        assert client.get("/api/v1/ping").status_code == 200  # Kometa's webhooks and proxies that strip the base
        assert client.get("/assets/app.js").text == "console.log(1)"
        moved = client.get("/system/tasks?x=1", follow_redirects=False)
        assert (moved.status_code, moved.headers["location"]) == (307, "/kometa/system/tasks?x=1")
        assert client.get("/kometa-other/x", follow_redirects=False).headers["location"] == "/kometa/kometa-other/x"  # not under the base
