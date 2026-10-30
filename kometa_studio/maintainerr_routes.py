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
        "has_key": bool(settings.api_key),  # the key itself never leaves the server
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
    api_key: str | None = Field(default=None, max_length=200)  # None: keep the saved one; "": remove it
    leave_overlays_alone: bool = True


@router.put("")
async def put_maintainerr(body: MaintainerrIn, db: Db, service: Service) -> dict:
    current = maintainerr.load(db)
    url = (body.url or "").strip() or None
    if body.api_key is None:
        key = current.api_key if url else None
    else:
        key = service.box.encrypt(body.api_key.strip()) if body.api_key.strip() else None
    set_setting(db, maintainerr.SETTINGS, {"url": url, "api_key": key, "leave_overlays_alone": body.leave_overlays_alone})
    await service.refresh()
    return state(db, service)


class TestIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    api_key: str | None = None  # None: the saved one


@router.post("/test")
async def test_maintainerr(body: TestIn, db: Db, service: Service) -> dict:
    saved = maintainerr.load(db)
    key = body.api_key if body.api_key is not None else (service.box.decrypt(saved.api_key) if saved.api_key else None)
    try:
        return {"ok": True} | await service.test(body.url.strip(), key or None)
    except MaintainerrProblem as problem:
        return {"ok": False, "error": str(problem)}
    except Exception as error:  # an address that isn't a URL, say
        raise HTTPException(422, f"Can't use that address: {error}") from None
