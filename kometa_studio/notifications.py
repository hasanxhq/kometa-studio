"""Kometa's notification services and webhook events, for Settings → Notifications.

Kometa 2.5.3 reads four services from the root of config.yml (modules/config.py) and sends each
webhook event to them by name, or to plain URLs (modules/webhooks.py). Every key is required:

    notifiarr: apikey
    gotify:    url, token
    ntfy:      url, token, topic
    apprise:   config (a path or URL to an Apprise configuration)

Studio tests a service itself, with httpx, before it saves one: a Notifiarr key is checked the way
Kometa checks it at start-up, Gotify and ntfy get one labelled test message, and an Apprise
configuration is read and must list at least one service (Apprise sends the messages, and Studio
doesn't have it). Saving edits the YAML node by node and goes through ConfigWriter like any edit.

Studio's own webhook receiver (kometa_config.ensure_studio_webhooks) is never edited here: its
entries keep their place at the end of each event's list, with their comment.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from .kometa_config import STUDIO_MARK, WEBHOOK_EVENTS, _parse, is_studio_webhook, render
from .kometa_files import BARE_MASK, PLACEHOLDER, mask_secrets
from .plex_routes import mask

NOTIFIARR_URL = "https://notifiarr.com/api/v1/"
TIMEOUT = 10.0
TEST_TITLE = "Kometa Studio test notification"
TEST_MESSAGE = "Kometa Studio sent this to check that Kometa can notify you here. Nothing else to do."


@dataclass(frozen=True)
class Key:
    name: str
    label: str
    secret: bool = False


@dataclass(frozen=True)
class Service:
    name: str
    label: str
    keys: tuple[Key, ...]


SERVICES: dict[str, Service] = {
    service.name: service
    for service in (
        Service("notifiarr", "Notifiarr", (Key("apikey", "API key", secret=True),)),
        Service("gotify", "Gotify", (Key("url", "Server URL"), Key("token", "Application token", secret=True))),
        Service("ntfy", "ntfy", (Key("url", "Server URL"), Key("token", "Access token", secret=True), Key("topic", "Topic"))),
        Service("apprise", "Apprise", (Key("config", "Apprise configuration"),)),
    )
}


class NotificationProblem(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _text(value: object) -> str | None:
    return None if value is None or value == "" else str(value)


def _section(document: CommentedMap, name: str) -> dict:
    section = document.get(name)
    return section if isinstance(section, dict) else {}


def _targets(value: object) -> list[str]:
    """One webhook event's targets: Kometa takes a single string or a list."""
    if value is None or value == "":
        return []
    items = value if isinstance(value, list) else [value]
    return [str(item) for item in items if item is not None and item != ""]


def url_id(url: str) -> str:
    """How the browser names a webhook URL it can't see in full."""
    return "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def mask_url(url: str) -> str:
    """A webhook URL with its secrets hidden: tokens in the query, Discord's and Slack's path, a password before the host."""
    masked = PLACEHOLDER.sub(BARE_MASK, mask_secrets(url)[0])
    return re.sub(r"^([a-z][a-z0-9+.-]*://[^/@:\s]*:)[^/@\s]+@", rf"\g<1>{BARE_MASK}@", masked, flags=re.IGNORECASE)


# --- Reading ------------------------------------------------------------------------


def read_state(text: str | None) -> dict:
    """The services and webhook events in config.yml, with every secret masked."""
    document = _parse(text)[0] if text else CommentedMap()
    services = []
    for service in SERVICES.values():
        section = _section(document, service.name)
        keys = []
        for key in service.keys:
            value = _text(section.get(key.name))
            keys.append({"name": key.name, "label": key.label, "secret": key.secret, "value": None if key.secret else value, "masked": mask(value) if key.secret else None})
        services.append({"name": service.name, "label": service.label, "configured": service.name in document, "keys": keys})
    return {"services": services, "webhooks": read_webhooks(document)}


