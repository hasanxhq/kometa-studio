"""The poster Kometa will give each ready-made collection, worked out from its default file, fetched and kept small.

Kometa's defaults name their posters by pattern: the ``shared`` template's ``url_poster`` is
``Default-Images/master/<<image>>.jpg``, where each default file sets ``image`` (``genre/<<original_key_name_encoded>>``,
``chart/<<style>>/<<mapping_name_encoded>>``, ``award/oscars/winner/<<key>>`` …), and the ``tmdb_person`` template's is
``People-Images-<<style>>/master/<<key_name_first_letter>>/Images/<<key_encoded>><<extra>>.jpg`` (defaults/templates.yml).
Studio fills in the same placeholders, so a tile shows the poster Kometa will apply before the collection is built.

Like default_covers, the images aren't in this repo: Studio's server fetches them from Kometa's image repos, shrinks
them, and keeps them in the data folder. The browser only ever asks Studio, and only for a default, block and key: the
URL is worked out again on the server, never taken from the request. A poster that can't be had is a 404, and the tile
keeps its colour banner.
"""

import asyncio
import hashlib
import io
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from starr_studio.default_covers import DEFAULT_IMAGES
from starr_studio.kometa_files import _read

logger = logging.getLogger(__name__)

PEOPLE_TYPES = {"actor", "director", "producer", "writer"}
PEOPLE_STYLE = "bw"  # the people defaults' own default style (defaults/movie/director.yml and friends)
ALLOWED = ("https://raw.githubusercontent.com/Kometa-Team/",)

WIDTH, HEIGHT = 360, 540  # tiles are at most ~180 px wide; twice that stays sharp on high-density screens
SLOTS = 4  # posters fetched at once, as default_covers
TIMEOUT = 30
RETRY_AFTER = 600  # seconds before trying a missing poster again
MAX_BYTES = 8_000_000

_loaded: dict[Path, tuple[float, dict]] = {}


def _yaml() -> YAML:
    return YAML(typ="safe", pure=True)


def _default_file(kometa_root: Path, library_type: str, name: str) -> Path | None:
    defaults = kometa_root / "defaults" if (kometa_root / "defaults").is_dir() else kometa_root
    for folder in (library_type, "both", "chart", "award"):
        path = defaults / folder / f"{name}.yml"
        if path.is_file():
            return path
    return None


def _load(path: Path) -> dict:
    """A default file's YAML, read again only when it changes (a page of tiles asks for the same file dozens of times)."""
    mtime = path.stat().st_mtime
    hit = _loaded.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = _yaml().load(_read(path)) or {}
    except YAMLError:
        data = {}
    data = data if isinstance(data, dict) else {}
    _loaded[path] = (mtime, data)
    return data


def _pick(value: Any, key: str) -> Any:
    """A template variable for this key: its own value, else ``default``. Kometa's ``conditions`` aren't followed."""
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k) == key:
                return v
        return value.get("default")
    return value


def _image(variables: dict) -> Any:
    """``image``, or a ``conditionals: image:`` default when the file sets it that way (both/resolution.yml)."""
    if "image" in variables:
        return variables["image"]
    conditionals = variables.get("conditionals")
    if isinstance(conditionals, dict) and isinstance(conditionals.get("image"), dict):
        return conditionals["image"].get("default")
    return None


def fill(template: str, values: dict[str, str]) -> str | None:
    """Substitute placeholders, longest names first. None if any stay unresolved."""
    out = template
    for name in sorted(values, key=len, reverse=True):
        out = out.replace(f"<<{name}>>", values[name])
    return None if "<<" in out else out


def _values(key: str, key_name: str, style: Any, library_type: str) -> dict[str, str]:
    encoded = quote(key_name, safe="")
    return {
        "key": key,
        "key_encoded": quote(key, safe=""),
        "key_name": key_name,
        "key_name_encoded": encoded,
        "original_key_name": key,
        "original_key_name_encoded": quote(key, safe=""),
        "mapping_name": key_name,
        "mapping_name_encoded": encoded,
        "style": str(style) if style not in (None, "") else "white",
        "library_type": library_type,
        "library_typeU": library_type.capitalize(),
    }


