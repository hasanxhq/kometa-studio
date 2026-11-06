"""The collection builder: fields, values, preview, and collections built from a smart filter."""

from __future__ import annotations

import hashlib
import io

from PIL import Image
from ruamel.yaml import YAML

from fakeplex import FakePlex
from starr_studio import collections as col
from starr_studio.default_covers import DEFAULT_IMAGES
from test_ready_made_routes import make_client, root, wait_for_flags, wait_for_run, wait_for_task  # noqa: F401 (root is a fixture)

ACTION = {"match": "all", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}]}


def tiny_image(fmt: str = "PNG", color: str = "red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 3), color).save(buf, fmt)
    return buf.getvalue()


def body(title: str = "Action Picks", filters: dict | None = None, **extra) -> dict:
    return {
        "library": "Movies",
        "title": title,
        "filters": filters or ACTION,
        "sort_by": None,
        "limit": None,
        "visible": {"library": True, "home": True, "shared": False},
        "minimum_items": 2,
        "summary": "Things that explode",
        "sort_title": None,
        "poster": None,
    } | extra


def built_file(root) -> dict:
    return YAML(typ="safe").load((root / "config" / "studio" / "Movies" / "built.yml").read_text())


def test_fields_and_values_come_from_kometa_and_plex(root):
    with make_client(root)[0] as client:
        fields = client.get("/api/v1/builder/fields", params={"library": "Movies"}).json()
        assert fields["library_type"] == "movie"
        genre = next(f for f in fields["fields"] if f["key"] == "genre")
        assert genre["kind"] == "tag" and genre["listable"] is True and {"key": "", "label": genre["modifiers"][0]["label"]} == genre["modifiers"][0]
        assert any(s["key"] == "release.desc" for s in fields["sorts"])
        values = client.get("/api/v1/builder/values", params={"library": "Movies", "field": "genre"}).json()["values"]
        assert {"key": "Action", "title": "Action"} in values


def test_preview_asks_plex_with_kometas_query_and_reports_problems(root):
    client, plex, _ = make_client(root)
    with client:
        empty = client.post("/api/v1/builder/preview", json={"library": "Movies", "filters": {"match": "all", "rules": []}}).json()
        assert empty["count"] == 0 and empty["problems"]
        preview = client.post("/api/v1/builder/preview", json={"library": "Movies", "filters": ACTION, "sort_by": None}).json()
        assert preview["problems"] == [] and preview["count"] >= 1
        assert {"rating_key", "title", "year", "thumb"} <= set(preview["items"][0])
        asked = [r for r in plex.requests if r.url.path == "/library/sections/1/all" and r.url.params.get("X-Plex-Container-Size") == "30"]
        assert asked and "genre" in str(asked[-1].url)


def test_create_writes_a_smart_collection_checks_it_and_runs_only_it(root):
    client, _, _ = make_client(root)
    with client:
        wait_for_flags(client)
        made = client.post("/api/v1/collections", json=body())
        assert made.status_code == 201, made.text
        built = made.json()
        assert built["title"] == "Action Picks" and built["filters"] == ACTION and built["visible"]["home"] is True
        collection = built_file(root)["collections"]["Action Picks"]
        assert collection["smart_filter"] == {"all": {"genre": ["Action"]}}
        assert collection["label"] == "Studio" and collection["minimum_items"] == 2 and collection["summary"] == "Things that explode"
        assert collection["visible_home"] is True and collection["visible_shared"] is False
        assert "studio/Movies/built.yml" in (root / "config" / "config.yml").read_text()
        run = wait_for_run(client, built["run_id"])
        assert run["trigger"] == "builder" and run["request"]["collections"] == ["Action Picks"] and run["request"]["libraries"] == ["Movies"]
        listed = client.get("/api/v1/collections", params={"library": "Movies"}).json()["collections"]
        assert [c["id"] for c in listed] == [built["id"]]
        # Not a ready-made category: the gallery doesn't show it.
        assert all(c["name"] != "built" for c in client.get("/api/v1/ready-made/libraries/Movies").json()["categories"])


def test_bad_filters_and_taken_names_are_refused(root):
    plex = FakePlex()
    plex.add_collection("1", "Hand Made", labels=[], items=2)
    client, _, _ = make_client(root, plex)
    with client:
        wait_for_flags(client)
        bad = client.post("/api/v1/collections", json=body(filters={"match": "all", "rules": [{"field": "nope", "modifier": "", "value": "x"}]}))
        assert bad.status_code == 422 and bad.json()["detail"]["problems"]
        taken = client.post("/api/v1/collections", json=body(title="Hand Made"))
        assert taken.status_code == 409 and "didn't make" in taken.json()["detail"]["message"]
        assert client.post("/api/v1/collections", json=body()).status_code == 201
        again = client.post("/api/v1/collections", json=body(title="action picks"))
        assert again.status_code == 409 and "already has" in again.json()["detail"]["message"]
        assert col.built_rows(client.app.state.db, "Movies")[0]["title"] == "Action Picks"


def test_rename_removes_the_old_studio_collection_and_delete_removes_it(root):
    plex = FakePlex()
    client, _, _ = make_client(root, plex)
    with client:
        wait_for_flags(client)
        built = client.post("/api/v1/collections", json=body()).json()
        wait_for_run(client, built["run_id"])
        old_key = plex.add_collection("1", "Action Picks", labels=["Studio"], items=5)  # what Kometa made
        renamed = client.put(f"/api/v1/collections/{built['id']}", json=body(title="Big Bangs")).json()
        assert renamed["title"] == "Big Bangs" and old_key in plex.deletions
        assert list(built_file(root)["collections"]) == ["Big Bangs"]
        wait_for_run(client, renamed["run_id"])

        new_key = plex.add_collection("1", "Big Bangs", labels=["Studio"], items=5)
        gone = client.delete(f"/api/v1/collections/{built['id']}").json()
        assert gone == {"removed": True, "reason": None} and new_key in plex.deletions
        assert not (root / "config" / "studio" / "Movies" / "built.yml").exists()
        assert "studio/Movies/built.yml" not in (root / "config" / "config.yml").read_text()
        assert client.get(f"/api/v1/collections/{built['id']}").status_code == 404


def test_delete_never_touches_a_collection_studio_didnt_make(root):
    plex = FakePlex()
    client, _, _ = make_client(root, plex)
    with client:
        wait_for_flags(client)
        built = client.post("/api/v1/collections", json=body()).json()
        wait_for_run(client, built["run_id"])
        theirs = plex.add_collection("1", "Action Picks", labels=[], items=5)
        gone = client.delete(f"/api/v1/collections/{built['id']}").json()
        assert gone["removed"] is False and "no Studio label" in gone["reason"] and theirs not in plex.deletions


def test_a_ready_made_plex_collection_opens_in_the_builder(root):
    client, plex, _ = make_client(root)
    with client:
        wait_for_task(client, "ready_made_counts")
        detail = client.get("/api/v1/ready-made/libraries/Movies/categories/genre").json()
        assert detail["customisable"] is True
        assert client.get("/api/v1/ready-made/libraries/Movies/categories/basic").json()["customisable"] is False
        action = next(e for e in detail["collections"] if e["key"] == "Action")
        draft = client.get(
            "/api/v1/ready-made/libraries/Movies/categories/genre/customise", params={"block": action["block"], "key": "Action"}
        ).json()
        assert draft["title"] == "Action Movies"
        assert draft["filters"] == {"match": "any", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}]}
        assert draft["poster"] == {"kind": "url", "url": f"{DEFAULT_IMAGES}/genre/Action.jpg"}
        # The fixture's content_rating block: G with its TV-G addon, so either one.
        rating = client.get("/api/v1/ready-made/libraries/Movies/categories/content_rating/customise", params={"block": "Ratings", "key": "G"})
        assert rating.status_code == 200, rating.text
        assert rating.json()["filters"] == {"match": "any", "rules": [{"field": "content_rating", "modifier": "", "value": ["G", "TV-G"]}]}
        assert rating.json()["poster"] is None  # fixture has no image map we can resolve
        # People get the tmdb_person template's People-Images poster.
        person = client.get(
            "/api/v1/ready-made/libraries/Movies/categories/director/customise", params={"block": "Directors", "key": "Denis Villeneuve"}
        ).json()
        assert person["poster"] == {
            "kind": "url",
            "url": "https://raw.githubusercontent.com/Kometa-Team/People-Images-bw/master/D/Images/Denis%20Villeneuve.jpg",
        }
        # An add-on the library doesn't have is left out, as Kometa does.
        plex.TAGS["1"]["contentRating"] = [t for t in plex.TAGS["1"]["contentRating"] if t["key"] != "TV-G"]
        alone = client.get("/api/v1/ready-made/libraries/Movies/categories/content_rating/customise", params={"block": "Ratings", "key": "G"}).json()
        assert alone["filters"]["rules"][0]["value"] == ["G"]
        chart = client.get("/api/v1/ready-made/libraries/Movies/categories/basic/customise", params={"block": "", "key": "Newly Released"})
        assert chart.status_code == 422


