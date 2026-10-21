"""طبقة عربي الأنماط (pattern_text) ووصف الحقول والتحقق (pattern_fields): دوال صافية."""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pattern_fields as pf  # noqa: E402
import pattern_text as pt  # noqa: E402


def sample() -> dict:
    return {
        "pattern_name": "The Sensory Layer Reveal", "framework": "ingredient_reveal", "framework_secondary": "demo_proof",
        "one_line_summary": "A rhythmic hook then a slow ingredient reveal.", "product_category": "fragrance",
        "target_audience": "Arabic-speaking consumers", "dialect_or_language": "shami", "dialect_sub": None,
        "hook": {"type": "pattern interrupt via rhythmic list", "duration_sec": 1.13, "mechanism": "A staccato repetition.",
                 "transferable_template": "Smell of [A], smell of [B]"},
        "emotional_arc": ["curiosity", "intrigue", "anticipation"],
        "product_entry_sec": 1.13, "product_entry_style": "Bottle appears mid-action", "proof_mechanism": "ingredient reveal",
        "objection_handled": ["will it last", "is it versatile"],
        "cta": {"type": "direct order via phone number", "placement_sec": 6.8, "wording_style": "bare number overlay", "extra_key": "keep me"},
        "pacing": {"total_duration_sec": 30.0, "scene_count": 3, "avg_scene_sec": 10.0, "cut_rhythm": "fast then slow", "words_per_second": 2.4},
        "visual_language": {"shot_types": ["macro close-up", "slow-motion pour"], "setting": "dark tabletop", "production_style": "studio",
                            "text_overlay_style": "bold callouts", "talent": "none"},
        "scene_blueprint": [
            {"slot": 1, "function": "Deliver the hook", "duration_sec": 1.0, "shot_type": "overlay", "vo_intent": "list", "on_screen_text_role": "caption", "emotion": "curiosity"},
            {"slot": 2, "function": "Introduce the product", "duration_sec": 9.0, "shot_type": "macro", "vo_intent": "claim", "on_screen_text_role": "minimal", "emotion": "intrigue"},
            {"slot": 3, "function": "Close with CTA", "duration_sec": 20.0, "shot_type": "hero", "vo_intent": "restate", "on_screen_text_role": "phone", "emotion": "urgency"},
        ],
        "why_it_works": ["Auditory pattern interrupt."], "weak_points": ["Needs layered products."],
        "production_complexity": "medium", "best_for": ["fragrances"], "avoid_for": ["gadgets"], "reusability_score": 7,
        "_source": {"video_id": "v1", "type": "mined"}, "_legacy": {"dialect_or_language": "Levantine (Shami)", "framework": "Ingredient Reveal", "product_category": "Fragrance"},
        "_taxonomy": {"version": 1, "complete": True}, "cluster_id": "cl_001", "cluster_role": "primary",
    }


# ═════════════════ العرض ═════════════════
def test_is_arabic_means_arabic_letters_are_at_least_half():
    assert pt.is_arabic("نمط الكشف عن الطبقات") and pt.is_arabic("قالب: [المكوّن A] ثم [المكوّن B]")
    assert not pt.is_arabic("The Sensory Layer Reveal") and not pt.is_arabic("") and not pt.is_arabic("12 + 3")
    assert not pt.is_arabic("a long english sentence with one كلمة")


def test_localized_prefers_present_keys_even_empty_and_leaves_the_source_untouched():
    p = sample()
    before = copy.deepcopy(p)
    p["ar"] = {"pattern_name": "كشف الطبقات الحسية", "hook": {"type": "قطع الإيقاع"}, "target_audience": "",
               "emotional_arc": ["فضول", "ترقّب"], "visual_language": {"shot_types": []}}
    p["scene_blueprint"][1]["ar"] = {"function": "تعريف المنتج", "vo_intent": ""}
    v = pt.localized(p)
    assert "ar" not in v and "ar" not in v["scene_blueprint"][1]
    assert v["pattern_name"] == "كشف الطبقات الحسية" and v["hook"]["type"] == "قطع الإيقاع"
    assert v["hook"]["mechanism"] == "A staccato repetition."                         # مفتاح غير موجود بـ ar ← الأصل
    assert v["target_audience"] == ""                                                  # مفتاح موجود وفاضي ← بيغلب (ما بيرجع الإنجليزي)
    assert v["emotional_arc"] == ["فضول", "ترقّب"] and v["visual_language"]["shot_types"] == []
    assert v["scene_blueprint"][1]["function"] == "تعريف المنتج" and v["scene_blueprint"][1]["vo_intent"] == ""
    assert v["scene_blueprint"][1]["shot_type"] == "macro" and v["scene_blueprint"][0]["function"] == "Deliver the hook"
    p2 = copy.deepcopy(p)
    del p2["ar"], p2["scene_blueprint"][1]["ar"]
    assert p2 == before                                                                # الأصل ما انلمس
    assert pt.display_name(p) == "كشف الطبقات الحسية" and pt.display_name(before) == "The Sensory Layer Reveal"


