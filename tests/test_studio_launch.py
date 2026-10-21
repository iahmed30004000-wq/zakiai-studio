"""استوديو الإنتاج — المحطة ١١: الإطلاق (عقد vp-ops.v1)."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import requests
import yaml

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_characters_shots as tc  # noqa: E402
import test_studio_voice_timeline as tv  # noqa: E402

import characters  # noqa: E402
import config  # noqa: E402
import launch  # noqa: E402
import montage  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import voice_studio  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")
ROOT = Path(__file__).resolve().parent.parent
CONTRACT = yaml.safe_load((ROOT / "contracts" / "vp-ops.v1.yaml").read_text(encoding="utf-8"))


class FakeOps:
    """عمليات وهمية: بتسجّل الطلبات وبتردّ حسب الجدول."""

    def __init__(self):
        self.calls = []
        self.responses = []          # قائمة (status_code, json) بالترتيب؛ الأخير بيتكرر
        self.raise_exc = None

    def request(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        if self.raise_exc:
            raise self.raise_exc
        code, body = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        r = requests.Response()
        r.status_code = code
        r._content = json.dumps(body).encode()
        return r


@pytest.fixture
def ops(monkeypatch):
    f = FakeOps()
    monkeypatch.setattr(launch.requests, "request", f.request)
    monkeypatch.setattr(launch, "_secret", lambda n: {"crm_token_launch": "TOK_LAUNCH", "crm_token": "TOK_READ"}.get(n))
    import crm
    monkeypatch.setattr(crm, "base_url", lambda: "https://ops.example.com")
    return f


class Light:
    pass


@pytest.fixture
def animated(env, monkeypatch):
    """خط زمني معتمد وشخصية مختارة، ومحطات ٦–١٠ معتمدة (بلا توليد صور/حركات — مش موضوع هالاختبارات)."""
    st = tv.produce_ok(env, monkeypatch)
    ch = tc.mk(env, name="ريم")
    characters.choose("s1", json.loads(st.script.read_text(encoding="utf-8")), ch["id"])
    voice_studio.approve_voice(st.script)
    for n in range(6, 11):
        studio_state.set_state("s1", n, "approved", "x")
    o = Light()
    o.script, o.env = st.script, env
    return o


@pytest.fixture
def exported(animated):
    """تصدير نهائي 1080×1920 حقيقي مسجَّل بالخط الزمني، وبريف فيه معرّفات العمليات."""
    out = animated.env.lib / "exports" / "VP-testp-1-v1.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=1080x1920:d=2:r=30", "-f", "lavfi", "-i", "sine=d=2",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], capture_output=True, check=True)
    tl = timeline.load("s1")
    tl["render"] = {"final": {"file": "exports/VP-testp-1-v1.mp4", "at": "2026-09-30T10:00:00+00:00", "size": [1080, 1920],
                              "duration_ms": tl["voice"]["duration_ms"], "ahat": False, "captions": 10}}
    timeline.save("s1", tl)
    p = animated.env.products / "testp.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d.update(ops_product_id="prod_77", ops_store_id="store_9")
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    animated.out = out
    return animated


# ───────────────────────── بناء الطلب ─────────────────────────
def test_meta_has_every_required_contract_field_and_correct_values(exported):
    meta, video = launch.build_meta(exported.script, "test")
    required = set(CONTRACT["components"]["schemas"]["LaunchMeta"]["required"])
    assert required <= set(meta), required - set(meta)
    assert meta["vp_id"] == "VP-testp-1-v1" and meta["mode"] == "test" and meta["country"] == "SY"
    assert meta["product_id"] == "prod_77" and meta["store_id"] == "store_9" and meta["framework"] == "pas"
    assert 45 <= meta["duration_sec"] <= 50 and meta["character_id"] == "ch_f_001"
    assert meta["checksum_sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert base64.b64decode(meta["thumbnail"])[:4] == b"\x89PNG"
    assert "00:00:00" in meta["captions_srt"] and "-->" in meta["captions_srt"]
    assert len(meta["script_text"].splitlines()) == 7


def test_missing_ops_ids_or_bad_video_block_the_request(exported):
    p = exported.env.products / "testp.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["ops_store_id"] = ""
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(launch.LaunchError) as e:
        launch.build_meta(exported.script, "active")
    assert "معرّف المتجر" in str(e.value) and e.value.code == "invalid_meta"
    d["ops_store_id"] = "store_9"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=540x960:d=1:r=30", "-pix_fmt", "yuv420p", str(exported.out)],
                   capture_output=True, check=True)
    with pytest.raises(launch.LaunchError) as e2:
        launch.build_meta(exported.script, "active")
    assert e2.value.code == "video_invalid" and "1080x1920" in str(e2.value)
    with pytest.raises(launch.LaunchError):
        launch.build_meta(exported.script, "weird")


def test_info_lists_every_blocker_in_arabic(animated, monkeypatch):
    monkeypatch.setattr(launch, "_secret", lambda n: None)
    import crm
    monkeypatch.setattr(crm, "base_url", lambda: "")
    i = launch.info(animated.script)
    text = " | ".join(i["problems"])
    assert "تصدير نهائي" in text and "معرّف المنتج" in text and "توكن vp:launch" in text and "عنوان العمليات" in text
    assert i["vp_id"] == "VP-testp-1-v1" and not i["launch_token_set"]


def test_srt_format():
    s = launch.to_srt([{"start_ms": 1500, "end_ms": 3723450, "text": "مرحبا"}])
    assert s.startswith("1\n00:00:01,500 --> 01:02:03,450\nمرحبا")


# ───────────────────────── الإرسال ─────────────────────────
def test_send_requires_explicit_confirmation_and_sends_one_multipart_request(exported, ops):
    ops.responses = [(200, {"request_id": "req_1", "status": "received", "ops_url": "https://ops.example.com/r/1"})]
    with pytest.raises(launch.LaunchError) as e:
        launch.send(exported.script, "test")
    assert e.value.code == "confirm_required" and ops.calls == []
    r = launch.send(exported.script, "test", confirm=True)
    assert r == {"mode": "test", "request_id": "req_1", "status": "received", "label": "استُلم"}
    assert len(ops.calls) == 1
    c = ops.calls[0]
    assert c["method"] == "POST" and c["url"] == "https://ops.example.com/api/v1/vp/launch-requests"
    assert c["headers"]["Authorization"] == "Bearer TOK_LAUNCH"                 # vp:launch مش القراءة
    assert c["allow_redirects"] is False
    meta = json.loads(c["data"]["meta"])
    assert meta["mode"] == "test" and meta["vp_id"] == "VP-testp-1-v1"
    assert studio_state.state_of("s1", 11) == "running"
    rec = launch.records("VP-testp-1-v1")["test"]
    assert rec["request_id"] == "req_1" and rec["status"] == "received"


def test_same_video_same_mode_is_never_sent_twice_but_other_mode_is_allowed(exported, ops):
    ops.responses = [(200, {"request_id": "req_1", "status": "received"})]
    launch.send(exported.script, "test", confirm=True)
    with pytest.raises(launch.LaunchError) as e:
        launch.send(exported.script, "test", confirm=True)
    assert e.value.code == "duplicate_request" and len(ops.calls) == 1
    ops.responses = [(200, {"request_id": "req_2", "status": "preparing"})]
    launch.send(exported.script, "active", confirm=True)
    assert set(launch.records("VP-testp-1-v1")) == {"test", "active"} and len(ops.calls) == 2


def test_after_failure_or_rejection_a_new_request_is_allowed(exported, ops):
    ops.responses = [(200, {"request_id": "req_1", "status": "received"}), (200, {"request_id": "req_2", "status": "failed"})]
    launch.send(exported.script, "test", confirm=True)
    ops.responses = [(200, {"status": "rejected", "reason": "الحساب موقوف"})]
    launch.refresh(exported.script, "test")
    ops.responses = [(200, {"request_id": "req_3", "status": "received"})]
    assert launch.send(exported.script, "test", confirm=True)["request_id"] == "req_3"


def test_errors_are_arabic_classified_and_nothing_is_recorded(exported, ops, monkeypatch):
    ops.responses = [(403, {"code": "forbidden", "message": "التوكن ما إله صلاحية"})]
    with pytest.raises(launch.LaunchError) as e:
        launch.send(exported.script, "test", confirm=True)
    assert e.value.code == "forbidden" and "صلاحية" in str(e.value) and launch.records("VP-testp-1-v1") == {}
    ops.raise_exc = requests.exceptions.ConnectionError()
    with pytest.raises(launch.LaunchError) as e2:
        launch.send(exported.script, "test", confirm=True)
    assert e2.value.code == "offline" and "ما انبعت" in str(e2.value) and launch.records("VP-testp-1-v1") == {}
    ops.raise_exc = None
    ops.responses = [(422, {"code": "checksum_mismatch", "message": "الـchecksum ما طابق"})]
    with pytest.raises(launch.LaunchError) as e3:
        launch.send(exported.script, "test", confirm=True)
    assert e3.value.code == "checksum_mismatch"
    ops.responses = [(200, {"oops": True})]
    with pytest.raises(launch.LaunchError) as e4:
        launch.send(exported.script, "test", confirm=True)
    assert e4.value.code == "bad_response"
    monkeypatch.setattr(launch, "_secret", lambda n: None)
    with pytest.raises(launch.LaunchError) as e5:
        launch.send(exported.script, "test", confirm=True)
    assert e5.value.code == "no_token"


def test_http_non_localhost_and_redirects_are_refused(exported, ops, monkeypatch):
    import crm
    monkeypatch.setattr(crm, "base_url", lambda: "http://ops.example.com")
    with pytest.raises(launch.LaunchError):
        launch.send(exported.script, "test", confirm=True)
    monkeypatch.setattr(crm, "base_url", lambda: "https://ops.example.com")
    ops.responses = [(302, {})]
    with pytest.raises(launch.LaunchError) as e:
        launch.send(exported.script, "test", confirm=True)
    assert e.value.code == "redirect"


def test_send_blocked_before_station_10_is_approved(exported, ops):
    studio_state.set_state("s1", 10, "awaiting_choice", "x")
    with pytest.raises(launch.LaunchError) as e:
        launch.send(exported.script, "test", confirm=True)
    assert e.value.code == "station_blocked" and ops.calls == []


# ───────────────────────── الحالة والإلغاء ─────────────────────────
@pytest.mark.parametrize("status,state", [("preparing", "running"), ("awaiting_approval", "awaiting_choice"),
                                          ("launched", "approved"), ("rejected", "failed"), ("failed", "failed")])
def test_refresh_uses_read_token_and_maps_status_to_station_state(exported, ops, status, state):
    ops.responses = [(200, {"request_id": "req_1", "status": "received"})]
    launch.send(exported.script, "active", confirm=True)
    ops.responses = [(200, {"status": status, "reason": "سبب", "ad_id": "ad_5", "ops_url": "https://ops.example.com/x"})]
    rec = launch.refresh(exported.script, "active")
    assert ops.calls[-1]["method"] == "GET" and ops.calls[-1]["url"].endswith("/launch-requests/req_1")
    assert ops.calls[-1]["headers"]["Authorization"] == "Bearer TOK_READ"
    assert rec["status"] == status and studio_state.state_of("s1", 11) == state
    if status == "launched":
        assert rec["ad_id"] == "ad_5"


def test_unknown_status_is_rejected_not_guessed(exported, ops):
    ops.responses = [(200, {"request_id": "req_1", "status": "received"})]
    launch.send(exported.script, "active", confirm=True)
    ops.responses = [(200, {"status": "exploded"})]
    with pytest.raises(launch.LaunchError) as e:
        launch.refresh(exported.script, "active")
    assert e.value.code == "bad_response"


def test_cancel_only_before_approval_and_with_launch_token(exported, ops):
    ops.responses = [(200, {"request_id": "req_1", "status": "awaiting_approval"})]
    launch.send(exported.script, "test", confirm=True)
    ops.responses = [(200, {})]
    rec = launch.cancel(exported.script, "test")
    assert rec["status"] == "cancelled" and ops.calls[-1]["url"].endswith("/req_1/cancel")
    assert ops.calls[-1]["headers"]["Authorization"] == "Bearer TOK_LAUNCH"
    ops.responses = [(200, {"request_id": "req_2", "status": "launched"})]
    launch.send(exported.script, "test", confirm=True)
    n = len(ops.calls)
    with pytest.raises(launch.LaunchError) as e:
        launch.cancel(exported.script, "test")
    assert e.value.code == "cannot_cancel" and len(ops.calls) == n              # ما راح للسيرفر أصلاً
    with pytest.raises(launch.LaunchError):
        launch.cancel(exported.script, "active")                                # ما في طلب


# ───────────────────────── API ─────────────────────────
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_montage
    app = FastAPI()
    app.include_router(routes_montage.router)
    return TestClient(app)


def test_api_launch_flow(exported, ops):
    c = client()
    i = c.get("/api/studio/s1.json/launch/info").json()
    assert i["problems"] == [] and i["launch_token_set"] and i["vp_id"] == "VP-testp-1-v1"
    bad = c.post("/api/studio/s1.json/launch", json={"mode": "active"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "confirm_required"
    assert c.post("/api/studio/s1.json/launch", json={"mode": "nope", "confirm": True}).status_code == 409
    ops.responses = [(200, {"request_id": "req_1", "status": "received"})]
    ok = c.post("/api/studio/s1.json/launch", json={"mode": "active", "confirm": True})
    assert ok.status_code == 200 and ok.json()["label"] == "استُلم"
    dup = c.post("/api/studio/s1.json/launch", json={"mode": "active", "confirm": True})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "duplicate_request"
    ops.responses = [(200, {"status": "awaiting_approval", "ops_url": "https://ops.example.com/r/1"})]
    r = c.post("/api/studio/s1.json/launch/refresh", json={"mode": "active"})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
    assert c.get("/api/studio/s1.json/launch/info").json()["records"]["active"]["ops_url"].endswith("/r/1")
    ops.responses = [(200, {})]
    assert c.post("/api/studio/s1.json/launch/cancel", json={"mode": "active"}).json()["status"] == "cancelled"


def test_launch_token_endpoints_never_return_the_secret(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_crm
    import secrets_store
    store = {}
    monkeypatch.setattr(secrets_store, "set_secret", lambda n, v: store.__setitem__(n, v))
    monkeypatch.setattr(secrets_store, "get_secret", lambda n: store.get(n))
    monkeypatch.setattr(secrets_store, "delete_secret", lambda n: store.pop(n, None))
    monkeypatch.setattr(routes_crm, "_save_base_url", lambda u: None)
    app = FastAPI()
    app.include_router(routes_crm.router)
    c = TestClient(app)
    r = c.put("/api/crm/config", json={"base_url": "https://ops.example.com", "launch_token": "SECRET_XYZ"})
    assert r.status_code == 200 and r.json()["launch_token_set"] is True and "SECRET_XYZ" not in r.text
    assert store["crm_token_launch"] == "SECRET_XYZ" and "crm_token" not in store
    assert "SECRET_XYZ" not in c.get("/api/crm/status").text
    assert c.delete("/api/crm/launch-token").json()["launch_token_set"] is False
