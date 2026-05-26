from pathlib import Path

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