def test_for_model_is_the_arabic_view_without_internal_keys():
    p = sample()
    p["ar"] = {"pattern_name": "كشف"}
    m = pt.for_model(p)
    assert m["pattern_name"] == "كشف" and m["framework"] == "ingredient_reveal"       # الـ slugs ما بتتغيّر
    assert not any(k.startswith("_") or k.startswith("cluster_") or k == "ar" for k in m)


def test_rev_ignores_cluster_changes_but_not_content_changes():
    p = sample()
    r = pt.rev(p)
    q = copy.deepcopy(p)
    q["cluster_id"], q["_similar_to"] = "cl_999", [{"x": 1}]
    assert pt.rev(q) == r
    q["ar"] = {"pattern_name": "اسم جديد"}
    assert pt.rev(q) != r


# ═════════════════ التعديل ═════════════════
def test_merge_edit_puts_text_in_ar_numbers_on_top_and_keeps_the_english_and_unknown_keys():
    p = sample()
    e = pt.editable(p)
    assert e["pattern_name"] == "The Sensory Layer Reveal" and [s["_k"] for s in e["scene_blueprint"]] == [0, 1, 2]
    e["pattern_name"] = "كشف الطبقات"
    e["hook"]["duration_sec"] = 2.5
    e["reusability_score"] = 9
    e["why_it_works"] = ["سبب أول", "سبب تاني"]
    e["production_complexity"] = "high"
    q = pt.merge_edit(p, e)
    assert q["pattern_name"] == "The Sensory Layer Reveal" and q["ar"]["pattern_name"] == "كشف الطبقات"      # الأصل ثابت للبصمة
    assert q["hook"]["duration_sec"] == 2.5 and q["reusability_score"] == 9 and q["production_complexity"] == "high"
    assert q["ar"]["why_it_works"] == ["سبب أول", "سبب تاني"] and q["why_it_works"] == ["Auditory pattern interrupt."]
    assert q["cta"]["extra_key"] == "keep me" and q["cluster_id"] == "cl_001" and q["_legacy"] == p["_legacy"]
    assert pt.localized(q)["pattern_name"] == "كشف الطبقات"


def test_merge_edit_rebuilds_scenes_by_original_index_and_recomputes_counts():
    p = sample()
    e = pt.editable(p)
    s0, s1, s2 = e["scene_blueprint"]
    s1["function"] = "تعريف المنتج"
    new = {"function": "مشهد جديد بالعربي", "duration_sec": 4, "shot_type": "", "vo_intent": "", "on_screen_text_role": "", "emotion": "فضول", "_k": None}
    e["scene_blueprint"] = [s2, s1, new]                       # ترتيب جديد: التالت أول، وحذف الأول، وإضافة جديد
    q = pt.merge_edit(p, pt.editable(p) | {"scene_blueprint": e["scene_blueprint"]})
    sc = q["scene_blueprint"]
    assert [s["slot"] for s in sc] == [1, 2, 3] and len(sc) == 3
    assert sc[0]["function"] == "Close with CTA" and "ar" not in sc[0]                                     # ما اتغيّر ← ما بيتجمّد إنجليزي بـ ar
    assert sc[1]["function"] == "Introduce the product" and sc[1]["ar"]["function"] == "تعريف المنتج"
    assert sc[2]["function"] == "مشهد جديد بالعربي" and "ar" not in sc[2]                                  # الجديد نصه الأول عربي
    assert [s["function"] for s in pt.localized(q)["scene_blueprint"]] == ["Close with CTA", "تعريف المنتج", "مشهد جديد بالعربي"]
    assert q["pacing"]["scene_count"] == 3 and q["pacing"]["avg_scene_sec"] == 10.0                        # 30 ثانية ÷ 3


