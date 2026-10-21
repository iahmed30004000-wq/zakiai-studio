"""الهوكات (script_hooks): قراءة السيناريوهات القديمة، معايرة رد الكاتب، التركيب، تبديل الأساسي، والفحص الفوري بالكود."""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import make_brief, make_script  # noqa: E402

import config  # noqa: E402
import script_hooks as sh  # noqa: E402
import taxonomy  # noqa: E402

HOOK = "تعبانة من جفاف عينك؟"                       # 4 كلمات
REST = "جرّبي قطرة بتريّح عينك من أول يوم بدون حرقة"   # باقي كلام المشهد 1 بعد الهوك


def script(**over):
    s = make_script(hook=HOOK)
    s["scenes"][0]["voiceover"] = f"{HOOK} {REST}"
    s["scenes"][0]["duration_sec"] = 6.0
    s["scenes"][0]["on_screen_text"] = "جفاف العين"
    s["scenes"][0]["visual"] = "وجه امرأة تفرك عينها قدام الشاشة"
    s.update(over)
    return s


def writer_output(n=3):
    s = script()
    s["hooks"] = [
        {"id": "x1", "type": "question", "spoken": HOOK, "on_screen_text": "ما بيطابق", "visual": "ما بيطابق", "why": "سؤال مباشر"},
        {"id": "x2", "type": "number", "spoken": "٣ من ٥ أشخاص عيونهم بتتعب", "on_screen_text": "٣ من ٥", "visual": "أرقام تظهر فوق وجه", "why": "رقم بيشدّ"},
        {"id": "x3", "type": "life_moment", "spoken": "الساعة ١٢ بالليل وعينك لسا قدام الشاشة", "on_screen_text": "نص الشاشة", "visual": "غرفة معتمة", "why": "موقف مألوف"},
        {"id": "x4", "type": "contrarian", "spoken": "نظرك مش ضعيف، عينك بس جافة", "on_screen_text": "", "visual": "", "why": "ادعاء معاكس"},
        {"id": "x5", "type": "visual_shock", "spoken": "شوفي شو بيصير لعينك بعد ٨ ساعات شاشة", "on_screen_text": "", "visual": "لقطة قريبة", "why": "صدمة"},
    ][:n]
    return s


# ═════════════════ الأساسيات ═════════════════
def test_clean_requested_clamps_and_defaults():
    assert sh.clean_requested(None) == config.HOOKS_DEFAULT == 3
    assert [sh.clean_requested(x) for x in ("4", 0, -3, 99, "x", 5, 1)] == [4, 1, 1, 5, 3, 5, 1]


def test_hook_types_are_a_closed_arabic_list():
    assert set(sh.TYPES) == {"question", "number", "life_moment", "contrarian", "visual_shock"} and sh.TYPES is taxonomy.HOOK_TYPES
    assert all(isinstance(v, str) and v for v in sh.TYPES.values())


def test_legacy_script_reads_as_a_single_main_hook_and_is_never_rewritten():
    s = script()
    hs = sh.hooks_of(s)
    assert len(hs) == 1 and hs[0]["id"] == "h1" and hs[0]["spoken"] == HOOK and hs[0]["type"] == "other"
    assert hs[0]["on_screen_text"] == "جفاف العين" and hs[0]["visual"].startswith("وجه امرأة")
    assert sh.main_id(s) == "h1" and not sh.has_alternatives(s) and "hooks" not in s              # القراءة ما بتكتب
    assert sh.public(s)["legacy"] is True


def test_hooks_of_returns_copies_not_the_scripts_own_dicts():
    s = sh.normalize(writer_output())
    h = sh.hooks_of(s)
    h[0]["spoken"] = "تغيّر"
    assert s["hooks"][0]["spoken"] == HOOK


# ═════════════════ معايرة رد الكاتب ═════════════════
def test_normalize_orders_ids_closes_types_and_ties_the_main_hook_to_the_script():
    s = writer_output(4)
    s["hooks"][1]["type"] = "نوع غريب"
    n = sh.normalize(s, 4)
    assert [h["id"] for h in n["hooks"]] == ["h1", "h2", "h3", "h4"] and n["hook_main"] == "h1"
    assert n["hooks"][1]["type"] == "other" and n["hooks"][0]["type"] == "question"
    assert n["hook_line"] == n["hooks"][0]["spoken"] == HOOK
    assert n["hooks"][0]["on_screen_text"] == "جفاف العين" and n["hooks"][0]["visual"].startswith("وجه امرأة")     # الأساسي من المشهد 1
    assert n["_meta"]["hooks_requested"] == 4
    assert s["hooks"][0]["id"] == "x1"                                                          # الأصل ما اتغيّر


