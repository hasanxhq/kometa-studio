"""TMDb's English language names, which Kometa uses to name audio and subtitle language collections.

Kometa titles an ``audio_language`` or ``subtitle_language`` collection with TMDb's ``english_name`` for the
Plex tag's key (tmdbapis' ``_iso_639_1``, from ``/configuration/languages``), and only falls back to Plex's own
title when TMDb doesn't know the key. Plex's titles are in the language itself ("Français"), so Studio needs
TMDb's list to know the names Kometa will give them. The list is kept in ``<data dir>/tmdb-languages.json``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from .config_sections import read_section

log = logging.getLogger(__name__)

URL = "https://api.themoviedb.org/3/configuration/languages"
CACHE = "tmdb-languages.json"
COUNTRY_URL = "https://api.themoviedb.org/3/configuration/countries"
COUNTRY_CACHE = "tmdb-countries.json"
MAX_AGE = 30 * 24 * 3600  # TMDb's list hardly changes
TIMEOUT = 10.0


def _load(path: Path) -> tuple[float, dict[str, str]] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = {str(k): str(v) for k, v in data["names"].items()}
        return float(data["fetched_at"]), names
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


async def _fetch(http: httpx.AsyncClient, apikey: str, url: str = URL, code_field: str = "iso_639_1") -> dict[str, str]:
    response = await http.get(url, params={"api_key": apikey}, timeout=TIMEOUT)
    response.raise_for_status()
    names: dict[str, str] = {}
    for entry in response.json():
        code, name = entry.get(code_field), entry.get("english_name")
        if code and name:
            names[str(code).lower()] = str(name)
    if not names:
        raise ValueError(f"TMDb sent nothing from {url}")
    return names


async def english_names(http: httpx.AsyncClient, config: Path | None, data_dir: Path) -> dict[str, str] | None:
    """ISO 639-1 code (lower case) → TMDb's English name; a stale copy if TMDb can't be reached; None if neither."""
    return await _names(http, config, data_dir, CACHE, URL, "iso_639_1")


async def english_country_names(http: httpx.AsyncClient, config: Path | None, data_dir: Path) -> dict[str, str] | None:
    """ISO 3166-1 code (lower case) → TMDb's English name, as tmdbapis names a show's origin countries for Kometa."""
    return await _names(http, config, data_dir, COUNTRY_CACHE, COUNTRY_URL, "iso_3166_1")


async def _names(http: httpx.AsyncClient, config: Path | None, data_dir: Path, cache: str, url: str, code_field: str) -> dict[str, str] | None:
    path = data_dir / cache
    cached = _load(path)
    if cached is not None and time.time() - cached[0] < MAX_AGE:
        return cached[1]
    apikey = (read_section(config, "tmdb") or {}).get("apikey")
    if apikey:
        try:
            names = await _fetch(http, str(apikey), url, code_field)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            log.warning("Couldn't get TMDb's names from %s: %s", url, error)
        else:
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"fetched_at": time.time(), "names": names}), encoding="utf-8")
                tmp.replace(path)
            except OSError as error:
                log.warning("Couldn't keep TMDb's names from %s: %s", url, error)
            return names
    return cached[1] if cached is not None else None


def kometa_title(names: dict[str, str], key: str, plex_title: str) -> str:
    """The name Kometa gives a language key: TMDb's, looked up by the key as Plex has it (``en-US`` isn't found)."""
    return names.get(key, plex_title)