def test_poster_upload_is_content_addressed_and_type_checked(root):
    client, _, _ = make_client(root)
    with client:
        png = tiny_image("PNG")
        ok = client.post("/api/v1/builder/posters", content=png, headers={"Content-Type": "image/png"})
        assert ok.status_code == 200, ok.text
        path = ok.json()["path"]
        assert ok.json() == {"kind": "file", "path": path}
        name = path.rsplit("/", 1)[-1]
        assert name == f"{hashlib.sha256(png).hexdigest()[:16]}.png"
        stored = root / "config" / path
        assert stored.read_bytes() == png
        served = client.get(f"/api/v1/builder/posters/{name}")
        assert served.status_code == 200 and served.content == png and served.headers["content-type"].startswith("image/png")

        for fmt, media in (("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
            data = tiny_image(fmt)
            got = client.post("/api/v1/builder/posters", content=data, headers={"Content-Type": media})
            assert got.status_code == 200 and got.json()["kind"] == "file"

        fake = client.post("/api/v1/builder/posters", content=b"not an image but called.png", headers={"Content-Type": "image/png"})
        assert fake.status_code == 422 and "JPEG" in fake.json()["detail"]

        huge = b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)
        assert client.post("/api/v1/builder/posters", content=huge, headers={"Content-Type": "image/png"}).status_code == 422


def age(*paths) -> None:
    """Make uploads older than the grace period that keeps them for editors still open."""
    import os
    import time

    for path in paths:
        old = time.time() - 2 * 3600
        os.utime(path, (old, old))


def test_create_writes_file_or_url_poster_and_cleanup_drops_unused(root):
    client, _, _ = make_client(root)
    with client:
        wait_for_flags(client)
        png = tiny_image("PNG")
        uploaded = client.post("/api/v1/builder/posters", content=png, headers={"Content-Type": "image/png"}).json()
        url = "https://example.com/poster.jpg"
        made = client.post("/api/v1/collections", json=body(poster=uploaded))
        assert made.status_code == 201, made.text
        collection = built_file(root)["collections"]["Action Picks"]
        assert collection["file_poster"].endswith(uploaded["path"])
        assert "url_poster" not in collection
        assert made.json()["poster"] == uploaded

        linked = client.post("/api/v1/collections", json=body(title="Linked", poster={"kind": "url", "url": url}))
        assert linked.status_code == 201, linked.text
        assert built_file(root)["collections"]["Linked"]["url_poster"] == url
        assert "file_poster" not in built_file(root)["collections"]["Linked"]

        plain = client.post("/api/v1/collections", json=body(title="Plain"))
        assert plain.status_code == 201
        assert "file_poster" not in built_file(root)["collections"]["Plain"]
        assert "url_poster" not in built_file(root)["collections"]["Plain"]

        # An upload no collection uses yet survives other saves for a while: another editor may still be open.
        pending = client.post("/api/v1/builder/posters", content=tiny_image("PNG", color="blue"), headers={"Content-Type": "image/png"}).json()
        client.put(f"/api/v1/collections/{plain.json()['id']}", json=body(title="Plain"))
        assert (root / "config" / pending["path"]).is_file()

        # Swap the first collection's poster for a URL; once old enough, the unreferenced files are removed.
        age(root / "config" / uploaded["path"], root / "config" / pending["path"])
        changed = client.put(f"/api/v1/collections/{made.json()['id']}", json=body(poster={"kind": "url", "url": url}))
        assert changed.status_code == 200, changed.text
        assert not (root / "config" / uploaded["path"]).exists()
        assert not (root / "config" / pending["path"]).exists()

        other = tiny_image("JPEG")
        second = client.post("/api/v1/builder/posters", content=other, headers={"Content-Type": "image/jpeg"}).json()
        with_file = client.put(f"/api/v1/collections/{made.json()['id']}", json=body(poster=second))
        assert with_file.status_code == 200
        assert (root / "config" / second["path"]).is_file()
        age(root / "config" / second["path"])
        client.delete(f"/api/v1/collections/{made.json()['id']}")
        assert not (root / "config" / second["path"]).exists()


def test_preview_keeps_plexs_or_grouping_in_order(root):
    # httpx regroups repeated keys, which would turn push=1&genre=A&or=1&genre=B&pop=1 into an AND.
    client, plex, _ = make_client(root)
    with client:
        spec = {"match": "any", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}, {"field": "genre", "modifier": "", "value": ["Drama"]}]}
        assert client.post("/api/v1/builder/preview", json={"library": "Movies", "filters": spec}).json()["problems"] == []
        asked = [r for r in plex.requests if r.url.path == "/library/sections/1/all" and r.url.params.get("X-Plex-Container-Size") == "30"]
        assert "push=1&genre=Action&or=1&genre=Drama&pop=1" in str(asked[-1].url)


