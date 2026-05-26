from __future__ import annotations

import asyncio
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
            "hash": t.get("hash"), "name": t.get("name"), "category": t.get("category"), "save_path": t.get("save_path"), "content_path": t.get("content_path"),
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
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    await self._login(client)
                    after = await self.get_torrents(client)
            except httpx.HTTPError:
                after = []
            old_hashes = {t["hash"] for t in before if t.get("hash")}
            if any(t.get("hash") not in old_hashes for t in after):
                break
            await asyncio.sleep(0.4)
        old_hashes = {t["hash"] for t in before if t.get("hash")}
        candidates = [t for t in after if t.get("hash") not in old_hashes]
        selected = None
        if len(candidates) == 1:
            selected = candidates[0]
        elif len(candidates) > 1:
            name_l = (name or "").lower()
            strong = [c for c in candidates if c.get("category") == category and name_l and name_l in (c.get("name") or "").lower()]
            if len(strong) == 1:
                selected = strong[0]
            elif not strong:
                weak = [c for c in candidates if c.get("category") == category or (name_l and name_l in (c.get("name") or "").lower())]
                if len(weak) == 1:
                    selected = weak[0]
        return {
            "category": category,
            "hash": selected.get("hash") if selected else None,
            "name": selected.get("name") if selected else name,
            "save_path": selected.get("save_path") if selected else save_path,
            "content_path": selected.get("content_path") if selected else None,
            "last_error": None if selected else "Could not determine torrent hash after add; importer will wait until matched manually.",
        }
