import asyncio

import pytest

from app.qbittorrent import QbitClient, QbitError, _torrent_info_hash


class _Resp:
    def __init__(self, status_code=200, text="Ok.", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, data=None, files=None):
        if url.endswith('/auth/login'):
            return _Resp(text='Ok.')
        return _Resp(text='Ok.')

    async def get(self, url, params=None):
        return _Resp(payload=[])


def test_add_torrent_looks_up_by_info_hash(monkeypatch):
    import app.qbittorrent as qbm

    monkeypatch.setattr(qbm.httpx, 'AsyncClient', _Client)

    torrent_bytes = b"d8:announce3:xyz4:infod4:name4:Book6:lengthi12345eee"
    expected_hash = _torrent_info_hash(torrent_bytes)
    looked_up = {"hash": None}

    async def _fake_get_torrent(self, hash):
        looked_up["hash"] = hash
        return {"hash": hash, "name": "Book", "category": "audiobooks", "save_path": "/x", "content_path": "/x/Book"}

    monkeypatch.setattr(QbitClient, 'get_torrent', _fake_get_torrent)

    client = QbitClient()
    result = asyncio.run(client.add_torrent(torrent_bytes, 'audiobook', 'Target Name'))
    assert looked_up['hash'] == expected_hash
    assert result['hash'] == expected_hash


def test_torrent_info_hash_extracts_info_dict_hash():
    torrent_bytes = b"d8:announce3:xyz4:infod4:name4:Book6:lengthi12345eee"
    assert _torrent_info_hash(torrent_bytes) == "05c591eecfd83ffc3f863bb011bd324ea218c6e8"


def test_torrent_info_hash_wraps_bencode_parse_failures():
    torrent_bytes = b"d4:infod4:name4:Book6:lengthi12345e"
    with pytest.raises(QbitError, match="malformed bencode structure"):
        _torrent_info_hash(torrent_bytes)


def test_get_torrents_by_hashes_uses_hashes_query_param(monkeypatch):
    import app.qbittorrent as qbm

    first_hash = "abcdef1234567890abcdef1234567890abcdef12"
    second_hash = "1234567890abcdef1234567890abcdef12345678"
    calls = []

    class _HashClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, data=None, files=None):
            return _Resp(text="Ok.")

        async def get(self, url, params=None):
            calls.append((url, params))
            return _Resp(payload=[{"hash": first_hash.upper(), "name": "Loaded"}])

    monkeypatch.setattr(qbm.httpx, "AsyncClient", _HashClient)

    result = asyncio.run(QbitClient().get_torrents_by_hashes([first_hash.upper(), first_hash, "not-a-hash", second_hash]))

    assert len(calls) == 1
    assert calls[0][0].endswith("/api/v2/torrents/info")
    assert calls[0][1] == {"hashes": f"{first_hash}|{second_hash}"}
    assert result[0]["hash"] == first_hash.upper()


def test_get_torrents_by_hashes_skips_qbit_when_no_hashes(monkeypatch):
    import app.qbittorrent as qbm

    def _fail_client(*args, **kwargs):
        raise AssertionError("qBittorrent should not be contacted without valid hashes")

    monkeypatch.setattr(qbm.httpx, "AsyncClient", _fail_client)

    assert asyncio.run(QbitClient().get_torrents_by_hashes(["", "not-a-hash"])) == []


def test_get_torrents_by_hashes_chunks_large_hash_lists(monkeypatch):
    import app.qbittorrent as qbm

    hashes = [f"{index:040x}" for index in range(51)]
    calls = []

    class _ChunkClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, data=None, files=None):
            return _Resp(text="Ok.")

        async def get(self, url, params=None):
            calls.append(params["hashes"])
            return _Resp(payload=[])

    monkeypatch.setattr(qbm.httpx, "AsyncClient", _ChunkClient)

    assert asyncio.run(QbitClient().get_torrents_by_hashes(hashes)) == []
    assert len(calls) == 2
    assert calls[0] == "|".join(hashes[:50])
    assert calls[1] == hashes[50]
