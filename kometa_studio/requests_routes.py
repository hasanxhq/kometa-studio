"""/api/v1/requests: endpoints for missing media requests."""

import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import arr
from .arr import ArrProblem
from .plex_library import PlexNotFound
from .requesting import (
    Item,
    RequestOutcome,
    RequestService,
    RequestSettings,
    RequestsDisabled,
    SeerrConnectionIn,
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


@router.get("/settings")
async def get_settings(service: ServiceDep) -> dict:
    return {
        "settings": service.load_settings().model_dump(),
        "seerr": service.seerr_json(),
        "connected": service.connected(),
    }


@router.put("/settings")
async def put_settings(body: RequestSettings, service: ServiceDep) -> dict:
    service.save_settings(body)
    return {
        "settings": service.load_settings().model_dump(),
        "seerr": service.seerr_json(),
        "connected": service.connected(),
    }


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
async def put_seerr(body: SeerrConnectionIn, service: ServiceDep) -> dict:
    try:
        conn = service.seerr_from_input(body)
    except ArrProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    try:
        await service.test_seerr(conn)
    except ArrProblem as problem:
        raise HTTPException(422, f"Not saved: {problem}") from None
    service.save_seerr(conn)
    return {
        "settings": service.load_settings().model_dump(),
        "seerr": service.seerr_json(),
        "connected": service.connected(),
    }


@router.delete("/seerr")
async def delete_seerr(service: ServiceDep) -> dict:
    service.delete_seerr()
    return {
        "settings": service.load_settings().model_dump(),
        "seerr": service.seerr_json(),
        "connected": service.connected(),
    }


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
    now = datetime.now(UTC)
    counts = await service.refresh(now)
    server = service.plex_server()
    if server is not None:
        await service.label_imported(server, now)
    return counts


@router.post("/{row_id}/cancel")
async def cancel_request(row_id: int, service: ServiceDep) -> dict:
    try:
        return await service.cancel(row_id, datetime.now(UTC))
    except PlexNotFound:
        raise HTTPException(404, f"Request {row_id} not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
