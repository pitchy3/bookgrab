from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings


def get_db_path() -> Path:
    return Path(settings.database_path)


def ensure_db_path_ready() -> Path:
    db_path = get_db_path()
    db_dir = db_path.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(db_dir, os.W_OK):
        raise RuntimeError(f"Database directory is not writable: {db_dir}. Check Docker volume permissions for /config.")
    if db_path.exists() and (not os.access(db_path, os.R_OK) or not os.access(db_path, os.W_OK)):
        raise RuntimeError(f"Database file exists but is not readable/writable: {db_path}")
    return db_path


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(ensure_db_path_ready()))
    conn.row_factory = sqlite3.Row
    return conn


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS download_history (id INTEGER PRIMARY KEY,mam_id TEXT,title TEXT,media_type TEXT,qbit_category TEXT,added_at TEXT,status TEXT,error TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS downloads (
          id INTEGER PRIMARY KEY,mam_id TEXT,title TEXT,author TEXT,narrator TEXT,series TEXT,media_type TEXT NOT NULL,qbit_category TEXT,qbit_hash TEXT,qbit_name TEXT,save_path TEXT,content_path TEXT,
          added_at TEXT NOT NULL,completed_at TEXT,import_status TEXT NOT NULL DEFAULT 'queued',import_attempts INTEGER NOT NULL DEFAULT 0,
          imported_at TEXT,last_checked_at TEXT,last_error TEXT)""")
        add_column_if_missing(conn, "downloads", "author", "TEXT")
        add_column_if_missing(conn, "downloads", "narrator", "TEXT")
        add_column_if_missing(conn, "downloads", "series", "TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS imported_files (
          id INTEGER PRIMARY KEY,download_id INTEGER NOT NULL,source_path TEXT NOT NULL,destination_path TEXT NOT NULL,size_bytes INTEGER,
          imported_at TEXT NOT NULL,status TEXT NOT NULL,error TEXT,UNIQUE(download_id, source_path, destination_path),
          FOREIGN KEY(download_id) REFERENCES downloads(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS qbit_mam_cache (
          qbit_hash TEXT PRIMARY KEY,
          mam_id INTEGER,
          mam_title TEXT,
          media_type TEXT,
          qbit_name TEXT,
          qbit_category TEXT,
          lookup_status TEXT NOT NULL,
          last_seen_in_qbit TEXT NOT NULL,
          looked_up_at TEXT NOT NULL,
          last_error TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS qbit_mam_sync_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          qbit_inventory_seen_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qbit_mam_cache_mam_id ON qbit_mam_cache(mam_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qbit_mam_cache_status ON qbit_mam_cache(lookup_status)")
        conn.commit()


def add_history(mam_id: str, title: str, media_type: str, qbit_category: str, status: str, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO download_history (mam_id,title,media_type,qbit_category,added_at,status,error) VALUES (?,?,?,?,?,?,?)", (mam_id, title, media_type, qbit_category, datetime.now(UTC).isoformat(), status, error))
        conn.commit()


def record_download(**kwargs: Any) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO downloads (mam_id,title,author,narrator,series,media_type,qbit_category,qbit_hash,qbit_name,save_path,content_path,added_at,import_status,last_error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (kwargs.get("mam_id"), kwargs.get("title"), kwargs.get("author"), kwargs.get("narrator"), kwargs.get("series"), kwargs["media_type"], kwargs.get("qbit_category"), kwargs.get("qbit_hash"), kwargs.get("qbit_name"), kwargs.get("save_path"), kwargs.get("content_path"), datetime.now(UTC).isoformat(), kwargs.get("import_status", "queued"), kwargs.get("last_error")),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_pending_imports(limit: int = 50) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM downloads WHERE import_status IN ('queued','waiting','partial') ORDER BY id ASC LIMIT ?", (limit,))
        return cur.fetchall()


def get_download_by_hash(qbit_hash: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM downloads WHERE qbit_hash = ? ORDER BY id DESC LIMIT 1", (qbit_hash,))
        return cur.fetchone()


def get_bookgrab_qbit_hashes() -> set[str]:
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT qbit_hash FROM downloads WHERE qbit_hash IS NOT NULL AND qbit_hash != ''").fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return set()
        raise
    return {str(row["qbit_hash"]).strip().lower() for row in rows if row["qbit_hash"]}


def update_download_import_state(download_id: int, status: str, last_error: str | None = None, completed: bool = False) -> None:
    now = datetime.now(UTC).isoformat()
    with get_conn() as conn:
        conn.execute(
            """UPDATE downloads SET import_status=?, import_attempts=import_attempts+1, imported_at=?, completed_at=COALESCE(completed_at, ?), last_error=? WHERE id=?""",
            (status, now if status in {"imported", "skipped", "partial"} else None, now if completed else None, last_error, download_id),
        )
        conn.commit()


def mark_download_checked(download_id: int, status: str = "waiting", last_error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE downloads SET last_checked_at=?, import_status=?, last_error=? WHERE id=?", (datetime.now(UTC).isoformat(), status, last_error, download_id))
        conn.commit()


def update_download_qbit_info(download_id: int, qbit_hash: str | None = None, qbit_name: str | None = None, save_path: str | None = None, content_path: str | None = None, import_status: str | None = None, last_error: str | None = None) -> None:
    fields = []
    values: list[Any] = []
    if qbit_hash is not None:
        fields.append("qbit_hash=?")
        values.append(qbit_hash)
    if qbit_name is not None:
        fields.append("qbit_name=?")
        values.append(qbit_name)
    if save_path is not None:
        fields.append("save_path=?")
        values.append(save_path)
    if content_path is not None:
        fields.append("content_path=?")
        values.append(content_path)
    if import_status is not None:
        fields.append("import_status=?")
        values.append(import_status)
    fields.append("last_error=?")
    values.append(last_error)
    fields.append("last_checked_at=?")
    values.append(datetime.now(UTC).isoformat())
    values.append(download_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE downloads SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()


def record_imported_file(download_id: int, source_path: str, destination_path: str, size_bytes: int | None, status: str, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO imported_files (download_id,source_path,destination_path,size_bytes,imported_at,status,error)
            VALUES (?,?,?,?,?,?,?)""",
            (download_id, source_path, destination_path, size_bytes, datetime.now(UTC).isoformat(), status, error),
        )
        conn.commit()


