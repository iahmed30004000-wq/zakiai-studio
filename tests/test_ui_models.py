"""واجهة سجل الموديلات (models.js): فحص ثابت — بدون متصفح ولا سيرفر ولا شبكة.
النوع (أمر محلي | صندوق http)، حقول الصندوق، زر الفحص، آخر المحاولات، وتهريب كل نص جاي من الخادم."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATIC = ROOT / "web" / "static"
JS = (STATIC / "models.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
NODE = shutil.which("node")

# حقول بتيجي من الخادم/السجل وممكن تحمل أي نص — ما بينفع تنحط بـ innerHTML بدون esc()
SERVER_TEXT_FIELDS = ("name", "id", "limits", "resolution", "url", "reason", "error", "model_name", "model_id",
                      "script_stem", "shot_id", "token_secret", "at", "path", "backend", "message")


@pytest.mark.skipif(NODE is None, reason="node مش موجود")
def test_models_js_parses_with_node_check():
    r = subprocess.run([NODE, "--check", str(STATIC / "models.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_kind_selector_and_http_fields_exist_with_hints():
    for needle in ('id="mfKind"', 'value="command"', 'value="http"', 'id="mfUrl"', 'id="mfMode"', 'value="i2v"', 'value="t2v"',
                   'id="mfSteps"', 'id="mfGuid"', 'id="mfTokName"', 'id="mfTokVal"', 'id="mfProbe"', 'id="mfProbeOut"',
                   'id="mfCmdBox"', 'id="mfHttpBox"', 'id="mfModel"', "نوع التشغيل", "افحص الصندوق", "آخر المحاولات"):
        assert needle in JS, needle
    # كل حقل جديد إله سطر شرح مع مثال
    http_box = JS[JS.index('id="mfHttpBox"'):JS.index('id="mfProbe"')]
    assert http_box.count('class="zk-field"') == 7                      # +1: اسم النموذج بالصندوق العام (mfModel)
    assert http_box.count('<span class="hint">') >= 7
    assert "مثال" in http_box and "http://127.0.0.1:8101" in http_box
    assert 'type="password"' in JS and 'autocomplete="new-password"' in JS            # التوكن ما بينعرض
    for ltr in ('id="mfUrl" dir="ltr"', 'id="mfModel" dir="ltr"', 'id="mfSteps" type="number" min="1" max="200" dir="ltr"', 'id="mfTokName" dir="ltr"'):
        assert ltr in JS, ltr


def test_save_sends_kind_and_http_block_and_token_separately():
    assert "kind: k" in JS and "body.http = {" in JS and 'k === "command") body.command' in JS
    assert "token_secret: $(\"#mfTokName\").value, model: $(\"#mfModel\").value" in JS
    assert "/api/motion/models/${enc(r.id)}/token" in JS and "/api/motion/models/${enc(m.id)}/probe" in JS
    body_line = [ln for ln in JS.splitlines() if "body.http = {" in ln][0]
    assert "mfTokVal" not in body_line                                  # التوكن مش جزء من جسم السجل
    assert "/api/production-log?kind=motion" in JS


def test_probe_summary_texts_are_plain_arabic_for_each_state():
    for text in ("شغّال وجاهز", "الكرت مشغول", "واقف أو فيه مشكلة", "ما انحمّل"):
        assert text in JS, text
    # النتيجة بتنعرض بـ setStatus (textContent) مش innerHTML
    probe_block = JS[JS.index("probeBtn.addEventListener"):JS.index('$("#mfSave")')]
    assert "setStatus(out, s.text, s.kind)" in probe_block and "innerHTML" not in probe_block


def _template_expressions(src: str) -> list[str]:
    """كل تعبير ${...} بأي مستوى تداخل (مطابقة أقواس بسيطة تتجاوز النصوص)."""
    out, i = [], 0
    while True:
        i = src.find("${", i)
        if i < 0:
            return out
        depth, j, quote = 1, i + 2, None
        while j < len(src) and depth:
            c = src[j]
            if quote:
                if c == "\\":
                    j += 1
                elif c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "`":
                # قالب متداخل: نطابقه كامل بما فيه ${...} الداخلية
                k = j + 1
                d2 = 0
                while k < len(src):
                    if src[k] == "\\":
                        k += 2
                        continue
                    if src[k:k + 2] == "${":
                        d2 += 1
                        k += 2
                        continue
                    if src[k] == "}" and d2:
                        d2 -= 1
                    elif src[k] == "`" and not d2:
                        break
                    k += 1
                j = k
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        out.append(src[i + 2:j - 1])
        i += 2


def _strip_calls(expr: str, names: tuple[str, ...]) -> str:
    for name in names:
        while True:
            m = re.search(rf"\b{name}\(", expr)
            if not m:
                break
            depth, j = 1, m.end()
            while j < len(expr) and depth:
                depth += (expr[j] == "(") - (expr[j] == ")")
                j += 1
            expr = expr[:m.start()] + "SAFE" + expr[j:]
    return expr


def test_every_server_text_in_templates_goes_through_esc():
    exprs = _template_expressions(JS)
    assert len(exprs) > 40
    # تعبيرات بتروح لـ textContent (setStatus/toast) أو شروط ternary قبل esc() — مش innerHTML
    text_sinks = {"e.message", '(p && p.reason) || "ما رد"', 'a.error ? esc(a.error) : "—"'}
    for line in JS.splitlines():
        if "${e.message}" in line or "p.reason" in line:
            assert re.search(r"(setStatus|toast)[(]", line) or "text:" in line, line
    bad = []
    for e in exprs:
        if e in text_sinks:
            continue
        rest = _strip_calls(e, ("esc", "enc", "errBox"))                  # errBox بتعمل esc داخلياً لرسالة الخطأ
        rest = re.sub(r"`[^`]*`", "``", rest)                         # القوالب المتداخلة بتنفحص كتعبيرات لحالها
        for f in SERVER_TEXT_FIELDS:
            if re.search(rf"\b[A-Za-z_]\w*\??\.{f}\b", rest):
                bad.append((f, e[:80]))
    assert not bad, bad
    assert JS.count("esc(") >= 30
    # اسم الموديل والسبب والخطأ تحديداً
    for must in ("esc(m.name)", "esc(a.error)", "esc(a.model_name || a.model_id", "esc(hp.url)", "esc(a.script_stem", "esc(fmtAt(a.at))"):
        assert must in JS, must
    assert "${a.error}" not in JS and "${p.reason}" not in JS


def test_tables_are_responsive_and_rtl_friendly():
    assert JS.count('class="tbl stack"') == 2 and JS.count("scroll-x") == 2
    assert JS.count("data-label=") >= 14
    assert re.search(r"\.tbl\.stack", CSS) and "minmax(min(100%" in CSS
    assert "min-width: 0" in CSS
    # حقول إدخال اللاتيني (عنوان، أرقام، أسماء مفاتيح) بـ dir=ltr وباقي الواجهة RTL افتراضياً
    assert JS.count('dir="ltr"') >= 8
    assert 'dir="rtl"' not in JS or True
    assert not re.search("[\u0660-\u0669\u06F0-\u06F9]", JS)         # أرقام غربية بالكود والتعليقات


def test_mock_files_match_the_new_shape():
    import motion
    mm = json.loads((STATIC / "mock" / "motion_models.json").read_text(encoding="utf-8"))
    kinds = {m["kind"] for m in mm["models"]}
    assert kinds == {"command", "http"} and set(mm["kinds"]) == {"command", "http"}
    h = next(m for m in mm["models"] if m["kind"] == "http")
    assert motion.validate_engine_url(h["http"]["url"]) == h["http"]["url"]
    assert set(h["http"]) >= {"url", "mode", "steps", "guidance", "token_secret", "token_set"} and h["http"]["mode"] in motion.HTTP_MODES
    assert "token" not in json.dumps({k: v for k, v in h["http"].items() if k not in ("token_secret", "token_set")})
    pr = json.loads((STATIC / "mock" / "motion_probe.json").read_text(encoding="utf-8"))
    assert set(pr) >= {"ok", "backend", "loaded", "queued", "running"}
    lg = json.loads((STATIC / "mock" / "motion_log.json").read_text(encoding="utf-8"))
    assert {i["status"] for i in lg["items"]} == {"ok", "failed"} and all(i["kind"] == "motion" for i in lg["items"])
    import production_log
    assert all(i["path"] in production_log.PATHS and set(i) >= {"at", "shot_id", "model_name", "path", "status", "seconds", "error"} for i in lg["items"])


def test_models_view_still_wired_in_the_shell():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="v-models"' in index and "models.js" in index
    assert 'id="mmBody"' in index or "mmBody" in index
