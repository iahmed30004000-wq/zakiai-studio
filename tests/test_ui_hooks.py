"""واجهة الهوكات (hooks.js + خطوة السيناريو): الربط، الأزرار، ونموذج المحاكاة. فحوص ثابتة بلا متصفح."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "hooks.js").read_text(encoding="utf-8")
STUDIO = (STATIC / "studio.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def mock(name):
    return json.loads((STATIC / "mock" / f"{name}.json").read_text(encoding="utf-8"))


def test_hooks_js_is_loaded_once_after_studio_and_before_the_shell():
    tags = re.findall(r'<script src="/([\w.-]+\.js)\?v=\d+"></script>', HTML)
    assert tags.count("hooks.js") == 1 and tags.index("studio.js") < tags.index("hooks.js") < tags.index("shell.js") < tags.index("boot.js")
    assert len(set(re.findall(r"\?v=(\d+)", HTML))) == 1


def test_step_three_hosts_the_hooks_panel_and_rerenders_after_a_main_change():
    assert '<div class="panel" id="hkPanel"></div>' in STUDIO
    assert "hkMount(file, async () => { await studioLoad(); await renderStep3(); loadScriptStatus(); })" in STUDIO
    assert STUDIO.index('id="hkPanel"') < STUDIO.index('data-top="hook_line"')                    # الهوكات فوق حقول التعديل


def test_the_generate_form_asks_for_the_number_of_hooks_and_sends_it():
    sel = re.search(r'<select id="genHooks">.*?</select>', HTML, re.S).group(0)
    assert [int(v) for v in re.findall(r'<option value="(\d)"', sel)] == [1, 2, 3, 4, 5] and 'value="3" selected' in sel
    assert "extra.hooks = $(\"#genHooks\").value;" in STUDIO


def test_every_hooks_call_goes_through_the_script_hooks_api_and_asks_before_big_changes():
    ok = r"scripts/\$\{enc\((?:HK\.)?file\)\}/hooks"                                  # enc(file) بالتحميل، enc(HK.file) بالأفعال
    assert re.search(r"`/api/" + ok, JS) and not re.search(r'["`]/api/(?!' + ok + "|hooks-bank)", JS)          # + بنك الهوكات
    for path in ("/select", "/${enc(id)}/regenerate", "/${enc(id)}/version", "/${enc(id)}"):
        assert path in JS, path
    for question in ("بتخلّي هالهوك هو الأساسي", "تحذف هالهوك؟", "بنعمل نسخة فيديو لهالهوك"):
        assert f"confirm(\"{question}" in JS, question
    assert not re.search("[٠-٩۰-۹]", JS)


def test_the_card_offers_the_right_buttons_per_hook():
    for needle in ('data-hk="select"', 'data-hk="regen"', 'data-hk="del"', 'data-hk="version"', 'data-hk="save"', 'data-hk="add"',
                   "اختار أساسي", "ولّد بداله", "اعمل نسخة فيديو لهالهوك", "＋ هوك جديد"):
        assert needle in JS, needle
    assert "if (h.main) return \"\";" in JS and "h.can_version.ok ? \"\" : \"disabled\"" in JS         # الأساسي بلا نسخة، والمرفوض بلا زر
    assert "const isVersion = !!d.version_of" in JS and "هاي <b>نسخة هوك</b>" in JS                  # نسخة الهوك ما بتضيف هوكات


def test_mock_hooks_cover_main_ok_blocked_and_version_states():
    d = mock("script_hooks")
    assert d["ok"] and d["main"] == "h1" and d["max"] == 5 and set(d["types"]) == {"question", "number", "life_moment", "contrarian", "visual_shock"}
    by = {h["id"]: h for h in d["hooks"]}
    assert d["main"] in by                                                                          # علامة «الأساسي» بتنحسب من d.main (المحاكاة بتعيد حسابها)
    assert by["h2"]["can_version"] == {"ok": True, "reason": ""} and by["h3"]["can_version"]["ok"] is False and by["h3"]["findings"][0]["severity"] == "blocker"
    assert all(h["version"] is None for h in d["hooks"]) and d["version_of"] is None
    for path in ("mockHooks", "mockHooksWrite", "select|regenerate|version"):
        assert path in APP, path


# ═════════════════ بنك الهوكات ═════════════════
SHELL = (STATIC / "shell.js").read_text(encoding="utf-8")


def test_the_bank_is_a_library_tab_wired_through_the_shell():
    tabs = re.search(r'<div class="seg" id="libsTabs".*?</div>', HTML, re.S).group(0)
    # بنك الهوكات قسم جوّا رف «الأنماط والهوكات» (libsPatTabs)
    sub = re.search(r'<div class="seg seg-sm" id="libsPatTabs".*?</div>', HTML, re.S).group(0)
    assert 'data-tab="hooks">بنك الهوكات</button>' in sub and '<div id="libs-hooks" class="tabpane"></div>' in HTML
    assert re.search(r'const LIBS_TABS = \[[^\]]*"hooks"', SHELL) and 'case "hooks": return VIEWS.hooksBank.enter();' in SHELL
    assert "VIEWS.hooksBank = { async enter() { await hkbLoad(); } };" in JS


def test_the_bank_talks_to_its_own_api_and_confirms_destructive_actions():
    urls = set(re.findall(r"[`\"](/api/hooks-bank[^`\"]*)", JS))
    assert "/api/hooks-bank" in urls and any(u.startswith("/api/hooks-bank/${enc(key") for u in urls)
    for needle in ('data-hkb="star"', 'data-hkb="archive"', 'data-hkb="copy"', 'data-hkb="edit"', 'data-hkb="delete"', "تحذف هالهوك اليدوي من البنك؟",
                   "نجّمه: بيروح مثال للكاتب", "هوك يدوي", "رابح", "لسا ما اتجرّب بإعلان"):
        assert needle in JS, needle
    assert 'qs.set("star", "true")' in JS and 'qs.set("archived", "true")' in JS


def test_mock_bank_covers_every_role_a_result_a_star_and_a_manual_entry():
    d = mock("hooks_bank")
    roles = {e["role"] for e in d["items"]}
    assert roles == {"main", "alt", "video", "manual"} and d["counts"]["total"] == len(d["items"]) and set(d["types"]) == {"question", "number", "life_moment", "contrarian", "visual_shock"}
    assert any(e["star"] for e in d["items"]) and any((e["result"] or {}).get("verdict") == "winner" for e in d["items"])
    assert any(e["source"] == "manual" and e["note"] for e in d["items"]) and all(e["key"] for e in d["items"]) and len({e["key"] for e in d["items"]}) == len(d["items"])
    for fn in ("mockBank", "mockBankWrite", '"/api/hooks-bank"'):
        assert fn in APP, fn
