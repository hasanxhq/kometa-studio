"""Requests service: send missing media to Radarr/Sonarr or Seerr, and track them.

Seerr's connection is Kometa's own: config.yml's ``seerr:`` (url, apikey), which Settings → Requests
writes. A seedbox's proxy login in front of it (HTTP Basic) is Studio's alone, kept encrypted, since
Kometa can't send one. Studio does the requesting itself (cap, dedupe, tracking, cancel); it never
writes Kometa's ``seerr_add_missing``, which would request everything missing on every run.
"""

import asyncio
import contextlib
import hashlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from . import arr, tmdb_details
from .arr import ArrProblem, Connection, Kind
from .config_sections import read_section, save_section
from .config_write import ConfigWriter, SaveRefused
from .crypto import SecretBox
from .db import delete_setting, get_setting, set_setting
from .kometa_config import read_plex
from .plex_library import PlexNotFound, PlexServer, PlexUnavailable
from .scheduler import utc_text
from .services import mask

log = logging.getLogger(__name__)

REQUESTS_SETTINGS = "requests.settings"
# Before Seerr's connection lived in config.yml: url, encrypted key and proxy login. Carried into config.yml.
REQUESTS_SEERR = "requests.seerr"
SEERR_LOGIN = "requests.seerr_login"  # the proxy login in front of Seerr, if any (url and key are in config.yml's seerr:)
SEERR_CARRY = "requests.seerr_carry"  # why the old connection couldn't move into config.yml: {"error", "config": its hash}
POLL_EVERY = 300.0  # 5 minutes
TIMEOUT = 10.0


class RequestsDisabled(Exception):
    """Requests are globally disabled."""


class RadarrRequestSettings(BaseModel):
    quality_profile: str | None = None
    root_folder: str | None = None
    minimum_availability: Literal["announced", "inCinemas", "released"] = "released"
    search: bool = True


class SonarrRequestSettings(BaseModel):
    quality_profile: str | None = None
    root_folder: str | None = None
    monitor: Literal["all", "future", "missing", "existing", "firstSeason", "latestSeason", "pilot"] = "all"
    search: bool = True
    series_type: Literal["standard", "anime", "daily"] = "standard"


class RequestSettings(BaseModel):
    enabled: bool = False
    via: Literal["auto", "arr", "seerr"] = "auto"
    radarr: RadarrRequestSettings = Field(default_factory=RadarrRequestSettings)
    sonarr: SonarrRequestSettings = Field(default_factory=SonarrRequestSettings)
    daily_cap: int | None = None
    confirm_over: int = 25


class Item(BaseModel):
    item: str
    title: str | None = None
    year: int | None = None


class RequestItemResult(BaseModel):
    item: str
    status: str
    error: str | None = None


class RequestOutcome(BaseModel):
    requested: int = 0
    exists: int = 0
    failed: int = 0
    capped: int = 0
    skipped: int = 0
    items: list[RequestItemResult] = Field(default_factory=list)


class SeerrConnectionIn(BaseModel):
    url: str = Field(max_length=500)
    api_key: str | None = Field(default=None, max_length=200)  # None: keep the key in config.yml
    username: str | None = Field(default=None, max_length=200)  # for a proxy in front of Seerr; empty: none
    password: str | None = Field(default=None, max_length=500)  # None: keep the saved one


@dataclass
class SeerrConnection:
    url: str
    api_key: str
    login: tuple[str, str] | None = None  # for a proxy in front of Seerr (HTTP Basic), as on a seedbox


def load_settings(db: sqlite3.Connection) -> RequestSettings:
    raw = get_setting(db, REQUESTS_SETTINGS) or {}
    return RequestSettings.model_validate(raw)


def save_settings(db: sqlite3.Connection, settings: RequestSettings) -> None:
    set_setting(db, REQUESTS_SETTINGS, settings.model_dump())


def kometa_seerr(config: Path | None) -> tuple[str | None, str | None]:
    """The url and apikey in config.yml's seerr: section, if there are both."""
    section = read_section(config, "seerr") or {}
    url, key = section.get("url"), section.get("apikey")
    return (str(url) if url else None, str(key) if key else None)


def _login(raw: dict, box: SecretBox) -> tuple[str, str] | None:
    if not raw.get("username"):
        return None
    return raw["username"], (box.decrypt(raw["password"]) or "") if raw.get("password") else ""


def seerr_login(db: sqlite3.Connection, box: SecretBox) -> tuple[str, str] | None:
    """Studio's own proxy login in front of Seerr: Kometa can't send one."""
    saved = get_setting(db, SEERR_LOGIN)
    if saved is not None:
        return _login(saved, box)
    return _login(get_setting(db, REQUESTS_SEERR) or {}, box)  # not carried over yet


def save_seerr_login(db: sqlite3.Connection, box: SecretBox, login: tuple[str, str] | None) -> None:
    set_setting(db, SEERR_LOGIN, {"username": login[0], "password": box.encrypt(login[1]) if login[1] else None} if login else {})


def legacy_seerr(db: sqlite3.Connection, box: SecretBox) -> SeerrConnection | None:
    """A connection saved before it lived in config.yml (url, key and login all in SQLite)."""
    raw = get_setting(db, REQUESTS_SEERR)
    if not raw or not raw.get("url") or not raw.get("api_key"):
        return None
    api_key = box.decrypt(raw["api_key"])
    if not api_key:
        return None
    return SeerrConnection(url=raw["url"], api_key=api_key, login=_login(raw, box))