def test_retry_builds_a_failed_collection_again(root):
    client, _, _ = make_client(root)
    with client:
        wait_for_flags(client)
        built = client.post("/api/v1/collections", json=body()).json()
        wait_for_run(client, built["run_id"])
        db = client.app.state.db
        with db:
            db.execute("UPDATE collections SET plex_exists = 0, last_error = ? WHERE id = ?", ("TMDb Error: Connection reset", built["id"]))
        assert client.get(f"/api/v1/collections/{built['id']}").json()["state"] == "failed"
        retried = client.post(f"/api/v1/collections/{built['id']}/retry")
        assert retried.status_code == 200, retried.text
        again = retried.json()
        assert again["run_id"] != built["run_id"] and again["state"] in ("queued", "building")
        run = wait_for_run(client, again["run_id"])
        assert run["trigger"] == "builder" and run["request"]["collections"] == ["Action Picks"]
        # Already building: refused rather than queued twice.
        with db:
            db.execute("UPDATE runs SET status = 'queued' WHERE id = ?", (again["run_id"],))
        busy = client.post(f"/api/v1/collections/{built['id']}/retry")
        assert busy.status_code == 409 and "already being built" in busy.json()["detail"]["message"]
        assert client.post("/api/v1/collections/9999/retry").status_code == 404


