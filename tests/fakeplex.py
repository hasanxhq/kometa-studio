"""A fake plex.tv and Plex server behind an httpx.MockTransport, for tests that must not touch the network."""

from pathlib import Path

import httpx

RESOURCES_XML = (Path(__file__).parent / "fixtures" / "plex_resources.xml").read_text()

ACCOUNT_TOKEN = "acct-token"
SERVER_TOKEN = "srv-token"
SERVER_ID = "srv1"
REMOTE_URI = "https://203-0-113-7.abc123.plex.direct:32400"
RELAY_URI = "https://198-51-100-9.abc123.plex.direct:8443"


class FakePlex:
    """Answers like plex.tv and the fixture's "Seedbox" server.

    From outside the seedbox, the remote plex.direct URI and the relay work; the
    container-local address and the plain public IP don't.
    """

    def __init__(self) -> None:
        self.pin_approved = False
        self.pin_expired = False
        self.account_token = ACCOUNT_TOKEN
        self.reachable = {REMOTE_URI, RELAY_URI}
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        token = request.headers.get("X-Plex-Token")
        if url.host == "plex.tv":
            return self.plex_tv(request, token)
        origin = f"{url.scheme}://{url.host}:{url.port}"
        if origin not in self.reachable:
            raise httpx.ConnectError("Connection refused", request=request)
        if url.path != "/":
            return httpx.Response(404)
        if token != SERVER_TOKEN:
            return httpx.Response(401)
        return httpx.Response(
            200, json={"MediaContainer": {"machineIdentifier": SERVER_ID, "friendlyName": "Seedbox", "version": "1.41.2.9200"}}
        )

    def plex_tv(self, request: httpx.Request, token: str | None) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/v2/pins":
            assert request.headers["X-Plex-Client-Identifier"]
            return httpx.Response(201, json={"id": 42, "code": "abcd1234", "expiresIn": 1800, "authToken": None})
        if path == "/api/v2/pins/42":
            if self.pin_expired:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": 42, "expiresIn": 1700, "authToken": ACCOUNT_TOKEN if self.pin_approved else None})
        if token != self.account_token:
            return httpx.Response(401)
        if path == "/api/v2/user":
            return httpx.Response(200, json={"username": "hasan", "email": "hasan@example.com"})
        if path == "/api/resources":
            return httpx.Response(200, text=RESOURCES_XML, headers={"Content-Type": "application/xml"})
        return httpx.Response(404)
