"""Covers for the Defaults gallery: real posters from Kometa's image repos, side by side and uncropped.

The posters aren't in this repo. Those image repos have no licence file, and their logos and portraits belong to others, so
Studio's server fetches them from the URLs Kometa itself uses and keeps the finished cover in the data folder. Nothing is drawn
or generated here. A cover that can't be made is a 404, and the gallery keeps its colour banner.
"""

import asyncio
import hashlib
import io
import logging
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

DEFAULT_IMAGES = "https://raw.githubusercontent.com/Kometa-Team/Default-Images/master"
PEOPLE_IMAGES = "https://raw.githubusercontent.com/Kometa-Team/People-Images-bw/master"  # Kometa's default style for people

WIDTH, HEIGHT = 720, 248
POSTER_WIDTH = 165  # a whole 2:3 poster at HEIGHT
GAP = 14
LAYOUT = 1  # change with the drawing below: old covers are then remade

SLOTS = 4  # posters fetched at once: a page of tiles shouldn't open dozens of connections to GitHub
TIMEOUT = 30
RETRY_AFTER = 600  # seconds before trying a failed cover again
MAX_BYTES = 8_000_000  # the largest of these posters is under 2 MB


def _posters(*paths: str) -> tuple[str, ...]:
    return tuple(f"{DEFAULT_IMAGES}/{quote(path)}.jpg" for path in paths)


def _charts(*names: str) -> tuple[str, ...]:
    return _posters(*(f"chart/color/{name}" for name in names))


def _award(folder: str) -> tuple[str, ...]:
    return _posters(*(f"award/{folder}/{name}" for name in ("best_picture_winner", "winner", "best_director_winner")))


def _people(*names: str) -> tuple[str, ...]:
    return tuple(f"{PEOPLE_IMAGES}/{name[0]}/Images/{quote(name)}.jpg" for name in names)


# A sample of what each collection default makes. A default that isn't here keeps its colour banner.
COVERS: dict[str, tuple[str, ...]] = {
    "actor": _people("Margot Robbie", "Angelina Jolie", "Chris Hemsworth"),
    "anilist": _charts("AniList Popular", "AniList Top Rated", "AniList Trending"),
    "aspect": _posters("aspect/1.78", "aspect/1.85", "aspect/2.35"),
    "audio_language": _posters("audio_language/en", "audio_language/fr", "audio_language/ja"),
    "bafta": _award("bafta"),
    "based": _posters("based/Book", "based/Comic", "based/True Story"),
    "basic": _charts("Newly Released", "New Episodes"),
    "berlinale": _award("berlinale"),
    "cannes": _award("cannes"),
    "cesar": _award("cesar"),
    "choice": _award("choice"),
    "collectionless": _posters("collectionless"),
    "content_rating_au": _posters("content_rating/au/G", "content_rating/au/M", "content_rating/au/MA15+"),
    "content_rating_cs": _posters("content_rating/cs/12", "content_rating/cs/14", "content_rating/cs/15"),
    "content_rating_de": _posters("content_rating/de/0", "content_rating/de/12", "content_rating/de/16"),
    "content_rating_mal": _posters("content_rating/mal/G", "content_rating/mal/PG-13", "content_rating/mal/R"),
    "content_rating_nz": _posters("content_rating/nz/G", "content_rating/nz/M", "content_rating/nz/PG"),
    "content_rating_uk": _posters("content_rating/uk/12", "content_rating/uk/12A", "content_rating/uk/15"),
    "content_rating_us": _posters("content_rating/us/PG-13", "content_rating/us/R", "content_rating/us/TV-MA"),
    "continent": _posters("country/white/Africa", "country/white/Europe", "country/white/North America"),
    "country": _posters("country/white/France", "country/white/Japan", "country/white/United Kingdom"),
    "decade": _posters("decade/best/2000", "decade/best/2010", "decade/best/2020"),
    "director": _people("Greta Gerwig", "James Gunn", "James Mangold"),
    "emmy": _award("emmys"),
    "franchise": _posters("franchise/Fast & Furious", "franchise/Harry Potter", "franchise/James Bond 007"),
    "genre": _posters("genre/Action", "genre/Comedy", "genre/Horror"),
    "golden": _award("golden"),
    "imdb": _charts("IMDb Top 250", "IMDb Popular", "IMDb Lowest Rated"),
    "letterboxd": _charts("Letterboxd Top 250", "Letterboxd Top 500", "Top 250 Horror"),
    "myanimelist": _charts("MyAnimeList Popular", "MyAnimeList Top Rated", "MyAnimeList Favorited"),
    "network": _posters("network/color/HBO", "network/color/BBC One", "network/color/NBC"),
    "nfr": _posters("award/nfr/2025", "award/nfr/2024", "award/nfr/2023"),  # its folder has no winner posters
    "oscars": _award("oscars"),
    "other_chart": _charts("Common Sense Selection", "Metacritic Must See", "StevenLu's Popular Movies"),
    "pca": _award("pca"),
    "producer": _people("Amy Pascal", "Arnon Milchan", "Avi Arad"),
    "razzie": _award("razzie"),
    "region": _posters("country/white/Andean", "country/white/Benelux", "country/white/Nordic"),
    "resolution": _posters("resolution/4k", "resolution/1080", "resolution/720"),
    "sag": _award("sag"),
    "seasonal": _posters("seasonal/halloween", "seasonal/christmas", "seasonal/valentine"),
    "separator_award": _posters("separators/orig/award"),
    "separator_chart": _posters("separators/orig/chart"),
    "simkl": _charts("Simkl Trending Today", "Simkl Trending This Week", "Simkl Trending This Month"),
    "spirit": _award("spirit"),
    "streaming": _posters("streaming/color/Netflix", "streaming/color/Disney+", "streaming/color/Prime Video"),
    "studio": _posters("studio/A24", "studio/Pixar", "studio/Marvel Studios"),
    "subtitle_language": _posters("subtitle_language/en", "subtitle_language/fr", "subtitle_language/ja"),
    "sundance": _award("sundance"),
    "tautulli": _charts("Tautulli Popular", "Tautulli Watched"),
    "tiff": _award("tiff"),
    "tmdb": _charts("TMDb Popular", "TMDb Top Rated", "TMDb Trending"),
    "tracearr": _charts("Tracearr Popular", "Tracearr Trending", "Tracearr Watched"),
    "universe": _posters("universe/mcu", "universe/dcu", "universe/trek"),
    "venice": _award("venice"),
    "writer": _people("David Koepp", "David Lynch", "Fran Walsh"),
    "year": _posters("year/best/2023", "year/best/2024", "year/best/2025"),
}


