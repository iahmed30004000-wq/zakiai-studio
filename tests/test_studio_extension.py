"""إضافة المتصفح (المحطة ٧ — المسار الثاني): الإيقاع، شروط الوقوف، الجسر مع الاستوديو، وقيود البنية."""

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_images as ti  # noqa: E402
from test_studio_images import stage  # noqa: E402,F401

import ext_bridge  # noqa: E402
import image_studio as ims  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node غير متوفر")


def node(code: str):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8", dir=str(EXT)) as f:
        f.write(code)
        name = f.name
    try:
        r = subprocess.run([NODE, name], capture_output=True, encoding="utf-8", cwd=str(EXT), timeout=60)
    finally:
        os.unlink(name)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ───────────────────────── الإيقاع (pace.js) ─────────────────────────
PRELUDE = """
const P = require('./lib/pace.js');
let seed = 12345; const rng = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
"""


@needs_node
def test_natural_typing_has_variable_delays_punctuation_pauses_and_hesitations():
    out = node(PRELUDE + """
const text = 'لقطة قريبة على العبوة، بإضاءة هادئة. ' .repeat(4);
const plan = P.typingPlan(text, 'natural', rng);
const d = plan.map(p => p.delay);
const punct = plan.filter(p => '،.'.includes(p.ch)).map(p => p.delay);
const plain = plan.filter(p => /[\\u0621-\\u064a]/.test(p.ch)).map(p => p.delay);
console.log(JSON.stringify({n: plan.length, chars: [...text].length, min: Math.min(...d), max: Math.max(...d),
  distinct: new Set(d).size, avgPunct: punct.reduce((a,b)=>a+b,0)/punct.length, avgPlain: plain.reduce((a,b)=>a+b,0)/plain.length,
  total: P.planDurationMs(plan), hes: d.filter(x => x > 400).length}));
""")
    assert out["n"] == out["chars"] and out["min"] >= 45 and out["distinct"] > 30      # فواصل متغيّرة
    assert out["avgPunct"] > out["avgPlain"] + 150                                      # وقفة عند الترقيم
    assert out["hes"] >= 3                                                              # ترددات أحياناً
    assert 5000 < out["total"] < 60000                                                  # مدة إنسانية معقولة


@needs_node
def test_fast_is_faster_and_max_pastes_whole_text_in_one_step():
    out = node(PRELUDE + """
const t = 'كلمات كتير للاختبار '.repeat(5);
console.log(JSON.stringify({nat: P.planDurationMs(P.typingPlan(t,'natural',rng)), fast: P.planDurationMs(P.typingPlan(t,'fast',rng)),
  max: P.typingPlan(t,'max',rng), t}));
""")
    assert out["fast"] < out["nat"] / 3
    assert len(out["max"]) == 1 and out["max"][0]["paste"] == out["t"] and out["max"][0]["delay"] == 0


@needs_node
def test_waits_scale_by_mode_and_unknown_mode_throws():
    out = node(PRELUDE + """
const w = (m,k) => Array.from({length: 200}, () => P.wait(m,k,rng));
const r = (a) => [Math.min(...a), Math.max(...a)];
let threw = false; try { P.typingPlan('x','warp'); } catch (e) { threw = true; }
console.log(JSON.stringify({nat: r(w('natural','afterSubmit')), fast: r(w('fast','afterSubmit')), max: r(w('max','afterSubmit')), threw}));
""")
    assert 20000 <= out["nat"][0] and out["nat"][1] <= 60000
    assert 10000 <= out["fast"][0] and out["fast"][1] <= 20000
    assert out["max"][1] <= 4000 and out["threw"] is True


