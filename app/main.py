from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import add_history, get_db_path, get_import_status, get_qbit_mam_matches_by_mam_ids, get_qbit_mam_sync_status, init_db, record_download
from app.mam import MamClient, MamError
from app.models import AddRequest, SearchRequest
from app.importer import importer_loop, run_import_once
from app.qbittorrent import QbitClient, QbitError, _torrent_info_hash
from app.qbit_mam_sync import (
    QbitMamSyncAlreadyRunning,
    qbit_mam_sync_scheduler_loop,
    run_qbit_mam_sync_with_lock,
    sync_qbit_mam_hashes,
    validate_qbit_mam_sync_cron_config,
)
from app.library_presence import library_presence_service

app = FastAPI(title="BookGrab")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

mam_client = MamClient()
qbit_client = QbitClient()
_search_cache: dict[str, dict[int, dict[str, Any]]] = {}
_search_cache_updated_at: dict[str, float] = {}
_importer_task = None
_qbit_mam_sync_task = None
_SESSION_MAX_AGE_SECONDS = 60 * 60 * 8


def _is_insecure_default(value: str, insecure_values: set[str]) -> bool:
    return value.strip().lower() in insecure_values


def _validate_auth_config() -> None:
    if not settings.app_auth_enabled:
        return
    if _is_insecure_default(settings.app_password, {"", "change-me"}):
        raise RuntimeError("Refusing to start with APP_AUTH_ENABLED=true and insecure APP_PASSWORD")
    secret = settings.app_session_secret.strip()
    if _is_insecure_default(secret, {"", "change-this-random-secret"}):
        raise RuntimeError("Refusing to start with APP_AUTH_ENABLED=true and insecure APP_SESSION_SECRET")
    if len(secret) < 32:
        raise RuntimeError("Refusing to start with APP_AUTH_ENABLED=true and APP_SESSION_SECRET shorter than 32 characters")


def _is_https_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https"


def _validate_import_config() -> None:
    if settings.import_mode != "hardlink":
        raise RuntimeError("IMPORT_MODE currently supports only 'hardlink'")
    if settings.import_conflict_policy not in {"skip", "replace"}:
        raise RuntimeError("IMPORT_CONFLICT_POLICY must be 'skip' or 'replace'")
    if not settings.import_audiobook_library_path and not settings.import_ebook_library_path:
        raise RuntimeError("At least one of IMPORT_AUDIOBOOK_LIBRARY_PATH or IMPORT_EBOOK_LIBRARY_PATH must be set when importer is enabled")


def _sign_token(value: str) -> str:
    digest = hmac.new(settings.app_session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}:{digest}"


def _is_logged_in(request: Request) -> bool:
    if not settings.app_auth_enabled:
        return True
    token = request.cookies.get("session")
    if not token:
        return False
    expected = _sign_token(settings.app_username)
    return hmac.compare_digest(token, expected)


