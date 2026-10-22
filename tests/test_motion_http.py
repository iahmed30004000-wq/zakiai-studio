"""صناديق النماذج (kind=http) بالتحريك + البديل التلقائي + سجل الإنتاج.
الخدمة الحقيقية (services/engine) بخلفية تجريبية على uvicorn بخيط على 127.0.0.1 — بدون كرت ولا Docker ولا إنترنت."""

from __future__ import annotations

import http.server
import json
import logging
import os
import shutil
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from a_helpers import env  # noqa: E402,F401  (fixture)
from test_studio_images import stage  # noqa: E402,F401  (fixture)
from test_studio_motion import lavfi, model, ready, tc_client  # noqa: E402,F401  (fixtures + مساعدين)

import config  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import production_log  # noqa: E402
import secrets_store  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
from services.engine.app import OOM_MESSAGE, Settings, create_app  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")

ALL = ("product", "realism", "faces", "camera_motion", "hand")
TOKEN = "tok-SECRET-9f3a1c77"


def silent(*_a, **_k):
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(motion, "HTTP_POLL_SEC", 0.05)


@pytest.fixture
def box(tmp_path):
    """بيشغّل صندوق حقيقي (خدمة محرك + uvicorn) بخيط. بيرجّع عنوانه."""
    import uvicorn
    running = []

    def start(token=None, name="ltx", **over):
        port = free_port()
        s = Settings(backend="fake", name=name, outputs=tmp_path / f"box_{name}_{port}", lock_dir=tmp_path / "locks",
                     token=token, lock_poll_sec=0.05, **over)
        srv = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning", access_log=False))
        th = threading.Thread(target=srv.run, daemon=True)
        th.start()
        end = time.time() + 15
        while not srv.started and time.time() < end:
            time.sleep(0.02)
        assert srv.started, "الصندوق ما قام"
        running.append((srv, th))
        return f"http://127.0.0.1:{port}"

    yield start
    for srv, th in running:
        srv.should_exit = True
        th.join(10)


@pytest.fixture
def mem_secrets():
    mem, prev = secrets_store.use_memory_backend()
    yield mem
    secrets_store.restore_backend(prev)


class Redirector:
    """سيرفر صغير بيرد 302 لعنوان خارجي على أي طلب — لنتأكد إن ما في تحويلات."""

    def __init__(self):
        outer = self
        self.hits: list[str] = []

        class H(http.server.BaseHTTPRequestHandler):
            def _go(self):
                outer.hits.append(f"{self.command} {self.path}")
                n = int(self.headers.get("Content-Length") or 0)
                while n > 0:                                         # لازم نقرا جسم الطلب كله قبل الرد، وإلا الاتصال بينقطع (RST) والعميل ما بيشوف الـ 302
                    n -= len(self.rfile.read(min(n, 65536)) or b"") or n
                self.send_response(302)
                self.send_header("Location", "http://example.com/steal")
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = do_DELETE = _go

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def redirector():
    r = Redirector()
    yield r
    r.close()


def http_model(url, name="صندوق", token_secret=None, strengths=ALL, **kw):
    h = {"url": url, "mode": "i2v"}
    if token_secret:
        h["token_secret"] = token_secret
    return {"name": name, "kind": "http", "max_sec": 6, "vram_gb": 4, "strengths": list(strengths), "speed_sec_per_sec": 30,
            "http": h, **kw}


def clip_ms(stem, cand):
    return motion.probe_duration(motion.abs_of(stem, cand["clip"])) * 1000


# ───────────────────────── قائمة السماح للعنوان ─────────────────────────
@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1:8101", "http://127.0.0.1:8101"),
    ("http://localhost:8101/", "http://localhost:8101"),
    ("http://[::1]:8101", "http://[::1]:8101"),
    ("http://127.5.5.5:80", "http://127.5.5.5:80"),
    ("http://ltx:8101", "http://ltx:8101"),
    ("  http://WAN:8102  ", "http://wan:8102"),
])
def test_allowlist_accepts_loopback_and_docker_names(url, expected):
    assert motion.validate_engine_url(url) == expected


