"""واجهة الأنماط (patedit.js): الربط بالصفحة، التسميات بالعربي، ومحاكاة (mock) متزامنة مع الخادم. فحوص ثابتة بلا متصفح."""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pattern_fields as pf  # noqa: E402
import pattern_text as pt  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "patedit.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def mock(name):
    return json.loads((STATIC / "mock" / f"{name}.json").read_text(encoding="utf-8"))


def test_the_script_is_loaded_once_after_app_and_before_the_shell():
    tags = re.findall(r'<script src="/([\w.-]+\.js)\?v=\d+"></script>', HTML)
    assert tags.count("patedit.js") == 1
    assert tags.index("app.js") < tags.index("patedit.js") < tags.index("shell.js") < tags.index("boot.js")
    assert len(set(re.findall(r"\?v=(\d+)", HTML))) == 1                              # كل الوسوم بنفس الرقم


def test_the_library_page_has_the_new_pattern_import_archive_and_translation_slots():
    for needle in ('href="#/pattern/new"', 'id="peImportBtn"', 'id="peArchBtn"', 'id="peArchCount"', 'id="peTrBanner"', 'id="peArchPanel"'):
        assert needle in HTML, needle


def test_origin_labels_are_arabic_everywhere_and_the_english_tags_are_gone():
    assert 'mined: "من فيديو", authored: "يدوي", proven: "من النتايج"' in APP
    sel = re.search(r'<select id="fOrigin".*?</select>', HTML, re.S).group(0)
    assert "من فيديو" in sel and "يدوي" in sel and "من النتايج" in sel
    assert "(mined)" not in sel and "(authored)" not in sel and "(proven)" not in sel
    assert "مستخرج" not in APP.split("const ORIGIN")[1].split("\n")[0]


def test_the_pattern_route_opens_the_editor_for_new_and_edit_and_the_page_calls_the_editor_helpers():
    assert 'id === "new" || (id && p.q.edit === "1")' in APP and "peOpen(id)" in APP
    for helper in ("peActionsHtml(id, p)", "peMoreHtml(p)", "peWirePage(id, p)", "fillPatPick("):
        assert helper in APP, helper
    for fn in ("peOpen", "peActionsHtml", "peMoreHtml", "peWirePage", "peLibEnter", "peImportOpen", "peRenderTranslation"):
        assert re.search(rf"^(?:async )?function {fn}\b", JS, re.M), fn


def test_the_editor_talks_only_to_the_pattern_lib_api_and_never_edits_files_directly():
    urls = set(re.findall(r'["`](/api/[\w/${}.\-()]+)', JS))
    assert urls and all(u.startswith("/api/pattern-lib") for u in urls), urls
    assert "confirm: true" in JS and 'r.ok === false && r.confirm' in JS                   # أسئلة التكرار والاستعمال
    assert "rev: PE.view.rev" in JS                                                        # حماية التعارض
    assert not re.search("[٠-٩۰-۹]", JS)


def test_editor_fields_follow_the_server_schema_not_a_hardcoded_list():
    assert "const v = PE.view, sc = PE.schema" in JS and "sc.groups.map" in JS and "sc.fields.filter" in JS and "PE.schema.scene_fields" in JS
    assert not any(f'"{p}"' in JS for p in ("hook.type", "pattern_name", "cta.type"))        # ما في مسار حقل مكتوب بالكود
    assert "dialect_sub_parent" in JS                                                      # اللهجة الفرعية بتتبع اللهجة


def test_mock_schema_matches_the_real_schema_exactly():
    assert mock("pattern_schema") == json.loads(json.dumps(pf.schema()))


def test_mock_views_are_editor_ready_and_consistent_with_the_text_layer():
    views, detail = mock("pattern_view"), mock("pattern_detail")
    assert set(views) == set(detail) and "ad_999" in views
    paths = {f["path"] for f in pf.FIELDS}
    for pid, v in views.items():
        assert {"id", "rev", "archived", "name", "fields", "refs", "history", "missing_ar", "origin"} <= set(v), pid
        assert v["fields"]["scene_blueprint"] and all("_k" in s for s in v["fields"]["scene_blueprint"]), pid
        assert all(pf.has_path(v["fields"], p) for p in paths), pid
    assert views["ad_999"]["archived"] is True and detail["ad_999"]["_archived"] is True
    assert views["ad_105"]["fields"] == pt.editable({k: x for k, x in detail["ad_105"].items() if k != "_archived"})


def test_mock_import_preview_and_translation_state_have_the_shape_the_ui_reads():
    prev = mock("pattern_import_preview")
    assert re.fullmatch(r"[0-9a-f]{16}", prev["token"]) and set(prev["counts"]) == {"ok", "warn", "error"}
    assert {r["status"] for r in prev["rows"]} == {"ok", "warn", "error"}
    assert all({"row", "name", "status", "errors", "warnings"} <= set(r) for r in prev["rows"])
    assert all({"field", "label", "msg"} <= set(e) for r in prev["rows"] for e in r["errors"])
    assert set(mock("pattern_translation")) == {"patterns", "pending_patterns", "pending_keys"}
    assert mock("pattern_archived")["items"][0]["id"] == "ad_999"
    for path in ("/api/pattern-lib/schema", "/api/pattern-lib/translation", "/api/pattern-lib/archived", "/api/pattern-lib/import", "/api/pattern-lib/import/commit"):
        assert path in APP, path


def test_translation_is_automatic_the_owner_has_no_trial_or_translate_buttons():
    """المالك ما بيقعد يترجم: الواجهة بتبدأ الترجمة لحالها وبتعرض تقدّم بس. الزر الوحيد «أعد المحاولة» وقت الخطأ."""
    assert "data-tr=" not in JS and "جرّب على نمطين" not in JS and "ترجم الكل" not in JS and "ترجم الباقي" not in JS
    assert 'post("/api/pattern-lib/translate", {})' in JS                          # بتبدأها لحالها
    assert 'post("/api/pattern-lib/translate", { retry: true })' in JS and 'id="peTrRetry"' in JS
    assert "جاري ترجمة الأنماط للعربي تلقائياً" in JS and "peTrPoll(4000)" in JS      # تقدّم حي
    assert "t.running" in JS and "t.retry_in" in JS and "t.stuck" in JS and "t.auto" in JS
    for state in ('"error"', '"pending"'):                                          # المحاكاة بتغطّي الحالتين
        assert f'mode === {state}' in APP or f'mode !== "pending"' in APP
