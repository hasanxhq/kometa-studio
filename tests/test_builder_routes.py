"""The collection builder: fields, values, preview, and collections built from a smart filter."""

from __future__ import annotations

from ruamel.yaml import YAML

from fakeplex import FakePlex
from kometa_studio import collections as col
from test_ready_made_routes import make_client, root, wait_for_flags, wait_for_run, wait_for_task  # noqa: F401 (root is a fixture)

ACTION = {"match": "all", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}]}


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
    with make_client(root)[0] as client:
        wait_for_task(client, "ready_made_counts")
        detail = client.get("/api/v1/ready-made/libraries/Movies/categories/genre").json()
        assert detail["customisable"] is True
        assert client.get("/api/v1/ready-made/libraries/Movies/categories/basic").json()["customisable"] is False
        action = next(e for e in detail["collections"] if e["key"] == "Action")
        draft = client.get(
            "/api/v1/ready-made/libraries/Movies/categories/genre/customise", params={"block": action["block"], "key": "Action"}
        ).json()
        assert draft["title"] == "Action Movies"
        assert draft["filters"] == {"match": "all", "rules": [{"field": "genre", "modifier": "", "value": ["Action"]}]}
        chart = client.get("/api/v1/ready-made/libraries/Movies/categories/basic/customise", params={"block": "", "key": "Newly Released"})
        assert chart.status_code == 422
