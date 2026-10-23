"""المرحلة 7 (الشكل والدليل): ثيما «نجمة وطريق» (ليل/نهار)، مبدّل بكبسة، رؤوس الصفحات كأبطال، رسومات الحالات
الفاضية، صفحة الدخول، الترويسة على الجوال، والمصطلحات الجديدة بالدليل. كله فحص ساكن على ملفات web/static (بلا متصفح)."""
import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


THEME = _read("theme.css")
ORN = _read("ornament.css")
INDEX = _read("index.html")


# ───────── الثيمان: ليل / نهار ─────────
def _block(start: str) -> str:
    i = THEME.index(start)
    j = THEME.index("{", i)
    return THEME[j + 1:THEME.index("}", j)]


def _tokens(body: str) -> dict:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--vp-[\w-]+)\s*:\s*([^;]+);", body)}


THEMES = {
    "night": _tokens(_block(':root,\n[data-theme="night"]')),
    "day": _tokens(_block('[data-theme="day"],')),
}


def test_the_two_themes_define_the_same_tokens():
    assert list(THEMES) == ["night", "day"] and len(THEMES["night"]) >= 48
    assert set(THEMES["day"]) == set(THEMES["night"]), sorted(set(THEMES["night"]) ^ set(THEMES["day"]))
    # «نيون» اندمج بالليل: ما عاد إله كتلة ثيم، بس اسم قديم بالترحيل
    assert '[data-theme="neon"] {' not in THEME
    assert "neon: \"night\"" in _read("boot.js")


def test_fonts_are_ibm_plex_sans_arabic():
    root = _block(":root {")
    t = _tokens(root)
    assert "IBM Plex Sans Arabic" in t["--vp-font-sans"]
    # خط العرض العربي والعناوين عربية محلية — بلا خط لاتيني صارخ (Bangers انشال)
    assert "Bangers" not in THEME and "Bangers" not in ORN
    for f in ("IBMPlexSansArabic-400-arabic.woff2", "IBMPlexSansArabic-600-arabic.woff2", "IBMPlexSansArabic-700-arabic.woff2",
              "OFL-IBMPlexSansArabic.txt"):
        assert (STATIC / "fonts" / f).exists(), f
    assert 'font-family: "IBM Plex Sans Arabic"' in ORN and "IBMPlexSansArabic-400-arabic.woff2" in ORN


def _lum(hexc: str) -> float:
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


PAIRS = [
    ("--vp-text", ["--vp-bg", "--vp-surface", "--vp-surface-2", "--vp-surface-3"]),
    ("--vp-text-muted", ["--vp-bg", "--vp-surface", "--vp-surface-2", "--vp-surface-3"]),
    ("--vp-text-faint", ["--vp-bg", "--vp-surface", "--vp-surface-2"]),
    ("--vp-heading", ["--vp-bg", "--vp-surface", "--vp-surface-2"]),
    ("--vp-brand-text", ["--vp-bg", "--vp-surface", "--vp-surface-2", "--vp-brand-soft"]),
    ("--vp-accent", ["--vp-bg", "--vp-surface", "--vp-surface-2"]),
    ("--vp-on-brand", ["--vp-brand"]),
    ("--vp-on-cta", ["--vp-cta", "--vp-cta-hover"]),
    ("--vp-on-danger", ["--vp-danger"]),
    ("--vp-ok", ["--vp-surface", "--vp-ok-soft"]),
    ("--vp-warn", ["--vp-surface", "--vp-warn-soft"]),
    ("--vp-danger", ["--vp-surface", "--vp-danger-soft"]),
    ("--vp-info", ["--vp-surface", "--vp-info-soft"]),
    ("--vp-idle", ["--vp-surface", "--vp-idle-soft"]),
]


@pytest.mark.parametrize("theme", ["night", "day"])
def test_text_contrast_is_at_least_aa_on_every_surface(theme):
    t = THEMES[theme]
    bad = []
    for fg, bgs in PAIRS:
        for bg in bgs:
            assert t[fg].startswith("#") and t[bg].startswith("#"), (theme, fg, bg)
            r = _ratio(t[fg], t[bg])
            if r < 4.5:
                bad.append(f"{fg} {t[fg]} على {bg} {t[bg]} = {r:.2f}")
    assert not bad, f"{theme}: " + "; ".join(bad)


