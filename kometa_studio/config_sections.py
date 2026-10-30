"""Changing one top-level section of config.yml (``radarr:``, ``tmdb:``, …) from a Settings form, adding a
library, and starting a new collection or overlay file for a library.

Every change goes through the normal save flow (``ConfigWriter.save``): Kometa checks it, the old
file is backed up, and comments and layout elsewhere in the file are kept.
"""

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from .config_items import FILE_LISTS, ItemProblem, new_file
from .config_write import ConfigWriter, Edit, SaveRefused, file_hash
from .kometa_config import TEMPLATE_INDENT, _parse, render

# Old names Kometa still reads (modules/config.py). Kometa fills the new list from the old one only when the new
# one is missing, so adding the new list would hide what the old one names.
OLD_NAMES = {"collection_files": "metadata_path", "overlay_files": "overlay_path"}


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


# --- Libraries ------------------------------------------------------------------------


def with_library(text: str | None, name: str) -> str:
    """``text`` with an empty library ``name`` under ``libraries``. Kometa skips it until it has files or operations."""
    document, indent = _parse(text) if text else (CommentedMap(), TEMPLATE_INDENT)
    libraries = document.get("libraries")
    if libraries is None:
        libraries = CommentedMap()
        document["libraries"] = libraries
    if not isinstance(libraries, CommentedMap):
        raise ValueError("`libraries` in config.yml isn't a mapping")
    taken = {str(key) for key in libraries} | {str(body["library_name"]) for body in libraries.values() if isinstance(body, dict) and body.get("library_name")}
    if name in taken:
        raise ValueError(f"config.yml already has a library called {name}")
    libraries[name] = None
    return render(text, document, indent)


def with_library_file(text: str, library: str, files: str, reference: str) -> str:
    """``text`` with ``- file: reference`` added to the library's ``files`` list (collection_files or overlay_files)."""
    document, indent = _parse(text)
    libraries = document.get("libraries")
    if not isinstance(libraries, CommentedMap) or library not in libraries:
        raise ValueError(f"config.yml has no library called {library}")
    body = libraries[library]
    if body is None:
        body = CommentedMap()
        libraries[library] = body
    if not isinstance(body, CommentedMap):
        raise ValueError(f"{library} in config.yml isn't a mapping")
    if files not in body and OLD_NAMES[files] in body:
        raise ValueError(f"{library} still uses the old {OLD_NAMES[files]}. Rename it to {files} in config.yml first.")
    entry = CommentedMap([("file", reference)])
    current = body.get(files)
    if current is None:
        body[files] = CommentedSeq([entry])
    elif isinstance(current, list):
        current.append(entry)
    else:  # a single entry, which Kometa also accepts
        body[files] = CommentedSeq([current, entry])
    return render(text, document, indent)


def _config_edit(writer: ConfigWriter, change) -> Edit:
    path = writer.config_path
    current = path.read_bytes() if path.exists() else None
    try:
        text = change(current.decode("utf-8") if current is not None else None)
    except (ValueError, YAMLError) as error:
        raise SaveRefused(409, f"Can't update config.yml: {error}") from None
    return Edit(writer.relative(path), text, file_hash(current) if current is not None else None)


async def add_library(writer: ConfigWriter, name: str) -> dict:
    return await writer.save([_config_edit(writer, lambda text: with_library(text, name))], f"Added the library {name}")


async def new_file_for_library(writer: ConfigWriter, relative: str, library: str, section: str, name: str, value: dict) -> dict:
    """Start a new file with one collection or overlay, and add it to the library's list in config.yml: one save, checked by Kometa."""
    path = writer.resolve(relative)
    if path.exists():
        raise SaveRefused(409, f"{relative} already exists. Choose it from the list, or pick another name.", path=relative)
    if not writer.config_path.exists():
        raise SaveRefused(409, "config.yml doesn't exist yet")
    try:
        text = new_file(section, name, value)
    except ItemProblem as problem:
        raise SaveRefused(problem.status, problem.message, path=relative) from None
    config = _config_edit(writer, lambda current: with_library_file(current or "", library, FILE_LISTS[section], writer.reference(path)))
    return await writer.save([Edit(writer.relative(path), text, None), config], f"Added {name!r} in a new file, {writer.relative(path)}, for {library}")
