"""/api/v1/settings/maintainerr: Maintainerr on Settings → Connect."""

import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import maintainerr
from .db import set_setting
from .maintainerr import Maintainerr, MaintainerrProblem
from .runs_routes import get_db

router = APIRouter(prefix="/api/v1/settings/maintainerr", tags=["maintainerr"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def get_service(request: Request) -> Maintainerr:
    return request.app.state.maintainerr


Service = Annotated[Maintainerr, Depends(get_service)]


def state(db: sqlite3.Connection, service: Maintainerr) -> dict:
    settings = maintainerr.load(db)
    snapshot = service.snapshot
    return {
        "url": settings.url,
        "username": settings.username,
        "has_password": bool(settings.password),  # the password itself never leaves the server
        "leave_overlays_alone": settings.leave_overlays_alone,
        "collections": [
            {"title": c.title, "library": snapshot.library_titles.get(c.library_key), "overlays": c.overlays and c.active}
            for c in sorted(snapshot.collections, key=lambda c: c.title.casefold())
        ],
        "overlays_enabled": snapshot.overlays_enabled,
        "error": snapshot.error,
        "checked_seconds_ago": round(time.monotonic() - snapshot.at) if snapshot.at else None,
        "risks": [risk.message for risk in service.risks()],
    }


@router.get("")
async def get_maintainerr(db: Db, service: Service) -> dict:
    return state(db, service)


class MaintainerrIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)  # empty: disconnect
    username: str | None = Field(default=None, max_length=200)  # for a proxy in front of it; empty: none
    password: str | None = Field(default=None, max_length=500)  # None: keep the saved one
    leave_overlays_alone: bool = True


def _password(db: sqlite3.Connection, service: Maintainerr, username: str | None, password: str | None) -> str | None:
    """The encrypted password to keep: a new one, the saved one, or none without a username."""
    if not username:
        return None
    if password is None:
        return maintainerr.load(db).password
    return service.box.encrypt(password) if password else None


@router.put("")
async def put_maintainerr(body: MaintainerrIn, db: Db, service: Service) -> dict:
    url = (body.url or "").strip() or None
    username = (body.username or "").strip() or None if url else None
    set_setting(
        db,
        maintainerr.SETTINGS,
        {"url": url, "username": username, "password": _password(db, service, username, body.password), "leave_overlays_alone": body.leave_overlays_alone},
    )
    await service.refresh()
    return state(db, service)


class TestIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    username: str | None = None
    password: str | None = None  # None: the saved one


@router.post("/test")
async def test_maintainerr(body: TestIn, db: Db, service: Service) -> dict:
    """Test the connection as entered (not saved yet)."""
    username = (body.username or "").strip() or None
    auth = None
    if username:
        saved = maintainerr.load(db)
        password = body.password if body.password is not None else (service.box.decrypt(saved.password) or "" if saved.password else "")
        auth = (username, password)
    try:
        return {"ok": True} | await service.test(body.url.strip(), auth)
    except MaintainerrProblem as problem:
        return {"ok": False, "error": str(problem)}
    except Exception as error:  # an address that isn't a URL, say
        raise HTTPException(422, f"Can't use that address: {error}") from None
