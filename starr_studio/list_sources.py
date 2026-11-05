"""Collections from a list: which of Kometa's list builders Studio offers, links to them, and their preview.

A list collection is a builder collection whose ``definition.source`` is ``{"kind": "list", "builder", "value",
"label"}``. Studio writes it as that Kometa builder (``tmdb_collection: 1234``, ``imdb_chart: top_movies``, …) with
``sync_mode: sync``, so the collection follows the list. Kometa's own ``radarr_add_missing``/``sonarr_add_missing``
stay off: only Studio requests missing titles.

The preview splits a list into what the library has and what it's missing, before anything is saved. Studio reads
TMDb lists and charts, and MDBList lists, itself; IMDb and Letterboxd it leaves to Kometa (they need scraping), so
those preview after their first build. Trakt is gone from Kometa (2.5), so Studio doesn't offer it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from .plex_library import PlexItem

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w342"
MDBLIST_API = "https://api.mdblist.com"
TIMEOUT = 15.0
CACHE_SECONDS = 600  # charts move; a preview reads them again after ten minutes
MAX_COUNT = 500  # titles from a TMDb chart: 25 pages of 20
TMDB_PAGE = 20

Input = Literal["search", "link", "choice", "count"]
Group = Literal["TMDb", "IMDb", "Letterboxd", "MDBList"]

# Kometa's IMDb charts (modules/imdb.py ``charts``/``chart_urls``), the ones that fit each library type.
IMDB_CHARTS = {
    "movie": [
        ("top_movies", "Top 250 Movies", "chart/top"),
        ("popular_movies", "Most Popular Movies", "chart/moviemeter"),
        ("box_office", "Box Office", "chart/boxoffice"),
        ("top_english", "Top Rated English Movies", "chart/top-english-movies"),
        ("lowest_rated", "Lowest Rated Movies", "chart/bottom"),
        ("top_indian", "Top Rated Indian Movies", "india/top-rated-indian-movies"),
    ],
    "show": [
        ("top_shows", "Top 250 TV Shows", "chart/toptv"),
        ("popular_shows", "Most Popular TV Shows", "chart/tvmeter"),
    ],
}

# TMDb chart builders that take a count, and the TMDb path each reads, per library type.
TMDB_CHARTS: dict[str, dict[str, str]] = {
    "tmdb_popular": {"movie": "/movie/popular", "show": "/tv/popular"},
    "tmdb_top_rated": {"movie": "/movie/top_rated", "show": "/tv/top_rated"},
    "tmdb_trending_weekly": {"movie": "/trending/movie/week", "show": "/trending/tv/week"},
    "tmdb_trending_daily": {"movie": "/trending/movie/day", "show": "/trending/tv/day"},
    "tmdb_now_playing": {"movie": "/movie/now_playing"},
    "tmdb_upcoming": {"movie": "/movie/upcoming"},
    "tmdb_airing_today": {"show": "/tv/airing_today"},
    "tmdb_on_the_air": {"show": "/tv/on_the_air"},
}
SERVICE_NAMES = {"mdblist": "MDBList", "tmdb": "TMDb"}
INT_BUILDERS = {"tmdb_collection", "tmdb_list", *TMDB_CHARTS}


class SourceError(ValueError):
    """The source can't be used as given; the message says why, plainly."""


class NotPreviewable(Exception):
    """Studio can't read this list itself; the message says when it can be seen."""


@dataclass(frozen=True)
class Kind:
    builder: str
    label: str
    group: Group
    input: Input
    types: tuple[str, ...] = ("movie", "show")
    placeholder: str | None = None
    previewable: bool = False
    needs: str | None = None  # a connection in config.yml: "mdblist"


