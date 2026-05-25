from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import add_history, init_db
from app.mam import MamClient, MamError
from app.models import AddRequest, SearchRequest
from app.qbittorrent import QbitClient, QbitError

app = FastAPI(title="BookGrab")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

mam_client = MamClient()
qbit_client = QbitClient()
_search_cache: dict[str, dict[int, dict[str, Any]]] = {}


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


@app.on_event("startup")
async def startup() -> None:
    os.makedirs(settings.config_dir, exist_ok=True)
    init_db()


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
    response.set_cookie("session", _sign_token(settings.app_username), httponly=True, samesite="lax")
    return response


@app.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    return response


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/search")
async def api_search(payload: SearchRequest, request: Request) -> dict[str, Any]:
    _require_login(request)
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

    sanitized = []
    per_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        per_id[row["id"]] = row
        safe = {k: v for k, v in row.items() if k != "_dl"}
        sanitized.append(safe)
    _search_cache[f"{payload.media_type}:{payload.query.lower()}:{payload.sort}"] = per_id
    return {"results": sanitized}


@app.post("/api/add")
async def api_add(payload: AddRequest, request: Request) -> dict[str, Any]:
    _require_login(request)

    matched: dict[str, Any] | None = None
    for cache in _search_cache.values():
        if payload.id in cache:
            matched = cache[payload.id]
            break
    if not matched:
        raise HTTPException(status_code=404, detail="Result not found in recent server-side search cache")

    try:
        torrent_bytes = await mam_client.download_torrent(matched.get("_dl", ""))
        category = await qbit_client.add_torrent(torrent_bytes, payload.media_type, matched.get("title", "mam"))
        add_history(str(payload.id), matched.get("title", ""), payload.media_type, category, "success")
    except (MamError, QbitError) as exc:
        add_history(str(payload.id), matched.get("title", ""), payload.media_type, "", "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": "Added to qBittorrent"}
