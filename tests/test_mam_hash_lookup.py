import asyncio

from app.mam import MamClient


class Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class Client:
    payloads = []
    response_payload = {"data": []}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json=None, headers=None):
        self.__class__.payloads.append(json)
        return Resp(self.__class__.response_payload)


def test_lookup_by_hash_returns_normalized_row(monkeypatch):
    import app.mam as mam

    Client.payloads = []
    Client.response_payload = {"data": [{"id": "110685", "title": "The First Law Trilogy", "seeders": "4", "catname": "Audiobooks"}]}
    monkeypatch.setattr(mam.httpx, "AsyncClient", Client)

    row = asyncio.run(MamClient().lookup_by_hash("CE24CCB52739482BE59F8539ED403889F4856638"))

    assert row["id"] == 110685
    assert row["title"] == "The First Law Trilogy"
    assert row["seeders"] == 4
    assert Client.payloads[0]["tor"]["hash"] == "ce24ccb52739482be59f8539ed403889f4856638"


def test_lookup_by_hash_returns_none_for_no_rows(monkeypatch):
    import app.mam as mam

    Client.payloads = []
    Client.response_payload = {"data": []}
    monkeypatch.setattr(mam.httpx, "AsyncClient", Client)

    row = asyncio.run(MamClient().lookup_by_hash("ce24ccb52739482be59f8539ed403889f4856638"))

    assert row is None
