from app.mam import build_search_payload, normalize_result


def test_normalize_result_parses_json_people_fields():
    raw = {
        "id": "42",
        "title": "Example",
        "author_info": '{"8234":"Author A","99":"Author B"}',
        "narrator_info": '{"112":"Narr A"}',
        "series_info": '{"1":"Series X"}',
        "filetypes": "mp3",
        "size": "1.2 GiB",
        "seeders": "5",
        "leechers": 0,
        "free": 1,
        "vip": 0,
        "my_snatched": False,
        "added": "2026-01-01",
        "catname": "Audiobooks",
    }
    row = normalize_result(raw)
    assert row["id"] == 42
    assert row["author"] == "Author A, Author B"
    assert row["narrator"] == "Narr A"
    assert row["series"] == "Series X"
    assert row["_torrent_id"] == "42"
    assert row["filetypes"] == "mp3"


def test_build_search_payload_matches_documented_shape():
    payload = build_search_payload(
        query="project hail mary",
        media_type="audiobook",
        search_in=["title", "author", "narrator"],
        sort="seedersDesc",
        search_type="active",
    )

    assert payload["thumbnail"] == "true"
    assert payload["tor"]["text"] == "project hail mary"
    assert payload["tor"]["srchIn"] == ["title", "author", "narrator"]
    assert payload["tor"]["searchType"] == "active"
    assert payload["tor"]["sortType"] == "seedersDesc"
    assert payload["tor"]["startNumber"] == "0"
    assert payload["tor"]["main_cat"] == ["13"]


def test_normalize_result_parses_string_flags_as_false():
    raw = {"id": "7", "title": "Flags", "free": "0", "fl_vip": "0", "vip": "0", "my_snatched": "0"}
    row = normalize_result(raw)
    assert row["free"] is False
    assert row["vip"] is False
    assert row["my_snatched"] is False


def test_normalize_result_parses_string_flags_as_true():
    raw = {"id": "8", "title": "Flags", "free": "1", "vip": "true", "my_snatched": "yes"}
    row = normalize_result(raw)
    assert row["free"] is True
    assert row["vip"] is True
    assert row["my_snatched"] is True
