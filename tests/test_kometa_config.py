import stat

import pytest
from ruamel.yaml import YAML

from kometa_studio.kometa_config import ensure_studio_webhooks, read_plex, write_plex

CONFIG = """\
## Kometa config, managed by hand until now
libraries:
  Movies:
    collection_files:
      - default: basic           # keep this
      - file: config/Movies.yml
plex:                            # REQUIRED
  url: http://192.168.1.12:32400 # old server
  token: old-token
  timeout: 60
  verify_ssl: true
tmdb:
  apikey: "quoted-key"
"""


def test_only_url_and_token_change(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(CONFIG)

    backup = write_plex(path, "https://203-0-113-7.abc123.plex.direct:32400", "new-token", tmp_path / "backups")

    expected = CONFIG.replace("http://192.168.1.12:32400", "https://203-0-113-7.abc123.plex.direct:32400").replace(
        "old-token", "new-token"
    )
    assert path.read_text() == expected
    assert backup is not None and backup.read_text() == CONFIG
    assert read_plex(path).url == "https://203-0-113-7.abc123.plex.direct:32400"
    assert read_plex(path).token == "new-token"


def test_four_space_files_keep_their_indentation(tmp_path):
    path = tmp_path / "config.yml"
    original = "libraries:\n    Movies:\n        collection_files:\n        -   default: basic\nplex:\n    url: http://old\n    token: t\n"
    path.write_text(original)
    write_plex(path, "http://new", "t2", tmp_path / "backups")
    assert path.read_text() == original.replace("http://old", "http://new").replace("token: t\n", "token: t2\n")


def test_creates_config_when_missing(tmp_path):
    path = tmp_path / "config" / "config.yml"
    assert read_plex(path).url is None

    backup = write_plex(path, "http://server:32400", "tok", tmp_path / "backups")

    assert backup is None
    assert path.read_text() == "plex:\n  url: http://server:32400\n  token: tok\n"


def test_fills_an_empty_plex_section(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("plex:\ntmdb:\n  apikey: k\n")
    write_plex(path, "http://server:32400", "tok", tmp_path / "backups")
    assert path.read_text() == "plex:\n  url: http://server:32400\n  token: tok\ntmdb:\n  apikey: k\n"


def test_file_permissions_are_kept(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(CONFIG)
    path.chmod(0o600)
    write_plex(path, "http://server:32400", "tok", tmp_path / "backups")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []  # no temp files left behind


STUDIO = "http://127.0.0.1:8484/api/v1/kometa/events?token=abc"
HOOKS = """\
libraries:
  Movies:
    webhooks:
      changes: https://discord.com/api/webhooks/x
  TV Shows:
    collection_files:
      - default: basic
webhooks:
  error: notifiarr         # tell me
  run_end:
    - ntfy
    - http://127.0.0.1:9999/api/v1/kometa/events?token=old
  run_start:
plex:
  url: http://plex:32400
"""


def test_studio_joins_every_webhook_event(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(HOOKS)

    assert ensure_studio_webhooks(path, STUDIO, tmp_path / "backups") is True

    document = YAML().load(path.read_text())
    hooks = document["webhooks"]
    assert list(hooks["error"]) == ["notifiarr", STUDIO]
    assert list(hooks["run_end"]) == ["ntfy", STUDIO]  # the old port and token are replaced
    for event in ("run_start", "version", "changes", "delete"):
        assert list(hooks[event]) == [STUDIO]
    # A library's own `changes` replaces the global one in Kometa, so Studio joins it too.
    assert list(document["libraries"]["Movies"]["webhooks"]["changes"]) == ["https://discord.com/api/webhooks/x", STUDIO]
    assert "webhooks" not in document["libraries"]["TV Shows"]
    assert "# tell me" in path.read_text()
    assert path.read_text().count("# managed by Kometa Studio") == 7
    assert document["plex"]["url"] == "http://plex:32400"


def test_studio_webhooks_are_only_written_once(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(HOOKS)
    ensure_studio_webhooks(path, STUDIO, tmp_path / "backups")
    written = path.read_text()

    assert ensure_studio_webhooks(path, STUDIO, tmp_path / "backups") is False
    assert path.read_text() == written
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_a_config_without_lists_gets_the_templates_list_style(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("plex:\n  url: http://plex:32400\n")
    ensure_studio_webhooks(path, STUDIO, tmp_path / "backups")
    assert f"  run_end:\n    - {STUDIO}  # managed by Kometa Studio\n" in path.read_text()


def test_webhooks_need_an_existing_config(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_studio_webhooks(tmp_path / "config.yml", STUDIO, tmp_path / "backups")
