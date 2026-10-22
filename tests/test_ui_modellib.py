"""واجهة «مكتبة النماذج» (modellib.js): فحص ثابت + تشغيل بـ node + عقد الحمولات مع الخادم الحقيقي + المحاكاة. بلا متصفح."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_ui_globals import is_closed_scope, scripts_in_order  # noqa: E402

import model_library as ml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
AR_DIGITS = re.compile("[٠-٩۰-۹]")
NODE = shutil.which("node") is not None


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


JS = _read("modellib.js")


# ───────── الصياغة والنطاق والترتيب والعلامات ─────────
@pytest.mark.skipif(not NODE, reason="node مش موجود")
@pytest.mark.parametrize("name", ["modellib.js", "app.js", "shell.js", "guide.js", "settings.js"])
def test_node_check(name):
    r = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True)
    assert r.returncode == 0, f"{name}: {r.stderr}"


def test_closed_scope_exposing_only_window_model_lib():
    assert is_closed_scope(JS)
    assert "window.ModelLib = {" in JS and len(re.findall(r"\bwindow\.\w+\s*=", JS)) == 1
    assert "VIEWS.models.enter = async function" in JS and "prev.call(VIEWS.models, p)" in JS      # بنلفّ دخول تبويب المصنع ولا بنستبدله


def test_script_order_markup_and_tab_name():
    names = scripts_in_order()
    assert names.index("models.js") < names.index("modellib.js") < names.index("shell.js")
    idx = _read("index.html")
    assert re.search(r'<script src="/modellib\.js\?v=\d+"></script>', idx)
    assert idx.index('id="mlBody"') < idx.index('id="mmBody"')                                    # المكتبة فوق جدول التحريك
    assert '<button type="button" data-tab="local">مكتبة النماذج</button>' in idx and 'id="fac-local"' in idx   # المعرّف بيضل
    assert "مكتبة النماذج" in _read("shell.js") and "/api/model-library" in _read("shell.js")        # بطاقة الحالة بتعدّ المكتبة
    g = _read("guide.js")
    assert "#/factory/local" in g and "مكتبة النماذج" in g


def test_no_arabic_indic_digits_no_keys_no_raw_colours():
    pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})")
    assert not AR_DIGITS.search(JS) and not pat.search(JS)
    css = _read("style.css")
    block = css[css.index("مكتبة النماذج (modellib.js)"):]
    assert ".ml-grid" in block and ".ml-wiz" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", block), "ألوان مكتوبة بالـ CSS (لازم var(--vp-*))"


RISKY = re.compile(r"\$\{\s*(?!esc\()[\w.]+\.(title|name|label|text|path|message|msg|id|url|model|reason|note|link_label|task_label|summary|builtin|unusable_reason)\s*\}")


def test_server_text_goes_through_esc():
    bad = [ln.strip() for ln in JS.splitlines() if "<" in ln and RISKY.search(ln)]
    assert not bad, bad
    assert JS.count("esc(") >= 40
    for attr in ("value", "src", "data-id", "id", "for", "placeholder"):
        for m in re.finditer(rf'\b{attr}="\$\{{([^}}]*)\}}"', JS):
            assert m.group(1).startswith(("esc(", "k")) or m.group(1) in ("id", "name", "u", "ph"), (attr, m.group(1))      # ph = ثوابت من الكود (مثال: "10")


def test_every_data_attribute_action_has_a_handler():
    acts = set(re.findall(r'data-act="(\w+)"', JS))
    handled = set(re.findall(r"^\s+(\w+): \(\) =>", JS[JS.index("const run = {"):JS.index("if (run) run();")], re.M)) | set(re.findall(r"\b(add|builtin|default|try|toggle|edit|del): \(\)", JS))
    assert {"add", "builtin", "default", "try", "toggle", "edit", "del"} <= handled
    assert acts - {"fb", "pin"} <= handled, acts - handled
    steps = set(re.findall(r'data-w="(\w+)"', JS))
    wired = set(re.findall(r'act === "(\w+)"', JS))
    assert steps <= wired, steps - wired


def test_endpoints_used_by_modellib_exist_on_the_server_and_in_the_mock():
    from web import app as webapp
    server = {re.sub(r"\{[^}]+\}", "{}", p) for p in webapp.app.openapi()["paths"] if p.startswith("/api/model-library")}
    src = JS.replace("${API}", "/api/model-library")
    src = re.sub(r"\$\{[^}]*\}", "{}", src)
    used = {m.group(1).split("?")[0].rstrip("/") for m in re.finditer(r"[`\"'](/api/model-library[^`\"']*)[`\"']", src)}
    assert len(used) >= 8, used
    assert used <= server, used - server
    app = _read("app.js")
    block = app[app.index("async function mockLibHook("):app.index("async function mockApi(")]
    for key in ("/templates", "/probe", "/models", "/test/inputs", "/try", "/test", "/default", "/box", "/app/inspect"):
        assert key in block.replace("\\/", "/"), key


# ───────── المحاكاة ─────────
def test_mock_files_match_the_real_shapes():
    tpl = json.loads(_read("mock/model_templates.json"))["templates"]
    assert {t["id"] for t in tpl} == {t["id"] for t in ml.templates()}, "أعد توليد mock/model_templates.json من الخادم"
    for t in tpl:
        assert {"open", "task_label", "link_label", "commercial_label"} <= set(t)
    o = json.loads(_read("mock/model_library.json"))
    assert [t["task"] for t in o["tasks"]] == list(ml.TASKS)
    assert {"box", "problem", "gpu", "links", "path"} <= set(o) and [l["id"] for l in o["links"]] == list(ml.LINKS)
    for t in o["tasks"]:
        assert {"label", "default", "fallback_builtin", "can_fallback", "builtin", "models"} <= set(t)
        for m in t["models"]:
            if t["task"] != "motion":
                assert {"id", "name", "task", "link", "enabled", "licence", "usable", "unusable_reason", "licence_label", "token_set", "stats"} <= set(m), m["id"]
    blob = json.dumps(o, ensure_ascii=False) + json.dumps(tpl, ensure_ascii=False)
    assert not re.search(r"sk-[A-Za-z0-9]{12,}|Bearer ", blob)


# ───────── تشغيل modellib.js بـ node: بناء حمولة المعالج وقبول الخادم الحقيقي لها ─────────
HARNESS = r"""
const fs = require("fs");
global.window = {};
global.document = { addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } };
global.matchMedia = () => ({ matches: false });
global.$ = () => null; global.$$ = () => [];
global.enc = encodeURIComponent;
global.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
global.soft = async () => ({ data: null, err: null });
global.errBox = () => "";
global.CSS = { escape: (s) => s };
eval(fs.readFileSync(process.argv[1], "utf8"));
const U = window.ModelLib.util;
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = { lines: U.lines("a\n\n  b \r\n c"), env: U.envOf("A=1\nB=x=y\nC"), bodies: {}, edits: {} };
for (const t of input.templates) {
  const f = U.fromTemplate(U.blankFields(t.task, t.link), t);
  if (t.link === "std") { f.url = f.url || "http://127.0.0.1:8000/v1"; f.model = f.model || "some-model"; f.token = "tok-FAKE-xyz"; }
  if (t.link === "app") {
    f.url = f.url || "http://127.0.0.1:7860"; f.api = "/run"; f.hash = "abcdef0123456789";
    f.inputs = t.task === "lipsync" ? { v: { mode: "from", from: "video" }, a: { mode: "from", from: "audio" } } : { p: { mode: "from", from: "prompt" }, k: { mode: "const", const: "7" }, skipme: { mode: "skip" } };
  }
  f.confirmed = true;
  out.bodies[t.id] = U.payload({ task: t.task, link: t.link, tpl: t.id, f }, true);
}
for (const m of input.models) {
  const f = U.fromModel(U.blankFields(m.task, m.link), m);
  f.name = m.name + " (معدّل)";
  out.edits[m.id] = U.payload({ task: m.task, link: m.link, tpl: m.template, f }, false);
}
console.log(JSON.stringify(out));
"""


def _run_node(tmp_path, templates, models):
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"templates": templates, "models": models}, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "modellib.js"), str(inp)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node مش موجود")
def test_wizard_payloads_for_every_open_template_are_accepted_by_the_real_server(tmp_path):
    open_tpls = [t for t in ml.templates() if t["link"] in ml.OPEN_LINKS and t["task"] in ml.LIBRARY_TASKS]
    assert len(open_tpls) >= 12
    o = _run_node(tmp_path, open_tpls, [])
    assert o["lines"] == ["a", "b", "c"] and o["env"] == {"A": "1", "B": "x=y", "C": ""}
    for t in open_tpls:
        body = o["bodies"][t["id"]]
        token = body.pop("token", None)
        assert (token == "tok-FAKE-xyz") == (t["link"] == "std")                  # التوكن بيطلع بحقل مستقل مش جوّا std
        assert body["enabled"] is False and body["template"] == t["id"] and body["task"] == t["task"] and body["link"] == t["link"]
        m = ml.create(body, by="سارة")
        assert m["name"] == t["name"] and m["licence"]["commercial"] == t["licence"]["commercial"] and m["enabled"] is False
        if t["licence"]["commercial"] in ("conditional", "unknown"):
            assert m["licence"]["confirmed_by_owner"] is True and m["licence"]["confirmed_by"] == "سارة"
        if t["link"] == "command":
            assert m["command"]["argv"] == t["defaults"]["command"]["argv"]
        if t["link"] == "app":
            assert m["app"]["api_name"] == "/run" and m["app"]["schema_hash"] == "abcdef0123456789" and m["app"]["output"] == {"index": None}
            assert {"param": "k", "const": 7} in m["app"]["inputs"] or t["task"] == "lipsync"       # القيمة الثابتة الرقمية بتنبعت رقم مش نص
            assert all(i["param"] != "skipme" for i in m["app"]["inputs"])                            # «القيمة الجاهزة» ما بتنبعت أبداً


@pytest.mark.skipif(not NODE, reason="node مش موجود")
def test_edit_payloads_round_trip_without_touching_task_link_or_the_token(tmp_path):
    made = []
    for t in ml.templates():
        if t["link"] in ml.OPEN_LINKS and t["task"] in ml.LIBRARY_TASKS and t["id"] in ("speaches-stt", "chatterbox-voice", "cmd-image", "cmd-upscale"):
            raw = {"name": t["name"], "task": t["task"], "link": t["link"], "template": t["id"], "licence": {**t["licence"], "confirmed_by_owner": True},
                   **json.loads(json.dumps(t["defaults"]))}
            if t["link"] == "std":
                raw["std"] = {**raw["std"], "url": "http://127.0.0.1:8000/v1", "model": raw["std"].get("model") or "m"}
            made.append(ml.public(ml.create(raw)))
    assert len(made) == 4
    o = _run_node(tmp_path, [], made)
    for m in made:
        body = o["edits"][m["id"]]
        assert "task" not in body and "link" not in body and "enabled" not in body and "token" not in body
        u = ml.update(m["id"], body, by="سارة")
        assert u["name"] == m["name"] + " (معدّل)" and u["task"] == m["task"] and u["link"] == m["link"]
        assert u["caps"] == m["caps"] and u["params"] == m["params"] and u["timeout_sec"] == m["timeout_sec"]       # ما ضاع شي بالرحلة
        assert u["licence"]["confirmed_by_owner"] is True
        assert (u.get("std") or {}).get("url") == (m.get("std") or {}).get("url")