def _require_login(request: Request) -> None:
    if not _is_logged_in(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _prune_search_cache(now: float | None = None) -> None:
    current = now if now is not None else time.time()
    ttl = settings.search_cache_ttl_seconds
    max_entries = settings.search_cache_max_entries

    expired_keys = [key for key, updated_at in _search_cache_updated_at.items() if (current - updated_at) > ttl]
    for key in expired_keys:
        _search_cache.pop(key, None)
        _search_cache_updated_at.pop(key, None)

    if len(_search_cache_updated_at) <= max_entries:
        return

    keys_by_oldest = sorted(_search_cache_updated_at.items(), key=lambda item: item[1])
    keys_to_remove = len(_search_cache_updated_at) - max_entries
    for key, _ in keys_by_oldest[:keys_to_remove]:
        _search_cache.pop(key, None)
        _search_cache_updated_at.pop(key, None)


@app.on_event("startup")
async def startup() -> None:
    global _importer_task, _qbit_mam_sync_task
    uid = os.getuid()
    gid = os.getgid()
    db_path = get_db_path()
    config_dir = Path(settings.config_dir)

    print("BookGrab starting")
    print(f"Config directory: {config_dir}")
    print(f"Database path: {db_path}")
    print(f"Running as UID:GID: {uid}:{gid}")
    _validate_auth_config()

    try:
        init_db()
    except Exception as exc:
        config_exists = config_dir.exists()
        config_writable = os.access(config_dir, os.W_OK)
        raise RuntimeError(
            f"Failed to initialize SQLite database at {db_path}. "
            f"The /config directory must exist and be writable by the container user. "
            f"/config exists={config_exists}, writable={config_writable}. "
            f"Current UID:GID is {uid}:{gid}. "
            "On the host, try: mkdir -p ./config && chown -R <uid>:<gid> ./config && chmod -R u+rwX,g+rwX ./config"
        ) from exc

    if settings.import_min_completion_ratio_legacy_present:
        print("Startup warning: IMPORT_MIN_COMPLETION_RATIO is deprecated and ignored; importer completion now requires amount_left == 0")

    if settings.import_enabled:
        print("Importer: enabled")
        _validate_import_config()
        _importer_task = __import__("asyncio").create_task(importer_loop())
    else:
        print("Importer: disabled")

    if settings.mam_hash_lookup_enabled and settings.mam_hash_lookup_cron_enabled:
        cron_expression, cron_timezone = validate_qbit_mam_sync_cron_config()
        print(f"qBit/MAM sync scheduler: enabled with cron {cron_expression!r} in timezone {cron_timezone.key}")
        _qbit_mam_sync_task = asyncio.create_task(
            qbit_mam_sync_scheduler_loop(
                qbit_client=qbit_client,
                mam_client=mam_client,
                cron_expression=cron_expression,
                timezone=cron_timezone,
            )
        )
    else:
        print("qBit/MAM sync scheduler: disabled")


@app.on_event("shutdown")
async def shutdown() -> None:
    global _importer_task, _qbit_mam_sync_task
    if _importer_task:
        _importer_task.cancel()
    if _qbit_mam_sync_task:
        _qbit_mam_sync_task.cancel()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    if settings.app_auth_enabled and not _is_logged_in(request):
        return templates.TemplateResponse("index.html", {"request": request, "logged_in": False, "defaults": settings})
    return templates.TemplateResponse("index.html", {"request": request, "logged_in": True, "defaults": settings})


@app.post("/login")
async def login(request: Request) -> JSONResponse:
    if not settings.app_auth_enabled:
        return JSONResponse({"ok": True})
    data = await request.json()
    if data.get("username") != settings.app_username or data.get("password") != settings.app_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    response = JSONResponse({"ok": True})
    response.set_cookie(
        "session",
        _sign_token(settings.app_username),
        httponly=True,
        samesite="lax",
        secure=_is_https_request(request),
        max_age=_SESSION_MAX_AGE_SECONDS,
        expires=int(time.time()) + _SESSION_MAX_AGE_SECONDS,
    )
    return response


@app.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    return response


@app.get("/api/health")
async def health() -> dict[str, str | bool]:
    return {"ok": True, "database": "ok"}


@app.post("/api/search")
async def api_search(payload: SearchRequest, request: Request) -> dict[str, Any]:
    _require_login(request)
    _prune_search_cache()
    try:
        rows = await mam_client.search(
            query=payload.query,
            media_type=payload.media_type,
            search_in=payload.search_in,
            sort=payload.sort,
            search_type=settings.default_search_type,
        )
    except MamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    qbit_matches = {}
    if settings.mam_hash_lookup_enabled:
        qbit_matches = get_qbit_mam_matches_by_mam_ids([int(row["id"]) for row in rows])

    sanitized = []
    per_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        per_id[row["id"]] = row
        safe = {k: v for k, v in row.items() if not k.startswith("_")}
        qbit_match = qbit_matches.get(int(row["id"]))
        safe["in_qbit"] = qbit_match is not None
        safe["qbit_name"] = qbit_match["qbit_name"] if qbit_match is not None else None
        sanitized.append(safe)
    if payload.media_type == "audiobook":
        for safe in sanitized:
            try:
                in_library, library_matches = await library_presence_service.annotate(safe)
            except Exception:  # noqa: BLE001
                in_library, library_matches = False, []
            safe["in_library"] = in_library
            safe["library_matches"] = library_matches
    else:
        for safe in sanitized:
            safe["in_library"] = False
            safe["library_matches"] = []

    cache_key = f"{payload.media_type}:{payload.query.lower()}:{payload.sort}"
    _search_cache[cache_key] = per_id
    _search_cache_updated_at[cache_key] = time.time()
    _prune_search_cache()
    return {"results": sanitized}


@app.post("/api/add")
async def api_add(payload: AddRequest, request: Request) -> dict[str, Any]:
    _require_login(request)
    _prune_search_cache()

    matched: dict[str, Any] | None = None
    cached_media_type: str | None = None
    for cache_key, cache in _search_cache.items():
        if payload.id in cache:
            matched = cache[payload.id]
            cached_media_type = cache_key.split(":", 1)[0]
            break
    if not matched or cached_media_type not in {"audiobook", "ebook"}:
        raise HTTPException(status_code=404, detail="Result not found in recent server-side search cache")

    try:
        torrent_id = str(matched.get("_torrent_id") or "").strip()
        if not torrent_id:
            keys = sorted(matched.keys())
            raise MamError(f"Missing source torrent id; available result keys: {keys}")
        torrent_bytes = await mam_client.download_torrent(torrent_id)
        info_hash = _torrent_info_hash(torrent_bytes)
        existing = await qbit_client.get_torrent(info_hash)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Torrent is already loaded in qBittorrent as {existing.get('name') or info_hash}",
            )
        result = await qbit_client.add_torrent(torrent_bytes, cached_media_type, matched.get("title", "mam"))
        add_history(str(payload.id), matched.get("title", ""), cached_media_type, result.get("category", ""), "success")
        import_status = "queued" if settings.import_enabled else "disabled"
        record_download(mam_id=str(payload.id), title=matched.get("title", ""), author=matched.get("author", ""), narrator=matched.get("narrator", ""), series=matched.get("series", ""), media_type=cached_media_type, qbit_category=result.get("category"), qbit_hash=result.get("hash"), qbit_name=result.get("name"), save_path=result.get("save_path"), content_path=result.get("content_path"), import_status=import_status, last_error=result.get("last_error"))
    except HTTPException:
        add_history(str(payload.id), matched.get("title", ""), cached_media_type, "", "failed", "Duplicate already loaded in qBittorrent")
        raise
    except (MamError, QbitError) as exc:
        add_history(str(payload.id), matched.get("title", ""), cached_media_type, "", "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": "Added to qBittorrent", "hash": result.get("hash"), "category": result.get("category"), "import_status": import_status}


