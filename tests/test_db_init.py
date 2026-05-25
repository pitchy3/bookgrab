from pathlib import Path

import pytest

from app import db


def test_ensure_db_path_ready_creates_parent_directory(monkeypatch, tmp_path):
    db_file = tmp_path / "nested" / "bookgrab.db"
    monkeypatch.setattr(db.settings, "database_path", str(db_file))

    resolved = db.ensure_db_path_ready()

    assert resolved == db_file
    assert db_file.parent.exists()


def test_init_db_creates_sqlite_file_in_writable_directory(monkeypatch, tmp_path):
    db_file = tmp_path / "app.db"
    monkeypatch.setattr(db.settings, "database_path", str(db_file))

    db.init_db()

    assert db_file.exists()


def test_ensure_db_path_ready_fails_for_non_writable_dir(monkeypatch, tmp_path):
    db_file = tmp_path / "app.db"
    monkeypatch.setattr(db.settings, "database_path", str(db_file))
    monkeypatch.setattr(db.os, "access", lambda *_args, **_kwargs: False)

    with pytest.raises(RuntimeError, match="Database directory is not writable"):
        db.ensure_db_path_ready()
