import asyncio

from app import main
from app.db import get_conn, get_qbit_mam_matches_by_mam_ids, init_db, record_download, upsert_qbit_mam_cache
from app.qbit_mam_sync import MAM_HASH_LOOKUP_DELAY_SECONDS, sync_qbit_mam_hashes

HASH1 = "a" * 40
HASH2 = "b" * 40
HASH3 = "c" * 40


class FakeQbit:
    def __init__(self, hashes, trackers=None, categories=None, top_trackers=None, fail_trackers=None):
        self.hashes = hashes
        self.trackers = trackers or {h: ["https://www.myanonamouse.net/announce"] for h in hashes}
        self.categories = categories or {}
        self.top_trackers = top_trackers or {}
        self.fail_trackers = set(fail_trackers or [])

    async def get_torrents(self):
        return [
            {
                "hash": h,
                "name": f"Torrent {h[0]}",
                "category": self.categories.get(h, "audiobooks"),
                "tracker": self.top_trackers.get(h),
            }
            for h in self.hashes
        ]

    async def get_torrent_trackers(self, info_hash):
        if info_hash in self.fail_trackers:
            raise RuntimeError("tracker endpoint failed")
        return [{"url": tracker} for tracker in self.trackers.get(info_hash, [])]


class FakeMam:
    def __init__(self, rows):
        self.rows = rows
        self.lookups = []

    async def lookup_by_hash(self, info_hash):
        self.lookups.append(info_hash)
        value = self.rows.get(info_hash)
        if isinstance(value, Exception):
            raise value
        return value


def _setup_db(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "database_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(main.settings, "mam_hash_lookup_scope", "mam_only")
    monkeypatch.setattr(main.settings, "mam_tracker_hosts", ["myanonamouse.net", "www.myanonamouse.net"])
    monkeypatch.setattr(main.settings, "mam_hash_lookup_include_categories", ["audiobooks", "ebooks"])
    init_db()


def test_qbit_sync_stores_matched_mapping(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 100)
    mam = FakeMam({HASH1: {"id": 110685, "title": "The First Law Trilogy", "catname": "Audiobooks"}})

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1]), mam, logger=lambda _msg: None))

    assert result["matched"] == 1
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM qbit_mam_cache WHERE qbit_hash=?", (HASH1,)).fetchone()
    assert row["mam_id"] == 110685
    assert row["lookup_status"] == "matched"
    assert row["qbit_name"] == "Torrent a"


def test_qbit_sync_caches_no_match(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    mam = FakeMam({HASH1: None})

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1]), mam, logger=lambda _msg: None))

    assert result["no_match"] == 1
    with get_conn() as conn:
        row = conn.execute("SELECT lookup_status FROM qbit_mam_cache WHERE qbit_hash=?", (HASH1,)).fetchone()
    assert row["lookup_status"] == "no_match"


def test_qbit_sync_respects_max_per_run(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 2)
    mam = FakeMam({HASH1: None, HASH2: None, HASH3: None})

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1, HASH2, HASH3]), mam, sleep=lambda _s: asyncio.sleep(0), logger=lambda _msg: None))

    assert result["processed"] == 2
    assert mam.lookups == [HASH1, HASH2]


def test_qbit_sync_waits_between_lookups(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 100)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    mam = FakeMam({HASH1: None, HASH2: None})

    asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1, HASH2]), mam, sleep=fake_sleep, logger=lambda _msg: None))

    assert sleeps == [MAM_HASH_LOOKUP_DELAY_SECONDS]


def test_qbit_sync_logs_initial_estimate(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 2)
    logs = []
    mam = FakeMam({HASH1: None, HASH2: None, HASH3: None})

    asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1, HASH2, HASH3]), mam, sleep=lambda _s: asyncio.sleep(0), logger=logs.append))

    first = logs[0]
    assert "3 qBittorrent torrents found" in first
    assert "3 pending MAM hash lookups" in first
    assert "Using fixed 10s delay and max 2 lookups per run" in first
    assert "at least 20s" in first


def test_mam_only_includes_torrent_with_mam_tracker(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    mam = FakeMam({HASH1: None})

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1]), mam, logger=lambda _msg: None))

    assert result["candidates"] == 1
    assert result["candidate_selection"]["selected_by_tracker"] == 1
    assert mam.lookups == [HASH1]


