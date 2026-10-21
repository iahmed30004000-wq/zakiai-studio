"""فحص ثابت لواجهة المرحلة ٧ (web/static) — بدون متصفح ولا سيرفر ولا شبكة."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

# الأرقام العربية-الهندية والفارسية
AR_DIGITS = re.compile("[٠-٩۰-۹]")

SCREENS = ["library", "pattern", "products", "studio", "performance", "settings"]
TOPBAR_IDS = ["topbar", "tbCrm", "tbQueue", "tbBackup", "tbJobs", "jobBadge", "drawer", "jobList"]

# كل عناوين الـ API المطلوبة بعقد RESET_CONTRACT.md + القديمة اللي بتنضم
REQUIRED_API = [
    "/api/brief/schema", "/completeness", "/facts/sync", "/api/library/coverage",
    "/api/harvest/candidates", "/reject", "/api/harvest/plan", "/review-loop", "/status", "/versions",
    "/approve", "/api/crm/status", "/api/crm/config", "/api/crm/token", "/api/crm/sync", "/ad-name",
    "/api/performance/patterns", "/api/performance/scripts", "/api/performance/alerts", "/api/drafts",
    "/api/learning/last", "/api/learning/run", "/api/queue", "/api/queue/poll",
    "/api/backup/status", "/api/backup/run", "/api/backup/restore-test", "/api/backup/export-key",
    "/api/settings/spend-limits", "/api/scheduler/status", "/api/review-queue", "/resolve", "/api/taxonomy",
    "/api/patterns", "/api/products", "/api/scripts", "/api/matches", "/api/jobs", "/api/stats",
    "/api/extract/upload", "/api/extract/link", "/api/mine", "/api/generate", "/api/compare",
    "/api/tts", "/api/imagegen", "/api/stt", "/api/settings", "/api/prompts",
    "/api/connections", "/api/tasks", "/api/usage", "/api/performance", "/api/learn",
]


def _scripts() -> list[str]:
    return re.findall(r'<script[^>]*\ssrc="/?([^"?]+)(?:\?[^"]*)?"', INDEX)


def _js_all() -> str:
    return "\n".join((STATIC / s).read_text(encoding="utf-8") for s in _scripts())


def test_all_six_screens_and_settings_present():
    # إعادة البناء (ui_contract.md): القائمة صارت 5 أماكن + ترس الإعدادات؛ الشاشات القديمة بتضل أقسام مصدر
    # وبتنوصل إما بعنصر قائمة أو بتحويل مسار قديم بـ boot.js
    boot = (STATIC / "boot.js").read_text(encoding="utf-8")
    for s in SCREENS:
        assert re.search(rf'<section id="v-{s}"[^>]*data-view="{s}"', INDEX), f"شاشة {s} ناقصة"
        assert f'data-route="{s}"' in INDEX or f'case "{s}"' in boot, f"رابط التنقل لـ {s} ناقص"


def test_topbar_elements():
    for i in TOPBAR_IDS:
        assert f'id="{i}"' in INDEX, f"عنصر الشريط العلوي {i} ناقص"
    # الترويسة ثابتة: بقاعدة الاستوديو على خانة الغلاف
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert re.search(r'slot="header"\][^{]*\{[^}]*position:\s*sticky', css), "الترويسة لازم تكون ثابتة (sticky)"


def test_rtl_dark_and_no_external_resources():
    assert 'dir="rtl"' in INDEX and 'lang="ar' in INDEX
    assert 'data-theme="night"' in INDEX          # ثيم «ليالي الشرق» الافتراضي (كان dark)
    # لا CDN ولا خطوط خارجية: كل روابط الصفحة محلية
    assert not re.search(r'(?:src|href)="https?://', INDEX)
    css = (STATIC / "style.css").read_text(encoding="utf-8") + (STATIC / "theme.css").read_text(encoding="utf-8")
    assert "@import" not in css and "url(http" not in css and "fonts.googleapis" not in css
    assert not re.search(r"""fetch\(["'`]https?://""", _js_all())


def test_theme_layer_defined_and_linked():
    theme = (STATIC / "theme.css").read_text(encoding="utf-8")
    assert ":root" in theme
    names = set(re.findall(r"(--vp-[\w-]+)\s*:", theme))
    assert len(names) >= 60
    for essential in ["--vp-bg", "--vp-surface", "--vp-text", "--vp-brand", "--vp-danger", "--vp-ok",
                      "--vp-font-sans", "--vp-space-3", "--vp-radius-md"]:
        assert essential in names
    assert 'href="/theme.css?v=' in INDEX
    # theme.css يسبق style.css
    assert INDEX.index("/theme.css") < INDEX.index("/style.css")


def test_style_uses_only_theme_variables():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "style.css فيه لون ثابت — لازم كله من theme.css"
    assert not re.search(r"rgba?\(", css)
    theme = (STATIC / "theme.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--vp-[\w-]+)\s*:", theme))
    used = set(re.findall(r"var\((--vp-[\w-]+)", css))
    assert used <= defined, f"متغيرات مستخدمة وغير معرّفة: {sorted(used - defined)}"


