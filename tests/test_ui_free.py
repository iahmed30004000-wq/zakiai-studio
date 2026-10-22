"""واجهة «المشروع الحر» (free.js + تكاملها مع mission/home/guide) — فحص ثابت + تشغيل بـ node + عقد مع الخادم الحقيقي. بلا متصفح."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_ui_globals import is_closed_scope, scripts_in_order  # noqa: E402

import free_project as fp  # noqa: E402
import timeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
AR_DIGITS = re.compile("[٠-٩۰-۹]")
NODE = shutil.which("node") is not None


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


FREE = _read("free.js")
MON = _read("freemontage.js")


# ───────── الصياغة والنطاق والترتيب ─────────
@pytest.mark.skipif(not NODE, reason="node مش موجود")
@pytest.mark.parametrize("name", ["free.js", "freemontage.js", "mission.js", "home.js", "guide.js", "app.js"])
def test_node_check(name):
    r = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True)
    assert r.returncode == 0, f"{name}: {r.stderr}"


def test_free_js_is_a_closed_scope_exposing_only_window_free_project():
    assert is_closed_scope(FREE)
    assert "window.FreeProject = {" in FREE
    for k in ("enter", "isFile", "hash", "structureOf", "addTab"):
        assert re.search(rf"^\s+{k}\b", FREE[FREE.index("window.FreeProject = {"):], re.M), k


def test_montage_tab_is_a_closed_scope_registered_through_add_tab():
    assert is_closed_scope(MON) and "FreeProject.addTab({ key: \"montage\"" in MON
    assert "window." not in MON.replace("window.FreeProject", "")                  # ما بيعرّف شي عام


def test_script_order_and_cache_version_are_consistent():
    idx = _read("index.html")
    names = scripts_in_order()
    assert "free.js" in names and names.index("free.js") < names.index("freemontage.js") < names.index("mission.js")
    versions = set(re.findall(r"\?v=(\d+)", idx)) | set(re.findall(r"\?v=(\d+)", _read("login.html")))
    assert len(versions) == 1, versions                                    # نفس الرقم بكل مكان
    assert re.search(r'<script src="/free\.js\?v=\d+"></script>', idx)


def test_home_and_mission_link_to_the_free_project():
    idx, home, mission, guide = _read("index.html"), _read("home.js"), _read("mission.js"), _read("guide.js")
    assert 'href="#/mission/new?free=1"' in idx and "مشروع حر" in idx
    assert "FreeProject.enter(" in mission and "free=1" in mission                  # تحويل + رابط «أو ابدأ مشروع حر»
    assert 's.mode === "free"' in home and "freeLink(" in home and "مشروع حر" in home
    assert 'mode === "free"' in guide and "free_project:" in guide and "free=1" in guide


def test_no_arabic_indic_digits_no_keys_and_no_raw_colours():
    pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})")
    assert not AR_DIGITS.search(FREE) and not pat.search(FREE) and not AR_DIGITS.search(MON) and not pat.search(MON)
    css = _read("style.css")
    block = css[css.index("المشروع الحر (free.js)"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", block), "ألوان مكتوبة بالـ CSS (لازم var(--vp-*))"


# ───────── الاتساق الداخلي ─────────
def test_every_data_act_has_a_click_handler_and_every_field_an_input_handler():
    acts = set(re.findall(r'data-act="([\w-]+)"', FREE))
    on_click = FREE[FREE.index("function onClick("):FREE.index("function onInput(")]
    handled = set(re.findall(r'case "([\w-]+)":', on_click))
    assert acts and acts <= handled, f"أزرار بلا معالج: {acts - handled}"
    fields = set(re.findall(r'data-f="([\w-]+)"', FREE))
    handlers = FREE[FREE.index("function onInput("):FREE.index("const hasFiles")]
    for f in fields:
        assert f'"{f}"' in handlers, f"حقل بلا معالج: {f}"


RISKY = re.compile(r"\$\{\s*(?!esc\()[\w.]+\.(title|voiceover|visual|text|path|clip|provider|message|file|id|key|product_name|name|msg)\s*\}")


def test_server_text_goes_through_esc_in_templates():
    html_lines = [ln for ln in FREE.splitlines() if "<" in ln]
    bad = [ln.strip() for ln in html_lines if RISKY.search(ln)]
    assert not bad, bad
    assert FREE.count("esc(") >= 25
    # سمات HTML اللي فيها نص من الخادم (مسار صورة/مقطع/معرّف) كلها بـ esc
    for attr in ("src", "poster", "data-path", "data-clip", "data-id", "value"):
        for m in re.finditer(rf'{attr}="\$\{{([^}}]*)\}}"', FREE):
            # v = قيمة ثابتة من قائمة جاهزة (خيارات حركة الصورة)، i/j/n = أرقام فهارس
            assert m.group(1).startswith(("esc(", "secStr(", "key")) or m.group(1) in ("i", "j", "n", "v"), (attr, m.group(1))


def test_endpoints_used_by_free_js_exist_on_the_server():
    from web import app as webapp
    server = {re.sub(r"\{[^}]+\}", "{}", p) for p in webapp.app.openapi()["paths"] if p.startswith("/api/")}
    used = set()
    src = re.sub(r"\$\{[^}]*\}", "{}", FREE + MON)                       # التعابير جوّا القوالب (ممكن فيها علامات اقتباس) بتصير {}
    for m in re.finditer(r"[`\"'](/api/[^`\"']+)[`\"']", src):
        used.add(m.group(1).split("?")[0])
    assert len(used) >= 10, used
    missing = {u for u in used if u not in server and u != "/api/scenes/template.xlsx"}
    assert not missing, missing
    assert "/api/scenes/template.xlsx" in server


# ───────── المحاكاة ─────────
def test_mock_board_is_a_valid_free_timeline_and_listed_as_free():
    b = json.loads(_read("mock/free_board.json"))
    tl = {"mode": "free", "scenes": b["scenes"], "length_ms": b["length_ms"]}
    res = timeline.validate(tl)
    assert res["ok"], res["errors"]
    assert sum(sh["end_ms"] - sh["start_ms"] for sc in b["scenes"] for sh in sc["shots"]) == b["length_ms"]
    assert b["readiness"]["no_media"] == [sh["id"] for sc in b["scenes"] for sh in sc["shots"]
                                          if not ((sh["image"] or {}).get("chosen") or (sh.get("motion") or {}).get("clip"))]
    listed = [s for s in json.loads(_read("mock/scripts.json")) if s.get("mode") == "free"]
    assert [s["file"] for s in listed] == [b["file"]] and listed[0]["scenes"] == len(b["scenes"])
    for sc in b["scenes"]:
        for sh in sc["shots"]:
            ch = (sh["image"] or {}).get("chosen")
            assert not ch or (STATIC / "mock" / ch).exists(), ch


def test_app_js_mock_handles_the_free_routes():
    app = _read("app.js")
    for k in ("mockFreeHook", "mockFreeBoard", "free\\/board", "free\\/(structure|import|media)", "/api/free/projects"):
        assert k in app, k


# ───────── تشغيل free.js بـ node: الدوال الصافية + عقد الحمولة مع الخادم الحقيقي ─────────
HARNESS = r"""
const fs = require("fs");
const listeners = {};
global.window = { addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); } };
global.document = { addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } };
global.matchMedia = () => ({ matches: false });
global.$ = () => null; global.$$ = () => [];
global.enc = encodeURIComponent;
global.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
global.toLatin = (s) => String(s);
global.MOCK = false;
global.soft = async () => ({ data: null, err: null });
global.errBox = () => "";
eval(fs.readFileSync(process.argv[1], "utf8"));
const F = window.FreeProject, U = F.util;
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
out.clock = [0, 999, 1500, 61000, 125000].map(U.clock);
out.secStr = [3000, 2500, 500, 60000].map(U.secStr);
out.parse = ["3", "2,5", " 4 ", "", "abc", "0"].map((v) => { const n = U.parseSec(v); return Number.isNaN(n) ? "NaN" : n; });
out.isFile = [F.isFile("free__20261022_0900__x.json"), F.isFile("VARA__ad_1.json"), F.isFile(""), F.isFile(null)];
out.hash = [F.hash("free__a b.json"), F.hash("free__a.json", "montage"), F.hash("free__a.json", "scenes")];
out.addTab = (() => { F.addTab({ key: "x", label: "س", mount() {} }); F.addTab({ key: "x", label: "تكرار", mount() {} }); F.addTab({ key: "", mount() {} }); F.addTab({ key: "y" }); return "ok"; })();
if (input.board) {
  const b = input.board;
  const state = { rev: b.rev, title: b.title, productFile: b.product_file, scenes: U.fromServer(b.scenes) };
  out.layout = U.layoutOf(state.scenes);
  if (input.edit) {
    state.scenes[0].voiceover = "كلام جديد";
    state.scenes[0].shots[0].dur_ms = 4500;
    state.scenes[0].shots[0].text = "نص شاشة";
    state.scenes.push(U.blankScene());
    state.scenes[1].shots.push(U.blankShot());
    state.scenes.splice(0, 0, state.scenes.splice(1, 1)[0]);              // ترتيب جديد: المشهد التاني أول
    state.title = "عنوان معدّل";
  }
  out.payload = F.structureOf(state);
}
console.log(JSON.stringify(out));
"""


def _node(board=None, edit=False, tmp=None):
    inp = Path(tmp) / "in.json"
    inp.write_text(json.dumps({"board": board, "edit": edit}, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "free.js"), str(inp)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node مش موجود")
def test_pure_helpers_in_node(tmp_path):
    o = _node(tmp=tmp_path)
    assert o["clock"] == ["0:00", "0:01", "0:02", "1:01", "2:05"]
    assert o["secStr"] == ["3", "2.5", "0.5", "60"]
    assert o["parse"] == [3, 2.5, 4, "NaN", "NaN", 0]
    assert o["isFile"] == [True, False, False, False]
    assert o["hash"] == ["#/mission/free__a%20b.json", "#/mission/free__a.json?tab=montage", "#/mission/free__a.json"]


def client():
    from web import routes_free, routes_studio
    app = FastAPI()
    app.include_router(routes_free.router)
    app.include_router(routes_studio.router)
    return TestClient(app)


@pytest.mark.skipif(not NODE, reason="node مش موجود")
def test_payload_built_by_the_ui_is_accepted_by_the_server_and_keeps_media(env, tmp_path):
    c = client()
    f = c.post("/api/free/projects", data={"title": "ع", "text": "أول\n\nتاني"}).json()["file"]
    png = tmp_path / "a.png"
    Image.new("RGB", (320, 480), (200, 30, 30)).save(png)
    sid = c.get(f"/api/studio/{f}/free/board").json()["scenes"][0]["shots"][0]["id"]
    assert c.post(f"/api/studio/{f}/shots/{sid}/upload", files={"file": ("a.png", png.read_bytes(), "image/png")}).status_code == 200
    board = c.get(f"/api/studio/{f}/free/board").json()
    # بلا تعديل: الحمولة نفسها بتنقبل وما بتغيّر شي (والصورة بتضل)
    same = _node(board, False, tmp_path)["payload"]
    r = c.put(f"/api/studio/{f}/free/structure", json=same)
    assert r.status_code == 200, r.text
    assert r.json()["scenes"][0]["shots"][0]["image"]["chosen"] and r.json()["length_ms"] == board["length_ms"]
    # مع تعديلات الواجهة: كلام، مدة، نص، مشهد جديد بلقطتين، ترتيب جديد، عنوان
    board = r.json()
    out = _node(board, True, tmp_path)
    r = c.put(f"/api/studio/{f}/free/structure", json=out["payload"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["title"] == "عنوان معدّل" and len(b["scenes"]) == 3
    assert b["scenes"][0]["voiceover"] == "تاني" and len(b["scenes"][0]["shots"]) == 2     # المشهد التاني صار أول وإله لقطة زيادة
    assert all(sh["id"] for sh in b["scenes"][0]["shots"])
    moved = b["scenes"][1]
    assert moved["voiceover"] == "كلام جديد" and moved["shots"][0]["text"] == "نص شاشة"
    assert moved["shots"][0]["end_ms"] - moved["shots"][0]["start_ms"] == 4500
    assert moved["shots"][0]["image"]["chosen"]                              # الصورة مشت مع لقطتها
    new = b["scenes"][2]
    assert new["key"] and len(new["shots"]) == 1 and new["shots"][0]["id"]
    assert b["length_ms"] == sum(sh["end_ms"] - sh["start_ms"] for sc in b["scenes"] for sh in sc["shots"])
    assert timeline.validate(timeline.load(Path(f).stem))["ok"]
    # الحمولة القديمة (rev قديم) بتنرفض بـ 409 بنص عربي بيعرفه الـ UI (كلمة «أحدث»)
    stale = c.put(f"/api/studio/{f}/free/structure", json=out["payload"])
    assert stale.status_code == 409 and "أحدث" in stale.json()["detail"]


# ───────── اليدوي جوّا المهمة الموجّهة (studio.js + production.js + index.html) ─────────
def test_guided_manual_ui_is_wired_to_existing_routes_and_markup():
    from web import app as webapp
    studio, prod, idx = _read("studio.js"), _read("production.js"), _read("index.html")
    server = {re.sub(r"\{[^}]+\}", "{}", p) for p in webapp.app.openapi()["paths"]}
    for ep in ("/api/scripts/manual", "/api/scripts/manual/from-voice", "/api/scripts/manual/result/{}", "/api/scripts/{}/approve-local",
               "/api/studio/{}/voice/upload", "/api/studio/{}/shots/{}/upload"):
        assert ep in server, ep
    for k in ("/api/scripts/manual", "/api/scripts/manual/from-voice", "/api/scripts/manual/result/", "approve-local"):
        assert k in studio, k
    assert "/voice/upload" in prod and "/shots/${enc(id)}/upload" in prod and "data-upshot" in prod and "data-upclip" in prod
    for el in ('id="manualPanel"', 'id="voiceStartPanel"', 'id="manText"', 'id="manFile"', 'id="manGo"', 'id="vsFile"', 'id="vsGo"'):
        assert el in idx, el
    for el in ("manGo", "vsGo", "manNote", "vsNote", "approveLocalBtn"):               # كل معرّف بيستعمله studio.js موجود بالصفحة أو بقالب الموافقة
        assert el in studio, el
    assert "needs_confirm" in studio and "confirm(" in studio                           # موافقة بتأكيد على مرحلتين
    assert not AR_DIGITS.search(studio) and not AR_DIGITS.search(prod)


# ───────── «شغل سريع» + أبواب «يدوي بلا تسلسل» بكل مرحلة ─────────
def _quick_keys() -> list[str]:
    body = FREE[FREE.index("const QUICK = {"):FREE.index("const QUICK_ROW")]
    return re.findall(r"^  (\w+): \{ ico:", body, re.M)


def test_quick_actions_are_defined_and_each_after_step_is_handled():
    keys = _quick_keys()
    assert keys == ["animate", "generate", "speak", "transcribe", "montage"], keys
    body = FREE[FREE.index("const QUICK = {"):FREE.index("const QUICK_ROW")]
    modes = set(re.findall(r'mode: "(\w+)"', body))
    assert modes <= {o for o in re.findall(r'^\s+\["(\w+)", "[^"]+", ', FREE[FREE.index("const START_OPTS"):FREE.index("const QUICK = {")], re.M)} | {"prompt"}, modes
    row = re.search(r"const QUICK_ROW = \[([^\]]*)\]", FREE).group(1)
    assert set(re.findall(r'"(\w+)"', row)) == set(keys)
    afters = set(re.findall(r'after: "(\w*)"', body)) - {""}
    assert afters == {"animate", "generate", "tts"}, afters
    run = FREE[FREE.index("async function runAfter("):FREE.index("async function fillMissing()")]
    assert 'a.kind === "tts"' in run and 'a.kind === "generate"' in run and "animate(sh)" in run and "genImage(sh, true)" in run
    # بتشتغل بس لمشروعها بالذات (ما بتنطلق على مشروع تاني لو فشل فتح الأول) وبتنمسح مع شاشة البداية
    assert "a.file === FS.file" in FREE and "FS.after = null;" in FREE[FREE.index("function renderStart("):FREE.index("async function startGo(")]
    # الصوت: الشغلة السريعة ما بتسأل تأكيد مرتين، بس العادية لسا بتسأل
    assert "!opts.quick && !confirm(" in FREE
    assert "quickHash," in FREE and "quick: Object.fromEntries(" in FREE
    assert "MAX_PROMPTS" in FREE and 'fd.append("text", prompts.map(' in FREE            # كل سطر وصف = مشهد بوصف صورة
    assert "download=" in FREE and "نزّل" in FREE                                         # الناتج بينزّل بزر تحت كل لقطة


def test_mission_doors_point_at_real_quick_actions_and_start_modes():
    mission = _read("mission.js")
    assert 'id="msManual"' in mission and "renderManual()" in mission and "const MANUAL_DOORS = {" in mission
    # الجدول قبل دليل المراحل (اختبار دليل المراحل بيعدّ example/why جواته)
    assert mission.index("const MANUAL_DOORS") < mission.index("const MISSION_GUIDE")
    table = mission[mission.index("const MANUAL_DOORS"):mission.index("/* دليل كل مرحلة")]
    stages = {int(n) for n in re.findall(r"^\s+(\d): \[", table, re.M)}
    assert stages == {3, 4, 5, 6, 7}, stages                                              # المراحل 1 و2 مش مقفولة، ما بدها باب
    for k in re.findall(r'quick: "(\w+)"', table):
        assert k in _quick_keys(), k
    starts = set(re.findall(r'^\s+\["(\w+)", "[^"]+", ', FREE[FREE.index("const START_OPTS"):FREE.index("const QUICK = {")], re.M))
    for m in re.findall(r'start: "(\w+)"', table):
        assert m in starts, m
    assert "يدوي بلا تسلسل" in mission and "window.FreeProject" in mission
    assert 'q.quick' in FREE and "q.start" in FREE                                        # شاشة البداية بتقرا quick و start من الرابط
    idx = _read("index.html")
    assert re.search(r'href="#/mission/new\?free=1">اشتغل يدوي بلا ترتيب', idx)           # باب من الرئيسية كمان


DOORS_HARNESS = r"""
const fs = require("fs");
global.window = { addEventListener() {} };
global.document = { addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } };
global.matchMedia = () => ({ matches: false });
global.$ = () => null; global.$$ = () => [];
global.enc = encodeURIComponent;
global.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
global.MOCK = false;
global.soft = async () => ({ data: null, err: null });
global.errBox = () => "";
eval(fs.readFileSync(process.argv[1], "utf8"));                                     // free.js ← window.FreeProject
const F = window.FreeProject;
const src = fs.readFileSync(process.argv[2], "utf8");
const doors = src.slice(src.indexOf("const MANUAL_DOORS"), src.indexOf("/* دليل كل مرحلة"));
const fn = src.slice(src.indexOf("function renderManual()"), src.indexOf("function renderBar()"));
const MS = { stage: 1 };
const host = { innerHTML: "" };
global.$ = (sel) => (sel === "#msManual" ? host : null);
eval(doors + fn + "; global.__r = (stage) => { MS.stage = stage; host.innerHTML = ''; renderManual(); return host.innerHTML; };");
const out = { hash: F.quickHash("animate"), keys: Object.keys(F.quick), names: Object.fromEntries(Object.entries(F.quick).map(([k, v]) => [k, v.name])), stages: {} };
for (let n = 1; n <= 7; n++) out.stages[n] = global.__r(n);
const keep = window.FreeProject;
window.FreeProject = undefined;
out.noFree = [3, 4, 5, 6, 7].map((n) => global.__r(n));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node مش موجود")
def test_doors_render_for_each_stage_in_node():
    r = subprocess.run(["node", "-e", DOORS_HARNESS, str(STATIC / "free.js"), str(STATIC / "mission.js")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["hash"] == "#/mission/new?free=1&quick=animate"
    assert o["keys"] == ["animate", "generate", "speak", "transcribe", "montage"]
    st = o["stages"]
    assert st["1"] == "" and st["2"] == ""
    assert 'href="#/mission/new?free=1&start=text"' in st["3"]
    assert "quick=speak" in st["4"] and "quick=transcribe" in st["4"]
    assert "quick=generate" in st["5"] and "start=images" in st["5"]
    assert "quick=animate" in st["6"] and o["names"]["animate"] in st["6"]
    assert "quick=montage" in st["7"] and o["names"]["montage"] in st["7"]
    assert all("يدوي بلا تسلسل" in st[n] for n in "34567")
    assert o["noFree"] == [""] * 5                                          # free.js ما انحمّل: ما في أبواب مكسورة


def test_quick_flows_run_on_the_real_server_routes(env, tmp_path):
    """نفس الحمولات اللي بتبعتها شاشة البداية: وصف صور (generate) وصور للتحريك (animate) + وصف الحركة على مسار التحريك."""
    from web import routes_free, routes_motion, routes_studio
    app = FastAPI()
    for mod in (routes_free, routes_studio, routes_motion):
        app.include_router(mod.router)
    c = TestClient(app)
    # ولّد صورة: كل سطر وصف = مشهد بوصف صورة وبلا كلام ولا وسائط
    prompts = ["زجاجة عطر سوداء على رخام", "يد امرأة بتحط الكريم"]
    made = c.post("/api/free/projects", data={"title": "ولّد صورة", "text": "\n\n".join(f"صورة: {p}" for p in prompts), "split_sentences": "false"})
    assert made.status_code == 200, made.text
    f = made.json()["file"]
    b = c.get(f"/api/studio/{f}/free/board").json()
    assert [sc["visual"] for sc in b["scenes"]] == prompts and all(not sc["voiceover"] for sc in b["scenes"])
    assert len(b["readiness"]["no_media"]) == 2 and all(len(sc["shots"]) == 1 for sc in b["scenes"])
    # حرّك صورة: صور مرفوعة بمشروع باسم الشغلة، بعدها وصف الحركة بيتحفظ على لقطتها
    made = c.post("/api/free/projects", data={"title": "حرّك صورة", "product_file": ""})
    f2 = made.json()["file"]
    png = tmp_path / "a.png"
    Image.new("RGB", (320, 480), (30, 30, 200)).save(png)
    r = c.post(f"/api/studio/{f2}/free/media", files=[("files", ("a.png", png.read_bytes(), "image/png"))])
    assert r.status_code == 200, r.text
    b2 = c.get(f"/api/studio/{f2}/free/board").json()
    sh = b2["scenes"][0]["shots"][0]
    assert (sh["image"] or {}).get("chosen") and not (sh.get("motion") or {}).get("clip")      # بالضبط شرط runAfter: صورة وبلا مقطع
    d = c.put(f"/api/studio/{f2}/shots/{sh['id']}/motion-desc", json={"desc": "الكاميرا بتقرّب ببطء"})
    assert d.status_code == 200, d.text
    assert timeline.load(Path(f2).stem)["scenes"][0]["shots"][0]["motion_desc"] == "الكاميرا بتقرّب ببطء"

