from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from app.config import settings
from app.db import get_pending_imports, mark_download_checked, record_imported_file, update_download_import_state

JUNK = {".ds_store", "thumbs.db", "desktop.ini", ".nfo"}
JUNK_EXT = {".part", ".parts", ".torrent", ".nfo"}
COMPLETE_STATES = {"uploading", "stalledup", "queuedup", "pausedup", "forcedup", "checkingup"}


def media_extensions_for_type(media_type: str) -> set[str]:
    exts = settings.import_audiobook_extensions if media_type == "audiobook" else settings.import_ebook_extensions
    return {e.strip().lower() for e in exts.split(",") if e.strip()}


def is_supported_media_file(path: str | Path, media_type: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in media_extensions_for_type(media_type)


def safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", name).strip().strip(".") or "unknown"


def safe_dirname(name: str) -> str:
    return safe_filename(name).replace("..", "_")


def find_importable_files(content_path: str, media_type: str) -> list[Path]:
    p = Path(content_path)
    if not p.exists():
        return []
    if p.is_file():
        return [p] if is_supported_media_file(p, media_type) else []
    files = [f for f in p.rglob("*") if f.is_file() and f.name.lower() not in JUNK and f.suffix.lower() not in JUNK_EXT and is_supported_media_file(f, media_type)]
    non_sample = [f for f in files if "sample" not in f.name.lower()]
    return non_sample or files


def build_destination_path(download: dict, source_path: str | Path, library_root: str) -> Path:
    src = Path(source_path).resolve()
    root = Path(library_root).resolve()
    title = safe_dirname(download.get("title") or download.get("qbit_name") or "unknown")
    content_path = Path(download.get("content_path") or src).resolve()
    rel = Path(safe_filename(src.name))
    if content_path.is_dir():
        try:
            rel = Path(*[safe_dirname(p) for p in src.relative_to(content_path).parts])
        except Exception:
            rel = Path(safe_filename(src.name))
    dest = (root / title / rel).resolve()
    if root not in dest.parents and dest != root:
        raise ValueError("Destination path escapes library root")
    return dest


def hardlink_file(src: str | Path, dst: str | Path, conflict_policy: str, dry_run: bool) -> str:
    srcp, dstp = Path(src), Path(dst)
    if not srcp.exists() or not srcp.is_file():
        raise FileNotFoundError(f"Source file missing or not regular: {srcp}")
    dstp.parent.mkdir(parents=True, exist_ok=True)
    if dstp.exists():
        if conflict_policy == "skip":
            return "skipped"
        if conflict_policy == "replace":
            dstp.unlink()
        elif conflict_policy != "skip":
            raise ValueError(f"Unsupported conflict policy: {conflict_policy}")
    if dry_run:
        return "linked"
    os.link(srcp, dstp)
    return "linked"


async def import_download(download: dict, qbit_torrent: dict | None) -> str:
    try:
        media_type = download["media_type"]
        root = settings.import_audiobook_library_path if media_type == "audiobook" else settings.import_ebook_library_path
        if not root:
            update_download_import_state(download["id"], "failed", "Import library path is not configured", completed=True)
            return "failed"
        files = find_importable_files(download.get("content_path") or "", media_type)
        if not files:
            update_download_import_state(download["id"], "failed", "No supported files found", completed=True)
            return "failed"
        ok = fail = skip = 0
        for f in files:
            dst = build_destination_path(download, f, root)
            try:
                status = hardlink_file(f, dst, settings.import_conflict_policy, settings.import_dry_run)
                record_imported_file(download["id"], str(f), str(dst), f.stat().st_size, "imported" if status == "linked" else "skipped")
                if status == "linked":
                    ok += 1
                else:
                    skip += 1
            except Exception as exc:
                fail += 1
                record_imported_file(download["id"], str(f), str(dst), None, "failed", str(exc))
        final = "imported" if ok and not fail and not skip else "skipped" if skip and not ok and not fail else "partial" if (ok or skip) and fail else "failed"
        update_download_import_state(download["id"], final, None if final != "failed" else "Import failed", completed=True)
        return final
    except Exception as exc:
        update_download_import_state(download["id"], "failed", str(exc), completed=True)
        return "failed"


async def run_import_once(qbit_client=None) -> dict:
    if not settings.import_enabled:
        return {"enabled": False, "processed": 0}
    if qbit_client is None:
        from app.qbittorrent import QbitClient
        qbit_client = QbitClient()
    pending = get_pending_imports()
    summary = {"enabled": True, "processed": 0, "imported": 0, "waiting": 0, "failed": 0}
    for d in pending:
        d = dict(d)
        if not d.get("qbit_hash"):
            mark_download_checked(d["id"], "waiting", "Missing qBittorrent hash")
            summary["waiting"] += 1
            continue
        t = await qbit_client.get_torrent(d["qbit_hash"])
        if not t:
            mark_download_checked(d["id"], "waiting", "Torrent not found in qBittorrent")
            summary["waiting"] += 1
            continue
        complete = t["progress"] >= settings.import_min_completion_ratio and (t["amount_left"] == 0 or t["progress"] >= 1.0)
        if settings.import_require_seeding_or_complete:
            complete = complete and (t.get("state", "").lower() in COMPLETE_STATES)
        if not complete:
            mark_download_checked(d["id"], "waiting")
            summary["waiting"] += 1
            continue
        status = await import_download(d, t)
        summary[status] = summary.get(status, 0) + 1
        summary["processed"] += 1
    return summary


async def importer_loop() -> None:
    while True:
        try:
            await run_import_once()
        except Exception as exc:
            print(f"Importer pass failed: {exc}")
        await asyncio.sleep(settings.import_interval_seconds)
