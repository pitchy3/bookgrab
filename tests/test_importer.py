from pathlib import Path
import asyncio

from app import importer
from app.importer import find_importable_files, hardlink_file, is_supported_media_file, plan_imports


def test_media_extension_filtering():
    assert is_supported_media_file("a.m4b", "audiobook")
    assert not is_supported_media_file("a.txt", "audiobook")



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



def test_run_import_once_logs_diagnostic_when_amount_left_zero_but_progress_imperfect(monkeypatch):
    monkeypatch.setattr(importer.settings, "import_enabled", True)
    monkeypatch.setattr(importer.settings, "import_require_seeding_or_complete", False)
    monkeypatch.setattr(importer, "get_pending_imports", lambda: [{"id": 1, "title": "Book", "media_type": "audiobook", "qbit_hash": "h1", "content_path": "/x"}])

    updates = []
    monkeypatch.setattr(importer, "update_download_qbit_info", lambda *args, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(importer, "mark_download_checked", lambda *args, **kwargs: None)

    async def _fake_import_download(_download, _torrent):
        return "imported"

    monkeypatch.setattr(importer, "import_download", _fake_import_download)
    q = _Qbit(torrent={"hash": "h1", "name": "Book", "category": "audiobooks", "content_path": "/x", "save_path": "/x", "progress": 0.9999, "state": "downloading", "amount_left": 0})
    summary = asyncio.run(importer.run_import_once(q))
    assert summary["processed"] == 1
    assert summary["imported"] == 1
    assert any("amount_left=0 but progress=0.9999" in (u.get("last_error") or "") for u in updates)


def _plan_paths(download, content_path, files, library_root):
    plans = plan_imports(download, content_path, files, str(library_root))
    return sorted(str(p.destination_path) for p in plans)


def test_plan_single_file_audiobook(tmp_path):
    src = tmp_path / "downloads" / "Project Hail Mary.m4b"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    d = {"title": "ignored", "qbit_name": "ignored", "media_type": "audiobook"}
    out = _plan_paths(d, src, [src], tmp_path / "library" / "audiobooks")
    assert out == [str((tmp_path / "library" / "audiobooks" / "Project Hail Mary" / "Project Hail Mary.m4b").resolve())]


def test_plan_verified_throne_of_glass_top_level_m4b_books(tmp_path):
    root = tmp_path / "downloads" / "Throne of Glass collection"
    root.mkdir(parents=True)
    titles = [
        "Crown of Midnight (Throne of Glass, Book 2)",
        "Empire of Storms (Throne of Glass, Book 5)",
        "Heir of Fire (Throne of Glass, Book 3)",
        "Kingdom of Ash (Throne of Glass, Book 7)",
        "Queen of Shadows (Throne of Glass, Book 4)",
        "Throne of Glass (Throne of Glass, Book 1)",
        "Tower of Dawn (Throne of Glass, Book 6)",
    ]
    for t in titles:
        (root / f"{t}.m4b").write_bytes(b"x")
        (root / f"{t}.jpg").write_bytes(b"x")
    files = find_importable_files(str(root), "audiobook")
    out = _plan_paths({"title": "Throne of Glass collection", "qbit_name": "Throne of Glass collection", "media_type": "audiobook"}, root, files, tmp_path / "library" / "audiobooks")
    assert len(out) == 7
    assert all(p.endswith('.m4b') for p in out)


def test_plan_verified_wheel_of_time_folder_shape(tmp_path):
    root = tmp_path / "downloads" / "Robert Jordan - The Wheel of Time Series"
    files = [
        root / "(0) New Spring (Unabridged)" / "[01] Intro.mp3",
        root / "(0) New Spring (Unabridged)" / "[02] Chapter 1 - The Hook.mp3",
        root / "(0) New Spring (Unabridged)" / "[03] Chapter 2 - A Wish Fulfilled.mp3",
        root / "(1) The Eye of the World (Unabridged)" / "[01] Intro.mp3",
        root / "(1) The Eye of the World (Unabridged)" / "[02] Chapter 1.mp3",
    ]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    (root / "(0) New Spring (Unabridged)" / "Folder.jpg").write_bytes(b"x")
    (root / "(1) The Eye of the World (Unabridged)" / "Folder.jpg").write_bytes(b"x")
    discovered = find_importable_files(str(root), "audiobook")
    out = _plan_paths({"title": "Wheel of Time", "qbit_name": "Wheel of Time", "media_type": "audiobook"}, root, discovered, tmp_path / "library" / "audiobooks")
    assert str((tmp_path / "library" / "audiobooks" / "_0_ New Spring _Unabridged_" / "_01_ Intro.mp3").resolve()) in out
    assert str((tmp_path / "library" / "audiobooks" / "_1_ The Eye of the World _Unabridged_" / "_02_ Chapter 1.mp3").resolve()) in out


def test_plan_folder_with_multiple_m4b_parts_is_one_book(tmp_path):
    root = tmp_path / "downloads" / "Series"
    a = root / "Book 01" / "Part 1.m4b"
    b = root / "Book 01" / "Part 2.m4b"
    for f in [a, b]:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    out = _plan_paths({"title": "Series", "qbit_name": "Series", "media_type": "audiobook"}, root, [a, b], tmp_path / "library" / "audiobooks")
    assert str((tmp_path / "library" / "audiobooks" / "Book 01" / "Part 1.m4b").resolve()) in out
    assert str((tmp_path / "library" / "audiobooks" / "Book 01" / "Part 2.m4b").resolve()) in out


def test_plan_top_level_mp3_files_group_as_one_book(tmp_path):
    root = tmp_path / "downloads" / "Some Book"
    files = []
    for name in ["[01] Intro.mp3", "[02] Chapter 1.mp3", "[03] Chapter 2.mp3"]:
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        files.append(f)
    out = _plan_paths({"title": "Some Book", "qbit_name": "Some Book", "media_type": "audiobook"}, root, files, tmp_path / "library" / "audiobooks")
    assert str((tmp_path / "library" / "audiobooks" / "Some Book" / "_01_ Intro.mp3").resolve()) in out
    assert str((tmp_path / "library" / "audiobooks" / "Some Book" / "_03_ Chapter 2.mp3").resolve()) in out


def test_plan_multiple_top_level_m4b_files_are_separate_books(tmp_path):
    root = tmp_path / "downloads" / "Series"
    a = root / "Book 01.m4b"
    b = root / "Book 02.m4b"
    root.mkdir(parents=True)
    a.write_bytes(b"x"); b.write_bytes(b"x")
    out = _plan_paths({"title": "Series", "qbit_name": "Series", "media_type": "audiobook"}, root, [a, b], tmp_path / "library" / "audiobooks")
    assert str((tmp_path / "library" / "audiobooks" / "Book 01" / "Book 01.m4b").resolve()) in out
    assert str((tmp_path / "library" / "audiobooks" / "Book 02" / "Book 02.m4b").resolve()) in out


def test_plan_multiple_ebook_files_each_own_folder(tmp_path):
    root = tmp_path / "downloads" / "Series"
    a = root / "Book 01.epub"
    b = root / "Book 02.pdf"
    c = root / "Book 03.azw3"
    root.mkdir(parents=True)
    a.write_bytes(b"x"); b.write_bytes(b"x"); c.write_bytes(b"x")
    out = _plan_paths({"title": "Series", "qbit_name": "Series", "media_type": "ebook"}, root, [a, b, c], tmp_path / "library" / "ebooks")
    assert str((tmp_path / "library" / "ebooks" / "Book 01" / "Book 01.epub").resolve()) in out
    assert str((tmp_path / "library" / "ebooks" / "Book 02" / "Book 02.pdf").resolve()) in out
    assert str((tmp_path / "library" / "ebooks" / "Book 03" / "Book 03.azw3").resolve()) in out


def test_plan_mixed_top_level_folder_and_file(tmp_path):
    root = tmp_path / "downloads" / "Series"
    a = root / "Book 01" / "[01] Intro.mp3"
    b = root / "Book 01" / "[02] Chapter 1.mp3"
    c = root / "Book 02.m4b"
    for f in [a, b, c]:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    out = _plan_paths({"title": "Series", "qbit_name": "Series", "media_type": "audiobook"}, root, [a, b, c], tmp_path / "library" / "audiobooks")
    assert str((tmp_path / "library" / "audiobooks" / "Book 01" / "_01_ Intro.mp3").resolve()) in out
    assert str((tmp_path / "library" / "audiobooks" / "Book 02" / "Book 02.m4b").resolve()) in out


def test_plan_path_safety_cannot_escape_root(tmp_path):
    root = tmp_path / "downloads" / "Series"
    a = root / "Book 01" / "track.mp3"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"x")
    library_root = (tmp_path / "library" / "audiobooks").resolve()
    plans = plan_imports({"title": "Series", "qbit_name": "Series", "media_type": "audiobook"}, root, [a], str(library_root))
    assert all(p.destination_path.resolve().is_relative_to(library_root) for p in plans)
