import asyncio
import base64
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from kometa_studio import network
from kometa_studio.app import create_app
from kometa_studio.crypto import SecretBox
from kometa_studio.db import open_database, set_setting
from kometa_studio.network import NetworkSettings, NetworkTransport
from kometa_studio.settings import Settings


class Proxy:
    """A forward proxy on localhost that answers absolute-form requests itself (no internet needed), optionally asking for a login."""

    def __init__(self, login: tuple[str, str] | None = None):
        self.seen: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if login and self.headers.get("Proxy-Authorization") != "Basic " + base64.b64encode(":".join(login).encode()).decode():
                    self.send_response(407)
                    self.send_header("Proxy-Authenticate", 'Basic realm="proxy"')
                    self.end_headers()
                    return
                outer.seen.append(self.path)
                body = b"fl=1\nip=203.0.113.9\nloc=IN\n" if self.path.endswith("/cdn-cgi/trace") else b"via proxy"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def db(tmp_path):
    connection = open_database(tmp_path / "studio.db")
    yield connection
    connection.close()


def test_what_goes_direct():
    settings = NetworkSettings(no_proxy=[".example.com", "100.64.0.0/10", "nas"])
    for host in ("localhost", "127.0.0.1", "192.168.1.20", "10.1.2.3", "plex.local", "media.example.com", "100.64.1.1", "nas"):
        assert network.direct(host, settings), host
    for host in ("api.themoviedb.org", "8.8.8.8", "example.com.evil.net", "notnas"):
        assert not network.direct(host, settings), host


def test_no_proxy_entries_typed_with_commas_are_split(tmp_path, db):
    # As saved before entries were split: one line holding a comma-separated list, with a sentence's full stop.
    set_setting(db, network.SETTING, {"proxy_url": "http://proxy.lan:3128", "no_proxy": ["nas, 100.64.0.0/10, .example.com."]})
    settings = network.load(db)
    assert settings.no_proxy == ["nas", "100.64.0.0/10", ".example.com"]
    assert network.direct("media.example.com", settings) and network.direct("100.64.1.1", settings) and network.direct("nas", settings)
    assert network.split_entries(["a.lan b.lan", "", "a.lan,,c.lan"]) == ["a.lan", "b.lan", "c.lan"]
    env = network.kometa_env(db, None, tmp_path / "data")
    assert env["NO_PROXY"].endswith(",.local,nas,100.64.0.0/10,.example.com")


def test_kometa_gets_the_proxy_doh_and_ipv4_first_in_its_environment(tmp_path, db):
    box = SecretBox.load_or_create(tmp_path / "data")
    assert network.kometa_env(db, box, tmp_path / "data") == {}
    set_setting(
        db,
        network.SETTING,
        {
            "proxy_url": "http://proxy.lan:3128",
            "proxy_username": "hasan",
            "proxy_password": box.encrypt("p@ss:word"),
            "no_proxy": [".example.com"],
            "doh_services": ["mdblist"],
            "doh_provider": "google",
            "prefer_ipv4": True,
        },
    )
    env = network.kometa_env(db, box, tmp_path / "data")
    assert env["HTTPS_PROXY"] == env["http_proxy"] == "http://hasan:p%40ss%3Aword@proxy.lan:3128"
    assert env["NO_PROXY"].endswith(",.local,.example.com") and env["NO_PROXY"].startswith("localhost,127.0.0.0/8")
    assert (env["STUDIO_DOH_HOSTS"], env["STUDIO_DOH_URL"], env["STUDIO_PREFER_IPV4"]) == ("mdblist.com", "https://8.8.8.8/resolve", "1")
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(network.WRAPPER)

    set_setting(db, network.SETTING, {"proxy_url": "socks5://proxy.lan:1080"})
    env = network.kometa_env(db, box, tmp_path / "data")
    extras = tmp_path / "data" / "kometa-extras"
    assert env["HTTPS_PROXY"] == "socks5://proxy.lan:1080"
    assert env["PYTHONPATH"] == str(extras) and (extras / "socks.py").is_file()  # PySocks for Kometa's Python, from Studio's own


