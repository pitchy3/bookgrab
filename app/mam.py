from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

MEDIA_TO_MAIN_CAT = {"audiobook": "13", "ebook": "14"}
INFO_HASH_RE = re.compile(r"^[a-fA-F0-9]{40}$")
MAM_ID_RE = re.compile(r"(?:^|;\s*)mam_id=([^;\s]+)")


class MamError(Exception):
    pass


class MamDynamicSeedboxConfigError(MamError):
    pass


def normalize_mam_cookie(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "=" not in text and ";" not in text:
        return f"mam_id={text}"
    return text


def _read_cookie_file(path_value: str) -> str:
    path_text = str(path_value or "").strip()
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.is_file():
        return ""
    try:
        return normalize_mam_cookie(path.read_text(encoding="utf-8").strip())
    except OSError:
        return ""


def load_mam_cookie() -> str:
    for source in (getattr(settings, "mam_cookie_file", ""), getattr(settings, "mam_cookie_store_path", "")):
        cookie = _read_cookie_file(source)
        if cookie:
            return cookie
    cookie = normalize_mam_cookie(settings.mam_cookie)
    if cookie:
        return cookie
    parts = []
    if settings.mam_uid:
        parts.append(f"mam_id={settings.mam_uid.strip()}")
    if settings.mam_session:
        parts.append(f"mam_session={settings.mam_session.strip()}")
    return "; ".join(parts)


def _build_cookie_header() -> str:
    return load_mam_cookie()


def mam_cookie_has_mam_id(cookie: str | None = None) -> bool:
    return MAM_ID_RE.search(cookie if cookie is not None else load_mam_cookie()) is not None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_dynamic_seedbox_state() -> dict[str, Any]:
    path = Path(settings.mam_dynamic_seedbox_state_path)
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def save_dynamic_seedbox_state(state: dict[str, Any]) -> None:
    path = Path(settings.mam_dynamic_seedbox_state_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    except OSError:
        pass


def _message_from_payload(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("message", "msg", "Message", "Msg", "error", "Error"):
            if data.get(key) is not None:
                return str(data[key])
    return ""


def _success_from_payload(data: Any, message: str) -> bool:
    if message.strip().lower() == "no change":
        return True
    if isinstance(data, dict):
        for key in ("Success", "success", "ok"):
            if key in data:
                return data[key] is True or str(data[key]).lower() == "true" or data[key] == 1
    return False


def _classify_mam_http_error(exc: httpx.HTTPError, context: str) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"Network timeout while querying {context}. Check connectivity and MAM_BASE_URL."
    if isinstance(exc, httpx.ConnectError):
        return f"Connection failure while querying {context}. Check network/VPN and MAM_BASE_URL."
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in {401, 403}:
            return f"MAM returned HTTP {code} for {context}; likely auth/session/IP association issue. Check MAM API mam_id cookie and dynamic seedbox settings."
        return f"MAM returned HTTP {code} for {context}. Check MAM_BASE_URL and source availability."
    return f"Failed to query {context}. Check source auth/session and URL."


def _sanitize_dynamic_message(message: str, status_code: int | None = None) -> str:
    msg = (message or "").strip() or (f"HTTP {status_code}" if status_code else "Unknown response")
    lower = msg.lower()
    if "incorrect session type" in lower:
        return "Incorrect session type; use an IP/ASN-locked MAM API mam_id session, not a browser session cookie."
    if "no session cookie" in lower:
        return "No Session Cookie; configure a MAM API mam_id cookie/token."
    if "invalid cookie" in lower:
        return "Invalid session - Invalid Cookie; check the MAM API mam_id token."
    if "ip mismatch" in lower:
        return "Invalid session - IP mismatch; create/refresh the API session from the same VPN/container egress IP."
    if "asn mismatch" in lower:
        return "Invalid session - ASN mismatch; create/refresh the API session from the same VPN/container ASN."
    return msg


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

    async def _refresh_before_request(self) -> None:
        if not settings.mam_dynamic_seedbox_enabled or not settings.mam_dynamic_seedbox_run_before_search:
            return
        result = await self.refresh_dynamic_seedbox_ip(force=False)
        if result.get("skipped") or result.get("cooldown") or result.get("ok"):
            return
        if result.get("auth_config_error"):
            raise MamError(f"MAM dynamic seedbox refresh failed: {result.get('message')}")

    async def refresh_dynamic_seedbox_ip(self, force: bool = False) -> dict[str, Any]:
        state = load_dynamic_seedbox_state()
        now = datetime.now(UTC)
        last_attempt = _parse_ts(state.get("last_attempt_at"))
        if last_attempt and not force:
            elapsed = (now - last_attempt).total_seconds()
            if elapsed < settings.mam_dynamic_seedbox_min_interval_seconds:
                return {**state, "ok": bool(state.get("ok")), "skipped": True, "cooldown": True, "message": state.get("message") or "Skipped due to cooldown"}

        cookie = load_mam_cookie()
        if not cookie:
            result = {**state, "ok": False, "skipped": True, "cooldown": False, "auth_config_error": True, "message": "Missing MAM cookie; configure a MAM API mam_id token."}
            return result
        if not mam_cookie_has_mam_id(cookie):
            result = {**state, "ok": False, "skipped": True, "cooldown": False, "auth_config_error": True, "message": "Missing mam_id; dynamic seedbox refresh requires an IP/ASN-locked MAM API mam_id session."}
            return result

        attempt_at = _now_iso()
        result: dict[str, Any] = {"ok": False, "skipped": False, "cooldown": False, "last_attempt_at": attempt_at}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(settings.mam_dynamic_seedbox_url, headers={"User-Agent": "BookGrab/1.0", "Cookie": cookie})
            status_code = resp.status_code
            try:
                data = resp.json()
            except ValueError:
                data = {}
            message = _sanitize_dynamic_message(_message_from_payload(data), status_code)
            ok = status_code == 200 and _success_from_payload(data, message)
            cooldown = status_code == 429 or "last change too recent" in message.lower()
            if ok:
                result["last_success_at"] = attempt_at
            result.update({"ok": ok, "cooldown": cooldown, "status_code": status_code, "message": message})
            if status_code == 403:
                result["auth_config_error"] = True
            if isinstance(data, dict):
                result["ip"] = data.get("ip") or data.get("IP")
                result["asn"] = data.get("asn") or data.get("ASN")
                result["as"] = data.get("as") or data.get("AS")
        except httpx.HTTPError as exc:
            result.update({"message": _classify_mam_http_error(exc, "MAM dynamic seedbox refresh"), "network_error": True})
        state.update({k: v for k, v in result.items() if k not in {"skipped"} and v is not None})
        save_dynamic_seedbox_state(state)
        return {**state, **result}

    async def search(self, query: str, media_type: str, search_in: list[str], sort: str, search_type: str) -> list[dict[str, Any]]:
        await self._refresh_before_request()
        payload = build_search_payload(query, media_type, search_in, sort, search_type)
        url = f"{self.base_url}/tor/js/loadSearchJSONbasic.php"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise MamError(_classify_mam_http_error(exc, "search API")) from exc
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise MamError("Unexpected response from search API")
        filtered = [normalize_result(r) for r in rows if str(r.get("main_cat", "")) == MEDIA_TO_MAIN_CAT[media_type]]
        return filtered

    async def lookup_by_hash(self, info_hash: str) -> dict[str, Any] | None:
        await self._refresh_before_request()
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
                raise MamError(_classify_mam_http_error(exc, "MAM hash lookup API")) from exc
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
        await self._refresh_before_request()
        tid = str(torrent_id).strip()
        if not tid:
            raise MamError("Missing source torrent id")
        url = f"{self.base_url}/tor/download.php?tid={tid}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise MamError(_classify_mam_http_error(exc, "torrent download")) from exc
        content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        body = resp.content
        if content_type == "application/x-bittorrent" or body.startswith(b"d"):
            return body
        raise MamError(
            f"MAM download response was not a torrent (content-type={content_type or 'unknown'})"
        )
