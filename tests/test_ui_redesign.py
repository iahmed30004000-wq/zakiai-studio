"""إعادة هيكلة الواجهة (23/10): نافذة «إعلان جديد»، «إعلاناتي» جوّا الرئيسية، جاهزية المصنع، صفحة الدليل، إعدادات بأربع تبويبات،
مكتبات بأربع رفوف، وثيم «ساحل النيون» بصور حقيقية. فحص ساكن على web/static (بلا متصفح ولا سيرفر)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
NODE = shutil.which("node")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


INDEX = _read("index.html")


def test_new_ad_chooser_is_one_door_with_three_cards():
    najma = _read("najma.js")
    # الزر الكبير بالقائمة وزر «＋ جديد» بالترويسة بيفتحوا نفس النافذة
    assert INDEX.count("data-new-chooser") >= 3
    for k, href in (("guided", "#/mission/new?stage=1"), ("free", "#/mission/new?free=1")):
        assert f'k: "{k}"' in najma and f'href: "{href}"' in najma
    assert 'k: "quick"' in najma and "FreeProject" in najma and "quickHash" in najma
    # الرسمة اللي لسا ما وصلت ما بتكسر الكرت (بتضل نجمة مرسومة)
    assert "/img/art/new-" in najma and 'addEventListener("error"' in najma
    assert ".nc-card" in _read("ornament.css") and ".nav-new" in _read("ornament.css")


def test_my_ads_live_inside_home_and_missions_page_is_gone():
    assert 'id="msList"' in INDEX and 'id="msFilter"' in INDEX and 'id="homeMyAds"' in INDEX
    assert "missions.js" not in INDEX and not (STATIC / "missions.js").exists()
    home = _read("home.js")
    for fn in ("renderMyAds", "adMatches", "homeNextLine"):
        assert fn in home, fn
    assert "VIEWS.missions" not in "".join(_read(p.name) for p in STATIC.glob("*.js"))


def test_factory_readiness_has_fix_buttons_and_keys_have_one_home():
    shell, st = _read("shell.js"), _read("settings.js")
    assert 'id="facReady"' in INDEX and 'id="facReadySum"' in INDEX
    assert "data-fix=" in shell and "صلّح" in shell and "ready-prob" in shell
    # مفتاح الصور/الصوت الناقص: «صلّح» بيوديك لخانة المفتاح نفسها
    assert "#/factory/api/media|#sTtsKey" in shell and "#/factory/api/media|#sImgKey" in shell and "#/factory/api/keys|#apiKeyInput" in shell
    # التفريغ (STT) انتقل جنب الصوت والصور، ومفاتيح الإعدادات الباقية مكانها «كل المفاتيح»
    assert '#sttPanel' in shell and 'id="sttPanel"' in INDEX
    assert '["#/factory/api/media", "اضبطه من هون ←"]' in st
    seg = re.search(r'<div class="seg seg-sm" id="facApiTabs".*?</div>', INDEX, re.S).group(0)
    assert seg.index('data-tab="keys"') < seg.index('data-tab="media"') < seg.index('data-tab="models"')


def test_libraries_are_four_shelves_with_pattern_subsections():
    seg = re.search(r'<div class="seg" id="libsTabs".*?</div>', INDEX, re.S).group(0)
    assert re.findall(r'data-tab="(\w+)"', seg) == ["products", "characters", "patterns", "sounds"]
    sub = re.search(r'<div class="seg seg-sm" id="libsPatTabs".*?</div>', INDEX, re.S).group(0)
    assert re.findall(r'data-tab="(\w+)"', sub) == ["patterns", "hooks", "presets"]
    shell = _read("shell.js")
    assert "LIBS_PAT" in shell and 'bindTabClicks("#libsPatTabs"' in shell


def test_settings_have_four_tabs_with_companion_sections():
    seg = re.search(r'<div class="seg" id="setTabs".*?</div>', INDEX, re.S).group(0)
    assert re.findall(r'data-tab="(\w+)"', seg) == ["staff", "ops", "analysis", "advanced"]
    st = _read("settings.js")
    for old, new in (("general", "ops"), ("activity", "staff"), ("crm", "advanced")):
        assert f'{old}: "{new}"' in st                       # الروابط القديمة بتنزل على تبويبها
    # الحفظ بمكانين لنفس الإعدادات: زر واحد بمعالج واحد
    assert len(re.findall(r"saveSettingsValues\(", st)) >= 2 and INDEX.count('class="btn save-settings"') == 2


def test_dead_studio_step_and_old_picker_are_gone():
    for gone in ('id="studioSteps"', 'id="st-5"', 'id="mediaTabs"', 'id="prodPick"', 'data-guide-next'):
        assert gone not in INDEX, gone
    for i in (1, 2, 3, 4):
        assert f'id="st-{i}"' in INDEX
    assert "#studioSteps" not in _read("studio.js")


def test_mission_bar_has_one_primary_button_and_a_finish_screen():
    m = _read("mission.js")
    bar = m[m.index("function renderBar()"):m.index("function goNext()")]
    assert bar.count("zk-btn--primary") == 4 and "ودّيني للناقص" in bar and "التالي →" in bar and "data-new-chooser" in bar
    assert "function celebrate(" in m and "خلص الإعلان" in m and "mission-done.png" in m
    assert 'section.open = label === "بريف المنتج"' in m


# ───────── صفحة الدليل ─────────
def test_guide_page_has_steps_problems_and_words_from_one_source():
    g = _read("guidepage.js")
    assert "window.GuidePage" in g and "VIEWS.guide" in g and g.lstrip().startswith("/*") and "(() => {" in g
    assert "Mission.guideTexts" in g and "Guide.GLOSSARY" in g          # ما في نسخة تانية من الشرح
    assert "guideTexts: MISSION_GUIDE" in _read("mission.js")
    probs = re.findall(r"\{ q: \"([^\"]+)\"", g)
    assert len(probs) == 10, probs
    for hash_ in re.findall(r'"(#/[^"]+)"\]', g):
        route = hash_[2:].split("/")[0].split("?")[0]
        assert route in ("home", "mission", "library", "factory", "settings", "guide"), hash_
    assert "guideTourBtn" in INDEX and "data-new-chooser" in INDEX[INDEX.index('id="v-guide"'):]
    assert "#/guide" in _read("guide.js") and "ROUTES" in _read("boot.js") and "guide: { view: \"guide\"" in _read("boot.js")
    scripts = re.findall(r'<script[^>]*\ssrc="/?([^"?]+)', INDEX)
    assert scripts.index("guide.js") < scripts.index("guidepage.js") < scripts.index("boot.js")


def test_every_problem_in_the_guide_points_at_a_screen_that_exists():
    if NODE is None:
        pytest.skip("node مش موجود")
    harness = r"""
