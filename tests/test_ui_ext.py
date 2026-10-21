"""فحص ثابت لواجهة الإضافة متعددة المواقع (web/static) — بدون متصفح ولا سيرفر ولا شبكة.
المرجع: ext_contract.md (جانب الواجهة)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
MOCK = STATIC / "mock"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
KINDS = ["voice", "image", "video", "ahat", "music"]
SITES = ["gemini", "chatgpt", "aistudio", "flow", "flowmusic", "elevenlabs"]
AR_DIGITS = re.compile("[٠-٩۰-۹]")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _mock(name: str):
    return json.loads((MOCK / f"{name}.json").read_text(encoding="utf-8"))


def _scripts() -> list[str]:
    return re.findall(r'<script[^>]*\ssrc="/?([^"?]+)(?:\?[^"]*)?"', INDEX)


# ───────── الصياغة والتحميل ─────────
@pytest.mark.skipif(shutil.which("node") is None, reason="node مش موجود")
def test_all_scripts_parse_with_node_check():
    for s in _scripts():
        r = subprocess.run(["node", "--check", str(STATIC / s)], capture_output=True, text=True)
        assert r.returncode == 0, f"{s}: {r.stderr}"


def test_ext_script_loaded_between_models_and_ahat_with_same_version():
    scripts = _scripts()
    assert "ext.js" in scripts
    assert scripts.index("production.js") < scripts.index("ext.js") < scripts.index("ahat.js") < scripts.index("boot.js")
    versions = set(re.findall(r'<(?:link|script)[^>]*?(?:src|href)="/[^"?]+\?v=(\d+)"', INDEX))
    assert len(versions) == 1, versions


def test_extension_route_nav_and_section_wired():
    # القائمة الجديدة: الإضافة صارت تبويب بالمصنع (#/factory/extension) والمسار القديم بيتحوّل بـ boot.js
    assert 'case "extension"' in _read("boot.js") and 'id="v-extension"' in INDEX and 'id="extBody"' in INDEX
    assert 'id="ahExt"' in INDEX
    assert '"extension"' in _read("boot.js")
    assert "VIEWS.extension" in _read("ext.js")


# ───────── النقاط: بس نقاط العقد §2 المحلية، وبلا توكن ─────────
def test_ui_uses_only_local_contract_endpoints_and_no_extension_side_endpoints():
    ui = _read("ext.js") + _read("production.js") + _read("ahat.js")
    for ep in ("/ext/status", "/ext/control", "/ext/requests", "/ext/retry", "/api/ext/selftest", "/api/ext/download", "/api/ext/token"):
        assert ep in ui, ep
    # نقاط الإضافة (بتوكن) ما بتنلمس من الواجهة
    for bad in ("/ext/queue", "/ext/result", "/ext/tasks", "/ext/asset", "/ext/config", "/ext/log", "/ext/stop"):
        assert bad not in ui, f"الواجهة ما لازم تستدعي {bad}"
    assert "X-VP-Ext-Token" not in ui
    assert not re.search(r"""fetch\(["'`]https?://""", ui)


def test_control_body_fields_and_retry_and_requests_shape():
    prod, ext, ah = _read("production.js"), _read("ext.js"), _read("ahat.js")
    for f in ("step_mode", "only", "one_by_one", "kind", "command", "mode", "site"):
        assert f in prod, f
    assert "task_id" in ext and "method: \"DELETE\"" in ext and "/ext/retry" in ext
    for f in ("prompt", "name", "mood", "seconds"):
        assert f in ah, f
    assert '"POST"' in ah and "/ext/requests" in ah


def test_no_deferred_features_buttons():
    """مؤجّل بقرار صريح: تعديل جزء من الصورة (قناع) واستنساخ الصوت."""
    ui = _read("ext.js") + _read("production.js") + _read("ahat.js")
    for word in ("استنساخ", "قناع", "inpaint", "voice_clone", "clone"):
        assert word not in ui, word


# ───────── النصوص الإلزامية ─────────
def test_required_arabic_warnings_present():
    prod, ext, ah = _read("production.js"), _read("ext.js"), _read("ahat.js")
    assert "بتخالف شروطهم" in prod and "ما في استئناف تلقائي" in prod and "بتتجاوز" in prod   # قديمة (test_phase7_static)
    assert "ولّد بالإضافة (ElevenLabs)" in prod and "حرّك بـ Flow (الإضافة)" in prod
    assert "لقطة" in prod and "مع مراجعة" in prod and "الكل مرة وحدة" in prod
    assert "حساب ثانوي" in ext and "طبيعي" in ext and "بتخالف شروط" in ext
    assert "غير مجرّب" in ext and "وضع المطوّر" in ext and "chrome://extensions" in ext
    assert "بلا غناء ولا كلام" in ah and "غير معتمد" in ah
    # كمّل بيدوي: ما في استدعاء تلقائي لأمر run
    assert 'set({ command: "run" })' in prod and "confirm(" in prod
    assert prod.count('command: "run"') == 1


def test_all_three_speeds_with_warning_texts():
    ext = _read("ext.js")
    for k in ("natural", "fast", "max"):
        assert re.search(rf"\b{k}:", ext), k
    assert "EXT_SPEEDS" in ext and "mode_warning" in _read("production.js")


def test_motion_candidate_from_extension_is_marked():
    prod = _read("production.js")
    assert "isExtCand" in prod and "من الإضافة" in prod
    mi = _mock("motion_info")
    ext_c = [c for s in mi["shots"] for c in s["candidates"] if str(c.get("provider", "")).startswith("extension")]
    assert ext_c, "مرشّح من الإضافة ناقص بملف المحاكاة"


# ───────── الأمان: هروب النصوص ─────────
RISKY = re.compile(r"\b(?:r|c|l|s|x|t|m|d|p|res)\.(name|prompt|id|error|reason|stop_reason|stop_code|msg|shot|step|label|newUrl|hosts|mood|mood_label|kind|site|task_id|shot_id|model_name)\b")


def _unescaped_server_fields(src: str) -> list[str]:
    """حقول قادمة من الخادم داخل ${...} بلا esc() حواليها (ما عدا استخدامها كشرط/مقارنة)."""
    bad = []
    for m in RISKY.finditer(src):
        i = m.start()
        j = src.rfind("${", 0, i)
        if j < 0 or "}" in src[j:i].replace("${", "").split("`")[-1] and False:
            continue
        head = src[j:i]
        if "esc(" in head or "enc(" in head or "extSite(" in head or "extKind(" in head:
            continue
        tail = src[m.end():m.end() + 24]
        if re.match(r"\s*(\?|&&|===|!==|\|\||\)\s*\?|\)\s*\))", tail) or re.match(r"\s*\|\|", tail):
            continue
        # خارج قالب (كود عادي): ما يهمنا
        if j < 0 or src.count("`", 0, i) % 2 == 0:
            continue
        bad.append(src[j:m.end() + 20].replace(chr(10), " ")[:110])
    return bad


def test_server_fields_are_escaped_in_templates():
    for name in ("ext.js", "ahat.js"):
        bad = _unescaped_server_fields(_read(name))
        assert not bad, f"{name}: حقول من الخادم بلا esc: {bad}"
    prod = _read("production.js")
    ext_part = prod[prod.index("مسار إضافة المتصفح (محطات 4 و7 و9)"):]
    bad = _unescaped_server_fields(ext_part)
    assert not bad, f"production.js (الإضافة): {bad}"


def test_no_raw_innerhtml_assignment_from_variables():
    for name in ("ext.js", "ahat.js"):
        for line in _read(name).splitlines():
            m = re.search(r"innerHTML\s*=\s*(.+)", line)
            if m:
                assert m.group(1).lstrip().startswith(("`", '"', "errBox(", "extReqList(")), f"{name}: {line.strip()}"


def test_mock_probe_contains_xss_string_and_is_escaped_by_design():
    reqs = _mock("ext_requests")["requests"]
    assert any("<script>" in r["prompt"] or "<img" in r["name"] for r in reqs)
    assert "esc(r.prompt" in _read("ext.js") and "esc(r.name" in _read("ext.js")


def test_no_tokens_or_keys_in_static_files():
    pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|xi-api-key|Bearer\s+[A-Za-z0-9._-]{20,})")
    for p in list(STATIC.glob("*.js")) + list(STATIC.glob("*.html")) + list(MOCK.glob("*.json")):
        assert not pat.search(p.read_text(encoding="utf-8")), p.name
    assert _mock("ext_token")["token"].startswith("MOCK")


