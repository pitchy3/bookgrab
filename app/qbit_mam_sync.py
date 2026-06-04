from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from app.config import settings
from app.db import (
    get_qbit_mam_cache_by_hash,
    get_qbit_mam_sync_status,
    mark_qbit_mam_inventory_seen,
    mark_qbit_mam_seen,
    upsert_qbit_mam_cache,
)
from app.mam import MamClient
from app.qbittorrent import QbitClient

INFO_HASH_RE = re.compile(r"^[a-fA-F0-9]{40}$")


def normalize_info_hash(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if INFO_HASH_RE.fullmatch(text):
        return text
    return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _media_type_from_row(row: dict[str, Any]) -> str | None:
    catname = str(row.get("catname", "")).lower()
    if "audio" in catname:
        return "audiobook"
    if "ebook" in catname or "book" in catname:
        return "ebook"
    return None


def _is_due(row: Any, now: datetime) -> bool:
    if row is None:
        return True
    looked_up_at = _parse_dt(row["looked_up_at"])
    if looked_up_at is None:
        return True
    status = row["lookup_status"]
    if status == "error":
        return now - looked_up_at >= timedelta(hours=settings.mam_hash_lookup_retry_error_ttl_hours)
    if status == "no_match":
        return now - looked_up_at >= timedelta(days=settings.mam_hash_lookup_no_match_ttl_days)
    return now - looked_up_at >= timedelta(days=settings.mam_hash_lookup_cache_ttl_days)


def format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m" if secs == 0 else f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


async def sync_qbit_mam_hashes(
    qbit_client: QbitClient | None = None,
    mam_client: MamClient | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    logger: Callable[[str], Any] = print,
) -> dict[str, Any]:
    if not settings.mam_hash_lookup_enabled:
        logger("qBit/MAM sync: disabled by MAM_HASH_LOOKUP_ENABLED=false")
        status = get_qbit_mam_sync_status()
        return {"enabled": False, **status, "processed": 0, "matched": 0, "no_match": 0, "errors": 0}

    qbit_client = qbit_client or QbitClient()
    mam_client = mam_client or MamClient()
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    torrents = await qbit_client.get_torrents()
    qbit_by_hash: dict[str, dict[str, Any]] = {}
    for torrent in torrents:
        qbit_hash = normalize_info_hash(torrent.get("hash"))
        if qbit_hash:
            qbit_by_hash[qbit_hash] = torrent

    pending: list[tuple[str, dict[str, Any]]] = []
    cached_count = 0
    for qbit_hash, torrent in qbit_by_hash.items():
        row = get_qbit_mam_cache_by_hash(qbit_hash)
        if row is not None:
            mark_qbit_mam_seen(qbit_hash, torrent.get("name"), torrent.get("category"), now_iso)
        if _is_due(row, now):
            pending.append((qbit_hash, torrent))
        else:
            cached_count += 1

    mark_qbit_mam_inventory_seen(now_iso)

    max_per_run = settings.mam_hash_lookup_max_per_run
    run_pending = pending[:max_per_run] if max_per_run else pending
    delay = settings.mam_hash_lookup_delay_seconds
    estimated_seconds = len(run_pending) * delay
    max_text = str(max_per_run) if max_per_run else "no limit"
    run_scope = "full initial sync may require multiple runs" if max_per_run and len(pending) > len(run_pending) else "all pending lookups are scheduled for this run"
    logger(
        f"qBit/MAM sync: {len(qbit_by_hash)} qBittorrent torrents found, {cached_count} cached, "
        f"{len(pending)} pending MAM hash lookups. Using {delay:g}s delay and max {max_text} lookups per run. "
        f"This run may take at least {format_duration(estimated_seconds)}; {run_scope}."
    )
    if not max_per_run and pending:
        logger(f"At {delay:g}s per lookup, {len(pending)} lookups may take about {format_duration(len(pending) * delay)}.")

    matched = 0
    no_match = 0
    errors = 0
    processed = 0
    for idx, (qbit_hash, torrent) in enumerate(run_pending):
        lookup_time = datetime.now(UTC).isoformat()
        try:
            row = await mam_client.lookup_by_hash(qbit_hash)
            if row is None:
                no_match += 1
                upsert_qbit_mam_cache(
                    qbit_hash=qbit_hash,
                    lookup_status="no_match",
                    last_seen_in_qbit=now_iso,
                    looked_up_at=lookup_time,
                    qbit_name=torrent.get("name"),
                    qbit_category=torrent.get("category"),
                )
            else:
                matched += 1
                upsert_qbit_mam_cache(
                    qbit_hash=qbit_hash,
                    lookup_status="matched",
                    last_seen_in_qbit=now_iso,
                    looked_up_at=lookup_time,
                    mam_id=int(row["id"]),
                    mam_title=row.get("title"),
                    media_type=_media_type_from_row(row),
                    qbit_name=torrent.get("name"),
                    qbit_category=torrent.get("category"),
                )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            upsert_qbit_mam_cache(
                qbit_hash=qbit_hash,
                lookup_status="error",
                last_seen_in_qbit=now_iso,
                looked_up_at=lookup_time,
                qbit_name=torrent.get("name"),
                qbit_category=torrent.get("category"),
                last_error=str(exc),
            )
        processed += 1
        remaining = len(run_pending) - processed
        if processed % 10 == 0 or processed == len(run_pending):
            logger(
                f"qBit/MAM sync progress: processed={processed}, matched={matched}, "
                f"no_match={no_match}, errors={errors}, remaining={remaining}"
            )
        if idx < len(run_pending) - 1 and delay > 0:
            await sleep(delay)

    logger(
        f"qBit/MAM sync complete: processed={processed}, matched={matched}, "
        f"no_match={no_match}, errors={errors}, pending_remaining={max(len(pending) - processed, 0)}"
    )
    status = get_qbit_mam_sync_status()
    return {
        "enabled": True,
        **status,
        "qbit_torrents_found": len(qbit_by_hash),
        "cached": cached_count,
        "pending": len(pending),
        "processed": processed,
        "matched": matched,
        "no_match": no_match,
        "errors": errors,
    }
