import httpx
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_sections import read_section
from kometa_studio.settings import Settings

TMDB_KEY = "tmdb-good-key"
MDBLIST_KEY = "mdb-good-key"


class FakeServices:
    """TMDb's /configuration and MDBList's /user, as Kometa calls them."""

    TMDB_ADDRESS = "203.0.113.10"  # what 1.1.1.1 says api.themoviedb.org is

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.tmdb_blocked = False  # the network's DNS doesn't give TMDb's real address

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "1.1.1.1" and request.url.path == "/dns-query":
            assert request.headers["Accept"] == "application/dns-json"
            name = request.url.params["name"]
            return httpx.Response(200, json={"Status": 0, "Answer": [{"name": name, "type": 5, "data": "cname.example."}, {"name": name, "type": 1, "TTL": 300, "data": self.TMDB_ADDRESS}]})
        if request.url.host == self.TMDB_ADDRESS:  # reached by address: only TMDb's real name will do for TLS and Host
            assert request.extensions.get("sni_hostname") == "api.themoviedb.org" and request.headers["Host"] == "api.themoviedb.org"
            request.url = request.url.copy_with(host="api.themoviedb.org")
        elif request.url.host == "api.themoviedb.org" and self.tmdb_blocked:
            raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)
        if request.url.host == "api.themoviedb.org" and request.url.path == "/3/configuration":
            ok = request.url.params.get("api_key") == TMDB_KEY
            return httpx.Response(200, json={"images": {}}) if ok else httpx.Response(401, json={"status_message": "Invalid API key"})
        if request.url.host == "api.mdblist.com" and request.url.path == "/user":
            if request.url.params.get("apikey") != MDBLIST_KEY:
                return httpx.Response(403, json={"error": "Invalid API key!"})
            return httpx.Response(200, json={"api_requests": 1000, "api_requests_count": 312, "is_supporter": False})
        return httpx.Response(404)


def make_client(tmp_path, text="tmdb:\n  apikey: tmdb-old-key  # from the wiki\n  language: en\n"):
    config = tmp_path / "config.yml"
    config.write_text(text)
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config), static_dir=tmp_path / "no-static", http_transport=FakeServices().transport())
    return TestClient(app, client=("127.0.0.1", 50000)), config