def test_every_asset_has_version_and_exists():
    # روابط <link> و<script> فقط (روابط سبرايت الأيقونات #… مش ملفات مستقلة)
    refs = re.findall(r'<(?:link|script)[^>]*?(?:src|href)="(/[^"]+)"', INDEX)
    assert refs
    versions = set()
    for r in refs:
        m = re.match(r"^/([^?]+)\?v=(\d+)$", r)
        assert m, f"الرابط {r} بلا ?v="
        assert (STATIC / m.group(1)).exists(), f"الملف {m.group(1)} مش موجود"
        versions.add(m.group(2))
    assert len(versions) == 1, f"أرقام الإصدار مختلفة: {versions}"
    assert int(next(iter(versions))) >= 5, "لازم ترفع رقم ?v= عن النسخة القديمة (4)"


def test_no_arabic_indic_digits_in_static_files():
    files = [STATIC / "index.html", STATIC / "style.css", STATIC / "theme.css"]
    files += [STATIC / s for s in _scripts()]
    files += list((STATIC / "mock").glob("*.json"))
    for f in files:
        assert not AR_DIGITS.search(f.read_text(encoding="utf-8")), f"أرقام عربية-هندية في {f.name}"


def test_app_js_has_all_contract_endpoints():
    js = _js_all()
    missing = [p for p in REQUIRED_API if p not in js]
    assert not missing, f"عناوين API ناقصة: {missing}"


def test_app_js_is_first_script_and_handles_absent_api():
    assert [x for x in _scripts() if not x.startswith("vendor/")][0] == "app.js"
    js = _js_all()
    assert "الخدمة غير مفعّلة بعد" in js          # حالة فاضية عربية لغياب الـ API
    assert "class ApiError" in js and "unavailable" in js
    assert 'get("mock") === "1"' in js            # وضع المحاكاة


def test_esc_used_and_no_raw_innerhtml_of_api_fields():
    js = _js_all()
    assert "const esc = " in js
    # أي قالب innerHTML فيه ${...} من بيانات API لازم يمر بـ esc/دوال معروفة — فحص خفيف: عدد esc كبير
    assert js.count("esc(") > 300


def test_mock_files_valid_json_and_cover_contract():
    d = STATIC / "mock"
    files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.json")}
    for need in ["crm_status", "coverage", "brief_schema", "completeness", "harvest", "scripts", "script_status",
                 "script_versions", "ad_name", "perf_patterns", "perf_scripts", "perf_alerts", "drafts",
                 "learning_last", "backup_status", "scheduler_status", "queue", "spend_limits", "matches",
                 "patterns", "pattern_detail", "taxonomy", "review_queue", "products", "product_detail"]:
        assert need in files, f"ملف محاكاة ناقص: {need}"
    cs = files["crm_status"]
    for k in ["configured", "token_set", "base_url", "connected", "last_sync", "pending_queue", "last_backup",
              "days_since_backup", "backup_alert"]:
        assert k in cs
    cov = files["coverage"]
    assert {"quota", "active_categories", "matrix", "per_category", "gaps"} <= set(cov)
    assert all({"scene_blueprint"} <= set(p) for p in files["pattern_detail"].values())
    for f, st in files["script_status"].items():
        assert {"status", "blockers", "rounds"} <= set(st)


@pytest.mark.skipif(shutil.which("node") is None, reason="node مش موجود")
def test_js_syntax_ok():
    for s in _scripts():
        r = subprocess.run(["node", "--check", str(STATIC / s)], capture_output=True, text=True)
        assert r.returncode == 0, f"{s}: {r.stderr}"


# ───────── الغلاف (zaki-ui) وشاشة الإنتاج ─────────
def test_shell_and_vendor_package():
    assert "<zk-app-shell" in INDEX and 'slot="header"' in INDEX and 'slot="sidebar"' in INDEX and 'slot="content"' in INDEX
    assert "<zk-app-switcher" in INDEX and 'class="zk"' in INDEX
    v = STATIC / "vendor" / "zaki-ui"
    for f in ("zaki-ui.all.css", "zaki-ui.all.js", "icons.svg", "tokens.css", "fonts.css", "VERSION"):
        assert (v / f).exists(), f
    assert (v / "VERSION").read_text().strip().startswith("0.")
    # الحزمة قائمة بذاتها
    assert "--sys-" not in (v / "tokens.css").read_text(encoding="utf-8")


