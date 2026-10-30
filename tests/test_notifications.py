import json
import shutil
import sys
from pathlib import Path

import pytest
from fakenotify import APPRISE_URL, GOTIFY_TOKEN, GOTIFY_URL, NOTIFIARR_KEY, NTFY_TOKEN, NTFY_TOPIC, NTFY_URL, FakeNotify
from fastapi.testclient import TestClient

from kometa_studio import notifications
from kometa_studio.app import create_app
from kometa_studio.settings import Settings

FAKE_KOMETA = Path(__file__).parent / "fixtures" / "fake_kometa.py"
STUDIO_URL = "http://127.0.0.1:8484/api/v1/kometa/events?token=studio-secret"
DISCORD = "https://discord.com/api/webhooks/1/discord-secret"

CONFIG = f"""\
libraries:
  Movies:
    collection_files:
      - default: basic
plex:
  url: http://plex:32400
  token: real-plex-token
# Push to my phone
gotify:
  url: {GOTIFY_URL}  # the LAN address
  token: {GOTIFY_TOKEN}
webhooks:
  error: gotify
  version:
  run_start:
    - {STUDIO_URL}  # managed by Kometa Studio
  run_end:
    - {DISCORD}
    - gotify
    - {STUDIO_URL}  # managed by Kometa Studio
  changes:
    - {STUDIO_URL}  # managed by Kometa Studio
  delete:
"""


@pytest.fixture
def kometa(tmp_path) -> Path:
    root = tmp_path / "kometa"
    config = root / "config"
    config.mkdir(parents=True)
    (config / "config.yml").write_text(CONFIG)
    (config / "fake.json").write_text("{}")  # fake_kometa logs its checks next to it
    return root


@pytest.fixture
def fake() -> FakeNotify:
    return FakeNotify()


def make_client(tmp_path, kometa, fake, **settings):
    defaults = {
        "data_dir": kometa / "config" / ".studio",
        "kometa_config": kometa / "config" / "config.yml",
        "kometa_entry": FAKE_KOMETA,
        "kometa_python": Path(sys.executable),
    }
    app = create_app(Settings(**(defaults | settings)), static_dir=tmp_path / "no-static", http_transport=fake.transport())
    return TestClient(app, client=("127.0.0.1", 50000))


def config_text(kometa) -> str:
    return (kometa / "config" / "config.yml").read_text()


def backups(kometa) -> list[Path]:
    folder = kometa / "config" / ".studio" / "backups"
    return sorted(folder.iterdir()) if folder.exists() else []


def by_name(state: dict, name: str) -> dict:
    return next(s for s in state["services"] if s["name"] == name)