def test_keys_are_read_from_config_yml_and_masked(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        state = client.get("/api/v1/settings/services").json()
    assert state == {"tmdb": {"apikey": "…-key", "bypass_dns": False}, "mdblist": {"apikey": None}}


def test_a_key_is_tested_and_mdblist_says_its_allowance(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        bad = client.post("/api/v1/settings/services/tmdb/test", json={"apikey": "nope"}).json()
        good = client.post("/api/v1/settings/services/tmdb/test", json={"apikey": TMDB_KEY}).json()
        mdb = client.post("/api/v1/settings/services/mdblist/test", json={"apikey": MDBLIST_KEY}).json()
        missing = client.post("/api/v1/settings/services/mdblist/test", json={})
    assert bad == {"ok": False, "error": "TMDb rejected the API key"}
    assert good == {"ok": True}
    assert mdb == {"ok": True, "limit": 1000, "used": 312}
    assert missing.status_code == 422


def test_a_key_is_saved_only_after_passing_its_test_and_the_rest_is_kept(tmp_path):
    client, config = make_client(tmp_path)
    with client:
        refused = client.put("/api/v1/settings/services/tmdb", json={"apikey": "nope"})
        assert "tmdb-old-key" in config.read_text()
        saved = client.put("/api/v1/settings/services/tmdb", json={"apikey": TMDB_KEY})
        mdb = client.put("/api/v1/settings/services/mdblist", json={"apikey": MDBLIST_KEY}).json()
    assert refused.status_code == 422 and refused.json()["detail"] == "Not saved: TMDb rejected the API key"
    assert saved.status_code == 200
    assert read_section(config, "tmdb") == {"apikey": TMDB_KEY, "language": "en"}
    assert "# from the wiki" in config.read_text()
    assert mdb == {"tmdb": {"apikey": "…-key", "bypass_dns": False}, "mdblist": {"apikey": "…-key"}}


def test_mdblist_can_be_removed_but_tmdb_cant(tmp_path):
    client, config = make_client(tmp_path, f"tmdb:\n  apikey: {TMDB_KEY}\nmdblist:\n  apikey: {MDBLIST_KEY}\n")
    with client:
        assert client.delete("/api/v1/settings/services/tmdb").status_code == 409
        state = client.delete("/api/v1/settings/services/mdblist").json()
    assert state["mdblist"] == {"apikey": None}
    assert "mdblist" not in config.read_text()


def test_tmdb_behind_a_dns_block_is_reached_over_dns_over_https_and_kept_for_that_key(tmp_path):
    from kometa_studio import network

    config = tmp_path / "config.yml"
    config.write_text(f"tmdb:\n  apikey: {TMDB_KEY}\n")
    fake = FakeServices()
    fake.tmdb_blocked = True
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config), static_dir=tmp_path / "no-static", http_transport=fake.transport())
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        blocked = client.post("/api/v1/settings/services/tmdb/test", json={}).json()
        bypassed = client.post("/api/v1/settings/services/tmdb/test", json={"bypass_dns": True}).json()
        saved = client.put("/api/v1/settings/services/tmdb", json={"bypass_dns": True}).json()
        db = client.app.state.db
        env = network.kometa_env(db, None, config, tmp_path / "data")
        assert config.read_text() == f"tmdb:\n  apikey: {TMDB_KEY}\n"  # same key: config.yml isn't rewritten

        # Another key in config.yml (edited by hand, say): the bypass was for the old one.
        config.write_text("tmdb:\n  apikey: another-key\n")
        assert client.get("/api/v1/settings/services").json()["tmdb"]["bypass_dns"] is False
        assert network.kometa_env(db, None, config, tmp_path / "data") == {}
        config.write_text(f"tmdb:\n  apikey: {TMDB_KEY}\n")
        still_blocked = client.put("/api/v1/settings/services/tmdb", json={"bypass_dns": False})  # tested without the bypass: refused
        fake.tmdb_blocked = False
        off = client.put("/api/v1/settings/services/tmdb", json={"bypass_dns": False}).json()
    assert blocked["ok"] is False and "Name or service not known" in blocked["error"]
    assert bypassed == {"ok": True}
    assert saved["tmdb"] == {"apikey": "…-key", "bypass_dns": True}
    assert env["STUDIO_DOH_HOSTS"] == "themoviedb.org,tmdb.org" and env["PYTHONPATH"].split(":")[0] == str(network.WRAPPER)
    assert still_blocked.status_code == 422
    assert off["tmdb"]["bypass_dns"] is False


def test_kometas_python_resolves_tmdb_over_dns_over_https(tmp_path):
    """The wrapper Kometa runs with: TMDb's names through DoH, everything else as usual."""
    import json
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from kometa_studio import network

    asked = []

    class DoH(BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            body = json.dumps({"Status": 0, "Answer": [{"type": 1, "TTL": 60, "data": "198.51.100.7"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/dns-json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), DoH)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = (
        "import socket\n"
        "print(sorted({a[4][0] for a in socket.getaddrinfo('api.themoviedb.org', 443)}))\n"
        "print(sorted({a[4][0] for a in socket.getaddrinfo('image.tmdb.org', 443, socket.AF_INET)}))\n"
        "print(sorted({a[4][0] for a in socket.getaddrinfo('localhost', 80, socket.AF_INET)}))\n"
    )
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(network.WRAPPER), "STUDIO_DOH_HOSTS": "themoviedb.org,tmdb.org", "STUDIO_DOH_URL": f"http://127.0.0.1:{server.server_port}/dns-query"}
    try:
        out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    finally:
        server.shutdown()
    assert out.stdout.splitlines() == ["['198.51.100.7']", "['198.51.100.7']", "['127.0.0.1']"], out.stderr
    assert len(asked) == 2 and "name=api.themoviedb.org" in asked[0]
