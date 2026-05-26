from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from app.config import settings
from app.db import get_pending_imports, mark_download_checked, record_imported_file, update_download_import_state, update_download_qbit_info

JUNK = {".ds_store", "thumbs.db", "desktop.ini", ".nfo"}
JUNK_EXT = {".part", ".parts", ".torrent", ".nfo"}
COMPLETE_STATES = {"uploading", "stalledup", "queuedup", "pausedup", "forcedup", "checkingup"}


def infer_qbit_category(download: dict) -> str:
    if download.get("qbit_category"):
        return str(download["qbit_category"])
    return settings.qbit_category_audiobooks if download.get("media_type") == "audiobook" else settings.qbit_category_ebooks


def normalize_match_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\.[a-z0-9]{1,5}$", "", text)
    text = re.sub(r"[_\-:;,.()[\]{}]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def recover_qbit_torrent_for_download(download: dict, qbit_client) -> dict | None:
    print(f"Importer: download id={download['id']} missing hash; attempting recovery")
    torrents = await qbit_client.get_torrents()
    expected_category = infer_qbit_category(download).strip().lower()
    title_keys = {normalize_match_text(download.get("title")), normalize_match_text(download.get("qbit_name"))}
    title_keys = {k for k in title_keys if k}

    candidates = []
    for t in torrents:
        t_name = normalize_match_text(t.get("name"))
        t_base = normalize_match_text(Path(t.get("content_path") or "").name)
        cat = (t.get("category") or "").strip().lower()
        if expected_category and cat and cat != expected_category:
            continue
        matched = False
        for key in title_keys:
            if (t_name and key in t_name) or (t_base and key in t_base):
                matched = True
                break
        if matched:
            candidates.append(t)

    if not candidates:
        msg = "Missing qBittorrent hash; no matching qBittorrent torrent found"
        mark_download_checked(download["id"], "waiting", msg)
        print(f"Importer: {msg} for id={download['id']}")
        return None
    if len(candidates) > 1:
        details = ", ".join(f"{c.get('name')} ({c.get('hash')})" for c in candidates[:5])
        msg = f"Missing qBittorrent hash; ambiguous matches: {details}"
        mark_download_checked(download["id"], "waiting", msg)
        print(f"Importer: ambiguous matches for id={download['id']}: {details}")
        return None

    selected = candidates[0]
    update_download_qbit_info(download["id"], qbit_hash=selected.get("hash"), qbit_name=selected.get("name"), save_path=selected.get("save_path"), content_path=selected.get("content_path"), import_status="queued", last_error=None)
    print(f"Importer: recovered hash for id={download['id']}: {selected.get('hash')}")
    return selected


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
        content_path = (qbit_torrent or {}).get("content_path") or download.get("content_path") or ""
        download["content_path"] = content_path
        print(f"Importer: selected content_path for id={download['id']}: {content_path}")
        if not content_path:
            update_download_import_state(download["id"], "waiting", "Missing content path from qBittorrent and download record")
            return "waiting"
        files = find_importable_files(content_path, media_type)
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
        print("Importer: disabled")
        return {"enabled": False, "processed": 0}
    if qbit_client is None:
        from app.qbittorrent import QbitClient
        qbit_client = QbitClient()
    pending = get_pending_imports()
    print(f"Importer: pass start; pending={len(pending)}")
    summary = {"enabled": True, "processed": 0, "imported": 0, "waiting": 0, "failed": 0}
    for d in pending:
        d = dict(d)
        print(f"Importer: checking id={d['id']} title={d.get('title')}")
        if not d.get("qbit_hash"):
            t = await recover_qbit_torrent_for_download(d, qbit_client)
            if not t:
                summary["waiting"] += 1
                continue
        else:
            t = await qbit_client.get_torrent(d["qbit_hash"])
        if not t:
            mark_download_checked(d["id"], "waiting", "Torrent not found in qBittorrent")
            summary["waiting"] += 1
            continue
        if t.get("name") or t.get("save_path") or t.get("content_path"):
            update_download_qbit_info(d["id"], qbit_name=t.get("name") or None, save_path=t.get("save_path") or None, content_path=t.get("content_path") or None)
            d["qbit_name"] = t.get("name") or d.get("qbit_name")
            d["save_path"] = t.get("save_path") or d.get("save_path")
            d["content_path"] = t.get("content_path") or d.get("content_path")
        progress = float(t.get("progress", 0.0) or 0.0)
        amount_left = int(t.get("amount_left", 0) or 0)
        state = str(t.get("state", ""))
        complete = amount_left == 0
        if complete and progress < 0.999999:
            warn = f"Torrent completion diagnostic: amount_left=0 but progress={progress}"
            print(f"Importer: warning id={d['id']} {warn}")
            update_download_qbit_info(d["id"], last_error=warn)
        if settings.import_require_seeding_or_complete:
            complete = complete and (state.lower() in COMPLETE_STATES)
        print(f"Importer: completion check id={d['id']} progress={progress} state={state} amount_left={amount_left} complete={complete}")
        if not complete:
            reason = f"Torrent not ready: progress={progress}, state={state}, amount_left={amount_left}"
            mark_download_checked(d["id"], "waiting", reason)
            summary["waiting"] += 1
            continue
        status = await import_download(d, t)
        print(f"Importer: hardlink result id={d['id']} status={status}")
        summary[status] = summary.get(status, 0) + 1
        summary["processed"] += 1
    print(f"Importer: pass end; summary={summary}")
    return summary


async def importer_loop() -> None:
    while True:
        try:
            await run_import_once()
        except Exception as exc:
            print(f"Importer pass failed: {exc}")
        await asyncio.sleep(settings.import_interval_seconds)
