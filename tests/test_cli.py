"""The starr-studio command: create-user and set-proxy, which a seedbox install runs before the first start."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from starr_studio import auth, cli, reverse_proxy
from starr_studio.app import create_app
from starr_studio.db import open_database
from starr_studio.settings import Settings


def run(monkeypatch, tmp_path, *args: str, stdin: str = "") -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    with pytest.raises(SystemExit) as stopped:
        cli.main([*args, "--data-dir", str(tmp_path / "data")])
    return stopped.value.code


def stored(tmp_path, key):
    db = open_database(tmp_path / "data" / "studio.db")
    try:
        from starr_studio.db import get_setting

        return get_setting(db, key)
    finally:
        db.close()


def test_create_user_before_the_first_start(monkeypatch, tmp_path):
    assert run(monkeypatch, tmp_path, "create-user", "--username", "short", "--password-stdin", stdin="1234567\n") == 2
    assert stored(tmp_path, auth.AUTH) is None

    assert run(monkeypatch, tmp_path, "create-user", "--username", " me ", "--password-stdin", stdin="correct horse\n") == 0
    saved = stored(tmp_path, auth.AUTH)
    assert saved["username"] == "me" and saved["required"] == "enabled"
    assert auth.check_password("correct horse", saved["password"])

    assert run(monkeypatch, tmp_path, "create-user", "--username", "other", "--password-stdin", stdin="another one\n") == 3
    assert run(monkeypatch, tmp_path, "create-user", "--username", "other", "--if-missing", "--password-stdin", stdin="another one\n") == 0
    assert stored(tmp_path, auth.AUTH)["username"] == "me"
    assert run(monkeypatch, tmp_path, "create-user", "--username", "other", "--replace", "--password-stdin", stdin="another one\n") == 0
    assert stored(tmp_path, auth.AUTH)["username"] == "other"


def test_a_local_request_signs_in_once_a_user_exists(monkeypatch, tmp_path):
    assert run(monkeypatch, tmp_path, "create-user", "--username", "me", "--password-stdin", stdin="correct horse\n") == 0
    app = create_app(Settings(data_dir=tmp_path / "data"), static_dir=tmp_path / "no-static")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/settings/general").status_code == 401
        assert client.post("/api/v1/auth/login", json={"username": "me", "password": "correct horse"}).status_code == 200


def test_set_proxy(monkeypatch, tmp_path):
    assert run(monkeypatch, tmp_path, "set-proxy", "--url-base", "starr-studio/", "--trusted", "127.0.0.1") == 0
    assert stored(tmp_path, reverse_proxy.SETTING) == {"url_base": "/starr-studio", "trusted": ["127.0.0.1"]}
    assert run(monkeypatch, tmp_path, "set-proxy", "--trusted", "0.0.0.0/0") == 2
    assert run(monkeypatch, tmp_path, "set-proxy", "--url-base", "/api") == 2
    assert stored(tmp_path, reverse_proxy.SETTING)["url_base"] == "/starr-studio"
