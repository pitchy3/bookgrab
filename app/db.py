from __future__ import annotations

import os
import sqlite3
from datetime import datetime, UTC
from pathlib import Path

from app.config import settings


def get_db_path() -> Path:
    return Path(settings.database_path)


def ensure_db_path_ready() -> Path:
    db_path = get_db_path()
    db_dir = db_path.parent
    db_dir.mkdir(parents=True, exist_ok=True)

    if not os.access(db_dir, os.W_OK):
        raise RuntimeError(
            f"Database directory is not writable: {db_dir}. "
            "Check Docker volume permissions for /config."
        )
    if db_path.exists() and (not os.access(db_path, os.R_OK) or not os.access(db_path, os.W_OK)):
        raise RuntimeError(f"Database file exists but is not readable/writable: {db_path}")

    return db_path


def get_conn() -> sqlite3.Connection:
    db_path = ensure_db_path_ready()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS download_history (
              id INTEGER PRIMARY KEY,
              mam_id TEXT,
              title TEXT,
              media_type TEXT,
              qbit_category TEXT,
              added_at TEXT,
              status TEXT,
              error TEXT
            )
            """
        )
        conn.commit()


def add_history(mam_id: str, title: str, media_type: str, qbit_category: str, status: str, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO download_history (mam_id, title, media_type, qbit_category, added_at, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (mam_id, title, media_type, qbit_category, datetime.now(UTC).isoformat(), status, error),
        )
        conn.commit()