# ───────────────────────── شروط الوقوف (detect.js) ─────────────────────────
CASES = [
    ({"text": "please verify you are human", "has": {"composer": True}}, "verification"),
    ({"text": "hello", "has": {"captchaFrame": True, "composer": True}}, "verification"),
    ({"text": "Checking your browser before accessing", "has": {"composer": False}}, "verification"),
    ({"text": "تحقق من أنك لست روبوت", "has": {"composer": True}}, "verification"),
    ({"text": "We detected unusual activity from your account", "has": {"composer": True}}, "unusual_activity"),
    ({"text": "لاحظنا نشاط غير عادي", "has": {"composer": True}}, "unusual_activity"),
    ({"text": "You've reached your usage limit. Try again later", "has": {"composer": True}}, "limit"),
    ({"text": "وصلت إلى الحد اليومي", "has": {"composer": True}}, "limit"),
    ({"text": "Too many requests", "has": {"composer": True}}, "limit"),
    ({"text": "I can't create that image because of content policy", "has": {"composer": True}}, "refused"),
    ({"text": "Sign in to continue", "has": {"composer": False}}, "login_required"),
    ({"text": "welcome", "has": {"passwordField": True, "composer": False}}, "login_required"),
    ({"text": "تسجيل الدخول", "has": {"loginForm": True}}, "login_required"),
    ({"text": "ok", "host": "evil.example.com", "expectedHosts": ["gemini.google.com"], "has": {"composer": True}}, "unknown_page"),
    ({"text": "ok", "has": {"composer": False}, "waitedComposerMs": 25000, "composerTimeoutMs": 20000}, "unknown_page"),
]


@needs_node
def test_every_stop_condition_stops_with_a_classified_arabic_reason():
    res = node("const D=require('./lib/detect.js'); const cases=" + json.dumps(CASES) +
               ";console.log(JSON.stringify(cases.map(([s])=>D.decideStop(s))))")
    for (snap, code), r in zip(CASES, res):
        assert r["stop"] is True and r["code"] == code, (snap, r)
        assert r["reason"] and any("؀" <= ch <= "ۿ" for ch in r["reason"])


@needs_node
def test_normal_pages_do_not_stop_and_pace_mode_never_changes_stop_rules():
    ok = [{"text": "Gemini — create an image of a cat", "host": "gemini.google.com", "expectedHosts": ["gemini.google.com"], "has": {"composer": True}},
          {"text": "", "has": {"composer": True}},
          {"text": "بانتظار صندوق الكتابة", "has": {"composer": False}, "waitedComposerMs": 3000, "composerTimeoutMs": 20000}]
    res = node("const D=require('./lib/detect.js'); const c=" + json.dumps(ok) + ";console.log(JSON.stringify(c.map(s=>D.decideStop(s))))")
    assert all(r == {"stop": False} for r in res)
    # detect.js ما بيعرف شي عن الأوضاع — نفس القواعد بكل سرعة
    assert "mode" not in (EXT / "lib" / "detect.js").read_text(encoding="utf-8").lower().replace("model", "")


# ───────────────────────── قيود بنية الإضافة ─────────────────────────
SITE_HOSTS = ("gemini.google.com", "chatgpt.com", "aistudio.google.com", "flow.google.com", "elevenlabs.io", "flowmusic.app", "www.flowmusic.app")


def test_manifest_is_mv3_with_minimal_permissions_and_only_the_needed_hosts():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3 and m["version"] == "0.4.0"
    # alarms للفحص اليومي، وdownloads+offscreen (v0.3) لحفظ نتيجة «التجربة السريعة» بمجلد التنزيلات (راجع test_ext_quick)
    assert set(m["permissions"]) == {"storage", "notifications", "alarms", "downloads", "offscreen"}
    for banned in ("tabs", "cookies", "webRequest", "webNavigation", "history", "scripting", "debugger", "<all_urls>",
                   "activeTab", "declarativeNetRequest", "management", "nativeMessaging", "identity", "clipboardRead"):
        assert banned not in m["permissions"] and banned not in m["host_permissions"]
    allowed = ("http://localhost:8000/", "http://127.0.0.1:8000/") + tuple(f"https://{h}/" for h in SITE_HOSTS)
    assert all(h.startswith(allowed) for h in m["host_permissions"])
    assert set(m["host_permissions"]) == {f"{u}*" for u in allowed}
    assert not any(h.startswith(("http://*", "https://*", "*")) for h in m["host_permissions"])   # بلا wildcard نطاقات
    assert "optional_permissions" not in m and "externally_connectable" not in m
    cs = m["content_scripts"]
    assert len(cs) == 1 and set(cs[0]["matches"]) == {f"https://{h}/*" for h in SITE_HOSTS}
    assert not cs[0].get("all_frames")
    for f in [m["background"]["service_worker"], m["action"]["default_popup"], m["options_ui"]["page"], *cs[0]["js"], *m["icons"].values()]:
        assert (EXT / f).exists(), f
    assert cs[0]["js"] == ["lib/pace.js", "lib/detect.js", "lib/adapters.js", "lib/engine.js", "content.js"]


