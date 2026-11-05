"""Behind a reverse proxy (round 1.1): a URL base, and the proxies whose word Studio takes for who's visiting.

URL base: Studio answers under it (``/kometa/libraries``, ``/kometa/api/v1/…``) and without it, so a proxy
that strips the prefix and one that passes it on both work, and so do Kometa's webhooks, which call Studio
directly. ``UrlBaseMiddleware`` strips it before routing. The page gets a ``<base href>`` naming it, which
its assets, API calls and links follow; opening a page without the base redirects to it.

Trusted proxies: a request relayed by a proxy (it carries X-Forwarded-For or similar) never counts as local,
because the proxy is usually on the same host. A request from a trusted proxy is judged by the visitor's
address instead: the right-most address in X-Forwarded-For (or Forwarded, or X-Real-IP) that isn't a trusted
proxy itself. Earlier addresses are whatever the visitor sent, so they're never believed. Sign-in's "disabled
for local addresses" and its limit on failed sign-ins then see the real visitor.
"""

import ipaddress
import re
import sqlite3

from pydantic import BaseModel, Field, field_validator

from .db import get_setting

SETTING = "reverse_proxy"  # {"url_base": "/kometa", "trusted": ["172.18.0.0/16"]}
PROXY_HEADERS = (b"x-forwarded-for", b"forwarded", b"x-real-ip")
URL_BASE = re.compile(r"^(/[A-Za-z0-9._~-]+)*$")


def _entries(value: object) -> list[str]:
    parts = value if isinstance(value, list) else [value]
    found: list[str] = []
    for part in parts:
        for entry in re.split(r"[,\s]+", str(part or "")):
            if entry and entry not in found:
                found.append(entry)
    return found


class ReverseProxySettings(BaseModel):
    url_base: str = ""  # "" or "/kometa": a leading slash, no trailing one
    trusted: list[str] = Field(default_factory=list, max_length=50)  # addresses or networks (CIDR)

    @field_validator("url_base", mode="before")
    @classmethod
    def _url_base(cls, value: object) -> str:
        text = str(value or "").strip().strip("/")
        base = f"/{text}" if text else ""
        if not URL_BASE.match(base) or base.lower() in ("/api", "/assets") or base.lower().startswith(("/api/", "/assets/")):
            raise ValueError("A URL base is a path such as /kometa: letters, digits, dots, dashes and underscores")
        return base

    @field_validator("trusted", mode="before")
    @classmethod
    def _trusted(cls, value: object) -> list[str]:
        found = []
        for entry in _entries(value):
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                raise ValueError(f"{entry} isn't an address or a network such as 172.18.0.0/16") from None
            if network.prefixlen == 0:
                raise ValueError(f"{entry} would trust every address, so anyone could claim to be local")
            found.append(entry)
        return found


def load(db: sqlite3.Connection) -> ReverseProxySettings:
    try:
        return ReverseProxySettings.model_validate(get_setting(db, SETTING) or {})
    except ValueError:  # never let a bad stored value lock Studio
        return ReverseProxySettings()


def _address(text: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not text:
        return None
    text = text.strip().strip('"')
    if text.startswith("["):  # Forwarded: for="[2001:db8::1]:4711"
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:  # an IPv4 address with a port
        text = text.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address, trusted: list[str]) -> bool:
    return any(address in ipaddress.ip_network(entry, strict=False) for entry in trusted)


def _chain(headers: dict[bytes, bytes]) -> list[str] | None:
    """The addresses the proxies say the request came through, first (the visitor) to last; None if unreadable."""
    if b"x-forwarded-for" in headers:
        return [part.strip() for part in headers[b"x-forwarded-for"].decode("latin-1").split(",")]
    if b"forwarded" in headers:
        found = []
        for element in headers[b"forwarded"].decode("latin-1").split(","):
            pairs = dict(pair.strip().partition("=")[::2] for pair in element.split(";") if "=" in pair)
            found.append(pairs.get("for") or pairs.get("For") or "")
        return found
    if b"x-real-ip" in headers:
        return [headers[b"x-real-ip"].decode("latin-1").strip()]
    return None


def visitor(client_host: str | None, headers: dict[bytes, bytes], trusted: list[str]) -> tuple[str | None, bool]:
    """The visitor's address, and whether it came through a proxy Studio doesn't trust (so can't be judged local)."""
    if not any(name in headers for name in PROXY_HEADERS):
        return client_host, False
    peer = _address(client_host)
    if peer is None or not trusted or not _is_trusted(peer, trusted):
        return client_host, True
    chain = _chain(headers) or []
    addresses = [_address(entry) for entry in chain]
    for address in reversed(addresses):
        if address is None:
            return client_host, True  # an entry Studio can't read: don't guess
        if not _is_trusted(address, trusted):
            return str(address), False
    return (str(addresses[0]), False) if addresses else (client_host, True)


class UrlBaseMiddleware:
    """Strips the URL base from paths that have it. Paths without it are served as they are."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            base = load(scope["app"].state.db).url_base if getattr(scope["app"].state, "db", None) is not None else ""
            path = scope["path"]
            under = bool(base) and (path == base or path.startswith(base + "/"))
            if under:
                raw = scope.get("raw_path") or path.encode()
                raw = raw[len(base) :] if raw.startswith(base.encode()) else raw
                scope = dict(scope, path=path[len(base) :] or "/", raw_path=raw or b"/")
            scope.setdefault("state", {})
            scope["state"]["url_base"] = base
            scope["state"]["under_url_base"] = under
        await self.app(scope, receive, send)
