import time

from fastapi.testclient import TestClient

from app import main
from app.mam import MamError
from app.qbittorrent import QbitError


def test_login_rejects_invalid_credentials(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", True)
    monkeypatch.setattr(main.settings, "app_username", "admin")
    monkeypatch.setattr(main.settings, "app_password", "safe-pass")
    monkeypatch.setattr(main.settings, "app_session_secret", "s" * 32)

    client = TestClient(main.app)
    response = client.post("/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_api_endpoints_require_auth_when_enabled(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", True)
    monkeypatch.setattr(main.settings, "app_username", "admin")
    monkeypatch.setattr(main.settings, "app_password", "safe-pass")
    monkeypatch.setattr(main.settings, "app_session_secret", "s" * 32)

    client = TestClient(main.app)

    search = client.post("/api/search", json={"query": "book", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})
    add = client.post("/api/add", json={"id": 1, "media_type": "audiobook"})

    assert search.status_code == 401
    assert add.status_code == 401


def test_api_search_maps_mam_auth_failures_to_502(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    async def _bad_search(**kwargs):
        raise MamError("Failed to query search API. Check source auth/session and URL.")

    monkeypatch.setattr(main.mam_client, "search", _bad_search)

    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "book", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 502
    assert "auth/session" in response.json()["detail"]


def test_api_add_maps_qbit_login_failures_to_502(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    monkeypatch.setattr(main, "add_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "record_download", lambda *args, **kwargs: None)

    async def _fake_download_torrent(_torrent_id: str):
        return b"d8:announce"

    async def _fake_add_torrent(*_args, **_kwargs):
        raise QbitError("qBittorrent login failed")

    monkeypatch.setattr(main.mam_client, "download_torrent", _fake_download_torrent)
    monkeypatch.setattr(main.qbit_client, "add_torrent", _fake_add_torrent)

    main._search_cache.clear()
    main._search_cache_updated_at.clear()
    main._search_cache["audiobook:test:seedersDesc"] = {1: {"id": 1, "title": "Book", "_torrent_id": "1"}}
    main._search_cache_updated_at["audiobook:test:seedersDesc"] = time.time()

    client = TestClient(main.app)
    response = client.post("/api/add", json={"id": 1, "media_type": "audiobook"})

    assert response.status_code == 502
    assert response.json()["detail"] == "qBittorrent login failed"


def test_search_response_escapes_xss_in_title(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    async def _fake_search(**kwargs):
        return [{"id": 7, "title": "<script>alert(1)</script>", "_torrent_id": "7", "seeders": 1, "leechers": 0, "catname": "Cat"}]

    monkeypatch.setattr(main.mam_client, "search", _fake_search)

    client = TestClient(main.app)
    search = client.post("/api/search", json={"query": "xss", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})
    assert search.status_code == 200

    html = client.get("/").text
    assert "<script>alert(1)</script>" not in html
