from __future__ import annotations

import asyncio
import importlib.util
import re
from urllib.parse import urlparse
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if importlib.util.find_spec("croniter") is not None:
    from croniter import croniter as _croniter
else:
    _croniter = None

from app.config import settings
from app.db import (
    get_bookgrab_qbit_hashes,
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
_CRON_DAY_OF_MONTH_VALUES = set(range(1, 32))
_CRON_DAY_OF_WEEK_VALUES = set(range(0, 7))
MAM_HASH_LOOKUP_DELAY_SECONDS = 10
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


def _cron_day_matches(candidate: datetime, day_values: set[int], weekday_values: set[int]) -> bool:
    dom_is_unrestricted = day_values == _CRON_DAY_OF_MONTH_VALUES
    dow_is_unrestricted = weekday_values == _CRON_DAY_OF_WEEK_VALUES
    day_matches = candidate.day in day_values
    cron_weekday = (candidate.weekday() + 1) % 7
    weekday_matches = cron_weekday in weekday_values

    if dom_is_unrestricted and dow_is_unrestricted:
        return True
    if dom_is_unrestricted:
        return weekday_matches
    if dow_is_unrestricted:
        return day_matches
    return day_matches or weekday_matches


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
        if (
            candidate.minute in minute_values
            and candidate.hour in hour_values
            and candidate.month in month_values
            and _cron_day_matches(candidate, day_values, weekday_values)
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


def _hostname_from_tracker_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.hostname:
        return None
    return parsed.hostname.lower()


def _tracker_row_url(row: Any) -> Any:
    if isinstance(row, dict):
        return row.get("url")
    return row


def _tracker_url_matches_mam(value: Any, tracker_hosts: set[str]) -> bool:
    hostname = _hostname_from_tracker_url(value)
    return hostname in tracker_hosts if hostname else False


async def _torrent_has_mam_tracker(
    qbit_hash: str,
    torrent: dict[str, Any],
    qbit_client: QbitClient,
    tracker_hosts: set[str],
    logger: Callable[[str], Any],
) -> bool:
    if _tracker_url_matches_mam(torrent.get("tracker"), tracker_hosts):
        return True
    try:
        tracker_rows = await qbit_client.get_torrent_trackers(qbit_hash)
    except Exception as exc:  # noqa: BLE001
        logger(f"qBit/MAM sync warning: failed to fetch tracker list for {qbit_hash}: {exc}")
        return False
    return any(_tracker_url_matches_mam(_tracker_row_url(row), tracker_hosts) for row in tracker_rows)


async def select_mam_hash_lookup_candidates(
    qbit_by_hash: dict[str, dict[str, Any]],
    qbit_client: QbitClient,
    logger: Callable[[str], Any] = print,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    scope = settings.mam_hash_lookup_scope
    tracker_hosts = {host.strip().lower() for host in settings.mam_tracker_hosts if host.strip()}
    include_categories = {category.strip().lower() for category in settings.mam_hash_lookup_include_categories if category.strip()}
    bookgrab_hashes = get_bookgrab_qbit_hashes() if scope == "bookgrab" else set()

    candidates: dict[str, dict[str, Any]] = {}
    reason_counts = {"tracker": 0, "category": 0, "bookgrab": 0, "all": 0}

    if scope == "all":
        candidates = dict(qbit_by_hash)
        reason_counts["all"] = len(candidates)
    else:
        for qbit_hash, torrent in qbit_by_hash.items():
            reasons: set[str] = set()
            if tracker_hosts and await _torrent_has_mam_tracker(qbit_hash, torrent, qbit_client, tracker_hosts, logger):
                reasons.add("tracker")
            if scope == "category" and str(torrent.get("category") or "").strip().lower() in include_categories:
                reasons.add("category")
            if scope == "bookgrab" and qbit_hash in bookgrab_hashes:
                reasons.add("bookgrab")
            if reasons:
                candidates[qbit_hash] = torrent
                for reason in reasons:
                    reason_counts[reason] += 1

    summary = {
        "scope": scope,
        "total_discovered": len(qbit_by_hash),
        "selected_candidates": len(candidates),
        "filtered_out": max(len(qbit_by_hash) - len(candidates), 0),
        "selected_by_tracker": reason_counts["tracker"],
        "selected_by_category": reason_counts["category"],
        "selected_by_bookgrab": reason_counts["bookgrab"],
        "selected_by_all": reason_counts["all"],
    }
    return candidates, summary


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

    candidates, selection_summary = await select_mam_hash_lookup_candidates(qbit_by_hash, qbit_client, logger)

    for qbit_hash, torrent in qbit_by_hash.items():
        row = get_qbit_mam_cache_by_hash(qbit_hash)
        if row is not None:
            mark_qbit_mam_seen(qbit_hash, torrent.get("name"), torrent.get("category"), now_iso)

    pending: list[tuple[str, dict[str, Any]]] = []
    cached_count = 0
    for qbit_hash, torrent in candidates.items():
        row = get_qbit_mam_cache_by_hash(qbit_hash)
        if _is_due(row, now):
            pending.append((qbit_hash, torrent))
        else:
            cached_count += 1

    mark_qbit_mam_inventory_seen(now_iso)

    max_per_run = settings.mam_hash_lookup_max_per_run
    run_pending = pending[:max_per_run] if max_per_run else pending
    delay = MAM_HASH_LOOKUP_DELAY_SECONDS
    estimated_seconds = len(run_pending) * delay
    max_text = str(max_per_run) if max_per_run else "no limit"
    run_scope = "full initial sync may require multiple runs" if max_per_run and len(pending) > len(run_pending) else "all pending lookups are scheduled for this run"
    logger(
        f"qBit/MAM sync: {len(qbit_by_hash)} qBittorrent torrents found, scope={selection_summary['scope']}, "
        f"{selection_summary['selected_candidates']} candidates selected, {selection_summary['filtered_out']} filtered out "
        f"(tracker={selection_summary['selected_by_tracker']}, category={selection_summary['selected_by_category']}, "
        f"bookgrab={selection_summary['selected_by_bookgrab']}, all={selection_summary['selected_by_all']}), "
        f"{cached_count} cached, {len(pending)} pending MAM hash lookups. "
        f"Using fixed {delay:g}s delay and max {max_text} lookups per run. "
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
        "candidate_selection": selection_summary,
        "candidates": selection_summary["selected_candidates"],
        "filtered_out": selection_summary["filtered_out"],
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
