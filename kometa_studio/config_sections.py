"""Changing one top-level section of config.yml (``radarr:``, ``tmdb:``, …) from a Settings form, adding a
library, and starting a new collection or overlay file for a library.

Every change goes through the normal save flow (``ConfigWriter.save``): Kometa checks it, the old
file is backed up, and comments and layout elsewhere in the file are kept.
"""

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from .config_items import FILE_LISTS, ItemProblem, _update, new_file
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


def with_playlist_file(text: str, reference: str) -> str:
    """``text`` with ``- file: reference`` added to config.yml's playlist_files (playlists aren't per library)."""
    document, indent = _parse(text)
    entry = CommentedMap([("file", reference)])
    current = document.get("playlist_files")
    if current is None:
        document["playlist_files"] = CommentedSeq([entry])
    elif isinstance(current, list):
        current.append(entry)
    else:  # a single entry, which Kometa also accepts
        document["playlist_files"] = CommentedSeq([current, entry])
    return render(text, document, indent)


async def new_playlist_file(writer: ConfigWriter, relative: str, name: str, value: dict) -> dict:
    """Start a new file with one playlist, and add it to config.yml's playlist_files: one save, checked by Kometa."""
    path = writer.resolve(relative)
    if path.exists():
        raise SaveRefused(409, f"{relative} already exists. Choose it from the list, or pick another name.", path=relative)
    if not writer.config_path.exists():
        raise SaveRefused(409, "config.yml doesn't exist yet")
    text = new_file("playlists", name, value)
    config = _config_edit(writer, lambda current: with_playlist_file(current or "", writer.reference(path)))
    return await writer.save([Edit(writer.relative(path), text, None), config], f"Added the playlist {name!r} in a new file, {writer.relative(path)}")


# --- Kometa's defaults in a library -------------------------------------------------------


def _is_default(entry: object, name: str) -> bool:
    if not isinstance(entry, dict):
        return False
    return entry.get("default") == name or entry.get("pmm") == name or entry.get("git") == f"PMM/{name}"


def _library_body(document: CommentedMap, library: str) -> CommentedMap:
    libraries = document.get("libraries")
    if not isinstance(libraries, CommentedMap) or library not in libraries:
        raise ValueError(f"config.yml has no library called {library}")
    body = libraries[library]
    if body is None:
        body = CommentedMap()
        libraries[library] = body
    if not isinstance(body, CommentedMap):
        raise ValueError(f"{library} in config.yml isn't a mapping")
    return body


def _set_variables(entry: CommentedMap, variables: dict) -> None:
    current = entry.get("template_variables")
    if not variables:
        entry.pop("template_variables", None)
    elif isinstance(current, CommentedMap):
        _update(current, variables)  # unchanged variables keep their YAML (comments, quoting)
    else:
        entry["template_variables"] = CommentedMap(variables)


def with_library_default(text: str, library: str, files: str, name: str, variables: dict | None) -> str:
    """``text`` with Kometa's default ``name`` in the library's ``files`` list, with these template variables; ``variables`` None takes it out.

    A default listed more than once (with different variables, say) has its first entry changed, or every entry taken out.
    """
    document, indent = _parse(text)
    body = _library_body(document, library)
    if files not in body and OLD_NAMES[files] in body:
        raise ValueError(f"{library} still uses the old {OLD_NAMES[files]}. Rename it to {files} in config.yml first.")
    current = body.get(files)
    entries = current if isinstance(current, list) else ([] if current is None else [current])
    if variables is None:
        kept = [entry for entry in entries if not _is_default(entry, name)]
        if len(kept) == len(entries):
            raise ValueError(f"{library} doesn't use the {name} default")
        if kept:
            if isinstance(current, list):
                current[:] = kept
            else:
                body[files] = CommentedSeq(kept)
        else:
            del body[files]  # Kometa refuses an empty list
        return render(text, document, indent)
    found = next((entry for entry in entries if _is_default(entry, name)), None)
    if found is None:
        found = CommentedMap([("default", name)])
        if isinstance(current, list):
            current.append(found)
        else:
            body[files] = CommentedSeq([*entries, found])
    elif not isinstance(found, CommentedMap):
        raise ValueError(f"The {name} entry in config.yml isn't a mapping")
    _set_variables(found, variables)
    return render(text, document, indent)


def with_library_variables(text: str, library: str, variables: dict) -> str:
    """``text`` with the library's own template_variables (for every file in it) set to ``variables``."""
    document, indent = _parse(text)
    _set_variables(_library_body(document, library), variables)
    return render(text, document, indent)


async def set_library_default(writer: ConfigWriter, library: str, kind: str, name: str, variables: dict | None) -> dict:
    files = "overlay_files" if kind == "overlay" else "collection_files"
    action = f"Turned off the {name} default" if variables is None else f"Set the {name} default"
    return await writer.save([_config_edit(writer, lambda text: with_library_default(text or "", library, files, name, variables))], f"{action} for {library}")


async def set_library_variables(writer: ConfigWriter, library: str, variables: dict) -> dict:
    return await writer.save([_config_edit(writer, lambda text: with_library_variables(text or "", library, variables))], f"Set the template variables for {library}")


# --- Kometa's own settings: block ------------------------------------------------------


def with_settings(text: str, values: dict) -> str:
    """``text`` with Kometa's ``settings:`` block set to ``values``. Unchanged keys keep their YAML; an empty block goes."""
    document, indent = _parse(text)
    current = document.get("settings")
    if not values:
        document.pop("settings", None)
    elif isinstance(current, CommentedMap):
        _update(current, values)
    else:
        document["settings"] = CommentedMap(values)
    return render(text, document, indent)


async def set_settings(writer: ConfigWriter, base: dict, values: dict) -> dict:
    """Save the settings form. ``base`` is what the form started from: if config.yml's settings changed since, nothing is saved."""
    if (read_section(writer.config_path, "settings") or {}) != base:
        raise SaveRefused(409, "Kometa's settings in config.yml changed since you opened them. Reload to see the new ones.")
    return await writer.save([_config_edit(writer, lambda text: with_settings(text or "", values))], "Changed Kometa's settings")
