from pathlib import Path
import asyncio

from app import importer
from app.importer import build_destination_path, find_importable_files, hardlink_file, is_supported_media_file


def test_media_extension_filtering():
    assert is_supported_media_file("a.m4b", "audiobook")
    assert not is_supported_media_file("a.txt", "audiobook")


def test_safe_destination_path_generation(tmp_path):
    src = tmp_path / "src" / "Disc 01" / "track01.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    d = {"title": "My:Book", "content_path": str(tmp_path / "src"), "qbit_name": "fallback"}
    dst = build_destination_path(d, src, str(tmp_path / "lib"))
    assert str(dst).startswith(str((tmp_path / "lib").resolve()))
    assert "My_Book" in str(dst)


def test_hardlink_success(tmp_path):
    src = tmp_path / "a.m4b"
    dst = tmp_path / "dest" / "a.m4b"
    src.write_bytes(b"abc")
    status = hardlink_file(src, dst, "skip", False)
    assert status == "linked"
    assert dst.exists() and src.stat().st_ino == dst.stat().st_ino


def test_conflict_skip(tmp_path):
    src = tmp_path / "a.m4b"; src.write_bytes(b"abc")
    dst = tmp_path / "b" / "a.m4b"; dst.parent.mkdir(parents=True); dst.write_bytes(b"old")
    assert hardlink_file(src, dst, "skip", False) == "skipped"


def test_conflict_replace(tmp_path):
    src = tmp_path / "a.m4b"; src.write_bytes(b"abc")
    dst = tmp_path / "b" / "a.m4b"; dst.parent.mkdir(parents=True); dst.write_bytes(b"old")
    assert hardlink_file(src, dst, "replace", False) == "linked"
    assert dst.read_bytes() == b"abc"


def test_conflict_invalid_policy(tmp_path):
    src = tmp_path / "a.m4b"; src.write_bytes(b"abc")
    dst = tmp_path / "b" / "a.m4b"; dst.parent.mkdir(parents=True); dst.write_bytes(b"old")
    try:
        hardlink_file(src, dst, "bogus", False)
        assert False, "expected ValueError"
    except ValueError:
        assert True


def test_directory_discovery_and_junk_ignore(tmp_path):
    root = tmp_path / "dl"; root.mkdir()
    (root / "book.m4b").write_bytes(b"x")
    (root / "sample.m4b").write_bytes(b"x")
    (root / "Thumbs.db").write_text("x")
    (root / "x.nfo").write_text("x")
    files = find_importable_files(str(root), "audiobook")
    names = {f.name for f in files}
    assert "book.m4b" in names
    assert "Thumbs.db" not in names


class _Qbit:
    def __init__(self, torrents=None, torrent=None):
        self._torrents = torrents or []
        self._torrent = torrent

    async def get_torrents(self):
        return self._torrents

    async def get_torrent(self, _hash):
        return self._torrent


def test_recover_qbit_hash_exact_match(monkeypatch):
    called = {}
    monkeypatch.setattr(importer, "update_download_qbit_info", lambda *args, **kwargs: called.update(kwargs))
    d = {"id": 1, "title": "The Assassin's Blade", "media_type": "audiobook", "qbit_name": "The Assassin's Blade"}
    q = _Qbit([{"hash": "h1", "name": "The Assassin's Blade.mp3", "category": "audiobooks", "content_path": "/x/The Assassin's Blade.mp3", "save_path": "/x"}])
    out = asyncio.run(importer.recover_qbit_torrent_for_download(d, q))
    assert out["hash"] == "h1"
    assert called["qbit_hash"] == "h1"


def test_recover_qbit_hash_author_prefix(monkeypatch):
    monkeypatch.setattr(importer, "update_download_qbit_info", lambda *args, **kwargs: None)
    d = {"id": 1, "title": "The Assassin's Blade", "media_type": "audiobook", "qbit_name": "The Assassin's Blade"}
    q = _Qbit([{"hash": "h1", "name": "Sarah J. Maas - The Assassin's Blade.mp3", "category": "audiobooks", "content_path": "/x/Sarah J. Maas - The Assassin's Blade.mp3", "save_path": "/x"}])
    out = asyncio.run(importer.recover_qbit_torrent_for_download(d, q))
    assert out["hash"] == "h1"


