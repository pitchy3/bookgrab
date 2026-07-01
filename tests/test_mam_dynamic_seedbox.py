import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import mam
from app import main


class Resp:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.headers = {}
        self.content = b""
    def json(self):
        return self._data


def test_cookie_normalization():
    assert mam.normalize_mam_cookie("") == ""
    assert mam.normalize_mam_cookie(" token ") == "mam_id=token"
    assert mam.normalize_mam_cookie("mam_id=token") == "mam_id=token"
    assert mam.normalize_mam_cookie("mam_id=abc; mam_session=xyz") == "mam_id=abc; mam_session=xyz"


def test_cookie_precedence(monkeypatch, tmp_path):
    cookie_file = tmp_path / "file_cookie"
    store_file = tmp_path / "store_cookie"
    cookie_file.write_text("filetoken")
    store_file.write_text("storetoken")
    monkeypatch.setattr(mam.settings, "mam_cookie_file", str(cookie_file))
    monkeypatch.setattr(mam.settings, "mam_cookie_store_path", str(store_file))
    monkeypatch.setattr(mam.settings, "mam_cookie", "envtoken")
    monkeypatch.setattr(mam.settings, "mam_uid", "uid")
    monkeypatch.setattr(mam.settings, "mam_session", "session")
    assert mam.load_mam_cookie() == "mam_id=filetoken"
    cookie_file.unlink()
    assert mam.load_mam_cookie() == "mam_id=storetoken"
    store_file.unlink()
    assert mam.load_mam_cookie() == "mam_id=envtoken"
    monkeypatch.setattr(mam.settings, "mam_cookie", "")
    assert mam.load_mam_cookie() == "mam_id=uid; mam_session=session"


def test_dynamic_seedbox_parsing_and_cooldown(monkeypatch, tmp_path):
    calls = []
    state = tmp_path / "state.json"
    monkeypatch.setattr(mam.settings, "mam_cookie_file", "")
    monkeypatch.setattr(mam.settings, "mam_cookie_store_path", "")
    monkeypatch.setattr(mam.settings, "mam_cookie", "mam_id=secret")
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_state_path", str(state))
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_min_interval_seconds", 3600)

    class Client:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, headers):
            calls.append(headers)
            return Resp(200, {"Success": True, "message": "Completed", "ip": "1.2.3.4", "ASN": 123, "AS": "Test AS"})

    monkeypatch.setattr(mam.httpx, "AsyncClient", Client)
    result = asyncio.run(mam.MamClient().refresh_dynamic_seedbox_ip())
    assert result["ok"] is True
    assert result["message"] == "Completed"
    assert result["ip"] == "1.2.3.4"
    assert "secret" not in state.read_text()
    skipped = asyncio.run(mam.MamClient().refresh_dynamic_seedbox_ip())
    assert skipped["skipped"] is True
    assert len(calls) == 1
    forced = asyncio.run(mam.MamClient().refresh_dynamic_seedbox_ip(force=True))
    assert forced["ok"] is True
    assert len(calls) == 2


def test_dynamic_seedbox_no_change_and_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(mam.settings, "mam_cookie_file", "")
    monkeypatch.setattr(mam.settings, "mam_cookie_store_path", "")
    monkeypatch.setattr(mam.settings, "mam_cookie", "mam_id=secret")
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_state_path", str(tmp_path / "state.json"))
    responses = [
        Resp(200, {"Success": False, "msg": "No change"}),
        Resp(429, {"msg": "Last change too recent"}),
        Resp(403, {"msg": "No Session Cookie"}),
        Resp(403, {"msg": "Invalid session - Invalid Cookie"}),
        Resp(403, {"msg": "Invalid session - IP mismatch"}),
        Resp(403, {"msg": "Invalid session - ASN mismatch"}),
        Resp(403, {"msg": "Incorrect session type - non-API session"}),
    ]

    class Client:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, headers): return responses.pop(0)

    monkeypatch.setattr(mam.httpx, "AsyncClient", Client)
    client = mam.MamClient()
    assert asyncio.run(client.refresh_dynamic_seedbox_ip(force=True))["ok"] is True
    assert asyncio.run(client.refresh_dynamic_seedbox_ip(force=True))["cooldown"] is True
    messages = [asyncio.run(client.refresh_dynamic_seedbox_ip(force=True))["message"] for _ in range(5)]
    assert any("No Session Cookie" in m for m in messages)
    assert any("Invalid Cookie" in m for m in messages)
    assert any("IP mismatch" in m for m in messages)
    assert any("ASN mismatch" in m for m in messages)
    assert any("Incorrect session type" in m for m in messages)


def test_api_safety(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    monkeypatch.setattr(main.settings, "mam_cookie_store_path", str(tmp_path / "cookie"))
    monkeypatch.setattr(main.settings, "mam_dynamic_seedbox_enabled", False)
    monkeypatch.setattr(mam.settings, "mam_cookie_file", "")
    monkeypatch.setattr(mam.settings, "mam_cookie_store_path", str(tmp_path / "cookie"))
    monkeypatch.setattr(mam.settings, "mam_cookie", "mam_id=topsecret")
    response = TestClient(main.app).get("/api/source-auth/status")
    text = response.text
    assert response.status_code == 200
    assert "topsecret" not in text
    response = TestClient(main.app).post("/api/source-auth/cookie", json={"cookie": "mam_id=newsecret"})
    assert response.status_code == 200
    assert "newsecret" not in response.text
    assert "newsecret" in Path(main.settings.mam_cookie_store_path).read_text()


def test_dynamic_seedbox_auth_error_precedes_cooldown(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    state.write_text('{"last_attempt_at":"2999-01-01T00:00:00+00:00","ok":true}')
    monkeypatch.setattr(mam.settings, "mam_cookie_file", "")
    monkeypatch.setattr(mam.settings, "mam_cookie_store_path", "")
    monkeypatch.setattr(mam.settings, "mam_cookie", "")
    monkeypatch.setattr(mam.settings, "mam_uid", "")
    monkeypatch.setattr(mam.settings, "mam_session", "")
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_state_path", str(state))
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_enabled", True)
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_run_before_search", True)

    try:
        asyncio.run(mam.MamClient()._refresh_before_request())
    except mam.MamError as exc:
        assert "Missing MAM cookie" in str(exc)
    else:
        raise AssertionError("expected missing-cookie auth error")


def test_dynamic_seedbox_retries_after_network_error(monkeypatch, tmp_path):
    calls = 0
    state = tmp_path / "state.json"
    monkeypatch.setattr(mam.settings, "mam_cookie_file", "")
    monkeypatch.setattr(mam.settings, "mam_cookie_store_path", "")
    monkeypatch.setattr(mam.settings, "mam_cookie", "mam_id=secret")
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_state_path", str(state))
    monkeypatch.setattr(mam.settings, "mam_dynamic_seedbox_min_interval_seconds", 3600)

    class Client:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, headers):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise mam.httpx.ConnectError("vpn down")
            return Resp(200, {"Success": True, "message": "Completed"})

    monkeypatch.setattr(mam.httpx, "AsyncClient", Client)
    client = mam.MamClient()
    first = asyncio.run(client.refresh_dynamic_seedbox_ip())
    assert first["network_error"] is True
    second = asyncio.run(client.refresh_dynamic_seedbox_ip())
    assert second["ok"] is True
    assert second["network_error"] is False
    assert calls == 2
