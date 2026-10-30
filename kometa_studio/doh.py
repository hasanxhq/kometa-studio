"""DNS bypass for TMDb (feedback round 1): look TMDb's hosts up through Cloudflare's DNS over HTTPS at
1.1.1.1 instead of the system's resolver, for networks whose DNS blocks or misdirects TMDb.

QUICK FIX, to be removed: the maintainer asked for this to go once Settings → Network's proxy
(network.py) is in and proven to work. Until then network.kometa_env and NetworkTransport honour it
alongside the Network page's own DNS over HTTPS.

It's turned on with the TMDb key on Settings → Connect and kept for that key: ``SETTING`` holds a hash
of the key it was saved with, so saving another key without the box ticked turns it off.

- Studio's own TMDb calls connect to the address DoH gives, sending TMDb's name for TLS (SNI) and in
  the Host header, so the certificate is still checked against TMDb's name.
- Kometa's runs and checks get the same through network.kometa_env (TMDb's names, ``HOSTS``, are
  answered over DoH by ``kometa_doh/sitecustomize.py``). Kometa's own code is untouched.

It only helps where TMDb is blocked by DNS. A network that blocks TMDb's addresses still blocks it.
"""

import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config_sections import read_section
from .db import delete_setting, get_setting, set_setting

DOH_URL = "https://1.1.1.1/dns-query"
HOSTS = ("themoviedb.org", "tmdb.org")  # api.themoviedb.org, image.tmdb.org, …
SETTING = "tmdb.doh"  # {"key": sha256 of the TMDb key it was saved with}
TIMEOUT = 10.0


class DohProblem(Exception):
    pass


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def remember(db: sqlite3.Connection, key: str, on: bool) -> None:
    if on:
        set_setting(db, SETTING, {"key": key_hash(key)})
    else:
        delete_setting(db, SETTING)


def enabled(db: sqlite3.Connection, config: Path | None) -> bool:
    """On for the TMDb key in config.yml, if it was saved with the box ticked."""
    saved = get_setting(db, SETTING)
    key = (read_section(config, "tmdb") or {}).get("apikey")
    return bool(saved and key and saved.get("key") == key_hash(str(key)))


async def resolve(http: httpx.AsyncClient, host: str, url: str = DOH_URL) -> str:
    """The first IPv4 address DoH (``url``: 1.1.1.1 unless another provider's) gives for ``host``."""
    return (await resolve_all(http, host, url))[0]


async def resolve_all(http: httpx.AsyncClient, host: str, url: str = DOH_URL) -> list[str]:
    """Every IPv4 address DoH gives for ``host``, in its order."""
    provider = urlsplit(url).hostname
    try:
        response = await http.get(url, params={"name": host, "type": "A"}, headers={"Accept": "application/dns-json"}, timeout=TIMEOUT)
        if response.status_code != 200:
            raise DohProblem(f"{provider} answered HTTP {response.status_code} when looking up {host}")
        answers = response.json().get("Answer") or []
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise DohProblem(f"Couldn't look up {host} over DNS over HTTPS ({provider}): {error}") from None
    found = [str(answer["data"]) for answer in answers if isinstance(answer, dict) and answer.get("type") == 1 and answer.get("data")]
    if not found:
        raise DohProblem(f"{provider} has no address for {host}")
    return found


async def get(http: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET ``url``, its host looked up over DoH: connect to that address, with the real name for TLS and Host.

    If an address can't be connected to (some networks reset a few of a CDN's addresses), the next one is tried.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    headers = dict(kwargs.pop("headers", None) or {}) | {"Host": parts.netloc}
    failed: httpx.TransportError | None = None
    for address in await resolve_all(http, host):
        netloc = address + (f":{parts.port}" if parts.port else "")
        try:
            return await http.get(urlunsplit(parts._replace(netloc=netloc)), headers=headers, extensions={"sni_hostname": host}, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            failed = error
    raise failed  # type: ignore[misc]
