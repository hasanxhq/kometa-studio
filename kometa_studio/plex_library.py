"""Reading libraries and collections from the Plex server Kometa uses, read-only.

"Managed" follows Kometa's own rule (modules/operations.py): a collection carrying the
label ``Kometa`` (or the older ``PMM``) was built by Kometa. Plex's collection list has no
labels, so Studio asks for the collections carrying those labels instead, which is one
request per label rather than one per collection.
"""

import asyncio
import re
from dataclasses import dataclass, field

import httpx

KOMETA_LABELS = ("Kometa", "PMM")
COLLECTION_TYPE = "18"  # Plex's metadata type for collections
TIMEOUT = 20.0
# Images the poster proxy may fetch: a collection's or item's own artwork, nothing else.
IMAGE_PATH = re.compile(r"^/library/(?:collections|metadata)/\d+/(?:composite|thumb|art)/\d+$")


class PlexUnavailable(Exception):
    """The server couldn't be asked; the message is shown to the user."""


@dataclass
class PlexCollection:
    rating_key: str
    title: str
    items: int
    managed: bool
    smart: bool
    summary: str
    thumb: str | None
    added_at: int | None
    updated_at: int | None


@dataclass
class PlexLibrary:
    key: str
    title: str
    type: str  # movie, show, artist, photo
    collections: list[PlexCollection] = field(default_factory=list)


class PlexServer:
    def __init__(self, client: httpx.AsyncClient, url: str, token: str):
        self.client = client
        self.url = url.rstrip("/")
        self.token = token

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = await self.client.get(
                self.url + path,
                params=params,
                headers={"Accept": "application/json", "X-Plex-Token": self.token},
                timeout=TIMEOUT,
            )
        except httpx.TimeoutException:
            raise PlexUnavailable(f"Plex didn't answer within {TIMEOUT:g} s") from None
        except httpx.HTTPError as error:
            raise PlexUnavailable(f"Can't reach Plex: {error}") from None
        if response.status_code == 401:
            raise PlexUnavailable("Plex rejected the token in config.yml. Connect again in Settings → Plex.")
        if response.status_code != 200:
            raise PlexUnavailable(f"Plex answered HTTP {response.status_code} for {path}")
        try:
            return response.json()["MediaContainer"]
        except (ValueError, KeyError):
            raise PlexUnavailable("Plex sent something Studio can't read") from None

    async def libraries(self) -> list[PlexLibrary]:
        container = await self._get("/library/sections")
        return [PlexLibrary(str(d["key"]), str(d["title"]), str(d.get("type", ""))) for d in container.get("Directory", [])]

    async def collections(self, library_key: str) -> list[PlexCollection]:
        listing, labels = await asyncio.gather(
            self._get(f"/library/sections/{library_key}/collections"),
            self._get(f"/library/sections/{library_key}/label"),
        )
        label_ids = [str(d["key"]) for d in labels.get("Directory", []) if d.get("title") in KOMETA_LABELS]
        managed: set[str] = set()
        for container in await asyncio.gather(
            *(self._get(f"/library/sections/{library_key}/all", {"type": COLLECTION_TYPE, "label": label_id}) for label_id in label_ids)
        ):
            managed |= {str(m["ratingKey"]) for m in container.get("Metadata", [])}
        return [
            PlexCollection(
                rating_key=str(m["ratingKey"]),
                title=str(m.get("title", "")),
                items=int(m.get("childCount") or 0),
                managed=str(m["ratingKey"]) in managed,
                smart=str(m.get("smart", "0")) in ("1", "True", "true"),
                summary=str(m.get("summary") or ""),
                thumb=_image_path(m.get("thumb")),
                added_at=m.get("addedAt"),
                updated_at=m.get("updatedAt"),
            )
            for m in listing.get("Metadata", [])
        ]

    async def image(self, path: str, width: int, height: int) -> tuple[bytes, str]:
        """A poster, resized by Plex. ``path`` must be one Plex gave Studio (IMAGE_PATH)."""
        if not IMAGE_PATH.match(path):
            raise ValueError("Not a Plex artwork path")
        try:
            response = await self.client.get(
                self.url + path,
                params={"width": width, "height": height},
                headers={"X-Plex-Token": self.token},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise PlexUnavailable(f"Can't reach Plex: {error}") from None
        if response.status_code != 200:
            raise PlexUnavailable(f"Plex answered HTTP {response.status_code}")
        return response.content, response.headers.get("Content-Type", "image/jpeg")


def _image_path(thumb: object) -> str | None:
    """Plex's thumb with its own query (?width=…) removed; Studio's proxy adds the size."""
    if not isinstance(thumb, str):
        return None
    path = thumb.split("?", 1)[0]
    return path if IMAGE_PATH.match(path) else None
