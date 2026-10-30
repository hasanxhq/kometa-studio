import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_write import parse_report
from kometa_studio.settings import Settings
from kometa_studio.textmerge import merge3

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"

CONFIG = """\
libraries:
  Movies:
    collection_files:
      - file: config/Movies.yml
plex:
  url: http://plex:32400
  token: real-plex-token
webhooks:
  run_end: https://discord.com/api/webhooks/1/discord-secret
"""
MOVIES = "collections:\n  Trending:\n    tmdb_trending_weekly: 30\n"


@pytest.fixture
def kometa(tmp_path) -> Path:
    """Kometa's install folder, with config/ inside it as in the Docker image."""
    root = tmp_path / "kometa"
    config = root / "config"
    (config / "logs").mkdir(parents=True)
    (config / "config.yml").write_text(CONFIG)
    (config / "Movies.yml").write_text(MOVIES)
    (config / "logs" / "meta.log").write_text("old log\n")
    (config / "fake.json").write_text("{}")
    return root


def make_client(tmp_path, kometa, **settings):
    defaults = {
        "data_dir": kometa / "config" / ".studio",
        "kometa_config": kometa / "config" / "config.yml",
        "kometa_entry": FAKE_KOMETA,
        "kometa_python": Path(sys.executable),
    }
    return TestClient(create_app(Settings(**(defaults | settings)), static_dir=tmp_path / "no-static"))


def opened(client, path):
    return client.get("/api/v1/config/edit", params={"path": path}).json()


def calls(kometa) -> list[dict]:
    log = kometa / "config" / "validate_calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_editing_shows_secrets_as_placeholders(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        body = opened(client, "config.yml")
    assert "real-plex-token" not in body["text"] and "discord-secret" not in body["text"]
    assert "token: ••••(1)" in body["text"]
    assert body["hidden"] == 2
    assert len(body["hash"]) == 64


