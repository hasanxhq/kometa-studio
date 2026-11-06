"""The poster Kometa will give each ready-made collection: worked out from the default file, fetched, shrunk and cached."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from starr_studio.ready_made_posters import ReadyMadePosters, poster_url

DEFAULT_IMAGES = "https://raw.githubusercontent.com/Kometa-Team/Default-Images/master"


def write(root: Path, folder: str, name: str, text: str) -> None:
    path = root / "defaults" / folder / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Default files shaped like Kometa 2.5.4's own (defaults/movie/director.yml, both/genre.yml, chart/imdb.yml …)."""
    write(tmp_path, "movie", "director", """
dynamic_collections:
  Top Directors:
    type: director
    template: [tmdb_person, smart_filter, shared]
    template_variables:
      tmdb_person_offset:
        default: 0
        Richard Brooks: 1
      style:
        default: bw
""")
    write(tmp_path, "movie", "actor", """
dynamic_collections:
  Top Actors:
    type: actor
    template_variables:
      style:
        default: bw
        Margot Robbie: rainier
""")
    write(tmp_path, "both", "genre", """
dynamic_collections:
  Genre:
    type: genre
    template_variables:
      image:
        default: genre/<<original_key_name_encoded>>
        Acción: genre/Action
""")
    write(tmp_path, "movie", "country", """
dynamic_collections:
  Country:
    type: country
    template_variables:
      image:
        default: country/<<style>>/<<original_key_name_encoded>>
      style:
        default: white
""")
    write(tmp_path, "both", "resolution", """
external_templates:
  default: templates
  template_variables:
    conditionals:
      image:
        default: resolution/<<key>>
        conditions:
          - style: standards
            value: resolution/standards/<<key>>
dynamic_collections:
  Resolution:
    type: resolution
""")
    write(tmp_path, "chart", "imdb", """
external_templates:
  default: templates
  template_variables:
    image: chart/<<style>>/<<mapping_name_encoded>>
collections:
  IMDb Top 250:
    variables:
      style: color
      key: top
    template: [{name: imdb_chart, chart: top}, {name: shared}]
""")
    write(tmp_path, "both", "plain", """
dynamic_collections:
  Plain:
    type: genre
""")
    return tmp_path


def test_people_get_kometas_people_images_poster(root):
    url = poster_url(root, "movie", "director", "Top Directors", "Mikael Håfström")
    assert url == "https://raw.githubusercontent.com/Kometa-Team/People-Images-bw/master/M/Images/Mikael%20H%C3%A5fstr%C3%B6m.jpg"


def test_a_person_offset_and_a_per_person_style_follow_the_default(root):
    assert poster_url(root, "movie", "director", "Top Directors", "Richard Brooks").endswith("/R/Images/Richard%20Brooks%20%281%29.jpg")
    assert "/People-Images-rainier/" in poster_url(root, "movie", "actor", "Top Actors", "Margot Robbie")
    assert "/People-Images-bw/" in poster_url(root, "movie", "actor", "Top Actors", "Chris Hemsworth")


def test_shared_template_image_paths(root):
    assert poster_url(root, "movie", "genre", "Genre", "Science Fiction") == f"{DEFAULT_IMAGES}/genre/Science%20Fiction.jpg"
    assert poster_url(root, "movie", "genre", "Genre", "Acción") == f"{DEFAULT_IMAGES}/genre/Action.jpg"  # per-key path
    assert poster_url(root, "movie", "country", "Country", "France") == f"{DEFAULT_IMAGES}/country/white/France.jpg"
    assert poster_url(root, "movie", "resolution", "Resolution", "4k") == f"{DEFAULT_IMAGES}/resolution/4k.jpg"  # conditionals default


def test_a_static_chart_uses_its_title_as_the_mapping_name(root):
    assert poster_url(root, "movie", "imdb", "", "IMDb Top 250") == f"{DEFAULT_IMAGES}/chart/color/IMDb%20Top%20250.jpg"


def test_no_poster_when_the_default_doesnt_name_one(root):
    assert poster_url(root, "movie", "plain", "Plain", "Action") is None
    assert poster_url(root, "movie", "genre", "No Such Block", "Action") is None
    assert poster_url(root, "movie", "imdb", "", "Not In The File") is None
    assert poster_url(root, "movie", "nope", "", "x") is None


def jpeg(width: int = 1000, height: int = 1500) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(out, "JPEG")
    return out.getvalue()


def make_posters(tmp_path: Path, handler) -> tuple[ReadyMadePosters, list[str]]:
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return ReadyMadePosters(http, tmp_path / "posters"), asked


def test_a_poster_is_fetched_once_and_kept_small(tmp_path):
    posters, asked = make_posters(tmp_path, lambda request: httpx.Response(200, content=jpeg()))
    url = f"{DEFAULT_IMAGES}/genre/Action.jpg"

    async def twice():
        return await asyncio.gather(posters.poster(url), posters.poster(url))

    first, second = asyncio.run(twice())
    assert first == second and first is not None
    assert len(asked) == 1
    with Image.open(first) as image:
        assert image.format == "WEBP"
        assert image.size == (360, 540)
    assert asyncio.run(posters.poster(url)) == first and len(asked) == 1  # from the data folder now


def test_a_missing_poster_is_a_none_and_isnt_asked_for_again_straight_away(tmp_path):
    posters, asked = make_posters(tmp_path, lambda request: httpx.Response(404))
    url = f"{DEFAULT_IMAGES}/genre/Nope.jpg"
    assert asyncio.run(posters.poster(url)) is None
    assert asyncio.run(posters.poster(url)) is None
    assert len(asked) == 1


def test_only_kometas_image_repos_are_fetched(tmp_path):
    posters, asked = make_posters(tmp_path, lambda request: httpx.Response(200, content=jpeg()))
    assert asyncio.run(posters.poster("http://plex.local:32400/library/metadata/1/thumb")) is None
    assert asyncio.run(posters.poster("https://raw.githubusercontent.com/someone-else/repo/master/x.jpg")) is None
    assert asked == []


def test_something_that_isnt_an_image_is_a_none(tmp_path):
    posters, _ = make_posters(tmp_path, lambda request: httpx.Response(200, content=b"<html>rate limited</html>"))
    assert asyncio.run(posters.poster(f"{DEFAULT_IMAGES}/genre/Action.jpg")) is None