@pytest.mark.parametrize("url", [
    "http://example.com:80",                      # خارجي
    "http://8.8.8.8:80",
    "http://10.0.0.5:8101",                       # شبكة داخلية مش loopback
    "http://192.168.1.5:8101",
    "http://ltx.internal:8101",                   # اسم بنقاط
    "https://127.0.0.1:8101",                     # https
    "ftp://127.0.0.1:21",
    "http://user:pw@127.0.0.1:8101",              # credentials
    "http://user@127.0.0.1:8101",
    "http://127.0.0.1:8101@evil.com:80",          # خدعة @
    "http://127.0.0.1:8101/?token=abc",           # query
    "http://127.0.0.1:8101#frag",
    "http://127.0.0.1:8101/jobs",                 # مسار
    "http://127.0.0.1",                           # بلا منفذ
    "http://127.0.0.1:",
    "http://127.0.0.1:99999",                     # منفذ خارج المدى
    "http://2130706433:8101",                     # IP رقمي
    "http://0x7f000001:8101",
    "http://127.1:8101",
    "http://1ltx:8101",                           # يبدأ برقم
    "http://127.0.0.1:8101\\@evil.com",
    "http://127.0.0.1:8101 /x",
    "http://:8101",
    "", "   ", None, 5,
])
def test_allowlist_rejects_everything_else(url):
    with pytest.raises(motion.MotionError):
        motion.validate_engine_url(url)


def test_registry_validates_http_models_and_never_stores_tokens(env):
    m = motion.upsert_model(http_model("http://127.0.0.1:8101", "LTX", token_secret="engine_ltx"))
    assert m["kind"] == "http" and m["http"] == {"url": "http://127.0.0.1:8101", "mode": "i2v", "steps": None, "guidance": None,
                                                 "token_secret": "engine_ltx", "model": None}
    assert m["command"] is None
    def general(name, model):
        return {**http_model("http://engine:8000", name), "http": {"url": "http://engine:8000", "mode": "i2v", "model": model}}
    gen = motion.upsert_model(general("عام", "Wan2.2-TI2V-5B-Diffusers"))                                           # الصندوق العام: اسم مجلد الأوزان
    assert gen["http"]["model"] == "Wan2.2-TI2V-5B-Diffusers"
    for bad in ("../x", "فيه مسافة", "a b", "x" * 130):
        with pytest.raises(motion.MotionError, match="اسم نموذج الصندوق"):
            motion.upsert_model(general("سيئ", bad))
    assert motion.upsert_model({"http": {"model": ""}}, gen["id"])["http"]["model"] is None                       # فاضي = صندوق بنموذج ثابت
    with pytest.raises(motion.MotionError):
        motion.upsert_model(http_model("http://evil.example.com:8101"))
    with pytest.raises(motion.MotionError):
        motion.upsert_model({**http_model("http://127.0.0.1:8101"), "http": {"url": "http://127.0.0.1:8101", "token": "x"}})   # حقل غير معروف
    with pytest.raises(motion.MotionError):
        motion.upsert_model({"name": "x", "max_sec": 3, "kind": "http"})                                            # بلا إعدادات
    with pytest.raises(motion.MotionError):
        motion.upsert_model(http_model("http://ltx:8101", token_secret="فيه مسافة"))
    with pytest.raises(motion.MotionError):
        motion.upsert_model({**http_model("http://ltx:8101"), "kind": "ftp"})
    upd = motion.upsert_model({"http": {"steps": "25", "guidance": 3.5, "mode": "t2v"}}, m["id"])        # تحديث جزئي بيحافظ على العنوان
    assert upd["http"]["url"] == "http://127.0.0.1:8101" and upd["http"]["steps"] == 25 and upd["http"]["guidance"] == 3.5 and upd["http"]["mode"] == "t2v"
    with pytest.raises(motion.MotionError):
        motion.upsert_model({"http": {"steps": 9999}}, m["id"])
    back = motion.upsert_model({"kind": "command", "command": lavfi()}, m["id"])                     # رجوع لأمر محلي
    assert back["kind"] == "command" and back["http"] is None
    assert "tok" not in (motion.registry_path().read_text(encoding="utf-8")).lower().replace("token_secret", "")


