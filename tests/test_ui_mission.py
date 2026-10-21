"""فحص ثابت لمسار «المهمة» (mission.js) وتعديلات studio.js / production.js — بدون متصفح ولا سيرفر.
المرجع: ui_contract.md (جدول المراحل السبعة، ودور M)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
AR_DIGITS = re.compile("[٠-٩۰-۹]")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ───────── الصياغة ─────────
@pytest.mark.skipif(shutil.which("node") is None, reason="node مش موجود")
@pytest.mark.parametrize("name", ["mission.js", "studio.js", "production.js"])
def test_node_check(name):
    r = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True)
    assert r.returncode == 0, f"{name}: {r.stderr}"


# ───────── جدول المحطات ← المراحل (حسب العقد) ─────────
EXPECTED_STAGE = {1: 1, 2: 3, 3: 4, 4: 4, 5: 4, 6: 5, 7: 5, 8: 5, 9: 6, 10: 7, 11: 7}


def test_station_to_stage_table_matches_contract():
    src = _read("mission.js")
    m = re.search(r"const STATION_STAGE = \{([^}]*)\}", src)
    assert m, "جدول STATION_STAGE ناقص"
    table = {int(k): int(v) for k, v in re.findall(r"(\d+)\s*:\s*(\d+)", m.group(1))}
    assert table == EXPECTED_STAGE
    # كل محطة من الإحدى عشر (studio_state.STATIONS) إلها مرحلة
    import studio_state
    assert set(studio_state.STATIONS) == set(table)


@pytest.mark.skipif(shutil.which("node") is None, reason="node مش موجود")
def test_station_to_stage_runtime_and_hash():
    """نشغّل mission.js بـ node مع بيئة متصفح وهمية صغيرة ونفحص Mission API فعلياً."""
    harness = r"""
const fs = require("fs");
const listeners = {};
global.window = { addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); } };
global.document = { addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } };
global.location = { hash: "" };
global.VIEWS = {};
global.$ = () => null; global.$$ = () => [];
global.enc = encodeURIComponent;
global.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
eval(fs.readFileSync(process.argv[1], "utf8"));
const M = window.Mission;
const out = {
  stages: M.stages.map((s) => [s.n, s.name, s.stations]),
  sos: Object.fromEntries([1,2,3,4,5,6,7,8,9,10,11].map((n) => [n, M.stageOfStation(n)])),
  h1: M.hash("a b.json", 5, { s: 7 }),
  h2: M.hash(null, 1, { product: "vara.json" }),
  h3: M.hash("x.json", 99),
  legacy5: M.fromStudioQuery({ step: "5", script: "x.json" }),
  legacy1: M.fromStudioQuery({ step: "1", product: "p.json" }),
  hasView: typeof VIEWS.mission.enter,
};
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", harness, str(STATIC / "mission.js")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert {int(k): v for k, v in d["sos"].items()} == EXPECTED_STAGE
    assert [s[0] for s in d["stages"]] == [1, 2, 3, 4, 5, 6, 7]
    assert [s[1] for s in d["stages"]] == ["المنتج", "الفكرة", "السيناريو", "الشخصية والصوت", "الصور",
                                           "التحريك والآهات", "المونتاج والإطلاق"]
    st = {s[0]: set(s[2]) for s in d["stages"]}
    assert st[4] == {3, 4, 5} and st[5] == {6, 7, 8} and st[6] == {9, 10} and st[7] == {10, 11}
    assert d["h1"] == "#/mission/a%20b.json?stage=5&s=7"
    assert d["h2"] == "#/mission/new?stage=1&product=vara.json"
    assert d["h3"] == "#/mission/x.json?stage=7"            # المرحلة بتنحصر بين 1 و7
    assert d["legacy5"] == "#/mission/x.json?stage=4"       # خطوة الاستوديو 5 القديمة ← الشخصية والصوت
    assert d["legacy1"].startswith("#/mission/new?stage=2")
    assert d["hasView"] == "function"


