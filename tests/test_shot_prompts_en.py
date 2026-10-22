"""النسخة الإنجليزية لبرومبتات اللقطات (prompt_model): ترجمة + بطاقة الهوية، والرجوع للعربي لو الذكاء مش متاح."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage, gen_and_choose, first_shot  # noqa: E402,F401
import test_studio_characters_shots as tc  # noqa: E402

import characters  # noqa: E402
import identity  # noqa: E402
import image_studio as ims  # noqa: E402
import shot_prompts as sp  # noqa: E402
import timeline  # noqa: E402

CARD = "a 32-year-old Syrian (Levantine Arab) woman with natural Middle Eastern facial features"


def en_of(item):
    return f"English version of {item['id']}"


def translator(calls=None, fn=en_of):
    def t(items):
        if calls is not None:
            calls.append([i["id"] for i in items])
        return {i["id"]: fn(i) for i in items}

    return t


def built(env, monkeypatch, with_char=True):
    st = tc.approved_timeline(env, monkeypatch, with_char=with_char)
    tl = timeline.load("s1")
    ch = characters.get("ch_f_001") if with_char else None
    sp.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", ch, "kama")
    return st, tl, ch


def shots(tl):
    return [s for sc in tl["scenes"] for s in sc["shots"]]


# ───────────────────────── التجميع ─────────────────────────
def test_the_english_prompt_is_the_identity_card_plus_the_translation_plus_the_no_text_rule(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    r = sp.english_for(tl, ch, "SY", translate=translator(), log=lambda *_: None)
    assert r == {"done": len(shots(tl)), "failed": 0}
    face = next(s for s in shots(tl) if s["type"] != "hand_product")
    assert face["prompt_model"].startswith(f"Subject (identical in every shot): {CARD}")
    assert "Keep exactly the same face as in the attached reference images." in face["prompt_model"]
    assert face["prompt_model"].endswith(f"English version of {face['id']}. No text, letters, numbers or logos in the image.")
    hand = next(s for s in shots(tl) if s["type"] == "hand_product")
    assert hand["prompt_model"].startswith("English version of") and "Subject" not in hand["prompt_model"]      # اليد بلا وجه


def test_without_a_character_the_prompt_is_just_the_translation(env, monkeypatch):
    _st, tl, _ch = built(env, monkeypatch, with_char=False)
    sp.english_for(tl, None, "", translate=translator(), log=lambda *_: None)
    assert all(s["prompt_model"].startswith("English version of") for s in shots(tl))


@pytest.mark.parametrize("text", ["A close-up. No text anywhere.", "Close-up without any text or letters", "no writing, no logos",
                                  "Medium shot, no on-screen text"])
def test_an_existing_no_text_rule_is_not_duplicated(text):
    out = sp._finish_en(text, {"type": "close"}, None)
    assert out.lower().count("text") <= 2 and "No text, letters, numbers or logos" not in out


def test_the_no_text_rule_is_added_when_missing_and_the_prompt_is_capped():
    assert sp._finish_en("A medium shot", {"type": "close"}, None) == "A medium shot. No text, letters, numbers or logos in the image."
    assert len(sp._finish_en("x " * 2000, {"type": "close"}, None)) <= sp.MAX_LEN


def test_the_translator_is_called_in_chunks_and_only_for_shots_without_an_english_version(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    monkeypatch.setattr(sp, "_EN_CHUNK", 4)
    s = shots(tl)
    s[0]["prompt_model"] = "ready already"
    calls = []
    r = sp.english_for(tl, ch, "SY", translate=translator(calls), log=lambda *_: None)
    assert r["done"] == len(s) - 1 and all(len(c) <= 4 for c in calls) and len(calls) == -(-(len(s) - 1) // 4)
    assert s[0]["prompt_model"] == "ready already" and s[0]["id"] not in sum(calls, [])
    assert sp.english_for(tl, ch, "SY", translate=translator(calls), log=lambda *_: None) == {"done": 0, "failed": 0}
    again = sp.english_for(tl, ch, "SY", translate=translator(), only=[s[1]["id"]], force=True, log=lambda *_: None)
    assert again["done"] == 1 and s[2]["prompt_model"] != "ready already"


def test_only_limits_the_shots_and_inherited_or_empty_ones_are_skipped(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    s = shots(tl)
    s[1]["inherited"] = True
    s[2]["prompt_ar"] = ""
    sp.english_for(tl, ch, "SY", translate=translator(), only=[s[0]["id"], s[1]["id"], s[2]["id"]], log=lambda *_: None)
    assert s[0]["prompt_model"] and not s[1]["prompt_model"] and not s[2]["prompt_model"] and not s[3]["prompt_model"]


def test_a_failing_or_arabic_translation_leaves_the_shot_without_an_english_version(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    logs = []

    def boom(items):
        raise RuntimeError("401")

    r = sp.english_for(tl, ch, "SY", translate=boom, log=logs.append)
    assert r["done"] == 0 and r["failed"] == len(shots(tl)) and all(not s["prompt_model"] for s in shots(tl))
    assert any("تعذّرت ترجمة" in m and "RuntimeError" in m and "401" not in m for m in logs)
    r2 = sp.english_for(tl, ch, "SY", translate=translator(fn=lambda i: "هاي لقطة قريبة على العبوة بدون ترجمة"), log=lambda *_: None)
    assert r2["done"] == 0 and all(not s["prompt_model"] for s in shots(tl))
    r3 = sp.english_for(tl, ch, "SY", translate=translator(fn=lambda i: "Close shot of the VARA عبوة box"), log=lambda *_: None)
    assert r3["done"] == len(shots(tl))                                                      # كلمة عربية وحدة (اسم/مصطلح) مقبولة


def test_a_partial_reply_translates_what_it_can(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    first = shots(tl)[0]["id"]
    r = sp.english_for(tl, ch, "SY", translate=lambda items: {first: "Only the first one"}, log=lambda *_: None)
    assert r["done"] == 1 and shots(tl)[0]["prompt_model"].endswith("Only the first one. No text, letters, numbers or logos in the image.")


def test_the_identity_card_is_translated_once_before_the_shots_when_a_character_is_used(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    seen = []
    monkeypatch.setattr(identity, "llm_translate", lambda f: seen.append(dict(f)) or {"skin": "olive skin", "hair": "brown hair",
                                                                                      "outfit": "a navy blouse", "look": "Levantine features"})
    sp.english_for(tl, ch, "SY", translate=translator(), log=lambda *_: None)
    assert len(seen) == 1 and "olive skin" in shots(tl)[0]["prompt_model"] and "wearing a navy blouse" in shots(tl)[0]["prompt_model"]
    sp.english_for(tl, characters.get("ch_f_001"), "SY", translate=translator(), force=True, log=lambda *_: None)
    assert len(seen) == 1                                                                    # البطاقة محفوظة


def test_a_broken_identity_step_never_blocks_the_prompts(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(identity, "ensure", boom)
    logs = []
    r = sp.english_for(tl, ch, "SY", translate=translator(), log=logs.append)
    assert r["done"] == len(shots(tl)) and any("بطاقة الهوية" in m for m in logs)


# ───────────────────────── ما بيروح للموديل ─────────────────────────
def test_model_prompt_prefers_the_english_version_and_falls_back_to_card_plus_arabic(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    face = next(s for s in shots(tl) if s["type"] != "hand_product")
    fb = sp.model_prompt(face, ch, "SY")
    assert fb.startswith(f"Subject (identical in every shot): {CARD}") and fb.endswith(face["prompt_ar"])
    assert sp.model_prompt(face)[:30] == fb[:30]                                            # بتجيب الشخصية من مرجع اللقطة
    face["prompt_model"] = "ready english"
    assert sp.model_prompt(face, ch, "SY") == "ready english"
    hand = next(s for s in shots(tl) if s["type"] == "hand_product")
    assert sp.model_prompt(hand, ch, "SY") == hand["prompt_ar"]
    face["prompt_model"] = ""
    face["prompt_ar"] = " "
    assert sp.model_prompt(face, ch) == ""


def test_without_a_character_the_fallback_is_the_arabic_prompt_as_it_was(env, monkeypatch):
    _st, tl, _ch = built(env, monkeypatch, with_char=False)
    sh = shots(tl)[0]
    assert sp.model_prompt(sh) == sh["prompt_ar"]


def test_editing_the_arabic_prompt_clears_the_english_version(env, monkeypatch):
    _st, tl, ch = built(env, monkeypatch)
    sp.english_for(tl, ch, "SY", translate=translator(), log=lambda *_: None)
    sh = shots(tl)[0]
    sp.set_prompt(tl, sh["id"], "لقطة جديدة تماماً")
    assert sh["prompt_model"] == ""


def test_refine_adds_the_identity_card_to_its_english_version(env, monkeypatch):
    import llm
    _st, tl, ch = built(env, monkeypatch)
    ids = [s["id"] for s in shots(tl)]
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"shots": [{"id": i, "prompt_ar": f"محسّن {i}", "prompt_model": f"english {i}"} for i in ids]})
    sp.refine(tl, log=lambda *_: None, ch=ch, country="SY")
    face = next(s for s in shots(tl) if s["type"] != "hand_product")
    assert face["prompt_model"].startswith("Subject (identical in every shot):") and f"english {face['id']}" in face["prompt_model"]


def test_the_default_translator_sends_the_arabic_prompts_to_the_imgprompt_task(env):
    env.fake.queue("imgprompt", {"shots": [{"id": "s1c1", "en": "A calm close-up"}, {"id": "x", "en": 5}, "junk"]})
    out = sp._llm_translate([{"id": "s1c1", "ar": "لقطة هادئة"}])
    assert out["s1c1"] == "A calm close-up" and env.fake.count("imgprompt") == 1
    assert "لقطة هادئة" in env.fake.user("imgprompt") and "JSON only" in env.fake.calls[-1]["system"]
    env.fake.queue("imgprompt", "not json shape")
    assert sp._llm_translate([{"id": "s1c1", "ar": "x"}]) == {}


# ───────────────────────── التوليد والمسارات ─────────────────────────
def test_generation_translates_once_stores_it_and_sends_the_english_to_the_model(stage, monkeypatch):
    calls = []
    monkeypatch.setattr(sp, "_llm_translate", translator(calls))
    sh = first_shot(timeline.load("s1"))
    ims.generate_shot(stage.script, sh["id"], n=2, log=lambda *_: None)
    assert calls == [[sh["id"]]]                                                              # ترجمة وحدة لخيارين
    sent = stage.calls[0]["visual"]
    assert sent.startswith("Subject (identical in every shot):") and f"English version of {sh['id']}" in sent
    assert stage.calls[1]["visual"] == sent
    stored = ims._shot(timeline.load("s1"), sh["id"])[1]
    assert stored["prompt_model"] == sent and stored["prompt_ar"]
    ims.generate_shot(stage.script, sh["id"], n=1, log=lambda *_: None)
    assert calls == [[sh["id"]]]                                                              # المخزّنة ما بتنترجم تاني


def test_a_translation_failure_does_not_stop_generation_and_retries_next_time(stage, monkeypatch):
    state = {"ok": False, "n": 0}

    def flaky(items):
        state["n"] += 1
        if not state["ok"]:
            raise RuntimeError("no key")
        return {i["id"]: "Recovered english" for i in items}

    monkeypatch.setattr(sp, "_llm_translate", flaky)
    sh = first_shot(timeline.load("s1"))
    r = ims.generate_shot(stage.script, sh["id"], n=1, log=lambda *_: None)
    assert r["made"] == 1 and stage.calls[-1]["visual"].endswith(sh["prompt_ar"])            # عربي + بطاقة الهوية
    state["ok"] = True
    ims.generate_shot(stage.script, sh["id"], n=1, log=lambda *_: None)
    assert "Recovered english" in stage.calls[-1]["visual"] and state["n"] == 2


def test_generate_all_translates_every_missing_shot_in_one_batch(stage, monkeypatch):
    calls = []
    monkeypatch.setattr(sp, "_llm_translate", translator(calls))
    ims.generate_all(stage.script, n=1, log=lambda *_: None)
    ids = [s["id"] for s in shots(timeline.load("s1"))]
    assert len(calls) == 1 and sorted(calls[0]) == sorted(ids)
    assert all(c["visual"] for c in stage.calls) and len(stage.calls) == len(ids)


def test_the_extension_queue_gets_the_same_english_or_card_plus_arabic(stage, monkeypatch):
    import ext_bridge
    monkeypatch.setattr(sp, "_llm_translate", translator())
    tl = timeline.load("s1")
    ch = characters.get(stage.ch["id"])
    sp.english_for(tl, ch, "", only=[first_shot(tl)["id"]], log=lambda *_: None)
    timeline.save("s1", tl)
    q = ext_bridge.build_queue(stage.script)
    first = next(x for x in q if x["shot_id"] == first_shot(tl)["id"])
    other = next(x for x in q if x["shot_id"] != first["shot_id"] and x["type"] != "hand_product")
    assert "English version of" in first["prompt"] and other["prompt"].startswith("Subject (identical in every shot):")


def test_the_build_route_translates_and_survives_a_dead_llm(env, monkeypatch):
    c = tc.client()
    st = tc.approved_timeline(env, monkeypatch, with_char=True)
    monkeypatch.setattr(sp, "_llm_translate", translator())
    r = c.post("/api/studio/s1.json/shots/build")
    assert r.status_code == 200
    sh = [s for sc in r.json()["timeline"]["scenes"] for s in sc["shots"]]
    assert all(s["prompt_model"] for s in sh)
    face = next(s for s in sh if s["type"] != "hand_product")
    assert face["prompt_model"].startswith("Subject (identical in every shot):") and face["prompt_ar"] != face["prompt_model"]

    def boom(items):
        raise RuntimeError("down")

    monkeypatch.setattr(sp, "_llm_translate", boom)
    import studio_state
    studio_state.set_state("s1", 6, "not_started", "x")
    r2 = c.post("/api/studio/s1.json/shots/build")
    assert r2.status_code == 200
    assert all(not s["prompt_model"] for sc in r2.json()["timeline"]["scenes"] for s in sc["shots"])          # بنيت من جديد بلا إنجليزي
    assert r2.json()["problems"] == [] and st.script.exists()