def test_normalize_drops_blank_and_duplicate_hooks_and_trims_to_the_request():
    s = writer_output(5)
    s["hooks"][2]["spoken"] = "  "
    s["hooks"][3]["spoken"] = "  " + s["hooks"][1]["spoken"] + "  "                         # نفس نص h2
    n = sh.normalize(s, 3)
    assert [h["spoken"] for h in n["hooks"]] == [HOOK, s["hooks"][1]["spoken"], s["hooks"][4]["spoken"]]
    assert [h["id"] for h in n["hooks"]] == ["h1", "h2", "h3"]


def test_normalize_keeps_hook_line_as_the_main_even_if_the_writer_disagrees():
    s = writer_output(3)
    s["hooks"][0]["spoken"] = "جملة تانية خالص"
    n = sh.normalize(s, 3)
    assert n["hooks"][0]["spoken"] == HOOK == n["hook_line"]


def test_normalize_without_hooks_leaves_an_old_style_script_alone():
    s = script()
    s["hooks"] = "مش قائمة"
    n = sh.normalize(s, 3)
    assert "hooks" not in n and "hook_main" not in n and n["hook_line"] == HOOK


def test_normalize_uses_the_meta_request_when_none_is_passed():
    s = writer_output(5)
    s["_meta"] = {"hooks_requested": 2}
    assert len(sh.normalize(s)["hooks"]) == 2


def test_hook_values_cover_every_alternative_for_the_no_repeat_registry():
    n = sh.normalize(writer_output(3))
    vals = sh.hook_values(n)
    assert vals[0] == HOOK and len(vals) == 3 and len(set(vals)) == 3
    assert sh.hook_values(script()) == [HOOK]


# ═════════════════ التركيب وتبديل الأساسي ═════════════════
def test_scene1_splits_into_the_hook_line_and_the_rest():
    assert sh.split_scene1(script()) == (HOOK, REST)
    s = script()
    s["hook_line"] = "سطر مش بداية المشهد"
    vo = s["scenes"][0]["voiceover"]
    assert sh.split_scene1(s) == (vo, "")                                                       # بدون بداية مطابقة: المشهد كامل


def test_an_alternative_replaces_only_the_opening_of_scene_one():
    n = sh.normalize(writer_output(3))
    alt = sh.compose_scene1(n, "h2")
    assert alt["voiceover"] == f"{n['hooks'][1]['spoken']} {REST}"
    assert alt["on_screen_text"] == "٣ من ٥" and alt["visual"] == "أرقام تظهر فوق وجه"
    assert alt["duration_sec"] == 6.0 and alt["scene_number"] == 1 and alt["purpose"] == n["scenes"][0]["purpose"]
    assert sh.compose_scene1(n, "h1") == n["scenes"][0]
    assert n["scenes"][0]["voiceover"] == f"{HOOK} {REST}"                                      # الأصل ما اتلمس
    with pytest.raises(KeyError):
        sh.compose_scene1(n, "h9")


def test_as_script_swaps_the_opening_everywhere_the_pipeline_reads_it():
    n = sh.normalize(writer_output(3))
    v = sh.as_script(n, "h3")
    assert v["hook_line"] == n["hooks"][2]["spoken"] and v["scenes"][0]["voiceover"].startswith(n["hooks"][2]["spoken"])
    assert v["scenes"][1:] == n["scenes"][1:] and v["cta_line"] == n["cta_line"] and v["hook_main"] == "h3"
    assert n["hook_line"] == HOOK


def test_selecting_a_new_main_keeps_the_old_one_as_an_alternative_and_round_trips():
    n = sh.normalize(writer_output(3))
    m = sh.select_main(n, "h2")
    assert m["hook_main"] == "h2" and m["hook_line"] == n["hooks"][1]["spoken"]
    assert m["scenes"][0]["voiceover"] == f"{n['hooks'][1]['spoken']} {REST}" and m["scenes"][0]["on_screen_text"] == "٣ من ٥"
    old = sh.get(m, "h1")
    assert old["spoken"] == HOOK and old["on_screen_text"] == "جفاف العين" and old["visual"].startswith("وجه امرأة")    # الأساسي القديم محفوظ
    back = sh.select_main(m, "h1")
    assert back["scenes"][0] == n["scenes"][0] and back["hook_line"] == HOOK and back["hook_main"] == "h1"
    assert sh.select_main(n, "h1") == n and sh.select_main(n, "h1") is not n
    with pytest.raises(KeyError):
        sh.select_main(n, "h9")


def test_selecting_the_main_on_a_legacy_script_is_a_no_op():
    s = script()
    assert sh.select_main(s, "h1") == s


# ═════════════════ الفحص ═════════════════
def test_a_clean_set_of_hooks_has_no_findings():
    n = sh.normalize(writer_output(3))
    assert all(rows == [] for rows in sh.check(n, make_brief()).values()) and sh.blockers(n, make_brief()) == {}


def test_a_hook_that_makes_scene_one_unspeakably_fast_is_a_blocker():
    n = sh.normalize(writer_output(3))
    n["hooks"][1]["spoken"] = " ".join(["كلمة"] * 30)
    rows = sh.check(n)["h2"]
    f = [x for x in rows if x["severity"] == "blocker"]
    assert f and f[0]["hook_id"] == "h2" and f[0]["scene"] == 1 and "أسرع من الممكن" in f[0]["issue"]
    assert list(sh.blockers(n)) == ["h2"]


