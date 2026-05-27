import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main


def test_validate_auth_config_rejects_default_password(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", True)
    monkeypatch.setattr(main.settings, "app_password", "change-me")
    monkeypatch.setattr(main.settings, "app_session_secret", "x" * 32)

    with pytest.raises(RuntimeError, match="APP_PASSWORD"):
        main._validate_auth_config()


def test_validate_auth_config_rejects_short_secret(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", True)
    monkeypatch.setattr(main.settings, "app_password", "safe-pass")
    monkeypatch.setattr(main.settings, "app_session_secret", "too-short")

    with pytest.raises(RuntimeError, match="shorter than 32"):
        main._validate_auth_config()


def test_validate_auth_config_allows_secure_settings(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", True)
    monkeypatch.setattr(main.settings, "app_password", "safe-pass")
    monkeypatch.setattr(main.settings, "app_session_secret", "s" * 32)

    main._validate_auth_config()


def test_login_sets_secure_cookie_flags(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", True)
    monkeypatch.setattr(main.settings, "app_username", "admin")
    monkeypatch.setattr(main.settings, "app_password", "safe-pass")
    monkeypatch.setattr(main.settings, "app_session_secret", "s" * 32)

    client = TestClient(main.app)
    response = client.post("/login", json={"username": "admin", "password": "safe-pass"}, headers={"x-forwarded-proto": "https"})

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie
    assert "max-age=" in cookie
    assert "expires=" in cookie


def test_startup_calls_auth_validation(monkeypatch):
    called = {"ok": False}

    def _fake_validate():
        called["ok"] = True

    monkeypatch.setattr(main, "_validate_auth_config", _fake_validate)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main.settings, "import_min_completion_ratio_legacy_present", False)
    monkeypatch.setattr(main.settings, "import_enabled", False)

    asyncio.run(main.startup())
    assert called["ok"] is True
