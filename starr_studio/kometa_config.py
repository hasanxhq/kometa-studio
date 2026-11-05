"""Reading and writing Kometa's config.yml.

Files are edited as ruamel.yaml round-trip documents, so the user's comments,
key order and anchors survive. This is the minimal save from milestone 2: back
up, then replace atomically. Validation with Kometa before writing comes later
(handoff v2 §7.4).
"""

import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.util import load_yaml_guess_indent

from .backups import take_backup
from .textmerge import merge3


@dataclass(frozen=True)
class PlexSettings:
    url: str | None
    token: str | None


# Kometa's template indents mappings by 2 and list items by 4 with the dash at 2.
TEMPLATE_INDENT = (2, 4, 2)


def _yaml(indent: tuple[int, int, int] = TEMPLATE_INDENT) -> YAML:
    yaml = YAML()  # round-trip mode
    yaml.preserve_quotes = True
    yaml.width = 4096  # never re-wrap long values
    mapping, sequence, offset = indent
    yaml.indent(mapping=mapping, sequence=sequence, offset=offset)
    return yaml


def _load(path: Path) -> tuple[CommentedMap, tuple[int, int, int], str | None]:
    """Load a file and guess its indentation, so saving it keeps the user's layout. Also returns the original text."""
    if not path.exists():
        return CommentedMap(), TEMPLATE_INDENT, None
    text = path.read_text(encoding="utf-8")
    document, indent = _parse(text)
    return document, indent, text


def _parse(text: str) -> tuple[CommentedMap, tuple[int, int, int]]:
    # ruamel guesses list indentation (where items start, where the dash sits) but not mapping indentation,
    # and its guess only means something if the file has a block list.
    _, sequence, offset = load_yaml_guess_indent(text)
    has_list = any(line.lstrip(" ").startswith("- ") for line in text.splitlines())
    if has_list and sequence:
        indent = (_mapping_indent(text), sequence, offset or 0)
    else:
        indent = (_mapping_indent(text), *TEMPLATE_INDENT[1:])
    document = _yaml(indent).load(text)
    if document is None:
        return CommentedMap(), indent
    if not isinstance(document, CommentedMap):
        raise ValueError("The file doesn't contain a YAML mapping at the top level")
    return document, indent


def _dump(document: CommentedMap, indent: tuple[int, int, int]) -> str:
    buffer = io.StringIO()
    _yaml(indent).dump(document, buffer)
    return buffer.getvalue()


def render(original: str | None, document: CommentedMap, indent: tuple[int, int, int]) -> str:
    """The new text for an edited document, keeping the original file's own formatting where ruamel would change it.

    If an unedited load and save gives back the original exactly, ruamel's output is used as is.
    Otherwise Studio's change is merged into the original text; the merge is only used if it
    holds exactly the same data as ruamel's output, else ruamel's output is used.
    """
    edited = _dump(document, indent)
    if original is None:
        return edited
    unedited = _dump(_parse(original)[0], indent)
    if unedited == original:
        return edited
    merged = merge3(unedited, original, edited)
    if merged is not None and _data(merged) == _data(edited):
        return merged
    return edited


def _data(text: str) -> object:
    return YAML(typ="safe", pure=True).load(text)


def _mapping_indent(text: str) -> int:
    """The indent of the first nested mapping key, which is how far this file indents each level."""
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        depth = len(line) - len(stripped)
        if depth and stripped and not stripped.startswith(("#", "-")) and ":" in stripped:
            return depth
    return TEMPLATE_INDENT[0]


def _text(value: object) -> str | None:
    return None if value is None or value == "" else str(value)


def read_plex(path: Path) -> PlexSettings:
    plex = _load(path)[0].get("plex")
    if not isinstance(plex, dict):
        return PlexSettings(None, None)
    return PlexSettings(_text(plex.get("url")), _text(plex.get("token")))


def write_plex(path: Path, url: str, token: str, backup_root: Path) -> Path | None:
    """Set plex.url and plex.token, keeping everything else. Returns the backed-up copy, if there was a file to back up."""
    document, indent, original = _load(path)
    plex = document.get("plex")
    if not isinstance(plex, CommentedMap):
        plex = CommentedMap()
        document["plex"] = plex
    plex["url"] = url
    plex["token"] = token
    return _save(path, original, document, indent, backup_root, "Connected Plex in Settings → Plex")


# --- Studio's webhook receiver (handoff v2 §5.2) ----------------------------------

WEBHOOK_EVENTS = ("error", "version", "run_start", "run_end", "changes", "delete")
EVENTS_PATH = "/api/v1/kometa/events"
STUDIO_MARK = "managed by Kometa Studio"


def is_studio_webhook(value: object) -> bool:
    return isinstance(value, str) and EVENTS_PATH in value and "token=" in value


def _add_studio_webhook(container: CommentedMap, key: str, url: str) -> bool:
    """Make Studio's URL the last target of one webhook attribute, keeping the user's own. Returns whether anything changed."""
    current = container.get(key)
    if isinstance(current, CommentedSeq):
        targets = current
    else:
        targets = CommentedSeq([] if current is None or current == "" else [current])
    studio = [index for index, value in enumerate(targets) if is_studio_webhook(value)]
    if targets is current and studio == [len(targets) - 1] and targets[-1] == url:
        return False
    for index in reversed(studio):  # an old port or token
        del targets[index]
    targets.append(url)
    targets.yaml_add_eol_comment(STUDIO_MARK, len(targets) - 1)
    container[key] = targets
    return True


def ensure_studio_webhooks(path: Path, url: str, backup_root: Path) -> bool:
    """Send every Kometa webhook event to Studio as well. Returns whether config.yml had to change.

    A library's own ``webhooks.changes`` replaces the global one in Kometa, so Studio adds itself there too.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} doesn't exist yet")
    document, indent, original = _load(path)
    changed = False
    hooks = document.get("webhooks")
    if not isinstance(hooks, CommentedMap):
        hooks = CommentedMap()
        document["webhooks"] = hooks
        changed = True
    for event in WEBHOOK_EVENTS:
        changed |= _add_studio_webhook(hooks, event, url)

    libraries = document.get("libraries")
    if isinstance(libraries, CommentedMap):
        for library in libraries.values():
            library_hooks = library.get("webhooks") if isinstance(library, CommentedMap) else None
            if isinstance(library_hooks, CommentedMap) and library_hooks.get("changes") not in (None, "", []):
                changed |= _add_studio_webhook(library_hooks, "changes", url)

    if changed:
        _save(path, original, document, indent, backup_root, "Added Studio's webhooks before a run")
    return changed


def _save(path: Path, original: str | None, document: CommentedMap, indent: tuple[int, int, int], backup_root: Path, reason: str) -> Path | None:
    text = render(original, document, indent)
    backup = take_backup(backup_root, path.parent, [path], reason) if original is not None else None
    write_atomic(path, text)
    return backup / path.name if backup else None


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder and rename it over the original, so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
