"""How Kometa's config could touch Maintainerr's collections, worked out from the config alone.

Maintainerr's collections carry no Kometa label, so to Kometa they're "unmanaged". Kometa reaches them
three ways (checked against Kometa 2.5.3's modules/config.py and operations.py):

- ``delete_collections`` (or the old ``delete_unmanaged_collections`` / ``delete_collections_with_less``)
  in a library's operations, unless it's limited to ``managed: true`` or ``configured: true``;
- ``mass_collection_mode`` (or ``mass_metadata_update: collections:``), which sets every collection's mode;
- a Kometa collection with the same name as one of Maintainerr's: Kometa adopts it, labels it, and in
  ``sync`` mode removes what Maintainerr put in it.

Each risk says which run modes reach it, so a run is held only when it would actually do the damage.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAMLError

from .kometa_files import ConfigReader, load_yaml

OPERATIONS_MODES = frozenset({"all", "operations"})
COLLECTIONS_MODES = frozenset({"all", "collections"})


@dataclass(frozen=True)
class Risk:
    library: str  # Kometa's name for the library
    kind: str  # delete, mode or name
    message: str
    modes: frozenset[str]  # run modes that would do it
    collection: str | None = None  # for kind "name": Kometa's collection


def _operations(body: dict) -> list[dict]:
    ops = body.get("operations")
    if isinstance(ops, dict):
        return [ops]
    if isinstance(ops, list):
        return [op for op in ops if isinstance(op, dict)]
    return []


def _deletes_unmanaged(op: dict) -> bool:
    rule = op.get("delete_collections")
    if isinstance(rule, dict):
        managed, configured, less = rule.get("managed"), rule.get("configured"), rule.get("less")
        if managed is None and configured is None and less is None:
            return False  # Kometa deletes nothing then
        return managed is not True and configured is not True
    return bool(op.get("delete_unmanaged_collections")) or op.get("delete_collections_with_less") is not None


def _sets_every_mode(op: dict) -> bool:
    if op.get("mass_collection_mode") is not None:
        return True
    update = op.get("mass_metadata_update")
    return isinstance(update, dict) and update.get("collections") is not None


def risks(config_path: Path, kometa_root: Path | None, owned: dict[str, list[str]]) -> list[Risk]:
    """``owned`` maps a Plex library title (lower case) to the names of Maintainerr's collections in it."""
    try:
        data: Any = load_yaml(config_path) or {}
    except (OSError, YAMLError):
        return []
    libraries = data.get("libraries") if isinstance(data, dict) else None
    if not isinstance(libraries, dict) or not owned:
        return []
    try:
        names_by_library = {
            library.name: {c["name"] for ref in library.collection_files for f in ref.files for c in f.collections if c.get("name")}
            for library in ConfigReader(config_path, kometa_root).read().libraries
        }
    except (OSError, ValueError):
        names_by_library = {}

    found: list[Risk] = []
    for name, body in libraries.items():
        body = body if isinstance(body, dict) else {}
        theirs = owned.get(str(body.get("library_name") or name).lower(), [])
        if not theirs:
            continue
        name = str(name)
        listed = ", ".join(f"“{title}”" for title in sorted(theirs)[:3]) + (" …" if len(theirs) > 3 else "")
        ops = _operations(body)
        if any(_deletes_unmanaged(op) for op in ops):
            found.append(
                Risk(
                    name,
                    "delete",
                    f"{name}: delete_collections would delete Maintainerr's collections ({listed}): Kometa sees them as unmanaged. "
                    "Limit it with managed: true.",
                    OPERATIONS_MODES,
                )
            )
        if any(_sets_every_mode(op) for op in ops):
            found.append(Risk(name, "mode", f"{name}: mass_collection_mode sets every collection's mode, Maintainerr's ({listed}) too.", OPERATIONS_MODES))
        lowered = {title.lower(): title for title in theirs}
        for collection in sorted(names_by_library.get(name, set())):
            if collection.lower() in lowered:
                found.append(
                    Risk(
                        name,
                        "name",
                        f"{name}: Kometa's collection “{collection}” has the same name as Maintainerr's, so Kometa would take it over. Rename one of them.",
                        COLLECTIONS_MODES,
                        collection,
                    )
                )
    return found


def reaches(risk: Risk, mode: str, libraries: list[str], collections: list[str]) -> bool:
    """Whether a run (mode, --run-libraries, --run-collections) would do what ``risk`` describes."""
    if mode not in risk.modes:
        return False
    if libraries and risk.library not in libraries:
        return False
    if collections:  # only those collections run: no operations, and no other collection
        return risk.kind == "name" and risk.collection in collections
    return True
