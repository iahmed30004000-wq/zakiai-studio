"""عميل Google Drive (gdrive.py): كله على خادم وهمي محلي (tests/fake_drive.py) — بلا إنترنت ولا حساب Google حقيقي."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from fake_drive import CID, CSECRET, RT, connect, drive  # noqa: E402,F401

import gdrive  # noqa: E402
import net_allow  # noqa: E402


# ── حارس العناوين ───────────────────────────────────────────────────────
def test_fixed_base_allows_only_listed_https_hosts():
    bases = ("https://oauth2.googleapis.com", "https://www.googleapis.com")
    assert net_allow.fixed_base("https://www.googleapis.com/drive/v3/files?q=x", bases)
    for bad in ("http://www.googleapis.com/drive/v3/files", "https://evil.example/drive", "https://www.googleapis.com.evil.io/x",
                "https://user:pw@www.googleapis.com/x", "https://www.googleapis.com:8443/x", "https://www.googleapis.com/a/../b",
                "https://www.googleapis.com/x y", ""):
        with pytest.raises(net_allow.NetAllowError):
            net_allow.fixed_base(bad, bases)


def test_fixed_base_http_only_for_loopback():
    assert net_allow.fixed_base("http://127.0.0.1:5000/token", ("http://127.0.0.1:5000",))
    with pytest.raises(net_allow.NetAllowError):
        net_allow.fixed_base("http://ltx:5000/token", ("http://ltx:5000",))      # اسم docker مش loopback


# ── الإعداد ─────────────────────────────────────────────────────────────
def test_set_app_validates_and_keeps_secret_out_of_settings_file(drive):
    with pytest.raises(gdrive.DriveError):
        gdrive.set_app("not-a-client", CSECRET)
    with pytest.raises(gdrive.DriveError):
        gdrive.set_app(CID, "short")
    gdrive.set_app(CID, CSECRET)
    assert gdrive.configured() and not gdrive.connected()
    raw = drive.settings.read_text(encoding="utf-8")
    assert CSECRET not in raw and CID in raw


def test_device_flow_pending_then_connected(drive):
    gdrive.set_app(CID, CSECRET)
    d = gdrive.device_start()
    assert d["user_code"] == "ABCD-EFGH" and "device_code" not in d
    assert gdrive.device_poll()["state"] == "pending"
    gdrive._device["next_at"] = 0                         # ما نستنى الفاصل
    drive.device = "ok"
    assert gdrive.device_poll()["state"] == "connected"
    st = gdrive.status()
    assert st["connected"] and st["email"] == "owner@example.com"
    raw = drive.settings.read_text(encoding="utf-8")
    assert RT not in raw and CSECRET not in raw
    assert all(RT not in str(v) for v in st.values())


def test_device_flow_denied(drive):
    gdrive.set_app(CID, CSECRET)
    gdrive.device_start()
    drive.device = "denied"
    assert gdrive.device_poll()["state"] == "denied"
    assert not gdrive.connected()


def test_device_start_needs_app(drive):
    with pytest.raises(gdrive.DriveError) as e:
        gdrive.device_start()
    assert e.value.code == "not_configured"


def test_revoked_refresh_token_is_fatal_auth(drive):
    connect(drive)
    gdrive.forget_token()
    drive.revoked = True
    with pytest.raises(gdrive.DriveFatal) as e:
        gdrive.about()
    assert e.value.code == "auth"


def test_disconnect_revokes_and_clears(drive):
    connect(drive)
    gdrive.disconnect()
    assert drive.revoked and not gdrive.connected() and gdrive.configured()


# ── المجلدات والرفع ─────────────────────────────────────────────────────
def test_folder_create_and_find_by_prop(drive):
    connect(drive)
    a = gdrive.create_folder("Zakiai", None, "Zakiai")
    b = gdrive.create_folder("كريم's", a, "Zakiai/كريم's")
    assert gdrive.find_by_prop("vp_folder", "Zakiai/كريم's") == b
    assert gdrive.find_by_prop("vp_folder", "Zakiai/غير") is None
    assert drive.path_of(b) == "Zakiai/كريم's"


def test_small_upload_then_update_same_file(drive, tmp_path):
    connect(drive)
    par = gdrive.create_folder("x", None, "x")
    f = tmp_path / "a.png"
    f.write_bytes(b"PNG-one")
    fid = gdrive.upload(f, name="مشهد-01.png", parent=par, key="k1", mime="image/png")
    assert drive.files[fid]["content"] == b"PNG-one" and drive.files[fid]["parents"] == [par]
    f.write_bytes(b"PNG-two")
    fid2 = gdrive.upload(f, name="مشهد-01.png", parent=par, key="k1", mime="image/png", file_id=fid)
    assert fid2 == fid and drive.files[fid]["content"] == b"PNG-two" and drive.files[fid]["revisions"] == 2
    assert gdrive.find_by_prop("vp_key", "k1") == fid


def test_resumable_upload_in_chunks(drive, tmp_path, monkeypatch):
    connect(drive)
    monkeypatch.setattr(gdrive, "SIMPLE_MAX", 10)
    monkeypatch.setattr(gdrive, "CHUNK", 256 * 1024)
    data = os.urandom(256 * 1024 * 2 + 1000)
    f = tmp_path / "v.mp4"
    f.write_bytes(data)
    seen = []
    fid = gdrive.upload(f, name="v.mp4", parent=gdrive.create_folder("x", None, "x"), key="kv", mime="video/mp4", on_session=seen.append)
    assert drive.files[fid]["content"] == data
    assert len(seen) == 1 and seen[0].startswith(drive.base)
    assert sum(1 for r in drive.requests if r["range"] and r["range"].startswith("bytes ") and "*" not in r["range"]) == 3


def test_resumable_resumes_after_network_drop(drive, tmp_path, monkeypatch):
    connect(drive)
    monkeypatch.setattr(gdrive, "SIMPLE_MAX", 10)
    monkeypatch.setattr(gdrive, "CHUNK", 256 * 1024)
    data = os.urandom(256 * 1024 * 3)
    f = tmp_path / "v.mp4"
    f.write_bytes(data)
    par = gdrive.create_folder("x", None, "x")
    drive.modes["resumable"] = "drop"
    seen = []
    with pytest.raises(gdrive.DriveTransient):
        gdrive.upload(f, name="v.mp4", parent=par, key="kv", mime="video/mp4", on_session=seen.append)
    fid = gdrive.upload(f, name="v.mp4", parent=par, key="kv", mime="video/mp4", session_url=seen[0])
    assert drive.files[fid]["content"] == data
    assert len([x for x in drive.files.values() if x["name"] == "v.mp4"]) == 1


def test_foreign_session_location_refused(drive, tmp_path, monkeypatch):
    connect(drive)
    monkeypatch.setattr(gdrive, "SIMPLE_MAX", 10)
    drive.modes["resumable"] = "evil_location"
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x" * 100)
    with pytest.raises(gdrive.DriveFatal) as e:
        gdrive.upload(f, name="v.mp4", parent=gdrive.create_folder("x", None, "x"), key="kv", mime="video/mp4")
    assert e.value.code == "bad_url"
    assert not any("evil" in r["path"] for r in drive.requests)


@pytest.mark.parametrize("mode,cls,code", [("500", gdrive.DriveTransient, "google_down"), ("429", gdrive.DriveTransient, "rate_limit"),
                                           ("quota", gdrive.DriveFatal, "full"), ("disabled", gdrive.DriveFatal, "api_disabled")])
def test_upload_error_mapping(drive, tmp_path, mode, cls, code):
    connect(drive)
    par = gdrive.create_folder("x", None, "x")
    drive.modes["upload"] = mode
    f = tmp_path / "a.png"
    f.write_bytes(b"x")
    with pytest.raises(cls) as e:
        gdrive.upload(f, name="a.png", parent=par, key="k", mime="image/png")
    assert e.value.code == code


def test_no_network_is_transient(drive):
    connect(drive)
    gdrive.forget_token()
    drive.stop()
    with pytest.raises(gdrive.DriveTransient) as e:
        gdrive.about()
    assert e.value.code == "network"
    drive.stop = lambda: None                              # الفكسشر بيوقفه مرة تانية


def test_redirects_not_followed(drive, monkeypatch):
    connect(drive)
    calls = []
    import requests

    real = requests.Session.request

    def spy(self, method, url, **kw):
        calls.append((self.trust_env, kw.get("allow_redirects")))
        return real(self, method, url, **kw)
    monkeypatch.setattr(requests.Session, "request", spy)
    gdrive.about()
    assert calls and all(te is False and ar is False for te, ar in calls)
