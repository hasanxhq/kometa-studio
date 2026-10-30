"""/api/v1/settings/network and /api/v1/network/check: Settings → Network (network.py).

The proxy and DNS over HTTPS follow the rest of Settings: a change is saved only after a passing
test, made again on the server when saving. IPv4 first is a plain switch.
"""

import sqlite3
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import doh, network
from .db import set_setting
from .runs_routes import get_db

router = APIRouter(prefix="/api/v1", tags=["network"])


class NetworkProblem(Exception):
    pass


Db = Annotated[sqlite3.Connection, Depends(get_db)]
SCHEMES = ("http", "https", "socks5", "socks5h")


def state(request: Request, db: sqlite3.Connection) -> dict:
    settings = network.load(db)
    return {
        "proxy_url": settings.proxy_url,
        "proxy_username": settings.proxy_username,
        "has_password": bool(settings.proxy_password),  # the password never leaves the server
        "no_proxy": settings.no_proxy,
        "doh_provider": settings.doh_provider,
        "doh_services": settings.doh_services,
        "prefer_ipv4": settings.prefer_ipv4,
        "local": network.LOCAL,
        "services": [{"id": key, "name": name, "domains": list(domains)} for key, (name, domains) in network.SERVICES.items()],
        "providers": [{"id": key, "name": name} for key, (name, _) in network.PROVIDERS.items()],
        "tmdb_quick_fix": doh.enabled(db, request.app.state.settings.kometa_config),
    }


def _save(db: sqlite3.Connection, **changes) -> None:
    set_setting(db, network.SETTING, network.load(db).model_copy(update=changes).model_dump())


@router.get("/settings/network")
async def get_network(request: Request, db: Db) -> dict:
    return state(request, db)


# --- The proxy -----------------------------------------------------------------------


class ProxyIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)  # None or empty: no proxy
    username: str | None = Field(default=None, max_length=200)  # empty: no login
    password: str | None = Field(default=None, max_length=500)  # None: keep the saved one
    no_proxy: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=100)


def _proxy(db: sqlite3.Connection, request: Request, body: ProxyIn) -> tuple[network.NetworkSettings, str | None]:
    """The settings as entered, and the proxy URL with its login."""
    url = (body.url or "").strip() or None
    if url:
        parts = urlsplit(url)
        if parts.scheme not in SCHEMES or not parts.hostname or not parts.port:
            raise HTTPException(422, "Enter the proxy as http://host:port, https://host:port or socks5://host:port")
    saved = network.load(db)
    username = (body.username or "").strip() or None
    box = request.app.state.secrets
    if not username:
        password = None
    elif body.password is not None:
        password = box.encrypt(body.password) if body.password else None
    else:
        password = saved.proxy_password
    entered = saved.model_copy(update={"proxy_url": url, "proxy_username": username, "proxy_password": password, "no_proxy": [e.strip() for e in body.no_proxy if e.strip()]})
    return entered, network.proxy_with_login(entered, box)


async def _test_proxy(proxy: str) -> str:
    try:
        return await network.test_proxy(proxy)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 407:
            raise NetworkProblem("The proxy wants a username and password" + (" (these were refused)" if "@" in proxy else "")) from None
        raise NetworkProblem(f"The proxy answered HTTP {error.response.status_code}") from None
    except (httpx.HTTPError, ValueError) as error:
        message = str(error) or type(error).__name__
        if "407" in message:
            message = "The proxy wants a username and password" + (" (these were refused)" if "@" in proxy else "")
        raise NetworkProblem(f"Couldn't get through the proxy: {message}") from None


@router.post("/settings/network/proxy/test")
async def test_proxy(body: ProxyIn, request: Request, db: Db) -> dict:
    _, proxy = _proxy(db, request, body)
    if proxy is None:
        return {"ok": False, "error": "Enter a proxy first"}
    try:
        return {"ok": True, "ip": await _test_proxy(proxy)}
    except NetworkProblem as problem:
        return {"ok": False, "error": str(problem)}


@router.put("/settings/network/proxy")
async def save_proxy(body: ProxyIn, request: Request, db: Db) -> dict:
    """Test the proxy again, then keep it. No URL: no proxy."""
    entered, proxy = _proxy(db, request, body)
    if proxy is not None:
        try:
            await _test_proxy(proxy)
        except NetworkProblem as problem:
            raise HTTPException(422, f"Not saved: {problem}") from None
    set_setting(db, network.SETTING, entered.model_dump())
    return state(request, db)


# --- DNS over HTTPS ------------------------------------------------------------------


class DohIn(BaseModel):
    provider: Literal["cloudflare", "google"] = "cloudflare"
    services: list[str] = Field(default_factory=list)


async def _test_doh(request: Request, body: DohIn) -> dict[str, str]:
    """One lookup per ticked service, through the chosen provider."""
    unknown = [name for name in body.services if name not in network.SERVICES]
    if unknown:
        raise HTTPException(422, f"Unknown services: {', '.join(unknown)}")
    url = network.PROVIDERS[body.provider][1]
    http = request.app.state.http
    found = {}
    for name in body.services:
        domain = network.SERVICES[name][1][0]
        host = "api.themoviedb.org" if name == "tmdb" else "api.mdblist.com" if name == "mdblist" else domain
        found[name] = await doh.resolve(http, host, url)
    return found


@router.post("/settings/network/doh/test")
async def test_doh(body: DohIn, request: Request) -> dict:
    try:
        return {"ok": True, "found": await _test_doh(request, body)}
    except doh.DohProblem as problem:
        return {"ok": False, "error": str(problem)}


@router.put("/settings/network/doh")
async def save_doh(body: DohIn, request: Request, db: Db) -> dict:
    try:
        await _test_doh(request, body)
    except doh.DohProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    _save(db, doh_provider=body.provider, doh_services=list(dict.fromkeys(body.services)))
    return state(request, db)


# --- IPv4 first ----------------------------------------------------------------------


class Ipv4In(BaseModel):
    prefer_ipv4: bool


@router.put("/settings/network/ipv4")
async def save_ipv4(body: Ipv4In, request: Request, db: Db) -> dict:
    _save(db, prefer_ipv4=body.prefer_ipv4)
    return state(request, db)


# --- The connection check --------------------------------------------------------------


@router.post("/network/check")
async def check(request: Request, db: Db) -> dict:
    return {"results": await network.check(request.app.state.http, db, request.app.state.settings.kometa_config)}