def read_webhooks(document: CommentedMap) -> dict:
    """config.yml's webhook events as a grid: one column per service or URL, Studio's own receiver locked."""
    hooks = document.get("webhooks")
    hooks = hooks if isinstance(hooks, dict) else {}
    columns: dict[str, dict] = {}
    for name, service in SERVICES.items():
        if name in document:
            columns[name] = {"id": name, "label": service.label, "kind": "service", "configured": True}
    events: dict[str, list[str]] = {}
    for event in WEBHOOK_EVENTS:
        chosen: list[str] = []
        for target in _targets(hooks.get(event)):
            if is_studio_webhook(target):
                column = {"id": "studio", "label": "Kometa Studio", "kind": "studio", "configured": True}
            elif target in SERVICES:
                column = {"id": target, "label": SERVICES[target].label, "kind": "service", "configured": target in document}
            else:
                column = {"id": url_id(target), "label": mask_url(target), "kind": "url", "configured": True}
            columns.setdefault(column["id"], column)
            if column["id"] not in chosen:
                chosen.append(column["id"])
        events[event] = chosen
    order = {"service": 0, "url": 1, "studio": 2}
    return {"targets": sorted(columns.values(), key=lambda c: order[c["kind"]]), "events": events}


# --- Editing ------------------------------------------------------------------------


def service(name: str) -> Service:
    if name not in SERVICES:
        raise NotificationProblem(404, f"Kometa has no notification service called {name!r}")
    return SERVICES[name]


def values_to_save(text: str | None, name: str, given: dict[str, str | None]) -> dict[str, str]:
    """The service's values as entered, with a secret left empty taken from config.yml. Every key is required."""
    which = service(name)
    saved = _section(_parse(text)[0], name) if text else {}
    values: dict[str, str] = {}
    for key in which.keys:
        value = (given.get(key.name) or "").strip()
        if not value and key.secret:
            value = _text(saved.get(key.name)) or ""
        if not value:
            raise NotificationProblem(422, f"Enter {which.label}'s {key.label.lower()}")
        values[key.name] = value
    return values


def apply_service(text: str | None, name: str, values: dict[str, str]) -> str:
    """config.yml with one service set; keys that didn't change keep their node, and the rest of the file is untouched."""
    which = service(name)
    document, indent = _parse(text) if text else (CommentedMap(), (2, 4, 2))
    section = document.get(name)
    if not isinstance(section, CommentedMap):
        section = CommentedMap()
        document[name] = section
    for key in which.keys:
        if _text(section.get(key.name)) != values[key.name]:
            section[key.name] = values[key.name]
    return render(text, document, indent)


def remove_service(text: str | None, name: str) -> str:
    """config.yml without one service's section, and without it in any webhook event (Kometa would skip it anyway)."""
    service(name)
    if not text:
        raise NotificationProblem(404, "config.yml doesn't exist yet")
    document, indent = _parse(text)
    if name not in document:
        raise NotificationProblem(404, f"{SERVICES[name].label} isn't set up in config.yml")
    del document[name]
    hooks = document.get("webhooks")
    if isinstance(hooks, CommentedMap):
        for event in WEBHOOK_EVENTS:
            _drop(hooks, event, name)
    libraries = document.get("libraries")
    if isinstance(libraries, CommentedMap):
        for library in libraries.values():
            library_hooks = library.get("webhooks") if isinstance(library, CommentedMap) else None
            if isinstance(library_hooks, CommentedMap):
                _drop(library_hooks, "changes", name)
    return render(text, document, indent)


def _drop(hooks: CommentedMap, event: str, name: str) -> None:
    current = _targets(hooks.get(event))
    if name in current:
        _set_targets(hooks, event, [t for t in current if t != name])


def _set_targets(hooks: CommentedMap, event: str, targets: list[str]) -> None:
    """Write one event's targets: a single string stays a string, Studio's entries keep their comment."""
    if not targets:
        hooks[event] = None
        return
    if len(targets) == 1 and not isinstance(hooks.get(event), list) and not is_studio_webhook(targets[0]):
        hooks[event] = targets[0]
        return
    seq = CommentedSeq(targets)
    for index, target in enumerate(targets):
        if is_studio_webhook(target):
            seq.yaml_add_eol_comment(STUDIO_MARK, index)
    hooks[event] = seq