def test_mam_only_excludes_non_mam_tracker_and_skips_mam_lookup(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    mam = FakeMam({HASH1: None})
    qbit = FakeQbit([HASH1], trackers={HASH1: ["https://example.org/announce"]})

    result = asyncio.run(sync_qbit_mam_hashes(qbit, mam, logger=lambda _msg: None))

    assert result["candidates"] == 0
    assert result["filtered_out"] == 1
    assert mam.lookups == []


def test_category_scope_includes_configured_category_plus_mam_tracker(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_scope", "category")
    monkeypatch.setattr(main.settings, "mam_hash_lookup_include_categories", ["audiobooks"])
    mam = FakeMam({HASH1: None, HASH2: None})
    qbit = FakeQbit(
        [HASH1, HASH2, HASH3],
        trackers={
            HASH1: ["https://example.org/announce"],
            HASH2: ["https://www.myanonamouse.net/announce"],
            HASH3: ["https://example.org/announce"],
        },
        categories={HASH1: "audiobooks", HASH2: "other", HASH3: "other"},
    )

    result = asyncio.run(sync_qbit_mam_hashes(qbit, mam, sleep=lambda _s: asyncio.sleep(0), logger=lambda _msg: None))

    assert result["candidates"] == 2
    assert result["candidate_selection"]["selected_by_category"] == 1
    assert result["candidate_selection"]["selected_by_tracker"] == 1
    assert mam.lookups == [HASH1, HASH2]


def test_bookgrab_scope_includes_bookgrab_hash_plus_mam_tracker(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_scope", "bookgrab")
    record_download(mam_id="1", title="Book", media_type="audiobook", qbit_hash=HASH1, import_status="queued")
    mam = FakeMam({HASH1: None, HASH2: None})
    qbit = FakeQbit(
        [HASH1, HASH2, HASH3],
        trackers={
            HASH1: ["https://example.org/announce"],
            HASH2: ["https://www.myanonamouse.net/announce"],
            HASH3: ["https://example.org/announce"],
        },
    )

    result = asyncio.run(sync_qbit_mam_hashes(qbit, mam, sleep=lambda _s: asyncio.sleep(0), logger=lambda _msg: None))

    assert result["candidates"] == 2
    assert result["candidate_selection"]["selected_by_bookgrab"] == 1
    assert result["candidate_selection"]["selected_by_tracker"] == 1
    assert mam.lookups == [HASH1, HASH2]


def test_all_scope_includes_every_torrent(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_scope", "all")
    mam = FakeMam({HASH1: None, HASH2: None, HASH3: None})
    qbit = FakeQbit([HASH1, HASH2, HASH3], trackers={h: ["https://example.org/announce"] for h in [HASH1, HASH2, HASH3]})

    result = asyncio.run(sync_qbit_mam_hashes(qbit, mam, sleep=lambda _s: asyncio.sleep(0), logger=lambda _msg: None))

    assert result["candidates"] == 3
    assert result["candidate_selection"]["selected_by_all"] == 3
    assert mam.lookups == [HASH1, HASH2, HASH3]


def test_tracker_lookup_failure_does_not_crash_sync(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    logs = []
    mam = FakeMam({HASH2: None})
    qbit = FakeQbit(
        [HASH1, HASH2],
        trackers={HASH2: ["https://www.myanonamouse.net/announce"]},
        fail_trackers={HASH1},
    )

    result = asyncio.run(sync_qbit_mam_hashes(qbit, mam, logger=logs.append))

    assert result["candidates"] == 1
    assert result["filtered_out"] == 1
    assert mam.lookups == [HASH2]
    assert any("failed to fetch tracker list" in message for message in logs)


def test_api_search_marks_in_qbit_from_cache_when_hash_lookup_enabled(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    upsert_qbit_mam_cache(
        qbit_hash=HASH1,
        lookup_status="matched",
        last_seen_in_qbit="2026-06-03T00:00:00+00:00",
        looked_up_at="2026-06-03T00:00:00+00:00",
        mam_id=110685,
        mam_title="The First Law Trilogy",
        qbit_name="Loaded Copy",
    )

    async def fake_search(**_kwargs):
        return [{"id": 110685, "title": "The First Law Trilogy", "_torrent_id": "110685"}]

    async def forbidden_lookup(_hash):
        raise AssertionError("search must not call MAM hash lookup")

    monkeypatch.setattr(main.mam_client, "search", fake_search)
    monkeypatch.setattr(main.mam_client, "lookup_by_hash", forbidden_lookup)
    from fastapi.testclient import TestClient

    response = TestClient(main.app).post("/api/search", json={"query": "law", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"})

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["in_qbit"] is True
    assert row["qbit_name"] == "Loaded Copy"
    assert "_torrent_hash" not in row



def test_api_search_skips_qbit_cache_when_hash_lookup_disabled(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", False)

    async def fake_search(**_kwargs):
        return [{"id": 110685, "title": "The First Law Trilogy", "_torrent_id": "110685", "_torrent_hash": HASH1}]

    def forbidden_cache_lookup(_mam_ids):
        raise AssertionError("should not be called")

    monkeypatch.setattr(main.mam_client, "search", fake_search)
    monkeypatch.setattr(main, "get_qbit_mam_matches_by_mam_ids", forbidden_cache_lookup)
    from fastapi.testclient import TestClient

    response = TestClient(main.app).post(
        "/api/search",
        json={"query": "law", "media_type": "audiobook", "search_in": ["title"], "sort": "seedersDesc"},
    )

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["in_qbit"] is False
    assert row["qbit_name"] is None
    assert "_torrent_id" not in row
    assert "_torrent_hash" not in row


def test_api_qbit_mam_sync_run_rejects_concurrent_request(monkeypatch):
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_sync(**_kwargs):
        started.set()
        await release.wait()
        return {"ok": True}

    monkeypatch.setattr(main, "sync_qbit_mam_hashes", slow_sync)

    async def run_requests():
        first = asyncio.create_task(main.api_qbit_mam_sync_run(object()))
        await started.wait()
        try:
            await main.api_qbit_mam_sync_run(object())
        except Exception as exc:  # noqa: BLE001
            second = exc
        else:
            second = None
        release.set()
        first_result = await first
        return first_result, second

    first_result, second = asyncio.run(run_requests())

    assert first_result == {"ok": True}
    assert second is not None
    assert second.status_code == 409
    assert second.detail == "qBit/MAM sync is already running"


def test_api_qbit_mam_sync_status_omits_pending_lookup_count(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    from fastapi.testclient import TestClient

    response = TestClient(main.app).get("/api/qbit-mam-sync/status")

    assert response.status_code == 200
    assert "pending_lookup_count" not in response.json()

def test_qbit_sync_empty_inventory_invalidates_previous_matches(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    upsert_qbit_mam_cache(
        qbit_hash=HASH1,
        lookup_status="matched",
        last_seen_in_qbit="2026-06-03T00:00:00+00:00",
        looked_up_at="2026-06-03T00:00:00+00:00",
        mam_id=110685,
        mam_title="The First Law Trilogy",
        qbit_name="Loaded Copy",
    )
    assert 110685 in get_qbit_mam_matches_by_mam_ids([110685])

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([]), FakeMam({}), logger=lambda _msg: None))

    assert result["qbit_torrents_found"] == 0
    assert result["processed"] == 0
    assert get_qbit_mam_matches_by_mam_ids([110685]) == {}

def test_api_add_blocks_duplicate_by_computed_hash_even_with_stale_cache(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    monkeypatch.setattr(main, "add_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "record_download", lambda *args, **kwargs: None)
    torrent_bytes = b"d8:announce3:xyz4:infod4:name4:Book6:lengthi12345eee"

    async def fake_download_torrent(_torrent_id):
        return torrent_bytes

    async def fake_get_torrent(info_hash):
        return {"hash": info_hash, "name": "Already There"}

    async def forbidden_add(*_args, **_kwargs):
        raise AssertionError("duplicate should be blocked before add")

    monkeypatch.setattr(main.mam_client, "download_torrent", fake_download_torrent)
    monkeypatch.setattr(main.qbit_client, "get_torrent", fake_get_torrent)
    monkeypatch.setattr(main.qbit_client, "add_torrent", forbidden_add)
    main._search_cache.clear()
    main._search_cache_updated_at.clear()
    main._search_cache["audiobook:test:seedersDesc"] = {1: {"id": 1, "title": "Book", "_torrent_id": "1"}}
    main._search_cache_updated_at["audiobook:test:seedersDesc"] = 1_800_000_000

    response = TestClient(main.app).post("/api/add", json={"id": 1, "media_type": "audiobook"})

    assert response.status_code == 409
    assert "Already There" in response.json()["detail"]


def test_fallback_cron_next_datetime_uses_or_for_restricted_dom_and_dow(monkeypatch):
    from datetime import UTC, datetime

    import app.qbit_mam_sync as qbit_mam_sync

    monkeypatch.setattr(qbit_mam_sync, "_croniter", None)

    next_run = qbit_mam_sync._next_cron_datetime("0 3 1 * 0", datetime(2026, 6, 2, tzinfo=UTC))

    assert next_run == datetime(2026, 6, 7, 3, tzinfo=UTC)

def test_fallback_cron_next_datetime_still_requires_restricted_dom_when_dow_is_wildcard(monkeypatch):
    from datetime import UTC, datetime

    import app.qbit_mam_sync as qbit_mam_sync

    monkeypatch.setattr(qbit_mam_sync, "_croniter", None)

    next_run = qbit_mam_sync._next_cron_datetime("0 3 1 * *", datetime(2026, 6, 2, tzinfo=UTC))

    assert next_run == datetime(2026, 7, 1, 3, tzinfo=UTC)

def test_qbit_mam_cron_disabled_by_default(monkeypatch):
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", False)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_cron_enabled", False)
    monkeypatch.setattr(main, "_validate_auth_config", lambda: None)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main.settings, "import_min_completion_ratio_legacy_present", False)
    monkeypatch.setattr(main.settings, "import_enabled", False)
    created = []

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)

    asyncio.run(main.startup())

    assert created == []
    assert main._qbit_mam_sync_task is None


def test_invalid_qbit_mam_cron_expression_raises_clear_error(monkeypatch):
    from app.qbit_mam_sync import validate_qbit_mam_sync_cron_config
    import pytest

    monkeypatch.setattr(main.settings, "mam_hash_lookup_cron", "bad cron")
    monkeypatch.setattr(main.settings, "mam_hash_lookup_cron_timezone", "UTC")

    with pytest.raises(RuntimeError, match="MAM_HASH_LOOKUP_CRON.*5-field"):
        validate_qbit_mam_sync_cron_config()


def test_invalid_qbit_mam_cron_timezone_raises_clear_error(monkeypatch):
    from app.qbit_mam_sync import validate_qbit_mam_sync_cron_config
    import pytest

    monkeypatch.setattr(main.settings, "mam_hash_lookup_cron", "0 3 * * *")
    monkeypatch.setattr(main.settings, "mam_hash_lookup_cron_timezone", "Not/AZone")

    with pytest.raises(RuntimeError, match="MAM_HASH_LOOKUP_CRON_TIMEZONE"):
        validate_qbit_mam_sync_cron_config()


def test_scheduled_sync_skips_when_lock_is_held(monkeypatch):
    from app.qbit_mam_sync import _run_scheduled_qbit_mam_sync_once, qbit_mam_sync_lock

    calls = []
    logs = []

    async def forbidden_sync(**_kwargs):
        calls.append("called")
        return {"ok": True}

    async def scenario():
        async with qbit_mam_sync_lock:
            result = await _run_scheduled_qbit_mam_sync_once(sync_func=forbidden_sync, logger=logs.append)
        return result

    result = asyncio.run(scenario())

    assert result is None
    assert calls == []
    assert any("scheduled sync skipped" in message for message in logs)


def test_scheduled_and_manual_paths_share_lock(monkeypatch):
    from app.qbit_mam_sync import _run_scheduled_qbit_mam_sync_once

    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_scheduled_sync(**_kwargs):
        started.set()
        await release.wait()
        return {"scheduled": True}

    async def manual_sync(**_kwargs):
        return {"manual": True}

    monkeypatch.setattr(main, "sync_qbit_mam_hashes", manual_sync)

    async def scenario():
        scheduled = asyncio.create_task(_run_scheduled_qbit_mam_sync_once(sync_func=slow_scheduled_sync, logger=lambda _msg: None))
        await started.wait()
        try:
            await main.api_qbit_mam_sync_run(object())
        except Exception as exc:  # noqa: BLE001
            manual_error = exc
        else:
            manual_error = None
        release.set()
        scheduled_result = await scheduled
        return scheduled_result, manual_error

    scheduled_result, manual_error = asyncio.run(scenario())

    assert scheduled_result == {"scheduled": True}
    assert manual_error is not None
    assert manual_error.status_code == 409


def test_skipped_scheduled_runs_are_not_queued(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.qbit_mam_sync import qbit_mam_sync_scheduler_loop, qbit_mam_sync_lock

    tz = ZoneInfo("UTC")
    times = [
        datetime(2026, 6, 4, 0, 0, tzinfo=tz),
        datetime(2026, 6, 4, 0, 1, tzinfo=tz),
    ]
    sleeps = []
    sync_calls = []
    logs = []

    def fake_now():
        return times[min(len(sleeps), len(times) - 1)]

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            return
        raise asyncio.CancelledError

    async def fake_sync(**_kwargs):
        sync_calls.append("called")
        return {"ok": True}

    async def scenario():
        async with qbit_mam_sync_lock:
            try:
                await qbit_mam_sync_scheduler_loop(
                    cron_expression="* * * * *",
                    timezone=tz,
                    sleep=fake_sleep,
                    now=fake_now,
                    sync_func=fake_sync,
                    logger=logs.append,
                )
            except asyncio.CancelledError:
                pass

    asyncio.run(scenario())

    assert sleeps == [60.0, 60.0]
    assert sync_calls == []
    assert sum("scheduled sync skipped" in message for message in logs) == 1
