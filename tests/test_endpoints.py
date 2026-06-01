from pathlib import Path
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


def test_search_renderer_escapes_xss_in_title(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    async def _fake_search(**kwargs):
        return [{"id": 7, "title": "<script>alert(1)</script>", "_torrent_id": "7", "seeders": 1, "leechers": 0, "catname": "Cat"}]

    monkeypatch.setattr(main.mam_client, "search", _fake_search)

    client = TestClient(main.app)
    search = client.post("/api/search", json={"query": "xss", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})
    assert search.status_code == 200

    app_js = Path("app/static/app.js").read_text()
    assert "titleDiv.textContent = r.title || " in app_js
    assert "titleDiv.innerHTML" not in app_js


def test_api_search_preserves_filetype_fields(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    async def _fake_search(**kwargs):
        return [{
            "id": 9,
            "title": "Format Test",
            "filetypes": "epub",
            "filetype": "azw3",
            "_torrent_id": "9",
            "seeders": 1,
            "leechers": 0,
            "catname": "Books",
        }]

    monkeypatch.setattr(main.mam_client, "search", _fake_search)
    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "format", "media_type": "ebook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["filetypes"] == "epub"
    assert row["filetype"] == "azw3"
    assert "_torrent_id" not in row




def test_api_search_in_library_positive_annotation(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    async def _fake_search(**kwargs):
        return [{"id": 3, "title": "Book", "author": "Jane", "narrator": "John", "_torrent_id": "3", "seeders": 1, "leechers": 0, "catname": "Audio"}]

    async def _annotate(_row):
        return (True, [{"provider": "Audiobookshelf", "title": "Book", "author": "Jane", "narrator": "John"}])

    monkeypatch.setattr(main.mam_client, "search", _fake_search)
    monkeypatch.setattr(main.library_presence_service, "annotate", _annotate)

    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "book", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["in_library"] is True
    assert row["library_matches"][0]["provider"] == "Audiobookshelf"
    assert "_torrent_id" not in row

def test_api_search_plex_disabled_does_not_break(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    monkeypatch.setattr(main.settings, "plex_enabled", False)

    async def _fake_search(**kwargs):
        return [{"id": 1, "title": "Book", "author": "Jane", "narrator": "John", "_torrent_id": "1", "seeders": 1, "leechers": 0, "catname": "Audio"}]

    monkeypatch.setattr(main.mam_client, "search", _fake_search)

    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "book", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["in_library"] is False
    assert row["library_matches"] == []


def test_api_search_plex_error_does_not_break(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    async def _fake_search(**kwargs):
        return [{"id": 2, "title": "Book", "author": "Jane", "narrator": "John", "_torrent_id": "2", "seeders": 1, "leechers": 0, "catname": "Audio"}]

    async def _boom(_safe):
        raise RuntimeError("provider down")

    monkeypatch.setattr(main.mam_client, "search", _fake_search)
    monkeypatch.setattr(main.library_presence_service, "annotate", _boom)

    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "book", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["in_library"] is False
    assert row["library_matches"] == []


def test_api_search_marks_rows_already_in_qbit(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    torrent_hash = "abcdef1234567890abcdef1234567890abcdef12"

    async def _fake_search(**kwargs):
        return [{"id": 44, "title": "Loaded Book", "_torrent_id": "44", "_torrent_hash": torrent_hash, "seeders": 1, "leechers": 0, "catname": "Audio"}]

    async def _fake_get_torrents():
        return [{"hash": torrent_hash.upper(), "name": "Loaded Book"}]

    monkeypatch.setattr(main.mam_client, "search", _fake_search)
    monkeypatch.setattr(main.qbit_client, "get_torrents", _fake_get_torrents)

    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "loaded", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["in_qbit"] is True
    assert row["qbit_name"] == "Loaded Book"
    assert "_torrent_hash" not in row


def test_api_search_qbit_error_does_not_break(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    torrent_hash = "abcdef1234567890abcdef1234567890abcdef12"

    async def _fake_search(**kwargs):
        return [{"id": 45, "title": "Book", "_torrent_id": "45", "_torrent_hash": torrent_hash, "seeders": 1, "leechers": 0, "catname": "Audio"}]

    async def _boom():
        raise RuntimeError("qbit down")

    monkeypatch.setattr(main.mam_client, "search", _fake_search)
    monkeypatch.setattr(main.qbit_client, "get_torrents", _boom)

    client = TestClient(main.app)
    response = client.post("/api/search", json={"query": "book", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    assert response.json()["results"][0]["in_qbit"] is False


def test_api_add_rejects_cached_qbit_match(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)

    main._search_cache.clear()
    main._search_cache_updated_at.clear()
    main._search_cache["audiobook:test:seedersDesc"] = {1: {"id": 1, "title": "Book", "_torrent_id": "1", "in_qbit": True}}
    main._search_cache_updated_at["audiobook:test:seedersDesc"] = time.time()

    client = TestClient(main.app)
    response = client.post("/api/add", json={"id": 1, "media_type": "audiobook"})

    assert response.status_code == 409
    assert "already loaded" in response.json()["detail"]
