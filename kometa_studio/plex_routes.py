"""/api/v1/plex: the setup wizard's endpoints (handoff v2 §4).

The plex.tv account token stays on the server, encrypted in SQLite. The browser
only ever sees server IDs, URIs and masked tokens.
"""

import asyncio
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, model_validator
from ruamel.yaml.error import YAMLError

from . import plex
from .crypto import SecretBox
from .db import delete_setting, get_setting, set_setting
from .kometa_config import read_plex, write_plex
from .settings import Settings

CLIENT_ID = "plex.client_id"
ACCOUNT_TOKEN = "plex.account_token"
ACCOUNT_NAME = "plex.account_name"

router = APIRouter(prefix="/api/v1/plex", tags=["plex"])


# --- Dependencies ------------------------------------------------------------


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def get_box(request: Request) -> SecretBox:
    return request.app.state.secrets


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


Db = Annotated[sqlite3.Connection, Depends(get_db)]
Http = Annotated[httpx.AsyncClient, Depends(get_http)]
Box = Annotated[SecretBox, Depends(get_box)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def client_id(db: sqlite3.Connection) -> str:
    """Studio's X-Plex-Client-Identifier: generated once, so plex.tv lists Studio as one device."""
    value = get_setting(db, CLIENT_ID)
    if not value:
        value = str(uuid.uuid4())
        set_setting(db, CLIENT_ID, value)
    return value


def account_token(db: sqlite3.Connection, box: SecretBox) -> str | None:
    encrypted = get_setting(db, ACCOUNT_TOKEN)
    return box.decrypt(encrypted) if encrypted else None


def sign_out(db: sqlite3.Connection) -> None:
    delete_setting(db, ACCOUNT_TOKEN)
    delete_setting(db, ACCOUNT_NAME)


def mask(token: str | None) -> str | None:
    if not token:
        return None
    return "…" + token[-4:] if len(token) > 8 else "••••"


def config_path(settings: Settings) -> Path:
    if settings.kometa_config is None:
        raise HTTPException(409, "Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG.")
    return settings.kometa_config


# --- Current state -------------------------------------------------------------


def current_state(db: sqlite3.Connection, settings: Settings) -> dict:
    config: dict = {"path": str(settings.kometa_config) if settings.kometa_config else None, "url": None, "token": None, "error": None}
    if settings.kometa_config is not None:
        try:
            current = read_plex(settings.kometa_config)
            config |= {"url": current.url, "token": mask(current.token)}
        except (OSError, ValueError) as error:
            config["error"] = f"Can't read config.yml: {error}"
        except YAMLError as error:
            config["error"] = f"config.yml isn't valid YAML: {error}"
    name = get_setting(db, ACCOUNT_NAME)
    return {"config": config, "account": {"name": name} if get_setting(db, ACCOUNT_TOKEN) else None}


@router.get("")
async def get_plex(db: Db, settings: AppSettings) -> dict:
    return current_state(db, settings)


# --- Sign in ---------------------------------------------------------------------


@router.post("/pin")
async def start_sign_in(db: Db, http: Http) -> dict:
    cid = client_id(db)
    pin = await _plex_call(plex.create_pin(http, cid))
    return {"id": pin.id, "auth_url": plex.auth_url(cid, pin)}


@router.get("/pin/{pin_id}")
async def poll_sign_in(pin_id: int, db: Db, http: Http, box: Box) -> dict:
    cid = client_id(db)
    try:
        token = await _plex_call(plex.check_pin(http, cid, pin_id))
    except HTTPException as error:
        if error.status_code == 410:
            return {"status": "expired"}
        raise
    if token is None:
        return {"status": "waiting"}
    name = await _plex_call(plex.account_name(http, cid, token))
    set_setting(db, ACCOUNT_TOKEN, box.encrypt(token))
    set_setting(db, ACCOUNT_NAME, name)
    return {"status": "signed_in", "account": {"name": name}}


@router.delete("/account", status_code=204)
async def delete_account(db: Db) -> Response:
    sign_out(db)
    return Response(status_code=204)


# --- Servers ---------------------------------------------------------------------


def _probe_json(probe: plex.Probe) -> dict:
    c = probe.candidate
    return {
        "uri": c.uri,
        "local": c.local,
        "relay": c.relay,
        "secure": c.secure,
        "ok": probe.ok,
        "error": probe.error,
        "latency_ms": probe.latency_ms,
    }


async def _account_servers(db: sqlite3.Connection, http: httpx.AsyncClient, box: SecretBox) -> list[plex.Server]:
    token = account_token(db, box)
    if token is None:
        raise HTTPException(409, "Sign in with Plex first.")
    try:
        return await _plex_call(plex.fetch_servers(http, client_id(db), token))
    except HTTPException as error:
        if error.status_code == 401:
            sign_out(db)  # the token was revoked; make the user sign in again
        raise


@router.get("/servers")
async def list_servers(db: Db, http: Http, box: Box) -> dict:
    servers = await _account_servers(db, http, box)
    probed = await asyncio.gather(*(plex.probe_server(http, server) for server in servers))
    return {
        "servers": [
            {
                "id": server.id,
                "name": server.name,
                "version": server.version,
                "connections": [_probe_json(p) for p in probes],
                "best": next((p.candidate.uri for p in probes if p.ok), None),
            }
            for server, probes in zip(servers, probed, strict=True)
        ]
    }


# --- Test and connect ----------------------------------------------------------


class ManualServer(BaseModel):
    url: str
    token: str


class ConnectRequest(BaseModel):
    """Either a discovered server (server_id + uri) or a typed one (url + token)."""

    server_id: str | None = None
    uri: str | None = None
    url: str | None = None
    token: str | None = None

    @model_validator(mode="after")
    def one_kind(self) -> "ConnectRequest":
        discovered = self.server_id is not None and self.uri is not None
        manual = self.url is not None and self.token is not None
        if discovered == manual:
            raise ValueError("Send either server_id and uri, or url and token")
        return self


def _checked_url(url: str) -> str:
    try:
        return plex.normalise_url(url)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/test")
async def test_server(body: ManualServer, http: Http) -> dict:
    url = _checked_url(body.url)
    try:
        identity = await plex.probe(http, url, body.token.strip())
    except plex.PlexError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "name": identity.name, "version": identity.version, "url": url}


