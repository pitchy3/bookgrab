import pytest

from app.config import Settings, parse_mam_hash_lookup_scope


def test_default_hash_lookup_scope_is_mam_only(monkeypatch):
    monkeypatch.delenv("MAM_HASH_LOOKUP_SCOPE", raising=False)

    settings = Settings()

    assert settings.mam_hash_lookup_scope == "mam_only"


@pytest.mark.parametrize("scope", ["mam_only", "category", "bookgrab", "all"])
def test_valid_hash_lookup_scopes_parse(monkeypatch, scope):
    monkeypatch.setenv("MAM_HASH_LOOKUP_SCOPE", scope)

    settings = Settings()

    assert settings.mam_hash_lookup_scope == scope


def test_invalid_hash_lookup_scope_raises_clear_error():
    with pytest.raises(RuntimeError, match="MAM_HASH_LOOKUP_SCOPE.*mam_only"):
        parse_mam_hash_lookup_scope("everything")


def test_tracker_host_list_normalizes(monkeypatch):
    monkeypatch.setenv("MAM_TRACKER_HOSTS", " MyAnonAMouse.net, www.MYANONAMOUSE.net ,, tracker.example ")

    settings = Settings()

    assert settings.mam_tracker_hosts == ["myanonamouse.net", "www.myanonamouse.net", "tracker.example"]


def test_include_categories_default_from_qbit_categories(monkeypatch):
    monkeypatch.delenv("MAM_HASH_LOOKUP_INCLUDE_CATEGORIES", raising=False)
    monkeypatch.setenv("QBIT_CATEGORY_AUDIOBOOKS", "AudioBooks")
    monkeypatch.setenv("QBIT_CATEGORY_EBOOKS", "EBooks")

    settings = Settings()

    assert settings.mam_hash_lookup_include_categories == ["audiobooks", "ebooks"]


def test_explicit_empty_category_list_disables_category_inclusion(monkeypatch):
    monkeypatch.setenv("MAM_HASH_LOOKUP_INCLUDE_CATEGORIES", "")

    settings = Settings()

    assert settings.mam_hash_lookup_include_categories == []