def test_rank_models_accepts_http_without_command_and_excludes_bad_urls():
    shot = {"id": "s1c1", "type": "close", "start_ms": 0, "end_ms": 3000, "motion_desc": "", "refs": {}}
    good = {"id": "a", "name": "صندوق", "kind": "http", "http": {"url": "http://127.0.0.1:8101", "mode": "i2v"}, "command": None,
            "max_sec": 5, "vram_gb": 0, "strengths": ["product"], "enabled": True, "lipsync": False, "speed_sec_per_sec": 30}
    no_url = {**good, "id": "b", "http": {"url": ""}}
    hand_edited = {**good, "id": "c", "http": {"url": "http://evil.example.com:80"}}
    cmd_missing = {**good, "id": "d", "kind": "command", "http": None}
    r = motion.rank_models(shot, [good, no_url, hand_edited, cmd_missing], vram_gb=8)
    assert [x["model"]["id"] for x in r["ranked"]] == ["a"]
    why = {x["model"]["id"]: x["reason"] for x in r["excluded"]}
    assert "عنوان الصندوق ناقص" in why["b"] and "غير مسموح" in why["c"] and "أمر" in why["d"]


# ───────────────────────── تشغيل كامل عبر http ─────────────────────────
def test_run_shot_over_http_produces_exact_duration_candidate_and_logs(ready, box, tmp_path):
    url = box()
    m = motion.upsert_model(http_model(url, "LTX صندوق"))
    sid = ready.ids[0]
    lines: list[str] = []
    r = motion.run_shot(ready.script, sid, log=lines.append)
    assert r["model"] == m["id"] and len(r["made"]) == 1 and r["fallbacks"] == 0
    sh = ims._shot(timeline.load("s1"), sid)[1]
    dur = sh["end_ms"] - sh["start_ms"]
    cand = sh["motion_candidates"][0]
    assert cand["model_id"] == m["id"] and cand["path"] == "http" and cand["duration_ms"] == dur and "fallback_from" not in cand
    assert abs(clip_ms("s1", cand) - dur) <= motion.DURATION_EPS_MS
    assert motion.validate_prompt(sh["motion_prompt"]) == []
    assert studio_state.state_of("s1", 9) == "awaiting_choice"
    assert any("[http]" in x for x in lines)
    out = motion.choose(ready.script, sid, cand["clip"])
    assert out["motion"]["duration_ms"] == dur and timeline.validate(timeline.load("s1"))["ok"]
    rec = production_log.recent(10, "motion")
    assert len(rec) == 1 and rec[0]["status"] == "ok" and rec[0]["path"] == "http" and rec[0]["kind"] == "motion"
    assert rec[0]["model_id"] == m["id"] and rec[0]["shot_id"] == sid and rec[0]["script_stem"] == "s1" and rec[0]["seconds"] > 0
    # الصندوق نضّف مهمته (DELETE بالنهاية): ما بقي فيديو ولا صورة بمجلد الخرج
    time.sleep(0.2)
    assert [p.name for d in tmp_path.glob("box_*") for p in d.iterdir()] == []


def test_http_model_params_reach_the_engine(ready, box, monkeypatch):
    url = box()
    mid = motion.upsert_model(http_model(url, "LTX"))["id"]
    motion.upsert_model({"http": {"steps": 7, "guidance": 2.5}}, mid)
    seen = {}
    real = motion._engine_call

    def spy(sess, method, base, path, **kw):
        if method == "POST" and path == "/jobs":
            seen["params"] = json.loads(kw["data"]["params"])
            seen["has_image"] = bool(kw.get("files"))
        return real(sess, method, base, path, **kw)

    monkeypatch.setattr(motion, "_engine_call", spy)
    motion.run_shot(ready.script, ready.ids[0], log=silent)
    p = seen["params"]
    assert p["mode"] == "i2v" and p["steps"] == 7 and p["guidance"] == 2.5 and 0.5 <= p["seconds"] <= 10 and seen["has_image"]
    assert p["width"] <= 2048 and p["height"] <= 2048
    assert "seconds" in p["prompt"] and not any(0x600 <= ord(c) <= 0x6ff for c in p["prompt"])            # الصناديق بتاخد برومبت إنجليزي


