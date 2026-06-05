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


def test_get_torrent_trackers_uses_qbit_tracker_endpoint(monkeypatch):
    calls = []

    class ClientWithTrackers(_Client):
        async def get(self, url, params=None):
            calls.append((url, params))
            if url.endswith('/torrents/trackers'):
                return _Resp(payload=[{"url": "https://www.myanonamouse.net/announce"}])
            return _Resp(payload=[])

        async def aclose(self):
            return None

    import app.qbittorrent as qbm

    monkeypatch.setattr(qbm.httpx, 'AsyncClient', ClientWithTrackers)

    trackers = asyncio.run(QbitClient().get_torrent_trackers("a" * 40))

    assert trackers == [{"url": "https://www.myanonamouse.net/announce"}]
    assert calls[-1] == ("http://qbittorrent:8080/api/v2/torrents/trackers", {"hash": "a" * 40})