def get_import_status(limit: int = 20) -> dict[str, Any]:
    with get_conn() as conn:
        counts_rows = conn.execute("SELECT import_status, COUNT(*) as c FROM downloads GROUP BY import_status").fetchall()
        counts = {row["import_status"]: row["c"] for row in counts_rows}
        recent = [dict(r) for r in conn.execute("SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        files = [dict(r) for r in conn.execute("SELECT * FROM imported_files ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        return {"counts": counts, "recent_downloads": recent, "recent_imported_files": files, "recent_files": files}


def upsert_qbit_mam_cache(
    qbit_hash: str,
    lookup_status: str,
    last_seen_in_qbit: str,
    looked_up_at: str,
    mam_id: int | None = None,
    mam_title: str | None = None,
    media_type: str | None = None,
    qbit_name: str | None = None,
    qbit_category: str | None = None,
    last_error: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO qbit_mam_cache (qbit_hash,mam_id,mam_title,media_type,qbit_name,qbit_category,lookup_status,last_seen_in_qbit,looked_up_at,last_error)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(qbit_hash) DO UPDATE SET
              mam_id=excluded.mam_id, mam_title=excluded.mam_title, media_type=excluded.media_type, qbit_name=excluded.qbit_name,
              qbit_category=excluded.qbit_category, lookup_status=excluded.lookup_status, last_seen_in_qbit=excluded.last_seen_in_qbit,
              looked_up_at=excluded.looked_up_at, last_error=excluded.last_error""",
            (qbit_hash, mam_id, mam_title, media_type, qbit_name, qbit_category, lookup_status, last_seen_in_qbit, looked_up_at, last_error),
        )
        conn.commit()


def mark_qbit_mam_seen(qbit_hash: str, qbit_name: str | None, qbit_category: str | None, last_seen_in_qbit: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE qbit_mam_cache SET qbit_name=?, qbit_category=?, last_seen_in_qbit=? WHERE qbit_hash=?",
            (qbit_name, qbit_category, last_seen_in_qbit, qbit_hash),
        )
        conn.commit()


def mark_qbit_mam_inventory_seen(qbit_inventory_seen_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO qbit_mam_sync_state (id,qbit_inventory_seen_at) VALUES (1,?)
            ON CONFLICT(id) DO UPDATE SET qbit_inventory_seen_at=excluded.qbit_inventory_seen_at""",
            (qbit_inventory_seen_at,),
        )
        conn.commit()


def get_qbit_mam_cache_by_hash(qbit_hash: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM qbit_mam_cache WHERE qbit_hash=?", (qbit_hash,)).fetchone()


def get_qbit_mam_matches_by_mam_ids(mam_ids: list[int]) -> dict[int, sqlite3.Row]:
    if not mam_ids:
        return {}
    placeholders = ",".join("?" for _ in mam_ids)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM qbit_mam_cache
                WHERE lookup_status='matched'
                  AND mam_id IN ({placeholders})
                  AND last_seen_in_qbit = COALESCE(
                    (SELECT qbit_inventory_seen_at FROM qbit_mam_sync_state WHERE id=1),
                    (SELECT MAX(last_seen_in_qbit) FROM qbit_mam_cache)
                  )""",
                mam_ids,
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {}
        raise
    return {int(row["mam_id"]): row for row in rows if row["mam_id"] is not None}


def get_qbit_mam_sync_status() -> dict[str, Any]:
    try:
        with get_conn() as conn:
            counts_rows = conn.execute("SELECT lookup_status, COUNT(*) as c FROM qbit_mam_cache GROUP BY lookup_status").fetchall()
            counts = {row["lookup_status"]: row["c"] for row in counts_rows}
            total = conn.execute("SELECT COUNT(*) AS c FROM qbit_mam_cache").fetchone()["c"]
            last_lookup = conn.execute("SELECT MAX(looked_up_at) AS ts FROM qbit_mam_cache").fetchone()["ts"]
            last_inventory = conn.execute("SELECT qbit_inventory_seen_at AS ts FROM qbit_mam_sync_state WHERE id=1").fetchone()
            last_sync = last_inventory["ts"] if last_inventory is not None else last_lookup
            last_errors = conn.execute("SELECT COUNT(*) AS c FROM qbit_mam_cache WHERE lookup_status='error'").fetchone()["c"]
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        counts = {}
        total = 0
        last_sync = None
        last_errors = 0
    return {"cached_mappings_count": total, "counts": counts, "last_sync_time": last_sync, "last_error_count": last_errors}