def test_saving_without_changes_does_not_freeze_the_english_into_ar():
    """لو المحرّر بعت كل الحقول بلا تعديل، ما بيدخل شي لـ ar، وإلا الترجمة بتفكّر الإنجليزي «مترجم» وبتتخطّاه."""
    p = sample()
    q = pt.merge_edit(p, pt.editable(p))
    assert "ar" not in q and q["scene_blueprint"] == [{**s, "slot": i} for i, s in enumerate(p["scene_blueprint"], 1)]
    assert pt.missing_ar_keys(q) == pt.missing_ar_keys(p)


def test_only_the_changed_text_goes_to_ar_and_clearing_a_field_sticks():
    p = sample()
    e = pt.editable(p)
    e["one_line_summary"] = ""                                   # مسح حقل: بيضل فاضي، ما بيرجع الإنجليزي
    e["scene_blueprint"][1]["emotion"] = "فضول"
    q = pt.merge_edit(p, e)
    assert q["ar"] == {"one_line_summary": ""}
    assert q["scene_blueprint"][1]["ar"] == {"emotion": "فضول"} and "ar" not in q["scene_blueprint"][0]
    assert pt.localized(q)["one_line_summary"] == "" and pt.localized(q)["pattern_name"] == "The Sensory Layer Reveal"


# ═════════════════ الترجمة ═════════════════
def test_missing_keys_skip_arabic_and_lists_go_whole_and_apply_only_fills_the_missing():
    p = sample()
    p["pattern_name"] = "نمط عربي أصلاً"
    keys = pt.missing_ar_keys(p)
    assert "pattern_name" not in keys and "one_line_summary" in keys and "hook.transferable_template" in keys
    assert {"emotional_arc.0", "emotional_arc.1", "emotional_arc.2"} <= set(keys) and "scene_blueprint.1.function" in keys
    assert {"_legacy.framework", "_legacy.product_category", "_legacy.dialect_or_language"} <= set(keys)
    flat = pt.extract_texts(p)
    assert flat["scene_blueprint.2.function"] == "Close with CTA" and flat["emotional_arc.1"] == "intrigue" and flat["_legacy.framework"] == "Ingredient Reveal"
    got = {k: f"ع:{v}" for k, v in flat.items()}
    got["one_line_summary"] = "ملخص ٣ مشاهد"                                           # أرقام هندية ← 0-9
    q, n = pt.apply_ar(p, got)
    assert n > 10 and q["ar"]["one_line_summary"] == "ملخص 3 مشاهد" and q["ar"]["emotional_arc"] == ["ع:curiosity", "ع:intrigue", "ع:anticipation"]
    assert q["scene_blueprint"][0]["ar"]["function"] == "ع:Deliver the hook" and q["ar"]["_legacy"]["framework"] == "ع:Ingredient Reveal"
    assert pt.missing_ar_keys(q) == []
    q2, n2 = pt.apply_ar(q, {"one_line_summary": "تغيير غير مقبول", "hook.type": "غيّرت"})     # بيعبّي الناقص بس (الموجود بـ ar ما بينكتب فوقه)
    assert n2 == 0 and q2["ar"]["one_line_summary"] == "ملخص 3 مشاهد"


def test_apply_ar_writes_a_list_only_when_all_its_items_arrived():
    p = sample()
    q, n = pt.apply_ar(p, {"emotional_arc.0": "فضول", "emotional_arc.2": "ترقّب"})        # ناقص البند 1
    assert n == 0 and "ar" not in q
    q, n = pt.apply_ar(p, {"emotional_arc.0": "فضول", "emotional_arc.1": "فضول 2", "emotional_arc.2": "ترقّب", "scene_blueprint.9.function": "x", "bogus": "x"})
    assert n == 3 and q["ar"]["emotional_arc"] == ["فضول", "فضول 2", "ترقّب"]                   # فهرس مشهد خارج النطاق ومفتاح غريب بيتجاهلوا


# ═════════════════ التحقق ═════════════════
def good_fields(**over):
    f = {"pattern_name": "نمط تجريبي", "framework": "pas", "product_category": "skincare", "hook": {"type": "سؤال صادم"},
         "scene_blueprint": [{"function": "هوك"}, {"function": "إثبات"}, {"function": "دعوة"}]}
    f.update(over)
    return f


def test_validate_create_requires_name_framework_category_hook_and_three_scenes():
    clean, errs = pf.validate(good_fields(), "create")
    assert errs == [] and clean["framework"] == "pas" and [s["slot"] for s in clean["scene_blueprint"]] == [1, 2, 3]
    _, errs = pf.validate({}, "create")
    assert {e["field"] for e in errs} >= {"pattern_name", "framework", "product_category", "hook.type", "scene_blueprint"}
    _, errs = pf.validate(good_fields(scene_blueprint=[{"function": "a"}, {"function": "b"}]), "create")
    assert any(e["field"] == "scene_blueprint" and "3" in e["msg"] for e in errs)
    _, errs = pf.validate(good_fields(scene_blueprint=[{"function": "a"}, {"function": ""}, {"function": "c"}]), "create")
    assert any(e["field"] == "scene_blueprint.2.function" for e in errs)


