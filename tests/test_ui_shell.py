"""فحص ثابت لهيكل الواجهة الجديد «ليالي الشرق» (ui_contract.md — دور S): القائمة، المسارات والتحويلات،
الثيمين، واجهة الدليل (Guide)، والرئيسية/المكتبات/المصنع. بدون متصفح ولا سيرفر ولا شبكة."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
NODE = shutil.which("node")

CONTRACT_ORDER = ["app.js", "studio.js", "perf.js", "settings.js", "production.js", "characters.js", "productref.js",
                  "models.js", "ext.js", "ahat.js", "guide.js", "ornament.js", "home.js", "mission.js", "boot.js"]


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _scripts() -> list[str]:
    return re.findall(r'<script[^>]*\ssrc="/?([^"?]+)(?:\?[^"]*)?"', INDEX)


def _nav() -> str:
    m = re.search(r'<nav slot="sidebar".*?</nav>', INDEX, re.S)
    assert m
    return m.group(0)


def _header() -> str:
    m = re.search(r'<header slot="header".*?</header>', INDEX, re.S)
    assert m
    return m.group(0)


# ───────── الصياغة والتحميل ─────────
@pytest.mark.skipif(NODE is None, reason="node مش موجود")
def test_every_script_parses_with_node_check():
    for s in _scripts():
        if not (STATIC / s).exists():
            pytest.fail(f"{s} مش موجود")
        r = subprocess.run([NODE, "--check", str(STATIC / s)], capture_output=True, text=True)
        assert r.returncode == 0, f"{s}: {r.stderr}"


def test_script_order_follows_contract_and_one_shared_version():
    scripts = [s for s in _scripts() if not s.startswith("vendor/")]
    assert _scripts()[0].startswith("vendor/zaki-ui/")
    pos = [scripts.index(s) for s in CONTRACT_ORDER]
    assert pos == sorted(pos), f"ترتيب السكربتات مخالف للعقد: {scripts}"
    assert scripts[-1] == "boot.js"
    # shell.js (تركيب المكتبات والمصنع) بعد ahat وقبل guide
    assert scripts.index("ahat.js") < scripts.index("shell.js") < scripts.index("guide.js")
    refs = re.findall(r'<(?:link|script)[^>]*?(?:src|href)="(/[^"]+)"', INDEX)
    vers = {r.rsplit("?v=", 1)[1] for r in refs}
    assert refs and len(vers) == 1 and int(next(iter(vers))) >= 30, refs        # كل الروابط بنفس رقم الإصدار، وأكبر من نسخة ما قبل الشكل الجديد
    v = next(iter(vers))
    assert f'href="/ornament.css?v={v}"' in INDEX and f'src="/ornament.js?v={v}"' in INDEX


# ───────── القائمة والترويسة ─────────
def test_sidebar_has_exactly_the_five_places():
    nav = _nav()
    routes = re.findall(r'class="zk-nav-item nav-item"[^>]*data-route="([\w-]+)"', nav)
    assert routes == ["home", "mission", "library", "factory", "performance"], routes
    for glyph, name in (("◆", "الرئيسية"), ("✦", "المهمة"), ("❖", "المكتبات"), ("⚙", "المصنع"), ("★", "الأداء")):
        assert re.search(rf"{glyph}</span>\s*{name}", nav), name
    # «النمط» و«خط الإنتاج» انحذفوا من القائمة، والإعدادات صارت ترس بالترويسة
    for gone in ("النمط<", "خط الإنتاج", 'data-route="pattern"', 'data-route="pipeline"', 'data-route="settings"'):
        assert gone not in nav, gone
    assert 'id="railStations"' in nav


def test_header_has_settings_gear_next_tour_and_theme():
    h = _header()
    assert re.search(r'<a [^>]*id="settingsBtn"[^>]*href="#/settings"', h) or re.search(r'href="#/settings"[^>]*id="settingsBtn"', h)
    assert 'data-route="settings"' in h
    assert 'id="guideNextBtn"' in h and "شو بعمل هلأ؟" in h
    assert 'id="tourBtn"' in h and "الجولة" in h
    assert 'id="themeBtn"' in h
    assert 'href="#/home"' in h                       # الشعار بيرجّع للرئيسية


def test_new_sections_and_containers():
    assert '<section id="v-mission" class="view" data-view="mission"><div id="missionBody"></div></section>' in INDEX
    for sid, view in (("v-home", "home"), ("v-libs", "libs"), ("v-factory", "factory")):
        assert re.search(rf'<section id="{sid}" class="view" data-view="{view}"', INDEX), sid
    for t in ("patterns", "products", "characters", "sounds"):
        assert re.search(rf'id="libsTabs".*?data-tab="{t}"', INDEX, re.S) and f'id="libs-{t}"' in INDEX, t
    for t in ("api", "local", "extension"):
        assert re.search(rf'id="facTabs".*?data-tab="{t}"', INDEX, re.S) and f'id="fac-{t}"' in INDEX, t
    for t in ("models", "keys", "media"):
        assert re.search(rf'id="facApiTabs".*?data-tab="{t}"', INDEX, re.S), t
    # الشاشات القديمة بتضل أقسام مصدر للتركيب
    for old in ("library", "pattern", "products", "studio", "characters", "models", "ahat", "extension", "production"):
        assert f'id="v-{old}"' in INDEX, old
    for i in ("homeHero", "homeWait", "homeMissions", "homeMethods", "plLibPanel", "statCards", "catList"):
        assert f'id="{i}"' in INDEX, i


def test_settings_lost_api_tabs_to_factory():
    seg = re.search(r'<div class="seg" id="setTabs".*?</div>', INDEX, re.S).group(0)
    for t in ("models", "keys", "media"):
        assert f'data-tab="{t}"' not in seg, t
        assert f'id="set-{t}"' in INDEX, t                 # العقد نفسها بتنتقل للمصنع (shell.js)
    for t in ("general", "crm", "ops", "analysis", "advanced"):
        assert f'data-tab="{t}"' in seg, t
    sh, st = _read("shell.js"), _read("settings.js")
    assert '"#set-models", "#set-keys", "#set-media"' in sh and "#fac-api" in sh
    assert "async function loadApiSection" in st and "loadApiSection(" in sh


def test_shell_mounts_old_screens_and_calls_old_views():
    sh = _read("shell.js")
    for src, dst in (("#v-library", "#libs-patterns"), ("#v-products", "#libs-products"), ("#v-characters", "#libs-characters"),
                     ("#v-ahat", "#libs-sounds"), ("#v-models", "#fac-local"),
                     ("#v-extension", "#fac-extension")):
        assert f'mountInto("{src}", "{dst}")' in sh, src
    assert "appendChild" in sh
    for v in ("VIEWS.library.enter", "VIEWS.products.enter", "VIEWS.characters.enter",
              "VIEWS.ahat.enter", "VIEWS.models.enter", "VIEWS.extension.enter"):
        assert v in sh, v
    assert "VIEWS.libs =" in sh and "VIEWS.factory =" in sh


# ───────── المسارات والتحويلات (بتشغيل boot.js بـ node مع بدائل خفيفة) ─────────
REDIRECTS = {
    "#/pipeline": "#/home",
    "#/": None,
    "#/library": "#/library/patterns",
    "#/library/queue": "#/library/patterns/queue",
    "#/library/coverage": "#/library/patterns/coverage",
    "#/library/patterns": None,
    "#/products": "#/library/products",
    "#/products/kama.json?tab=refs": "#/library/products/kama.json?tab=refs",
    "#/characters": "#/library/characters",
    "#/characters/ch_f_001": "#/library/characters/ch_f_001",
    "#/product-ref/kama": "#/library/products?ref=kama&tab=refs",
    "#/product-ref": "#/library/products?tab=refs",
    "#/library/characters?ref=kama": "#/library/products?ref=kama&tab=refs",
    "#/library/characters?ref=": "#/library/products?tab=refs",
    "#/ahat": "#/library/sounds",
    "#/models": "#/factory/local",
    "#/models/mm_001": "#/factory/local/mm_001",
    "#/extension": "#/factory/extension",
    "#/factory": "#/factory/api",
    "#/settings/keys": "#/factory/api/keys",
    "#/settings/crm": None,
    "#/pattern": "#/library/patterns",
    "#/pattern/ad_1": None,
    "#/studio": "#/mission/new?stage=2",
    "#/studio?step=3&script=a.json": "#/mission/a.json?stage=3&step=3",
    "#/studio?step=5&script=a.json": "#/mission/a.json?stage=4",
    "#/production": "#/home",
    "#/production/a.json?s=7": "#/mission/a.json?stage=5&s=7",
    "#/production/a.json?s=4": "#/mission/a.json?stage=4&s=4",
    "#/production/a.json?s=10": "#/mission/a.json?stage=7&s=10",
    "#/mission/new?stage=1": None,
    "#/home": None,
}

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8").replace(/\nboot\(\);\s*$/, "\n");
const store = {};
const ctx = {
  URLSearchParams, encodeURIComponent, decodeURIComponent, console,
  location: { hash: "" },
  localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } },
  document: { documentElement: { dataset: {}, setAttribute() {}, getAttribute() { return null; } } },
};
ctx.window = ctx; ctx.addEventListener = () => {};
ctx.$ = () => null; ctx.$$ = () => [];
vm.createContext(ctx);
vm.runInContext(src, ctx);
const cases = JSON.parse(process.argv[3]);
const out = {};
for (const h of cases) { ctx.location.hash = h; out[h] = vm.runInContext("legacyRedirect(parseHash())", ctx); }
out.__names = vm.runInContext("ROUTE_NAMES", ctx);
out.__legacy = vm.runInContext("LEGACY_ROUTES", ctx);
out.__themes = vm.runInContext("THEMES.map((t) => t.k)", ctx);
out.__migrate = vm.runInContext("['dark','light','calm','night','day','zzz'].map(normTheme)", ctx);
out.__stage = vm.runInContext("[1,2,3,4,5,6,7,8,9,10,11].map(stageOfStation)", ctx);
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def routing(tmp_path_factory):
    if NODE is None:
        pytest.skip("node مش موجود")
    h = tmp_path_factory.mktemp("boot") / "harness.js"
    h.write_text(HARNESS, encoding="utf-8")
    r = subprocess.run([NODE, str(h), str(STATIC / "boot.js"), json.dumps(list(REDIRECTS))], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_new_routes_exist(routing):
    assert set(routing["__names"]) >= {"home", "mission", "library", "factory", "performance", "settings", "pattern"}
    for gone in ("pipeline", "studio", "production", "products", "characters", "models", "ahat", "extension"):
        assert gone not in routing["__names"], gone
        assert gone in routing["__legacy"], gone


def test_legacy_routes_redirect_per_contract(routing):
    for h, want in REDIRECTS.items():
        assert routing[h] == want, f"{h}: {routing[h]!r} ≠ {want!r}"


def test_station_to_stage_table(routing):
    assert routing["__stage"] == [1, 3, 4, 4, 4, 5, 5, 5, 6, 7, 7]


def test_themes_night_day_with_migration(routing):
    assert routing["__themes"] == ["night", "day"]
    assert routing["__migrate"] == ["night", "day", "day", "night", "day", "night"]
    assert 'data-theme="night"' in INDEX
    boot = _read("boot.js")
    assert re.search(r"try\s*\{\s*saved = localStorage\.getItem", boot)


def test_boot_uses_mission_api_when_present():
    boot = _read("boot.js")
    assert "Mission.stageOfStation" in boot and "Mission.hash" in boot
    assert "#/mission/" in boot


# ───────── واجهة الدليل ─────────
GLOSSARY_TERMS = ["نمط", "بريف", "مرشّح", "محطة", "بوابة المدة", "الإضافة", "الخطّاف", "اللقطة", "الشخصية", "المونتاج"]


def test_guide_api_shape():
    g = _read("guide.js")
    assert re.search(r"window\.Guide\s*=\s*\{[^}]*\bstagePanel\b[^}]*\bterm\b[^}]*\bnext\b[^}]*\btour\b[^}]*\bpalette\b", g)
    assert "function stagePanel(hostEl" in g and "function term(key)" in g
    assert "async function next()" in g and "function tour(force)" in g and "function palette()" in g
    # Ctrl+K، والجولة 5 محطات أول زيارة فقط مع try/catch للتخزين
    assert "e.ctrlKey || e.metaKey" in g and '"k"' in g
    assert len(re.findall(r"\{ sel: ", g)) == 5
    assert 'store.get("vp-tour-done")' in g and 'store.set("vp-tour-done", "1")' in g
    for line in g.splitlines():
        if "localStorage." in line:
            assert "try" in line, f"تخزين بلا try/catch: {line.strip()}"
    # «شو بعمل هلأ؟» من /api/scripts + حالات المحطات
    assert "/api/scripts" in g and "/state`" in g


def test_glossary_covers_contract_terms_with_examples():
    g = _read("guide.js")
    block = g[g.index("const GLOSSARY"):g.index("const INDEX")]
    entries = re.findall(r'^\s+(\w+): \{ t: "([^"]+)", a: \[([^\]]*)\], d: "([^"]+)", ex: "([^"]+)" \},$', block, re.M)
    assert len(entries) >= 15
    names = set()
    for _k, t, aliases, d, ex in entries:
        names.add(t)
        names.update(re.findall(r'"([^"]+)"', aliases))
        assert len(d) > 20 and len(ex) > 8
    for term in GLOSSARY_TERMS:
        assert term in names, f"المصطلح «{term}» ناقص بالقاموس"


def test_term_marks_mounted_on_screen_titles():
    keys = re.findall(r'<span class="term-slot" data-term="(\w+)"></span>', INDEX)
    assert len(keys) >= 6
    g = _read("guide.js")
    for k in keys:
        assert re.search(rf"^\s+{k}: \{{ t:", g, re.M), k
    assert "mountTerms()" in g


# ───────── الرئيسية ─────────
def test_home_uses_existing_state_endpoints_and_moves_old_panels():
    h = _read("home.js")
    for ep in ("/api/scripts", "/state`", "/status`", "/ext/status`", "/api/review-queue"):
        assert ep in h, ep
    assert "loadStats()" in h and "loadDashUsage" not in h and "homeMoveOld" not in h           # الاستهلاك مكانه الإعدادات بس
    assert 'id="plUsagePanel"' not in INDEX and 'id="v-pipeline"' not in INDEX and "loadPipeline" not in _read("app.js")
    assert "renderMethods($(\"#homeMethods\"), false, true)" in h
    assert "awaiting_choice" in h and "failed" in h and "stop_code" in h
    assert "كمّل المهمة" in h and "missionHash(" in h and "stageOfStation(" in h
    for m in ("scripts", "studio_state", "script_status", "ext_status", "review_queue"):
        assert (STATIC / "mock" / f"{m}.json").exists(), m


# ───────── الهروب ─────────
SERVER_FIELDS = r"(display_name|title|note|label|product_name|stop_reason|reason|problem|line|name|file|text)"


@pytest.mark.parametrize("name", ["home.js", "guide.js", "shell.js"])
def test_no_unescaped_server_fields_in_templates(name):
    js = _read(name)
    # بس الأسطر اللي بتبني HTML (فيها «<»)؛ النصوص العادية بتتهرّب وقت العرض
    html_lines = "\n".join(ln for ln in js.splitlines() if "<" in ln)
    bad = re.findall(r"\$\{\s*(?!esc\()[\w.]+\." + SERVER_FIELDS + r"\s*\}", html_lines)
    assert not bad, f"{name}: حقول بدون esc(): {bad}"
    assert js.count("esc(") >= 4


def test_no_arabic_indic_digits_in_new_files():
    for f in ("home.js", "guide.js", "shell.js", "boot.js", "index.html"):
        assert not re.search("[٠-٩۰-۹]", _read(f)), f
