"""Talking to plex.tv and Plex servers: PIN sign-in, server discovery, connection probing.

Modelled on Overseerr's flow (handoff v2 §4). Every function takes an httpx.AsyncClient
so tests can swap in a mock transport.
"""

import asyncio
import socket
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx

from . import __version__

PLEX_TV = "https://plex.tv"
PRODUCT = "Kometa Studio"
PROBE_TIMEOUT = 5.0


class PlexError(Exception):
    """A plex.tv or Plex server request failed; the message is shown to the user."""


class PinExpired(PlexError):
    pass


class TokenRejected(PlexError):
    pass


def client_headers(client_id: str, token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Version": __version__,
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Platform": "Web",
        "X-Plex-Device": PRODUCT,
        "X-Plex-Device-Name": PRODUCT,
    }
    if token:
        headers["X-Plex-Token"] = token
    return headers


# --- Sign in (PIN flow) ---------------------------------------------------------


@dataclass(frozen=True)
class Pin:
    id: int
    code: str


async def create_pin(client: httpx.AsyncClient, client_id: str) -> Pin:
    response = await _plex_tv(client, "POST", "/api/v2/pins", client_id, params={"strong": "true"})
    data = response.json()
    return Pin(int(data["id"]), str(data["code"]))


async def check_pin(client: httpx.AsyncClient, client_id: str, pin_id: int) -> str | None:
    """Return the account token once the user has approved the PIN, None while still waiting."""
    try:
        response = await _plex_tv(client, "GET", f"/api/v2/pins/{pin_id}", client_id)
    except PlexError as error:
        if isinstance(error.__cause__, httpx.HTTPStatusError) and error.__cause__.response.status_code == 404:
            raise PinExpired("The sign-in code expired. Start again.") from None
        raise
    data = response.json()
    if data.get("authToken"):
        return str(data["authToken"])
    if data.get("expiresIn", 1) <= 0:
        raise PinExpired("The sign-in code expired. Start again.")
    return None


def auth_url(client_id: str, pin: Pin) -> str:
    """The app.plex.tv page the user signs in on. It approves the PIN for our client ID."""
    params = {
        "clientID": client_id,
        "code": pin.code,
        "context[device][product]": PRODUCT,
        "context[device][version]": __version__,
        "context[device][platform]": "Web",
        "context[device][device]": PRODUCT,
    }
    return "https://app.plex.tv/auth/#!?" + urlencode(params)


async def account_name(client: httpx.AsyncClient, client_id: str, token: str) -> str:
    response = await _plex_tv(client, "GET", "/api/v2/user", client_id, token=token)
    data = response.json()
    return str(data.get("username") or data.get("title") or data.get("email") or "Plex account")


# --- Find servers ----------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One way of reaching a server."""

    uri: str
    local: bool
    relay: bool

    @property
    def secure(self) -> bool:
        return self.uri.startswith("https://")


@dataclass(frozen=True)
class Server:
    id: str  # Plex's clientIdentifier, the same as the server's machineIdentifier
    name: str
    version: str
    token: str  # the server's own accessToken, which Kometa needs
    candidates: list[Candidate] = field(default_factory=list)


@dataclass(frozen=True)
class Probe:
    candidate: Candidate
    ok: bool
    error: str | None = None
    latency_ms: int | None = None


async def fetch_servers(client: httpx.AsyncClient, client_id: str, account_token: str) -> list[Server]:
    response = await _plex_tv(
        client,
        "GET",
        "/api/resources",
        client_id,
        token=account_token,
        params={"includeHttps": "1", "includeRelay": "1"},
        accept="application/xml",
    )
    return parse_resources(response.text)