# ───────── أصول الصور: webp + credits.json ─────────
def test_theme_images_are_webp_and_every_one_is_credited():
    urls = set(re.findall(r'url\("(/img/theme/[^"]+)"\)', ORN + THEME + _read("style.css")))
    assert len(urls) >= 12, urls
    for u in urls:
        assert u.endswith(".webp"), u                       # jpg القديمة انشالت
        assert (STATIC / u.lstrip("/")).exists(), u
    credits = json.loads((STATIC / "img" / "theme" / "credits.json").read_text(encoding="utf-8"))
    by_file = {c["file"]: c for c in credits}
    for u in urls:
        name = u.rsplit("/", 1)[-1]
        assert name in by_file, f"{name} بلا سطر حقوق بـ credits.json"
    for c in credits:
        for k in ("file", "what", "author", "licence", "licence_url", "source"):
            assert c.get(k), (c.get("file"), k)
        assert c["source"].startswith("https://"), c["file"]
    # جدول الحقوق المقروء للبشر موجود كمان
    assert "credits.json" in (STATIC / "img" / "theme" / "README.md").read_text(encoding="utf-8")


def test_theme_stays_an_original_look():
    """طابع بس: ما بيظهر اسم لعبة ولا شركة ولا خط مرخّص بالكود الظاهر للمستخدم."""
    for name in ("theme.css", "ornament.css", "style.css", "index.html", "login.html", "boot.js", "guide.js", "login.js"):
        txt = _read(name)
        assert not re.search(r"GTA|Rockstar|Pricedown|Grand Theft", txt, re.I), name


def test_image_variables_cover_every_hero_slot():
    root = ORN[ORN.index(":root {"):]
    declared = set(re.findall(r"(--img-[\w-]+):\s*url\(\"/img/theme/", root[:root.index("\n}")]))
    assert len(declared) >= 12, declared
    slots = set(re.findall(r"\.hero\[data-img=\"[\w-]+\"\]\s*\{\s*--hero-img:\s*(var\(--img-[\w-]+\))", ORN))
    assert slots, "ما لقيت قواعد صور الأبطال"
    for s in slots:
        assert s[len("var("):-1] in declared, s


# ───────── مبدّل الثيم: كبسة وحدة ─────────
def test_theme_is_a_one_click_toggle_with_no_menu():
    boot = _read("boot.js")
    assert 'id="themeBtn"' in INDEX and 'id="themeDd"' not in INDEX and 'id="themeMenu"' not in INDEX
    assert 'id="themeGlyph"' in INDEX and 'id="themeName"' in INDEX
    # أسماء الثيمين بالعربي + الترحيل من الأسماء القديمة
    assert '"نجمة وطريق (ليل)"' in boot and '"نجمة وطريق (نهار)"' in boot
    assert 'THEME_MIGRATE = { dark: "night", neon: "night", light: "day", calm: "day" }' in boot
    # كبسة وحدة بتقلب ليل ↔ نهار؛ ما في قائمة ولا applyTheme من عنصر قائمة
    assert "function nextTheme()" in boot and 'addEventListener("click", () => applyTheme(nextTheme()))' in boot
    assert 'zk.dropdown($("#themeDd")' not in boot
    # صفحة الدخول بتقرأ نفس المفتاح وبتطبّع الأسماء القديمة
    login = _read("login.js")
    assert "vp-theme" in login


# ───────── رؤوس الصفحات كأبطال ─────────
def test_main_page_heads_are_heroes_with_known_images():
    heroes = re.findall(r'class="page-head hero compact"[^>]*data-img="([\w-]+)"', INDEX)
    assert {"pattern", "factory", "performance"} <= set(heroes), heroes
    assert 'class="page-head mission-head hero compact" data-img="mission"' in _read("mission.js")
    defined = set(re.findall(r'\.hero\[data-img="([\w-]+)"\]', ORN))
    for img in heroes:
        assert img in defined, img
    shell = _read("shell.js")
    m = re.search(r"const LIBS_IMG = \{([^}]*)\}", shell)
    assert m, "LIBS_IMG ناقص"
    per_tab = dict(re.findall(r'(\w+): "([\w-]+)"', m.group(1)))
    tabs = re.search(r"const LIBS_TABS = \[([^\]]*)\]", shell).group(1)
    for t in re.findall(r'"(\w+)"', tabs):
        assert t in per_tab, f"رف المكتبات «{t}» بلا صورة بطل"
    assert set(per_tab.values()) <= defined
    # كل رأس رئيسي فيه زر «الخطوة الجاية» وفي مقبض عام لهالزر
    assert INDEX.count("data-guide-next") >= 3
    assert "[data-guide-next]" in _read("guide.js")