# ───────────────────────── التحويلات (redirect) ─────────────────────────
def test_redirects_are_never_followed(ready, redirector):
    motion.upsert_model(http_model(redirector.url, "محوِّل"))
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], log=silent)
    assert "التحويلات ممنوعة" in str(e.value)
    assert redirector.hits == ["POST /jobs"]                      # طلب واحد بس: ما لحقنا Location ولا بعتنا DELETE لعنوان تاني
    mid = motion.load_models()[0]["id"]
    p = motion.probe(mid)
    assert p["ok"] is False and "التحويلات" in p["reason"]


# ───────────────────────── التوكن ─────────────────────────
def test_token_travels_in_header_and_never_shows_in_logs_or_records(ready, box, mem_secrets, caplog, tmp_path):
    url = box(token=TOKEN)
    secrets_store.set_secret("engine_ltx", TOKEN)
    m = motion.upsert_model(http_model(url, "LTX", token_secret="engine_ltx"))
    caplog.set_level(logging.DEBUG)
    lines: list[str] = []
    motion.run_shot(ready.script, ready.ids[0], log=lines.append)           # لو التوكن ما وصل الصندوق كان 401
    blob = "\n".join(lines) + caplog.text + motion.registry_path().read_text(encoding="utf-8")
    blob += json.dumps(production_log.recent(50, "motion")) + json.dumps(production_log.stats())
    blob += json.dumps(timeline.load("s1"), ensure_ascii=False)
    blob += json.dumps(tc_client().get("/api/motion-models").json(), ensure_ascii=False)
    assert TOKEN not in blob
    # توكن غلط ← رسالة واضحة بدون ما تذكر القيمة، وبتنسجّل فشل
    secrets_store.set_secret("engine_ltx", "wrong-token-1234")
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], log=lines.append)
    assert "التوكن" in str(e.value) and TOKEN not in str(e.value) and "wrong-token-1234" not in str(e.value)
    fails = [r for r in production_log.recent(50, "motion") if r["status"] == "failed"]
    assert fails and all("wrong-token-1234" not in (r["error"] or "") for r in fails)
    p = motion.probe(m["id"])
    assert p["ok"] is False and "التوكن" in p["reason"]


def test_token_falls_back_to_env_var_when_secret_store_is_empty(ready, box, mem_secrets, monkeypatch):
    url = box(token=TOKEN)
    motion.upsert_model(http_model(url, "LTX", token_secret="engine_ltx"))
    mid = motion.load_models()[0]["id"]
    assert motion.probe(mid)["ok"] is False                       # لا مخزن ولا بيئة
    monkeypatch.setenv("ENGINE_TOKEN", TOKEN)                     # سيرفر لينكس: بلا Credential Manager
    assert motion.probe(mid)["ok"] is True


def test_token_api_stores_in_secret_store_and_reports_only_a_flag(env, mem_secrets, box):
    c = tc_client()
    mid = c.post("/api/motion-models", json=http_model("http://127.0.0.1:8101", "LTX")).json()["id"]
    assert c.put(f"/api/motion/models/{mid}/token", json={"token": "abc"}).status_code == 409      # ما في اسم مفتاح بعد
    assert c.put(f"/api/motion-models/{mid}", json={"http": {"token_secret": "engine_ltx"}}).status_code == 200
    r = c.put(f"/api/motion/models/{mid}/token", json={"token": TOKEN})
    assert r.status_code == 200 and r.json() == {"ok": True, "token_set": True}
    assert secrets_store.get_secret("engine_ltx") == TOKEN
    listing = c.get("/api/motion-models")
    assert TOKEN not in listing.text and listing.json()["models"][0]["http"]["token_set"] is True
    assert c.put(f"/api/motion/models/{mid}/token", json={"token": ""}).json()["token_set"] is False
    assert c.put("/api/motion/models/mm_999/token", json={"token": "x"}).status_code == 404
    assert c.put(f"/api/motion/models/{mid}/token", json={"token": 5}).status_code == 400


