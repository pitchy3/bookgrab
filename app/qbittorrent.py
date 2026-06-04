from __future__ import annotations

import asyncio
import hashlib
import httpx

from app.config import settings


class QbitError(Exception):
    pass


class QbitClient:
    def __init__(self) -> None:
        self.base_url = settings.qbit_base_url
        self.username = settings.qbit_username
        self.password = settings.qbit_password
        self.timeout = settings.mam_timeout_seconds

    async def _login(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(f"{self.base_url}/api/v2/auth/login", data={"username": self.username, "password": self.password})
        if resp.status_code >= 400 or "Ok." not in resp.text:
            raise QbitError("qBittorrent login failed")

    def _normalize(self, t: dict) -> dict:
        return {
            "hash": t.get("hash"), "name": t.get("name"), "category": t.get("category"), "tracker": t.get("tracker"), "save_path": t.get("save_path"), "content_path": t.get("content_path"),
            "progress": float(t.get("progress", 0.0) or 0.0), "state": t.get("state"), "completion_on": t.get("completion_on"), "amount_left": int(t.get("amount_left", 0) or 0), "size": int(t.get("size", 0) or 0),
        }

    async def get_torrents(self, client: httpx.AsyncClient | None = None) -> list[dict]:
        own = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            if own:
                await self._login(client)
            resp = await client.get(f"{self.base_url}/api/v2/torrents/info")
            resp.raise_for_status()
            return [self._normalize(t) for t in resp.json()]
        finally:
            if own:
                await client.aclose()


    async def get_torrent_trackers(self, hash: str, client: httpx.AsyncClient | None = None) -> list[dict]:
        own = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            if own:
                await self._login(client)
            resp = await client.get(f"{self.base_url}/api/v2/torrents/trackers", params={"hash": hash})
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                return []
            return [row for row in rows if isinstance(row, dict)]
        finally:
            if own:
                await client.aclose()

    async def get_torrent(self, hash: str) -> dict | None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._login(client)
            resp = await client.get(f"{self.base_url}/api/v2/torrents/info", params={"hashes": hash})
            resp.raise_for_status()
            js = resp.json()
            if not js:
                return None
            return self._normalize(js[0])

    async def add_torrent(self, torrent_bytes: bytes, media_type: str, name: str) -> dict:
        expected_hash = _torrent_info_hash(torrent_bytes)
        category = settings.qbit_category_audiobooks if media_type == "audiobook" else settings.qbit_category_ebooks
        save_path = settings.qbit_save_path_audiobooks if media_type == "audiobook" else settings.qbit_save_path_ebooks
        form_data = {"category": category}
        if save_path:
            form_data["savepath"] = save_path
        files = {"torrents": (f"{name}.torrent", torrent_bytes, "application/x-bittorrent")}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                await self._login(client)
                before = await self.get_torrents(client)
                resp = await client.post(f"{self.base_url}/api/v2/torrents/add", data=form_data, files=files)
            except httpx.HTTPError as exc:
                raise QbitError("qBittorrent is unavailable") from exc
        if resp.status_code >= 400:
            raise QbitError("Failed to upload torrent to qBittorrent")
        if "Fails." in resp.text:
            raise QbitError("Torrent add failed (possibly duplicate)")
        after = []
        for _ in range(5):
            try:
                found = await self.get_torrent(expected_hash)
                if found:
                    after = [found]
                    break
            except httpx.HTTPError:
                after = []
            await asyncio.sleep(0.4)
        selected = after[0] if after else None
        return {
            "category": category,
            "hash": selected.get("hash") if selected else None,
            "name": selected.get("name") if selected else name,
            "save_path": selected.get("save_path") if selected else save_path,
            "content_path": selected.get("content_path") if selected else None,
            "last_error": None if selected else "Could not find uploaded torrent in qBittorrent by info hash; importer will wait until matched manually.",
        }


def _bencode_item_end(raw: bytes, idx: int) -> int:
    if idx >= len(raw):
        raise ValueError("invalid bencode: unexpected end")
    token = raw[idx:idx + 1]
    if token == b'i':
        end = raw.find(b'e', idx + 1)
        if end < 0:
            raise ValueError("invalid bencode integer")
        return end + 1
    if token == b'l' or token == b'd':
        j = idx + 1
        while j < len(raw) and raw[j:j + 1] != b'e':
            j = _bencode_item_end(raw, j)
            if token == b'd':
                j = _bencode_item_end(raw, j)
        if j >= len(raw):
            raise ValueError("invalid bencode container")
        return j + 1
    if token.isdigit():
        colon = raw.find(b':', idx)
        if colon < 0:
            raise ValueError("invalid bencode string")
        size = int(raw[idx:colon])
        return colon + 1 + size
    raise ValueError("invalid bencode token")


def _torrent_info_hash(torrent_bytes: bytes) -> str:
    if not torrent_bytes.startswith(b'd'):
        raise QbitError("Invalid torrent: expected top-level dictionary")
    i = 1
    while i < len(torrent_bytes) and torrent_bytes[i:i + 1] != b'e':
        colon = torrent_bytes.find(b':', i)
        if colon < 0:
            raise QbitError("Invalid torrent: malformed key")
        try:
            key_len = int(torrent_bytes[i:colon])
        except ValueError as exc:
            raise QbitError("Invalid torrent: malformed key length") from exc
        key_start = colon + 1
        key_end = key_start + key_len
        key = torrent_bytes[key_start:key_end]
        value_start = key_end
        try:
            value_end = _bencode_item_end(torrent_bytes, value_start)
        except ValueError as exc:
            raise QbitError("Invalid torrent: malformed bencode structure") from exc
        if key == b'info':
            if torrent_bytes[value_start:value_start + 1] != b'd':
                raise QbitError("Invalid torrent: info is not a dictionary")
            return hashlib.sha1(torrent_bytes[value_start:value_end]).hexdigest()
        i = value_end
    raise QbitError("Invalid torrent: missing info dictionary")
