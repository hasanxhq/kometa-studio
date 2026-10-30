"""A fake Maintainerr behind an httpx handler, shaped like its API (apps/server: collections and overlays
controllers), optionally behind a seedbox's nginx asking for a username and password."""

import base64
import json

import httpx

MAINTAINERR_URL = "http://maintainerr.test:6246"


class FakeMaintainerr:
    def __init__(self) -> None:
        self.collections = [
            # A rule collection Maintainerr made in Plex (rating key 102 in FakePlex's Movies), with overlays.
            {"id": 7, "title": "Spy Kids", "libraryId": "1", "mediaServerId": "102", "isActive": True, "overlayEnabled": True,
             "manualCollection": False, "manualCollectionName": "", "deleteAfterDays": 30, "arrAction": 0},
            # One without overlays, in a library Kometa doesn't use.
            {"id": 8, "title": "Leaving Soon Shows", "libraryId": "2", "mediaServerId": "201", "isActive": True, "overlayEnabled": False,
             "manualCollection": False, "manualCollectionName": "", "deleteAfterDays": 14, "arrAction": 0},
        ]
        self.overlays_enabled = True
        self.status = "idle"
        self.down = False
        self.media_server = True  # Maintainerr 403s its overlay endpoints without a working media server
        self.proxy_login: tuple[str, str] | None = None  # nginx Basic auth in front, as on a seedbox
        self.calls: list[str] = []  # "METHOD /path", in order

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        if self.proxy_login:
            expected = "Basic " + base64.b64encode(":".join(self.proxy_login).encode()).decode()
            if request.headers.get("Authorization") != expected:
                page = "<html><head><title>401 Authorization Required</title></head><body><center>nginx</center></body></html>"
                return httpx.Response(401, text=page, headers={"Content-Type": "text/html", "WWW-Authenticate": 'Basic realm="Maintainerr Auth"'})
        path = request.url.path
        if path.startswith("/api/overlays") and not self.media_server:
            return httpx.Response(403, json={"message": "Forbidden resource", "error": "Forbidden", "statusCode": 403})
        self.calls.append(f"{request.method} {path}")
        if request.method == "GET" and path == "/api/collections":
            return httpx.Response(200, json=self.collections)
        if request.method == "GET" and path == "/api/overlays/settings":
            return httpx.Response(200, json={"enabled": self.overlays_enabled, "cronSchedule": "0 3 * * *"})
        if request.method == "PUT" and path == "/api/overlays/settings":
            self.overlays_enabled = json.loads(request.content).get("enabled", self.overlays_enabled)
            return httpx.Response(200, json={"enabled": self.overlays_enabled, "cronSchedule": "0 * * * *"})
        if request.method == "GET" and path == "/api/overlays/status":
            return httpx.Response(200, json={"status": self.status, "lastRun": None, "lastResult": None})
        if request.method == "POST" and path.startswith("/api/overlays/revert/"):
            return httpx.Response(201, json={"success": True})
        if request.method == "POST" and path == "/api/overlays/process":
            return httpx.Response(202)
        return httpx.Response(404)
