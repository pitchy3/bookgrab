import pytest

from app.config import Settings, parse_mam_hash_lookup_scope


def test_mam_hash_lookup_scope_defaults_to_mam_only(monkeypatch):
    monkeypatch.delenv("MAM_HASH_LOOKUP_SCOPE", raising=False)

    settings = Settings()

    assert settings.mam_hash_lookup_scope == "mam_only"


@pytest.mark.parametrize("scope", ["mam_only", "category", "bookgrab", "all"])
def test_mam_hash_lookup_scope_valid_values_parse(monkeypatch, scope):
    monkeypatch.setenv("MAM_HASH_LOOKUP_SCOPE", scope)

    settings = Settings()

    assert settings.mam_hash_lookup_scope == scope


def test_mam_hash_lookup_scope_invalid_value_raises_clear_error():
    with pytest.raises(RuntimeError, match="MAM_HASH_LOOKUP_SCOPE.*all.*mam_only"):
        parse_mam_hash_lookup_scope("everything")


def test_mam_tracker_hosts_normalize_lowercase_trim_and_empty(monkeypatch):
    monkeypatch.setenv("MAM_TRACKER_HOSTS", " MyAnonAMouse.net, ,WWW.MYANONAMOUSE.NET ")

    settings = Settings()

    assert settings.mam_tracker_hosts == ["myanonamouse.net", "www.myanonamouse.net"]


def test_mam_hash_lookup_include_categories_defaults_from_qbit_categories(monkeypatch):
    monkeypatch.delenv("MAM_HASH_LOOKUP_INCLUDE_CATEGORIES", raising=False)
    monkeypatch.setenv("QBIT_CATEGORY_AUDIOBOOKS", "audio")
    monkeypatch.setenv("QBIT_CATEGORY_EBOOKS", "ebooks")

    settings = Settings()

    assert settings.mam_hash_lookup_include_categories == ["audio", "ebooks"]


def test_mam_hash_lookup_include_categories_explicit_empty_disables_category_inclusion(monkeypatch):
    monkeypatch.setenv("MAM_HASH_LOOKUP_INCLUDE_CATEGORIES", "")
    monkeypatch.setenv("QBIT_CATEGORY_AUDIOBOOKS", "audio")
    monkeypatch.setenv("QBIT_CATEGORY_EBOOKS", "ebooks")

    settings = Settings()

    assert settings.mam_hash_lookup_include_categories == []