def load_seerr_connection(db: sqlite3.Connection, box: SecretBox, config: Path | None) -> SeerrConnection | None:
    """config.yml's seerr: with Studio's proxy login; until that's been carried over, the one saved in SQLite."""
    url, key = kometa_seerr(config)
    if url and key:
        return SeerrConnection(url=url, api_key=key, login=seerr_login(db, box))
    return legacy_seerr(db, box)


def seerr_json(db: sqlite3.Connection, box: SecretBox, config: Path | None) -> dict | None:
    conn = load_seerr_connection(db, box, config)
    if conn is None:
        url = kometa_seerr(config)[0] or (get_setting(db, REQUESTS_SEERR) or {}).get("url")
        if not url:
            return None
        login = seerr_login(db, box)
        return {"url": url, "api_key": None, "username": login[0] if login else None, "has_password": bool(login and login[1])}
    return {
        "url": conn.url,
        "api_key": mask(conn.api_key),  # the key and password never leave the server
        "username": conn.login[0] if conn.login else None,
        "has_password": bool(conn.login and conn.login[1]),
    }


def _config_hash(config: Path | None) -> str:
    try:
        return hashlib.sha256(config.read_bytes()).hexdigest() if config is not None else "missing"
    except OSError:
        return "missing"


def _refusal(refused: SaveRefused) -> str:
    errors = refused.validation.errors if refused.validation else []
    return f"{refused.message} {errors[0]}" if errors else refused.message


async def carry_over_seerr(db: sqlite3.Connection, box: SecretBox, config: Path | None, writer: ConfigWriter | None) -> bool:
    """Move a connection saved before Seerr lived in config.yml into config.yml's seerr:, once. True once done.

    The proxy login stays Studio's. The old setting is deleted only after the save went through; until
    then Studio keeps using it, and ``SEERR_CARRY`` says why for Health. A refused save would be refused
    again, so it's only tried again once config.yml has changed.
    """
    raw = get_setting(db, REQUESTS_SEERR)
    if not raw:
        return True
    url, key = kometa_seerr(config)
    legacy = legacy_seerr(db, box)
    if not (url and key) and legacy is not None:
        digest = _config_hash(config)
        last = get_setting(db, SEERR_CARRY) or {}
        if last.get("config") == digest:
            return False
        if writer is None or digest == "missing":
            set_setting(db, SEERR_CARRY, {"error": "Kometa's config.yml doesn't exist yet.", "config": digest})
            return False
        try:
            await save_section(writer, "seerr", {"url": legacy.url, "apikey": legacy.api_key}, "Moved Seerr's connection into config.yml")
        except SaveRefused as refused:
            set_setting(db, SEERR_CARRY, {"error": _refusal(refused), "config": _config_hash(config)})
            log.warning("Seerr's connection stays in Studio's database for now: %s", _refusal(refused))
            return False
        log.info("Moved Seerr's connection into config.yml's seerr:")
    elif legacy is None and not (url and key):
        return False  # a key Studio can't decrypt: nothing to carry; Settings → Requests asks for it again
    # config.yml has it now (or already had its own, which wins): only the proxy login is left to keep.
    if get_setting(db, SEERR_LOGIN) is None:
        set_setting(db, SEERR_LOGIN, {"username": raw.get("username"), "password": raw.get("password")} if raw.get("username") else {})
    delete_setting(db, REQUESTS_SEERR)
    delete_setting(db, SEERR_CARRY)
    return True


async def probe_seerr_connection(http: httpx.AsyncClient, conn: SeerrConnection) -> dict:
    url = conn.url.rstrip("/")
    headers = {"X-Api-Key": conn.api_key, "Accept": "application/json"}
    auth = conn.login or httpx.USE_CLIENT_DEFAULT

    # 1. status
    try:
        res = await http.get(f"{url}/api/v1/status", timeout=TIMEOUT, auth=auth)
    except httpx.TimeoutException:
        raise ArrProblem(f"No answer within {TIMEOUT:g} s") from None
    except httpx.HTTPError as error:
        raise ArrProblem(f"Can't connect: {error}") from None
    if res.status_code == 401 and res.headers.get("www-authenticate", "").lower().startswith("basic"):
        raise ArrProblem("The proxy in front of it wants a username and password" + (" (these were refused)" if conn.login else ""))
    if res.status_code != 200:
        raise ArrProblem(f"It answered HTTP {res.status_code}")
    try:
        status_data = res.json()
    except ValueError:
        raise ArrProblem("That address answered, but not like Seerr") from None
    version = str(status_data.get("version") or "")

    # 2. auth/me to verify API key
    try:
        auth_res = await http.get(f"{url}/api/v1/auth/me", headers=headers, timeout=TIMEOUT, auth=auth)
    except httpx.TimeoutException:
        raise ArrProblem(f"No answer within {TIMEOUT:g} s") from None
    except httpx.HTTPError as error:
        raise ArrProblem(f"Can't connect: {error}") from None
    if auth_res.status_code in (401, 403):
        raise ArrProblem("The API key was rejected")
    if auth_res.status_code != 200:
        raise ArrProblem(f"Auth check answered HTTP {auth_res.status_code}")

    # 3. the name it goes by (Seerr's own setting, so it's only reported, never checked)
    title = None
    try:
        pub_res = await http.get(f"{url}/api/v1/settings/public", timeout=5.0, auth=auth)
        if pub_res.status_code == 200:
            title = str(pub_res.json().get("applicationTitle") or "") or None
    except (httpx.HTTPError, ValueError, AttributeError):
        pass

    return {"title": title, "version": version}


