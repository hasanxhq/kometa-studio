import stat

from kometa_studio.kometa_config import read_plex, write_plex

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