def test_extension_never_reads_credentials_and_never_opens_a_second_tab():
    files = {p.name: p.read_text(encoding="utf-8") for p in list(EXT.glob("*.js")) + list(EXT.glob("lib/*.js"))}
    for name, src in files.items():
        if name in ("detect.js", "adapters.js"):
            continue                                           # هون بس بنكشف وجود حقل كلمة السر، بلا قراءة قيمته
        assert "password" not in src.lower() or name in ("popup.js", "options.js"), name
    for name in ("detect.js", "adapters.js"):
        src = files[name]
        assert not any(bad in src for bad in ("passwordField.value", '[type="password"]").value', "type=\"password\"]').value"))
    assert "document.cookie" not in "".join(files.values()) and "localStorage" not in files["content.js"]
    bg = files["background.js"]
    assert bg.count("chrome.tabs.create") == 1                   # تبويب واحد فقط (ensureTab)
    assert "if (RUN.tabClosed) throw" in bg                      # وما بيفتح تاني لو الأول اتسكّر أثناء الشغل
    assert bg.count("loop();") == 2                              # loop بيبدأ بس من start وresume (ضغطة المالك)
    assert "setInterval(() => loop" not in bg
    # alarms مسموحة بس للفحص الذاتي اليومي: المنبّه ما بيبدأ توليد
    assert "chrome.alarms" in bg and "autoSelftest" in bg


def test_stop_conditions_are_checked_at_every_step_and_never_bypassed():
    c = (EXT / "content.js").read_text(encoding="utf-8")
    eng = (EXT / "lib" / "engine.js").read_text(encoding="utf-8")
    for step in ("precheck", "generating", "afterSubmit"):
        assert f'"{step}"' in eng, step
    assert "step${i}" in eng or "`step${i}:" in eng
    assert eng.count("haltFrom(") >= 5 and "env.check(0)" in eng and "click()" in c
    assert "VPDetect.decideStop" in c
    for evasion in ("navigator.webdriver", "userAgent", "canvas.toDataURL", "solveCaptcha", "grecaptcha", "2captcha"):
        assert evasion not in c and evasion not in eng and evasion not in (EXT / "background.js").read_text(encoding="utf-8"), evasion
    assert "resume" in (EXT / "background.js").read_text(encoding="utf-8")


def test_options_only_accepts_localhost_studio_urls():
    o = (EXT / "options.js").read_text(encoding="utf-8")
    assert "localhost|127" in o and "http://" in o


# ───────────────────────── الجسر: التوكن ─────────────────────────
@pytest.fixture
def bridge(stage, monkeypatch, tmp_path):
    import secrets_store
    store = {}
    monkeypatch.setattr(secrets_store, "get_secret", lambda n: store.get(n))
    monkeypatch.setattr(secrets_store, "set_secret", lambda n, v: store.__setitem__(n, v))
    stage.store = store
    return stage