# ───────────────────────── الفحص (probe) ─────────────────────────
def test_probe_reports_health_dead_box_and_wrong_kind(env, box):
    url = box()
    a = motion.upsert_model(http_model(url, "حي"))
    dead = motion.upsert_model(http_model(f"http://127.0.0.1:{free_port()}", "ميت"))
    cmd = motion.upsert_model(model("أمر"))
    p = motion.probe(a["id"])
    assert p["ok"] is True and p["backend"] == "fake" and p["loaded"] is False and p["queued"] == 0 and p["running"] == 0
    d = motion.probe(dead["id"])
    assert d["ok"] is False and "واقف" in d["reason"] and "backend" not in d
    with pytest.raises(motion.MotionError):
        motion.probe(cmd["id"])
    with pytest.raises(motion.MotionError):
        motion.probe("mm_099")
    # الوضع مش مدعوم عند الصندوق
    motion.upsert_model({"http": {"mode": "t2v"}}, a["id"])
    assert motion.probe(a["id"])["ok"] is True                      # الصندوق التجريبي بيدعم الاتنين


def test_probe_api_endpoint(env, box):
    url = box()
    c = tc_client()
    mid = c.post("/api/motion-models", json=http_model(url, "حي")).json()["id"]
    r = c.post(f"/api/motion/models/{mid}/probe")
    assert r.status_code == 200 and r.json()["ok"] is True and set(r.json()) >= {"ok", "backend", "loaded", "queued", "running"}
    bad = c.post("/api/motion-models", json=http_model("http://127.0.0.1:8101", "x")).json()["id"]
    c.put(f"/api/motion-models/{bad}", json={"http": {"url": f"http://127.0.0.1:{free_port()}"}})
    assert c.post(f"/api/motion/models/{bad}/probe").json()["ok"] is False
    assert c.post("/api/motion/models/mm_999/probe").status_code == 404
    cm = c.post("/api/motion-models", json=model("أمر")).json()["id"]
    assert c.post(f"/api/motion/models/{cm}/probe").status_code == 409
    assert c.post("/api/motion-models", json=http_model("http://example.com:80", "خارجي")).status_code == 400
    assert c.get("/api/motion-models").json()["kinds"]["http"]


def test_probe_sees_busy_gpu(env, box, tmp_path):
    url = box()
    mid = motion.upsert_model(http_model(url, "حي"))["id"]
    import requests
    jid = requests.post(url + "/jobs", data={"params": json.dumps({"mode": "t2v", "seconds": 1, "sleep": 1.5})}, timeout=10).json()["id"]
    end = time.time() + 10
    while time.time() < end and not motion.probe(mid).get("running"):
        time.sleep(0.05)
    p = motion.probe(mid)
    assert p["ok"] and p["running"] == 1 and p["gpu_busy"] is True
    requests.delete(f"{url}/jobs/{jid}", timeout=10)


# ───────────────────────── البديل التلقائي ─────────────────────────
def test_auto_fallback_from_dead_box_to_command_model_and_logs_both(ready):
    dead = motion.upsert_model(http_model(f"http://127.0.0.1:{free_port()}", "صندوق ميت"))
    cmd = motion.upsert_model(model("أمر احتياطي", max_sec=6, strengths=()))
    sid = ready.ids[0]
    rk = motion.rank_models(ims._shot(timeline.load("s1"), sid)[1], motion.load_models(), vram_gb=8)
    assert rk["ranked"][0]["model"]["id"] == dead["id"]                      # الميت هو الأفضل بالترتيب
    lines: list[str] = []
    r = motion.run_shot(ready.script, sid, n=2, log=lines.append)
    assert r["made"] and r["model"] == cmd["id"] and r["fallbacks"] == 2
    sh = ims._shot(timeline.load("s1"), sid)[1]
    assert len(sh["motion_candidates"]) == 2
    for c in sh["motion_candidates"]:
        assert c["model_id"] == cmd["id"] and c["fallback_from"] == dead["id"] and c["path"] == "command"
        assert abs(clip_ms("s1", c) - (sh["end_ms"] - sh["start_ms"])) <= motion.DURATION_EPS_MS
    log = production_log.recent(20, "motion")
    assert [(x["model_id"], x["status"], x["path"]) for x in reversed(log)] == [(dead["id"], "failed", "http"), (cmd["id"], "ok", "command"),
                                                                               (cmd["id"], "ok", "command")]    # الميت اتجرّب مرة وحدة بس
    assert "واقف" in log[-1]["error"] and any("البديل" in x for x in lines)
    assert studio_state.state_of("s1", 9) == "awaiting_choice"
    motion.choose(ready.script, sid, sh["motion_candidates"][0]["clip"])


