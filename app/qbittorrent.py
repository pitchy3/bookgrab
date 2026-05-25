from __future__ import annotations

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
        url = f"{self.base_url}/api/v2/auth/login"
        resp = await client.post(url, data={"username": self.username, "password": self.password})
        if resp.status_code >= 400 or "Ok." not in resp.text:
            raise QbitError("qBittorrent login failed")

    async def add_torrent(self, torrent_bytes: bytes, media_type: str, name: str) -> str:
        category = settings.qbit_category_audiobooks if media_type == "audiobook" else settings.qbit_category_ebooks
        save_path = settings.qbit_save_path_audiobooks if media_type == "audiobook" else settings.qbit_save_path_ebooks
        form_data = {"category": category}
        if save_path:
            form_data["savepath"] = save_path

        files = {"torrents": (f"{name}.torrent", torrent_bytes, "application/x-bittorrent")}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                await self._login(client)
                resp = await client.post(f"{self.base_url}/api/v2/torrents/add", data=form_data, files=files)
            except httpx.HTTPError as exc:
                raise QbitError("qBittorrent is unavailable") from exc
        if resp.status_code >= 400:
            raise QbitError("Failed to upload torrent to qBittorrent")
        if "Fails." in resp.text:
            raise QbitError("Torrent add failed (possibly duplicate)")
        return category