def test_a_too_slow_alternative_is_only_a_minor_note():
    n = sh.normalize(writer_output(2))
    n["scenes"][0]["duration_sec"] = 12.0
    n["hooks"][1]["spoken"] = "قصير"
    f = sh.check(n)["h2"]
    assert [x["severity"] for x in f] == ["minor"] and "أبطأ" in f[0]["issue"]


def test_on_screen_text_over_five_words_is_a_major_note_per_hook():
    n = sh.normalize(writer_output(2))
    n["hooks"][1]["on_screen_text"] = "ست كلمات كاملة بنص الشاشة هاد هون"
    f = sh.check(n)["h2"]
    assert any(x["severity"] == "major" and x["field"] == "on_screen_text" for x in f)


def test_an_alternative_with_a_forbidden_claim_is_blocked_by_the_same_rules_as_the_script():
    n = sh.normalize(writer_output(3))
    n["hooks"][2]["spoken"] = "بتشفي عينك من أول قطرة"
    brief = make_brief(forbidden_claims=["بتشفي"])
    f = sh.blockers(n, brief)
    assert list(f) == ["h3"] and f["h3"][0]["hook_id"] == "h3" and "تشفي" in f["h3"][0]["evidence"] and f["h3"][0]["scene"] == 1
    assert sh.blockers(n, None) == {}                                                           # بدون بريف ما في فحص ادعاءات


def test_offers_and_scarcity_in_an_alternative_follow_the_brief_rules():
    n = sh.normalize(writer_output(2))
    n["hooks"][1]["spoken"] = "خصم ٥٠٪ لآخر القطع"
    rows = sh.check(n, make_brief())["h2"]
    assert {r["field"] for r in rows if r.get("rule")} <= {"hook_line", "voiceover"} and any(r.get("rule") for r in rows)


def test_a_duplicate_line_between_hooks_is_flagged():
    n = sh.normalize(writer_output(3))
    n["hooks"][2]["spoken"] = n["hooks"][1]["spoken"]            # بعد normalize (اللي بيحذف المكرر) انعمل تعديل يدوي
    f = sh.check(n)["h3"]
    assert any("نفس سطر هوك تاني" in x["issue"] for x in f)


def test_an_empty_alternative_is_a_blocker():
    n = sh.normalize(writer_output(2))
    n["hooks"][1]["spoken"] = ""
    assert sh.blockers(n)["h2"][0]["issue"] == "الهوك بلا سطر محكي"


def test_the_main_hook_is_not_rechecked_here_the_normal_reviewer_owns_it():
    n = sh.normalize(writer_output(2))
    n["scenes"][0]["voiceover"] = " ".join(["كلمة"] * 40)       # المشهد 1 نفسه غلط: مسؤولية المراجع العادي
    assert sh.check(n, make_brief())["h1"] == []


# ═════════════════ للواجهة ═════════════════
def test_public_view_has_arabic_type_labels_findings_and_a_fresh_or_stale_ai_check():
    n = sh.normalize(writer_output(3))
    n["hooks_review"] = {"h2": {"verdict": "ok", "note": "ممتاز", "fp": sh.fingerprint(n["hooks"][1])},
                         "h3": {"verdict": "ok", "note": "", "fp": "قديمة"}}
    pub = sh.public(n, make_brief())
    assert pub["main"] == "h1" and pub["legacy"] is False and pub["requested"] == 3 and pub["max"] == 5
    by = {h["id"]: h for h in pub["hooks"]}
    assert by["h1"]["main"] is True and by["h2"]["main"] is False
    assert by["h2"]["type_label"] == "رقم" and by["h1"]["type_label"] == "سؤال"
    assert by["h2"]["ai"] == {"verdict": "ok", "note": "ممتاز", "fresh": True} and by["h3"]["ai"]["fresh"] is False and by["h1"]["ai"] is None
    assert set(pub["types"]) == set(sh.TYPES)


def test_fingerprint_changes_with_the_text_but_not_with_whitespace():
    h = {"spoken": "جملة  وحدة", "on_screen_text": "نص", "visual": "وصف"}
    assert sh.fingerprint(h) == sh.fingerprint({**h, "spoken": "جملة وحدة "})
    assert sh.fingerprint(h) != sh.fingerprint({**h, "visual": "وصف تاني"})


def test_nothing_in_the_module_mutates_its_inputs():
    n = sh.normalize(writer_output(3))
    before = copy.deepcopy(n)
    for fn in (lambda: sh.hooks_of(n), lambda: sh.as_script(n, "h2"), lambda: sh.select_main(n, "h2"),
               lambda: sh.check(n, make_brief()), lambda: sh.public(n, make_brief()), lambda: sh.compose_scene1(n, "h3")):
        fn()
    assert n == before
