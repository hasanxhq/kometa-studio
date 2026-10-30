"""Fake notification services behind an httpx handler, shaped like their APIs as Kometa uses them
(modules/notifiarr.py, gotify.py, ntfy.py): Notifiarr's key check, Gotify's /version and /message,
an ntfy topic, and an Apprise configuration served over HTTP."""

import json

import httpx

NOTIFIARR_KEY = "notifiarr-real-key"
GOTIFY_URL = "http://gotify.test"
GOTIFY_TOKEN = "gotify-real-token"
NTFY_URL = "http://ntfy.test"
NTFY_TOKEN = "tk_ntfy-real-token"
NTFY_TOPIC = "kometa-ab12"
APPRISE_URL = "http://configs.test/apprise.yml"


class FakeNotify:
    def __init__(self) -> None:
        self.apprise_config = "urls:\n  - tgram://bottoken/ChatID\n  - pover://user@token\n"
        self.down: set[str] = set()  # hosts that refuse connections
        self.calls: list[str] = []  # "METHOD host/path", in order
        self.messages: list[dict] = []  # what Gotify and ntfy were sent

    def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host in self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        self.calls.append(f"{request.method} {host}{path}")
        if host == "notifiarr.com":
            return self._notifiarr(request)
        if host == "gotify.test":
            return self._gotify(request)
        if host == "ntfy.test":
            return self._ntfy(request)
        if host == "configs.test" and path == "/apprise.yml":
            return httpx.Response(200, text=self.apprise_config)
        return httpx.Response(404, text="Not Found")

    def _notifiarr(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/v1/user/pmm/" or request.url.params.get("fetch") != "settings":
            return httpx.Response(404, json={"result": "error", "details": {"response": "not found"}})
        if request.headers.get("X-API-Key") != NOTIFIARR_KEY:
            return httpx.Response(401, json={"result": "error", "details": {"response": "Invalid API key"}})
        return httpx.Response(200, json={"result": "success", "details": {"response": {"settings": {"pmm": True}}}})

    def _gotify(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/version":
            return httpx.Response(200, json={"version": "2.6.1", "commit": "abc", "buildDate": "2025-01-01"})
        if request.method == "POST" and request.url.path == "/message":
            if request.headers.get("X-Gotify-Key") != GOTIFY_TOKEN:
                return httpx.Response(
                    401, json={"error": "Unauthorized", "errorCode": 401, "errorDescription": "you need to provide a valid access token or user credentials to access this api"}
                )
            body = json.loads(request.content)
            self.messages.append({"service": "gotify"} | body)
            return httpx.Response(200, json={"id": len(self.messages), "appid": 1} | body)
        return httpx.Response(404, json={"error": "Not Found", "errorCode": 404, "errorDescription": "page not found"})

    def _ntfy(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.path != f"/{NTFY_TOPIC}":
            return httpx.Response(404, json={"code": 40401, "http": 404, "error": "page not found"})
        if request.headers.get("Authorization") != f"Bearer {NTFY_TOKEN}":
            return httpx.Response(401, json={"code": 40101, "http": 401, "error": "unauthorized"})
        message = {"service": "ntfy", "title": request.headers.get("Title"), "message": request.content.decode()}
        self.messages.append(message)
        return httpx.Response(200, json={"id": "x1", "event": "message", "topic": NTFY_TOPIC, "title": message["title"], "message": message["message"]})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)