test_seerr_connection = probe_seerr_connection


def _profile_id(profiles: list, name: str | None) -> int | None:
    if not name:
        return None
    for p in profiles:
        if isinstance(p, dict) and p.get("name") == name:
            return p.get("id")
    return None


class RequestService:
    def __init__(
        self,
        db: sqlite3.Connection,
        http: httpx.AsyncClient,
        box: SecretBox,
        config: Path | None,
        data_dir: Path | None = None,
        writer: ConfigWriter | None = None,
    ):
        self.db = db
        self.http = http
        self.box = box
        self.config = config
        self.data_dir = data_dir
        self.writer = writer
        self._task: asyncio.Task | None = None
        self._carrying = asyncio.Lock()
        # Called after each check; the app uses it to rebuild collections whose requested titles reached Plex.
        self.after_labelling: Callable[[], object] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="requests-refresh")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            # At start-up, then on every check while the old setting is still there (only after config.yml changed).
            try:
                await self.carry_over()
            except Exception:
                log.exception("Moving Seerr's connection into config.yml failed")
            try:
                if self.load_settings().enabled:
                    await self.check(datetime.now(UTC))
            except Exception:
                log.exception("Refreshing requests failed")
            await asyncio.sleep(POLL_EVERY)

    async def check(self, now: datetime) -> dict[str, int]:
        """Bring statuses up to date from the apps, label what reached Plex, then let ``after_labelling`` act on it."""
        counts = await self.refresh(now)
        server = self.plex_server()
        if server is not None:
            await self.label_imported(server, now)
        if self.after_labelling is not None:
            self.after_labelling()
        return counts

    def load_settings(self) -> RequestSettings:
        return load_settings(self.db)

    def save_settings(self, settings: RequestSettings) -> None:
        save_settings(self.db, settings)

    def load_seerr_connection(self) -> SeerrConnection | None:
        return load_seerr_connection(self.db, self.box, self.config)

    async def carry_over(self) -> bool:
        async with self._carrying:
            return await carry_over_seerr(self.db, self.box, self.config, self.writer)

    def seerr_json(self) -> dict | None:
        return seerr_json(self.db, self.box, self.config)

    def seerr_from_input(self, body: SeerrConnectionIn) -> SeerrConnection:
        saved = self.load_seerr_connection()
        key = (body.api_key or "").strip() or (saved.api_key if saved else "")
        url = body.url.strip()
        if not url or not key:
            raise ArrProblem("Enter Seerr's URL and API key")
        username = (body.username or "").strip() or None
        login = None
        if username:
            password = body.password if body.password is not None else (saved.login[1] if saved and saved.login else "")
            login = (username, password or "")
        return SeerrConnection(url=url, api_key=key, login=login)

    async def test_seerr(self, conn: SeerrConnection) -> dict:
        return await test_seerr_connection(self.http, conn)

    def connected(self) -> dict[str, bool]:
        radarr = arr.connection(self.db, self.box, self.config, "radarr") is not None
        sonarr = arr.connection(self.db, self.box, self.config, "sonarr") is not None
        seerr = self.load_seerr_connection() is not None
        return {
            "radarr": radarr,
            "sonarr": sonarr,
            "seerr": seerr,
        }

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, count(*) FROM requests GROUP BY status").fetchall()
        by_status = {r[0]: r[1] for r in rows}
        return {
            "requested": by_status.get("requested", 0),
            "downloading": by_status.get("downloading", 0),
            "imported": by_status.get("imported", 0),
            "failed": by_status.get("failed", 0),
            "cancelled": by_status.get("cancelled", 0),
            "exists": by_status.get("exists", 0),
        }

    def plex_server(self) -> PlexServer | None:
        try:
            current = read_plex(self.config) if self.config else None
            if current is None or not current.url or not current.token:
                return None
            return PlexServer(self.http, current.url, current.token)
        except Exception:
            return None

    def _tmdb_client(self) -> tmdb_details.TMDbDetails | None:
        apikey = (read_section(self.config, "tmdb") or {}).get("apikey")
        if not apikey:
            return None
        data_dir = self.data_dir or (self.config.parent if self.config else Path("."))
        return tmdb_details.TMDbDetails(self.http, str(apikey), data_dir)

    async def _tmdb_to_tvdb(self, tmdb_id: str) -> str | None:
        tmdb = self._tmdb_client()
        if tmdb is not None:
            try:
                data = await tmdb._get(f"tv:{tmdb_id}:external_ids", f"/tv/{tmdb_id}/external_ids")
                if isinstance(data, dict) and data.get("tvdb_id"):
                    return str(data["tvdb_id"])
            except Exception:
                pass
        apikey = (read_section(self.config, "tmdb") or {}).get("apikey")
        if apikey:
            try:
                res = await self.http.get(
                    f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids",
                    params={"api_key": apikey},
                    timeout=TIMEOUT,
                )
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict) and data.get("tvdb_id"):
                        return str(data["tvdb_id"])
            except Exception:
                pass
        return None

    async def _tvdb_to_tmdb(self, tvdb_id: str) -> str | None:
        tmdb = self._tmdb_client()
        if tmdb is not None:
            try:
                found = await tmdb.tmdb_id({"tvdb": tvdb_id}, is_movie=False)
                if found:
                    return str(found)
            except Exception:
                pass
        apikey = (read_section(self.config, "tmdb") or {}).get("apikey")
        if apikey:
            try:
                res = await self.http.get(
                    f"https://api.themoviedb.org/3/find/{tvdb_id}",
                    params={"api_key": apikey, "external_source": "tvdb_id"},
                    timeout=TIMEOUT,
                )
                if res.status_code == 200:
                    data = res.json()
                    results = data.get("tv_results") or []
                    if results and results[0].get("id"):
                        return str(results[0]["id"])
            except Exception:
                pass
        return None

    async def _ensure_tag(self, conn: Connection) -> int:
        tags = await arr._get(self.http, conn, "/api/v3/tag")
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, dict) and str(t.get("label", "")).lower() == "starr":
                    return int(t["id"])
        created = await arr._post(self.http, conn, "/api/v3/tag", json={"label": "starr"})
        if isinstance(created, dict) and "id" in created:
            return int(created["id"])
        raise ArrProblem("Could not create tag 'starr'")

    async def _resolve_radarr_options(self, conn: Connection, radarr_settings: RadarrRequestSettings, profile: str | None = None) -> tuple[int, str]:
        profiles = await arr._get(self.http, conn, "/api/v3/qualityprofile")
        if not isinstance(profiles, list) or not profiles:
            raise ArrProblem("No quality profile available in Radarr")
        folders = await arr._get(self.http, conn, "/api/v3/rootfolder")
        if not isinstance(folders, list) or not folders:
            raise ArrProblem("No root folder available in Radarr")

        qp_id = _profile_id(profiles, profile)
        if qp_id is None and profile:
            log.info("The collection's quality profile %r isn't in Radarr any more; using the default", profile)
        if qp_id is None:
            qp_id = _profile_id(profiles, radarr_settings.quality_profile)
        if qp_id is None:
            qp_id = profiles[0].get("id")

        rf_path = None
        if radarr_settings.root_folder:
            for f in folders:
                if isinstance(f, dict) and f.get("path") == radarr_settings.root_folder:
                    rf_path = f.get("path")
                    break
        if rf_path is None:
            rf_path = folders[0].get("path")

        if qp_id is None or rf_path is None:
            raise ArrProblem("Invalid Radarr quality profile or root folder")
        return int(qp_id), str(rf_path)

    async def _resolve_sonarr_options(self, conn: Connection, sonarr_settings: SonarrRequestSettings, profile: str | None = None) -> tuple[int, str]:
        profiles = await arr._get(self.http, conn, "/api/v3/qualityprofile")
        if not isinstance(profiles, list) or not profiles:
            raise ArrProblem("No quality profile available in Sonarr")
        folders = await arr._get(self.http, conn, "/api/v3/rootfolder")
        if not isinstance(folders, list) or not folders:
            raise ArrProblem("No root folder available in Sonarr")

        qp_id = _profile_id(profiles, profile)
        if qp_id is None and profile:
            log.info("The collection's quality profile %r isn't in Sonarr any more; using the default", profile)
        if qp_id is None:
            qp_id = _profile_id(profiles, sonarr_settings.quality_profile)
        if qp_id is None:
            qp_id = profiles[0].get("id")

        rf_path = None
        if sonarr_settings.root_folder:
            for f in folders:
                if isinstance(f, dict) and f.get("path") == sonarr_settings.root_folder:
                    rf_path = f.get("path")
                    break
        if rf_path is None:
            rf_path = folders[0].get("path")

        if qp_id is None or rf_path is None:
            raise ArrProblem("Invalid Sonarr quality profile or root folder")
        return int(qp_id), str(rf_path)

    async def _request_radarr(
        self,
        conn: Connection,
        radarr_settings: RadarrRequestSettings,
        it: Item,
        kind_id: tuple[str, str],
        profile: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        try:
            _, raw_id = kind_id
            tmdb_id = int(raw_id)
        except ValueError:
            return "failed", None, f"Invalid TMDb ID: {kind_id[1]}"

        try:
            existing = await arr._get(self.http, conn, "/api/v3/movie", {"tmdbId": tmdb_id})
            movies = existing if isinstance(existing, list) else ([existing] if isinstance(existing, dict) and existing.get("id") else [])
            if movies:
                return "exists", str(movies[0]["id"]), None

            qp_id, rf_path = await self._resolve_radarr_options(conn, radarr_settings, profile)
            starr_tag = await self._ensure_tag(conn)

            lookup = await arr._get(self.http, conn, "/api/v3/movie/lookup/tmdb", {"tmdbId": tmdb_id})
            movie_data = lookup[0] if isinstance(lookup, list) and lookup else (lookup if isinstance(lookup, dict) else None)
            if not movie_data or not isinstance(movie_data, dict):
                return "failed", None, "Movie not found on TMDb"

            payload = dict(movie_data)
            payload["qualityProfileId"] = qp_id
            payload["rootFolderPath"] = rf_path
            payload["monitored"] = True
            payload["minimumAvailability"] = radarr_settings.minimum_availability
            payload["tags"] = [starr_tag]
            payload["addOptions"] = {"searchForMovie": radarr_settings.search}

            created = await arr._post(self.http, conn, "/api/v3/movie", json=payload)
            external_id = str(created.get("id")) if isinstance(created, dict) and created.get("id") else None
            return "requested", external_id, None
        except ArrProblem as problem:
            return "failed", None, str(problem)
        except Exception as e:
            return "failed", None, str(e)

    async def _request_sonarr(
        self,
        conn: Connection,
        sonarr_settings: SonarrRequestSettings,
        it: Item,
        kind_id: tuple[str, str],
        profile: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        kind, raw_id = kind_id
        if kind == "tvdb":
            try:
                tvdb_id = int(raw_id)
            except ValueError:
                return "failed", None, f"Invalid TVDb ID: {raw_id}"
        elif kind == "tmdb-show":
            try:
                mapped_tvdb = await self._tmdb_to_tvdb(raw_id)
                if not mapped_tvdb:
                    return "failed", None, f"No TVDb ID found for TMDb show {raw_id}"
                tvdb_id = int(mapped_tvdb)
            except Exception as e:
                return "failed", None, f"Error mapping TMDb show to TVDb: {e}"
        else:
            return "failed", None, f"Unsupported show ID kind: {kind}"

        try:
            existing = await arr._get(self.http, conn, "/api/v3/series", {"tvdbId": tvdb_id})
            series_list = existing if isinstance(existing, list) else ([existing] if isinstance(existing, dict) and existing.get("id") else [])
            if series_list:
                return "exists", str(series_list[0]["id"]), None

            qp_id, rf_path = await self._resolve_sonarr_options(conn, sonarr_settings, profile)
            starr_tag = await self._ensure_tag(conn)

            lookup = await arr._get(self.http, conn, "/api/v3/series/lookup", {"term": f"tvdb:{tvdb_id}"})
            series_data = lookup[0] if isinstance(lookup, list) and lookup else (lookup if isinstance(lookup, dict) else None)
            if not series_data or not isinstance(series_data, dict):
                return "failed", None, "Series not found on TVDb"

            payload = dict(series_data)
            payload["qualityProfileId"] = qp_id
            payload["rootFolderPath"] = rf_path
            payload["monitored"] = True
            payload["seriesType"] = sonarr_settings.series_type
            payload["seasonFolder"] = True
            payload["tags"] = [starr_tag]
            payload["addOptions"] = {
                "monitor": sonarr_settings.monitor,
                "searchForMissingEpisodes": sonarr_settings.search,
            }

            created = await arr._post(self.http, conn, "/api/v3/series", json=payload)
            external_id = str(created.get("id")) if isinstance(created, dict) and created.get("id") else None
            return "requested", external_id, None
        except ArrProblem as problem:
            return "failed", None, str(problem)
        except Exception as e:
            return "failed", None, str(e)

    async def _request_seerr(
        self,
        conn: SeerrConnection,
        it: Item,
        media: str,
        kind_id: tuple[str, str],
    ) -> tuple[str, str | None, str | None]:
        kind, raw_id = kind_id
        if media == "movie":
            media_type = "movie"
            try:
                tmdb_id = int(raw_id)
            except ValueError:
                return "failed", None, f"Invalid TMDb ID: {raw_id}"
        else:
            media_type = "tv"
            if kind == "tmdb-show":
                try:
                    tmdb_id = int(raw_id)
                except ValueError:
                    return "failed", None, f"Invalid TMDb ID: {raw_id}"
            elif kind == "tvdb":
                try:
                    mapped = await self._tvdb_to_tmdb(raw_id)
                    if not mapped:
                        return "failed", None, f"No TMDb ID found for TVDb show {raw_id}"
                    tmdb_id = int(mapped)
                except Exception as e:
                    return "failed", None, f"Error mapping TVDb show to TMDb: {e}"
            else:
                return "failed", None, f"Unsupported ID kind: {kind}"

        body: dict[str, Any] = {
            "mediaType": media_type,
            "mediaId": tmdb_id,
        }
        if media_type == "tv":
            body["seasons"] = "all"

        url = conn.url.rstrip("/")
        headers = {"X-Api-Key": conn.api_key, "Accept": "application/json"}
        auth = conn.login or httpx.USE_CLIENT_DEFAULT

        try:
            response = await self.http.post(
                f"{url}/api/v1/request",
                json=body,
                headers=headers,
                auth=auth,
                timeout=TIMEOUT,
            )
        except httpx.TimeoutException:
            return "failed", None, f"No answer within {TIMEOUT:g} s"
        except httpx.HTTPError as error:
            return "failed", None, f"Can't connect: {error}"

        if response.status_code == 409:
            return "exists", None, None

        if response.status_code in (200, 201):
            try:
                data = response.json()
                external_id = str(data["id"]) if isinstance(data, dict) and "id" in data else None
                return "requested", external_id, None
            except ValueError:
                return "requested", None, None

        resp_text = response.text.lower()
        if "already requested" in resp_text or "already available" in resp_text:
            return "exists", None, None

        detail = ""
        try:
            err_json = response.json()
            if isinstance(err_json, dict) and (err_json.get("message") or err_json.get("error")):
                detail = f": {err_json.get('message') or err_json.get('error')}"
        except Exception:
            pass
        return "failed", None, f"It answered HTTP {response.status_code}{detail}"

    def _record(
        self,
        item: str,
        media: str,
        title: str | None,
        year: int | None,
        library: str,
        collection_id: int | None,
        via: str,
        external_id: str | None,
        status: str,
        error: str | None,
        now: datetime,
    ) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO requests (item, media, title, year, library, collection_id, via, external_id, status, error, requested_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item,
                media,
                title,
                year,
                library,
                collection_id,
                via,
                external_id,
                status,
                error,
                utc_text(now),
                utc_text(now),
            ),
        )
        self.db.commit()
        return cursor.lastrowid

    async def request(
        self,
        items: list[Item],
        library: str,
        collection_id: int | None,
        now: datetime,
        cap: int | None = None,
        profile: str | None = None,
    ) -> RequestOutcome:
        """Ask for ``items``. ``profile`` names the Radarr/Sonarr quality profile to use instead of the default
        (Seerr picks its own)."""
        settings = self.load_settings()
        if not settings.enabled:
            raise RequestsDisabled("Requests are disabled")

        # Asked once is enough: a title already requested, downloading, imported, or already in Radarr/Sonarr
        # ('exists', which Studio leaves alone) isn't filed again on every later run.
        active_rows = self.db.execute(
            "SELECT item FROM requests WHERE status IN ('requested', 'downloading', 'imported', 'exists')"
        ).fetchall()
        active_items = {r[0] for r in active_rows}
        seen_in_batch: set[str] = set()

        # Daily cap calculation
        effective_cap = cap if cap is not None else settings.daily_cap
        if collection_id is not None and effective_cap is not None:
            today_start = f"{now.date().isoformat()}T00:00:00Z"
            used_today = self.db.execute(
                # Only what was actually sent counts towards the cap, not failures or titles the app already had.
                "SELECT count(*) FROM requests WHERE collection_id = ? AND requested_at >= ? AND status IN ('requested', 'downloading', 'imported')",
                (collection_id, today_start),
            ).fetchone()[0]
            remaining_cap = max(0, effective_cap - used_today)
        else:
            remaining_cap = None

        outcome = RequestOutcome()

        for it in items:
            if it.item in active_items or it.item in seen_in_batch:
                outcome.skipped += 1
                outcome.items.append(RequestItemResult(item=it.item, status="skipped"))
                continue

            if remaining_cap is not None and remaining_cap <= 0:
                outcome.capped += 1
                outcome.items.append(RequestItemResult(item=it.item, status="capped"))
                continue

            seen_in_batch.add(it.item)
            if remaining_cap is not None:
                remaining_cap -= 1

            # Parse media and raw id
            if it.item.startswith("tmdb-movie:"):
                media = "movie"
                kind_id = ("tmdb-movie", it.item.removeprefix("tmdb-movie:"))
            elif it.item.startswith("tmdb-show:"):
                media = "show"
                kind_id = ("tmdb-show", it.item.removeprefix("tmdb-show:"))
            elif it.item.startswith("tvdb:"):
                media = "show"
                kind_id = ("tvdb", it.item.removeprefix("tvdb:"))
            else:
                outcome.failed += 1
                error_msg = f"Unknown item key format: {it.item}"
                self._record(it.item, "movie", it.title, it.year, library, collection_id, "unknown", None, "failed", error_msg, now)
                outcome.items.append(RequestItemResult(item=it.item, status="failed", error=error_msg))
                continue

            # Route target
            chosen_via = settings.via
            if chosen_via == "auto":
                seerr_conn = self.load_seerr_connection()
                target_app = "seerr" if seerr_conn is not None else ("radarr" if media == "movie" else "sonarr")
            elif chosen_via == "seerr":
                target_app = "seerr"
            else:
                target_app = "radarr" if media == "movie" else "sonarr"

            if target_app == "seerr":
                seerr_conn = self.load_seerr_connection()
                if seerr_conn is None:
                    error_msg = "Seerr isn't connected"
                    status = "failed"
                    external_id = None
                    self._record(it.item, media, it.title, it.year, library, collection_id, "seerr", None, status, error_msg, now)
                    outcome.failed += 1
                    outcome.items.append(RequestItemResult(item=it.item, status=status, error=error_msg))
                    continue
                via_record = "seerr"
                status, external_id, error_msg = await self._request_seerr(seerr_conn, it, media, kind_id)
            elif target_app == "radarr":
                via_record = "radarr"
                radarr_conn = arr.connection(self.db, self.box, self.config, "radarr")
                if radarr_conn is None:
                    error_msg = "Radarr isn't connected"
                    status = "failed"
                    external_id = None
                    self._record(it.item, media, it.title, it.year, library, collection_id, via_record, None, status, error_msg, now)
                    outcome.failed += 1
                    outcome.items.append(RequestItemResult(item=it.item, status=status, error=error_msg))
                    continue
                status, external_id, error_msg = await self._request_radarr(radarr_conn, settings.radarr, it, kind_id, profile)
            else:  # sonarr
                via_record = "sonarr"
                sonarr_conn = arr.connection(self.db, self.box, self.config, "sonarr")
                if sonarr_conn is None:
                    error_msg = "Sonarr isn't connected"
                    status = "failed"
                    external_id = None
                    self._record(it.item, media, it.title, it.year, library, collection_id, via_record, None, status, error_msg, now)
                    outcome.failed += 1
                    outcome.items.append(RequestItemResult(item=it.item, status=status, error=error_msg))
                    continue
                status, external_id, error_msg = await self._request_sonarr(sonarr_conn, settings.sonarr, it, kind_id, profile)

            self._record(it.item, media, it.title, it.year, library, collection_id, via_record, external_id, status, error_msg, now)
            if status == "requested":
                outcome.requested += 1
                active_items.add(it.item)
            elif status == "exists":
                outcome.exists += 1
            elif status == "failed":
                outcome.failed += 1

            outcome.items.append(RequestItemResult(item=it.item, status=status, error=error_msg))

        return outcome

    async def refresh(self, now: datetime) -> dict[str, int]:
        rows = self.db.execute("SELECT * FROM requests WHERE status IN ('requested', 'downloading')").fetchall()
        if not rows:
            return self.counts()

        radarr_conn = arr.connection(self.db, self.box, self.config, "radarr")
        sonarr_conn = arr.connection(self.db, self.box, self.config, "sonarr")

        radarr_queue_movie_ids = set()
        if radarr_conn:
            try:
                queue_data = await arr._get(self.http, radarr_conn, "/api/v3/queue", {"includeMovie": "true"})
                records = queue_data.get("records", []) if isinstance(queue_data, dict) else (queue_data if isinstance(queue_data, list) else [])
                for r in records:
                    mid = r.get("movieId") or (r.get("movie") or {}).get("id")
                    if mid:
                        radarr_queue_movie_ids.add(mid)
            except Exception as e:
                log.warning("Could not fetch Radarr queue: %s", e)

        sonarr_queue_series_ids = set()
        if sonarr_conn:
            try:
                queue_data = await arr._get(self.http, sonarr_conn, "/api/v3/queue", {"includeSeries": "true"})
                records = queue_data.get("records", []) if isinstance(queue_data, dict) else (queue_data if isinstance(queue_data, list) else [])
                for r in records:
                    sid = r.get("seriesId") or (r.get("series") or {}).get("id")
                    if sid:
                        sonarr_queue_series_ids.add(sid)
            except Exception as e:
                log.warning("Could not fetch Sonarr queue: %s", e)

        radarr_starr_tag_id = None
        if radarr_conn:
            try:
                radarr_starr_tag_id = await self._ensure_tag(radarr_conn)
            except Exception:
                pass

        sonarr_starr_tag_id = None
        if sonarr_conn:
            try:
                sonarr_starr_tag_id = await self._ensure_tag(sonarr_conn)
            except Exception:
                pass

        for r in rows:
            row = dict(r)
            row_id = row["id"]
            via = row["via"]
            media = row["media"]
            item = row["item"]
            current_status = row["status"]

            if media == "movie" and radarr_conn:
                tmdb_id = item.split(":")[1] if ":" in item else None
                if not tmdb_id:
                    continue
                try:
                    found = await arr._get(self.http, radarr_conn, "/api/v3/movie", {"tmdbId": tmdb_id})
                    movie_list = found if isinstance(found, list) else ([found] if isinstance(found, dict) and found.get("id") else [])
                    if movie_list:
                        movie = movie_list[0]
                        movie_id = movie["id"]

                        if via == "seerr" and radarr_starr_tag_id is not None:
                            tags = movie.get("tags") or []
                            if radarr_starr_tag_id not in tags:
                                movie["tags"] = [*tags, radarr_starr_tag_id]
                                await arr._put(self.http, radarr_conn, f"/api/v3/movie/{movie_id}", json=movie)

                        if movie.get("hasFile"):
                            self.db.execute(
                                "UPDATE requests SET status = 'imported', imported_at = ?, updated_at = ? WHERE id = ?",
                                (utc_text(now), utc_text(now), row_id),
                            )
                        elif movie_id in radarr_queue_movie_ids and current_status != "downloading":
                            self.db.execute(
                                "UPDATE requests SET status = 'downloading', updated_at = ? WHERE id = ?",
                                (utc_text(now), row_id),
                            )
                except Exception as e:
                    log.warning("Error checking movie %s in Radarr: %s", tmdb_id, e)

            elif media == "show" and sonarr_conn:
                tvdb_id = None
                if item.startswith("tvdb:"):
                    tvdb_id = item.removeprefix("tvdb:")
                elif item.startswith("tmdb-show:"):
                    tmdb_id = item.removeprefix("tmdb-show:")
                    tvdb_id = await self._tmdb_to_tvdb(tmdb_id)
                if not tvdb_id:
                    continue
                try:
                    found = await arr._get(self.http, sonarr_conn, "/api/v3/series", {"tvdbId": tvdb_id})
                    series_list = found if isinstance(found, list) else ([found] if isinstance(found, dict) and found.get("id") else [])
                    if series_list:
                        series = series_list[0]
                        series_id = series["id"]

                        if via == "seerr" and sonarr_starr_tag_id is not None:
                            tags = series.get("tags") or []
                            if sonarr_starr_tag_id not in tags:
                                series["tags"] = [*tags, sonarr_starr_tag_id]
                                await arr._put(self.http, sonarr_conn, f"/api/v3/series/{series_id}", json=series)

                        file_count = (series.get("statistics") or {}).get("episodeFileCount", 0)
                        if file_count > 0:
                            self.db.execute(
                                "UPDATE requests SET status = 'imported', imported_at = ?, updated_at = ? WHERE id = ?",
                                (utc_text(now), utc_text(now), row_id),
                            )
                        elif series_id in sonarr_queue_series_ids and current_status != "downloading":
                            self.db.execute(
                                "UPDATE requests SET status = 'downloading', updated_at = ? WHERE id = ?",
                                (utc_text(now), row_id),
                            )
                except Exception as e:
                    log.warning("Error checking series %s in Sonarr: %s", tvdb_id, e)

        self.db.commit()
        return self.counts()

    def on_imports(self, kind: Kind, records: list[dict], now: datetime) -> int:
        updated_count = 0
        for record in records:
            keys = arr.item_keys(kind, record)
            if not keys:
                continue
            placeholders = ",".join("?" for _ in keys)
            cursor = self.db.execute(
                f"""
                UPDATE requests
                SET status = 'imported', imported_at = ?, updated_at = ?
                WHERE item IN ({placeholders}) AND status IN ('requested', 'downloading')
                """,
                (utc_text(now), utc_text(now), *keys),
            )
            updated_count += cursor.rowcount
        if updated_count > 0:
            self.db.commit()
        return updated_count

    async def label_imported(self, server: PlexServer, now: datetime) -> int:
        rows = self.db.execute("SELECT * FROM requests WHERE status = 'imported' AND labelled_at IS NULL").fetchall()
        if not rows:
            return 0

        try:
            libraries = await server.libraries()
        except PlexUnavailable as e:
            log.warning("Could not list Plex libraries for labelling: %s", e)
            return 0

        lib_by_name = {lib.title: lib for lib in libraries}
        lib_by_name_lower = {lib.title.lower(): lib for lib in libraries}

        rows_by_lib: dict[str, list[dict]] = {}
        for r in rows:
            d = dict(r)
            rows_by_lib.setdefault(d["library"], []).append(d)

        labelled_count = 0
        for lib_name, lib_rows in rows_by_lib.items():
            plex_lib = lib_by_name.get(lib_name) or lib_by_name_lower.get(lib_name.lower())
            if not plex_lib or plex_lib.type not in ("movie", "show"):
                continue

            try:
                all_ids = await server.all_ids(plex_lib.key, plex_lib.type)
            except PlexUnavailable as e:
                log.warning("Could not fetch ids for Plex library %s: %s", lib_name, e)
                continue

            item_to_rating_key = {}
            for rating_key, ids in all_ids:
                if ids.get("tmdb"):
                    item_to_rating_key[f"tmdb-movie:{ids['tmdb']}"] = rating_key
                    item_to_rating_key[f"tmdb-show:{ids['tmdb']}"] = rating_key
                if ids.get("tvdb"):
                    item_to_rating_key[f"tvdb:{ids['tvdb']}"] = rating_key

            for row in lib_rows:
                rating_key = item_to_rating_key.get(row["item"])
                if rating_key is None:
                    # Check tvdb <-> tmdb if alternative key matches
                    if row["item"].startswith("tmdb-show:"):
                        mapped_tvdb = await self._tmdb_to_tvdb(row["item"].removeprefix("tmdb-show:"))
                        if mapped_tvdb:
                            rating_key = item_to_rating_key.get(f"tvdb:{mapped_tvdb}")
                    elif row["item"].startswith("tvdb:"):
                        mapped_tmdb = await self._tvdb_to_tmdb(row["item"].removeprefix("tvdb:"))
                        if mapped_tmdb:
                            rating_key = item_to_rating_key.get(f"tmdb-show:{mapped_tmdb}")

                if rating_key is None:
                    continue

                try:
                    await server.add_label(rating_key, "starr", row["media"], library_key=plex_lib.key)
                    self.db.execute(
                        "UPDATE requests SET labelled_at = ?, updated_at = ? WHERE id = ?",
                        (utc_text(now), utc_text(now), row["id"]),
                    )
                    labelled_count += 1
                except PlexUnavailable as e:
                    log.warning("Failed to add label to item %s in Plex: %s", rating_key, e)

        self.db.commit()
        return labelled_count

    async def cancel(self, row_id: int, now: datetime) -> dict:
        row = self.db.execute("SELECT * FROM requests WHERE id = ?", (row_id,)).fetchone()
        if not row:
            raise PlexNotFound(f"Request {row_id} not found")
        row_dict = dict(row)
        if row_dict["status"] not in ("requested", "downloading"):
            raise ValueError(f"Can't cancel request with status '{row_dict['status']}'")

        via = row_dict["via"]
        external_id = row_dict["external_id"]
        if via == "radarr" and external_id:
            conn = arr.connection(self.db, self.box, self.config, "radarr")
            if conn:
                try:
                    movie = await arr._get(self.http, conn, f"/api/v3/movie/{external_id}")
                    if isinstance(movie, dict):
                        movie["monitored"] = False
                        await arr._put(self.http, conn, f"/api/v3/movie/{external_id}", json=movie)
                except Exception as e:
                    log.warning("Could not unmonitor movie %s in Radarr: %s", external_id, e)
        elif via == "sonarr" and external_id:
            conn = arr.connection(self.db, self.box, self.config, "sonarr")
            if conn:
                try:
                    series = await arr._get(self.http, conn, f"/api/v3/series/{external_id}")
                    if isinstance(series, dict):
                        series["monitored"] = False
                        await arr._put(self.http, conn, f"/api/v3/series/{external_id}", json=series)
                except Exception as e:
                    log.warning("Could not unmonitor series %s in Sonarr: %s", external_id, e)
        elif via == "seerr" and external_id:
            seerr_conn = self.load_seerr_connection()
            if seerr_conn:
                try:
                    url = seerr_conn.url.rstrip("/")
                    headers = {"X-Api-Key": seerr_conn.api_key, "Accept": "application/json"}
                    auth = seerr_conn.login or httpx.USE_CLIENT_DEFAULT
                    await self.http.delete(f"{url}/api/v1/request/{external_id}", headers=headers, auth=auth, timeout=TIMEOUT)
                except Exception as e:
                    log.warning("Could not delete request %s in Seerr: %s", external_id, e)

        self.db.execute(
            "UPDATE requests SET status = 'cancelled', updated_at = ? WHERE id = ?",
            (utc_text(now), row_id),
        )
        self.db.commit()
        updated = self.db.execute("SELECT * FROM requests WHERE id = ?", (row_id,)).fetchone()
        return dict(updated)
