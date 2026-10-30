"""Settings → Network (feedback round 1): a proxy, DNS over HTTPS for chosen services, and IPv4 first,
for Studio's own calls and Kometa's alike, and a connection check.

Studio's calls all go through one httpx client whose transport is ``NetworkTransport``. Per request it:
- sends the request through the proxy, unless the host is local (``LOCAL``) or on the user's
  ``no_proxy`` list;
- otherwise, for a host of a ticked service (``SERVICES``), looks it up over DNS over HTTPS and
  connects to that address, with the real name for TLS (SNI) and in the Host header;
- binds IPv4 when IPv4 comes first.

Kometa gets the same through its environment (``kometa_env``): HTTP_PROXY, HTTPS_PROXY and NO_PROXY,
which requests honours, and ``kometa_doh/`` on PYTHONPATH, whose sitecustomize answers the ticked
services' names over DoH and puts IPv4 first. A SOCKS5 proxy also needs PySocks in Kometa's Python:
Studio copies its own (one module) into ``<data>/kometa-extras`` and adds that to the path, so
nothing is installed into Kometa's environment.

The proxy resolves names itself, so DoH only matters for connections that don't use it. TMDb's DNS
bypass on Settings → Connect (doh.py) is a quick fix, honoured here too until it's removed.
"""

import asyncio
import ipaddress
import json
import os
import shutil
import socket
import sqlite3
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field

from . import doh
from .config_sections import read_section
from .crypto import SecretBox
from .db import get_setting

SETTING = "network"
WRAPPER = Path(__file__).parent / "kometa_doh"
TIMEOUT = 10.0
CHECK_TIMEOUT = 8.0

