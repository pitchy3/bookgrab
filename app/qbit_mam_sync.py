from __future__ import annotations

import asyncio
import importlib.util
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if importlib.util.find_spec("croniter") is not None:
    from croniter import croniter as _croniter
else:
    _croniter = None

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
_CRON_FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
qbit_mam_sync_lock = asyncio.Lock()


class QbitMamSyncAlreadyRunning(RuntimeError):
    pass


def _parse_cron_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        if not part:
            raise ValueError("empty cron field part")
        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise ValueError("cron step must be positive")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)
        if start < minimum or end > maximum or start > end:
            raise ValueError("cron field out of range")
        values.update(range(start, end + 1, step))
    return values


def _is_valid_cron_expression(expression: str) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        return False
    if _croniter is not None:
        return bool(_croniter.is_valid(expression))
    try:
        for field, (minimum, maximum) in zip(fields, _CRON_FIELD_RANGES, strict=True):
            _parse_cron_field(field, minimum, maximum)
    except (TypeError, ValueError):
        return False
    return True


def _next_cron_datetime(expression: str, base: datetime) -> datetime:
    if _croniter is not None:
        return _croniter(expression, base).get_next(datetime)
    minute_values, hour_values, day_values, month_values, weekday_values = [
        _parse_cron_field(field, minimum, maximum)
        for field, (minimum, maximum) in zip(expression.split(), _CRON_FIELD_RANGES, strict=True)
    ]
    candidate = (base + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limit = candidate + timedelta(days=366 * 5)
    while candidate <= limit:
        cron_weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in minute_values
            and candidate.hour in hour_values
            and candidate.day in day_values
            and candidate.month in month_values
            and cron_weekday in weekday_values
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise RuntimeError("Could not calculate next MAM_HASH_LOOKUP_CRON occurrence within 5 years")


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


def validate_qbit_mam_sync_cron_config() -> tuple[str, ZoneInfo]:
    expression = settings.mam_hash_lookup_cron.strip()
    timezone_name = settings.mam_hash_lookup_cron_timezone.strip()
    if not expression:
        raise RuntimeError("MAM_HASH_LOOKUP_CRON_ENABLED=true requires MAM_HASH_LOOKUP_CRON to be a non-empty 5-field cron expression")
    if not _is_valid_cron_expression(expression):
        raise RuntimeError("MAM_HASH_LOOKUP_CRON must be a valid 5-field cron expression, for example '0 3 * * *'")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"MAM_HASH_LOOKUP_CRON_TIMEZONE must be a valid IANA timezone, got '{timezone_name}'") from exc
    return expression, timezone


async def run_qbit_mam_sync_with_lock(
    qbit_client: QbitClient | None = None,
    mam_client: MamClient | None = None,
    *,
    sync_func: Callable[..., Awaitable[dict[str, Any]]] = sync_qbit_mam_hashes,
    skip_if_running: bool = False,
    logger: Callable[[str], Any] = print,
) -> dict[str, Any] | None:
    if qbit_mam_sync_lock.locked():
        if skip_if_running:
            logger("qBit/MAM scheduled sync skipped: another qBit/MAM sync is already running")
            return None
        raise QbitMamSyncAlreadyRunning("qBit/MAM sync is already running")
    async with qbit_mam_sync_lock:
        return await sync_func(qbit_client=qbit_client, mam_client=mam_client)


async def _run_scheduled_qbit_mam_sync_once(
    qbit_client: QbitClient | None = None,
    mam_client: MamClient | None = None,
    *,
    sync_func: Callable[..., Awaitable[dict[str, Any]]] = sync_qbit_mam_hashes,
    logger: Callable[[str], Any] = print,
) -> dict[str, Any] | None:
    try:
        logger("qBit/MAM scheduled sync starting")
        result = await run_qbit_mam_sync_with_lock(
            qbit_client=qbit_client,
            mam_client=mam_client,
            sync_func=sync_func,
            skip_if_running=True,
            logger=logger,
        )
        if result is not None:
            logger("qBit/MAM scheduled sync finished")
        return result
    except Exception as exc:  # noqa: BLE001
        logger(f"qBit/MAM scheduled sync failed: {exc}")
        return None


async def qbit_mam_sync_scheduler_loop(
    qbit_client: QbitClient | None = None,
    mam_client: MamClient | None = None,
    *,
    cron_expression: str | None = None,
    timezone: ZoneInfo | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    now: Callable[[], datetime] | None = None,
    sync_func: Callable[..., Awaitable[dict[str, Any]]] = sync_qbit_mam_hashes,
    logger: Callable[[str], Any] = print,
) -> None:
    expression = cron_expression or settings.mam_hash_lookup_cron.strip()
    tz = timezone or ZoneInfo(settings.mam_hash_lookup_cron_timezone.strip())
    current_time = now or (lambda: datetime.now(tz))

    while True:
        base = current_time()
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        else:
            base = base.astimezone(tz)
        next_run = _next_cron_datetime(expression, base)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=tz)
        delay_seconds = max((next_run - base).total_seconds(), 0.0)
        logger(f"qBit/MAM scheduled sync next run at {next_run.isoformat()}")
        await sleep(delay_seconds)
        await _run_scheduled_qbit_mam_sync_once(
            qbit_client=qbit_client,
            mam_client=mam_client,
            sync_func=sync_func,
            logger=logger,
        )
