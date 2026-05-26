import asyncio

import pytest

from app.mam import MamClient, MamError, normalize_result


class _DummyResponse:
    def __init__(self, content: bytes, content_type: str = "application/x-bittorrent"):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


class _DummyClient:
    def __init__(self, response: _DummyResponse, calls: list[tuple[str, dict]]):
        self._response = response
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers: dict[str, str]):
        self._calls.append((url, headers))
        return self._response


def test_normalize_result_stores_id_as_private_torrent_reference():
    row = normalize_result({"id": "522748", "title": "X"})
    assert row["_torrent_id"] == "522748"


def test_normalize_result_missing_id_leaves_empty_private_torrent_reference():
    row = normalize_result({"title": "X"})
    assert row["_torrent_id"] == ""


def test_download_torrent_calls_tid_endpoint(monkeypatch):
    calls = []

    def _factory(*args, **kwargs):
        return _DummyClient(_DummyResponse(b"d8:announce"), calls)

    monkeypatch.setattr("app.mam.httpx.AsyncClient", _factory)
    client = MamClient()
    asyncio.run(client.download_torrent("522748"))
    assert calls[0][0].endswith("/tor/download.php?tid=522748")


def test_download_torrent_rejects_html_response(monkeypatch):
    calls = []

    def _factory(*args, **kwargs):
        return _DummyClient(_DummyResponse(b"<html>bad</html>", "text/html"), calls)

    monkeypatch.setattr("app.mam.httpx.AsyncClient", _factory)
    client = MamClient()
    with pytest.raises(MamError, match="not a torrent"):
        asyncio.run(client.download_torrent("522748"))


def test_download_torrent_requires_torrent_id():
    client = MamClient()
    with pytest.raises(MamError, match="Missing source torrent id"):
        asyncio.run(client.download_torrent(""))
