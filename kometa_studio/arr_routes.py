"""/api/v1/hooks/arr (Radarr and Sonarr's webhook) and /api/v1/settings/arr (Settings → Connect)."""

import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from . import arr_hooks
from .arr_hooks import ArrHooks, ArrSettings
from .db import get_setting, set_setting
from .runs_routes import get_db

router = APIRouter(prefix="/api/v1", tags=["arr"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def get_arr(request: Request) -> ArrHooks:
    return request.app.state.arr


Arr = Annotated[ArrHooks, Depends(get_arr)]


@router.post("/hooks/arr")
async def arr_webhook(request: Request, db: Db, arr: Arr, token: str = "") -> dict:
    """Radarr and Sonarr post here (Settings → Connect → Webhook in each). Checks its own token, not sign-in."""
    if not secrets.compare_digest(token, arr_hooks.token(db)):
        raise HTTPException(403, "Wrong token")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Expected a JSON body") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "Expected a JSON object")
    return arr.receive(payload, datetime.now(UTC))


def settings_json(db: sqlite3.Connection, arr: ArrHooks) -> dict:
    return {
        "settings": arr_hooks.load_settings(db).model_dump(),
        "path": f"/api/v1/hooks/arr?token={arr_hooks.token(db)}",
        "last_event": get_setting(db, arr_hooks.LAST_EVENT),
        "pending": arr.pending(),
    }


@router.get("/settings/arr")
async def get_arr_settings(db: Db, arr: Arr) -> dict:
    return settings_json(db, arr)


@router.put("/settings/arr")
async def put_arr_settings(body: ArrSettings, db: Db, arr: Arr) -> dict:
    set_setting(db, arr_hooks.SETTINGS, body.model_dump())
    return settings_json(db, arr)


@router.post("/settings/arr/token")
async def new_arr_token(db: Db, arr: Arr) -> dict:
    arr_hooks.new_token(db)
    return settings_json(db, arr)