KINDS: list[Kind] = [
    Kind("tmdb_collection", "TMDb collection (franchise)", "TMDb", "search", ("movie",), "Search TMDb collections, e.g. Dune", True),
    Kind("tmdb_list", "TMDb list", "TMDb", "link", placeholder="https://www.themoviedb.org/list/…", previewable=True),
    Kind("tmdb_popular", "TMDb popular", "TMDb", "count", previewable=True),
    Kind("tmdb_top_rated", "TMDb top rated", "TMDb", "count", previewable=True),
    Kind("tmdb_trending_weekly", "TMDb trending this week", "TMDb", "count", previewable=True),
    Kind("tmdb_trending_daily", "TMDb trending today", "TMDb", "count", previewable=True),
    Kind("tmdb_now_playing", "TMDb now playing", "TMDb", "count", ("movie",), previewable=True),
    Kind("tmdb_upcoming", "TMDb upcoming", "TMDb", "count", ("movie",), previewable=True),
    Kind("tmdb_airing_today", "TMDb airing today", "TMDb", "count", ("show",), previewable=True),
    Kind("tmdb_on_the_air", "TMDb on the air", "TMDb", "count", ("show",), previewable=True),
    Kind("imdb_chart", "IMDb chart", "IMDb", "choice"),
    Kind("imdb_list", "IMDb list", "IMDb", "link", placeholder="https://www.imdb.com/list/ls…/"),
    Kind("letterboxd_list", "Letterboxd list", "Letterboxd", "link", ("movie",), "https://letterboxd.com/<user>/list/<name>/"),
    Kind("mdblist_list", "MDBList list", "MDBList", "link", placeholder="https://mdblist.com/lists/<user>/<name>", previewable=True, needs="mdblist"),
]
BY_BUILDER = {kind.builder: kind for kind in KINDS}
NOT_BUILT_YET = "Studio can show what's in this list once it has been built."


def kind_for(builder: str, library_type: str) -> Kind:
    kind = BY_BUILDER.get(builder)
    if kind is None:
        raise SourceError(f"Studio doesn't make collections from {builder!r}")
    if library_type not in kind.types:
        what = "movies" if kind.types == ("movie",) else "shows"
        raise SourceError(f"A {kind.label} holds {what}, so it can't be a collection in a {'TV' if library_type == 'show' else 'movie'} library")
    return kind


def choices(builder: str, library_type: str) -> list[tuple[str, str]] | None:
    if builder == "imdb_chart":
        return [(key, label) for key, label, _url in IMDB_CHARTS.get(library_type, [])]
    return None


def catalogue(library_type: str, connected: set[str]) -> list[dict]:
    """The source kinds for a library, as the builder lists them."""
    out = []
    for kind in KINDS:
        if library_type not in kind.types:
            continue
        missing = kind.needs is not None and kind.needs not in connected
        out.append(
            {
                "builder": kind.builder,
                "label": kind.label,
                "group": kind.group,
                "input": kind.input,
                "placeholder": kind.placeholder,
                "choices": [{"value": v, "label": label} for v, label in choices(kind.builder, library_type) or []] or None,
                "previewable": kind.previewable,
                "available": not missing,
                "why": "Connect MDBList in Settings → Connect first" if missing and kind.needs == "mdblist" else None,
            }
        )
    return out


# --- Values and links ------------------------------------------------------------------------------


