import pytest

from app import main


def test_validate_import_config_rejects_non_hardlink_mode(monkeypatch):
    monkeypatch.setattr(main.settings, "import_mode", "copy")
    monkeypatch.setattr(main.settings, "import_conflict_policy", "skip")
    monkeypatch.setattr(main.settings, "import_audiobook_library_path", "/library/a")
    monkeypatch.setattr(main.settings, "import_ebook_library_path", "")

    with pytest.raises(RuntimeError, match="IMPORT_MODE"):
        main._validate_import_config()


def test_validate_import_config_rejects_invalid_conflict_policy(monkeypatch):
    monkeypatch.setattr(main.settings, "import_mode", "hardlink")
    monkeypatch.setattr(main.settings, "import_conflict_policy", "merge")
    monkeypatch.setattr(main.settings, "import_audiobook_library_path", "/library/a")
    monkeypatch.setattr(main.settings, "import_ebook_library_path", "")

    with pytest.raises(RuntimeError, match="IMPORT_CONFLICT_POLICY"):
        main._validate_import_config()


def test_validate_import_config_requires_at_least_one_library(monkeypatch):
    monkeypatch.setattr(main.settings, "import_mode", "hardlink")
    monkeypatch.setattr(main.settings, "import_conflict_policy", "skip")
    monkeypatch.setattr(main.settings, "import_audiobook_library_path", "")
    monkeypatch.setattr(main.settings, "import_ebook_library_path", "")

    with pytest.raises(RuntimeError, match="At least one"):
        main._validate_import_config()


def test_validate_hash_lookup_scope_rejects_invalid_scope(monkeypatch):
    monkeypatch.setattr(main.settings, "mam_hash_lookup_scope", "everything")

    with pytest.raises(RuntimeError, match="MAM_HASH_LOOKUP_SCOPE"):
        main._validate_mam_hash_lookup_config()
