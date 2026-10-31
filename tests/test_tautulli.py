import httpx
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_sections import read_section
from kometa_studio.settings import Settings

URL = "http://tautulli.lan:8181"
KEY = "tautulli-good-key"


class FakeTautulli:
    """Tautulli's /api/v2 as Kometa calls it when it starts."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "down.lan":
            raise httpx.ConnectError("Connection refused", request=request)
        if request.url.host != "tautulli.lan" or request.url.path != "/api/v2":
            return httpx.Response(200, text="<html>not Tautulli</html>")
        if request.url.params.get("apikey") != KEY:
            return httpx.Response(401, json={"response": {"result": "error", "message": "Invalid apikey", "data": {}}})
        assert request.url.params.get("cmd") == "get_tautulli_info"
        return httpx.Response(200, json={"response": {"result": "success", "message": None, "data": {"tautulli_version": "v2.15.2"}}})


def make_client(tmp_path, text="tmdb:\n  apikey: tmdb-key\n"):
    config = tmp_path / "config.yml"
    config.write_text(text)
    fake = FakeTautulli()
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config), static_dir=tmp_path / "no-static", http_transport=httpx.MockTransport(fake.handle))
    return TestClient(app, client=("127.0.0.1", 50000)), config, fake


def test_a_connection_is_tested_the_way_kometa_does(tmp_path):
    client, _, _ = make_client(tmp_path)
    with client:
        good = client.post("/api/v1/settings/tautulli/test", json={"url": URL + "/", "apikey": KEY}).json()
        wrong_key = client.post("/api/v1/settings/tautulli/test", json={"url": URL, "apikey": "nope"}).json()
        not_tautulli = client.post("/api/v1/settings/tautulli/test", json={"url": "http://other.lan", "apikey": KEY}).json()
        down = client.post("/api/v1/settings/tautulli/test", json={"url": "http://down.lan:8181", "apikey": KEY}).json()
        no_key = client.post("/api/v1/settings/tautulli/test", json={"url": URL})
        bad_url = client.post("/api/v1/settings/tautulli/test", json={"url": "tautulli.lan:8181", "apikey": KEY})
    assert good == {"ok": True, "version": "v2.15.2"}
    assert wrong_key == {"ok": False, "error": "Tautulli rejected the API key"}
    assert not_tautulli["ok"] is False and "not Tautulli's API" in not_tautulli["error"]
    assert down["ok"] is False and "Can't reach Tautulli" in down["error"]
    assert no_key.status_code == 422 and "API key" in no_key.json()["detail"]
    assert bad_url.status_code == 422


def test_saved_only_after_passing_its_test_and_masked(tmp_path):
    client, config, _ = make_client(tmp_path)
    with client:
        refused = client.put("/api/v1/settings/tautulli", json={"url": URL, "apikey": "nope"})
        assert "tautulli" not in config.read_text()
        saved = client.put("/api/v1/settings/tautulli", json={"url": URL + "/", "apikey": KEY}).json()
        # A new address with the saved key: the key isn't sent again.
        moved = client.put("/api/v1/settings/tautulli", json={"url": "http://tautulli.lan:8181"}).json()
        listed = client.get("/api/v1/settings/tautulli").json()
        backups = client.get("/api/v1/backups").json()["backups"]
    assert refused.status_code == 422 and "Not saved" in refused.json()["detail"]
    assert saved == {"url": URL, "apikey": "…-key"} == moved == listed
    assert read_section(config, "tautulli") == {"url": URL, "apikey": KEY}
    assert read_section(config, "tmdb") == {"apikey": "tmdb-key"}
    assert [b["reason"] for b in backups] == ["Connected Tautulli in Settings → Connect"]  # the unchanged save wrote nothing


def test_removing_it(tmp_path):
    client, config, _ = make_client(tmp_path, f"tmdb:\n  apikey: tmdb-key\ntautulli:\n  url: {URL}\n  apikey: {KEY}  # mine\n")
    with client:
        state = client.delete("/api/v1/settings/tautulli").json()
        again = client.delete("/api/v1/settings/tautulli")
    assert state == {"url": None, "apikey": None} and again.status_code == 200
    assert config.read_text() == "tmdb:\n  apikey: tmdb-key\n"
