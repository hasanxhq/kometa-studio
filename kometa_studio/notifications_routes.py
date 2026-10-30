"""/api/v1/settings/notifications: Kometa's notification services and webhook events on Settings → Notifications.

A service is saved only if its test passes: the browser keeps Save off until Test passes for the
values as they are, and the save route runs the same test again itself. Every change goes through
ConfigWriter (Kometa's check, backup, comments kept). Secrets never reach the browser.
"""

from pathlib import Path
from typing import Annotated

import httpx

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import notifications
from .config_routes import Writer
from .config_write import ConfigWriter, Edit, SaveRefused, file_hash
from .notifications import NotificationProblem
from .plex_routes import Http

router = APIRouter(prefix="/api/v1/settings/notifications", tags=["notifications"])

Value = Annotated[str, Field(max_length=2000)]


def _current(writer: ConfigWriter) -> tuple[str | None, str | None]:
    """config.yml's text and hash, or None for both if it doesn't exist yet."""
    path = writer.config_path
    if not path.is_file():
        return None, None
    data = path.read_bytes()
    return data.decode("utf-8"), file_hash(data)


def _refuse(status: int, message: str) -> HTTPException:
    # Shaped like a refused save, so the page shows it the same way.
    return HTTPException(status, {"message": message, "path": None, "validation": None})


def state(writer: ConfigWriter) -> dict:
    try:
        text, hash_ = _current(writer)
        return {"path": str(writer.config_path), "hash": hash_, "error": None} | notifications.read_state(text)
    except (ValueError, UnicodeDecodeError) as error:
        empty = notifications.read_state(None)
        return {"path": str(writer.config_path), "hash": None, "error": f"Can't read config.yml: {error}"} | empty


async def _save(writer: ConfigWriter, text: str, base_hash: str | None, reason: str) -> dict:
    try:
        result = await writer.save([Edit(writer.relative(writer.config_path), text, base_hash)], reason)
    except SaveRefused as refused:
        raise HTTPException(refused.status, refused.detail()) from None
    return state(writer) | {"saved": result}


def _root(request: Request, writer: ConfigWriter) -> Path:
    """Where Kometa runs from, which is where it resolves a relative Apprise path."""
    entry = request.app.state.settings.kometa_entry
    return entry.parent if entry else writer.config_dir


@router.get("")
async def get_notifications(writer: Writer) -> dict:
    return state(writer)


class WebhooksIn(BaseModel):
    base_hash: str | None
    events: dict[str, list[Value]]


@router.put("/webhooks")
async def put_webhooks(body: WebhooksIn, writer: Writer) -> dict:
    """The user's own targets per event. Studio's receiver isn't the browser's to change: it stays as it is."""
    text, _ = _current(writer)
    try:
        new = notifications.apply_webhooks(text, body.events)
    except NotificationProblem as problem:
        raise _refuse(problem.status, problem.message) from None
    if new == text:
        return state(writer) | {"saved": None}  # config.yml already says this
    return await _save(writer, new, body.base_hash, "Changed the webhook events in Settings → Notifications")


class ServiceIn(BaseModel):
    values: dict[str, Value | None]  # a secret left empty keeps the saved one


class SaveServiceIn(ServiceIn):
    base_hash: str | None


async def _tested(request: Request, writer: ConfigWriter, http: httpx.AsyncClient, name: str, given: dict[str, str | None]) -> tuple[dict[str, str], str]:
    """The values to use and what the test found; raises NotificationProblem if they're incomplete or the test fails."""
    text, _ = _current(writer)
    values = notifications.values_to_save(text, name, given)
    return values, await notifications.test_service(http, name, values, _root(request, writer))


@router.post("/{name}/test")
async def test_service(name: str, body: ServiceIn, request: Request, writer: Writer, http: Http) -> dict:
    """Test a service as entered, before it's saved."""
    if name not in notifications.SERVICES:
        _not_found(name)
    try:
        _, message = await _tested(request, writer, http, name, body.values)
    except NotificationProblem as problem:
        return {"ok": False, "error": problem.message}
    return {"ok": True, "message": message}


@router.put("/{name}")
async def save_service(name: str, body: SaveServiceIn, request: Request, writer: Writer, http: Http) -> dict:
    """Save a service, but only once the same test the Test button runs has passed again, here."""
    if name not in notifications.SERVICES:
        _not_found(name)
    try:
        values, _ = await _tested(request, writer, http, name, body.values)
    except NotificationProblem as problem:
        raise _refuse(422, f"The test failed, so nothing was saved: {problem.message}") from None
    text, _ = _current(writer)
    new = notifications.apply_service(text, name, values)
    if new == text:
        return state(writer) | {"saved": None}  # config.yml already says this
    label = notifications.SERVICES[name].label
    return await _save(writer, new, body.base_hash, f"Set up {label} in Settings → Notifications")


@router.delete("/{name}")
async def remove_service(name: str, base_hash: str, writer: Writer) -> dict:
    if name not in notifications.SERVICES:
        _not_found(name)
    text, _ = _current(writer)
    try:
        new = notifications.remove_service(text, name)
    except NotificationProblem as problem:
        raise _refuse(problem.status, problem.message) from None
    label = notifications.SERVICES[name].label
    return await _save(writer, new, base_hash, f"Removed {label} in Settings → Notifications")


def _not_found(name: str) -> None:
    raise HTTPException(404, f"Kometa has no notification service called {name!r}")