def client(host=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_ext
    app = FastAPI()
    app.include_router(routes_ext.router)
    return TestClient(app, client=(host, 5000)) if host else TestClient(app)


def png(size=(512, 768), color=(30, 90, 160)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


def test_token_is_generated_once_kept_in_the_secret_store_and_never_written_to_files(bridge):
    t = ext_bridge.token()
    assert len(t) >= 24 and ext_bridge.token() == t and bridge.store["studio_ext_token"] == t
    assert ext_bridge.verify(t) and not ext_bridge.verify("nope") and not ext_bridge.verify(None) and not ext_bridge.verify("")
    for f in Path(bridge.env.root).rglob("*"):
        if f.is_file() and f.suffix in (".json", ".jsonl", ".txt", ".log"):
            assert t not in f.read_text(encoding="utf-8", errors="ignore"), f
    t2 = ext_bridge.rotate_token()
    assert t2 != t and not ext_bridge.verify(t)


def test_extension_endpoints_reject_missing_or_wrong_token(bridge):
    c = client()
    for m, u in (("get", "/api/studio/s1.json/ext/queue"), ("get", "/api/studio/s1.json/ext/control"),
                 ("get", "/api/studio/s1.json/ext/ref/s1c1/0"), ("post", "/api/studio/s1.json/ext/log"),
                 ("post", "/api/studio/s1.json/ext/stop"), ("post", "/api/studio/s1.json/ext/result")):
        r = getattr(c, m)(u)
        assert r.status_code == 401, u
        r2 = getattr(c, m)(u, headers={"X-VP-Ext-Token": "wrong"})
        assert r2.status_code == 401, u


def test_pairing_token_is_shown_only_to_the_same_machine(bridge):
    assert client().get("/api/ext/token").status_code == 200
    assert client("8.8.8.8").get("/api/ext/token").status_code == 403
    assert client("8.8.8.8").post("/api/ext/token/rotate").status_code == 403


# ───────────────────────── الطابور والمراجع ─────────────────────────
def H(bridge):
    return {"X-VP-Ext-Token": ext_bridge.token()}


def test_queue_lists_shots_missing_candidates_in_order_with_prompts_and_refs(bridge):
    c = client()
    q = c.get("/api/studio/s1.json/ext/queue", headers=H(bridge)).json()["queue"]
    tl = timeline.load("s1")
    ids = [s["id"] for sc in tl["scenes"] for s in sc["shots"]]
    assert [i["shot_id"] for i in q] == ids
    first = q[0]
    assert first["want"] == 2 and first["prompt"] and any(r["name"] == "front.png" for r in first["refs"])
    assert c.get("/api/studio/s1.json/ext/ref/s1c1/0", headers=H(bridge)).status_code == 200
    assert c.get("/api/studio/s1.json/ext/ref/s1c1/9", headers=H(bridge)).status_code == 409


def test_queue_needs_approved_prompts_and_skips_shots_that_have_enough_options(bridge):
    c = client()
    ims_tl = timeline.load("s1")
    sh = ims_tl["scenes"][0]["shots"][0]
    sh["image"] = {"candidates": [{"path": "img/a.png"}, {"path": "img/b.png"}], "chosen": None}
    timeline.save("s1", ims_tl)
    q = c.get("/api/studio/s1.json/ext/queue", headers=H(bridge)).json()["queue"]
    assert sh["id"] not in [i["shot_id"] for i in q]
    studio_state.set_state("s1", 6, "awaiting_choice", "x")
    assert c.get("/api/studio/s1.json/ext/queue", headers=H(bridge)).status_code == 409


# ───────────────────────── استقبال النتائج ─────────────────────────
def post_result(c, bridge, shot="s1c1", data=None, site="gemini"):
    return c.post("/api/studio/s1.json/ext/result", headers=H(bridge), data={"shot_id": shot, "site": site},
                  files={"file": ("x.png", data if data is not None else png(), "image/png")})


def test_result_becomes_a_candidate_marked_extension_and_station_7_runs(bridge):
    c = client()
    r = post_result(c, bridge)
    assert r.status_code == 200 and r.json()["size"] == [512, 768]
    sh = ims._shot(timeline.load("s1"), "s1c1")[1]
    cand = sh["image"]["candidates"][0]
    assert cand["provider"] == "extension:gemini" and cand["path_used"] == "extension"
    assert ims.abs_of("s1", cand["path"]) and ":\\" not in cand["path"]
    assert studio_state.state_of("s1", 7) == "running"
    assert timeline.validate(timeline.load("s1"))["ok"]
    # ما بتنحسب ضمن حد نداءات الـAPI
    assert ims.budget("s1")["used"] == 0
    # واختيارها بيمشي بنفس مسار الـAPI (قص/تكبير)
    ch = ims.choose(bridge.script, "s1c1", cand["path"])
    assert ch["image"]["upscaled"] and ch["image"]["chosen"]


def test_bad_uploads_are_rejected_with_arabic_reasons(bridge):
    c = client()
    assert post_result(c, bridge, data=b"not an image").status_code == 409
    tiny = post_result(c, bridge, data=png((120, 120)))
    assert tiny.status_code == 409 and "صغيرة" in tiny.json()["detail"]
    assert post_result(c, bridge, site="bing").status_code == 409
    assert post_result(c, bridge, shot="s9c9").status_code in (404, 409)
    assert post_result(c, bridge, data=b"").status_code == 409
    assert ims._shot(timeline.load("s1"), "s1c1")[1].get("image", {}).get("candidates", []) == []


def test_finishing_the_queue_hands_the_choice_back_to_the_owner(bridge):
    c = client()
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    last = None
    for sid in ids:
        for _ in range(2):
            last = post_result(c, bridge, shot=sid).json()
    assert last["done"] is True
    assert studio_state.state_of("s1", 7) == "awaiting_choice"
    assert ext_bridge.control("s1")["command"] == "idle"
    assert c.get("/api/studio/s1.json/ext/queue", headers=H(bridge)).json()["queue"] == []


# ───────────────────────── الوقوف والتحكم والسجل ─────────────────────────
def test_stop_saves_position_and_reason_and_never_auto_resumes(bridge):
    c = client()
    c.post("/api/studio/s1.json/ext/control", json={"command": "run", "mode": "natural"})
    r = c.post("/api/studio/s1.json/ext/stop", headers=H(bridge),
               json={"code": "verification", "reason": "ظهر تحقق", "position": {"shot_id": "s1c3", "step": "generating"}})
    assert r.status_code == 200
    ctl = ext_bridge.control("s1")
    assert ctl["command"] == "stop" and ctl["stop_code"] == "verification" and ctl["position"]["shot_id"] == "s1c3"
    got = c.get("/api/studio/s1.json/ext/control", headers=H(bridge)).json()
    assert got["command"] == "stop"                                     # الإضافة بتقرا «stop» — ما بتكمّل لحالها
    log = ext_bridge.tail("s1")
    assert log[-1]["step"] == "stop" and "verification" in log[-1]["msg"] and log[-1]["shot"] == "s1c3"
    # الاستئناف بضغطة المالك بس، وبيمسح سبب الوقوف
    resumed = c.post("/api/studio/s1.json/ext/control", json={"command": "run"}).json()
    assert resumed["command"] == "run" and resumed["stop_code"] is None


def test_control_validation_warnings_and_modes(bridge):
    c = client()
    assert c.post("/api/studio/s1.json/ext/control", json={"mode": "warp"}).status_code == 409
    assert c.post("/api/studio/s1.json/ext/control", json={"site": "bing"}).status_code == 409
    assert c.post("/api/studio/s1.json/ext/control", json={"command": "explode"}).status_code == 409
    assert c.post("/api/studio/s1.json/ext/control", json={"mode": "natural"}).json()["warning"] == ""
    for m in ("fast", "max"):
        w = c.post("/api/studio/s1.json/ext/control", json={"mode": m}).json()["warning"]
        assert "احتمال" in w and ("الكشف" in w or "يلاحظ" in w)
    st = c.get("/api/studio/s1.json/ext/status").json()
    assert st["queue"] > 0 and st["next"] == "s1c1" and st["mode_warning"] and set(st["modes"]) == {"natural", "fast", "max"}


def test_log_is_bounded_truncated_and_records_each_step(bridge):
    c = client()
    for i in range(3):
        c.post("/api/studio/s1.json/ext/log", headers=H(bridge), json={"step": "type", "msg": "x" * 900, "shot": "s1c1"})
    rows = ext_bridge.tail("s1", 10)
    assert len(rows) == 3 and all(len(r["msg"]) <= 300 and r["step"] == "type" for r in rows)
    p = ext_bridge._log_path("s1")
    p.write_text("\n".join(json.dumps({"at": "x", "step": "s", "level": "info", "shot": "", "msg": str(i)})
                            for i in range(ext_bridge.MAX_LOG_LINES + 50)) + "\n", encoding="utf-8")
    ext_bridge.append_log("s1", {"step": "z", "msg": "last"})
    assert len(p.read_text(encoding="utf-8").splitlines()) <= ext_bridge.MAX_LOG_LINES
    assert ext_bridge.tail("s1", 1)[0]["msg"] == "last"