def test_a_good_edit_is_checked_by_kometa_backed_up_and_saved(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        text = movies["text"] + "  Pixar:\n    tmdb_company: 3\n"
        saved = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": text, "base_hash": movies["hash"]}], "reason": "Added Pixar"})
        listed = client.get("/api/v1/backups").json()

    assert saved.status_code == 200
    assert (kometa / "config" / "Movies.yml").read_text() == text
    assert saved.json()["validation"]["ok"] is True
    [backup] = listed["backups"]
    assert (backup["reason"], backup["files"]) == ("Added Pixar", ["Movies.yml"])
    assert (kometa / "config" / ".studio" / "backups" / backup["id"] / "Movies.yml").read_text() == MOVIES

    edited = [c for c in calls(kometa) if "Pixar" in json.dumps(c["files"]) or any("_edited" in a for a in c["args"])]
    structure = next(c for c in edited if "--validate-dir" not in c["args"])
    per_file = next(c for c in calls(kometa) if "--validate-dir" in c["args"])
    # Kometa checked the edited text in a sandbox, from the sandbox's working directory, without webhooks or logs.
    assert "Pixar" in structure["files"]["Movies.yml"]
    assert structure["cwd"] != str(kometa) and Path(structure["cwd"]).name.startswith("validate-")
    assert "webhooks" not in structure["files"]["config.yml"]
    assert "real-plex-token" in structure["files"]["config.yml"]  # Kometa needs the real secrets
    assert {"--validate-level", "structure", "--validate-schema", "--no-source-integrity", "--read-only-config"} <= set(structure["args"])
    assert "--validate-dir" in per_file["args"]
    assert not list((kometa / "config" / ".studio").glob("validate-*"))  # the sandbox is gone


def test_a_broken_edit_is_refused_with_kometas_message_and_nothing_changes(tmp_path, kometa):
    """Milestone 6's "done when"."""
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        response = client.put(
            "/api/v1/config/files",
            json={"files": [{"path": "Movies.yml", "text": "collections:\n  Bad:\n    BROKEN: 1\n", "base_hash": movies["hash"]}]},
        )
        listed = client.get("/api/v1/backups").json()

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "Kometa found problems, so nothing was saved."
    assert detail["validation"]["errors"] == ["Movies.yml: Collection Error: BROKEN is not a builder"]
    assert (kometa / "config" / "Movies.yml").read_text() == MOVIES
    assert listed["backups"] == []


def test_problems_already_there_do_not_block_a_save(tmp_path, kometa):
    (kometa / "config" / "Movies.yml").write_text(MOVIES + "  Old: {BROKEN: 1}\n")
    with make_client(tmp_path, kometa) as client:
        config = opened(client, "config.yml")
        text = config["text"].replace("url: http://plex:32400", "url: http://plex:32401")
        saved = client.put("/api/v1/config/files", json={"files": [{"path": "config.yml", "text": text, "base_hash": config["hash"]}]})
        # Adding a new problem on top is still refused.
        movies = opened(client, "Movies.yml")
        worse = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": movies["text"] + "  SCHEMA-BAD: 1\n", "base_hash": movies["hash"]}]})
    assert saved.status_code == 200
    assert saved.json()["validation"]["existing_errors"] == ["Movies.yml: Collection Error: BROKEN is not a builder"]
    assert saved.json()["validation"]["errors"] == []
    assert worse.status_code == 422
    assert worse.json()["detail"]["validation"]["errors"] == ["Movies.yml: [collection-schema.json] at collections: not allowed"]


def test_fixing_a_problem_saves_cleanly(tmp_path, kometa):
    (kometa / "config" / "Movies.yml").write_text(MOVIES + "  Old: {BROKEN: 1}\n")
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        saved = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": MOVIES, "base_hash": movies["hash"]}]}).json()
    assert saved["validation"] | {"output": ""} == {
        "ok": True, "errors": [], "warnings": [], "existing_errors": [], "checked_by_kometa": True, "crashed": False, "output": ""
    }


def test_a_crashed_check_never_lets_a_save_through(tmp_path, kometa):
    broken_kometa = tmp_path / "crashing_kometa.py"
    broken_kometa.write_text("import sys\nprint('Traceback (most recent call last): boom')\nsys.exit(1)\n")
    with make_client(tmp_path, kometa, kometa_entry=broken_kometa) as client:
        movies = opened(client, "Movies.yml")
        response = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": MOVIES, "base_hash": movies["hash"]}]})
    assert response.status_code == 422
    assert response.json()["detail"]["validation"]["crashed"] is True
    assert "boom" in response.json()["detail"]["validation"]["output"]


def test_yaml_mistakes_are_caught_before_kometa_runs(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        response = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": "collections:\n  Bad: [1,\n", "base_hash": movies["hash"]}]})
    assert response.status_code == 422
    assert "YAML error at line 3" in response.json()["detail"]["message"]
    assert calls(kometa) == []


def test_secrets_survive_a_save(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        config = opened(client, "config.yml")
        text = config["text"].replace("url: http://plex:32400", "url: http://plex:32401")
        assert client.put("/api/v1/config/files", json={"files": [{"path": "config.yml", "text": text, "base_hash": config["hash"]}]}).status_code == 200
    saved = (kometa / "config" / "config.yml").read_text()
    assert saved == CONFIG.replace("32400", "32401")


def test_a_file_changed_on_disk_meanwhile_is_not_overwritten(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        (kometa / "config" / "Movies.yml").write_text(MOVIES + "  Changed elsewhere: {}\n")
        response = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": MOVIES, "base_hash": movies["hash"]}]})
    assert response.status_code == 409
    assert "changed on disk" in response.json()["detail"]["message"]
    assert "Changed elsewhere" in (kometa / "config" / "Movies.yml").read_text()


def test_uploading_a_new_file(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        good = client.put("/api/v1/config/files", json={"files": [{"path": "collections/Anime.yml", "text": "collections:\n  Ghibli: {}\n"}], "reason": "Uploaded Anime.yml"})
        bad = client.put("/api/v1/config/files", json={"files": [{"path": "Bad.yml", "text": "SCHEMA-BAD: 1\n"}]})
        again = client.put("/api/v1/config/files", json={"files": [{"path": "collections/Anime.yml", "text": "collections: {}\n"}]})
        listed = client.get("/api/v1/backups").json()["backups"]

    assert good.status_code == 200
    assert (kometa / "config" / "collections" / "Anime.yml").read_text() == "collections:\n  Ghibli: {}\n"
    # Not referenced by config.yml, so Kometa's per-file schema check is what catches it.
    assert bad.status_code == 422
    assert bad.json()["detail"]["validation"]["errors"] == ["Bad.yml: [collection-schema.json] at collections: not allowed"]
    assert not (kometa / "config" / "Bad.yml").exists()
    assert again.status_code == 409  # an upload never silently replaces a file
    assert listed[0]["new_files"] == ["collections/Anime.yml"]


@pytest.mark.parametrize("path", [".studio/backups/x.yml", "logs/meta.yml", "../outside.yml", "notes.txt", "/etc/passwd"])
def test_only_kometa_yaml_files_are_editable(tmp_path, kometa, path):
    with make_client(tmp_path, kometa) as client:
        response = client.put("/api/v1/config/files", json={"files": [{"path": path, "text": "a: 1\n"}]})
    assert response.status_code == 403


def test_restoring_a_backup(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": "collections: {}\n", "base_hash": movies["hash"]}]})
        client.put("/api/v1/config/files", json={"files": [{"path": "New.yml", "text": "collections: {}\n"}], "reason": "Uploaded New.yml"})
        new_file_backup, movies_backup = client.get("/api/v1/backups").json()["backups"]

        compared = client.get(f"/api/v1/backups/{movies_backup['id']}/file", params={"path": "Movies.yml"}).json()
        assert (compared["backup"], compared["current"]) == (MOVIES, "collections: {}\n")

        restored = client.post(f"/api/v1/backups/{movies_backup['id']}/restore").json()
        undone = client.post(f"/api/v1/backups/{new_file_backup['id']}/restore").json()
        listed = client.get("/api/v1/backups").json()["backups"]

    assert (kometa / "config" / "Movies.yml").read_text() == MOVIES
    assert restored["restored"] == ["Movies.yml"] and restored["validation"]["ok"]
    assert undone["removed"] == ["New.yml"] and not (kometa / "config" / "New.yml").exists()
    assert listed[0]["reason"].startswith("Before restoring")  # restoring is itself undoable


def test_backups_keep_the_newest_thirty(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        for number in range(32):
            movies = opened(client, "Movies.yml")
            text = f"collections:\n  Number {number}: {{}}\n"
            assert client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": text, "base_hash": movies["hash"]}]}).status_code == 200
        listed = client.get("/api/v1/backups").json()
    assert len(listed["backups"]) == listed["keep"] == 30


def test_checking_without_saving(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        result = client.post("/api/v1/config/check", json={"files": [{"path": "Movies.yml", "text": "x:\n  BROKEN: 1\n", "base_hash": movies["hash"]}]}).json()
    assert result["ok"] is False and "BROKEN" in result["errors"][0]
    assert (kometa / "config" / "Movies.yml").read_text() == MOVIES


def test_schemas_are_passed_to_kometa_when_studio_has_them(tmp_path, kometa):
    schemas = tmp_path / "json-schema"
    schemas.mkdir()
    with make_client(tmp_path, kometa, kometa_schemas=schemas) as client:
        movies = opened(client, "Movies.yml")
        client.post("/api/v1/config/check", json={"files": [{"path": "Movies.yml", "text": MOVIES, "base_hash": movies["hash"]}]})
    for call in calls(kometa):
        assert call["args"][call["args"].index("--schema-path") + 1] == str(schemas)


def test_full_check_is_remembered(tmp_path, kometa):
    with make_client(tmp_path, kometa) as client:
        result = client.post("/api/v1/kometa/full-check").json()
        last = client.get("/api/v1/kometa/full-check").json()["last"]
    assert result["ok"] is True
    assert last["at"] == result["at"]
    assert "full" in calls(kometa)[-1]["args"]


# --- Pieces ------------------------------------------------------------------------


def test_parsing_kometas_report():
    output = "\n".join(
        f"| {line:<98} |"
        for line in [
            "Validation Report (structure+schema)",
            " Warnings (1):",
            "   config.yml: settings.cache is deprecated",
            "",
            " Errors (2):",
            "   config.yml: tmdb.apikey is required",
            "   Movies.yml: Collection Error: x",
            "=" * 98,
            " File: /tmp/a/New.yml",
            " Errors (1):",
            "   [collection-schema.json] at (root): bad",
            "=" * 98,
            "Finished",
        ]
    )
    errors, warnings = parse_report(output)
    assert warnings == ["config.yml: settings.cache is deprecated"]
    assert errors == ["config.yml: tmdb.apikey is required", "Movies.yml: Collection Error: x", "/tmp/a/New.yml: [collection-schema.json] at (root): bad"]


def test_three_way_merge_keeps_both_sides_or_gives_up():
    base = "a: 1\nlist:\n- x\nb: 2\n"
    ours = "a: 1\nlist:\n    - x\nb: 2\n"  # the user's indentation
    theirs = "a: 1\nlist:\n- x\nb: 3\n"  # Studio's change
    assert merge3(base, ours, theirs) == "a: 1\nlist:\n    - x\nb: 3\n"
    assert merge3(base, ours, "a: 1\nlist:\n- y\nb: 2\n") is None  # both changed the same line
    assert merge3(base, ours, "a: 1\nlist:\n- x\n- z\nb: 2\n") is None  # an insertion right after the user's change


def test_studios_own_edits_keep_a_mixed_style_file_as_it_was(tmp_path):
    from kometa_studio.kometa_config import write_plex

    original = (
        "libraries:\n  Movies:\n    collection_files:\n      - default: basic   # four-space list\n"
        "  TV:\n    collection_files:\n    - default: imdb   # two-space list\n"
        "plex:\n  url: http://old:32400\n  token: old\n"
    )
    path = tmp_path / "config.yml"
    path.write_text(original)
    write_plex(path, "http://new:32400", "new", tmp_path / "backups")
    assert path.read_text() == original.replace("http://old:32400", "http://new:32400").replace("token: old", "token: new")


def test_no_kometa_means_syntax_only(tmp_path, kometa):
    with make_client(tmp_path, kometa, kometa_entry=tmp_path / "missing" / "kometa.py") as client:
        movies = opened(client, "Movies.yml")
        saved = client.put("/api/v1/config/files", json={"files": [{"path": "Movies.yml", "text": "collections: {}\n", "base_hash": movies["hash"]}]}).json()
    assert saved["validation"]["checked_by_kometa"] is False
    assert "only the YAML syntax was checked" in saved["validation"]["warnings"][0]


def test_sandbox_links_unedited_files_instead_of_copying(tmp_path, kometa):
    big = kometa / "config" / "overlays" / "images"
    big.mkdir(parents=True)
    (big / "poster.png").write_bytes(b"\x89PNG")
    with make_client(tmp_path, kometa) as client:
        movies = opened(client, "Movies.yml")
        client.post("/api/v1/config/check", json={"files": [{"path": "Movies.yml", "text": MOVIES, "base_hash": movies["hash"]}]})
    structure = next(c for c in calls(kometa) if "--validate-dir" not in c["args"])
    assert set(structure["files"]) >= {"config.yml", "Movies.yml"}
    assert os.path.exists(big / "poster.png")  # untouched
