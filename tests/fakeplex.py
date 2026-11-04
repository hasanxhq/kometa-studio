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
        self.deletions: list[str] = []
        self._next_key = 200
        self.TAGS = {
            k: {tag: [dict(item) for item in items] for tag, items in tags.items()}
            for k, tags in self.DEFAULT_TAGS.items()
        }
        self.CREDITS = {k: dict(v) for k, v in self.DEFAULT_CREDITS.items()}
        self.TAG_COUNTS = {
            k: dict(counts)
            for k, counts in self.DEFAULT_TAG_COUNTS.items()
        }
        # Instance copies so tests can add/delete without polluting siblings.
        self.COLLECTIONS = {k: [dict(c) for c in v] for k, v in self.DEFAULT_COLLECTIONS.items()}
        self.LABELS = {k: [dict(x) for x in v] for k, v in self.DEFAULT_LABELS.items()}
        self.LABELLED = {k: list(v) for k, v in self.DEFAULT_LABELLED.items()}
        self.COLLECTION_META = {k: {**v, "Label": [dict(lab) for lab in v.get("Label", [])]} for k, v in self.DEFAULT_COLLECTION_META.items()}
        self.ITEMS = {k: [dict(i) for i in v] for k, v in self.DEFAULT_ITEMS.items()}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def add_collection(self, section_key: str, title: str, *, labels: list[str] | None = None, items: int = 0, thumb: str | None = None) -> str:
        """Add a collection as if Kometa (or something else) built it. Returns its rating key."""
        self._next_key += 1
        key = str(self._next_key)
        entry: dict = {"ratingKey": key, "title": title, "childCount": items}
        if thumb:
            entry["thumb"] = thumb
        self.COLLECTIONS.setdefault(section_key, []).append(entry)
        by_title = {d["title"]: str(d["key"]) for d in self.LABELS.get(section_key, [])}
        meta_labels = []
        for name in labels or []:
            if name not in by_title:
                new_id = str(9000 + len(self.LABELS.get(section_key, [])))
                self.LABELS.setdefault(section_key, []).append({"key": new_id, "title": name})
                by_title[name] = new_id
            lab_key = by_title[name]
            meta_labels.append({"id": int(lab_key) if lab_key.isdigit() else abs(hash(lab_key)) % 100000, "tag": name})
            self.LABELLED.setdefault(lab_key, []).append(key)
        self.COLLECTION_META[key] = {"librarySectionID": int(section_key), "Label": meta_labels}
        self.ITEMS[key] = []
        return key

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
        if request.method == "DELETE" and url.path.startswith("/library/metadata/"):
            return self.delete_metadata(url.path.rsplit("/", 1)[-1])
        if url.path.startswith("/library/"):
            return self.library(request)
        return httpx.Response(404)

    def delete_metadata(self, rating_key: str) -> httpx.Response:
        if rating_key not in self.COLLECTION_META:
            return httpx.Response(404)
        self.deletions.append(rating_key)
        for section, items in self.COLLECTIONS.items():
            self.COLLECTIONS[section] = [c for c in items if c["ratingKey"] != rating_key]
        for lab_key, keys in list(self.LABELLED.items()):
            self.LABELLED[lab_key] = [k for k in keys if k != rating_key]
        self.COLLECTION_META.pop(rating_key, None)
        self.ITEMS.pop(rating_key, None)
        return httpx.Response(200)

    # Libraries shaped like a real server's answers (checked against Plex Media Server 1.41).
    SECTIONS = [{"key": "1", "title": "Movies", "type": "movie"}, {"key": "2", "title": "TV Shows", "type": "show"}]
    DEFAULT_COLLECTIONS = {
        "1": [
            {"ratingKey": "101", "title": "Marvel", "childCount": 11, "thumb": "/library/collections/101/composite/1700000001?width=400&height=600"},
            {"ratingKey": "102", "title": "Spy Kids", "childCount": 3, "summary": "Made by hand", "thumb": "/library/collections/102/composite/1700000002"},
            {"ratingKey": "103", "title": "Old PMM collection", "childCount": 2, "smart": "1"},
            {"ratingKey": "104", "title": "Studio Chart", "childCount": 4, "thumb": "/library/collections/104/composite/1700000004"},
            {"ratingKey": "105", "title": "Action Movies", "childCount": 5, "thumb": "/library/collections/105/composite/1700000005"},
        ],
        "2": [],
    }
    SIZES = {"1": 812, "2": 64}  # movies, shows
    DEFAULT_LABELS = {
        "1": [
            {"key": "33517", "title": "Kometa"},
            {"key": "40", "title": "PMM"},
            {"key": "41", "title": "Favourites"},
            {"key": "42", "title": "Studio"},
        ],
        "2": [],
    }
    DEFAULT_LABELLED = {"33517": ["101", "105"], "40": ["103"], "41": ["102"], "42": ["104", "105"]}
    # What /library/metadata/<collection> and /library/collections/<key>/children give (Plex 1.41, trimmed).
    DEFAULT_COLLECTION_META = {
        "101": {"librarySectionID": 1, "Label": [{"id": 33517, "tag": "Kometa"}]},
        "102": {"librarySectionID": 1, "Label": [{"id": 41, "tag": "Favourites"}]},
        "103": {"librarySectionID": 1, "Label": [{"id": 40, "tag": "PMM"}]},
        "104": {"librarySectionID": 1, "Label": [{"id": 42, "tag": "Studio"}]},
        "105": {"librarySectionID": 1, "Label": [{"id": 42, "tag": "Studio"}, {"id": 33517, "tag": "Kometa"}]},
    }
    DEFAULT_ITEMS = {
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
        "104": [],
        "105": [],
    }

    # What /library/sections/<key>/all gives for movies, newest first (trimmed).
    TITLES = {
        "1": [
            {"ratingKey": "501", "type": "movie", "title": "Dune", "year": 2021, "thumb": "/library/metadata/501/thumb/1700000005", "Media": [{"videoResolution": "4k", "audioCodec": "truehd"}]},
            {"ratingKey": "502", "type": "movie", "title": "Dune Messiah", "year": 2026, "thumb": "/library/metadata/502/thumb/1700000006", "Media": [{"videoResolution": "1080", "audioCodec": "eac3"}]},
            {"ratingKey": "503", "type": "movie", "title": "Heat", "year": 1995},
        ]
    }

    # A title's full credits, as /library/metadata/<ratingKey> gives them (trimmed to the people).
    DEFAULT_CREDITS = {
        "501": {
            "Director": [{"id": 11, "tag": "Denis Villeneuve"}],
            "Writer": [{"id": 21, "tag": "Jon Spaihts"}, {"id": 11, "tag": "Denis Villeneuve"}],
            "Producer": [{"id": 31, "tag": "Mary Parent"}],
            "Role": [{"id": 41, "tag": "Timothée Chalamet"}, {"id": 42, "tag": "Zendaya"}, {"id": 43, "tag": "Rebecca Ferguson"}],
        },
        "502": {
            "Director": [{"id": 11, "tag": "Denis Villeneuve"}],
            "Writer": [{"id": 11, "tag": "Denis Villeneuve"}],
            "Producer": [{"id": 31, "tag": "Mary Parent"}],
            "Role": [{"id": 41, "tag": "Timothée Chalamet"}, {"id": 42, "tag": "Zendaya"}],
        },
        "503": {
            "Director": [{"id": 12, "tag": "Michael Mann"}],
            "Writer": [{"id": 12, "tag": "Michael Mann"}],
            "Role": [{"id": 44, "tag": "Al Pacino"}, {"id": 45, "tag": "Robert De Niro"}, {"id": 42, "tag": "Zendaya"}],
        },
    }

    # Tag values from /library/sections/<key>/<tag> (Plex 1.41).
    DEFAULT_TAGS = {
        "1": {
            "genre": [
                {"key": "Action", "title": "Action"},
                {"key": "Sci-Fi", "title": "Sci-Fi"},
                {"key": "Drama", "title": "Drama"},
            ],
            "contentRating": [
                {"key": "PG-13", "title": "PG-13"},
                {"key": "R", "title": "R"},
                {"key": "G", "title": "G"},
                {"key": "TV-G", "title": "TV-G"},
            ],
            "studio": [
                {"key": "Marvel Studios", "title": "Marvel Studios"},
                {"key": "Warner Bros.", "title": "Warner Bros."},
            ],
            "country": [
                {"key": "United States", "title": "United States"},
                {"key": "United Kingdom", "title": "United Kingdom"},
            ],
            "decade": [
                {"key": "2020", "title": "2020s"},
                {"key": "2010", "title": "2010s"},
                {"key": "1990", "title": "1990s"},
            ],
            "year": [
                {"key": "2026", "title": "2026"},
                {"key": "2021", "title": "2021"},
                {"key": "1995", "title": "1995"},
            ],
            "resolution": [
                {"key": "4k", "title": "4k"},
                {"key": "1080", "title": "1080"},
                {"key": "8k", "title": "8k"},
            ],
            "audioLanguage": [
                {"key": "en", "title": "English"},
                {"key": "fr", "title": "French"},
            ],
            "subtitleLanguage": [
                {"key": "en", "title": "English"},
                {"key": "es", "title": "Spanish"},
            ],
        },
        "2": {
            "network": [
                {"key": "HBO", "title": "HBO"},
                {"key": "Netflix", "title": "Netflix"},
            ],
            "genre": [
                {"key": "Comedy", "title": "Comedy"},
                {"key": "Drama", "title": "Drama"},
            ],
            "year": [
                {"key": "2020", "title": "2020"},
                {"key": "1999", "title": "1999"},
            ],
        },
    }

    # Counts for /library/sections/<key>/all with filter parameters.
    DEFAULT_TAG_COUNTS = {
        "1": {
            ("genre", "Action"): 5,
            ("genre", "Sci-Fi"): 2,
            ("genre", "Drama"): 1,
            ("contentRating", "PG-13"): 3,
            ("contentRating", "R"): 1,
            ("contentRating", "G"): 1,
            ("contentRating", "TV-G"): 2,
            ("studio", "Marvel Studios"): 4,
            ("studio", "Warner Bros."): 2,
            ("country", "United States"): 6,
            ("country", "United Kingdom"): 2,
            ("decade", "2020"): 2,
            ("decade", "2010"): 5,
            ("decade", "1990"): 1,
            ("year", "2026"): 1,
            ("year", "2021"): 1,
            ("year", "1995"): 1,
            ("resolution", "4k"): 1,
            ("resolution", "1080"): 1,
            ("resolution", "8k"): 1,
            ("audioLanguage", "en"): 5,
            ("audioLanguage", "fr"): 1,
            ("subtitleLanguage", "en"): 4,
            ("subtitleLanguage", "es"): 2,
        },
        "2": {
            ("network", "HBO"): 3,
            ("network", "Netflix"): 2,
            ("genre", "Comedy"): 2,
            ("genre", "Drama"): 1,
            ("year", "2020"): 1,
            ("year", "1999"): 1,
        },
    }

    def library(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")  # library, sections, <key>, <what>
        if parts == ["library", "sections"]:
            return httpx.Response(200, json={"MediaContainer": {"Directory": self.SECTIONS}})
        if len(parts) == 4 and parts[1] == "sections" and parts[2] in self.COLLECTIONS:
            key, what = parts[2], parts[3]
            if what in self.TAGS.get(key, {}):
                items = self.TAGS[key][what]
                return httpx.Response(200, json={"MediaContainer": {"size": len(items), "Directory": items}})
            if what == "collections":
                return httpx.Response(200, json={"MediaContainer": {"Metadata": self.COLLECTIONS[key]}})
            if what == "label":
                return httpx.Response(200, json={"MediaContainer": {"Directory": self.LABELS[key]}})
            if what == "all" and request.url.params.get("type") in ("1", "2") and "addedAt>>" not in request.url.params:
                if request.url.params.get("X-Plex-Container-Size", "0") != "0":  # a page of titles
                    title = request.url.params.get("title", "").lower()
                    found = [m for m in self.TITLES.get(key, []) if title in m["title"].lower()]
                    start, size = int(request.url.params.get("X-Plex-Container-Start", "0")), int(request.url.params["X-Plex-Container-Size"])
                    return httpx.Response(200, json={"MediaContainer": {"size": len(found[start : start + size]), "totalSize": len(found), "offset": start, "Metadata": found[start : start + size]}})
                counts = self.TAG_COUNTS.get(key, {})
                tag_params = ("genre", "contentRating", "studio", "country", "network", "decade", "year", "resolution", "audioLanguage", "subtitleLanguage")
                for tag_param in (*tag_params, *(f"episode.{t}" for t in ("resolution", "audioLanguage", "subtitleLanguage"))):
                    if tag_param in request.url.params:
                        val = request.url.params[tag_param]
                        cnt = counts.get((tag_param, val), 0)
                        return httpx.Response(200, json={"MediaContainer": {"size": 0, "totalSize": cnt, "Metadata": []}})
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
        if len(parts) == 3 and parts[1] == "metadata" and parts[2] in self.CREDITS:
            title = next(m for m in self.TITLES["1"] if m["ratingKey"] == parts[2])
            return httpx.Response(200, json={"MediaContainer": {"size": 1, "Metadata": [title | self.CREDITS[parts[2]]]}})
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
