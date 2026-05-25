from app import mam


def test_parse_people_handles_list_dict_and_plain_string():
    assert mam._parse_people([{"name": "A"}, {"name": "B"}]) == "A, B"
    assert mam._parse_people({"1": "X", "2": "Y"}) == "X, Y"
    assert mam._parse_people("Solo") == "Solo"


def test_parse_people_parses_json_encoded_map_string():
    assert mam._parse_people('{"1":"Author A","2":"Author B"}') == "Author A, Author B"


def test_parse_flag_supports_common_truthy_falsey_values():
    assert mam._parse_flag("yes") is True
    assert mam._parse_flag("off") is False
    assert mam._parse_flag(1) is True
    assert mam._parse_flag(0.0) is False


def test_build_cookie_header_prefers_explicit_cookie(monkeypatch):
    monkeypatch.setattr(mam.settings, "mam_cookie", "mam_id=abc; mam_session=def")
    monkeypatch.setattr(mam.settings, "mam_uid", "")
    monkeypatch.setattr(mam.settings, "mam_session", "")
    assert mam._build_cookie_header() == "mam_id=abc; mam_session=def"


def test_build_cookie_header_assembles_uid_and_session(monkeypatch):
    monkeypatch.setattr(mam.settings, "mam_cookie", "")
    monkeypatch.setattr(mam.settings, "mam_uid", "123")
    monkeypatch.setattr(mam.settings, "mam_session", "xyz")
    assert mam._build_cookie_header() == "mam_id=123; mam_session=xyz"
