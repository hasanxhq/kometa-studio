import pytest
from fastapi.testclient import TestClient

from kometa_studio import logs_routes
from kometa_studio.app import create_app
from kometa_studio.settings import Settings

# Shaped like Kometa 2.5's meta.log: fixed-width file name and level, wrapped lines indented.
META = """\
[2026-10-30 04:00:00,001] kometa.py                   INFO       |=====================================|
[2026-10-30 04:00:00,002] kometa.py                   INFO       | Starting Run                        |
[2026-10-30 04:00:01,100] config.py                   DEBUG      | Reading config.yml                  |
[2026-10-30 04:00:02,200] builder.py                  WARNING    | Collection Warning: no items found  |
[2026-10-30 04:00:03,300] builder.py                  ERROR      | Trakt Error: List not found         |
                                                                 | (continued) https://trakt.tv/x      |
[2026-10-30 04:00:04,400] kometa.py                   [TRACE]    | Cache hit                           |
"""


@pytest.fixture
def client(tmp_path):
    config = tmp_path / "config"
    logs = config / "logs"
    (logs / "Movies" / "collections" / "Marvel").mkdir(parents=True)
    (config / "config.yml").write_text("libraries: {}\n")
    (logs / "meta.log").write_text(META)
    (logs / "meta.log.1").write_text("old\n")
    (logs / "Movies" / "library.log").write_text("library\n")
    (logs / "Movies" / "collections" / "Marvel" / "collection.log").write_text("collection\n")
    (logs / "notes.txt").write_text("not a log")
    (config / "secret.log").write_text("outside the logs folder")
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config / "config.yml"), static_dir=tmp_path / "no-static")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client


def test_lists_kometas_logs_with_meta_log_first(client):
    paths = [f["path"] for f in client.get("/api/v1/logs").json()["files"]]
    assert paths[0] == "meta.log"
    assert sorted(paths) == ["Movies/collections/Marvel/collection.log", "Movies/library.log", "meta.log", "meta.log.1"]


def test_filters_by_level_keeping_continuation_lines(client):
    body = client.get("/api/v1/logs/file", params={"path": "meta.log", "level": "WARNING"}).json()
    assert [line["level"] for line in body["lines"]] == ["WARNING", "ERROR", "ERROR"]
    assert "(continued)" in body["lines"][-1]["text"]
    every = client.get("/api/v1/logs/file", params={"path": "meta.log", "level": "TRACE"}).json()["lines"]
    assert len(every) == 7 and every[-1]["level"] == "TRACE"
    default = client.get("/api/v1/logs/file", params={"path": "meta.log"}).json()["lines"]
    assert [line["level"] for line in default] == ["INFO", "INFO", "WARNING", "ERROR", "ERROR"]


def test_searches_and_limits(client):
    found = client.get("/api/v1/logs/file", params={"path": "meta.log", "q": "trakt", "level": "TRACE"}).json()
    assert [line["text"].split("| ")[1].strip() for line in found["lines"]] == ["Trakt Error: List not found         |", "(continued) https://trakt.tv/x      |"]
    limited = client.get("/api/v1/logs/file", params={"path": "meta.log", "limit": 2}).json()
    assert len(limited["lines"]) == 2 and limited["truncated"] is True


@pytest.mark.parametrize("path", ["../secret.log", "notes.txt", "missing.log", "/etc/passwd"])
def test_only_log_files_in_the_logs_folder(client, path):
    assert client.get("/api/v1/logs/file", params={"path": path}).status_code == 404
    assert client.get("/api/v1/logs/download", params={"path": path}).status_code == 404


def test_a_big_log_is_read_from_the_end(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_routes, "TAIL_BYTES", 100)
    path = tmp_path / "big.log"
    path.write_text("".join(f"[2026-10-30 04:00:00,000] kometa.py   INFO       | line {n} |\n" for n in range(50)))
    entries, truncated = logs_routes.read_entries(path)
    assert truncated is True
    assert entries[-1][1].endswith("| line 49 |")
    assert all(text.startswith("[") for _, text in entries)  # no half line at the start
