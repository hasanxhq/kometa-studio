"""A fake Radarr and Sonarr behind an httpx.MockTransport (shapes from their v3 API source)."""

import base64
from datetime import datetime

import httpx

RADARR_URL = "http://radarr.test:7878"
SONARR_URL = "http://sonarr.test:8989"
RADARR_KEY = "radarr-key"
SONARR_KEY = "sonarr-key"


class FakeArr:
    def __init__(self) -> None:
        self.history: dict[str, list[dict]] = {"radarr": [], "sonarr": []}
        self.down: set[str] = set()
        self.proxy_login: tuple[str, str] | None = None  # nginx Basic auth in front of Sonarr, as on a seedbox
        self.requests: list[httpx.Request] = []
        self._next_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def imported(self, kind: str, title: str, year: int, at: datetime) -> None:
        self._next_id += 1
        item = {"title": title, "year": year}
        record = {"id": self._next_id, "eventType": "downloadFolderImported", "date": at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "sourceTitle": f"{title}.{year}.mkv"}
        record["movie" if kind == "radarr" else "series"] = item
        self.history[kind].append(record)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        kind = "radarr" if url.startswith(RADARR_URL) else "sonarr" if url.startswith(SONARR_URL) else None
        if kind is None or kind in self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        if kind == "sonarr" and self.proxy_login and request.headers.get("Authorization") != "Basic " + base64.b64encode(":".join(self.proxy_login).encode()).decode():
            return httpx.Response(401, text="<html>nginx</html>", headers={"WWW-Authenticate": 'Basic realm="Sonarr"'})
        if request.headers.get("X-Api-Key") != {"radarr": RADARR_KEY, "sonarr": SONARR_KEY}[kind]:
            return httpx.Response(401)
        if request.url.path == "/api/v3/system/status":
            return httpx.Response(200, json={"appName": kind.capitalize(), "version": "5.14.0.9383" if kind == "radarr" else "4.0.11.2680"})
        if request.url.path == "/api/v3/rootfolder":
            return httpx.Response(200, json=[{"id": 1, "path": "/movies" if kind == "radarr" else "/tv", "accessible": True}])
        if request.url.path == "/api/v3/qualityprofile":
            return httpx.Response(200, json=[{"id": 4, "name": "HD-1080p"}, {"id": 5, "name": "Ultra-HD"}])
        if request.url.path == "/api/v3/history/since":
            since = request.url.params["date"]
            assert request.url.params["eventType"] == "3"
            keep = [r for r in self.history[kind] if r["date"][:19] >= since[:19]]
            # Like the real thing: the item only when asked for.
            include = request.url.params.get("includeMovie" if kind == "radarr" else "includeSeries") == "true"
            return httpx.Response(200, json=[r if include else {k: v for k, v in r.items() if k not in ("movie", "series")} for r in keep])
        return httpx.Response(404)
