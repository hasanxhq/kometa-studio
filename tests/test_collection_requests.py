"""Download missing: collections request the titles they lack, when saved and after each run."""

from __future__ import annotations

import asyncio

from ruamel.yaml import YAML

from starr_studio import collection_requests as cr
from starr_studio import collections as col
from starr_studio.kometa_command import RunRequest
from starr_studio.requesting import RequestOutcome, RequestSettings, save_settings
from test_builder_routes import body as filter_body
from test_list_sources import tmdb_client
from test_ready_made_routes import root, wait_for_flags, wait_for_run  # noqa: F401 (root is a fixture)

DUNE_SOURCE = {"kind": "list", "builder": "tmdb_collection", "value": "131296", "label": "Dune Collection"}


def dune(**extra) -> dict:
    return filter_body("Dune", filters={"match": "all", "rules": []}, sort_by="release") | {"source": DUNE_SOURCE} | extra


def record_requests(client) -> list:
    """Swap the request service's request() for one that notes what was asked, so no app is called."""
    calls: list = []

    async def fake(items, library, collection_id, now, cap=None, profile=None):
        call = {"items": [i.item for i in items], "library": library, "collection_id": collection_id, "cap": cap}
        if profile is not None:
            call["profile"] = profile
        calls.append(call)
        return RequestOutcome(requested=len(items))

    client.app.state.requests.request = fake
    return calls


def requests_on(client, **settings) -> None:
    save_settings(client.app.state.db, RequestSettings(enabled=True, **settings))