# ───────── واجهة Mission المشتركة ─────────
def test_mission_api_and_view_registered():
    src = _read("mission.js")
    assert "window.Mission = {" in src
    for k in ("stageOfStation", "hash: missionHash", "stages:", "studioHash", "onStudioSync", "ensureStudioStep"):
        assert k in src, k
    assert "VIEWS.mission = {" in src and "#missionBody" in src
    # المراحل 4–7 من production.js عبر التركيب، والمراحل 1–3 بنقل العقد الموجودة
    assert "prodMount(" in src and "VIEWS.products.enter(" in src and "VIEWS.studio.enter(" in src
    assert "appendChild" in src
    # الشريط السفلي، «ودّيني»، اللافتة، الدليل
    for k in ("mission-steps", "mission-bar", "ودّيني", "← رجوع", "التالي →", "Ornament.passed", "mission-passed",
              "Guide.stagePanel", "guide-panel"):
        assert k in src, k
    for cls in ('"done"', '"now"', '"locked"'):
        assert cls in src, cls
    # دليل لكل مرحلة من السبعة: شو/ليش/مثال
    guide = src[src.index("const MISSION_GUIDE"):src.index("const MS = ")]
    for n in range(1, 8):
        assert re.search(rf"\b{n}: \{{ what:", guide), f"دليل المرحلة {n} ناقص"
    assert guide.count("example:") == 7 and guide.count("why:") == 7
    # كل الأسماء جوّا دالة مغلقة (ما نصطدم بـ boot.js وغيره)
    assert "(() => {" in src and src.rstrip().endswith("})();")


def test_production_mount_api_and_partial_stations():
    prod = _read("production.js")
    assert "async function prodMount(host, o = {})" in prod
    assert "PRD.only" in prod and "visibleStations()" in prod
    assert 'PRD.part !== "montage"' in prod and 'PRD.part !== "ahat"' in prod      # المحطة 10 مقسومة
    # منطق المحطات نفسه باقٍ
    for ep in ("/voice/approve", "/shots/approve", "/images/approve", "/match/approve", "/motion/approve",
               "/montage/render", "/ambience", "/launch${url}", "/character`"):
        assert ep in prod, ep
    # الشريط الجانبي بيعرض محطات المرحلة الحالية بروابط المهمة
    rail = prod[prod.index("function renderRail()"):prod.index("async function prodMount")]
    assert "visibleStations()" in rail and "prodHash(" in rail
    assert "Mission.hash(" in prod and "Mission.stageOfStation(" in prod


# ───────── خطوة الاستوديو 5 انشالت، والروابط صارت للمهمة ─────────
def test_studio_step5_removed():
    st = _read("studio.js")
    for gone in ("renderStep5", "showMediaTab", "renderVoiceStep", "renderImagesStep", "#mediaTabs", "#mediaGate",
                 "#stepVoice", "#stepImages", "wireShotCards", "/api/voice/", "/api/images/"):
        assert gone not in st, gone
    assert "Math.min(4," in st
    # settings.js لسا بيصفّر كاش الصوت والصور — التصريح لازم يضل
    assert "let TTS_INFO" in st and "let IMG_INFO" in st


def test_no_internal_links_to_old_studio_or_production_routes():
    for name in ("studio.js", "production.js", "mission.js"):
        src = _read(name)
        assert "#/studio" not in src, name
        assert not re.search(r"""[`"']#/production""", src), name
        assert not re.search(r"""[`"']#/products/""", src), name
    st = _read("studio.js")
    assert "Mission.hash(file, 4)" in st                      # بعد الموافقة ← المرحلة 4


# ───────── الهروب والأمان ─────────
RISKY = re.compile(r"\$\{\s*(?:s|st|meta|p|prod|g|info|d|c)\.(name|label|note|reason|title|display_name|product|product_name|why|text|file)\b")


def test_mission_escapes_server_fields():
    src = _read("mission.js")
    # stageInfo بيبني جمل «شو الناقص» كنص خام (فيها ملاحظات الخادم) — بتنهرب مرة وحدة وقت الرسم
    body = src[:src.index("function stageInfo(")] + src[src.index("/* تفاصيل أدق لمحطات"):]
    bad = []
    for m in RISKY.finditer(body):
        tail = body[m.end():m.end() + 12]
        if re.match(r"\s*(\?|&&|===|!==|\|\|)", tail):      # شرط/مقارنة مش طباعة
            continue
        bad.append(m.group(0))
    assert not bad, f"حقول بلا esc: {bad}"
    assert "esc(info.why" in src and 'title="${esc(info.why' in src
    # كل innerHTML بالقوالب بيمر بـ esc للنصوص المتغيّرة
    assert src.count("esc(") >= 15
    for line in src.splitlines():
        m = re.search(r"innerHTML\s*=\s*(.+)", line)
        if m:
            rhs = m.group(1).lstrip()
            assert rhs.startswith(("`", '"', "errBox(", "MISSION_STAGES.map(")) or re.match(r"[\w.]+\s*\?\s*`", rhs), line.strip()


def test_no_arabic_indic_digits_and_no_keys():
    pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})")
    for name in ("mission.js", "studio.js", "production.js"):
        src = _read(name)
        assert not AR_DIGITS.search(src), name
        assert not pat.search(src), name