def test_studios_calls_use_the_proxy_except_for_local_addresses(tmp_path, db):
    proxy = Proxy(login=("hasan", "secret"))
    box = SecretBox.load_or_create(tmp_path / "data")
    set_setting(db, network.SETTING, {"proxy_url": proxy.url, "proxy_username": "hasan", "proxy_password": box.encrypt("secret")})

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"direct")

        def log_message(self, *args):
            pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()

    async def scenario():
        async with httpx.AsyncClient(transport=NetworkTransport(db, box, None)) as http:
            far = await http.get("http://api.example.test/3/configuration")
            near = await http.get(f"http://127.0.0.1:{origin.server_port}/")
            return far.text, near.text

    try:
        assert asyncio.run(scenario()) == ("via proxy", "direct")
        assert proxy.seen == ["http://api.example.test/3/configuration"]
    finally:
        proxy.close()
        origin.shutdown()


def test_studios_calls_to_ticked_services_resolve_over_doh(tmp_path, db):
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("Host"), request.extensions.get("sni_hostname")))
        if request.url.host == "8.8.8.8":
            return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1, "TTL": 300, "data": "198.51.100.4"}]})
        return httpx.Response(200, json={"api_requests": 1000})

    set_setting(db, network.SETTING, {"doh_services": ["mdblist"], "doh_provider": "google"})

    async def scenario():
        async with httpx.AsyncClient(transport=NetworkTransport(db, None, None, httpx.MockTransport(handle))) as http:
            await http.get("https://api.mdblist.com/user")
            await http.get("https://api.mdblist.com/user")  # the address is kept for its TTL
            await http.get("https://api.themoviedb.org/3/configuration")  # not ticked: as usual

    asyncio.run(scenario())
    assert seen == [
        ("https://8.8.8.8/resolve?name=api.mdblist.com&type=A", "8.8.8.8", None),
        ("https://198.51.100.4/user", "api.mdblist.com", "api.mdblist.com"),
        ("https://198.51.100.4/user", "api.mdblist.com", "api.mdblist.com"),
        ("https://api.themoviedb.org/3/configuration", "api.themoviedb.org", None),
    ]


# --- The page -------------------------------------------------------------------------


def make_client(tmp_path, handle=None):
    config = tmp_path / "config.yml"
    config.write_text("plex:\n  url: http://192.168.1.10:32400\n  token: t\n")
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config), static_dir=tmp_path / "no-static", http_transport=httpx.MockTransport(handle or (lambda r: httpx.Response(404))))
    return TestClient(app, client=("127.0.0.1", 50000))


def test_a_proxy_is_saved_only_after_it_works(tmp_path, monkeypatch):
    proxy = Proxy(login=("hasan", "secret"))
    monkeypatch.setattr(network, "TRACE_URL", "http://trace.test/cdn-cgi/trace")
    try:
        with make_client(tmp_path) as client:
            bad = client.post("/api/v1/settings/network/proxy/test", json={"url": "ftp://proxy"})
            no_login = client.post("/api/v1/settings/network/proxy/test", json={"url": proxy.url}).json()
            refused = client.put("/api/v1/settings/network/proxy", json={"url": proxy.url})
            tested = client.post("/api/v1/settings/network/proxy/test", json={"url": proxy.url, "username": "hasan", "password": "secret"}).json()
            saved = client.put("/api/v1/settings/network/proxy", json={"url": proxy.url, "username": "hasan", "password": "secret", "no_proxy": [" nas ", ""]}).json()
            page = client.get("/api/v1/settings/network").text
            kept = client.put("/api/v1/settings/network/proxy", json={"url": proxy.url, "username": "hasan", "no_proxy": ["nas"]})  # password kept
            cleared = client.put("/api/v1/settings/network/proxy", json={"url": None}).json()
    finally:
        proxy.close()
    assert bad.status_code == 422
    assert no_login == {"ok": False, "error": "The proxy wants a username and password"}
    assert refused.status_code == 422 and refused.json()["detail"].startswith("Not saved")
    assert tested == {"ok": True, "ip": "203.0.113.9"}
    assert (saved["proxy_url"], saved["proxy_username"], saved["has_password"], saved["no_proxy"]) == (proxy.url, "hasan", True, ["nas"])
    assert "secret" not in page
    assert kept.status_code == 200
    assert (cleared["proxy_url"], cleared["proxy_username"], cleared["has_password"]) == (None, None, False)


