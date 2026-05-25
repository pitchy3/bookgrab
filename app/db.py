from __future__ import annotations

import os
import sqlite3
from datetime import datetime, UTC

from app.config import settings


def get_conn() -> sqlite3.Connection:
    os.makedirs(settings.config_dir, exist_ok=True)
    path = os.path.join(settings.config_dir, "app.db")
    conn = sqlite3.connect(path)
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
