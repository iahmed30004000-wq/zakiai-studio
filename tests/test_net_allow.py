"""قائمة سماح الروابط الداخلية (net_allow): صندوق التحريك والواجهة القياسية، ولحام المسارات الآمن."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import motion  # noqa: E402
import net_allow as na  # noqa: E402


@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1:8101", "http://127.0.0.1:8101"), ("http://localhost:8101/", "http://localhost:8101"),
    ("http://[::1]:8101", "http://[::1]:8101"), ("http://127.5.5.5:80", "http://127.5.5.5:80"),
    ("http://engine:8100", "http://engine:8100"), ("  http://WAN:8102  ", "http://wan:8102"),
])
def test_accepts_loopback_and_docker_names(url, expected):
    assert na.validate(url) == expected


BAD = ["http://example.com:80", "http://8.8.8.8:80", "http://10.0.0.5:8101", "http://192.168.1.5:8101", "http://ltx.internal:8101",
       "https://127.0.0.1:8101", "ftp://127.0.0.1:21", "http://user:pw@127.0.0.1:8101", "http://user@127.0.0.1:8101",
       "http://127.0.0.1:8101@evil.com:80", "http://127.0.0.1:8101/?token=abc", "http://127.0.0.1:8101#frag", "http://127.0.0.1",
       "http://127.0.0.1:", "http://127.0.0.1:99999", "http://2130706433:8101", "http://0x7f000001:8101", "http://127.1:8101",
       "http://1ltx:8101", "http://127.0.0.1:8101\\@evil.com", "http://127.0.0.1:8101 /x", "http://:8101", "", "   ", None, 5]


@pytest.mark.parametrize("url", BAD)
def test_rejects_everything_else(url):
    with pytest.raises(na.NetAllowError):
        na.validate(url)
    with pytest.raises(na.NetAllowError):
        na.validate(url, allow_path=True)                       # المسار المسموح ما بيفتح باب لأي شي تاني


def test_a_path_is_only_accepted_when_the_kind_allows_it():
    with pytest.raises(na.NetAllowError, match="بدون مسار"):
        na.validate("http://127.0.0.1:8101/v1")
    assert na.validate("http://127.0.0.1:8101/v1", allow_path=True) == "http://127.0.0.1:8101/v1"
    assert na.validate("http://localhost:8000/v1/", allow_path=True) == "http://localhost:8000/v1"
    assert na.validate("http://localhost:8000", allow_path=True) == "http://localhost:8000"
    assert na.validate("http://speaches:8000/api/v1", allow_path=True) == "http://speaches:8000/api/v1"
    for bad in ("/../x", "/a/b/c/d", "/v1//x", "/v 1", "/%2e%2e", "/v1;x", "/v1?x=1", "/v1#x"):
        with pytest.raises(na.NetAllowError):
            na.validate(f"http://127.0.0.1:8101{bad}", allow_path=True)


def test_messages_are_arabic_and_use_the_given_subject():
    with pytest.raises(na.NetAllowError, match="رابط الواجهة مطلوب"):
        na.validate("", subject="رابط الواجهة", example="http://127.0.0.1:8000/v1")
    with pytest.raises(na.NetAllowError, match="ممنوع اسم مستخدم.*رابط الواجهة"):
        na.validate("http://a:b@127.0.0.1:1", subject="رابط الواجهة")
    with pytest.raises(na.NetAllowError, match="المضيف مش مسموح"):
        na.validate("http://example.com:1")


def test_join_keeps_calls_inside_the_base_and_same_host_blocks_redirect_tricks():
    base = na.validate("http://127.0.0.1:8000/v1", allow_path=True)
    assert na.join(base, "/images/generations") == "http://127.0.0.1:8000/v1/images/generations"
    for bad in ("images", "/../etc/passwd", "//evil.com/x", "/a?b=1", "/a#b", "/a b", "/a\\b", "", None):
        with pytest.raises(na.NetAllowError):
            na.join(base, bad)
    assert na.same_host(base, "http://127.0.0.1:8000/files/x.png")
    assert not na.same_host(base, "http://127.0.0.1:8001/x.png") and not na.same_host(base, "http://localhost:8000/x.png")
    assert not na.same_host(base, "https://127.0.0.1:8000/x.png") and not na.same_host(base, "http://evil.com/x.png") and not na.same_host(base, "http://[bad")


def test_motion_delegates_with_the_same_exception_type_and_messages():
    assert motion.validate_engine_url("http://engine:8100") == "http://engine:8100"
    with pytest.raises(motion.MotionError, match="عنوان الصندوق مطلوب"):
        motion.validate_engine_url("")
    with pytest.raises(motion.MotionError, match="المضيف مش مسموح"):
        motion.validate_engine_url("http://example.com:80")
    assert motion._host_allowed("localhost") and not motion._host_allowed("example.com")