def compose(posters: list[bytes]) -> bytes:
    """Whole posters in a row on a blurred, dimmed copy of the first. Raises OSError for a file Pillow can't read."""
    images = []
    for data in posters:
        image = Image.open(io.BytesIO(data))
        image.draft("RGB", (POSTER_WIDTH * 4, HEIGHT * 4))  # far faster than decoding 2000×3000
        images.append(image.convert("RGB"))
    wide = images[0].resize((WIDTH, round(WIDTH * 1.5)), Image.Resampling.BILINEAR)
    top = (wide.height - HEIGHT) // 2
    cover = wide.crop((0, top, WIDTH, top + HEIGHT)).filter(ImageFilter.GaussianBlur(26)).point(lambda value: value // 2)
    x = (WIDTH - len(images) * POSTER_WIDTH - (len(images) - 1) * GAP) // 2
    for image in images:
        cover.paste(image.resize((POSTER_WIDTH, HEIGHT), Image.Resampling.LANCZOS), (x, 0))
        x += POSTER_WIDTH + GAP
    out = io.BytesIO()
    cover.save(out, "WEBP", quality=76, method=6)
    return out.getvalue()


class DefaultCovers:
    def __init__(self, http: httpx.AsyncClient, folder: Path):
        self.http = http
        self.folder = folder
        self.slots = asyncio.Semaphore(SLOTS)
        self.locks: dict[str, asyncio.Lock] = {}
        self.failed: dict[str, float] = {}  # default → when it failed

    def path(self, name: str) -> Path:
        version = hashlib.sha256(repr((LAYOUT, COVERS[name])).encode()).hexdigest()[:12]  # new posters make a new cover
        return self.folder / f"{name}-{version}.webp"

    async def cover(self, name: str) -> Path | None:
        """The cover's file, made on first use. None if this default has none, or its posters can't be had right now."""
        if name not in COVERS:
            return None
        path = self.path(name)
        if path.is_file():
            return path
        async with self.locks.setdefault(name, asyncio.Lock()):  # the page's lazy images can ask twice
            if path.is_file():
                return path
            if time.monotonic() - self.failed.get(name, -RETRY_AFTER) < RETRY_AFTER:
                return None
            try:
                posters = await asyncio.gather(*(self._poster(url) for url in COVERS[name]))
                data = await asyncio.to_thread(compose, posters)
                self.folder.mkdir(parents=True, exist_ok=True)
                partial = path.with_suffix(".part")
                partial.write_bytes(data)
                partial.replace(path)
            except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError) as error:
                logger.info("No cover for the %s default: %s", name, error)
                self.failed[name] = time.monotonic()
                return None
            self.failed.pop(name, None)
            return path

    async def _poster(self, url: str) -> bytes:
        async with self.slots:
            response = await self.http.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError(f"{url} is larger than any poster should be")
        return response.content
