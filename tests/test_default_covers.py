import asyncio
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kometa_studio import default_covers
from kometa_studio.app import create_app
from kometa_studio.default_covers import COVERS, DEFAULT_IMAGES, HEIGHT, PEOPLE_IMAGES, WIDTH, DefaultCovers, compose
from kometa_studio.settings import Settings


def poster(colour: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (200, 300), colour).save(out, "JPEG")
    return out.getvalue()


class Upstream:
    """Stands in for raw.githubusercontent.com."""

    def __init__(self):
        self.asked: list[str] = []
        self.answer = httpx.Response(200, content=poster())

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))
        if isinstance(self.answer, Exception):
            raise self.answer
        return httpx.Response(self.answer.status_code, content=self.answer.content)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def client(tmp_path, upstream):
    settings = Settings(data_dir=tmp_path / "data", kometa_config=None)
    app = create_app(settings, static_dir=tmp_path / "no-static", http_transport=upstream.transport())
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def test_a_cover_is_every_poster_whole_on_the_gallerys_shape():
    three = Image.open(io.BytesIO(compose([poster("red"), poster("green"), poster("blue")])))
    assert three.format == "WEBP"
    assert three.size == (WIDTH, HEIGHT)
    colours = [three.convert("RGB").getpixel((x, HEIGHT // 2)) for x in (360 - 179, 360, 360 + 179)]
    assert colours[0][0] > 200 and colours[1][1] > 90 and colours[2][2] > 200
    assert Image.open(io.BytesIO(compose([poster()]))).size == (WIDTH, HEIGHT)


def test_covers_only_ask_for_kometas_own_images():
    for urls in COVERS.values():
        assert 1 <= len(urls) <= 3
        assert all(url.startswith((f"{DEFAULT_IMAGES}/", f"{PEOPLE_IMAGES}/")) and url.endswith(".jpg") for url in urls)


def test_a_paths_awkward_characters_are_escaped():
    assert f"{DEFAULT_IMAGES}/streaming/color/Disney%2B.jpg" in COVERS["streaming"]
    assert f"{DEFAULT_IMAGES}/franchise/Fast%20%26%20Furious.jpg" in COVERS["franchise"]
    assert f"{PEOPLE_IMAGES}/M/Images/Margot%20Robbie.jpg" in COVERS["actor"]


def test_a_cover_is_made_once_and_kept(client, upstream, tmp_path):
    first = client.get("/api/v1/config/defaults/genre/cover")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/webp"
    assert sorted(upstream.asked) == sorted(COVERS["genre"])
    assert client.get("/api/v1/config/defaults/genre/cover").content == first.content
    assert len(upstream.asked) == 3
    assert [path.suffix for path in (tmp_path / "data" / "default-covers").iterdir()] == [".webp"]


def test_changed_posters_make_a_new_cover(client, upstream, monkeypatch):
    client.get("/api/v1/config/defaults/genre/cover")
    monkeypatch.setitem(COVERS, "genre", COVERS["genre"][:2])
    assert client.get("/api/v1/config/defaults/genre/cover").status_code == 200
    assert len(upstream.asked) == 5


def test_an_unknown_default_asks_nothing(client, upstream):
    assert client.get("/api/v1/config/defaults/nope/cover").status_code == 404
    assert client.get("/api/v1/config/defaults/..%2F..%2Fstudio.db/cover").status_code == 404
    assert upstream.asked == []


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(404), httpx.Response(200, content=b"not an image"), httpx.ConnectError("no route")],
    ids=["missing", "not an image", "offline"],
)
def test_a_failed_cover_is_a_404_and_waits_before_trying_again(client, upstream, monkeypatch, answer):
    upstream.answer = answer
    assert client.get("/api/v1/config/defaults/basic/cover").status_code == 404
    asked = len(upstream.asked)
    assert client.get("/api/v1/config/defaults/basic/cover").status_code == 404
    assert len(upstream.asked) == asked

    upstream.answer = httpx.Response(200, content=poster())
    monkeypatch.setattr(default_covers, "RETRY_AFTER", 0)
    assert client.get("/api/v1/config/defaults/basic/cover").status_code == 200


def test_an_oversized_download_is_refused(client, upstream, monkeypatch):
    monkeypatch.setattr(default_covers, "MAX_BYTES", 10)
    assert client.get("/api/v1/config/defaults/basic/cover").status_code == 404


def test_covers_need_a_signed_in_visitor(client, upstream):
    response = client.put("/api/v1/settings/auth", json={"username": "hasan", "password": "correct horse", "required": "enabled"})
    assert response.status_code == 200, response.text
    client.cookies.clear()
    assert client.get("/api/v1/config/defaults/genre/cover").status_code == 401
    assert upstream.asked == []


def test_two_requests_for_one_cover_fetch_once(tmp_path, upstream):
    async def both():
        async with httpx.AsyncClient(transport=upstream.transport()) as http:
            covers = DefaultCovers(http, tmp_path)
            return await asyncio.gather(covers.cover("genre"), covers.cover("genre"))

    first, second = asyncio.run(both())
    assert first == second
    assert len(upstream.asked) == 3
