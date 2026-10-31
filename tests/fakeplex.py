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
        self.added: dict[str, list[int]] = {}  # section key -> when each movie or episode was added (Unix time)

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
        if token != SERVER_TOKEN:
            return httpx.Response(401)
        if url.path == "/":
            return httpx.Response(
                200, json={"MediaContainer": {"machineIdentifier": SERVER_ID, "friendlyName": "Seedbox", "version": "1.41.2.9200"}}
            )
        if url.path.startswith("/library/"):
            return self.library(request)
        return httpx.Response(404)

    # Libraries shaped like a real server's answers (checked against Plex Media Server 1.41).
    SECTIONS = [{"key": "1", "title": "Movies", "type": "movie"}, {"key": "2", "title": "TV Shows", "type": "show"}]
    COLLECTIONS = {
        "1": [
            {"ratingKey": "101", "title": "Marvel", "childCount": 11, "thumb": "/library/collections/101/composite/1700000001?width=400&height=600"},
            {"ratingKey": "102", "title": "Spy Kids", "childCount": 3, "summary": "Made by hand", "thumb": "/library/collections/102/composite/1700000002"},
            {"ratingKey": "103", "title": "Old PMM collection", "childCount": 2, "smart": "1"},
        ],
        "2": [],
    }
    SIZES = {"1": 812, "2": 64}  # movies, shows
    LABELS = {"1": [{"key": "33517", "title": "Kometa"}, {"key": "40", "title": "PMM"}, {"key": "41", "title": "Favourites"}], "2": []}
    LABELLED = {"33517": ["101"], "40": ["103"], "41": ["102"]}
    # What /library/metadata/<collection> and /library/collections/<key>/children give (Plex 1.41, trimmed).
    COLLECTION_META = {
        "101": {"librarySectionID": 1, "Label": [{"id": 33517, "tag": "Kometa"}]},
        "102": {"librarySectionID": 1, "Label": [{"id": 41, "tag": "Favourites"}]},
        "103": {"librarySectionID": 1, "Label": [{"id": 40, "tag": "PMM"}]},
    }
    ITEMS = {
        "101": [
            {
                "ratingKey": str(201 + n),
                "type": "movie",
                "title": f"Marvel film {n + 1}",
                "year": 2008 + n,
                "contentRating": "PG-13",
                "audienceRating": 7.5,
                "thumb": f"/library/metadata/{201 + n}/thumb/1700000100",
                "addedAt": 1700000000 + n,
                "Guid": [{"id": f"imdb://tt0{371746 + n}"}, {"id": f"tmdb://{1726 + n}"}, {"id": "tvdb://128"}],
            }
            for n in range(11)
        ],
        "102": [{"ratingKey": "301", "type": "movie", "title": "Spy Kids", "year": 2001}],
        "103": [{"ratingKey": "401", "type": "show", "title": "An Old Show", "year": 1999, "leafCount": 61, "Guid": [{"id": "tvdb://74852"}]}],
    }

    def library(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")  # library, sections, <key>, <what>
        if parts == ["library", "sections"]:
            return httpx.Response(200, json={"MediaContainer": {"Directory": self.SECTIONS}})
        if len(parts) == 4 and parts[1] == "sections" and parts[2] in self.COLLECTIONS:
            key, what = parts[2], parts[3]
            if what == "collections":
                return httpx.Response(200, json={"MediaContainer": {"Metadata": self.COLLECTIONS[key]}})
            if what == "label":
                return httpx.Response(200, json={"MediaContainer": {"Directory": self.LABELS[key]}})
            if what == "all" and request.url.params.get("type") in ("1", "2") and "addedAt>>" not in request.url.params:
                return httpx.Response(200, json={"MediaContainer": {"size": 0, "totalSize": self.SIZES.get(key, 0), "Metadata": []}})
            if what == "all" and request.url.params.get("type") in ("1", "4"):  # how many were added since, as Plex's addedAt>>= filter
                since = int(request.url.params.get("addedAt>>", "0"))
                count = len([at for at in self.added.get(key, []) if at >= since])
                return httpx.Response(200, json={"MediaContainer": {"size": 0, "totalSize": count, "Metadata": []}})
            if what == "all" and request.url.params.get("type") == "18":
                keys = self.LABELLED.get(request.url.params.get("label", ""), [])
                return httpx.Response(200, json={"MediaContainer": {"Metadata": [{"ratingKey": k} for k in keys]}})
        if len(parts) == 3 and parts[1] == "metadata" and parts[2] in self.COLLECTION_META:
            meta = next(c for c in self.COLLECTIONS["1"] if c["ratingKey"] == parts[2]) | self.COLLECTION_META[parts[2]] | {"type": "collection"}
            return httpx.Response(200, json={"MediaContainer": {"size": 1, "Metadata": [meta]}})
        if len(parts) == 3 and parts[1] == "metadata" and parts[2] == "201":  # a movie, not a collection
            return httpx.Response(200, json={"MediaContainer": {"size": 1, "Metadata": [self.ITEMS["101"][0] | {"librarySectionID": 1}]}})
        if len(parts) == 4 and parts[1] == "collections" and parts[3] == "children" and parts[2] in self.ITEMS:
            items = self.ITEMS[parts[2]]
            start, size = int(request.url.params.get("X-Plex-Container-Start", "0")), int(request.url.params.get("X-Plex-Container-Size", "50"))
            page = items[start : start + size]
            return httpx.Response(200, json={"MediaContainer": {"size": len(page), "totalSize": len(items), "offset": start, "Metadata": page}})
        if len(parts) == 5 and parts[1] == "collections" and parts[3] == "composite":
            return httpx.Response(200, content=b"\xff\xd8poster", headers={"Content-Type": "image/jpeg"})
        return httpx.Response(404)

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