def test_fallback_on_timeout_oom_and_bad_output_across_three_attempts(ready, box, monkeypatch):
    url = box()
    m_oom = motion.upsert_model(http_model(url, "ذاكرة", strengths=ALL, speed_sec_per_sec=10))
    m_bad = motion.upsert_model(model("خرج مكسور", max_sec=6, strengths=("product", "realism", "faces", "camera_motion"),
                                      command=["python", "-c", "open(r'{out}','wb').write(b'garbage')"]))
    m_ok = motion.upsert_model(model("سليم", max_sec=6, strengths=("product",)))
    real = motion._engine_call

    def forged(sess, method, base, path, **kw):                    # الصندوق بيحكي «الذاكرة ما كفّت» مثل ما بيعمل بالحقيقة
        if method == "GET" and path.startswith("/jobs/") and not path.endswith("/result"):
            r = real(sess, method, base, path, **kw)
            real_json = r.json()

            class R:
                status_code = 200
                def json(self_inner):
                    return {**real_json, "status": "failed", "error": OOM_MESSAGE} if real_json["status"] in ("queued", "waiting_gpu", "running", "done") else real_json
                def close(self_inner): pass
            return R()
        return real(sess, method, base, path, **kw)

    monkeypatch.setattr(motion, "_engine_call", forged)
    r = motion.run_shot(ready.script, ready.ids[0], log=silent)
    assert r["model"] == m_ok["id"]
    log = list(reversed(production_log.recent(10, "motion")))
    assert [(x["model_id"], x["status"]) for x in log] == [(m_oom["id"], "failed"), (m_bad["id"], "failed"), (m_ok["id"], "ok")]
    assert OOM_MESSAGE in log[0]["error"] and "صالح" in log[1]["error"]
    cand = ims._shot(timeline.load("s1"), ready.ids[0])[1]["motion_candidates"][0]
    assert cand["fallback_from"] == m_oom["id"]


def test_http_timeout_is_technical_and_cancels_the_engine_job(ready, box, monkeypatch):
    url = box()
    monkeypatch.setattr(config, "MOTION_TIMEOUT_SEC", 1)
    motion.upsert_model(http_model(url, "بطيء"))
    # الخلفية التجريبية ما بتتأخر لحالها: بنأخّرها عبر sleep بالمعاملات
    real = motion._engine_call

    def slow(sess, method, base, path, **kw):
        if method == "POST" and path == "/jobs":
            p = json.loads(kw["data"]["params"])
            p["sleep"] = 30
            kw["data"] = {"params": json.dumps(p)}
        return real(sess, method, base, path, **kw)

    monkeypatch.setattr(motion, "_engine_call", slow)
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], log=silent)
    assert "المهلة" in str(e.value) and studio_state.state_of("s1", 9) == "failed"
    import requests
    end = time.time() + 10                                          # DELETE وصل: الصندوق خلّص (ملغاة) ورجع فاضي
    while time.time() < end:
        h = requests.get(url + "/health", timeout=5).json()
        if h["running"] == 0:
            break
        time.sleep(0.05)
    assert h["running"] == 0 and h["queued"] == 0
    assert production_log.recent(5, "motion")[0]["status"] == "failed"


