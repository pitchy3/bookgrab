from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings

MEDIA_TO_MAIN_CAT = {"audiobook": "13", "ebook": "14"}
INFO_HASH_RE = re.compile(r"^[a-fA-F0-9]{40}$")


class MamError(Exception):
    pass


def _build_cookie_header() -> str:
    if settings.mam_cookie:
        return settings.mam_cookie
    parts = []
    if settings.mam_uid:
        parts.append(f"mam_id={settings.mam_uid}")
    if settings.mam_session:
        parts.append(f"mam_session={settings.mam_session}")
    return "; ".join(parts)


def _parse_people(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item.get("name", "")).strip() for item in value if isinstance(item, dict)).strip(", ")
    if isinstance(value, dict):
        return ", ".join(str(v).strip() for v in value.values() if str(v).strip())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return ", ".join(str(v).strip() for v in parsed.values() if str(v).strip())
        except json.JSONDecodeError:
            pass
        return text
    return ""


def build_search_payload(
    query: str,
    media_type: str,
    search_in: list[str],
    sort: str,
    search_type: str,
    start_number: int = 0,
) -> dict[str, Any]:
    # API docs indicate tor.srchIn is an array/list of field names.
    allowed_search_in = [k for k in ["title", "author", "narrator", "series"] if k in search_in]
    if not allowed_search_in:
        allowed_search_in = ["title"]

    return {
        "tor": {
            "text": query,
            "srchIn": allowed_search_in,
            "searchType": search_type,
            "sortType": sort,
            "startNumber": str(start_number),
            "main_cat": [MEDIA_TO_MAIN_CAT[media_type]],
        },
        "thumbnail": "true",
    }


def _parse_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, float):
        return value != 0.0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    torrent_id = str(item.get("id", "")).strip()
    return {
        "id": int(item.get("id", 0)),
        "title": str(item.get("title", "")).strip(),
        "author": _parse_people(item.get("author_info")),
        "narrator": _parse_people(item.get("narrator_info")),
        "series": _parse_people(item.get("series_info")),
        "filetypes": str(item.get("filetypes", "")),
        "filetype": str(item.get("filetype", "")),
        "size": str(item.get("size", "")),
        "seeders": int(item.get("seeders", 0) or 0),
        "leechers": int(item.get("leechers", 0) or 0),
        "free": _parse_flag(item.get("free", False)) or _parse_flag(item.get("fl_vip", False)),
        "vip": _parse_flag(item.get("vip", False)),
        "my_snatched": _parse_flag(item.get("my_snatched", False)),
        "added": str(item.get("added", "")),
        "catname": str(item.get("catname", "")),
        "_torrent_id": torrent_id,
    }


class MamClient:
    def __init__(self) -> None:
        self.base_url = settings.mam_base_url
        self.timeout = settings.mam_timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "BookGrab/1.0"}
        cookie = _build_cookie_header()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    async def search(self, query: str, media_type: str, search_in: list[str], sort: str, search_type: str) -> list[dict[str, Any]]:
        payload = build_search_payload(query, media_type, search_in, sort, search_type)
        url = f"{self.base_url}/tor/js/loadSearchJSONbasic.php"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise MamError("Failed to query search API. Check source auth/session and URL.") from exc
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise MamError("Unexpected response from search API")
        filtered = [normalize_result(r) for r in rows if str(r.get("main_cat", "")) == MEDIA_TO_MAIN_CAT[media_type]]
        return filtered

    async def lookup_by_hash(self, info_hash: str) -> dict[str, Any] | None:
        normalized_hash = str(info_hash or "").strip().lower()
        if not INFO_HASH_RE.fullmatch(normalized_hash):
            raise MamError("Invalid torrent info hash")
        payload = {"tor": {"hash": normalized_hash}, "thumbnail": "true"}
        url = f"{self.base_url}/tor/js/loadSearchJSONbasic.php"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise MamError("Failed to query MAM hash lookup API. Check source auth/session and URL.") from exc
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        if rows in (None, ""):
            return None
        if not isinstance(rows, list):
            raise MamError("Unexpected response from MAM hash lookup API")
        if not rows:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            raise MamError("Unexpected row from MAM hash lookup API")
        return normalize_result(first)

    async def download_torrent(self, torrent_id: str) -> bytes:
        tid = str(torrent_id).strip()
        if not tid:
            raise MamError("Missing source torrent id")
        url = f"{self.base_url}/tor/download.php?tid={tid}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise MamError("Failed downloading torrent. Session may be expired.") from exc
        content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        body = resp.content
        if content_type == "application/x-bittorrent" or body.startswith(b"d"):
            return body
        raise MamError(
            f"MAM download response was not a torrent (content-type={content_type or 'unknown'})"
        )
