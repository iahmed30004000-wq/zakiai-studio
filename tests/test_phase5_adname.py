import pytest

import adname


def test_build_five_parts_roundtrip():
    name = adname.build("SY", "kama", "DawaCare", "VP-kama-109-v2")
    assert name == "SY|kama|DawaCare|video|VP-kama-109-v2"
    assert adname.parse(name) == {"country": "SY", "product": "kama", "landing_page": "DawaCare",
                                  "type": "video", "script_id": "VP-kama-109-v2"}


def test_parse_four_parts_still_works_without_script():
    p = adname.parse("SY|kama|DawaCare|video")
    assert p["country"] == "SY" and p["product"] == "kama" and p["type"] == "video"
    assert p["script_id"] is None


def test_fifth_part_not_vp_is_not_guessed():
    assert adname.parse("SY|kama|DawaCare|video|test-2")["script_id"] is None
    assert adname.parse("SY|kama|DawaCare|video|VP-broken")["script_id"] is None


def test_parse_garbage_never_raises():
    for bad in ("", None, "abc", "a|b", "|||"):
        p = adname.parse(bad)
        assert set(p) == {"country", "product", "landing_page", "type", "script_id"}
        assert p["script_id"] is None


def test_build_sanitizes_separator_and_requires_vp():
    name = adname.build("SY", "kama", "Dawa|Care", "VP-kama-1-v1")
    assert adname.parse(name)["landing_page"] == "Dawa-Care"
    with pytest.raises(ValueError):
        adname.build("SY", "kama", "DawaCare", "kama-1-v1")
    with pytest.raises(ValueError):
        adname.build("SY", "kama", "", "VP-kama-1-v1")
