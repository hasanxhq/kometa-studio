"""/api/v1/settings/arr: Radarr and Sonarr on Settings → Connect."""

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import arr
from .arr import Arr, ArrProblem, ArrSettings, Connection, Kind
from .db import get_setting, set_setting
from .runs_routes import get_db

router = APIRouter(prefix="/api/v1/settings/arr", tags=["arr"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def get_arr(request: Request) -> Arr:
    return request.app.state.arr


ArrDep = Annotated[Arr, Depends(get_arr)]


def _connection_json(db: sqlite3.Connection, service: Arr, kind: Kind) -> dict:
    saved = (get_setting(db, arr.CONNECTIONS) or {}).get(kind) or {}
    config_url, config_token = arr.kometa_connection(service.config, kind)
    return {
        "source": saved.get("source", "config"),
        "url": saved.get("url"),
        "has_key": bool(saved.get("api_key")),  # the key itself never leaves the server
        "config_url": config_url if config_token else None,
        "status": get_setting(db, f"arr.status.{kind}"),
    }


def state(db: sqlite3.Connection, service: Arr) -> dict:
    return {
        "settings": arr.load_settings(db).model_dump(),
        "connections": {kind: _connection_json(db, service, kind) for kind in arr.KINDS},
        "pending": service.pending(),
    }


@router.get("")
async def get_arr_settings(db: Db, service: ArrDep) -> dict:
    return state(db, service)


@router.put("")
async def put_arr_settings(body: ArrSettings, db: Db, service: ArrDep) -> dict:
    set_setting(db, arr.RUNS, body.model_dump())
    return state(db, service)


class ConnectionIn(BaseModel):
    source: Literal["config", "studio", "off"]
    url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=200)  # None: keep the saved one


def _kind(kind: str) -> Kind:
    if kind not in arr.KINDS:
        raise HTTPException(404, "Radarr or Sonarr only")
    return kind  # type: ignore[return-value]


def _studio_connection(db: sqlite3.Connection, service: Arr, kind: Kind, body: ConnectionIn) -> Connection:
    saved = (get_setting(db, arr.CONNECTIONS) or {}).get(kind) or {}
    key = body.api_key or (service.box.decrypt(saved["api_key"]) if saved.get("api_key") else None)
    if not body.url or not key:
        raise HTTPException(422, f"Enter {arr.NAMES[kind]}'s URL and API key")
    return Connection(body.url.strip(), key.strip(), "studio")


@router.put("/{kind}")
async def put_connection(kind: str, body: ConnectionIn, db: Db, service: ArrDep) -> dict:
    which = _kind(kind)
    connections = get_setting(db, arr.CONNECTIONS) or {}
    saved = connections.get(which) or {}
    entry: dict = {"source": body.source}
    if body.source == "studio":
        conn = _studio_connection(db, service, which, body)
        entry |= {"url": conn.url, "api_key": service.box.encrypt(conn.api_key)}
    elif saved.get("url"):  # keep what was entered, for switching back
        entry |= {"url": saved["url"], "api_key": saved.get("api_key")}
    connections[which] = entry
    set_setting(db, arr.CONNECTIONS, connections)
    service.reset_cursor(which)
    return state(db, service)


@router.post("/{kind}/test")
async def test(kind: str, body: ConnectionIn, db: Db, service: ArrDep) -> dict:
    """Test the connection as entered (not saved yet), the way the arr apps' own Test buttons do."""
    which = _kind(kind)
    if body.source == "studio":
        conn = _studio_connection(db, service, which, body)
    elif body.source == "config":
        url, token = arr.kometa_connection(service.config, which)
        if not url or not token:
            return {"ok": False, "error": f"config.yml has no {which}: url and token"}
        conn = Connection(url, token, "config")
    else:
        return {"ok": False, "error": "Switched off"}
    try:
        return {"ok": True} | await arr.test_connection(service.http, conn, which)
    except ArrProblem as problem:
        return {"ok": False, "error": str(problem)}
