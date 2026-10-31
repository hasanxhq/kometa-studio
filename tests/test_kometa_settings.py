from fastapi.testclient import TestClient

from kometa_studio.app import create_app
from kometa_studio.config_sections import with_settings
from kometa_studio.kometa_files import settings_defaults
from kometa_studio.settings import Settings

TEXT = """\
libraries:
  Movies:
    collection_files:
      - file: config/Movies.yml
settings:
  cache: true   # keep it
  asset_directory:
    - config/assets
  sync_mode: append
"""


def test_changing_settings_keeps_the_rest_as_written():
    changed = with_settings(TEXT, {"cache": True, "asset_directory": ["config/assets"], "sync_mode": "sync", "minimum_items": 2})
    assert changed == TEXT.replace("  sync_mode: append\n", "  sync_mode: sync\n  minimum_items: 2\n")
    removed = with_settings(TEXT, {"cache": True, "asset_directory": ["config/assets"]})
    assert removed == TEXT.replace("  sync_mode: append\n", "")
    assert with_settings(TEXT, {}) == TEXT.split("settings:")[0]


def test_a_config_without_settings_gets_them():
    text = "libraries:\n  Movies:\n    collection_files:\n      - file: config/Movies.yml\n"
    assert with_settings(text, {"save_report": True}) == text + "settings:\n  save_report: true\n"


CONFIG_PY = """\
class ConfigFile:
    def __init__(self):
        self.general = {
            "run_order": check_for_attribute(self.data, "run_order", parent="settings", var_type="lower_list",
                                             default=["operations", "metadata", "collections", "overlays"]),
            "cache": check_for_attribute(self.data, "cache", parent="settings", var_type="bool", default=True),
            "asset_directory": check_for_attribute(self.data, "asset_directory", parent="settings", default_is_none=True),
            "custom": check_for_attribute(self.data, "custom", parent="settings", default=os.getcwd()),
        }
        for lib in libraries:
            check_for_attribute(lib, "cache", parent="settings", default=False)
"""


def test_kometas_defaults_are_read_from_its_source_without_running_it(tmp_path):
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "config.py").write_text(CONFIG_PY)
    defaults = settings_defaults(tmp_path)
    assert defaults == {"run_order": ["operations", "metadata", "collections", "overlays"], "cache": True, "asset_directory": None}
    assert settings_defaults(None) == {} and settings_defaults(tmp_path / "nowhere") == {}


def make_client(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(TEXT)
    app = create_app(Settings(data_dir=tmp_path / "data", kometa_config=config), static_dir=tmp_path / "no-static")
    return TestClient(app, client=("127.0.0.1", 50000)), config


def test_the_settings_form_through_the_api(tmp_path):
    client, config = make_client(tmp_path)
    with client:
        loaded = client.get("/api/v1/config/settings").json()
        base = loaded["values"]
        saved = client.put("/api/v1/config/settings", json={"base": base, "values": base | {"sync_mode": "sync"}})
        stale = client.put("/api/v1/config/settings", json={"base": base, "values": base | {"cache": False}})  # opened before that save
        backups = client.get("/api/v1/backups").json()["backups"]
    assert base == {"cache": True, "asset_directory": ["config/assets"], "sync_mode": "append"}
    assert saved.status_code == 200 and saved.json()["validation"]["ok"] is True
    assert "  sync_mode: sync\n" in config.read_text() and "cache: true   # keep it" in config.read_text()
    assert stale.status_code == 409 and "changed since you opened them" in stale.json()["detail"]["message"]
    assert [b["reason"] for b in backups] == ["Changed Kometa's settings"]