def test_a_ready_made_previews_before_its_built(root):
    """Opening a Ready-made tile: a Plex filter runs against Plex, a chart reads its list, anything else says why."""
    imdb = root / "kometa" / "defaults" / "chart" / "imdb.yml"
    imdb.write_text(
        "templates:\n  imdb_chart:\n    imdb_chart: <<chart>>_<<library_type>>s\n"
        "collections:\n  IMDb Top 250:\n    variables:\n      key: top\n    template:\n      - name: imdb_chart\n        chart: top\n      - name: shared\n"
    )
    client, plex, _ = make_client(root)
    with client:
        wait_for_task(client, "ready_made_counts")
        url = "/api/v1/ready-made/libraries/Movies/categories/{}/preview"

        genre = client.get(url.format("genre"), params={"block": "Genre", "key": "Action"}).json()
        assert genre["previewable"] is True and genre["problems"] == []
        assert genre["in_library_count"] >= 1 and genre["missing_count"] == 0
        assert {"rating_key", "title", "year", "thumb"} <= set(genre["in_library"][0])
        asked = [r for r in plex.requests if r.url.path == "/library/sections/1/all" and "genre" in str(r.url)]
        assert asked, "the default's own smart filter goes to Plex"

        # A person is a Plex filter too (FakePlex has no director tags, so Plex's answer is a problem, not a why).
        person = client.get(url.format("director"), params={"block": "Directors", "key": "Denis Villeneuve"}).json()
        assert person["previewable"] is True and person["why"] is None
        assert person["problems"] == ["Tag value 'Denis Villeneuve' not found for field 'director'"]

        # IMDb is a list only Kometa reads: the chart resolves to imdb_chart: top_movies, which says so.
        chart = client.get(url.format("imdb"), params={"key": "IMDb Top 250"}).json()
        assert chart["previewable"] is False
        assert chart["skipped"] == [{"label": "IMDb Top 250", "why": chart["why"]}]

        # Nothing Studio can read before the build: the fixture's basic chart names no list.
        basic = client.get(url.format("basic"), params={"key": "Newly Released"}).json()
        assert basic["previewable"] is False and "Build it to see" in basic["why"]