def test_all_attempts_fail_gives_one_combined_arabic_message_and_station_failed(ready):
    a = motion.upsert_model(http_model(f"http://127.0.0.1:{free_port()}", "صندوق أ"))
    b = motion.upsert_model(model("أمر ب", max_sec=6, command=["python", "-c", "import sys; sys.exit(3)"], strengths=("product",)))
    c = motion.upsert_model(model("أمر ج", max_sec=6, command=["python", "-c", "pass", "{out}"], strengths=("realism",)))
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], log=silent)
    msg = str(e.value)
    assert msg.startswith("كل المحاولات فشلت") and "«صندوق أ»" in msg and "«أمر ب»" in msg and "«أمر ج»" in msg
    assert "واقف" in msg and "فشل (3)" in msg and "ما كتب" in msg
    assert studio_state.state_of("s1", 9) == "failed"
    assert len(production_log.recent(10, "motion")) == 3 and {x["status"] for x in production_log.recent(10, "motion")} == {"failed"}
    assert production_log.stats()["failed"] == 3
    assert not list((motion.clips_dir("s1")).glob("*_raw.mp4"))              # ما بقي ملفات نصف مكتملة
    assert not ims._shot(timeline.load("s1"), ready.ids[0])[1].get("motion_candidates")


def test_max_three_attempts_and_no_fallback_flag(ready):
    ms = [motion.upsert_model(model(f"عاطل{i}", max_sec=6, command=["python", "-c", "import sys; sys.exit(2)"],
                                    strengths=("product", "realism")[: 2 - (i % 2)])) for i in range(5)]
    with pytest.raises(motion.MotionError):
        motion.run_shot(ready.script, ready.ids[0], log=silent)
    assert len(production_log.recent(20, "motion")) == motion.MAX_ATTEMPTS == 3
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], ms[0]["id"], log=silent, fallback=False)
    assert "كل المحاولات" not in str(e.value) and len(production_log.recent(20, "motion")) == 4


def test_owner_and_state_errors_never_trigger_fallback(ready):
    good1 = motion.upsert_model(model("أ", max_sec=6))
    good2 = motion.upsert_model(model("ب", max_sec=6))
    # 1) موديل مش مناسب لقطة (اختيار صريح) ← خطأ مالك
    short = motion.upsert_model(model("قصير", max_sec=1))
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], short["id"], log=silent)
    assert "ما بيناسب" in str(e.value) and not isinstance(e.value, motion.TechnicalError)
    # 2) موديل غير موجود
    with pytest.raises(motion.MotionError):
        motion.run_shot(ready.script, ready.ids[0], "mm_999", log=silent)
    # 3) المحطة مقفولة (التطابق غير معتمد)
    studio_state.set_state("s1", 8, "awaiting_choice", "x")
    with pytest.raises(motion.MotionError):
        motion.run_shot(ready.script, ready.ids[0], log=silent)
    assert production_log.recent(10, "motion") == []                                 # لا محاولات ولا بدائل
    studio_state.set_state("s1", 8, "approved", "x")
    # 4) ما في صورة معتمدة للقطة
    tl = timeline.load("s1")
    ims._shot(tl, ready.ids[0])[1]["image"] = {}
    timeline.save("s1", tl)
    with pytest.raises(motion.MotionError) as e2:
        motion.run_shot(ready.script, ready.ids[0], log=silent)
    assert "ما في صورة معتمدة" in str(e2.value) and production_log.recent(10, "motion") == []
    assert good1 and good2


def test_lipsync_missing_audio_is_a_state_error_with_no_fallback(ready):
    lip = ["ffmpeg", "-y", "-i", "{video}", "-c", "copy", "{out}"]
    motion.upsert_model(model("شفاه 1", max_sec=6, lipsync_command=lip))
    motion.upsert_model(model("شفاه 2", max_sec=6, lipsync_command=lip))
    sid = next(s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"] if s["type"] == "medium")
    motion.set_desc(ready.script, sid, "تتكلم للكاميرا", talking=True)
    man = ready.env.lib / "voice" / "s1" / "voice.json"
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, sid, log=silent)                     # الملف الصوتي المدموج مش موجود فعلياً
    assert "صوت" in str(e.value) and not isinstance(e.value, motion.TechnicalError)
    log = production_log.recent(10, "motion")
    assert len(log) == 1 and log[0]["status"] == "failed" and man.exists()  # محاولة وحدة بس: ما جرّبنا الثاني