def people_url(key: str, template_variables: dict) -> str | None:
    """The ``tmdb_person`` template's poster for one person."""
    name = key.strip()
    if not name:
        return None
    style = _pick(template_variables.get("style"), key) or PEOPLE_STYLE
    offset = _pick(template_variables.get("tmdb_person_offset"), key)
    extra = f" ({offset})" if offset not in (None, "", 0, "0") else ""
    return (
        f"https://raw.githubusercontent.com/Kometa-Team/People-Images-{quote(str(style), safe='')}/master/"
        f"{quote(name[0].upper(), safe='')}/Images/{quote(name + extra, safe='')}.jpg"
    )


def image_url(image: Any, key: str, key_name: str, template_variables: dict, library_type: str) -> str | None:
    """The ``shared`` template's poster for ``image`` (a path, or per-key paths with a ``default``)."""
    raw = _pick(image, key)
    if not isinstance(raw, str) or not raw.strip():
        return None
    style = _pick(template_variables.get("style"), key)
    path = fill(raw.strip(), _values(key, key_name, style, library_type))
    return f"{DEFAULT_IMAGES}/{path}.jpg" if path else None


def poster_url(kometa_root: Path, library_type: str, category: str, block: str, key: str) -> str | None:
    """The poster Kometa would apply to one ready-made collection, or None when its default doesn't say."""
    path = _default_file(kometa_root, library_type, category)
    if path is None:
        return None
    data = _load(path)
    external = data.get("external_templates") if isinstance(data.get("external_templates"), dict) else {}
    file_vars = external.get("template_variables") if isinstance(external.get("template_variables"), dict) else {}

    if not block:
        statics = data.get("collections") if isinstance(data.get("collections"), dict) else {}
        attrs = statics.get(key)
        if not isinstance(attrs, dict):
            return None
        own = attrs.get("variables") if isinstance(attrs.get("variables"), dict) else {}
        variables = {**file_vars, **own}
        # A static collection's mapping name is its title; ``key`` is its own variable (e.g. "popular").
        return image_url(_image(variables), str(variables.get("key", key)), key, variables, library_type)

    blocks = data.get("dynamic_collections") if isinstance(data.get("dynamic_collections"), dict) else {}
    attrs = blocks.get(block)
    if not isinstance(attrs, dict):
        return None
    own = attrs.get("template_variables") if isinstance(attrs.get("template_variables"), dict) else {}
    variables = {**file_vars, **own}
    if str(attrs.get("type", "")).lower() in PEOPLE_TYPES:
        return people_url(key, variables)
    overrides = attrs.get("key_name_override") if isinstance(attrs.get("key_name_override"), dict) else {}
    key_name = next((str(v) for k, v in overrides.items() if str(k) == key), key)
    return image_url(_image(variables), key, key_name, variables, library_type)


def shrink(data: bytes) -> bytes:
    """A tile-sized WebP. Raises OSError for a file Pillow can't read."""
    image = Image.open(io.BytesIO(data))
    image.draft("RGB", (WIDTH * 2, HEIGHT * 2))
    image = image.convert("RGB")
    image.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=80, method=6)
    return out.getvalue()


class ReadyMadePosters:
    def __init__(self, http: httpx.AsyncClient, folder: Path):
        self.http = http
        self.folder = folder
        self.slots = asyncio.Semaphore(SLOTS)
        self.locks: dict[str, asyncio.Lock] = {}
        self.failed: dict[str, float] = {}  # url → when it failed

    def path(self, url: str) -> Path:
        return self.folder / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.webp"

    async def poster(self, url: str) -> Path | None:
        """The poster's file, fetched on first use. None if it isn't one of Kometa's or can't be had right now."""
        if not url.startswith(ALLOWED):
            return None
        path = self.path(url)
        if path.is_file():
            return path
        async with self.locks.setdefault(url, asyncio.Lock()):
            if path.is_file():
                return path
            if time.monotonic() - self.failed.get(url, -RETRY_AFTER) < RETRY_AFTER:
                return None
            try:
                async with self.slots:
                    response = await self.http.get(url, timeout=TIMEOUT)
                response.raise_for_status()
                if len(response.content) > MAX_BYTES:
                    raise ValueError(f"{url} is larger than any poster should be")
                data = await asyncio.to_thread(shrink, response.content)
                self.folder.mkdir(parents=True, exist_ok=True)
                partial = path.with_suffix(".part")
                partial.write_bytes(data)
                partial.replace(path)
            except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError) as error:
                logger.info("No ready-made poster from %s: %s", url, error)
                self.failed[url] = time.monotonic()
                return None
            self.failed.pop(url, None)
            return path
