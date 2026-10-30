"""Reading and writing Kometa's config.yml.

Files are edited as ruamel.yaml round-trip documents, so the user's comments,
key order and anchors survive. This is the minimal save from milestone 2: back
up, then replace atomically. Validation with Kometa before writing comes later
(handoff v2 §7.4).
"""

import io
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.util import load_yaml_guess_indent


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


def _load(path: Path) -> tuple[CommentedMap, tuple[int, int, int]]:
    """Load a file and guess its indentation, so saving it keeps the user's layout."""
    if not path.exists():
        return CommentedMap(), TEMPLATE_INDENT
    text = path.read_text(encoding="utf-8")
    # ruamel guesses list indentation (where items start, where the dash sits) but not mapping indentation.
    _, sequence, offset = load_yaml_guess_indent(text)
    indent = (_mapping_indent(text), sequence or TEMPLATE_INDENT[1], offset if sequence else TEMPLATE_INDENT[2])
    document = _yaml(indent).load(text)
    if document is None:
        return CommentedMap(), TEMPLATE_INDENT
    if not isinstance(document, CommentedMap):
        raise ValueError(f"{path} doesn't contain a YAML mapping at the top level")
    return document, indent


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
    """Set plex.url and plex.token, keeping everything else. Returns the backup's path, if there was a file to back up."""
    document, indent = _load(path)
    plex = document.get("plex")
    if not isinstance(plex, CommentedMap):
        plex = CommentedMap()
        document["plex"] = plex
    plex["url"] = url
    plex["token"] = token

    buffer = io.StringIO()
    _yaml(indent).dump(document, buffer)
    backup = backup_file(path, backup_root)
    write_atomic(path, buffer.getvalue())
    return backup


def backup_file(path: Path, backup_root: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    target = backup_root / stamp / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


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