def parse_resources(xml_text: str) -> list[Server]:
    """Parse plex.tv's resources XML into the servers this account owns."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise PlexError(f"plex.tv sent a server list Studio can't read: {error}") from None
    servers = []
    for device in root.iter("Device"):
        provides = device.get("provides", "").split(",")
        if "server" not in provides or device.get("owned") != "1":
            continue
        connections = [
            (c.get("uri", ""), c.get("address", ""), c.get("port", ""), c.get("local") == "1", c.get("relay") == "1")
            for c in device.iter("Connection")
        ]
        servers.append(
            Server(
                id=device.get("clientIdentifier", ""),
                name=device.get("name", "Plex Media Server"),
                version=device.get("productVersion", ""),
                token=device.get("accessToken", ""),
                candidates=expand_connections(connections),
            )
        )
    return servers


def expand_connections(connections: list[tuple[str, str, str, bool, bool]]) -> list[Candidate]:
    """Turn plex.tv's connection list into URLs to try.

    Like Overseerr, each direct connection gives two candidates: the plex.direct HTTPS URI
    (a valid certificate) and the plain IP over HTTP, for servers where plex.direct DNS
    doesn't resolve (some routers block it). Relays are only reachable by their URI.
    """
    candidates: dict[str, Candidate] = {}
    for uri, address, port, local, relay in connections:
        if uri:
            candidates.setdefault(uri.rstrip("/"), Candidate(uri.rstrip("/"), local, relay))
        if not relay and address and port:
            host = f"[{address}]" if ":" in address else address
            plain = f"http://{host}:{port}"
            candidates.setdefault(plain, Candidate(plain, local, relay))
    return list(candidates.values())


def rank(probes: list[Probe]) -> list[Probe]:
    """Working first; then local before remote, HTTPS before HTTP, relay last, then fastest."""
    return sorted(
        probes,
        key=lambda p: (
            not p.ok,
            p.candidate.relay,
            not p.candidate.local,
            not p.candidate.secure,
            p.latency_ms if p.latency_ms is not None else float("inf"),
        ),
    )


# --- Probing ---------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    machine_id: str
    name: str
    version: str


async def probe(client: httpx.AsyncClient, uri: str, token: str, expected_id: str | None = None) -> Identity:
    """Ask a server who it is, with a token. Raises PlexError explaining what went wrong.

    Uses ``GET /`` rather than ``/identity``: /identity answers without checking the token,
    while ``/`` needs a valid one, and it's the same request Kometa makes when it connects.
    """
    try:
        response = await client.get(
            uri.rstrip("/") + "/",
            headers={"Accept": "application/json", "X-Plex-Token": token},
            timeout=PROBE_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        raise PlexError(f"No answer within {PROBE_TIMEOUT:g} s") from None
    except httpx.ConnectError as error:
        if isinstance(_root_cause(error), socket.gaierror):
            host = urlsplit(uri).hostname or uri
            hint = " Some routers block plex.direct names (DNS rebinding protection); try the plain IP address." if host.endswith(".plex.direct") else ""
            raise PlexError(f"Can't look up {host}.{hint}") from None
        raise PlexError(f"Can't connect: {_reason(error)}") from None
    except httpx.HTTPError as error:
        raise PlexError(f"Request failed: {_reason(error)}") from None

    if response.status_code == 401:
        raise TokenRejected("The server rejected the token")
    if response.status_code != 200:
        raise PlexError(f"The server answered HTTP {response.status_code}")
    try:
        container = response.json()["MediaContainer"]
        identity = Identity(
            machine_id=str(container["machineIdentifier"]),
            name=str(container.get("friendlyName") or "Plex Media Server"),
            version=str(container.get("version") or ""),
        )
    except (ValueError, KeyError, TypeError):
        raise PlexError("That address answered, but it isn't a Plex Media Server") from None
    if expected_id and identity.machine_id != expected_id:
        raise PlexError(f"A different Plex server answered ({identity.name})")
    return identity


async def probe_server(client: httpx.AsyncClient, server: Server) -> list[Probe]:
    """Probe every candidate in parallel and return them ranked."""

    async def one(candidate: Candidate) -> Probe:
        started = time.monotonic()
        try:
            await probe(client, candidate.uri, server.token, expected_id=server.id)
        except PlexError as error:
            return Probe(candidate, ok=False, error=str(error))
        return Probe(candidate, ok=True, latency_ms=round((time.monotonic() - started) * 1000))

    return rank(list(await asyncio.gather(*(one(c) for c in server.candidates))))


def normalise_url(url: str) -> str:
    """Check a typed server URL and strip what Plex doesn't need. Raises ValueError."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Enter the full address, starting with http:// or https://")
    if parts.query or parts.fragment:
        raise ValueError("Leave out anything after the address (no ?, # or token in the URL)")
    if parts.hostname == "plex.tv" or parts.hostname.endswith(".plex.tv"):
        raise ValueError("That's plex.tv, not your server. Use your server's own address")
    return url


# --- Helpers ---------------------------------------------------------------------


async def _plex_tv(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    client_id: str,
    *,
    token: str | None = None,
    params: dict[str, str] | None = None,
    accept: str = "application/json",
) -> httpx.Response:
    headers = client_headers(client_id, token) | {"Accept": accept}
    try:
        response = await client.request(method, PLEX_TV + path, headers=headers, params=params, timeout=15)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 401:
            raise TokenRejected("plex.tv rejected the sign-in. Sign in again.") from error
        raise PlexError(f"plex.tv answered HTTP {error.response.status_code}") from error
    except httpx.HTTPError as error:
        raise PlexError(f"Can't reach plex.tv: {_reason(error)}") from error
    return response


def _root_cause(error: BaseException) -> BaseException:
    while error.__cause__ is not None or error.__context__ is not None:
        error = error.__cause__ or error.__context__  # type: ignore[assignment]
    return error


def _reason(error: Exception) -> str:
    """The most useful line of an httpx error, e.g. a TLS failure."""
    return str(_root_cause(error)) or str(error) or type(error).__name__

