import asyncio

from app.qbittorrent import QbitClient


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


def test_add_torrent_multiple_candidates_does_not_guess(monkeypatch):
    import app.qbittorrent as qbm

    monkeypatch.setattr(qbm.httpx, 'AsyncClient', _Client)

    calls = {"n": 0}

    async def _fake_get_torrents(self, client=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"hash": "old", "name": "old", "category": "audiobooks", "save_path": "/x", "content_path": "/x/old"}]
        return [
            {"hash": "old", "name": "old", "category": "audiobooks", "save_path": "/x", "content_path": "/x/old"},
            {"hash": "new1", "name": "A.mp3", "category": "audiobooks", "save_path": "/x", "content_path": "/x/A.mp3"},
            {"hash": "new2", "name": "B.mp3", "category": "audiobooks", "save_path": "/x", "content_path": "/x/B.mp3"},
        ]

    monkeypatch.setattr(QbitClient, 'get_torrents', _fake_get_torrents)

    client = QbitClient()
    result = asyncio.run(client.add_torrent(b'd8:announce', 'audiobook', 'Target Name'))
    assert result['hash'] is None