# ───────────────────────── سجل الإنتاج ─────────────────────────
def test_production_log_record_recent_stats(env):
    assert production_log.recent() == [] and production_log.stats()["total"] == 0
    a = production_log.record("motion", "ok", script_stem="s1", shot_id="s1c1", model_id="mm_001", model_name="LTX", path="http", seconds=12.345)
    b = production_log.record("motion", "failed", script_stem="s1", shot_id="s1c1", model_id="mm_002", model_name="Wan", path="command",
                              seconds=3, error="خطأ " + "ط" * 500)
    c = production_log.record("voice", "ok", model_id="el", model_name="ElevenLabs", path="api", seconds=2)
    d = production_log.record("image", "failed", model_id="gpt", path="extension", error="Authorization: Bearer abc123 token=zzz")
    assert a < b < c < d
    rec = production_log.recent(10)
    assert [r["id"] for r in rec] == [d, c, b, a]                              # الأحدث أول
    assert [r["id"] for r in production_log.recent(2)] == [d, c]
    assert [r["id"] for r in production_log.recent(10, "motion")] == [b, a]
    assert rec[3]["seconds"] == 12.35 and set(rec[0]) == {"id", "at", "kind", "script_stem", "shot_id", "model_id", "model_name", "path", "status", "seconds", "error", "cost_usd", "score"}
    assert len(rec[2]["error"]) == 300 and rec[2]["error"].startswith("خطأ")
    assert "abc123" not in rec[0]["error"] and "zzz" not in rec[0]["error"]    # ما بنخزّن شي بيشبه التوكن
    st = production_log.stats()
    assert (st["total"], st["ok"], st["failed"]) == (4, 2, 2)
    assert st["by_kind"]["motion"] == {"ok": 1, "failed": 1} and st["by_path"]["http"] == {"ok": 1, "failed": 0}
    by = {m["model_id"]: m for m in st["by_model"]}
    assert by["mm_001"]["avg_seconds"] == 12.3 and by["mm_002"]["failed"] == 1 and by["mm_002"]["avg_seconds"] is None
    assert production_log.stats("motion")["total"] == 2
    for bad in (dict(kind="nope", status="ok"), dict(kind="motion", status="maybe"), dict(kind="motion", status="ok", path="ftp")):
        with pytest.raises(ValueError):
            production_log.record(**bad)
    with pytest.raises(ValueError):
        production_log.recent(5, "nope")


def test_production_log_never_breaks_production_when_db_is_unwritable(env, monkeypatch):
    db = production_log.db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    db.mkdir()                                                            # مجلد مكان الملف = فتح قاعدة البيانات بيفشل
    assert production_log.record("motion", "ok", model_id="x") is None
    assert production_log.recent() == [] or isinstance(production_log.recent(), list)
    assert production_log.stats()["total"] == 0


def test_production_log_api(env):
    production_log.record("motion", "ok", model_id="mm_001", model_name="A", path="http", seconds=1)
    production_log.record("voice", "failed", model_id="el", path="api", error="x")
    c = tc_client()
    r = c.get("/api/production-log").json()
    assert len(r["items"]) == 2 and r["stats"]["total"] == 2
    assert [i["kind"] for i in c.get("/api/production-log?kind=motion").json()["items"]] == ["motion"]
    assert len(c.get("/api/production-log?limit=1").json()["items"]) == 1
    assert c.get("/api/production-log?kind=nope").status_code == 400
    assert c.get("/api/production-log?limit=0").status_code == 400
    assert c.get("/api/production-log?limit=9999").status_code == 400
    con = sqlite3.connect(production_log.db_path())
    assert con.execute("select count(*) from attempts").fetchone()[0] == 2
    con.close()