@app.post("/api/import/run")
async def api_import_run(request: Request) -> dict[str, Any]:
    _require_login(request)
    if not settings.import_enabled:
        return {"enabled": False, "message": "Importer is disabled"}
    return await run_import_once(qbit_client)


@app.get("/api/import/status")
async def api_import_status(request: Request) -> dict[str, Any]:
    _require_login(request)
    return get_import_status()


@app.post("/api/qbit-mam-sync/run")
async def api_qbit_mam_sync_run(request: Request) -> dict[str, Any]:
    _require_login(request)
    try:
        result = await run_qbit_mam_sync_with_lock(
            qbit_client=qbit_client,
            mam_client=mam_client,
            sync_func=sync_qbit_mam_hashes,
        )
    except QbitMamSyncAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail="qBit/MAM sync is already running") from exc
    assert result is not None
    return result


@app.get("/api/qbit-mam-sync/status")
async def api_qbit_mam_sync_status(request: Request) -> dict[str, Any]:
    _require_login(request)
    status = get_qbit_mam_sync_status()
    return {
        "enabled": settings.mam_hash_lookup_enabled,
        "delay_seconds": settings.mam_hash_lookup_delay_seconds,
        "max_per_run": settings.mam_hash_lookup_max_per_run,
        **status,
    }