SERVICES: dict[str, tuple[str, tuple[str, ...]]] = {  # what DNS over HTTPS can be ticked for: name, and the domains it covers
    "tmdb": ("TMDb", ("themoviedb.org", "tmdb.org")),
    "mdblist": ("MDBList", ("mdblist.com",)),
    "imdb": ("IMDb", ("imdb.com", "media-amazon.com")),
    "tvdb": ("TheTVDB", ("thetvdb.com",)),
    "plextv": ("plex.tv", ("plex.tv", "plex.direct")),
    "letterboxd": ("Letterboxd", ("letterboxd.com",)),
    "github": ("GitHub (Kometa's defaults and updates)", ("github.com", "githubusercontent.com")),
}
PROVIDERS = {
    "cloudflare": ("Cloudflare (1.1.1.1)", "https://1.1.1.1/dns-query"),
    "google": ("Google (8.8.8.8)", "https://8.8.8.8/resolve"),
}
# Never through the proxy: this machine and private networks (Plex or the arr apps on the LAN, Studio's own webhook receiver).
LOCAL = ["localhost", "127.0.0.0/8", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", ".local"]


class NetworkSettings(BaseModel):
    proxy_url: str | None = None  # http://host:port, https://host:port or socks5://host:port
    proxy_username: str | None = None
    proxy_password: str | None = None  # encrypted
    no_proxy: list[str] = Field(default_factory=list)  # more hosts, domains (.example.com) or networks (CIDR) to reach directly
    doh_provider: Literal["cloudflare", "google"] = "cloudflare"
    doh_services: list[str] = Field(default_factory=list)
    prefer_ipv4: bool = False


def load(db: sqlite3.Connection) -> NetworkSettings:
    return NetworkSettings.model_validate(get_setting(db, SETTING) or {})


def proxy_with_login(settings: NetworkSettings, box: SecretBox | None) -> str | None:
    """The proxy URL with its login in it, as HTTP_PROXY wants it."""
    if not settings.proxy_url:
        return None
    if not settings.proxy_username:
        return settings.proxy_url
    password = (box.decrypt(settings.proxy_password) or "") if box and settings.proxy_password else ""
    parts = urlsplit(settings.proxy_url)
    login = quote(settings.proxy_username, safe="") + (":" + quote(password, safe="") if password else "")
    return parts._replace(netloc=f"{login}@{parts.netloc}").geturl()


def _matches(host: str, entry: str) -> bool:
    host, entry = host.lower().rstrip("."), entry.strip().lower()
    if not entry:
        return False
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(entry, strict=False)
    except ValueError:
        pass
    domain = entry.lstrip("*").lstrip(".")
    return host == domain or host.endswith("." + domain)


def direct(host: str, settings: NetworkSettings) -> bool:
    """Whether ``host`` is reached without the proxy."""
    return any(_matches(host, entry) for entry in LOCAL + settings.no_proxy)


def doh_domains(db: sqlite3.Connection, settings: NetworkSettings, config: Path | None) -> list[str]:
    """The domains looked up over DoH: the ticked services', and TMDb's while its key's quick fix is on (``config`` given)."""
    domains = [domain for name in settings.doh_services if name in SERVICES for domain in SERVICES[name][1]]
    if config is not None and doh.enabled(db, config):  # the TMDb key's quick fix
        domains += [domain for domain in doh.HOSTS if domain not in domains]
    return domains


def _covered(host: str, domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


# --- Kometa ---------------------------------------------------------------------------


def socks_module(data_dir: Path) -> Path | None:
    """A folder holding PySocks for Kometa's Python (copied from Studio's own), or None if Studio has none."""
    spec = find_spec("socks")
    if spec is None or spec.origin is None:
        return None
    folder = data_dir / "kometa-extras"
    target = folder / "socks.py"
    if not target.exists() or target.stat().st_size != Path(spec.origin).stat().st_size:
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(spec.origin, target)
    return folder


def kometa_env(db: sqlite3.Connection, box: SecretBox | None, config: Path | None, data_dir: Path) -> dict[str, str]:
    """Extra environment for Kometa's runs and checks."""
    settings = load(db)
    env: dict[str, str] = {}
    paths: list[str] = []
    domains = doh_domains(db, settings, config)
    if domains or settings.prefer_ipv4:
        paths.append(str(WRAPPER))
        if domains:
            env |= {"STUDIO_DOH_HOSTS": ",".join(domains), "STUDIO_DOH_URL": PROVIDERS[settings.doh_provider][1]}
        if settings.prefer_ipv4:
            env["STUDIO_PREFER_IPV4"] = "1"
    proxy = proxy_with_login(settings, box)
    if proxy:
        no_proxy = ",".join(LOCAL + settings.no_proxy)
        env |= {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "NO_PROXY": no_proxy, "http_proxy": proxy, "https_proxy": proxy, "no_proxy": no_proxy}
        if proxy.startswith("socks"):
            folder = socks_module(data_dir)
            if folder is not None:
                paths.append(str(folder))
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
    return env


# --- Studio's own calls ----------------------------------------------------------------


class NetworkTransport(httpx.AsyncBaseTransport):
    """Studio's transport: the proxy, DNS over HTTPS and IPv4 first, as Settings → Network says (see the module's docstring)."""

    def __init__(self, db: sqlite3.Connection, box: SecretBox, config: Path | None, inner: httpx.AsyncBaseTransport | None = None):
        self.db = db
        self.box = box
        self.config = config
        self.inner = inner  # tests hand in a mock; it then stands in for every direct connection
        self._key: str | None = None
        self._direct: httpx.AsyncBaseTransport | None = None
        self._proxy: httpx.AsyncBaseTransport | None = None
        self._cache: dict[str, tuple[float, list[str]]] = {}

    def _transports(self, settings: NetworkSettings) -> tuple[httpx.AsyncBaseTransport, httpx.AsyncBaseTransport | None]:
        key = settings.model_dump_json()
        if key != self._key or self._direct is None:
            old = [t for t in (self._direct, self._proxy) if t is not None and t is not self.inner]
            local = "0.0.0.0" if settings.prefer_ipv4 else None
            self._direct = self.inner or httpx.AsyncHTTPTransport(local_address=local)
            proxy = proxy_with_login(settings, self.box)
            self._proxy = httpx.AsyncHTTPTransport(proxy=proxy, local_address=local) if proxy else None
            self._key = key
            for transport in old:  # requests already under way keep their connections
                asyncio.get_running_loop().call_later(60, lambda t=transport: asyncio.ensure_future(t.aclose()))
        return self._direct, self._proxy

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        settings = load(self.db)
        straight, proxy = self._transports(settings)
        host = request.url.host
        if proxy is not None and not direct(host, settings):
            return await proxy.handle_async_request(request)
        # The Network page's DoH only: the TMDb quick fix is for Kometa, since Studio's own TMDb calls (key tests) say whether to bypass.
        domains = doh_domains(self.db, settings, None)
        if domains and not _is_address(host) and _covered(host, domains):
            failed: httpx.TransportError | None = None
            request.extensions = request.extensions | {"sni_hostname": host}
            for address in await self._resolve(straight, host, PROVIDERS[settings.doh_provider][1]):
                request.url = request.url.copy_with(host=address)  # the Host header keeps the real name
                try:
                    return await straight.handle_async_request(request)
                except (httpx.ConnectError, httpx.ConnectTimeout) as error:  # not connected, nothing sent: try the next address
                    failed = error
            raise failed  # type: ignore[misc]
        return await straight.handle_async_request(request)

    async def _resolve(self, transport: httpx.AsyncBaseTransport, host: str, url: str) -> list[str]:
        cached = self._cache.get(host)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        query = httpx.Request("GET", url, params={"name": host, "type": "A"}, headers={"Accept": "application/dns-json"}, extensions={"timeout": {"connect": TIMEOUT, "read": TIMEOUT, "write": TIMEOUT, "pool": TIMEOUT}})
        try:
            response = await transport.handle_async_request(query)
            data = json.loads(await response.aread())
        except (httpx.HTTPError, ValueError) as error:
            raise httpx.ConnectError(f"Couldn't look up {host} over DNS over HTTPS: {error}", request=query) from None
        answers = [a for a in data.get("Answer") or [] if isinstance(a, dict) and a.get("type") == 1 and a.get("data")]
        if not answers:
            raise httpx.ConnectError(f"DNS over HTTPS has no address for {host}", request=query)
        ttl = min(int(a.get("TTL", 300)) for a in answers)
        addresses = [str(a["data"]) for a in answers]
        self._cache[host] = (time.monotonic() + max(ttl, 30), addresses)
        return addresses

    async def aclose(self) -> None:
        for transport in (self._direct, self._proxy):
            if transport is not None:
                await transport.aclose()


# --- Tests and the connection check ----------------------------------------------------

TRACE_URL = "https://1.1.1.1/cdn-cgi/trace"  # Cloudflare says which address a request came from


async def test_proxy(proxy: str) -> str:
    """The address the internet sees through ``proxy``; raises httpx.HTTPError if it doesn't work."""
    async with httpx.AsyncClient(proxy=proxy, timeout=TIMEOUT) as client:
        response = await client.get(TRACE_URL)
        response.raise_for_status()
    found = dict(line.split("=", 1) for line in response.text.splitlines() if "=" in line)
    return found.get("ip", "an address Cloudflare didn't say")


async def system_lookup(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def targets(config: Path | None) -> list[tuple[str, str]]:
    """What the connection check tries: Kometa's and Studio's services, with the ones config.yml points at."""
    found = [
        ("plex.tv", "https://plex.tv/"),
        ("TMDb", "https://api.themoviedb.org/3/"),
        ("TMDb images", "https://image.tmdb.org/t/p/w92/"),
        ("MDBList", "https://api.mdblist.com/"),
        ("IMDb", "https://www.imdb.com/"),
        ("TheTVDB", "https://www.thetvdb.com/"),
        ("GitHub", "https://raw.githubusercontent.com/"),
    ]
    for key, name, path in (("plex", "Plex", "/identity"), ("radarr", "Radarr", "/api/v3/system/status"), ("sonarr", "Sonarr", "/api/v3/system/status")):
        url = (read_section(config, key) or {}).get("url")
        if url:
            found.insert(0 if key == "plex" else len(found), (name, str(url).rstrip("/") + path))
    return found


async def check_one(http: httpx.AsyncClient, db: sqlite3.Connection, name: str, url: str) -> dict:
    """DNS from the system and over DoH, then a request the way Studio makes them. Kometa runs from here too, so it fares the same."""
    settings = load(db)
    host = urlsplit(url).hostname or ""
    row: dict = {"name": name, "url": url, "host": host, "via": "direct" if direct(host, settings) or not settings.proxy_url else "proxy"}
    local = direct(host, NetworkSettings())  # LAN addresses: DoH can't know them
    try:
        row["system_dns"] = await system_lookup(host)
    except OSError as error:
        row["system_dns"], row["system_dns_error"] = [], str(error)
    row["doh_dns"] = None
    if not local and not _is_address(host):
        try:
            row["doh_dns"] = [await doh.resolve(http, host)]
        except doh.DohProblem as error:
            row["doh_dns_error"] = str(error)
    started = time.monotonic()
    try:
        response = await http.get(url, timeout=CHECK_TIMEOUT, follow_redirects=False)
        row |= {"ok": True, "status": response.status_code, "ms": round((time.monotonic() - started) * 1000), "error": None}
    except httpx.HTTPError as error:
        row |= {"ok": False, "status": None, "ms": None, "error": str(error) or type(error).__name__}
    row["verdict"] = await _verdict(http, row)
    return row


async def _verdict(http: httpx.AsyncClient, row: dict) -> str:
    if row["ok"]:
        return "OK"
    if row["via"] == "direct" and row.get("doh_dns") and row["doh_dns"] != row["system_dns"]:
        try:  # the address DoH gives, with the real name for TLS
            await doh.get(http, row["url"], timeout=CHECK_TIMEOUT, follow_redirects=False)
            return "Blocked by this network's DNS: works over DNS over HTTPS, or through a proxy"
        except (httpx.HTTPError, doh.DohProblem):
            pass
    if "CERTIFICATE_VERIFY_FAILED" in (row["error"] or ""):
        return "The certificate doesn't match: something on the way answers for this name"
    return "Unreachable from here" + (" through the proxy" if row["via"] == "proxy" else "")


async def check(http: httpx.AsyncClient, db: sqlite3.Connection, config: Path | None) -> list[dict]:
    return list(await asyncio.gather(*(check_one(http, db, name, url) for name, url in targets(config))))
