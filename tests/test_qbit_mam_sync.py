import asyncio

from app import main
from app.db import get_conn, init_db, upsert_qbit_mam_cache
from app.qbit_mam_sync import sync_qbit_mam_hashes

HASH1 = "a" * 40
HASH2 = "b" * 40
HASH3 = "c" * 40


class FakeQbit:
    def __init__(self, hashes):
        self.hashes = hashes

    async def get_torrents(self):
        return [{"hash": h, "name": f"Torrent {h[0]}", "category": "audiobooks"} for h in self.hashes]


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
    init_db()


def test_qbit_sync_stores_matched_mapping(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_delay_seconds", 0)
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
    monkeypatch.setattr(main.settings, "mam_hash_lookup_delay_seconds", 0)
    mam = FakeMam({HASH1: None})

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1]), mam, logger=lambda _msg: None))

    assert result["no_match"] == 1
    with get_conn() as conn:
        row = conn.execute("SELECT lookup_status FROM qbit_mam_cache WHERE qbit_hash=?", (HASH1,)).fetchone()
    assert row["lookup_status"] == "no_match"


def test_qbit_sync_respects_max_per_run(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_delay_seconds", 0)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 2)
    mam = FakeMam({HASH1: None, HASH2: None, HASH3: None})

    result = asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1, HASH2, HASH3]), mam, logger=lambda _msg: None))

    assert result["processed"] == 2
    assert mam.lookups == [HASH1, HASH2]


def test_qbit_sync_waits_between_lookups(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_delay_seconds", 10)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 100)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    mam = FakeMam({HASH1: None, HASH2: None})

    asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1, HASH2]), mam, sleep=fake_sleep, logger=lambda _msg: None))

    assert sleeps == [10]


def test_qbit_sync_logs_initial_estimate(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_enabled", True)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_delay_seconds", 10)
    monkeypatch.setattr(main.settings, "mam_hash_lookup_max_per_run", 2)
    logs = []
    mam = FakeMam({HASH1: None, HASH2: None, HASH3: None})

    asyncio.run(sync_qbit_mam_hashes(FakeQbit([HASH1, HASH2, HASH3]), mam, sleep=lambda _s: asyncio.sleep(0), logger=logs.append))

    first = logs[0]
    assert "3 qBittorrent torrents found" in first
    assert "3 pending MAM hash lookups" in first
    assert "Using 10s delay and max 2 lookups per run" in first
    assert "at least 20s" in first


def test_api_search_marks_in_qbit_from_cache_without_hash_lookup(monkeypatch, tmp_path):
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "app_auth_enabled", False)
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