def test_dns_over_https_is_saved_only_after_each_ticked_service_resolves(tmp_path):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "1.1.1.1":
            name = request.url.params["name"]
            answer = [] if name == "www.imdb.com" or name == "imdb.com" else [{"type": 1, "TTL": 60, "data": "198.51.100.8"}]
            return httpx.Response(200, json={"Status": 0, "Answer": answer})
        return httpx.Response(404)

    with make_client(tmp_path, handle) as client:
        good = client.post("/api/v1/settings/network/doh/test", json={"provider": "cloudflare", "services": ["tmdb", "mdblist"]}).json()
        bad = client.put("/api/v1/settings/network/doh", json={"provider": "cloudflare", "services": ["imdb"]})
        unknown = client.put("/api/v1/settings/network/doh", json={"services": ["trakt"]})
        saved = client.put("/api/v1/settings/network/doh", json={"provider": "cloudflare", "services": ["tmdb", "mdblist"]}).json()
        ipv4 = client.put("/api/v1/settings/network/ipv4", json={"prefer_ipv4": True}).json()
    assert good == {"ok": True, "found": {"tmdb": "198.51.100.8", "mdblist": "198.51.100.8"}}
    assert bad.status_code == 422 and "has no address for imdb.com" in bad.json()["detail"]
    assert unknown.status_code == 422
    assert saved["doh_services"] == ["tmdb", "mdblist"] and ipv4["prefer_ipv4"] is True
    assert [s["id"] for s in saved["services"]][:2] == ["tmdb", "mdblist"]


def test_the_connection_check_spots_a_dns_block(tmp_path, monkeypatch):
    blocked = "49.44.79.236"  # what the network's DNS says api.themoviedb.org is

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "1.1.1.1":
            return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1, "TTL": 60, "data": "13.224.0.10"}]})
        if request.url.host == "api.themoviedb.org":
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", request=request)
        if request.url.host == "13.224.0.10":
            return httpx.Response(401, json={"status_message": "Invalid API key"})
        if request.url.host == "192.168.1.10":
            return httpx.Response(200, json={"MediaContainer": {}})
        raise httpx.ConnectError("unreachable", request=request)

    async def system_lookup(host):
        return [blocked] if host == "api.themoviedb.org" else ["192.168.1.10"] if host == "192.168.1.10" else []

    monkeypatch.setattr(network, "system_lookup", system_lookup)
    monkeypatch.setattr(network, "targets", lambda config: [("Plex", "http://192.168.1.10:32400/identity"), ("TMDb", "https://api.themoviedb.org/3/")])
    with make_client(tmp_path, handle) as client:
        results = {row["name"]: row for row in client.post("/api/v1/network/check").json()["results"]}
    tmdb = results["TMDb"]
    assert (tmdb["system_dns"], tmdb["doh_dns"], tmdb["ok"]) == ([blocked], ["13.224.0.10"], False)
    assert tmdb["verdict"] == "Blocked by this network's DNS: works over DNS over HTTPS, or through a proxy"
    plex = results["Plex"]
    assert (plex["ok"], plex["status"], plex["doh_dns"], plex["verdict"], plex["via"]) == (True, 200, None, "OK", "direct")


def test_an_address_that_resets_is_skipped_for_the_next(tmp_path, db):
    """As on the maintainer's network: some of a CDN's addresses get reset."""
    tried = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "1.1.1.1":
            return httpx.Response(200, json={"Answer": [{"type": 1, "TTL": 60, "data": "3.175.86.50"}, {"type": 1, "TTL": 60, "data": "3.175.86.67"}]})
        tried.append(request.url.host)
        if request.url.host == "3.175.86.50":
            raise httpx.ConnectError("Connection reset by peer", request=request)
        return httpx.Response(401)

    set_setting(db, network.SETTING, {"doh_services": ["tmdb"]})

    async def scenario():
        async with httpx.AsyncClient(transport=NetworkTransport(db, None, None, httpx.MockTransport(handle))) as http:
            through_studio = (await http.get("https://api.themoviedb.org/3/")).status_code
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as plain:
            from kometa_studio import doh

            through_doh_get = (await doh.get(plain, "https://api.themoviedb.org/3/")).status_code
        return through_studio, through_doh_get

    assert asyncio.run(scenario()) == (401, 401)
    assert tried == ["3.175.86.50", "3.175.86.67", "3.175.86.50", "3.175.86.67"]