def test_theme_is_only_a_mapping_to_package_tokens():
    theme = (STATIC / "theme.css").read_text(encoding="utf-8")
    # «ليالي الشرق» (ui_contract.md): theme.css صار مصدر قيم الثيمين (night/day) وبيغذّي --zk-* (مش العكس)
    assert '[data-theme="night"]' in theme and '[data-theme="day"]' in theme
    assert "--zk-color-brand:" in theme and "--zk-color-surface-page:" in theme
    tokens = (STATIC / "vendor/zaki-ui/tokens.css").read_text(encoding="utf-8")
    for name in set(re.findall(r"var\((--zk-[a-z0-9-]+)", theme)):
        assert f"{name}:" in tokens, f"{name} مش معرّف بالحزمة"


def test_production_screen_wiring():
    assert 'id="v-production"' in INDEX and 'id="railStations"' in INDEX and 'case "production"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    js = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/state", "/voice", "/voice/approve", "/voice/audio", "/timeline", "/timeline/boundary"):
        assert f"/api/studio/${{enc(" in js and ep in js, ep
    for st in ("not_started", "running", "awaiting_choice", "approved", "failed", "stale"):
        assert st in js
    assert '"production"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    assert (STATIC / "mock" / "studio_timeline.json").exists()


def test_characters_and_stations_3_6_wiring():
    assert 'id="v-characters"' in INDEX and 'case "characters"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    ch = (STATIC / "characters.js").read_text(encoding="utf-8")
    for ep in ("/api/characters", "/sheet/", "/consent", "/retire"):
        assert ep in ch, ep
    prod = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/characters`", "/character`", "/shots/build", "/shots/approve", "/prompt`"):
        assert ep in prod, ep
    assert '"characters"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    for m in ("characters", "studio_characters", "studio_shots"):
        assert (STATIC / "mock" / f"{m}.json").exists(), m


def test_stations_7_8_and_product_ref_wiring():
    assert 'id="v-product-ref"' not in INDEX and 'id="prodRefSheet"' in INDEX      # ملف المنتج المرجعي صار بصفحة المنتج بس
    prod = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/images/info", "/images/generate", "/images/approve", "/match/approve", "/composite", "/verdict", "/check", "/choose"):
        assert ep in prod, ep
    pr = (STATIC / "productref.js").read_text(encoding="utf-8")
    assert "/api/product-refs/" in pr and "/angle/" in pr
    assert '"product-ref"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    for m in ("studio_images_info", "product_ref"):
        assert (STATIC / "mock" / f"{m}.json").exists(), m


def test_station_9_and_models_registry_wiring():
    assert 'id="v-models"' in INDEX and 'case "models"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    prod = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/motion/info", "/motion/run", "/motion/approve", "/motion/choose", "/motion-desc", "/clip/"):
        assert ep in prod, ep
    mj = (STATIC / "models.js").read_text(encoding="utf-8")
    assert "/api/motion-models" in mj and "JSON" in mj
    assert '"models"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    for m in ("motion_info", "motion_models"):
        assert (STATIC / "mock" / f"{m}.json").exists(), m


def test_station_10_and_ahat_wiring():
    assert 'id="v-ahat"' in INDEX and 'case "ahat"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    prod = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/montage/info", "/montage/render", "/ambience", "/render/"):
        assert ep in prod, ep
    ah = (STATIC / "ahat.js").read_text(encoding="utf-8")
    assert "/api/ahat" in ah and "heard" in ah
    assert '"ahat"' in (STATIC / "boot.js").read_text(encoding="utf-8")
    for m in ("montage_info", "ahat"):
        assert (STATIC / "mock" / f"{m}.json").exists(), m


def test_station_11_launch_wiring_and_launch_token_field():
    prod = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/launch/info", "/launch${url}", "/refresh", "/cancel", "confirm: true"):
        assert ep in prod, ep
    assert 'rel="noopener noreferrer"' in prod          # رابط العمليات الخارجي
    assert 'id="crmLaunchToken"' in INDEX and 'type="password"' in INDEX
    st = (STATIC / "settings.js").read_text(encoding="utf-8")
    assert "launch_token" in st and "/api/crm/launch-token" in st
    assert "launch_info" and (STATIC / "mock" / "launch_info.json").exists()


def test_station_7_extension_panel_wiring():
    prod = (STATIC / "production.js").read_text(encoding="utf-8")
    for ep in ("/ext/status", "/ext/control", "/api/ext/token", "/api/ext/token/rotate"):
        assert ep in prod, ep
    assert "بتخالف شروطهم" in prod and "ما في استئناف تلقائي" in prod and "بتتجاوز" in prod
    for m in ("ext_status", "ext_token"):
        assert (STATIC / "mock" / f"{m}.json").exists(), m