def test_the_page_is_filled_in_from_config_yml_with_secrets_masked(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        response = client.get("/api/v1/settings/notifications")
    assert response.status_code == 200
    body = response.json()
    raw = json.dumps(body)
    for secret in (GOTIFY_TOKEN, "discord-secret", "studio-secret", "real-plex-token"):
        assert secret not in raw

    gotify = by_name(body, "gotify")
    assert gotify["configured"] is True
    assert gotify["keys"] == [
        {"name": "url", "label": "Server URL", "secret": False, "value": GOTIFY_URL, "masked": None},
        {"name": "token", "label": "Application token", "secret": True, "value": None, "masked": "…" + GOTIFY_TOKEN[-4:]},
    ]
    assert by_name(body, "ntfy")["configured"] is False
    assert [k["name"] for k in by_name(body, "ntfy")["keys"]] == ["url", "token", "topic"]
    assert [k["name"] for k in by_name(body, "notifiarr")["keys"]] == ["apikey"]
    assert [k["name"] for k in by_name(body, "apprise")["keys"]] == ["config"]

    hooks = body["webhooks"]
    discord = notifications.url_id(DISCORD)
    assert [(t["id"], t["kind"]) for t in hooks["targets"]] == [("gotify", "service"), (discord, "url"), ("studio", "studio")]
    assert hooks["targets"][1]["label"] == "https://discord.com/api/webhooks/••••"
    assert hooks["events"] == {
        "error": ["gotify"],
        "version": [],
        "run_start": ["studio"],
        "run_end": [discord, "gotify", "studio"],
        "changes": ["studio"],
        "delete": [],
    }
    assert len(body["hash"]) == 64


def test_testing_a_service_sends_one_labelled_message_and_saves_nothing(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        response = client.post("/api/v1/settings/notifications/ntfy/test", json={"values": {"url": NTFY_URL, "token": NTFY_TOKEN, "topic": NTFY_TOPIC}})
    assert response.json() == {"ok": True, "message": f"ntfy accepted a test message on the topic {NTFY_TOPIC}."}
    assert fake.messages == [{"service": "ntfy", "title": "Kometa Studio test notification", "message": notifications.TEST_MESSAGE}]
    assert config_text(kometa) == CONFIG
    assert backups(kometa) == []


def test_a_saved_secret_left_empty_is_the_one_tested(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        kept = client.post("/api/v1/settings/notifications/gotify/test", json={"values": {"url": GOTIFY_URL, "token": ""}}).json()
        wrong = client.post("/api/v1/settings/notifications/gotify/test", json={"values": {"url": GOTIFY_URL, "token": "wrong"}}).json()
        missing = client.post("/api/v1/settings/notifications/ntfy/test", json={"values": {"url": NTFY_URL, "token": None, "topic": NTFY_TOPIC}}).json()
    assert kept == {"ok": True, "message": "Gotify 2.6.1 accepted a test message."}
    assert wrong == {"ok": False, "error": "Gotify refused the application token"}
    assert missing == {"ok": False, "error": "Enter ntfy's access token"}


@pytest.mark.parametrize(
    ("name", "values", "error"),
    [
        ("notifiarr", {"apikey": "nope"}, "Notifiarr refused the API key"),
        ("ntfy", {"url": NTFY_URL, "token": "tk_wrong", "topic": NTFY_TOPIC}, f"ntfy refused the access token for the topic {NTFY_TOPIC}"),
        ("gotify", {"url": "http://down.test", "token": "x"}, "Can't connect: Connection refused"),
        ("gotify", {"url": "http://elsewhere.test", "token": "x"}, "That address answered, but not like Gotify"),
    ],
)
def test_a_failed_test_says_why(tmp_path, kometa, fake, name, values, error):
    fake.down.add("down.test")
    with make_client(tmp_path, kometa, fake) as client:
        response = client.post(f"/api/v1/settings/notifications/{name}/test", json={"values": values})
    assert response.json() == {"ok": False, "error": error}


def test_notifiarr_is_checked_the_way_kometa_checks_it(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        response = client.post("/api/v1/settings/notifications/notifiarr/test", json={"values": {"apikey": NOTIFIARR_KEY}})
    assert response.json()["ok"] is True
    assert fake.calls == ["GET notifiarr.com/api/v1/user/pmm/"]
    assert fake.messages == []


def test_apprise_needs_a_configuration_that_lists_services(tmp_path, kometa, fake):
    (kometa / "apprise.yml").write_text("urls:\n  - tgram://bottoken/ChatID\n")
    (kometa / "config" / "empty.txt").write_text("# nothing yet\n")
    shutil.copy(FAKE_KOMETA, kometa / "kometa.py")
    with make_client(tmp_path, kometa, fake, kometa_entry=kometa / "kometa.py") as client:
        relative = client.post("/api/v1/settings/notifications/apprise/test", json={"values": {"config": "apprise.yml"}}).json()
        remote = client.post("/api/v1/settings/notifications/apprise/test", json={"values": {"config": APPRISE_URL}}).json()
        empty = client.post("/api/v1/settings/notifications/apprise/test", json={"values": {"config": str(kometa / "config" / "empty.txt")}}).json()
        absent = client.post("/api/v1/settings/notifications/apprise/test", json={"values": {"config": "/nowhere/apprise.yml"}}).json()
    # A relative path is where Kometa looks: its own folder, where it runs from.
    assert relative == {"ok": True, "message": "The Apprise configuration lists 1 notification service. Apprise sends the messages, so Studio sent none."}
    assert remote["ok"] is True and "lists 2 notification services" in remote["message"]
    assert empty == {"ok": False, "error": "That Apprise configuration lists no notification services, so Kometa would refuse it"}
    assert absent == {"ok": False, "error": "There's no file at /nowhere/apprise.yml"}


def test_apprise_text_format_is_counted():
    assert notifications.apprise_services("# mine\nmailto://me:pw@example.com\nfamily,phone=tgram://bot/123\n; old\n\n") == 2
    assert notifications.apprise_services("version: 1\nurls:\n  - pover://u@t:\n      - tag: x\n") == 1


def test_saving_a_service_tests_it_then_saves_through_kometas_check(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        response = client.put(
            "/api/v1/settings/notifications/ntfy",
            json={"values": {"url": NTFY_URL, "token": NTFY_TOKEN, "topic": NTFY_TOPIC}, "base_hash": state["hash"]},
        )
        listed = client.get("/api/v1/backups").json()
    assert response.status_code == 200, response.text
    body = response.json()
    assert by_name(body, "ntfy")["configured"] is True
    assert NTFY_TOKEN not in json.dumps(body)
    assert body["saved"]["validation"]["ok"] is True
    # The save route ran the test itself.
    assert [m["service"] for m in fake.messages] == ["ntfy"]

    text = config_text(kometa)
    assert text.startswith(CONFIG)  # everything else, comments included, as it was
    assert text[len(CONFIG) :] == f"ntfy:\n  url: {NTFY_URL}\n  token: {NTFY_TOKEN}\n  topic: {NTFY_TOPIC}\n"
    [backup] = listed["backups"]
    assert backup["reason"] == "Set up ntfy in Settings → Notifications"

    # Kometa checked the change, in its sandbox and without webhooks.
    calls = [json.loads(line) for line in (kometa / "config" / "validate_calls.jsonl").read_text().splitlines()]
    assert any(NTFY_TOPIC in c["files"]["config.yml"] for c in calls)


def test_the_backend_refuses_a_save_whose_test_fails(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        response = client.put(
            "/api/v1/settings/notifications/gotify", json={"values": {"url": GOTIFY_URL, "token": "wrong"}, "base_hash": state["hash"]}
        )
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "The test failed, so nothing was saved: Gotify refused the application token"
    assert config_text(kometa) == CONFIG
    assert backups(kometa) == []


def test_changing_a_service_keeps_its_comments_and_saved_secret(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        same_server = GOTIFY_URL + "/"  # the same server, written differently
        response = client.put("/api/v1/settings/notifications/gotify", json={"values": {"url": same_server, "token": ""}, "base_hash": state["hash"]})
    assert response.status_code == 200, response.text
    # The comment stays where it was, so the longer value leaves one space before it.
    assert config_text(kometa) == CONFIG.replace(f"url: {GOTIFY_URL}  #", f"url: {same_server} #")


def test_a_config_changed_on_disk_meanwhile_is_not_overwritten(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        (kometa / "config" / "config.yml").write_text(CONFIG + "\n")
        response = client.put(
            "/api/v1/settings/notifications/notifiarr", json={"values": {"apikey": NOTIFIARR_KEY}, "base_hash": state["hash"]}
        )
    assert response.status_code == 409
    assert config_text(kometa) == CONFIG + "\n"


def test_removing_a_service_takes_it_out_of_the_webhook_events_too(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        response = client.delete("/api/v1/settings/notifications/gotify", params={"base_hash": state["hash"]})
        again = client.delete("/api/v1/settings/notifications/gotify", params={"base_hash": response.json()["hash"]})
    assert response.status_code == 200, response.text
    assert by_name(response.json(), "gotify")["configured"] is False
    text = config_text(kometa)
    assert "gotify" not in text and GOTIFY_TOKEN not in text
    assert "error:\n" in text
    assert text.count(f"- {STUDIO_URL}  # managed by Kometa Studio") == 3
    assert f"- {DISCORD}\n" in text
    assert again.status_code == 404
    assert len(backups(kometa)) == 1


def test_webhook_events_save_the_users_targets_and_leave_studios_alone(tmp_path, kometa, fake):
    discord = notifications.url_id(DISCORD)
    slack = "https://hooks.slack.com/services/T0/B0/slack-secret"
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        events = {
            "error": ["gotify", slack],
            "version": ["gotify"],
            "run_start": ["studio", discord],
            "run_end": ["gotify"],  # Discord unticked; Studio's own entry isn't sent and must stay
            "changes": [],
            "delete": [],
        }
        response = client.put("/api/v1/settings/notifications/webhooks", json={"base_hash": state["hash"], "events": events})
    assert response.status_code == 200, response.text
    text = config_text(kometa)
    hooks = text[text.index("webhooks:") :]
    assert hooks == (
        "webhooks:\n"
        "  error:\n"
        "    - gotify\n"
        f"    - {slack}\n"
        "  version: gotify\n"
        "  run_start:\n"
        f"    - {DISCORD}\n"
        f"    - {STUDIO_URL}  # managed by Kometa Studio\n"
        "  run_end:\n"
        "    - gotify\n"
        f"    - {STUDIO_URL}  # managed by Kometa Studio\n"
        "  changes:\n"
        f"    - {STUDIO_URL}  # managed by Kometa Studio\n"
        "  delete:\n"
    )
    assert text[: text.index("webhooks:")] == CONFIG[: CONFIG.index("webhooks:")]
    body = response.json()
    assert "slack-secret" not in json.dumps(body)
    assert body["webhooks"]["events"]["error"] == ["gotify", notifications.url_id(slack)]


def test_studios_entries_survive_saving_a_service_and_removing_another(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        state = client.put("/api/v1/settings/notifications/notifiarr", json={"values": {"apikey": NOTIFIARR_KEY}, "base_hash": state["hash"]}).json()
        state = client.put("/api/v1/settings/notifications/webhooks", json={"base_hash": state["hash"], "events": {"changes": ["notifiarr"]}}).json()
        client.delete("/api/v1/settings/notifications/gotify", params={"base_hash": state["hash"]})
    text = config_text(kometa)
    assert text.count(f"- {STUDIO_URL}  # managed by Kometa Studio") == 3
    assert f"  changes:\n    - notifiarr\n    - {STUDIO_URL}  # managed by Kometa Studio\n" in text


def test_webhook_urls_must_be_ones_kometa_can_use(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        bad = client.put("/api/v1/settings/notifications/webhooks", json={"base_hash": state["hash"], "events": {"error": ["discord.com/hook"]}})
        stale = client.put("/api/v1/settings/notifications/webhooks", json={"base_hash": state["hash"], "events": {"error": ["url:0123456789abcdef"]}})
        event = client.put("/api/v1/settings/notifications/webhooks", json={"base_hash": state["hash"], "events": {"collection_added": ["gotify"]}})
    assert bad.status_code == 422 and "complete http:// or https:// URL" in bad.json()["detail"]["message"]
    assert stale.status_code == 409
    assert event.status_code == 422
    assert config_text(kometa) == CONFIG


def test_a_new_config_gets_a_service_section(tmp_path, kometa, fake):
    (kometa / "config" / "config.yml").unlink()
    with make_client(tmp_path, kometa, fake) as client:
        state = client.get("/api/v1/settings/notifications").json()
        assert state["hash"] is None
        response = client.put("/api/v1/settings/notifications/notifiarr", json={"values": {"apikey": NOTIFIARR_KEY}, "base_hash": None})
    assert response.status_code == 200, response.text
    assert config_text(kometa) == f"notifiarr:\n  apikey: {NOTIFIARR_KEY}\n"


def test_unknown_services_are_not_found(tmp_path, kometa, fake):
    with make_client(tmp_path, kometa, fake) as client:
        assert client.post("/api/v1/settings/notifications/pushover/test", json={"values": {}}).status_code == 404
        assert client.put("/api/v1/settings/notifications/pushover", json={"values": {}, "base_hash": None}).status_code == 404


def test_mask_url_hides_tokens_and_passwords():
    assert notifications.mask_url("https://hooks.slack.com/services/T0/B0/x") == "https://hooks.slack.com/services/••••"
    assert notifications.mask_url("http://me:pw@example.com/hook?token=abc&x=1") == "http://me:••••@example.com/hook?token=••••&x=1"
    assert notifications.mask_url("https://example.com/kometa") == "https://example.com/kometa"
