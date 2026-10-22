"""المرحلة 7 (الشكل والدليل): ثيم «ساحل النيون»، قائمة الثيمات، رؤوس الصفحات كأبطال، رسومات الحالات الفاضية،
صفحة الدخول، الترويسة على الجوال، والمصطلحات الجديدة بالدليل. كله فحص ساكن على ملفات web/static (بلا متصفح)."""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


THEME = _read("theme.css")
ORN = _read("ornament.css")
INDEX = _read("index.html")


# ───────── الثيمات الثلاثة ─────────
def _block(start: str) -> str:
    i = THEME.index(start)
    j = THEME.index("{", i)
    return THEME[j + 1:THEME.index("}", j)]


def _tokens(body: str) -> dict:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--vp-[\w-]+)\s*:\s*([^;]+);", body)}


THEMES = {
    "night": _tokens(_block(':root,\n[data-theme="night"]')),
    "day": _tokens(_block('[data-theme="day"],')),
    "neon": _tokens(_block('[data-theme="neon"] {')),
}


def test_neon_defines_every_token_the_other_themes_do():
    assert len(THEMES["neon"]) >= 48
    assert set(THEMES["night"]) <= set(THEMES["neon"]), sorted(set(THEMES["night"]) - set(THEMES["neon"]))
    assert set(THEMES["day"]) <= set(THEMES["night"]) | set(THEMES["neon"])
    # الخطوط: النيون بيبدّل خط العناوين والعرض (Lalezar + Bangers)
    assert "Bangers" in THEMES["neon"]["--vp-font-display"] and "Lalezar" in THEMES["neon"]["--vp-font-heading"]


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


@pytest.mark.parametrize("theme", ["night", "day", "neon"])
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


# ───────── أصول النيون ─────────
def test_neon_assets_exist_and_are_credited():
    neon = STATIC / "img" / "theme" / "neon"
    urls = set(re.findall(r'url\("(/img/theme/neon/[^"]+)"\)', ORN))
    assert len(urls) >= 9, urls
    for u in urls:
        assert (STATIC / u.lstrip("/")).exists(), u
    credits = (neon / "CREDITS.md").read_text(encoding="utf-8")
    for jpg in sorted(p.name for p in neon.glob("*.jpg")):
        assert jpg in credits, f"{jpg} بلا سطر حقوق"
    assert "Unsplash" in credits
    for f in ("bangers-latin.woff2", "OFL-Bangers.txt"):
        assert (STATIC / "fonts" / f).exists(), f
    assert "bangers-latin.woff2" in ORN and 'font-family: "Bangers"' in ORN


def test_neon_theme_stays_an_original_look():
    """طابع بس: ما بيظهر اسم لعبة ولا شركة ولا خط مرخّص بالكود الظاهر للمستخدم."""
    for name in ("theme.css", "ornament.css", "style.css", "index.html", "login.html", "boot.js", "guide.js", "login.js"):
        txt = _read(name)
        assert not re.search(r"GTA|Rockstar|Pricedown|Grand Theft", txt, re.I), name


def test_neon_image_variables_cover_every_hero_slot():
    block = ORN[ORN.index('[data-theme="neon"] {\n  --img-hero-home'):]
    block = block[:block.index("}")]
    root = ORN[ORN.index(":root {"):]
    slots = set(re.findall(r"(--img-[\w-]+):", root[:root.index("}")]))
    assert slots, "ما لقيت متغيرات الصور الأساسية"
    assert slots <= set(re.findall(r"(--img-[\w-]+):", block)), sorted(slots - set(re.findall(r"(--img-[\w-]+):", block)))


# ───────── قائمة الثيم ─────────
def test_theme_menu_is_built_from_the_themes_list():
    assert 'id="themeDd"' in INDEX and 'id="themeMenu"' in INDEX and 'role="menu"' in INDEX
    boot = _read("boot.js")
    assert 'k: "neon"' in boot and "ساحل النيون" in boot and "ليالي الشرق (ليلي)" in boot and "ليالي الشرق (نهاري)" in boot
    assert 'zk.dropdown($("#themeDd")' in boot and "applyTheme(k)" in boot
    # الصفحة الأولى للدخول بتقرأ نفس الثيم المحفوظ (بما فيه النيون)
    assert '"neon"' in _read("login.js")


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
def test_login_page_has_background_layers_and_door_images():
    block = ORN[ORN.index(".login-page {"):]
    block = block[:block.index("}")]
    assert "/img/art/login-bg.jpg" in block and "var(--vp-sky)" in block
    assert "neon-coast.door.webp" in ORN and "neon-coast.door-tall.webp" in ORN and "orientation: portrait" in ORN


def test_header_fits_laptop_and_phone_widths():
    css = _read("style.css")
    assert re.search(r"@media \(min-width: 561px\) and \(max-width: 1500px\)\s*\{[^}]*#tourBtn \.tb-lbl", css)
    phone = css[css.index("جوال: أزرار الترويسة أضيق"):][:600]
    assert ".zk-header__end" in phone and "flex-wrap: wrap" in phone and "#tourBtn { display: none; }" in phone
    assert 'id="tbJobs"' in INDEX and 'aria-label="المهام"' in INDEX     # زر بلا نص لازم يكون إله اسم


# ───────── الدليل ─────────
def test_new_glossary_terms_and_term_marks():
    g = _read("guide.js")
    for key in ("hooks_bank", "cinematic_moves", "face_match", "staff", "activity", "oms", "hook"):
        assert re.search(rf"^\s+{key}: \{{ t:", g, re.M), key
    assert "الهوكات" in g and "نيون" in g           # أسماء التبويبات الجديدة بالجولة والبحث السريع
    for f, key in (("hooks.js", "hooks_bank"), ("presets.js", "cinematic_moves"), ("accounts.js", "staff"), ("accounts.js", "activity")):
        assert f'Guide.term("{key}")' in _read(f), (f, key)
    for screen in ("#/library/hooks", "#/library/presets", "#/settings/staff", "#/settings/activity"):
        assert f'"{screen}"' in g, screen


def test_neon_black_outlines_keep_state_colors():
    """الحدود السودا العامة (زر/شريحة) ما لازم تبلع لون الحالة: خطر وتنبيه بيضلوا بلونهم."""
    for rule in ('[data-theme="neon"] .btn.danger { border-color: var(--vp-danger); }',
                 '[data-theme="neon"] .btn.warn { border-color: var(--vp-warn); }',
                 '[data-theme="neon"] .chip[data-state="danger"] { border-color: var(--vp-danger); }',
                 '[data-theme="neon"] .chip[data-state="warn"] { border-color: var(--vp-warn); }'):
        assert rule in ORN, rule


def test_quick_search_button_is_styled_by_the_theme_not_the_browser():
    css = _read("style.css")
    assert "button.nav-search { background: transparent; border: 1px solid var(--vp-border)" in css
