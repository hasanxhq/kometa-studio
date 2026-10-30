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
        self.cron = "0 * * * *"  # its overlay job's schedule: hourly, as on the maintainer's seedbox
        self.processed = 0  # overlay passes asked for
        self.status = "idle"
        self.down = False
        self.media_server = True  # Maintainerr 403s its overlay endpoints without a working media server
        self.proxy_login: tuple[str, str] | None = None  # nginx Basic auth in front, as on a seedbox
        self.slow_revert_polls = 0  # a revert that outlasts the request: status stays "running" for this many polls
        self.busy_process_polls = 0  # process answers 409 while status is "running" for this many polls
        self._running_polls = 0
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
            return httpx.Response(200, json={"enabled": self.overlays_enabled, "cronSchedule": self.cron})
        if request.method == "PUT" and path == "/api/overlays/settings":
            body = json.loads(request.content)  # a partial update, like the real one
            self.overlays_enabled = body.get("enabled", self.overlays_enabled)
            self.cron = body.get("cronSchedule", self.cron)
            return httpx.Response(200, json={"enabled": self.overlays_enabled, "cronSchedule": self.cron})
        if request.method == "GET" and path == "/api/overlays/status":
            status = self.status
            if self._running_polls > 0:
                self._running_polls -= 1
                status = "running"
            return httpx.Response(200, json={"status": status, "lastRun": None, "lastResult": None})
        if request.method == "POST" and path.startswith("/api/overlays/revert/"):
            if self.slow_revert_polls:
                self._running_polls, self.slow_revert_polls = self.slow_revert_polls, 0
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(201, json={"success": True})
        if request.method == "POST" and path == "/api/overlays/process":
            if self.busy_process_polls:
                self._running_polls, self.busy_process_polls = self.busy_process_polls, 0
                return httpx.Response(409, json={"message": "An overlay run is already in progress", "statusCode": 409})
            self.processed += 1
            return httpx.Response(202)
        return httpx.Response(404)
