"""DNS bypass for TMDb (feedback round 1): look TMDb's hosts up through Cloudflare's DNS over HTTPS at
1.1.1.1 instead of the system's resolver, for networks whose DNS blocks or misdirects TMDb.

It's turned on with the TMDb key on Settings → Connect and kept for that key: ``SETTING`` holds a hash
of the key it was saved with, so saving another key without the box ticked turns it off.

- Studio's own TMDb calls connect to the address DoH gives, sending TMDb's name for TLS (SNI) and in
  the Host header, so the certificate is still checked against TMDb's name.
- Kometa's runs and checks get ``kometa_doh/`` on ``PYTHONPATH``. Its ``sitecustomize`` makes Python's
  ``socket.getaddrinfo`` answer TMDb's names (``HOSTS``) through DoH; everything else resolves as
  usual. Kometa's own code is untouched.

It only helps where TMDb is blocked by DNS. A network that blocks TMDb's addresses still blocks it.
"""

import hashlib
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config_sections import read_section
from .db import delete_setting, get_setting, set_setting

DOH_URL = "https://1.1.1.1/dns-query"
HOSTS = ("themoviedb.org", "tmdb.org")  # api.themoviedb.org, image.tmdb.org, …
SETTING = "tmdb.doh"  # {"key": sha256 of the TMDb key it was saved with}
WRAPPER = Path(__file__).parent / "kometa_doh"
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


def kometa_env(db: sqlite3.Connection, config: Path | None) -> dict[str, str]:
    """Extra environment for Kometa's processes: the DoH wrapper, when it's on."""
    if not enabled(db, config):
        return {}
    path = os.pathsep.join(filter(None, [str(WRAPPER), os.environ.get("PYTHONPATH")]))
    return {"PYTHONPATH": path, "STUDIO_DOH_HOSTS": ",".join(HOSTS), "STUDIO_DOH_URL": DOH_URL}


async def resolve(http: httpx.AsyncClient, host: str) -> str:
    """The first IPv4 address DoH gives for ``host``."""
    try:
        response = await http.get(DOH_URL, params={"name": host, "type": "A"}, headers={"Accept": "application/dns-json"}, timeout=TIMEOUT)
        if response.status_code != 200:
            raise DohProblem(f"1.1.1.1 answered HTTP {response.status_code} when looking up {host}")
        answers = response.json().get("Answer") or []
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise DohProblem(f"Couldn't look up {host} over DNS over HTTPS (1.1.1.1): {error}") from None
    found = [str(answer["data"]) for answer in answers if isinstance(answer, dict) and answer.get("type") == 1 and answer.get("data")]
    if not found:
        raise DohProblem(f"1.1.1.1 has no address for {host}")
    return found[0]


async def get(http: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET ``url``, its host looked up over DoH: connect to that address, with the real name for TLS and Host."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    address = await resolve(http, host)
    netloc = address + (f":{parts.port}" if parts.port else "")
    headers = dict(kwargs.pop("headers", None) or {}) | {"Host": parts.netloc}
    return await http.get(urlunsplit(parts._replace(netloc=netloc)), headers=headers, extensions={"sni_hostname": host}, **kwargs)
