import asyncio

import pytest

from app import main
from app.mam import MamError
from app.models import AddRequest, SearchRequest


class _Req:
    pass


def test_api_search_does_not_leak_private_torrent_id(monkeypatch):
    async def _fake_search(**kwargs):
        return [{"id": 522748, "title": "Book", "_torrent_id": "522748"}]

    monkeypatch.setattr(main, "_require_login", lambda request: None)
    monkeypatch.setattr(main.mam_client, "search", _fake_search)
    main._search_cache.clear()

    payload = SearchRequest(query="book", media_type="audiobook", search_in=["title"], sort="seedersDesc")
    result = asyncio.run(main.api_search(payload, _Req()))

    assert result["results"][0]["id"] == 522748
    assert "_torrent_id" not in result["results"][0]


def test_api_add_uses_cached_torrent_id(monkeypatch):
    captured = {}

    async def _fake_download_torrent(torrent_id: str):
        captured["torrent_id"] = torrent_id
        return b"d8:announce"

    async def _fake_add_torrent(torrent_bytes: bytes, media_type: str, title: str):
        assert torrent_bytes.startswith(b"d")
        return {"hash": "abc", "category": "audiobooks", "name": "Book", "save_path": "/tmp", "content_path": "/tmp/Book"}

    monkeypatch.setattr(main, "_require_login", lambda request: None)
    monkeypatch.setattr(main.mam_client, "download_torrent", _fake_download_torrent)
    monkeypatch.setattr(main.qbit_client, "add_torrent", _fake_add_torrent)
    monkeypatch.setattr(main, "add_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "record_download", lambda *args, **kwargs: None)

    main._search_cache.clear()
    main._search_cache["audiobook:test:seedersDesc"] = {522748: {"id": 522748, "title": "Book", "_torrent_id": "522748"}}

    result = asyncio.run(main.api_add(AddRequest(id=522748, media_type="audiobook"), _Req()))

    assert result["ok"] is True
    assert captured["torrent_id"] == "522748"


def test_api_add_missing_torrent_id_raises_helpful_error(monkeypatch):
    monkeypatch.setattr(main, "_require_login", lambda request: None)
    monkeypatch.setattr(main, "add_history", lambda *args, **kwargs: None)

    main._search_cache.clear()
    main._search_cache["audiobook:test:seedersDesc"] = {522748: {"id": 522748, "title": "Book"}}

    with pytest.raises(Exception) as exc:
        asyncio.run(main.api_add(AddRequest(id=522748, media_type="audiobook"), _Req()))

    detail = exc.value.detail
    assert "Missing source torrent id" in detail
    assert "available result keys" in detail
    assert "mam_session" not in detail
    assert "mam_id" not in detail
    assert "cookie" not in detail.lower()