def valid_webhook_url(url: str) -> bool:
    """Kometa's own rule (modules/webhooks.py): a complete http(s) URL without spaces or angle brackets."""
    try:
        parsed = urlsplit(url)
        parsed.port  # noqa: B018 - raises for a malformed port, as in Kometa
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname) and not any(c.isspace() or c in "<>" for c in url)


def apply_webhooks(text: str | None, chosen: dict[str, list[str]]) -> str:
    """config.yml with the user's own webhook targets per event; Studio's receiver stays exactly where it is.

    ``chosen`` names targets as the grid does: a service name, a known URL's id, or a new http(s) URL.
    Events left out are not touched. Targets that stay keep their order; new ones go after them.
    """
    document, indent = _parse(text) if text else (CommentedMap(), (2, 4, 2))
    hooks = document.get("webhooks")
    if hooks is not None and hooks != "" and not isinstance(hooks, CommentedMap):
        raise NotificationProblem(422, "webhooks in config.yml isn't a mapping, so its events can't be edited here")
    current_hooks = hooks if isinstance(hooks, CommentedMap) else {}
    known = {url_id(t): t for event in WEBHOOK_EVENTS for t in _targets(current_hooks.get(event)) if t not in SERVICES and not is_studio_webhook(t)}

    def resolve(target: str) -> str | None:
        target = target.strip()
        if target == "studio":
            return None  # Studio's own entries aren't the browser's to change
        if target in SERVICES:
            return target
        if target in known:
            return known[target]
        if target.startswith("url:"):
            raise NotificationProblem(409, "A webhook URL changed in config.yml since the page loaded. Reload the page.")
        if valid_webhook_url(target):
            return target
        raise NotificationProblem(422, f"{mask_url(target)} isn't a webhook Kometa can use: enter a complete http:// or https:// URL")

    for event in chosen:
        if event not in WEBHOOK_EVENTS:
            raise NotificationProblem(422, f"Kometa has no webhook event called {event!r}")
    for event in WEBHOOK_EVENTS:
        if event not in chosen:
            continue
        wanted: list[str] = []
        for target in chosen[event]:
            resolved = resolve(target)
            if resolved is not None and resolved not in wanted:
                wanted.append(resolved)
        current = _targets(current_hooks.get(event))
        studio = [t for t in current if is_studio_webhook(t)]
        user = [t for t in current if not is_studio_webhook(t)]
        kept = [t for t in user if t in wanted] + [t for t in wanted if t not in user]
        if kept == user:
            continue
        if not isinstance(hooks, CommentedMap):
            hooks = CommentedMap()
            document["webhooks"] = hooks
            current_hooks = hooks
        _set_targets(hooks, event, kept + studio)
    return render(text, document, indent)


# --- Testing ------------------------------------------------------------------------


async def test_service(http: httpx.AsyncClient, name: str, values: dict[str, str], root: Path) -> str:
    """Test a service as entered. Returns what worked; raises NotificationProblem saying what didn't."""
    try:
        if name == "notifiarr":
            return await _test_notifiarr(http, values["apikey"])
        if name == "gotify":
            return await _test_gotify(http, values["url"], values["token"])
        if name == "ntfy":
            return await _test_ntfy(http, values["url"], values["token"], values["topic"])
        if name == "apprise":
            return await _test_apprise(http, values["config"], root)
    except httpx.TimeoutException:
        raise NotificationProblem(422, f"No answer within {TIMEOUT:g} s") from None
    except httpx.InvalidURL:
        raise NotificationProblem(422, "That isn't a URL Studio can use") from None
    except httpx.HTTPError as error:
        raise NotificationProblem(422, f"Can't connect: {error}") from None
    raise NotificationProblem(404, f"Kometa has no notification service called {name!r}")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