def _slug_label(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().capitalize() or slug


def normalise(builder: str, raw: str, library_type: str) -> tuple[str, str | None]:
    """The value Kometa takes for ``builder`` from what the user gave (an id, a count or a link), and a label if it carries one."""
    kind = kind_for(builder, library_type)
    text = str(raw or "").strip()
    if not text:
        raise SourceError(f"Give the {kind.label} to use")
    if builder in TMDB_CHARTS:
        if not text.isdigit() or not 1 <= int(text) <= MAX_COUNT:
            raise SourceError(f"How many titles: a number from 1 to {MAX_COUNT}")
        return str(int(text)), None
    if builder == "imdb_chart":
        found = dict(choices(builder, library_type) or [])
        if text not in found:
            raise SourceError(f"IMDb has no chart called {text!r} for this library")
        return text, f"IMDb {found[text]}"
    if text.isdigit() and builder in ("tmdb_collection", "tmdb_list"):
        return text, None
    resolved = from_link(text, library_type)
    if resolved[0] != builder:
        raise SourceError(f"That's a link to a {BY_BUILDER[resolved[0]].label}, not a {kind.label}")
    return resolved[1], resolved[2]


def from_link(url: str, library_type: str) -> tuple[str, str, str | None]:
    """(builder, value, label) for a pasted link, or SourceError saying what Studio takes."""
    text = url.strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.rstrip("/")
    builder: str | None = None
    value = label = None
    if host == "themoviedb.org":
        if match := re.match(r"^/collection/(\d+)", path):
            builder, value = "tmdb_collection", match.group(1)
        elif match := re.match(r"^/list/(\d+)", path):
            builder, value = "tmdb_list", match.group(1)
    elif host == "imdb.com":
        if match := re.search(r"/list/(ls\d+)", path):
            builder, value, label = "imdb_list", f"https://www.imdb.com/list/{match.group(1)}/", f"IMDb list {match.group(1)}"
        else:
            for types, charts in IMDB_CHARTS.items():
                for key, name, chart_path in charts:
                    if path.lstrip("/") == chart_path:
                        if types != library_type:
                            raise SourceError(f"IMDb's {name} chart holds {'movies' if types == 'movie' else 'shows'}, and this is a {'TV' if library_type == 'show' else 'movie'} library")
                        builder, value, label = "imdb_chart", key, f"IMDb {name}"
    elif host == "letterboxd.com":
        if match := re.match(r"^/([^/]+)/list/([^/]+)", path):
            builder = "letterboxd_list"
            value, label = f"https://letterboxd.com/{match.group(1)}/list/{match.group(2)}/", _slug_label(match.group(2))
    elif host == "mdblist.com":
        if match := re.match(r"^/lists/(.+)$", path):
            builder = "mdblist_list"
            value, label = f"https://mdblist.com/lists/{match.group(1)}", _slug_label(match.group(1).split("/")[-1])
    elif host.endswith("trakt.tv"):
        raise SourceError("Kometa no longer reads Trakt lists. MDBList can mirror a Trakt list: paste the MDBList link instead.")
    if builder is None or value is None:
        raise SourceError("Studio doesn't recognise this link. It takes TMDb collections and lists, IMDb lists and charts, Letterboxd lists and MDBList lists.")
    kind_for(builder, library_type)  # refuses a movies-only source in a TV library
    return builder, value, label


def kometa_value(builder: str, value: str) -> Any:
    """The value as Kometa's YAML wants it: ids and counts are numbers."""
    return int(value) if builder in INT_BUILDERS and str(value).isdigit() else value


# --- Reading lists -----------------------------------------------------------------------------------


@dataclass
class ListItem:
    tmdb: str | None
    imdb: str | None
    title: str
    year: int | None
    poster: str | None


@dataclass
class ListPreview:
    previewable: bool
    why: str | None = None
    total: int | None = None
    in_library: list[PlexItem] = field(default_factory=list)
    missing: list[ListItem] = field(default_factory=list)


def _year(value: Any) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def _tmdb_item(raw: dict) -> ListItem | None:
    if not raw.get("id"):
        return None
    poster = raw.get("poster_path")
    return ListItem(
        tmdb=str(raw["id"]),
        imdb=None,
        title=str(raw.get("title") or raw.get("name") or ""),
        year=_year(raw.get("release_date") or raw.get("first_air_date")),
        poster=f"{TMDB_IMAGE}{poster}" if poster else None,
    )


class Lists:
    """Reads lists from TMDb and MDBList with a short in-memory cache (ten minutes)."""

    def __init__(self, http: httpx.AsyncClient, tmdb_key: str | None, mdblist_key: str | None, cache: dict | None = None):
        self.http = http
        self.tmdb_key = tmdb_key
        self.mdblist_key = mdblist_key
        self._cache: dict[str, tuple[float, Any]] = cache if cache is not None else {}  # the app keeps one across requests

    async def _get(self, url: str, params: dict, service: str) -> Any:
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k not in ("api_key", "apikey"))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            response = await self.http.get(url, params=params, timeout=TIMEOUT)
        except httpx.HTTPError as error:
            raise SourceError(f"Can't reach {service}: {error}") from None
        if response.status_code == 404:
            raise SourceError(f"{service} has no such list")
        if response.status_code in (401, 403):
            raise SourceError(f"{service} refused Studio's API key")
        if response.status_code == 429:
            raise SourceError(f"{service}'s limit for today is used up")
        if response.status_code != 200:
            raise SourceError(f"{service} answered HTTP {response.status_code}")
        data = response.json()
        self._cache[key] = (time.monotonic(), data)
        return data

    async def _tmdb(self, path: str, params: dict | None = None) -> dict:
        if not self.tmdb_key:
            raise SourceError("Studio needs Kometa's TMDb key, in Settings → Connect")
        data = await self._get(f"{TMDB_API}{path}", {"api_key": self.tmdb_key, **(params or {})}, "TMDb")
        return data if isinstance(data, dict) else {}

    async def label(self, builder: str, value: str) -> str | None:
        """The list's own name, where TMDb has one."""
        if builder == "tmdb_collection":
            return str((await self._tmdb(f"/collection/{value}")).get("name") or "") or None
        if builder == "tmdb_list":
            return str((await self._tmdb(f"/list/{value}")).get("name") or "") or None
        return None

    async def search_collections(self, query: str) -> list[dict]:
        data = await self._tmdb("/search/collection", {"query": query})
        out = []
        for raw in data.get("results") or []:
            if raw.get("id") and raw.get("name"):
                poster = raw.get("poster_path")
                out.append({"value": str(raw["id"]), "title": str(raw["name"]), "year": None, "poster": f"{TMDB_IMAGE}{poster}" if poster else None})
        return out

    async def items(self, builder: str, value: str, library_type: str) -> list[ListItem]:
        """The list's titles in its own order. NotPreviewable for lists only Kometa reads."""
        kind = kind_for(builder, library_type)
        if not kind.previewable:
            raise NotPreviewable(NOT_BUILT_YET)
        if builder == "tmdb_collection":
            parts = (await self._tmdb(f"/collection/{value}")).get("parts") or []
            parts = sorted(parts, key=lambda p: str(p.get("release_date") or "9999"))  # Kometa's order is TMDb's; release order reads better
            return [item for item in map(_tmdb_item, parts) if item]
        if builder == "tmdb_list":
            wanted = "movie" if library_type == "movie" else "tv"
            items: list[ListItem] = []
            page, pages = 1, 1
            while page <= pages and page <= 25:
                data = await self._tmdb(f"/list/{value}", {"page": page})
                pages = int(data.get("total_pages") or 1)
                items += [i for raw in data.get("items") or [] if raw.get("media_type", wanted) == wanted and (i := _tmdb_item(raw))]
                page += 1
            return items
        if builder in TMDB_CHARTS:
            count = int(value)
            path = TMDB_CHARTS[builder][library_type]
            items = []
            for page in range(1, (count + TMDB_PAGE - 1) // TMDB_PAGE + 1):
                data = await self._tmdb(path, {"page": page})
                items += [i for raw in data.get("results") or [] if (i := _tmdb_item(raw))]
                if page >= int(data.get("total_pages") or page):
                    break
            return items[:count]
        if builder == "mdblist_list":
            return await self._mdblist(value, library_type)
        raise NotPreviewable(NOT_BUILT_YET)

    async def _mdblist(self, url: str, library_type: str) -> list[ListItem]:
        # As Kometa reads it (modules/mdblist.py): /lists/<user>/<slug>/items/<movie|show>, the TMDb id in id or tmdbid.
        if not self.mdblist_key:
            raise SourceError("Connect MDBList in Settings → Connect first")
        list_path = url.split("/lists/", 1)[-1].strip("/")
        media = "movie" if library_type == "movie" else "show"
        items: list[ListItem] = []
        offset = 0
        while True:
            data = await self._get(f"{MDBLIST_API}/lists/{list_path}/items/{media}", {"apikey": self.mdblist_key, "limit": 1000, "offset": offset}, "MDBList")
            batch = data if isinstance(data, list) else (data.get("movies" if media == "movie" else "shows") or data.get("items") or []) if isinstance(data, dict) else []
            for raw in batch:
                tmdb = raw.get("id") or raw.get("tmdbid")
                if not tmdb and not raw.get("imdb_id"):
                    continue
                items.append(ListItem(str(tmdb) if tmdb else None, raw.get("imdb_id"), str(raw.get("title") or ""), _year(raw.get("release_year")), None))
            if len(batch) < 1000 or offset > 10000:
                return items
            offset += len(batch)


def split(items: list[ListItem], library: list[PlexItem]) -> tuple[list[PlexItem], list[ListItem]]:
    """The list's titles the library has (as Plex items, in list order) and the ones it's missing."""
    by_tmdb = {i.ids["tmdb"]: i for i in library if i.ids.get("tmdb")}
    by_imdb = {i.ids["imdb"]: i for i in library if i.ids.get("imdb")}
    have: list[PlexItem] = []
    missing: list[ListItem] = []
    seen: set[str] = set()
    for item in items:
        found = (by_tmdb.get(item.tmdb) if item.tmdb else None) or (by_imdb.get(item.imdb) if item.imdb else None)
        if found is not None:
            if found.rating_key not in seen:
                seen.add(found.rating_key)
                have.append(found)
        else:
            missing.append(item)
    return have, missing


def missing_key(item: ListItem, library_type: str) -> str:
    """How ``wanted`` and requests name a missing title: ``tmdb-movie:603`` or ``tmdb-show:1399`` (``imdb:tt…`` without a TMDb id)."""
    if item.tmdb:
        return f"tmdb-{'movie' if library_type == 'movie' else 'show'}:{item.tmdb}"
    return f"imdb:{item.imdb}"