@router.post("/connect")
async def connect_server(body: ConnectRequest, db: Db, http: Http, box: Box, settings: AppSettings) -> dict:
    path = config_path(settings)
    if body.server_id is not None:
        servers = await _account_servers(db, http, box)
        server = next((s for s in servers if s.id == body.server_id), None)
        if server is None:
            raise HTTPException(404, "That server isn't on your Plex account any more. Refresh the list.")
        if body.uri not in {c.uri for c in server.candidates}:
            raise HTTPException(422, "That address isn't one of this server's connections.")
        url, token, expected = body.uri, server.token, server.id
    else:
        url, token, expected = _checked_url(body.url or ""), (body.token or "").strip(), None

    try:
        await plex.probe(http, url, token, expected_id=expected)
    except plex.PlexError as error:
        raise HTTPException(422, f"Studio couldn't connect with that address: {error}") from None

    try:
        write_plex(path, url, token, settings.data_dir / "backups")
    except OSError as error:
        raise HTTPException(500, f"Couldn't write {path}: {error}") from None
    except (ValueError, YAMLError) as error:
        raise HTTPException(409, f"Can't update config.yml: {error}") from None
    return current_state(db, settings)


async def _plex_call(awaitable):
    """Await a plex.* call, turning its errors into HTTP errors the frontend can show."""
    try:
        return await awaitable
    except plex.PinExpired as error:
        raise HTTPException(410, str(error)) from None
    except plex.TokenRejected as error:
        raise HTTPException(401, str(error)) from None
    except plex.PlexError as error:
        raise HTTPException(502, str(error)) from None