def test_recover_prefers_category_and_ambiguous(monkeypatch):
    errors = []
    monkeypatch.setattr(importer, "mark_download_checked", lambda _id, _s, e=None: errors.append(e))
    d = {"id": 1, "title": "Book", "media_type": "audiobook"}
    q = _Qbit([
        {"hash": "h1", "name": "Author - Book.mp3", "category": "audiobooks", "content_path": "/x/Author - Book.mp3"},
        {"hash": "h2", "name": "Other - Book.mp3", "category": "audiobooks", "content_path": "/x/Other - Book.mp3"},
        {"hash": "h3", "name": "Book.pdf", "category": "ebooks", "content_path": "/x/Book.pdf"},
    ])
    out = asyncio.run(importer.recover_qbit_torrent_for_download(d, q))
    assert out is None
    assert "ambiguous" in errors[-1]


def test_recover_no_match_sets_error(monkeypatch):
    errors = []
    monkeypatch.setattr(importer, "mark_download_checked", lambda _id, _s, e=None: errors.append(e))
    d = {"id": 1, "title": "Unique Title", "media_type": "audiobook"}
    out = asyncio.run(importer.recover_qbit_torrent_for_download(d, _Qbit([{"hash": "h", "name": "Different", "category": "audiobooks"}])))
    assert out is None
    assert "no matching" in errors[-1]


def test_recover_does_not_use_reverse_generic_substring(monkeypatch):
    errors = []
    monkeypatch.setattr(importer, "mark_download_checked", lambda _id, _s, e=None: errors.append(e))
    d1 = {"id": 1, "title": "The Book Thief", "media_type": "audiobook"}
    out1 = asyncio.run(importer.recover_qbit_torrent_for_download(d1, _Qbit([{"hash": "h", "name": "Book.mp3", "category": "audiobooks", "content_path": "/x/Book.mp3"}])))
    assert out1 is None
    d2 = {"id": 2, "title": "Project Hail Mary", "media_type": "audiobook"}
    out2 = asyncio.run(importer.recover_qbit_torrent_for_download(d2, _Qbit([{"hash": "h2", "name": "Hail.mp3", "category": "audiobooks", "content_path": "/x/Hail.mp3"}])))
    assert out2 is None
    assert all("no matching" in e for e in errors)


def test_run_import_once_recovers_and_uses_fresh_content_path(monkeypatch):
    monkeypatch.setattr(importer.settings, "import_enabled", True)
    monkeypatch.setattr(importer.settings, "import_require_seeding_or_complete", False)
    monkeypatch.setattr(importer.settings, "import_min_completion_ratio", 1.0)
    monkeypatch.setattr(importer, "get_pending_imports", lambda: [{"id": 1, "title": "Book", "media_type": "audiobook", "qbit_hash": None, "content_path": None}])
    monkeypatch.setattr(importer, "update_download_qbit_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(importer, "mark_download_checked", lambda *args, **kwargs: None)

    seen = {}

    async def _fake_import_download(download, _torrent):
        seen["content_path"] = download.get("content_path")
        return "imported"

    monkeypatch.setattr(importer, "import_download", _fake_import_download)
    q = _Qbit(
        torrents=[{"hash": "h1", "name": "Author - Book.mp3", "category": "audiobooks", "content_path": "/fresh/book.mp3", "save_path": "/fresh", "progress": 1.0, "state": "stalledUP", "amount_left": 0}],
        torrent={"hash": "h1", "name": "Author - Book.mp3", "category": "audiobooks", "content_path": "/fresh/book.mp3", "save_path": "/fresh", "progress": 1.0, "state": "stalledUP", "amount_left": 0},
    )
    summary = asyncio.run(importer.run_import_once(q))
    assert summary["processed"] == 1
    assert seen["content_path"] == "/fresh/book.mp3"


def test_run_import_once_waiting_reason_includes_progress_state_amount(monkeypatch):
    monkeypatch.setattr(importer.settings, "import_enabled", True)
    monkeypatch.setattr(importer.settings, "import_require_seeding_or_complete", True)
    monkeypatch.setattr(importer.settings, "import_min_completion_ratio", 0.95)
    monkeypatch.setattr(importer, "get_pending_imports", lambda: [{"id": 1, "title": "Book", "media_type": "audiobook", "qbit_hash": "h1", "content_path": "/x"}])
    captured = {}
    monkeypatch.setattr(importer, "mark_download_checked", lambda _id, _s, e=None: captured.setdefault("error", e))
    monkeypatch.setattr(importer, "update_download_qbit_info", lambda *args, **kwargs: None)
    q = _Qbit(torrent={"hash": "h1", "name": "Book", "category": "audiobooks", "content_path": "/x", "save_path": "/x", "progress": 1.0, "state": "downloading", "amount_left": 0})
    summary = asyncio.run(importer.run_import_once(q))
    assert summary["waiting"] == 1
    assert "progress=1.0" in captured["error"]
    assert "state=downloading" in captured["error"]
    assert "amount_left=0" in captured["error"]
