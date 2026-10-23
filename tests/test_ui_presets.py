"""واجهة الحركات السينمائية: تبويب المكتبات + محطة التحريك + وضع التجربة."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
SHELL = (STATIC / "shell.js").read_text(encoding="utf-8")
JS = (STATIC / "presets.js").read_text(encoding="utf-8")
PRD = (STATIC / "production.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def mock(name):
    return json.loads((STATIC / "mock" / f"{name}.json").read_text(encoding="utf-8"))


def test_the_library_has_a_presets_tab_wired_through_the_shell():
    tabs = re.search(r'<div class="seg" id="libsTabs".*?</div>', HTML, re.S).group(0)
    sub = re.search(r'<div class="seg seg-sm" id="libsPatTabs".*?</div>', HTML, re.S).group(0)      # قسم جوّا رف «الأنماط والهوكات»
    assert 'data-tab="presets">الحركات السينمائية</button>' in sub and '<div id="libs-presets" class="tabpane"></div>' in HTML
    assert re.search(r'<script src="/presets\.js\?v=\d+"></script>', HTML)
    assert re.search(r'const LIBS_TABS = \[[^\]]*"presets"', SHELL) and 'case "presets": return VIEWS.presets.enter();' in SHELL
    assert "VIEWS.presets = { async enter() { await pstLoad(); } };" in JS


def test_presets_js_keeps_its_names_private_and_talks_only_to_its_own_api():
    names = re.findall(r"^(?:async function|function|const|let|var) ([A-Za-z_$][\w$]*)", JS, re.M)
    assert names and all(n.startswith(("PST", "pst")) for n in names), [n for n in names if not n.startswith(("PST", "pst"))]
    urls = set(re.findall(r"[`\"](/api/[^`\"?]*)", JS))
    assert all(u.startswith(("/api/presets", "/api/studio/")) for u in urls), urls
    assert "/preset`" in JS and 'method: id ? "PUT" : "POST"' in JS and 'method: "DELETE"' in JS


def test_destructive_actions_are_confirmed_and_the_wording_is_plain():
    assert 'confirm(p && p.custom ? "تحذف هالوصفة؟" : "ترجّع الوصفة الأصلية وتشيل تعديلك؟")' in JS
    for needle in ("وصفة جديدة (حركة من عندك، بلا كود)", "لسا ما اتجرّبت — أول ما تطبّقها", "كلام الكاميرا لكل موديل (إنجليزي)", "وصفتك", "معدّلة منك",
                   "كاميرا ثابتة", "حركة كاميرا", "رجّع الأصلية", "ما في وصفات بهالقسم."):
        assert needle in JS, needle
    assert not re.search(r"[٠-٩]", JS)


def test_the_form_collects_exactly_what_the_api_validates():
    body = re.search(r"function pstCollect\(form\) \{.*?\n\}", JS, re.S).group(0)
    for k in ("name_ar", "category", "desc_ar", "motion_desc_ar", "camera_move", "recipes", "duration_s"):
        assert k in body, k
    assert '["default", "hailuo", "kling"]' in body and "Number(f(\"dur_lo\").value)" in body


def test_the_motion_station_loads_the_presets_and_offers_them_per_shot():
    st = re.search(r"async function renderMotionStation\(body\) \{.*?\n\}", PRD, re.S).group(0)
    assert 'soft("/api/presets")' in st and "r.data.presets = pr.data || null" in st
    assert "${pstGallery(d.presets)}" in PRD and "${pstShotControl(s, d.presets)}" in PRD and "pstBindShots(body, file, refresh);" in PRD
    assert PRD.index("${pstGallery(d.presets)}") < PRD.index('<div id="extPanel"></div>\n    ${d.shots.map')


def test_the_shot_control_covers_categories_look_choices_and_clearing():
    ctl = re.search(r"function pstShotControl\(s, data\) \{.*?\n\}", JS, re.S).group(0)
    for needle in ("حركة سينمائية (اختياري)", "optgroup", "الكاميرا والعدسة (اختياري)", "الطول البؤري", "الفتحة", "s.camera_preset"):
        assert needle in ctl, needle
    bind = re.search(r"function pstBindShots\(body, file, refresh\) \{.*?\n\}", JS, re.S).group(0)
    assert "انحطّت الحركة على اللقطة — اضغط «حرّك»" in bind and "انشالت الحركة الجاهزة" in bind
    assert '{ method: "DELETE" }' in bind and "انحفظ شكل الكاميرا" in bind


def test_mock_mode_has_the_presets_the_routes_and_an_active_preset_on_a_shot():
    d = mock("presets")
    assert d["counts"] == {"total": len(d["presets"]), "custom": 1, "with_example": 2} and len(d["presets"]) >= 20
    assert {p["category"] for p in d["presets"]} == {"camera", "product", "character"} == {c["id"] for c in d["categories"]}
    assert sum(1 for p in d["presets"] if p["example"]) == 2 and sum(1 for p in d["presets"] if p["custom"]) == 1
    assert [len(d["looks"][k]) for k in ("cameras", "lenses", "focals", "apertures")] == [6, 11, 6, 3]
    assert not re.search(r"[٠-٩]", json.dumps(d, ensure_ascii=False))
    assert 'if (path === "/api/presets") return mockFile("presets");' in APP
    assert re.search(r"presets\(\\/\[\^/\]\+\)\?\$/\.test\(path\) && method !== \"GET\"", APP) and "shots\\/[^/]+\\/preset$" in APP
    first = mock("motion_info")["shots"][0]
    assert first["camera_preset"]["id"] in {p["id"] for p in d["presets"]}


def test_the_styles_for_the_cards_and_the_gallery_exist():
    for cls in (".pst-card .pst-video", ".pst-grid", ".pst-mini", ".pst-gallery", ".pst-shot", ".pst-form"):
        assert cls in CSS, cls
