"""/api/v1/auth and /api/v1/settings/general: signing in, and Settings → General (handoff v2 §8)."""

import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from . import auth, reverse_proxy
from .auth import Caller
from .db import set_setting
from .scheduler import utc_text
from .settings import Settings

TIMEZONE = "general.timezone"

router = APIRouter(prefix="/api/v1", tags=["auth"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def _caller(request: Request) -> Caller:
    return Caller.from_scope(request.scope, reverse_proxy.load(request.app.state.db).trusted)


@router.get("/auth")
async def auth_status(request: Request, db: Db) -> dict:
    """What the browser needs to decide between the app, the login page and the "set up sign-in" notice."""
    caller = _caller(request)
    decision = auth.decide(db, caller, open_paths=False)
    configured = auth.auth_settings(db) is not None
    return {
        "allowed": decision.allowed,
        "reason": decision.reason or None,
        "message": decision.message or None,
        "configured": configured,
        "signed_in": decision.via == "session",
        "local": caller.local,
    }


class Login(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(body: Login, request: Request, response: Response, db: Db) -> dict:
    throttle: auth.LoginThrottle = request.app.state.login_throttle
    caller = _caller(request)
    address = caller.address or "?"
    if throttle.blocked(address):
        raise HTTPException(429, "Too many failed sign-ins. Wait a few minutes and try again.")
    settings = auth.auth_settings(db)
    if settings is None:
        raise HTTPException(409, "Sign-in isn't set up yet")
    # Check the password even for a wrong username, so the answer takes as long either way.
    password_ok = auth.check_password(body.password, settings["password"])
    if not password_ok or body.username != settings.get("username"):
        throttle.failed(address)
        raise HTTPException(401, "That username and password don't match")
    throttle.succeeded(address)
    token = auth.create_session(db, body.username)
    response.set_cookie(
        auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="strict", secure=caller.secure, path="/"
    )
    return {"ok": True}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: Db) -> dict:
    auth.end_session(db, _caller(request).cookie)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


# --- Settings → General ---------------------------------------------------------------


def general(request: Request, db: sqlite3.Connection) -> dict:
    settings: Settings = request.app.state.settings
    current = auth.auth_settings(db)
    return {
        "auth": {
            "configured": current is not None,
            "username": current.get("username") if current else None,
            "required": current.get("required", "enabled") if current else "disabled_for_local",
        },
        "api_key": auth.api_key(db),
        "timezone": request.app.state.timezone,
        "host": settings.host,
        "port": settings.port,
        "reverse_proxy": reverse_proxy.load(db).model_dump(),
        "you": _you(_caller(request)),
    }


def _you(caller: Caller) -> dict:
    """How Studio sees the request that's asking: who the visitor is, and whether that counts as local."""
    address, untrusted = reverse_proxy.visitor(caller.client_host, caller.headers, caller.trusted)
    proxied = any(name in caller.headers for name in reverse_proxy.PROXY_HEADERS)
    return {"address": address, "peer": caller.client_host, "proxied": proxied, "trusted_proxy": proxied and not untrusted, "local": caller.local}


@router.get("/settings/general")
async def get_general(request: Request, db: Db) -> dict:
    return general(request, db)


class AuthIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str | None = Field(default=None, max_length=1000)  # None: keep the current one
    required: Literal["enabled", "disabled_for_local"] = "enabled"
    current_password: str | None = None

    @field_validator("username")
    @classmethod
    def strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username can't be empty")
        return value


@router.put("/settings/auth")
async def put_auth(body: AuthIn, request: Request, response: Response, db: Db) -> dict:
    current = auth.auth_settings(db)
    if current is not None and not auth.check_password(body.current_password or "", current["password"]):
        raise HTTPException(403, "Enter your current password to change sign-in")
    if current is None and not body.password:
        raise HTTPException(422, "Choose a password")
    if body.password is not None and len(body.password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters")
    password = auth.hash_password(body.password) if body.password else current["password"]
    set_setting(db, auth.AUTH, {"username": body.username, "password": password, "required": body.required})

    caller = _caller(request)
    if current is None or body.password or body.username != current.get("username"):
        # New credentials: sign every other browser out, and keep this one signed in.
        auth.end_all_sessions(db, keep=caller.cookie)
        if auth.session_user(db, caller.cookie) is None:
            token = auth.create_session(db, body.username)
            response.set_cookie(
                auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="strict", secure=caller.secure, path="/"
            )
    return general(request, db)


@router.post("/settings/api-key")
async def regenerate_api_key(request: Request, db: Db) -> dict:
    auth.new_api_key(db)
    return general(request, db)


class TimezoneIn(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def known(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown timezone: {value}") from None
        return value


class ReverseProxyIn(BaseModel):
    url_base: str = Field(default="", max_length=100)
    trusted: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=50)


@router.put("/settings/reverse-proxy")
async def put_reverse_proxy(body: ReverseProxyIn, request: Request, db: Db) -> dict:
    """The URL base and trusted proxies. Takes effect with the next request; Studio still answers without the base."""
    try:
        settings = reverse_proxy.ReverseProxySettings.model_validate(body.model_dump())
    except ValueError as error:
        raise HTTPException(422, _first_error(error)) from None
    set_setting(db, reverse_proxy.SETTING, settings.model_dump())
    return general(request, db)


def _first_error(error: ValueError) -> str:
    errors = getattr(error, "errors", None)
    if callable(errors):
        return str(errors()[0]["msg"]).removeprefix("Value error, ")
    return str(error)


@router.put("/settings/timezone")
async def put_timezone(body: TimezoneIn, request: Request, db: Db) -> dict:
    set_setting(db, TIMEZONE, body.timezone)
    request.app.state.timezone = body.timezone
    # Schedules and Studio's tasks share this setting; rewriting them avoids a stale per-row zone.
    now = utc_text(datetime.now(UTC))
    with db:
        db.execute("UPDATE schedules SET timezone = ?, last_fired_at = ?", (body.timezone, now))
        db.execute("UPDATE tasks SET timezone = ?, last_fired_at = ?", (body.timezone, now))
    return general(request, db)