async def _test_notifiarr(http: httpx.AsyncClient, apikey: str) -> str:
    # Kometa's own check at start-up (modules/notifiarr.py): the account's settings, with the key.
    response = await http.get(f"{NOTIFIARR_URL}user/pmm/", params={"fetch": "settings"}, headers={"X-API-Key": apikey}, timeout=TIMEOUT)
    body = _json(response)
    if not isinstance(body, dict):
        raise NotificationProblem(422, f"Notifiarr answered HTTP {response.status_code}, without the JSON Kometa expects")
    details = body.get("details") if isinstance(body.get("details"), dict) else {}
    if response.status_code in (401, 403) or (response.status_code < 500 and body.get("result") == "error") or not details.get("response"):
        raise NotificationProblem(422, "Notifiarr refused the API key")
    if response.status_code >= 400:
        raise NotificationProblem(422, f"Notifiarr answered HTTP {response.status_code}")
    return "Notifiarr accepted the API key. Add notifiarr to the webhook events below to get Kometa's notifications there."


async def _test_gotify(http: httpx.AsyncClient, url: str, token: str) -> str:
    base = url.rstrip("/")
    version = _json(await http.get(f"{base}/version", timeout=TIMEOUT))  # Kometa checks this first
    if not isinstance(version, dict) or "version" not in version:
        raise NotificationProblem(422, "That address answered, but not like Gotify")
    response = await http.post(f"{base}/message", headers={"X-Gotify-Key": token}, json={"message": TEST_MESSAGE, "title": TEST_TITLE}, timeout=TIMEOUT)
    if response.status_code in (401, 403):
        raise NotificationProblem(422, "Gotify refused the application token")
    if response.status_code >= 400:
        body = _json(response)
        reason = body.get("errorDescription") if isinstance(body, dict) else None
        raise NotificationProblem(422, f"Gotify answered HTTP {response.status_code}" + (f": {reason}" if reason else ""))
    return f"Gotify {version['version']} accepted a test message."


async def _test_ntfy(http: httpx.AsyncClient, url: str, token: str, topic: str) -> str:
    headers = {"Authorization": f"Bearer {token}", "Title": TEST_TITLE, "Priority": "3", "Icon": "https://kometa.wiki/en/latest/assets/icon.png"}
    response = await http.post(f"{url.rstrip('/')}/{topic}", headers=headers, content=TEST_MESSAGE.encode("utf-8"), timeout=TIMEOUT)
    if response.status_code in (401, 403):
        raise NotificationProblem(422, f"ntfy refused the access token for the topic {topic}")
    if response.status_code >= 400:
        body = _json(response)
        reason = body.get("error") if isinstance(body, dict) else None
        raise NotificationProblem(422, f"ntfy answered HTTP {response.status_code}" + (f": {reason}" if reason else ""))
    return f"ntfy accepted a test message on the topic {topic}."


async def _test_apprise(http: httpx.AsyncClient, config: str, root: Path) -> str:
    if config.startswith(("http://", "https://")):
        response = await http.get(config, timeout=TIMEOUT)
        if response.status_code >= 400:
            raise NotificationProblem(422, f"The Apprise configuration's address answered HTTP {response.status_code}")
        text = response.text
    else:
        path = Path(config.removeprefix("file://")).expanduser()
        path = path if path.is_absolute() else root / path  # Kometa runs from its own folder
        if not path.is_file():
            raise NotificationProblem(422, f"There's no file at {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise NotificationProblem(422, f"Can't read {path}: {error}") from None
    count = apprise_services(text)
    if not count:
        raise NotificationProblem(422, "That Apprise configuration lists no notification services, so Kometa would refuse it")
    plural = "service" if count == 1 else "services"
    return f"The Apprise configuration lists {count} notification {plural}. Apprise sends the messages, so Studio sent none."


def apprise_services(text: str) -> int:
    """How many service URLs an Apprise configuration lists: YAML with ``urls:``, or its text format (one URL a line)."""
    try:
        data = YAML(typ="safe", pure=True).load(text)
    except YAMLError:
        data = None
    if isinstance(data, dict):
        urls = data.get("urls")
        return len([u for u in urls if u]) if isinstance(urls, list) else 0
    count = 0
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", ";")) and re.match(r"^(?:[\w\s,=-]*=\s*)?[a-z][a-z0-9+.-]*://\S", line, re.IGNORECASE):
            count += 1
    return count
