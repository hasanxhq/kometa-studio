"""Upload a collection file: same import as Move over, then add it to a library."""

from __future__ import annotations

from ruamel.yaml import YAML

from starr_studio.db import connect
from test_ready_made_routes import make_client, root, wait_for_flags, wait_for_run  # noqa: F401 (root is a fixture)

IMPORTABLE = (
    "collections:\n"
    "  Dune:\n"
    "    tmdb_collection: 726871\n"
    "    collection_order: release\n"
    "  Dramas:\n"
    "    smart_filter:\n"
    "      any:\n"
    "        genre: Drama\n"
)

MIXED = (
    "collections:\n"
    "  Dune:\n"
    "    tmdb_collection: 726871\n"
    "  Search:\n"
    "    plex_search:\n"
    "      any:\n"
    "        studio: A24\n"
)

BROKEN = "collections:\n  BROKEN Dune:\n    tmdb_collection: 726871\n"


def rows(root) -> list[tuple[str, str, str]]:
    db = connect(root / "data" / "studio.db")
    try:
        return sorted((r["library"], r["category"], r["title"]) for r in db.execute("SELECT * FROM collections"))
    finally:
        db.close()


def upload(client, library: str, text: str, filename: str = "mine.yml"):
    return client.post(
        f"/api/v1/import/upload?library={library}",
        content=text.encode("utf-8"),
        headers={"Content-Type": "application/x-yaml", "X-Filename": filename},
    )


def test_replace_imports_writes_built_runs_just_those_and_leaves_config_alone(root):
    before_config = (root / "config" / "config.yml").read_bytes()
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        staged = upload(client, "Movies", IMPORTABLE, "lists.yml")
        assert staged.status_code == 200, staged.text
        body = staged.json()
        assert body["library"] == "Movies"
        assert body["file"]["action"] == "replace"
        assert body["file"]["value"] == "lists.yml"
        assert {c["name"] for c in body["file"]["collections"]} == {"Dune", "Dramas"}
        token = body["token"]
        assert (root / "data" / "uploads" / f"{token}.yml").is_file()

        added = client.post(f"/api/v1/import/upload/{token}/add", json={"library": "Movies", "confirm": True})
        assert added.status_code == 200, added.text
        result = added.json()
        assert result["action"] == "replace"
        assert sorted(result["imported"]) == ["Dramas", "Dune"]
        assert result["kept_file"] is None
        run = wait_for_run(client, result["run_id"])
        assert run["trigger"] == "upload"
        assert run["request"]["collections"] == sorted(["Dune", "Dramas"])
        assert run["request"]["files"] == []

    assert not (root / "data" / "uploads" / f"{token}.yml").exists()
    assert (root / "config" / "config.yml").read_bytes() != before_config  # studio entry added
    assert not (root / "config" / "uploads").exists()  # replace never copies into Kometa's folder
    built = YAML(typ="safe").load((root / "config" / "studio" / "Movies" / "built.yml").read_text())["collections"]
    assert built["Dune"]["tmdb_collection"] == 726871
    assert built["Dramas"]["smart_filter"] == {"any": {"genre": "Drama"}}
    assert rows(root) == [("Movies", "built", "Dramas"), ("Movies", "built", "Dune")]


def test_keep_copies_whole_file_lists_it_unchanged(root):
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        staged = upload(client, "Movies", MIXED, "mixed.yml")
        assert staged.status_code == 200, staged.text
        assert staged.json()["file"]["action"] == "keep"
        token = staged.json()["token"]
        original = MIXED.encode("utf-8")

        added = client.post(f"/api/v1/import/upload/{token}/add", json={"library": "Movies", "confirm": True})
        assert added.status_code == 200, added.text
        result = added.json()
        assert result["action"] == "keep"
        assert result["imported"] == []
        assert result["kept_file"] == "uploads/mixed.yml"
        run = wait_for_run(client, result["run_id"])
        assert run["trigger"] == "upload"
        assert run["request"]["collections"] == []
        assert any(path.endswith("uploads/mixed.yml") for path in run["request"]["files"])

    kept = root / "config" / "uploads" / "mixed.yml"
    assert kept.read_bytes() == original
    config = YAML(typ="safe").load((root / "config" / "config.yml").read_text())
    entries = config["libraries"]["Movies"]["collection_files"]
    listed = [entry.get("file") for entry in entries]
    assert any(str(item).endswith("uploads/mixed.yml") for item in listed)
    assert rows(root) == []  # kept file: no builder rows


def test_broken_file_changes_nothing(root):
    before = (root / "config" / "config.yml").read_bytes()
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        # Mixed file with BROKEN so action is keep (plex_search) and the copy is refused by Kometa's check.
        text = "collections:\n  BROKEN Search:\n    plex_search:\n      any:\n        studio: A24\n"
        staged = upload(client, "Movies", text, "broken.yml")
        assert staged.status_code == 200
        token = staged.json()["token"]
        added = client.post(f"/api/v1/import/upload/{token}/add", json={"library": "Movies", "confirm": True})
        assert added.status_code >= 400, added.text
        # Replace path: all-importable BROKEN title.
        staged2 = upload(client, "Movies", BROKEN, "broken2.yml")
        token2 = staged2.json()["token"]
        added2 = client.post(f"/api/v1/import/upload/{token2}/add", json={"library": "Movies", "confirm": True})
        assert added2.status_code >= 400, added2.text

    assert (root / "config" / "config.yml").read_bytes() == before
    assert not (root / "config" / "uploads").exists() or not any((root / "config" / "uploads").iterdir())
    assert not (root / "config" / "studio" / "Movies" / "built.yml").exists()
    assert rows(root) == []


def test_bad_input_refused(root):
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        assert upload(client, "NoSuch", IMPORTABLE).status_code == 404
        assert upload(client, "Movies", "just a string").status_code == 422
        assert upload(client, "Movies", "- not\n- a\n- mapping\n").status_code == 422
        too_big = "x" * (1024 * 1024 + 1)
        assert upload(client, "Movies", too_big).status_code == 422
        bad_utf = client.post(
            "/api/v1/import/upload?library=Movies",
            content=b"\xff\xfe collections: {}\n",
            headers={"Content-Type": "text/plain", "X-Filename": "bad.yml"},
        )
        assert bad_utf.status_code == 422


def test_unknown_token_404(root):
    client, _plex, _m = make_client(root)
    with client:
        wait_for_flags(client)
        response = client.post("/api/v1/import/upload/0123456789abcdef/add", json={"library": "Movies", "confirm": True})
        assert response.status_code == 404
