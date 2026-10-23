"""م4 (النجمة والجولة): فحص ساكن لملفي najma.js وguide.js وشريحة الصرف — بلا متصفح ولا شبكة."""
import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


NAJMA = _read("najma.js")
GUIDE = _read("guide.js")
INDEX = _read("index.html")


# ───────── النجمة الحيّة: سطر المهمة ─────────
def test_objective_line_hidden_on_mission_and_cached_20s():
    assert "objective" in NAJMA and 'route === "mission"' in NAJMA
    assert "20000" in NAJMA                       # كاش 20 ثانية
    assert "OBJ.at = 0" in NAJMA                  # تحديث بعد المهام (نارفخ الكاش لما تخلص شغلة)


# ───────── شاشة التحميل ─────────
def test_loadscreen_kinds_minimize_and_passed_banner():
    for kind in ("images", "motion", "montage", "voice", "ahat"):
        assert re.search(rf"/\\{kind}", NAJMA) or kind in NAJMA, kind
    assert "6500" in NAJMA                        # تصغير تلقائي بعد 6.5 ثانية
    assert "nload-pill" in NAJMA and "showLayer" in NAJMA and "paintPill" in NAJMA
    assert "تمّت ✓" in NAJMA and "Ornament.passed" in NAJMA


def test_loadscreen_cancel_option_in_settings():
    assert "vpLoadscreenOpt" in NAJMA and "set-general" in NAJMA
    assert 'data-nl-off' in NAJMA and '"vp-loadscreen"' in NAJMA
    row = INDEX[INDEX.index('id="set-general"'):]
    assert 'id="vpLoadscreenOpt"' not in row       # بيتزنّد وقت التشغيل (settings.js مش ملك النجمة)


# ───────── الجولة: 5 محطات بالترتيب المطلوب ─────────
def test_tour_is_exactly_five_stops_in_contract_order():
    stops = re.findall(r'\{ sel: "([^"]+)"', GUIDE)
    assert len(stops) == 5, stops
    assert stops[0] == "#newBtn" and "#guideNextBtn" in stops[1] or stops[1] == "#guideNextBtn"
    assert stops[2].endswith("zk-drawer-toggle")   # القائمة
    assert stops[3] == "#guideBtn" and stops[4] == "#accBtn"
    # التخزين المحلي: الجولة أول زيارة بس
    assert 'store.get("vp-tour-done")' in GUIDE and 'store.set("vp-tour-done", "1")' in GUIDE


def test_no_neon_nights_wording_in_owned_files():
    for name in ("guide.js", "najma.js"):
        txt = _read(name)
        assert "نيون" not in txt and "ليالي الشرق" not in txt and "ساحل النيون" not in txt, name
    css = _read("ornament.css")
    for frag in re.findall(r'\.empty\[data-art="([\w-]+)"\]', css):
        assert "neon" not in frag and "night" not in frag


# ───────── القاموس: المصطلحات الجديدة بلا نيون ─────────
@pytest.mark.parametrize("term", ["المشروع الحر", "شغلة سريعة", "مكتبة النماذج"])
def test_new_glossary_entries(term):
    block = GUIDE[GUIDE.index("const GLOSSARY"):GUIDE.index("const INDEX")]
    assert term in block, term
    assert "نيون" not in block and "ليالي" not in block


# ───────── نوافذ الدليل: الحقوق من img/theme/credits.json ─────────
def test_credits_window_reads_theme_credits_json():
    assert 'img/theme/credits.json' in NAJMA
    credits = json.loads((STATIC / "img" / "theme" / "credits.json").read_text(encoding="utf-8"))
    assert isinstance(credits, list) and credits
    for c in credits:
        assert {"what", "author", "licence", "licence_url", "source"} <= set(c)


# ───────── شريحة الإنفاق الخضراء ─────────
def test_spend_chip_uses_usage_api_without_balances_and_weeks():
    assert '/api/usage?days=7&balances=false' in NAJMA
    assert "هالأسبوع" in NAJMA and "tb-spend" in NAJMA
    # العقد الخلفي موجود: balances=True قرب تعريف /api/usage
    app = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
    i = app.index('@app.get("/api/usage")')
    assert "balances: bool = True" in app[i:i + 200]
    # الشريحة بتتشال وبتتجدد كل 10 دقايق متل شريحة الصرف بالخادم
    assert "600000" in NAJMA and "cost_usd" in NAJMA


def test_spend_chip_matches_header_chip_markup():
    """شريحة الصرف بنفس بنية شرائح الترويسة (chip + dot + chip-k + chip-v) عشان ستايل الترويسة بيشغلها."""
    header = re.search(r'<header slot="header".*?</header>', INDEX, re.S).group(0)
    assert 'class="chip' in header and 'class="dot"' in header and "chip-k" in header and "chip-v" in header
    for frag in ('className = "chip tb-spend"', '<span class="dot"></span>', 'class="chip-k"', 'class="chip-v"'):
        assert frag in NAJMA, frag


# ───────── حالات الفراغ (فحص المكان + المفاتيح) ─────────
def test_empty_state_art_keys_cover_libraries():
    orn = _read("ornament.css")
    defined = set(re.findall(r'\.empty\[data-art="([\w-]+)"\]', orn))
    assert {"characters", "sounds", "patterns", "hooks", "moves", "products", "activity"} <= defined
    # الشخصيات والأصوات مستخدمة فعلاً
    assert 'data-art="characters"' in _read("characters.js")
    assert 'data-art="sounds"' in _read("ahat.js")
    assert 'data-art="patterns"' in _read("app.js")


def test_products_empty_state_location_reported():
    """ملاحظة الإبلاغ: صفحة المنتجات ما إلها حالة فاضية مصوّرة — قائمة المنتجات بترجع «＋ منتج جديد» دايماً (app.js loadProducts)."""
    src = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    i = src.index("async function loadProducts")
    assert "＋ منتج جديد" in src[i:i + 600]
