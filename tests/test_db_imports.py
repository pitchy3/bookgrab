from app import db


def test_db_helpers(monkeypatch, tmp_path):
    db_file = tmp_path / "app.db"
    monkeypatch.setattr(db.settings, "database_path", str(db_file))
    db.init_db()
    d_id = db.record_download(mam_id="1", title="T", media_type="audiobook", import_status="queued")
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
    assert len([f for f in s["recent_files"] if f["source_path"] == "/a"]) == 1