def test_no_arabic_indic_digits_and_no_hardcoded_colors_in_new_code():
    for name in ("ext.js", "ahat.js", "production.js", "app.js"):
        assert not AR_DIGITS.search(_read(name)), name
    for p in MOCK.glob("ext_*.json"):
        assert not AR_DIGITS.search(p.read_text(encoding="utf-8")), p.name
    css = _read("style.css")
    ext_css = css[css.index("الإضافة متعددة المواقع"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", ext_css)
    used = set(re.findall(r"var\((--vp-[\w-]+)", ext_css))
    defined = set(re.findall(r"(--vp-[\w-]+)\s*:", _read("theme.css")))
    assert used <= defined, used - defined


def test_mobile_360_no_horizontal_overflow_rules():
    css = _read("style.css")
    ext_css = css[css.index("الإضافة متعددة المواقع"):]
    assert "overflow-wrap: anywhere" in ext_css and "minmax(min(100%" in ext_css
    assert 'class="tbl stack"' in _read("ext.js") and "data-label" in _read("ext.js")


# ───────── ملفات المحاكاة ─────────
def test_mock_ext_status_has_new_contract_fields_for_both_variants():
    for name, want_cmd in (("ext_status", "stop"), ("ext_status_running", "run")):
        d = _mock(name)
        assert {"control", "queue", "next", "modes", "mode_warning", "log", "kinds", "requests", "sites"} <= set(d), name
        assert set(d["kinds"]) == set(KINDS)
        assert all(isinstance(v, int) for v in d["kinds"].values())
        assert set(d["modes"]) == {"natural", "fast", "max"}
        assert set(d["sites"]) == set(SITES)
        for s, v in d["sites"].items():
            assert {"kinds", "verified", "adapter_version"} <= set(v), s
            assert isinstance(v["verified"], bool)
        c = d["control"]
        assert c["command"] == want_cmd
        assert {"kind", "site", "mode", "step_mode", "only", "stop_code", "stop_reason", "position"} <= set(c)
        assert c["step_mode"] in ("all", "one_by_one") and c["kind"] in KINDS
    stopped, running = _mock("ext_status")["control"], _mock("ext_status_running")["control"]
    assert stopped["stop_code"] == "verification" and stopped["stop_reason"] and stopped["position"]
    assert running["only"] and isinstance(running["only"], list) and not running["stop_code"]
    # وجود الحالتين: مُتحقَّق ومش مُتحقَّق
    verified = {v["verified"] for v in _mock("ext_status")["sites"].values()}
    assert verified == {True, False}
    # كل موقع بنوعه حسب العقد §1
    sites = _mock("ext_status")["sites"]
    assert set(sites["elevenlabs"]["kinds"]) == {"voice", "ahat"} and sites["flowmusic"]["kinds"] == ["music"]
    assert set(sites["flow"]["kinds"]) == {"video", "image"}


def test_mock_selftest_has_ok_and_failed_rows_with_dates():
    res = _mock("ext_selftest")["results"]
    assert any(r["ok"] for r in res) and any(not r["ok"] and r["missing"] for r in res)
    for r in res:
        assert {"site", "kind", "ok", "adapter_version", "missing", "checked_at"} <= set(r)
        assert r["site"] in SITES and r["kind"] in KINDS and isinstance(r["missing"], list)
        assert r["checked_at"].startswith("@now")


def test_mock_requests_cover_ahat_music_and_all_states():
    reqs = _mock("ext_requests")["requests"]
    assert {"ahat", "music"} <= {r["kind"] for r in reqs}
    assert {"pending", "running", "done", "failed"} <= {r["status"] for r in reqs}
    for r in reqs:
        assert {"id", "kind", "prompt", "name", "mood", "seconds", "status"} <= set(r)
    music = [r for r in reqs if r["kind"] == "music" and "<" not in r["prompt"]]
    assert all("no vocals" in r["prompt"] for r in music)      # الموسيقى دايماً بلا غناء


def test_app_js_mock_handles_all_new_endpoints():
    app = _read("app.js")
    for token in ("ext_status_running", "ext_selftest", "ext_requests", "/api/ext/selftest",
                  "ext\\/control", "ext\\/requests", "ext\\/retry", "mockExtStatus", "mockExtWrite"):
        assert token in app, token
    assert 'get("ext") === "running"' in app


def test_all_mock_files_valid_json():
    for p in MOCK.glob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))
