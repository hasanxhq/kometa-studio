"""Editing one collection, overlay or template inside a YAML file, for the designed forms (handoff v2 §7.1).

The form sends the item's whole new value as JSON. Only what changed is touched: keys whose
value is the same keep their YAML node (comments, quoting, flow style), nested mappings are
updated key by key, and the file is rendered with kometa_config.render, which keeps the
file's own formatting. The result is then saved through ConfigWriter.save like any edit, so
Kometa's check and the backup still apply.
"""

from datetime import date, datetime
from typing import Any

from ruamel.yaml.comments import CommentedMap

from .kometa_config import _parse, render

SECTIONS = ("collections", "dynamic_collections", "overlays", "templates", "metadata", "playlists")


class ItemProblem(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def to_plain(value: Any) -> Any:
    """ruamel's round-trip types as plain JSON-able Python."""
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def read_item(text: str, section: str, name: str) -> dict:
    document, _ = _parse(text)
    items = document.get(section)
    if not isinstance(items, dict) or name not in items:
        raise ItemProblem(404, f"There's no {name!r} under {section} in this file")
    value = items[name]
    return to_plain(value) if isinstance(value, dict) else {}


def _update(target: CommentedMap, new: dict) -> None:
    for key in [key for key in target if key not in new]:
        del target[key]
    for key, value in new.items():
        if key in target:
            current = target[key]
            if to_plain(current) == value:
                continue  # unchanged: keep the node as written
            if isinstance(current, CommentedMap) and isinstance(value, dict):
                _update(current, value)
                continue
        target[key] = value


def apply_item(text: str, section: str, name: str, value: dict | None, *, create: bool = False, rename: str | None = None) -> str:
    """The file's new text with one item created, changed, renamed or (value None) removed."""
    if section not in SECTIONS:
        raise ItemProblem(422, f"Studio edits items under {', '.join(SECTIONS)}, not {section}")
    document, indent = _parse(text)
    items = document.get(section)
    if items is None:
        if not create:
            raise ItemProblem(404, f"There's no {section} section in this file")
        items = CommentedMap()
        document[section] = items
    if not isinstance(items, CommentedMap):
        raise ItemProblem(422, f"{section} in this file isn't a mapping, so its items can't be edited one by one")

    if create:
        if name in items:
            raise ItemProblem(409, f"{name!r} already exists in this file")
        if value is None:
            raise ItemProblem(422, "A new item needs settings")
        items[name] = value
        return render(text, document, indent)

    if name not in items:
        raise ItemProblem(404, f"There's no {name!r} under {section} in this file")
    if value is None:
        del items[name]
        return render(text, document, indent)

    target = items[name]
    if not isinstance(target, CommentedMap):
        target = CommentedMap()
        items[name] = target
    _update(target, value)
    if rename and rename != name:
        if rename in items:
            raise ItemProblem(409, f"{rename!r} already exists in this file")
        position = list(items).index(name)
        items.insert(position, rename, items.pop(name))
    return render(text, document, indent)


def schema_kind(text: str, path: str) -> str:
    """Which of Kometa's schemas a file follows: config, collection, overlay, metadata or playlist."""
    if path.rsplit("/", 1)[-1] in ("config.yml", "config.yaml"):
        return "config"
    try:
        document, _ = _parse(text)
    except Exception:  # an unparseable file still opens in the editor; its YAML error shows there
        return "collection"
    for key, kind in (("overlays", "overlay"), ("playlists", "playlist"), ("metadata", "metadata")):
        if key in document:
            return kind
    return "collection"
