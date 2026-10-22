"""بطاقة الهوية الإنجليزية للشخصية (identity.py): التجميع، البصمة، التخزين، التعديل اليدوي، المسارات."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
import test_studio_characters_shots as tc  # noqa: E402

import characters  # noqa: E402
import connections  # noqa: E402
import identity  # noqa: E402
import llm  # noqa: E402

FULL = {"skin": "light olive skin", "hair": "long wavy dark brown hair", "outfit": "a navy blouse and light jeans", "look": "soft Levantine features"}


def ch_dict(**kw):
    d = {"gender": "f", "age": 32, "skin": "خمرية", "hair": "بني طويل مموج", "wardrobe": {"description": "بلوزة كحلية وجينز"},
         "market_look": {"SY": "ملامح شامية ناعمة"}}
    d.update(kw)
    return d


class Tr:
    """مترجم مزيّف: بيرجّع الحقول المطلوبة بنسخة إنجليزية ثابتة وبيعدّ النداءات."""

    def __init__(self, out=None, boom=None):
        self.calls, self.out, self.boom = [], out, boom

    def __call__(self, fields):
        self.calls.append(dict(fields))
        if self.boom:
            raise self.boom
        return {k: v for k, v in (self.out or FULL).items() if k in fields}


# ───────────────────────── التجميع ─────────────────────────
def test_the_card_names_age_nationality_and_the_translated_details():
    t = identity.build(ch_dict(), "SY", FULL)
    assert t == ("a 32-year-old Syrian (Levantine Arab) woman with natural Middle Eastern facial features, soft Levantine features, "
                 "light olive skin, long wavy dark brown hair, wearing a navy blouse and light jeans")
    assert "man" in identity.build(ch_dict(gender="m"), "SY", FULL) and "woman" not in identity.build(ch_dict(gender="m"), "SY", FULL)


def test_without_translations_the_card_keeps_the_base_and_points_to_the_reference_images():
    t = identity.build(ch_dict(), "SY")
    assert t == "a 32-year-old Syrian (Levantine Arab) woman with natural Middle Eastern facial features, same skin tone, hair and outfit as the reference images"
    assert not identity.has_arabic(t)


def test_arabic_leftovers_from_a_translator_never_reach_the_card():
    t = identity.build(ch_dict(), "SY", {"skin": "خمرية", "hair": "dark brown hair", "outfit": "wearing بلوزة"})
    assert "dark brown hair" in t and not identity.has_arabic(t) and "wearing" not in t.split("hair")[1]


def test_a_leading_wearing_from_the_translator_is_not_doubled():
    assert identity.build(ch_dict(), "SY", {"outfit": "Wearing a red dress"}).endswith(", wearing a red dress")
    assert identity.build(ch_dict(), "SY", {"outfit": "dressed in a red dress"}).endswith(", wearing a red dress")


def test_country_resolution_prefers_the_request_then_the_only_market_then_generic_arab():
    assert identity.pick_country(ch_dict(), "jo") == "JO"
    assert identity.pick_country(ch_dict(), "") == "SY"
    two = ch_dict(market_look={"SY": "x", "SA": "y"})
    assert identity.pick_country(two, "") == "" and identity.pick_country(two, "SA") == "SA"
    assert identity.pick_country(ch_dict(market_look={}), "ZZ") == ""
    generic = identity.build(two, "", FULL)
    assert generic.startswith("a 32-year-old Middle Eastern Arab woman") or "Middle Eastern Arab woman" in generic
    assert "Saudi (Gulf Arab)" in identity.build(two, "SA", FULL) and "Emirati (Gulf Arab)" in identity.build(two, "AE", FULL)


def test_age_is_skipped_when_missing_and_the_text_is_capped():
    assert identity.build(ch_dict(age=None), "SY", FULL).startswith("a Syrian (Levantine Arab) woman")
    long = {"outfit": "a " + "very " * 200 + "long dress"}
    assert len(identity.build(ch_dict(), "SY", long)) <= identity.MAX_TEXT


def test_the_negative_prompt_blocks_the_known_drift():
    n = identity.negative()
    assert "East Asian facial features" in n and "different person" in n and "face morphing" in n and not identity.has_arabic(n)


# ───────────────────────── المصدر والبصمة ─────────────────────────
def test_source_fields_use_the_look_of_the_chosen_country_and_drop_empty_ones():
    ch = ch_dict(market_look={"SY": "ملامح شامية", "SA": "ملامح خليجية"})
    assert identity.source_fields(ch, "SA")["look"] == "ملامح خليجية" and identity.source_fields(ch, "SY")["look"] == "ملامح شامية"
    assert "look" not in identity.source_fields(ch, "")                                   # أكتر من بلد وما اختار
    assert set(identity.source_fields(ch_dict(skin="", hair=" "), "SY")) == {"outfit", "look"}


def test_the_source_hash_changes_with_every_identity_relevant_field_only():
    base = identity.src_hash(ch_dict(), "SY")
    assert identity.src_hash(ch_dict(), "SY") == base
    for change in ({"skin": "بيضاء"}, {"hair": "أسود"}, {"age": 33}, {"wardrobe": {"description": "فستان"}}, {"market_look": {"SY": "غيرها"}}):
        assert identity.src_hash(ch_dict(**change), "SY") != base, change
    assert identity.src_hash(ch_dict(persona="جديدة", name_ar="س"), "SY") == base                  # الطابع والاسم مش هوية شكل
    assert identity.src_hash(ch_dict(skin="خُمريّة"), "SY") == identity.src_hash(ch_dict(skin="خمريّة"), "SY")      # التشكيل ما بيفرق


def test_current_is_the_stored_card_only_while_fresh_complete_or_manual():
    ch = ch_dict()
    assert identity.current(ch, "SY")["stale"] is True and identity.current(ch, "SY")["complete"] is False
    fresh = {**ch, "identity_en": {"text": "STORED", "auto": True, "complete": True, "src": identity.src_hash(ch, "SY")}}
    assert identity.current(fresh, "SY") == {"text": "STORED", "auto": True, "complete": True, "stale": False}
    old = {**fresh, "skin": "بيضاء"}
    assert identity.current(old, "SY")["text"] != "STORED" and identity.current(old, "SY")["stale"] is True
    partial = {**ch, "identity_en": {"text": "STORED", "auto": True, "complete": False, "src": ""}}
    assert identity.current(partial, "SY")["text"] != "STORED"                               # بيانات مختلفة عن اللي انبنت منها
    half = {**ch, "identity_en": {"text": "HALF", "auto": True, "complete": False, "src": identity.src_hash(ch, "SY")}}
    assert identity.current(half, "SY") == {"text": "HALF", "auto": True, "complete": False, "stale": True}      # نصف مترجمة: بنستعملها وبنعيد المحاولة
    manual = {**old, "identity_en": {"text": "MY TEXT", "auto": False, "complete": True, "src": ""}}
    assert identity.current(manual, "SY") == {"text": "MY TEXT", "auto": False, "complete": True, "stale": False}
    bare = ch_dict(skin="", hair="", wardrobe={"description": ""}, market_look={})
    assert identity.current(bare)["complete"] is True                                       # ما في شي ينترجم


def test_text_of_is_empty_without_a_character():
    assert identity.text_of(None) == "" and "Syrian" in identity.text_of(ch_dict(), "SY")


# ───────────────────────── التخزين ─────────────────────────
def test_ensure_translates_once_stores_the_card_and_retranslates_only_when_the_data_changes(env):
    ch = tc.mk(env, name="ريم", country="SY")
    tr = Tr()
    a = identity.ensure(ch["id"], "SY", translate=tr)
    assert a["complete"] is True and a["auto"] is True and "light olive skin" in a["text"] and len(tr.calls) == 1
    assert set(tr.calls[0]) == {"skin", "hair", "outfit", "look"} and tr.calls[0]["skin"] == "خمرية"
    stored = characters.get(ch["id"])["identity_en"]
    assert stored["text"] == a["text"] and stored["src"] and stored["country"] == "SY" and stored["at"]
    identity.ensure(ch["id"], "SY", translate=tr)
    assert len(tr.calls) == 1                                                                # حديثة: ما بنترجم
    characters.update(ch["id"], {"skin": "بيضاء"})
    assert identity.current(characters.get(ch["id"]), "SY")["stale"] is True
    identity.ensure(ch["id"], "SY", translate=Tr({"skin": "fair skin", "hair": "h", "outfit": "o", "look": "l"}))
    assert "fair skin" in characters.get(ch["id"])["identity_en"]["text"]
    identity.ensure(ch["id"], "SY", translate=tr, force=True)
    assert len(tr.calls) == 2                                                                # force بيعيد حتى لو حديثة


def test_a_failing_translator_leaves_an_incomplete_base_card_and_retries_next_time(env):
    ch = tc.mk(env, name="ريم", country="SY")
    a = identity.ensure(ch["id"], "SY", translate=Tr(boom=RuntimeError("no key")))
    assert a["complete"] is False and "same skin tone, hair and outfit" in a["text"] and "Syrian" in a["text"]
    stored = characters.get(ch["id"])["identity_en"]
    assert stored["complete"] is False and stored["src"] == identity.src_hash(characters.get(ch["id"]), "SY")
    good = Tr()
    b = identity.ensure(ch["id"], "SY", translate=good)
    assert b["complete"] is True and len(good.calls) == 1


def test_a_translator_that_skips_a_field_counts_as_incomplete(env):
    ch = tc.mk(env, name="ريم", country="SY")
    a = identity.ensure(ch["id"], "SY", translate=Tr({"skin": "olive skin"}))
    assert a["complete"] is False and "olive skin" in a["text"]


def test_a_character_without_free_text_needs_no_translator(env):
    ch = characters.create({"name_ar": "ليلى", "gender": "f", "age": 30})
    tr = Tr()
    a = identity.ensure(ch["id"], "", translate=tr)
    assert a["complete"] is True and tr.calls == [] and a["text"].startswith("a 30-year-old Middle Eastern Arab woman")


def test_a_manual_card_is_never_overwritten_and_reset_returns_to_auto(env):
    ch = tc.mk(env, name="ريم", country="SY")
    m = identity.set_manual(ch["id"], "  a 32-year-old Syrian woman,   olive skin, dark hair  ")
    assert m == {"text": "a 32-year-old Syrian woman, olive skin, dark hair", "auto": False, "complete": True, "stale": False}
    tr = Tr()
    identity.ensure(ch["id"], "SY", translate=tr, force=True)
    assert tr.calls == [] and characters.get(ch["id"])["identity_en"]["text"].startswith("a 32-year-old Syrian woman, olive")
    characters.update(ch["id"], {"skin": "بيضاء"})
    assert identity.current(characters.get(ch["id"]), "SY")["auto"] is False                  # حتى لو تغيّرت البيانات
    r = identity.reset(ch["id"])
    assert r["auto"] is True and "identity_en" not in characters.get(ch["id"])
    assert identity.set_manual(ch["id"], "   ")["auto"] is True                                # نص فاضي = رجوع


def test_manual_cards_must_be_english_and_short(env):
    ch = tc.mk(env, name="ريم")
    with pytest.raises(identity.IdentityError, match="بالإنجليزي"):
        identity.set_manual(ch["id"], "امرأة شامية")
    with pytest.raises(identity.IdentityError, match="أطول"):
        identity.set_manual(ch["id"], "x " * 400)
    with pytest.raises(identity.IdentityError):
        identity.ensure("ch_f_999")


def test_saving_the_card_does_not_touch_the_characters_status_or_update_time(env):
    ch = tc.mk(env, name="ريم", country="SY")
    before = characters.get(ch["id"])
    identity.ensure(ch["id"], "SY", translate=Tr())
    after = characters.get(ch["id"])
    assert after["status"] == before["status"] == "ready" and after["updated_at"] == before["updated_at"]
    assert {k: v for k, v in after.items() if k != "identity_en"} == before


# ───────────────────────── الذكاء ─────────────────────────
def test_llm_translate_sends_the_fields_once_to_the_imgprompt_task_and_filters_the_reply(env):
    env.fake.queue("imgprompt", {"skin": "olive skin", "hair": "brown hair", "extra": "ignored", "outfit": ""})
    out = identity.llm_translate({"skin": "خمرية", "hair": "بني", "outfit": "فستان"})
    assert out == {"skin": "olive skin", "hair": "brown hair"}                                 # الفاضي والغريب بيطلعوا
    assert env.fake.count("imgprompt") == 1 and "خمرية" in env.fake.user("imgprompt")
    call = env.fake.calls[-1]
    assert "JSON" in call["system"] and "never invent" in call["system"]
    env.fake.queue("imgprompt", ["not", "a", "dict"])
    with pytest.raises(identity.IdentityError):
        identity.llm_translate({"skin": "x"})


def test_the_task_is_registered_for_the_models_settings():
    assert "imgprompt" in llm.TASK_LABELS and "imgprompt" in connections.TASK_PROFILE and "imgprompt" in llm.LEGACY_MODEL_KEYS


# ───────────────────────── المسارات ─────────────────────────
def test_identity_routes_read_edit_reset_and_rebuild(env, monkeypatch):
    ch = tc.mk(env, name="ريم", country="SY")
    c = tc.client()
    g = c.get(f"/api/characters/{ch['id']}/identity").json()
    assert g["stale"] is True and g["complete"] is False and g["negative"] == identity.NEGATIVE and g["country"] == "SY"
    monkeypatch.setattr(identity, "llm_translate", Tr())
    r = c.post(f"/api/characters/{ch['id']}/identity/rebuild", json={"country": "SY"}).json()
    assert r["complete"] is True and r["auto"] is True and "light olive skin" in r["text"] and r["stale"] is False
    m = c.put(f"/api/characters/{ch['id']}/identity", json={"text": "a Syrian woman, olive skin"}).json()
    assert m["auto"] is False and m["text"] == "a Syrian woman, olive skin"
    assert c.put(f"/api/characters/{ch['id']}/identity", json={"text": "عربي"}).status_code == 400
    back = c.put(f"/api/characters/{ch['id']}/identity", json={"text": ""}).json()
    assert back["auto"] is True
    assert c.get("/api/characters/ch_f_999/identity").status_code == 404
    assert c.get("/api/characters/bad/identity").status_code == 400
    assert c.post("/api/characters/ch_f_999/identity/rebuild", json={}).status_code == 400
    assert c.put("/api/characters/ch_f_999/identity", json={"text": "x"}).status_code == 400


def test_rebuild_without_a_working_llm_reports_an_incomplete_card_not_an_error(env, monkeypatch):
    ch = tc.mk(env, name="ريم", country="SY")
    monkeypatch.setattr(identity, "llm_translate", Tr(boom=RuntimeError("401")))
    r = tc.client().post(f"/api/characters/{ch['id']}/identity/rebuild", json={}).json()
    assert r["complete"] is False and r["auto"] is True and "Syrian" in r["text"]
