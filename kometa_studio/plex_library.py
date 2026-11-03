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


class PlexNotFound(PlexUnavailable):
    """Plex has nothing at that path (HTTP 404)."""


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
class PlexItem:
    """A movie or show in a collection."""

    rating_key: str
    title: str
    type: str  # movie, show, …
    year: int | None
    thumb: str | None
    ids: dict[str, str]  # tmdb, imdb, tvdb: what Kometa's builders match on
    content_rating: str | None
    audience_rating: float | None
    episodes: int | None  # shows only
    added_at: int | None
    video_resolution: str | None = None  # from Plex's media info, where the listing has it
    audio_codec: str | None = None


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
        if response.status_code == 404:
            raise PlexNotFound(f"Plex has nothing at {path}")
        if response.status_code != 200:
            raise PlexUnavailable(f"Plex answered HTTP {response.status_code} for {path}")
        try:
            return response.json()["MediaContainer"]
        except (ValueError, KeyError):
            raise PlexUnavailable("Plex sent something Studio can't read") from None

    async def libraries(self) -> list[PlexLibrary]:
        container = await self._get("/library/sections")
        return [PlexLibrary(str(d["key"]), str(d["title"]), str(d.get("type", ""))) for d in container.get("Directory", [])]

    async def tag_values(self, library_key: str, tag: str, library_type: str = "") -> list[tuple[str, str]]:
        """Tag values from /library/sections/{library_key}/{tag} as (title, key) tuples."""
        try:
            container = await self._get(f"/library/sections/{library_key}/{tag}")
        except PlexNotFound:
            return []
        return [
            (str(d.get("title", d.get("tag", d.get("key", "")))), str(d.get("key", "")))
            for d in container.get("Directory", [])
        ]

    async def count_where(self, library_key: str, library_type: str, params: dict) -> int:
        """How many movies or shows match the given filter parameters."""
        plex_type = {"movie": "1", "show": "2"}.get(library_type.lower())
        query = {"X-Plex-Container-Start": "0", "X-Plex-Container-Size": "0"}
        if plex_type:
            query["type"] = plex_type
        query.update(params)
        container = await self._get(f"/library/sections/{library_key}/all", query)
        return int(container.get("totalSize", container.get("size", 0)) or 0)

    async def added_since(self, library_key: str, library_type: str, since: int) -> int:
        """How many movies (or episodes, in a show library) Plex added to a library at or after ``since`` (Unix time)."""
        params = {"type": "4" if library_type == "show" else "1", "addedAt>>": str(since), "X-Plex-Container-Start": "0", "X-Plex-Container-Size": "0"}
        container = await self._get(f"/library/sections/{library_key}/all", params)
        return int(container.get("totalSize", container.get("size", 0)) or 0)

    async def size(self, library_key: str, library_type: str) -> int | None:
        """How many movies or shows a library holds; None for the kinds Kometa doesn't count (music, photos)."""
        plex_type = {"movie": "1", "show": "2"}.get(library_type)
        if plex_type is None:
            return None
        params = {"type": plex_type, "X-Plex-Container-Start": "0", "X-Plex-Container-Size": "0"}
        container = await self._get(f"/library/sections/{library_key}/all", params)
        return int(container.get("totalSize", container.get("size", 0)) or 0)

    async def _keys_with_labels(self, library_key: str, titles: tuple[str, ...] | list[str]) -> set[str]:
        """Rating keys of collections in a library that carry any of the given label titles."""
        labels = await self._get(f"/library/sections/{library_key}/label")
        label_ids = [str(d["key"]) for d in labels.get("Directory", []) if d.get("title") in titles]
        if not label_ids:
            return set()
        found: set[str] = set()
        for container in await asyncio.gather(
            *(self._get(f"/library/sections/{library_key}/all", {"type": COLLECTION_TYPE, "label": label_id}) for label_id in label_ids)
        ):
            found |= {str(m["ratingKey"]) for m in container.get("Metadata", [])}
        return found

    async def collections(self, library_key: str) -> list[PlexCollection]:
        listing, managed = await asyncio.gather(
            self._get(f"/library/sections/{library_key}/collections"),
            self._keys_with_labels(library_key, KOMETA_LABELS),
        )
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

    async def labelled_collections(self, library_key: str, label: str) -> list[PlexCollection]:
        """Collections in a library that carry ``label`` (same label lookup as ``collections``)."""
        listing, labelled = await asyncio.gather(
            self._get(f"/library/sections/{library_key}/collections"),
            self._keys_with_labels(library_key, (label,)),
        )
        return [
            PlexCollection(
                rating_key=str(m["ratingKey"]),
                title=str(m.get("title", "")),
                items=int(m.get("childCount") or 0),
                managed=False,
                smart=str(m.get("smart", "0")) in ("1", "True", "true"),
                summary=str(m.get("summary") or ""),
                thumb=_image_path(m.get("thumb")),
                added_at=m.get("addedAt"),
                updated_at=m.get("updatedAt"),
            )
            for m in listing.get("Metadata", [])
            if str(m["ratingKey"]) in labelled
        ]

    async def collection_labels(self, rating_key: str) -> set[str]:
        """The label tags on one collection, by rating key."""
        found = (await self._get(f"/library/metadata/{rating_key}")).get("Metadata") or []
        if not found or found[0].get("type") != "collection":
            raise PlexNotFound(f"Plex has no collection {rating_key}")
        return {str(label.get("tag")) for label in found[0].get("Label") or []}

    async def delete_collection(self, rating_key: str) -> None:
        """Delete a collection. Callers must re-check its labels on this rating key first."""
        try:
            response = await self.client.delete(
                f"{self.url}/library/metadata/{rating_key}",
                headers={"Accept": "application/json", "X-Plex-Token": self.token},
                timeout=TIMEOUT,
            )
        except httpx.TimeoutException:
            raise PlexUnavailable(f"Plex didn't answer within {TIMEOUT:g} s") from None
        except httpx.HTTPError as error:
            raise PlexUnavailable(f"Can't reach Plex: {error}") from None
        if response.status_code == 401:
            raise PlexUnavailable("Plex rejected the token in config.yml. Connect again in Settings → Plex.")
        if response.status_code == 404:
            raise PlexNotFound(f"Plex has no collection {rating_key}")
        if response.status_code not in (200, 204):
            raise PlexUnavailable(f"Plex answered HTTP {response.status_code} deleting {rating_key}")

    async def collection(self, rating_key: str) -> tuple[str, PlexCollection]:
        """One collection and the key of the library it's in. Managed by Kometa if it carries Kometa's label."""
        found = (await self._get(f"/library/metadata/{rating_key}")).get("Metadata") or []
        if not found or found[0].get("type") != "collection":
            raise PlexNotFound(f"Plex has no collection {rating_key}")
        m = found[0]
        labels = {str(label.get("tag")) for label in m.get("Label") or []}
        return str(m.get("librarySectionID", "")), PlexCollection(
            rating_key=str(m["ratingKey"]),
            title=str(m.get("title", "")),
            items=int(m.get("childCount") or 0),
            managed=bool(labels & set(KOMETA_LABELS)),
            smart=str(m.get("smart", "0")) in ("1", "True", "true"),
            summary=str(m.get("summary") or ""),
            thumb=_image_path(m.get("thumb")),
            added_at=m.get("addedAt"),
            updated_at=m.get("updatedAt"),
        )

    async def collection_items(self, rating_key: str, start: int, size: int) -> tuple[list[PlexItem], int]:
        """A page of a collection's movies or shows, in the collection's order, and how many it has in all."""
        container = await self._get(
            f"/library/collections/{rating_key}/children",
            {"includeGuids": "1", "X-Plex-Container-Start": str(start), "X-Plex-Container-Size": str(size)},
        )
        items = [_item(m) for m in container.get("Metadata") or []]
        return items, int(container.get("totalSize", container.get("size", len(items))) or 0)

    async def library_items(self, library_key: str, library_type: str, start: int, size: int, title: str = "") -> tuple[list[PlexItem], int]:
        """A page of a library's movies or shows, newest first, and how many there are. ``title`` narrows them to matching titles."""
        plex_type = {"movie": "1", "show": "2"}.get(library_type)
        if plex_type is None:
            return [], 0
        params = {"type": plex_type, "sort": "addedAt:desc", "X-Plex-Container-Start": str(start), "X-Plex-Container-Size": str(size)}
        if title:
            params["title"] = title
        container = await self._get(f"/library/sections/{library_key}/all", params)
        items = [_item(m) for m in container.get("Metadata") or []]
        return items, int(container.get("totalSize", container.get("size", len(items))) or 0)

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


def _item(m: dict) -> PlexItem:
    ids = {}
    for guid in m.get("Guid") or []:
        source, _, value = str(guid.get("id", "")).partition("://")
        if source in ("tmdb", "imdb", "tvdb") and value:
            ids[source] = value
    year = m.get("year")
    rating = m.get("audienceRating")
    media = next(iter(m.get("Media") or []), {})
    return PlexItem(
        rating_key=str(m["ratingKey"]),
        title=str(m.get("title", "")),
        type=str(m.get("type", "")),
        year=int(year) if isinstance(year, int | str) and str(year).isdigit() else None,
        thumb=_image_path(m.get("thumb")),
        ids=ids,
        content_rating=str(m["contentRating"]) if m.get("contentRating") else None,
        audience_rating=float(rating) if isinstance(rating, int | float) else None,
        episodes=int(m["leafCount"]) if m.get("type") == "show" and m.get("leafCount") is not None else None,
        added_at=m.get("addedAt"),
        video_resolution=str(media["videoResolution"]) if media.get("videoResolution") else None,
        audio_codec=str(media["audioCodec"]) if media.get("audioCodec") else None,
    )
