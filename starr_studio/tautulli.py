"""Tautulli on Settings → Connect: Kometa's own connection, in config.yml's ``tautulli:`` (url, apikey).

Kometa uses it for the ``tautulli_popular`` and ``tautulli_watched`` builders. A connection is tested
with the call Kometa makes when it starts (``cmd=get_tautulli_info``), and saved only if that test
passes. Only the shared ``tautulli:`` block is managed here; a library's own ``tautulli:`` override
is left as written.
"""

from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .config_routes import Writer, _write_call
from .config_sections import read_section, save_section
from .services import mask
from .settings import Settings

router = APIRouter(prefix="/api/v1/settings/tautulli", tags=["tautulli"])

SECTION = "tautulli"
TIMEOUT = 10.0


class TautulliProblem(Exception):
    pass


def saved(config: Path | None) -> tuple[str | None, str | None]:
    section = read_section(config, SECTION) or {}
    url, key = section.get("url"), section.get("apikey")
    return (str(url) if url else None, str(key) if key else None)


def state(config: Path | None) -> dict:
    url, key = saved(config)
    return {"url": url, "apikey": mask(key)}  # the key itself never leaves the server


async def check(http: httpx.AsyncClient, url: str, apikey: str) -> dict:
    """Ask Tautulli for its version, as Kometa does when it starts."""
    try:
        response = await http.get(f"{url}/api/v2", params={"apikey": apikey, "cmd": "get_tautulli_info"}, timeout=TIMEOUT)
    except httpx.TimeoutException:
        raise TautulliProblem(f"Tautulli didn't answer within {TIMEOUT:g} s") from None
    except httpx.HTTPError as error:
        raise TautulliProblem(f"Can't reach Tautulli at {url}: {error}") from None
    try:
        answer = response.json()["response"]
    except (ValueError, KeyError, TypeError):
        raise TautulliProblem(f"Something answered at {url} (HTTP {response.status_code}), but not Tautulli's API") from None
    if answer.get("result") != "success":
        message = answer.get("message") or f"HTTP {response.status_code}"
        raise TautulliProblem("Tautulli rejected the API key" if "apikey" in str(message).lower() else f"Tautulli: {message}")
    version = (answer.get("data") or {}).get("tautulli_version")
    return {"version": str(version) if version else None}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


AppSettings = Annotated[Settings, Depends(_settings)]
Http = Annotated[httpx.AsyncClient, Depends(_http)]


class TautulliIn(BaseModel):
    url: str = Field(max_length=500)
    apikey: str | None = Field(default=None, max_length=200)  # None: the key already in config.yml

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        value = value.strip().rstrip("/")  # Kometa strips the trailing slash too
        if not value.startswith(("http://", "https://")):
            raise ValueError("Enter Tautulli's address, starting with http:// or https://")
        return value


def _connection(settings: Settings, body: TautulliIn) -> tuple[str, str]:
    key = (body.apikey or "").strip() or saved(settings.kometa_config)[1]
    if not key:
        raise HTTPException(422, "Enter Tautulli's API key")
    return body.url, key


@router.get("")
async def get_tautulli(settings: AppSettings) -> dict:
    return state(settings.kometa_config)


@router.post("/test")
async def test_tautulli(body: TautulliIn, settings: AppSettings, http: Http) -> dict:
    try:
        return {"ok": True} | await check(http, *_connection(settings, body))
    except TautulliProblem as problem:
        return {"ok": False, "error": str(problem)}


@router.put("")
async def save_tautulli(body: TautulliIn, settings: AppSettings, http: Http, writer: Writer) -> dict:
    """Test again, then write url and apikey to config.yml. A connection that fails its test is never saved."""
    url, key = _connection(settings, body)
    try:
        await check(http, url, key)
    except TautulliProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    if (url, key) != saved(settings.kometa_config):
        await _write_call(save_section(writer, SECTION, {"url": url, "apikey": key}, "Connected Tautulli in Settings → Connect"))
    return state(settings.kometa_config)


@router.delete("")
async def remove_tautulli(settings: AppSettings, writer: Writer) -> dict:
    if saved(settings.kometa_config) != (None, None):
        await _write_call(save_section(writer, SECTION, None, "Removed Tautulli in Settings → Connect"))
    return state(settings.kometa_config)
