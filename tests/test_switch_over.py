"""Moving over from Kometa, step 3: Switch over (backup, import, one save, one run), Undo and Export."""

from __future__ import annotations

import io
import json
import zipfile

from ruamel.yaml import YAML

from starr_studio import collections as col
from starr_studio.db import connect
from test_ready_made_routes import FINISHED, make_client, root, wait_for_flags, wait_for_run  # noqa: F401 (root is a fixture)

LISTS = "collections:\n  Dune:\n    tmdb_collection: 726871\n    collection_order: release\n  Dramas:\n    smart_filter:\n      any:\n        genre: Drama\n"


def setup_kometa(root, lists: str = LISTS, extra: str = "") -> dict[str, bytes]:
    config = root / "config"
    (config / "lists.yml").write_text(lists)
    (config / "kept.yml").write_text("collections:\n  Search:\n    tmdb_discover:\n      with_companies: 41077\n")
    text = (config / "config.yml").read_text().replace(
        "Movies: {}",
        f"Movies:\n    collection_files:\n    - file: {config / 'lists.yml'}\n    - file: {config / 'kept.yml'}\n    - default: basic\n{extra}",
    )
    (config / "config.yml").write_text(text)
    return {path.relative_to(config).as_posix(): path.read_bytes() for path in config.rglob("*") if path.is_file()}


def files(root) -> dict[str, bytes]:
    config = root / "config"
    return {path.relative_to(config).as_posix(): path.read_bytes() for path in config.rglob("*") if path.is_file()}


def rows(root) -> list[tuple[str, str, str]]:
    db = connect(root / "data" / "studio.db")
    try:
        return sorted((r["library"], r["category"], r["title"]) for r in db.execute("SELECT * FROM collections"))
    finally:
        db.close()


def test_switch_over_imports_writes_one_save_and_runs_just_those(root):
    before = setup_kometa(root)
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        assert client.post("/api/v1/import/switch-over", json={}).status_code == 422
        response = client.post("/api/v1/import/switch-over", json={"confirm": True})
        assert response.status_code == 200, response.text
        result = response.json()
        run = wait_for_run(client, result["run_id"])
        assert run["trigger"] == "switch_over"
        assert run["request"]["collections"] == sorted(["Dune", "Dramas", "Newly Released"])
        assert client.get("/api/v1/import/switch-over").json()["active"]["id"] == result["switch_over"]["id"]
        again = client.post("/api/v1/import/switch-over", json={"confirm": True})
        assert again.status_code == 409 and "already switched over" in again.json()["detail"]

    summary = result["switch_over"]
    assert (summary["imported"], summary["ready_made"], summary["libraries"]) == (2, 1, ["Movies"])
    assert (root / "data" / "switch-over" / summary["backup"]).is_file()

    after = files(root)
    config = YAML(typ="safe").load(after["config.yml"])
    entries = config["libraries"]["Movies"]["collection_files"]
    listed = [entry.get("file") or entry.get("default") for entry in entries]
    assert str(root / "config" / "lists.yml") not in listed and "basic" not in listed  # replaced
    assert str(root / "config" / "kept.yml") in listed  # kept, runs as before
    assert any(str(item).endswith("studio/Movies/built.yml") for item in listed)
    assert any(str(item).endswith("studio/Movies/basic.yml") for item in listed)
    assert after["lists.yml"] == before["lists.yml"] and after["kept.yml"] == before["kept.yml"]  # never edited
    built = YAML(typ="safe").load(after["studio/Movies/built.yml"])["collections"]
    assert built["Dune"]["tmdb_collection"] == 726871 and built["Dune"]["collection_order"] == "release"
    assert built["Dramas"]["smart_filter"] == {"any": {"genre": "Drama"}}
    assert rows(root) == [("Movies", "basic", "Newly Released"), ("Movies", "built", "Dramas"), ("Movies", "built", "Dune")]


def test_nothing_to_import_is_refused(root):
    setup_kometa(root, lists="collections:\n  Search:\n    tmdb_discover:\n      with_companies: 41077\n")
    config = root / "config"
    (config / "config.yml").write_text((config / "config.yml").read_text().replace("    - default: basic\n", ""))
    client, _plex, _m = make_client(root)
    with client:
        response = client.post("/api/v1/import/switch-over", json={"confirm": True})
    assert response.status_code == 409 and "Nothing to move over" in response.json()["detail"]


def test_a_refused_check_changes_nothing(root):
    before = setup_kometa(root, lists="collections:\n  BROKEN Dune:\n    tmdb_collection: 726871\n")
    client, _plex, _m = make_client(root)
    with client:
        response = client.post("/api/v1/import/switch-over", json={"confirm": True})
        assert response.status_code >= 400, response.text
        assert client.get("/api/v1/import/switch-over").json()["active"] is None
    after = files(root)
    assert after["config.yml"] == before["config.yml"]
    assert "studio/Movies/built.yml" not in after
    assert rows(root) == []


def test_undo_shows_what_it_loses_and_puts_everything_back(root):
    before = setup_kometa(root)
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        result = client.post("/api/v1/import/switch-over", json={"confirm": True}).json()
        wait_for_run(client, result["run_id"])
        db = connect(root / "data" / "studio.db")
        col.insert_built(db, "Movies", "later", "Added Later", {"source": {"kind": "filters"}})
        db.commit()
        db.close()

        preview = client.get("/api/v1/import/undo").json()
        assert preview["loses"]["added"] == [{"library": "Movies", "title": "Added Later"}]
        assert preview["files"] == ["config.yml"]  # only what Undo changes: lists.yml was never touched
        assert "studio/Movies/built.yml" in preview["removes"]

        assert client.post("/api/v1/import/undo", json={}).status_code == 422
        response = client.post("/api/v1/import/undo", json={"confirm": True})
        assert response.status_code == 200, response.text
        undone = response.json()
        assert undone["restored_files"] >= 1 and undone["backup"]
        assert client.get("/api/v1/import/switch-over").json()["active"] is None
        assert client.get("/api/v1/import/undo").status_code == 409

    after = files(root)
    assert after["config.yml"] == before["config.yml"]
    assert not any(path.startswith("studio/Movies/") for path in after)
    assert rows(root) == []


def test_export_is_a_working_kometa_setup(root):
    setup_kometa(root)
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        result = client.post("/api/v1/import/switch-over", json={"confirm": True}).json()
        wait_for_run(client, result["run_id"])
        response = client.get("/api/v1/import/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    names = set(zipfile.ZipFile(io.BytesIO(response.content)).namelist())
    assert {"README.txt", "config.yml", "kept.yml", "studio/Movies/built.yml", "studio/Movies/basic.yml"} <= names
    assert "lists.yml" not in names  # no longer listed in config.yml


def test_report_and_switch_over_without_config(root):
    (root / "config" / "config.yml").unlink()
    client, _plex, _m = make_client(root)
    with client:
        assert client.get("/api/v1/import").json()["config"] is False
        response = client.post("/api/v1/import/switch-over", json={"confirm": True})
    assert response.status_code == 409
    assert json.dumps(response.json())  # a plain message