# ───────── رسومات الحالات الفاضية ─────────
def test_every_empty_state_art_key_has_css_and_a_missing_file_falls_back():
    keys = set()
    for p in STATIC.glob("*.js"):
        keys |= set(re.findall(r'class="empty"[^>]*data-art="([\w-]+)"', p.read_text(encoding="utf-8")))
    keys |= set(re.findall(r'data-art="([\w-]+)"', INDEX))
    assert {"patterns", "hooks", "moves", "activity", "characters", "sounds"} <= keys, keys
    for k in keys:
        assert f'.empty[data-art="{k}"]::before' in ORN, k
    js = _read("ornament.js")
    assert "function artCheck" in js and "img.onerror" in js and 'removeAttribute("data-art")' in js
    assert "artCheck });" in js or "artCheck})" in js


# ───────── صفحة الدخول والترويسة ─────────
def test_login_page_has_background_layers_and_a_portrait_rule():
    block = ORN[ORN.index(".login-page {"):]
    block = block[:block.index("}")]
    layers = re.findall(r"url\(|linear-gradient\(|var\(--vp-sky\)", block)
    assert len(layers) >= 3, block                       # تدرّج + صورة البطل + سماء مرسومة
    assert "var(--img-hero-home)" in block and "var(--vp-sky)" in block
    after = ORN[ORN.index(".login-page {"):]
    assert "@media (orientation: portrait)" in after[:after.index(".login-card")]
    assert ".login-card" in ORN and "backdrop-filter" in ORN


def test_header_fits_laptop_and_phone_widths():
    css = _read("style.css")
    # لابتوب: الترويسة بتشيل نصوص الأزرار (tb-lbl) وبتضل الأيقونات
    assert re.search(r"@media \(min-width: 561px\) and \(max-width: 1500px\)\s*\{[^}]*\.tb-lbl\s*\{\s*display: none", css)
    phone = css[css.index("جوال: أزرار الترويسة أضيق"):][:600]
    assert ".zk-header__end" in phone and "flex-wrap: wrap" in phone and "#guideBtn .tb-lbl { display: none; }" in phone
    assert 'id="tbJobs"' in INDEX and 'aria-label="المهام"' in INDEX     # زر بلا نص لازم يكون إله اسم
    # أزرار الترويسة نفسها بترتيب عقد «نجمة»: جديد، الخطوة الجاية، المهام، الدليل، الثيم، حسابي
    h = re.search(r'<header slot="header".*?</header>', INDEX, re.S).group(0)
    ids = ["newBtn", "guideNextBtn", "tbJobs", "guideBtn", "themeBtn", "accBtn"]
    positions = [h.index(f'id="{i}"') for i in ids]
    assert positions == sorted(positions), ids


# ───────── الدليل ─────────
def test_new_glossary_terms_and_term_marks():
    g = _read("guide.js")
    for key in ("hooks_bank", "cinematic_moves", "face_match", "staff", "activity", "oms", "hook"):
        assert re.search(rf"^\s+{key}: \{{ t:", g, re.M), key
    assert "بنك الهوكات" in g and "الهوكات" in g           # أسماء التبويبات الجديدة بالجولة والبحث السريع
    assert "الثيم بيتبدّل بكبسة" in g                      # الدليل بيشرح المبدّل الجديد بكبسة
    for f, key in (("hooks.js", "hooks_bank"), ("presets.js", "cinematic_moves"), ("accounts.js", "staff"), ("accounts.js", "activity")):
        assert f'Guide.term("{key}")' in _read(f), (f, key)
    for screen in ("#/library/hooks", "#/library/presets", "#/settings/staff", "#/settings/activity"):
        assert f'"{screen}"' in g, screen
    assert "niون" not in g and "نيون" not in g             # «نيون» ما عاد مصطلح — اندمج بالليل


def test_state_colors_keep_their_own_outlines():
    """الحدود العامة (زر/شريحة) ما لازم تبلع لون الحالة: خطر وتنبيه بيضلوا بلونهم بالثيمين."""
    css = _read("style.css")
    assert '.chip[data-state="danger"] { border-color: var(--vp-danger); color: var(--vp-danger); }' in css
    assert '.chip[data-state="warn"] { border-color: var(--vp-warn); }' in css
    assert '.btn.danger' in css or '.btn.danger' in ORN
    # ولا كتلة ثيم بتعيد تلوين الحالات
    for th in ("night", "day"):
        blk = THEME[THEME.index(f'[data-theme="{th}"]'):][:1200]
        assert ".btn.danger" not in blk and ".chip[data-state" not in blk, th


def test_quick_search_button_is_styled_by_the_theme_not_the_browser():
    css = _read("style.css")
    assert "button.nav-search { background: transparent; border: 1px solid var(--vp-border)" in css
