from app import db


def test_db_helpers(monkeypatch, tmp_path):
    db_file = tmp_path / "app.db"
    monkeypatch.setattr(db.settings, "database_path", str(db_file))
    db.init_db()
    d_id = db.record_download(mam_id="1", title="T", author="Author", narrator="Narrator", series="Series", media_type="audiobook", import_status="queued")
    db.record_download(mam_id="2", title="T2", media_type="audiobook", import_status="failed")
    p_id = db.record_download(mam_id="3", title="T3", media_type="audiobook", import_status="partial")
    rows = db.get_pending_imports()
    assert [r["id"] for r in rows] == [d_id, p_id]
    db.mark_download_checked(d_id)
    db.update_download_import_state(d_id, "imported")
    db.record_imported_file(d_id, "/a", "/b", 1, "imported")
    db.record_imported_file(d_id, "/a", "/b", 1, "imported")
    s = db.get_import_status()
    assert "recent_downloads" in s
    assert s["counts"]["imported"] >= 1
    stored = next(row for row in s["recent_downloads"] if row["id"] == d_id)
    assert stored["author"] == "Author"
    assert stored["narrator"] == "Narrator"
    assert stored["series"] == "Series"
    assert len([f for f in s["recent_files"] if f["source_path"] == "/a"]) == 1


def test_init_db_migrates_existing_downloads_without_metadata_columns(monkeypatch, tmp_path):
    import sqlite3

    db_file = tmp_path / "app.db"
    monkeypatch.setattr(db.settings, "database_path", str(db_file))
    with sqlite3.connect(db_file) as conn:
        conn.execute("""CREATE TABLE downloads (
          id INTEGER PRIMARY KEY,mam_id TEXT,title TEXT,media_type TEXT NOT NULL,qbit_category TEXT,qbit_hash TEXT,qbit_name TEXT,save_path TEXT,content_path TEXT,
          added_at TEXT NOT NULL,completed_at TEXT,import_status TEXT NOT NULL DEFAULT 'queued',import_attempts INTEGER NOT NULL DEFAULT 0,
          imported_at TEXT,last_checked_at TEXT,last_error TEXT)""")
        conn.commit()

    db.init_db()

    with db.get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(downloads)").fetchall()}
    assert {"author", "narrator", "series"}.issubset(columns)