def test_download_missing_needs_requests_on_and_a_list(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        off = client.post("/api/v1/collections", json=dune(download_missing=True))
        assert off.status_code == 422 and "Settings → Requests" in off.json()["detail"]["message"]
        requests_on(client)
        smart = client.post("/api/v1/collections", json=filter_body("Smart", download_missing=True))
        assert smart.status_code == 422 and "no missing titles" in smart.json()["detail"]["problems"][0]


def test_a_list_collection_requests_its_preview_missing_after_saving(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        requests_on(client, confirm_over=0)
        calls = record_requests(client)
        # More than confirm_over: asked first, nothing saved or requested.
        ask = client.post("/api/v1/collections", json=dune(download_missing=True, request_cap=3))
        assert ask.status_code == 409 and ask.json()["detail"]["needs_confirm"] is True and ask.json()["detail"]["count"] == 1
        assert calls == [] and col.built_rows(client.app.state.db, "Movies") == []

        made = client.post("/api/v1/collections", json=dune(download_missing=True, request_cap=3, confirm_requests=True))
        assert made.status_code == 201, made.text
        built = made.json()
        assert built["download_missing"] is True and built["request_cap"] == 3
        assert calls == [{"items": ["tmdb-movie:693134"], "library": "Movies", "collection_id": built["id"], "cap": 3}]
        assert set(built["requests"]) == {"waiting", "requested", "downloading", "imported", "failed"}
        wait_for_run(client, built["run_id"])

        # Editing it again doesn't ask for titles Studio has already asked for.
        db = client.app.state.db
        with db:
            db.execute(
                "INSERT INTO requests (item, media, library, collection_id, via, status, requested_at, updated_at) VALUES ('tmdb-movie:693134', 'movie', 'Movies', ?, 'radarr', 'requested', 't', 't')",
                (built["id"],),
            )
        again = client.put(f"/api/v1/collections/{built['id']}", json=dune(download_missing=True, request_cap=3))
        assert again.status_code == 200, again.text
        assert len(calls) == 1 and again.json()["requests"]["requested"] == 1


def test_requests_turned_off_later_dont_block_editing(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        requests_on(client)
        record_requests(client)
        built = client.post("/api/v1/collections", json=dune(download_missing=True)).json()
        wait_for_run(client, built["run_id"])
        save_settings(client.app.state.db, RequestSettings(enabled=False))
        edited = client.put(f"/api/v1/collections/{built['id']}", json=dune(download_missing=True, summary="Spice"))
        assert edited.status_code == 200 and edited.json()["download_missing"] is True


def _wanted(db, collection: str, *items: str) -> None:
    with db:
        db.executemany(
            "INSERT INTO wanted (library, collection, item, title, seen_at) VALUES ('Movies', ?, ?, ?, '2026-11-05T00:00:00Z')",
            [(collection, item, item.upper()) for item in items],
        )


def test_after_a_run_a_few_are_requested_and_many_wait(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        requests_on(client, confirm_over=2)
        calls = record_requests(client)
        db = client.app.state.db
        built = client.post("/api/v1/collections", json=dune()).json()
        wait_for_run(client, built["run_id"])
        with db:
            cr.set_download_missing(db, [built["id"]], True, 5)
        config = root / "config" / "config.yml"
        assert "save_report" not in config.read_text()

        hook = cr.MissingRequester(db, client.app.state.writer, client.app.state.requests)
        said: list[str] = []
        request = RunRequest(mode="collections", libraries=["Movies"], collections=["Dune"])

        async def run(fill):
            after = await hook.before_run(request, said.append)
            fill()
            await after()

        asyncio.run(run(lambda: _wanted(db, "Dune", "tmdb-movie:1", "tmdb-movie:2")))
        assert YAML(typ="safe").load(config.read_text())["settings"]["save_report"] is True  # Studio turned the report on
        assert calls == [{"items": ["tmdb-movie:1", "tmdb-movie:2"], "library": "Movies", "collection_id": built["id"], "cap": 5}]

        # Asked-for titles count as asked; then three new ones are more than confirm_over: they wait.
        with db:
            db.executemany(
                "INSERT INTO requests (item, media, library, collection_id, via, status, requested_at, updated_at) VALUES (?, 'movie', 'Movies', ?, 'radarr', 'failed', 't', 't')",
                [("tmdb-movie:1", built["id"]), ("tmdb-movie:2", built["id"])],
            )
        asyncio.run(run(lambda: _wanted(db, "Dune", "tmdb-movie:3", "tmdb-movie:4", "tmdb-movie:5")))
        assert len(calls) == 1 and any("wait for your go-ahead" in line for line in said)
        card = client.get(f"/api/v1/collections/{built['id']}").json()["requests"]
        assert card["waiting"] == 3 and card["failed"] == 2

        # The go-ahead requests them.
        ok = client.post(f"/api/v1/collections/{built['id']}/request-missing")
        assert ok.status_code == 200 and ok.json()["requested"] == 3
        assert calls[-1]["items"] == ["tmdb-movie:3", "tmdb-movie:4", "tmdb-movie:5"]

        # Requests off: the hook does nothing.
        save_settings(db, RequestSettings(enabled=False))
        assert asyncio.run(hook.before_run(request, said.append)) is None


def test_turning_download_missing_on_and_off(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        built = client.post("/api/v1/collections", json=dune()).json()
        smart = client.post("/api/v1/collections", json=filter_body("Smart")).json()
        assert client.put(f"/api/v1/collections/{built['id']}/download-missing", json={"download_missing": True}).status_code == 422
        requests_on(client)
        assert client.put(f"/api/v1/collections/{smart['id']}/download-missing", json={"download_missing": True}).status_code == 422
        on = client.put(f"/api/v1/collections/{built['id']}/download-missing", json={"download_missing": True})
        assert on.status_code == 200 and on.json()["download_missing"] is True
        assert YAML(typ="safe").load((root / "config" / "config.yml").read_text())["settings"]["save_report"] is True
        off = client.put(f"/api/v1/collections/{built['id']}/download-missing", json={"download_missing": False})
        assert off.json()["download_missing"] is False
        assert client.put("/api/v1/collections/9999/download-missing", json={"download_missing": False}).status_code == 404


def test_ready_made_build_marks_its_picks(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        pick = {"library": "Movies", "add": [{"category": "basic", "block": "", "key": "Newly Released"}], "remove": [], "dry_run": False, "download_missing": True}
        assert client.post("/api/v1/ready-made/build", json=pick).status_code == 422
        requests_on(client)
        built = client.post("/api/v1/ready-made/build", json=pick)
        assert built.status_code == 200, built.text
        row = col.rows(client.app.state.db, "Movies", "basic")[0]
        assert row["download_missing"] == 1
        tile = next(e for e in client.get("/api/v1/ready-made/libraries/Movies/categories/basic").json()["collections"] if e["key"] == "Newly Released")
        assert tile["download_missing"] is True and tile["requests"]["waiting"] == 0


def test_a_collection_keeps_its_own_quality_profile_for_requests(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        requests_on(client)
        calls = record_requests(client)
        made = client.post("/api/v1/collections", json=dune(download_missing=True, request_profile="Ultra-HD"))
        assert made.status_code == 201, made.text
        built = made.json()
        assert built["request_profile"] == "Ultra-HD"
        assert calls[0]["profile"] == "Ultra-HD"
        wait_for_run(client, built["run_id"])

        # Back to the default: saved without one.
        again = client.put(f"/api/v1/collections/{built['id']}", json=dune(download_missing=True))
        assert again.status_code == 200, again.text
        assert again.json()["request_profile"] is None


def test_a_requested_title_reaching_plex_rebuilds_just_its_collection_once(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        requests_on(client)
        record_requests(client)
        made = client.post("/api/v1/collections", json=dune(download_missing=True)).json()
        wait_for_run(client, made["run_id"])
        db, runner = client.app.state.db, client.app.state.runner
        queued_at = db.execute("SELECT queued_at FROM runs WHERE id = ?", (made["run_id"],)).fetchone()[0]

        def labelled(item: str, at: str) -> None:
            with db:
                db.execute(
                    "INSERT INTO requests (item, media, library, collection_id, via, status, requested_at, updated_at, imported_at, labelled_at)"
                    " VALUES (?, 'movie', 'Movies', ?, 'radarr', 'imported', ?, ?, ?, ?)",
                    (item, made["id"], at, at, at, at),
                )

        # Reached Plex before the last build was queued: that build already had it.
        labelled("tmdb-movie:1", "2000-01-01T00:00:00Z")
        assert cr.rebuild_arrived(db, runner) == []

        labelled("tmdb-movie:693134", "2999-01-01T00:00:00Z")
        assert queued_at < "2999"
        (run_id,) = cr.rebuild_arrived(db, runner)
        run = db.execute("SELECT request, trigger FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert RunRequest.model_validate_json(run["request"]).collections == ["Dune"]
        assert run["trigger"] == "requests"
        assert col.built_row(db, made["id"])["last_run_id"] == run_id
        wait_for_run(client, run_id)


def test_a_check_rebuilds_after_labelling(root):
    with tmdb_client(root, []) as client:
        wait_for_flags(client)
        service = client.app.state.requests
        assert service.after_labelling is not None  # the app wires it to rebuild_arrived
        order: list[str] = []

        async def refresh(now):
            order.append("refresh")
            return {}

        service.refresh = refresh
        service.after_labelling = lambda: order.append("after")
        assert client.post("/api/v1/requests/refresh").status_code == 200
        assert order == ["refresh", "after"]
