"""People collections (actor, director, writer, producer): who Kometa would make a collection for.

Kometa ranks a library's people by scanning every title's full credits (``meta.py``: ``library.get_all()``,
then each item reloaded, its first ``depth`` people counted) and keeps the most frequent, ``limit`` of them
with at least ``minimum`` titles. Studio does the same scan through Plex's API. Credits are kept in
``<data dir>/plex-people.json`` per title and read again only when Plex's ``updatedAt`` for it changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plex_library import PlexNotFound, PlexServer, PlexUnavailable

log = logging.getLogger(__name__)

PEOPLE_TYPES = ("actor", "director", "writer", "producer")
CACHE = "plex-people.json"
PARALLEL = 8

Credits = dict[str, list[tuple[str, str]]]  # kind → [(person id, name)] in Plex's order


@dataclass
class Person:
    name: str
    titles: int  # titles in the library crediting them anywhere (what Kometa's plex_search finds)


class PeopleScan:
    """Every title's credits for one library, in Kometa's order; read once per count, cached between counts."""

    def __init__(self, plex: PlexServer, data_dir: Path):
        self.plex = plex
        self.path = data_dir / CACHE
        self._libraries: dict[str, list[Credits]] = {}

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, cache: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as error:
            log.warning("Couldn't keep Plex's credits: %s", error)

    async def library(self, library_key: str, library_type: str) -> list[Credits]:
        if library_key in self._libraries:
            return self._libraries[library_key]
        keys = await self.plex.all_keys(library_key, library_type)
        cache = self._load()
        missing = [(key, updated) for key, updated in keys if (cache.get(key) or {}).get("updated") != updated]
        limit = asyncio.Semaphore(PARALLEL)

        async def read(key: str, updated: str) -> None:
            async with limit:
                try:
                    credits = await self.plex.credits(key)
                except PlexNotFound:  # gone since the listing: skipped, as Kometa logs and skips it
                    return
            cache[key] = {"updated": updated, "credits": {kind: [list(p) for p in people] for kind, people in credits.items()}}

        try:
            await asyncio.gather(*(read(key, updated) for key, updated in missing))
        finally:
            if missing:
                self._save(cache)
        found = [
            {kind: [(str(p[0]), str(p[1])) for p in people] for kind, people in (cache[key].get("credits") or {}).items()}
            for key, _ in keys
            if key in cache
        ]
        self._libraries[library_key] = found
        return found


def _setting(data: dict, *names: str) -> int | None:
    """A ``data:`` value by any of its names, case-insensitive, as Kometa reads it (``actor_depth`` is ``depth``)."""
    lowered = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        if name in lowered and lowered[name] is not None:
            try:
                return max(1, int(lowered[name]))
            except (TypeError, ValueError):
                return None
    return None


def rank(credits: list[Credits], kind: str, data: dict | None, include: list[str], exclude: list[str]) -> list[Person]:
    """The people Kometa makes collections for, in its order (``meta.py``, ``auto_type in [actor, director, writer, producer]``)."""
    data = data or {}
    depth = _setting(data, "depth", "actor_depth") or 3
    minimum = _setting(data, "minimum", "actor_minimum")
    limit = _setting(data, "limit", "number_of_actors")

    counted: dict[str, dict] = {}  # person id → {name, count}; insertion order is first appearance
    included: list[str] = []
    anywhere: dict[str, int] = {}
    for item in credits:
        people = item.get(kind, [])
        for name in {name for _, name in people}:
            anywhere[name] = anywhere.get(name, 0) + 1
        for person_id, name in people[:depth]:
            if name in include:
                if name not in included:
                    included.append(name)
            else:
                counted.setdefault(person_id, {"name": name, "count": 0})["count"] += 1

    roles = sorted(counted.values(), key=lambda role: role["count"], reverse=True)  # stable, as Kometa's sort
    if not minimum:
        minimum = 1 if limit else 3
    if not limit:
        limit = len(roles)
    names = list(included)
    for role in roles:
        if len(names) < limit and role["count"] >= minimum and role["name"] not in exclude and role["name"] not in names:
            names.append(role["name"])
    return [Person(name, anywhere.get(name, 0)) for name in names]


async def scan_or_none(scan: PeopleScan | None, library_key: str, library_type: str) -> list[Credits] | None:
    if scan is None:
        return None
    try:
        return await scan.library(library_key, library_type)
    except PlexUnavailable:
        raise
    except Exception:  # a malformed answer: the category says it couldn't be listed
        log.exception("Reading Plex's credits")
        return None
