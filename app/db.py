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
