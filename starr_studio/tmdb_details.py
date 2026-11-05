"""What Kometa looks up on TMDb for each title, for the franchise, origin country and original language categories.

Kometa's ``tmdb_collection``, ``origin_country`` and ``original_language`` dynamic collections read every title in
the library on TMDb (``meta.py``: ``config.TMDb.get_item``): a movie's collection, a show's origin countries, either's
original language. A title without a TMDb guid is found by its TVDb or IMDb ID, as Kometa's ``get_item`` does.
Answers are kept in ``<data dir>/tmdb-details.json`` for 30 days, like Kometa's own cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

API = "https://api.themoviedb.org/3"
CACHE = "tmdb-details.json"
MAX_AGE = 30 * 24 * 3600
TIMEOUT = 10.0
PARALLEL = 8


class TMDbUnavailable(Exception):
    pass


class TMDbDetails:
    def __init__(self, http: httpx.AsyncClient, apikey: str, data_dir: Path):
        self.http = http
        self.apikey = apikey
        self.path = data_dir / CACHE
        self._cache: dict[str, Any] | None = None
        self._limit = asyncio.Semaphore(PARALLEL)

    def _load(self) -> dict[str, Any]:
        if self._cache is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._cache = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def save(self) -> None:
        if self._cache is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as error:
            log.warning("Couldn't keep TMDb's answers: %s", error)

    async def _get(self, key: str, path: str, params: dict | None = None) -> dict | None:
        """TMDb's answer for ``path`` (None for a 404), from the cache while it's fresh."""
        cache = self._load()
        hit = cache.get(key)
        if isinstance(hit, dict) and time.time() - float(hit.get("at", 0)) < MAX_AGE:
            return hit.get("data")
        async with self._limit:
            try:
                response = await self.http.get(f"{API}{path}", params={"api_key": self.apikey, **(params or {})}, timeout=TIMEOUT)
            except httpx.HTTPError as error:
                raise TMDbUnavailable(f"Can't reach TMDb: {error}") from None
        if response.status_code == 404:
            data = None
        elif response.status_code != 200:
            raise TMDbUnavailable(f"TMDb answered HTTP {response.status_code}")
        else:
            data = response.json()
        cache[key] = {"at": time.time(), "data": data}
        return data

    async def tmdb_id(self, ids: dict[str, str], is_movie: bool) -> str | None:
        """The title's TMDb ID: its own guid, else found by TVDb ID (shows), else by IMDb ID of the same kind."""
        if ids.get("tmdb"):
            return ids["tmdb"]
        for source, external in (("tvdb", "tvdb_id"), ("imdb", "imdb_id")):
            value = ids.get(source)
            if not value or (source == "tvdb" and is_movie):
                continue
            found = await self._get(f"find:{source}:{value}", f"/find/{value}", {"external_source": external}) or {}
            results = found.get("movie_results" if is_movie else "tv_results") or []
            if results and results[0].get("id"):
                return str(results[0]["id"])
        return None

    async def details(self, tmdb_id: str, is_movie: bool) -> dict:
        """The fields Kometa reads: ``collection`` (id, name) for a movie, ``countries`` for a show, ``language`` for either."""
        kind = "movie" if is_movie else "tv"
        data = await self._get(f"{kind}:{tmdb_id}", f"/{kind}/{tmdb_id}") or {}
        collection = data.get("belongs_to_collection") or None
        return {
            "collection": (str(collection["id"]), str(collection["name"])) if collection and collection.get("id") and collection.get("name") else None,
            "countries": [str(c).lower() for c in data.get("origin_country") or []],
            "language": str(data["original_language"]).lower() if data.get("original_language") else None,
        }

    async def library(self, items: list[tuple[str, dict[str, str]]], is_movie: bool) -> list[tuple[str, dict]]:
        """(ratingKey, details) for every title TMDb knows, in the library's order."""

        async def one(rating_key: str, ids: dict[str, str]) -> tuple[str, dict] | None:
            tmdb_id = await self.tmdb_id(ids, is_movie)
            return (rating_key, await self.details(tmdb_id, is_movie)) if tmdb_id else None

        try:
            found = await asyncio.gather(*(one(key, ids) for key, ids in items))
        finally:
            self.save()
        return [item for item in found if item is not None]


class LibraryLookup:
    """Each library's TMDb details, read once per count; None when there's no TMDb key or TMDb can't be reached."""

    def __init__(self, details: TMDbDetails | None, plex, languages: dict[str, str] | None = None, countries: dict[str, str] | None = None):
        self.details = details
        self.plex = plex
        self.languages = languages
        self.countries = countries
        self._memo: dict[str, list[tuple[str, dict]] | None] = {}

    async def items(self, library_key: str, library_type: str) -> list[tuple[str, dict]] | None:
        if library_key not in self._memo:
            if self.details is None:
                self._memo[library_key] = None
            else:
                try:
                    ids = await self.plex.all_ids(library_key, library_type)
                    self._memo[library_key] = await self.details.library(ids, library_type == "movie")
                except TMDbUnavailable as error:
                    log.warning("TMDb details for library %s: %s", library_key, error)
                    self._memo[library_key] = None
        return self._memo[library_key]
