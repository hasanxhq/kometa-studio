"""TMDb and MDBList on Settings → Connect: Kometa's own keys, in config.yml's ``tmdb:`` and ``mdblist:``.

TMDb can be looked up over DNS over HTTPS instead of the system's DNS (doh.py), for that key's
calls by Studio and Kometa alike.

A key is tested with the same small call Kometa makes when it starts (TMDb's ``/configuration``,
MDBList's ``/user``), and saved only if that test passes. MDBList's answer also says how many
requests the key may make a day and how many it has made today, which Studio uses to keep runs
after imports from using up the daily allowance.
"""

import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import doh
from .config_routes import Writer, _write_call
from .config_sections import read_section, save_section
from .settings import Settings

router = APIRouter(prefix="/api/v1/settings/services", tags=["services"])

Service = Literal["tmdb", "mdblist"]
NAMES = {"tmdb": "TMDb", "mdblist": "MDBList"}
TMDB_URL = "https://api.themoviedb.org/3/configuration"
MDBLIST_URL = "https://api.mdblist.com/user"
TIMEOUT = 10.0


class ServiceProblem(Exception):
    pass


def mask(secret: str | None) -> str | None:
    return f"…{secret[-4:]}" if secret else None


def saved_key(config: Path | None, service: Service) -> str | None:
    section = read_section(config, service) or {}
    key = section.get("apikey")
    return str(key) if key else None


async def check_key(http: httpx.AsyncClient, service: Service, apikey: str, bypass_dns: bool = False) -> dict:
    """Test a key the way Kometa does when it starts. MDBList also says the key's daily allowance and use.

    ``bypass_dns`` (TMDb only) looks TMDb up over DNS over HTTPS first (see doh.py).
    """
    url, params = (TMDB_URL, {"api_key": apikey}) if service == "tmdb" else (MDBLIST_URL, {"apikey": apikey})
    try:
        if bypass_dns and service == "tmdb":
            response = await doh.get(http, url, params=params, timeout=TIMEOUT)
        else:
            response = await http.get(url, params=params, timeout=TIMEOUT)
    except doh.DohProblem as problem:
        raise ServiceProblem(str(problem)) from None
    except httpx.TimeoutException:
        raise ServiceProblem(f"{NAMES[service]} didn't answer within {TIMEOUT:g} s") from None
    except httpx.HTTPError as error:
        raise ServiceProblem(f"Can't reach {NAMES[service]}: {error}") from None
    if response.status_code in (401, 403):
        raise ServiceProblem(f"{NAMES[service]} rejected the API key")
    if response.status_code != 200:
        raise ServiceProblem(f"{NAMES[service]} answered HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise ServiceProblem(f"{NAMES[service]} answered, but not with JSON") from None
    if service == "tmdb":
        return {}
    if not isinstance(data, dict) or data.get("error"):
        raise ServiceProblem(f"MDBList: {data.get('error') if isinstance(data, dict) else 'unexpected answer'}")
    return {"limit": data.get("api_requests"), "used": data.get("api_requests_count")}


async def mdblist_usage(http: httpx.AsyncClient, config: Path | None) -> dict | None:
    """Today's use of the MDBList key in config.yml ({limit, used}), or None if there's no key or MDBList didn't say."""
    key = saved_key(config, "mdblist")
    if key is None:
        return None
    try:
        usage = await check_key(http, "mdblist", key)
    except ServiceProblem:
        return None
    return usage if isinstance(usage.get("limit"), int) and isinstance(usage.get("used"), int) else None


# --- Routes ------------------------------------------------------------------------


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


AppSettings = Annotated[Settings, Depends(_settings)]
Http = Annotated[httpx.AsyncClient, Depends(_http)]


def _service(name: str) -> Service:
    if name not in NAMES:
        raise HTTPException(404, "TMDb or MDBList only")
    return name  # type: ignore[return-value]


def state(db: sqlite3.Connection, config: Path | None) -> dict:
    found = {name: {"apikey": mask(saved_key(config, name))} for name in NAMES}  # the key itself never leaves the server
    found["tmdb"]["bypass_dns"] = doh.enabled(db, config)
    return found


@router.get("")
async def get_services(request: Request, settings: AppSettings) -> dict:
    return state(request.app.state.db, settings.kometa_config)


class KeyIn(BaseModel):
    apikey: str | None = Field(default=None, max_length=200)  # None: the key already in config.yml
    bypass_dns: bool = False  # TMDb only: look TMDb up over DNS over HTTPS (doh.py), and keep doing so for this key


def _key(settings: Settings, service: Service, body: KeyIn) -> str:
    key = (body.apikey or "").strip() or saved_key(settings.kometa_config, service)
    if not key:
        raise HTTPException(422, f"Enter {NAMES[service]}'s API key")
    return key


@router.post("/{name}/test")
async def test_service(name: str, body: KeyIn, settings: AppSettings, http: Http) -> dict:
    service = _service(name)
    try:
        return {"ok": True} | await check_key(http, service, _key(settings, service, body), body.bypass_dns)
    except ServiceProblem as problem:
        return {"ok": False, "error": str(problem)}


@router.put("/{name}")
async def save_service(name: str, body: KeyIn, request: Request, settings: AppSettings, http: Http, writer: Writer) -> dict:
    """Test the key again, then write it to config.yml. A key that fails its test is never saved."""
    service = _service(name)
    key = _key(settings, service, body)
    try:
        await check_key(http, service, key, body.bypass_dns)
    except ServiceProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    if key != saved_key(settings.kometa_config, service):
        await _write_call(save_section(writer, service, {"apikey": key}, f"Connected {NAMES[service]} in Settings → Connect"))
    if service == "tmdb":
        doh.remember(request.app.state.db, key, body.bypass_dns)
    return state(request.app.state.db, settings.kometa_config)


@router.delete("/{name}")
async def remove_service(name: str, request: Request, settings: AppSettings, writer: Writer) -> dict:
    service = _service(name)
    if service == "tmdb":
        raise HTTPException(409, "Kometa needs a TMDb key to run, so it can't be removed")
    await _write_call(save_section(writer, service, None, f"Removed {NAMES[service]} in Settings → Connect"))
    return state(request.app.state.db, settings.kometa_config)