const fs = require("fs"), vm = require("vm");
const ctx = { console, window: {}, document: { getElementById: () => null }, VIEWS: {}, esc: (s) => s, $$: () => [], selectTab: () => "steps", bindTabClicks() {} };
ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], "utf8"), ctx);
process.stdout.write(JSON.stringify(ctx.GuidePage.PROBLEMS));
"""
    r = subprocess.run([NODE, "-e", harness, "--", str(STATIC / "guidepage.js")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    probs = json.loads(r.stdout)
    assert len(probs) == 10
    for p in probs:
        assert p["q"] and p["a"] and p["ex"] and (p.get("chooser") or p["go"][1].startswith("#/")), p


# ───────── ساحل النيون: صور حقيقية بحقوق ─────────
def test_neon_theme_images_are_real_credited_webp():
    d = STATIC / "img" / "theme" / "neon"
    slots = ["hero-home", "hero-day", "home-night", "library", "mission", "pattern", "performance", "petra-night", "products", "sounds", "tiles", "tour", "factory"]
    for s in slots:
        f = d / f"{s}.webp"
        assert f.exists() and f.stat().st_size < 250 * 1024, s
    for f in ("neon-coast.door.webp", "neon-coast.door-tall.webp"):
        assert (d / f).exists(), f
    credits = {c["file"]: c for c in json.loads((STATIC / "img" / "theme" / "credits.json").read_text(encoding="utf-8"))}
    for s in slots:
        c = credits[f"neon/{s}.webp"]
        assert c["source"].startswith("https://") and c["licence"], s
    assert (d / "CREDITS.md").exists()
    orn = _read("ornament.css")
    for s in slots:
        assert f"/img/theme/neon/{s}.webp" in orn, s
    assert "SA" not in "".join(c["licence"].replace("Unsplash", "") for c in credits.values() if c["file"].startswith("neon/") and "BY-SA" in c["licence"].upper())


def test_neon_is_a_third_theme_reachable_by_one_click_and_login_accepts_it():
    boot, login = _read("boot.js"), _read("login.js")
    assert '{ k: "neon"' in boot and "THEMES.findIndex" in boot and "% THEMES.length" in boot
    assert '"neon"' in login
    theme = _read("theme.css")
    assert '[data-theme="neon"] {' in theme and "--vp-black" in theme
    assert not re.search(r"GTA|Rockstar|Pricedown|Grand Theft", theme + _read("ornament.css"), re.I)   # طابع بس، بلا أسماء ألعاب


def test_new_art_slots_are_real_photos_with_credits():
    """الـ 13 صورة الحقيقية (بدل رسومات GPT): حجم وصيغة صحيحين وحقوق بـ https، من مصادر مرخّصة (CC0/CC BY/دومين عام)."""
    from PIL import Image
    art = STATIC / "img" / "art"
    slots = {"login-bg.jpg": (1920, 1080), "guide-cover.jpg": (1600, 900), "mission-done.png": (1024, 1024)}
    for n in ("empty-patterns", "empty-hooks", "empty-moves", "empty-activity", "new-guided", "new-free", "new-quick", "guide-help", "factory-ready", "not-found"):
        slots[f"{n}.png"] = (800, 600)
    credits = {c["file"]: c for c in json.loads((STATIC / "img" / "theme" / "credits.json").read_text(encoding="utf-8"))}
    for name, size in slots.items():
        f = art / name
        assert f.exists() and f.stat().st_size < 600 * 1024, name
        with Image.open(f) as im:
            assert im.size == size and im.format == ("JPEG" if name.endswith(".jpg") else "PNG"), (name, im.size, im.format)
        c = credits[f"art/{name}"]
        assert c["source"].startswith("https://") and c["licence"], name
        assert not re.search(r"\bSA\b|NC", c["licence"]), (name, c["licence"])               # بلا ShareAlike ولا NonCommercial
    assert (art / "CREDITS.md").exists()
