"""Changing one top-level section of config.yml (``radarr:``, ``tmdb:``, …) from a Settings form.

The change goes through the normal save flow (``ConfigWriter.save``): Kometa checks it, the old
file is backed up, and comments and layout elsewhere in the file are kept.
"""

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from .config_write import ConfigWriter, Edit, SaveRefused, file_hash
from .kometa_config import _parse, render


def read_section(config: Path | None, key: str) -> dict | None:
    """A top-level section as plain data, or None if config.yml doesn't have it as a mapping."""
    if config is None or not config.is_file():
        return None
    try:
        document = YAML(typ="safe").load(config.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return None
    section = document.get(key) if isinstance(document, dict) else None
    return section if isinstance(section, dict) else None


def with_section(text: str | None, key: str | tuple[str, ...], values: dict[str, object] | None) -> str:
    """``text`` with one section's keys set (a None value removes that key), or the whole section removed (``values`` None).

    ``key`` may be a path to a nested section, such as ``("libraries", "Movies")``; the sections on the way must exist.
    """
    document, indent = _parse(text) if text else (CommentedMap(), (2, 4, 2))
    *parents, last = (key,) if isinstance(key, str) else key
    container = document
    for name in parents:
        container = container.get(name)
        if not isinstance(container, CommentedMap):
            raise ValueError(f"config.yml has no {'.'.join(parents)} section")
    if values is None:
        container.pop(last, None)
    else:
        section = container.get(last)
        if not isinstance(section, CommentedMap):
            section = CommentedMap()
            container[last] = section
        for name, value in values.items():
            if value is None:
                section.pop(name, None)
            else:
                section[name] = value
    return render(text, document, indent)


async def save_section(writer: ConfigWriter, key: str | tuple[str, ...], values: dict[str, object] | None, reason: str) -> dict:
    path = writer.config_path
    current = path.read_bytes() if path.exists() else None
    try:
        text = with_section(current.decode("utf-8") if current is not None else None, key, values)
    except (ValueError, YAMLError) as error:
        raise SaveRefused(409, f"Can't update config.yml: {error}") from None
    return await writer.save([Edit(writer.relative(path), text, file_hash(current) if current is not None else None)], reason)