def test_validate_closed_values_numbers_and_lists():
    clean, errs = pf.validate(good_fields(framework="nope", product_category="x", dialect_or_language="klingon"), "create")
    assert {e["field"] for e in errs} >= {"framework", "product_category", "dialect_or_language"}
    clean, errs = pf.validate(good_fields(reusability_score="٧", hook={"type": "سؤال", "duration_sec": "١٫٥"}, why_it_works="سبب 1\n\n سبب 2 \n"), "create")
    assert errs == [] and clean["reusability_score"] == 7 and clean["hook"]["duration_sec"] == 1.5 and clean["why_it_works"] == ["سبب 1", "سبب 2"]
    _, errs = pf.validate(good_fields(reusability_score=11), "create")
    assert any(e["field"] == "reusability_score" for e in errs)
    _, errs = pf.validate(good_fields(reusability_score="7.5"), "create")
    assert any(e["field"] == "reusability_score" and "صحيح" in e["msg"] for e in errs)
    clean, errs = pf.validate(good_fields(production_complexity="عالي"), "create")
    assert errs == [] and clean["production_complexity"] == "high"                      # قيم المستورِد القديم بتنقبل


def test_validate_edit_refuses_to_delete_every_scene():
    clean, errs = pf.validate({"scene_blueprint": []}, "edit", existing=sample())
    assert errs == [{"field": "scene_blueprint", "msg": "لازم يضل مشهد واحد على الأقل"}] and "scene_blueprint" not in clean
    clean, errs = pf.validate({"scene_blueprint": [{"function": "مشهد وحيد"}]}, "edit", existing=sample())
    assert errs == [] and len(clean["scene_blueprint"]) == 1


def test_validate_dialect_sub_must_belong_and_secondary_must_differ():
    _, errs = pf.validate(good_fields(dialect_or_language="gulf", dialect_sub="jordanian"), "create")
    assert any(e["field"] == "dialect_sub" for e in errs)
    clean, errs = pf.validate(good_fields(dialect_or_language="shami", dialect_sub="jordanian"), "create")
    assert errs == [] and clean["dialect_sub"] == "jordanian"
    _, errs = pf.validate(good_fields(framework_secondary="pas"), "create")
    assert any(e["field"] == "framework_secondary" for e in errs)
    clean, errs = pf.validate({"framework_secondary": "story"}, "edit", existing={"framework": "pas"})
    assert errs == [] and clean["framework_secondary"] == "story"
    _, errs = pf.validate({"framework_secondary": "pas"}, "edit", existing={"framework": "pas"})
    assert errs


def test_validate_edit_is_partial_and_refuses_to_blank_filled_core_fields():
    clean, errs = pf.validate({"one_line_summary": "ملخص جديد"}, "edit", existing={"framework": "pas", "product_category": "skincare", "pattern_name": "x"})
    assert errs == [] and list(clean) == ["one_line_summary"]
    for key in ("framework", "product_category", "pattern_name"):
        _, errs = pf.validate({key: ""}, "edit", existing={"framework": "pas", "product_category": "skincare", "pattern_name": "x"})
        assert any(e["field"] == key for e in errs), key
    clean, errs = pf.validate({"framework_secondary": ""}, "edit", existing={"framework": "pas"})
    assert errs == [] and clean["framework_secondary"] is None                          # الاختياري بينمسح
    _, errs = pf.validate({"scene_blueprint": [{"function": "x"}] * 31}, "edit")
    assert any("30" in e["msg"] for e in errs)


def test_schema_is_json_ready_and_covers_every_editable_path_once():
    import json
    s = pf.schema()
    json.dumps(s, ensure_ascii=False)
    paths = [f["path"] for f in s["fields"]]
    assert len(paths) == len(set(paths)) and {"pattern_name", "hook.type", "cta.wording_style", "visual_language.shot_types", "emotional_arc"} <= set(paths)
    assert s["options"]["frameworks"]["pas"] and s["options"]["complexity"]["medium"] == "متوسطة" and s["dialect_sub_parent"]["jordanian"] == "shami"
    assert {f["group"] for f in s["fields"]} <= {g["key"] for g in s["groups"]}
