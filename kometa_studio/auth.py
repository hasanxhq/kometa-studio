"""Sign-in and the API key, arr-style (handoff v2 §8).

Every /api path goes through ``AuthMiddleware``. A request is let in when it carries the API key
(``X-Api-Key`` header or ``apikey`` query parameter), a valid session cookie, or comes from a local
address while sign-in allows that. Until a username and password are set, only local addresses get
in, so a fresh install is never open to the internet. A request relayed by a proxy (it carries
``X-Forwarded-For`` or similar) never counts as local: the proxy itself is usually on the same host.

Changes from another site are refused whatever the credentials: a browser always sends ``Origin``
on a cross-site POST, and it must match the host Studio was reached at.
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .db import get_setting, set_setting

AUTH = "auth"  # {"username", "password" (scrypt hash), "required": "enabled" | "disabled_for_local"}
API_KEY = "auth.api_key"
COOKIE = "studio_session"
SESSION_DAYS = 30

# Paths that check their own token, are how one signs in, or say only "up" (the container's health check).
OPEN_PATHS = {"/api/v1/ping", "/api/v1/auth", "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/kometa/events", "/api/v1/hooks/arr"}
PROXY_HEADERS = (b"x-forwarded-for", b"forwarded", b"x-real-ip")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Logins: this many failures from one address within the window, and it has to wait.
MAX_FAILURES = 10
FAILURE_WINDOW = 15 * 60


# --- Passwords and keys ----------------------------------------------------------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), **_SCRYPT)
    return hmac.compare_digest(actual, base64.b64decode(digest))


def api_key(db: sqlite3.Connection) -> str:
    key = get_setting(db, API_KEY)
    if not key:
        key = new_api_key(db)
    return key


def new_api_key(db: sqlite3.Connection) -> str:
    key = secrets.token_hex(16)  # 32 hex characters, like the arr apps' keys
    set_setting(db, API_KEY, key)
    return key


def auth_settings(db: sqlite3.Connection) -> dict[str, Any] | None:
    """The sign-in settings, or None while no username and password are set."""
    value = get_setting(db, AUTH)
    return value if isinstance(value, dict) and value.get("password") else None


# --- Sessions --------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_session(db: sqlite3.Connection, username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with db:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (_utc(now),))
        db.execute(
            "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), username, _utc(now + timedelta(days=SESSION_DAYS))),
        )
    return token


def session_user(db: sqlite3.Connection, token: str | None) -> str | None:
    if not token:
        return None
    row = db.execute(
        "SELECT username FROM sessions WHERE token_hash = ? AND expires_at > ?", (_token_hash(token), _utc(datetime.now(UTC)))
    ).fetchone()
    return row["username"] if row else None


def end_session(db: sqlite3.Connection, token: str | None) -> None:
    if token:
        with db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def end_all_sessions(db: sqlite3.Connection, keep: str | None = None) -> None:
    with db:
        db.execute("DELETE FROM sessions WHERE token_hash != ?", (_token_hash(keep) if keep else "",))


# --- Who is asking ---------------------------------------------------------------


def is_local(client_host: str | None, proxied: bool) -> bool:
    """Loopback, private and link-local addresses, as the arr apps count them. Never through a proxy."""
    if proxied or not client_host:
        return False
    try:
        address = ipaddress.ip_address(client_host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_private or address.is_link_local


@dataclass
class Caller:
    """What one request brings, as AuthMiddleware sees it."""

    method: str
    path: str
    client_host: str | None
    headers: dict[bytes, bytes]
    query: dict[str, list[str]]
    scheme: str

    @classmethod
    def from_scope(cls, scope: dict) -> "Caller":
        client = scope.get("client")
        return cls(
            method=scope["method"],
            path=scope["path"],
            client_host=client[0] if client else None,
            headers={key.lower(): value for key, value in scope.get("headers", [])},
            query=parse_qs(scope.get("query_string", b"").decode("latin-1")),
            scheme=scope.get("scheme", "http"),
        )

    def header(self, name: bytes) -> str | None:
        value = self.headers.get(name)
        return value.decode("latin-1") if value is not None else None

    @property
    def local(self) -> bool:
        return is_local(self.client_host, any(name in self.headers for name in PROXY_HEADERS))

    @property
    def cookie(self) -> str | None:
        for part in (self.header(b"cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return value
        return None

    @property
    def secure(self) -> bool:
        return self.scheme == "https" or self.header(b"x-forwarded-proto") == "https"

    def cross_site(self) -> bool:
        """A change asked for by a page on another site (CSRF)."""
        if self.method in SAFE_METHODS:
            return False
        if self.header(b"sec-fetch-site") == "cross-site":
            return True
        origin = self.header(b"origin")
        if origin is None:
            return False  # not a browser: curl, Kometa, the arr apps
        host = self.header(b"x-forwarded-host") or self.header(b"host")
        return origin == "null" or urlsplit(origin).netloc != host


@dataclass
class Decision:
    allowed: bool
    status: int = 200
    reason: str = ""  # login, setup or cross_site
    message: str = ""
    via: str = ""  # api_key, session or local


def decide(db: sqlite3.Connection, caller: Caller, *, open_paths: bool = True) -> Decision:
    """Whether to let a request in. With ``open_paths=False``, as if it were for any other API path."""
    if caller.cross_site():
        return Decision(False, 403, "cross_site", "Studio doesn't take changes from other websites")
    if open_paths and caller.path in OPEN_PATHS:
        return Decision(True)
    key = caller.header(b"x-api-key") or (caller.query.get("apikey") or [None])[0]
    if key is not None:
        if hmac.compare_digest(key.encode(), api_key(db).encode()):
            return Decision(True, via="api_key")
        return Decision(False, 401, "login", "That API key isn't right")
    if session_user(db, caller.cookie):
        return Decision(True, via="session")
    settings = auth_settings(db)
    if settings is None:
        if caller.local:
            return Decision(True, via="local")
        return Decision(
            False,
            401,
            "setup",
            "Sign-in isn't set up yet, so Studio only answers this computer and your local network. "
            "Open Studio from there and set a username and password in Settings → General.",
        )
    if settings.get("required") == "disabled_for_local" and caller.local:
        return Decision(True, via="local")
    return Decision(False, 401, "login", "Sign in first")


class AuthMiddleware:
    """Guards every /api path. Plain ASGI, so server-sent event streams pass straight through."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        decision = decide(scope["app"].state.db, Caller.from_scope(scope))
        if decision.allowed:
            scope.setdefault("state", {})["auth_via"] = decision.via
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": {"message": decision.message, "reason": decision.reason}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": decision.status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


class LoginThrottle:
    """Failed logins per address, kept in memory: a restart forgets them, which is fine."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def _recent(self, address: str) -> list[float]:
        cutoff = time.monotonic() - FAILURE_WINDOW
        recent = [moment for moment in self._failures.get(address, []) if moment > cutoff]
        self._failures[address] = recent
        return recent

    def blocked(self, address: str) -> bool:
        return len(self._recent(address)) >= MAX_FAILURES

    def failed(self, address: str) -> None:
        self._recent(address).append(time.monotonic())

    def succeeded(self, address: str) -> None:
        self._failures.pop(address, None)
