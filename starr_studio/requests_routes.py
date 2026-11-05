"""/api/v1/requests: endpoints for missing media requests.

Seerr's url and API key are Kometa's, in config.yml's ``seerr:``; a save writes them there through the
normal save flow (Kometa's check, backup, formatting kept). A proxy login is Studio's own. Nothing is
saved without a passing test, made again on the server when saving.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import arr
from .arr import ArrProblem
from .config_routes import Writer, _write_call
from .config_sections import read_document, save_section
from .db import delete_setting
from .plex_library import PlexNotFound
from .requesting import (
    REQUESTS_SEERR,
    SEERR_LOGIN,
    Item,
    RequestOutcome,
    RequestService,
    RequestSettings,
    RequestsDisabled,
    SeerrConnectionIn,
    save_seerr_login,
)
from .runs_routes import get_db

router = APIRouter(prefix="/api/v1/requests", tags=["requests"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def get_service(request: Request) -> RequestService:
    return request.app.state.requests


ServiceDep = Annotated[RequestService, Depends(get_service)]


class CreateRequestBody(BaseModel):
    library: str
    collection_id: int | None = None
    items: list[Item]
    cap: int | None = None


def _state(service: RequestService) -> dict:
    return {
        "settings": service.load_settings().model_dump(),
        "seerr": service.seerr_json(),
        "connected": service.connected(),
    }


@router.get("/settings")
async def get_settings(service: ServiceDep) -> dict:
    return _state(service)


@router.put("/settings")
async def put_settings(body: RequestSettings, service: ServiceDep) -> dict:
    service.save_settings(body)
    return _state(service)


@router.get("/options")
async def get_options(service: ServiceDep) -> dict:
    radarr_conn = arr.connection(service.db, service.box, service.config, "radarr")
    sonarr_conn = arr.connection(service.db, service.box, service.config, "sonarr")
    errors = {}

    radarr_opts = None
    if radarr_conn is not None:
        try:
            info = await arr.test_connection(service.http, radarr_conn, "radarr")
            radarr_opts = {
                "quality_profiles": info["quality_profiles"],
                "root_folders": info["root_folders"],
            }
        except ArrProblem as problem:
            errors["radarr"] = str(problem)

    sonarr_opts = None
    if sonarr_conn is not None:
        try:
            info = await arr.test_connection(service.http, sonarr_conn, "sonarr")
            sonarr_opts = {
                "quality_profiles": info["quality_profiles"],
                "root_folders": info["root_folders"],
            }
        except ArrProblem as problem:
            errors["sonarr"] = str(problem)

    return {
        "radarr": radarr_opts,
        "sonarr": sonarr_opts,
        "errors": errors,
    }


@router.post("/seerr/test")
async def test_seerr(body: SeerrConnectionIn, service: ServiceDep) -> dict:
    try:
        conn = service.seerr_from_input(body)
    except ArrProblem as problem:
        return {"ok": False, "error": str(problem)}
    try:
        return {"ok": True} | await service.test_seerr(conn)
    except ArrProblem as problem:
        return {"ok": False, "error": str(problem)}


@router.put("/seerr")
async def put_seerr(body: SeerrConnectionIn, service: ServiceDep, writer: Writer) -> dict:
    """Test again, then write url and apikey to config.yml's seerr: and keep the proxy login."""
    try:
        conn = service.seerr_from_input(body)
    except ArrProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    if not writer.config_path.is_file():
        raise HTTPException(409, "Not saved: Kometa's config.yml doesn't exist yet. Connect Plex first.")
    try:
        await service.test_seerr(conn)
    except ArrProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    await _write_call(save_section(writer, "seerr", {"url": conn.url, "apikey": conn.api_key}, "Connected Seerr in Settings → Requests"))
    save_seerr_login(service.db, service.box, conn.login)
    delete_setting(service.db, REQUESTS_SEERR)  # config.yml holds it now
    return _state(service)


@router.delete("/seerr")
async def delete_seerr(service: ServiceDep, writer: Writer) -> dict:
    """Remove config.yml's seerr: (Kometa stops using it too) and Studio's proxy login."""
    if "seerr" in (read_document(service.config) or {}):
        await _write_call(save_section(writer, "seerr", None, "Removed Seerr in Settings → Requests"))
    delete_setting(service.db, SEERR_LOGIN)
    delete_setting(service.db, REQUESTS_SEERR)
    return _state(service)


@router.get("")
@router.get("/")
async def list_requests(
    service: ServiceDep,
    status: str | None = None,
    collection_id: int | None = None,
    limit: int = 200,
) -> dict:
    query = "SELECT * FROM requests"
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if collection_id is not None:
        clauses.append("collection_id = ?")
        params.append(collection_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY requested_at DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = service.db.execute(query, params).fetchall()
    return {
        "requests": [dict(r) for r in rows],
        "counts": service.counts(),
    }


@router.post("")
@router.post("/")
async def create_requests(body: CreateRequestBody, service: ServiceDep) -> RequestOutcome:
    try:
        return await service.request(
            items=body.items,
            library=body.library,
            collection_id=body.collection_id,
            now=datetime.now(UTC),
            cap=body.cap,
        )
    except RequestsDisabled as e:
        raise HTTPException(409, str(e)) from None


@router.post("/refresh")
async def refresh_requests(service: ServiceDep) -> dict[str, int]:
    return await service.check(datetime.now(UTC))


@router.post("/{row_id}/cancel")
async def cancel_request(row_id: int, service: ServiceDep) -> dict:
    try:
        return await service.cancel(row_id, datetime.now(UTC))
    except PlexNotFound:
        raise HTTPException(404, f"Request {row_id} not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
