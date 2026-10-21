"""استوديو الإنتاج — المحطة ٣ (مكتبة الشخصيات) والمحطة ٦ (برومبتات اللقطات)."""

import json
import os
import sqlite3
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_voice_timeline as tv  # noqa: E402

import characters  # noqa: E402
import shot_prompts  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import voice_studio  # noqa: E402

PNG = b"\x89PNG" + b"x" * 700


def mk(env, gender="f", name="ريم", age=32, cats=("eye_care",), country="SY", ready=True, **kw):
    ch = characters.create({
        "name_ar": name, "gender": gender, "age": age, "skin": "خمرية", "hair": "بني", "persona": "دافئة",
        "wardrobe": {"description": "بلوزة كحلية", "palette": ["#123456"]},
        "categories": list(cats), "market_look": {country: "ملامح شامية"},
        "voice": {"provider": "elevenlabs", "voice_id": "VOICE_" + name, "model": "eleven_v3"}, **kw})
    if ready:
        for v in characters.VIEWS:
            ch = characters.set_sheet(ch["id"], v, f"{v}.png", PNG)
    return ch


# ───────────────────────── مكتبة الشخصيات ─────────────────────────
def test_create_needs_name_and_age_and_ids_are_per_gender(env):
    with pytest.raises(characters.CharacterError):
        characters.create({"gender": "f", "age": 30})
    with pytest.raises(characters.CharacterError):
        characters.create({"name_ar": "س", "gender": "f"})
    a = characters.create({"name_ar": "أ", "gender": "f", "age": 30})
    b = characters.create({"name_ar": "ب", "gender": "m", "age": 40})
    c = characters.create({"name_ar": "ج", "gender": "f", "age": 28})
    assert (a["id"], b["id"], c["id"]) == ("ch_f_001", "ch_m_001", "ch_f_002")


def test_not_ready_until_five_sheets_voice_and_details(env):
    ch = characters.create({"name_ar": "ريم", "gender": "f", "age": 30})
    assert ch["status"] == "draft"
    miss = characters.missing_for_ready(ch)
    assert "ورقة مرجعية: أمام" in miss and "صوت ثابت (المزوّد + المعرّف)" in miss
    full = mk(env, name="نور")
    assert full["status"] == "ready" and characters.missing_for_ready(full) == []
    for v in list(characters.VIEWS)[:-1]:
        pass
    partial = mk(env, name="لينا", ready=False)
    characters.set_sheet(partial["id"], "front", "f.png", PNG)
    assert characters.get(partial["id"])["status"] == "draft"


def test_sheet_upload_validates_and_stays_relative(env):
    ch = characters.create({"name_ar": "ريم", "gender": "f", "age": 30})
    with pytest.raises(characters.CharacterError):
        characters.set_sheet(ch["id"], "front", "x.gif", PNG)
    with pytest.raises(characters.CharacterError):
        characters.set_sheet(ch["id"], "nope", "x.png", PNG)
    with pytest.raises(characters.CharacterError):
        characters.set_sheet(ch["id"], "front", "x.png", b"tiny")
    ch = characters.set_sheet(ch["id"], "front", "x.png", PNG)
    assert ch["sheet"]["front"] == "sheet/front.png"
    assert ":\\" not in json.dumps(ch) and ":/" not in json.dumps(ch)
    assert characters.sheet_path(ch["id"], "front").exists()


def test_real_person_needs_signed_consent(env):
    ch = mk(env, name="حقيقية", source="real_person")
    assert ch["status"] == "draft" and "ملف الموافقة" in " ".join(characters.missing_for_ready(ch))
    with pytest.raises(characters.CharacterError):
        characters.set_consent(ch["id"], "c.pdf", PNG, "", "إعلانات كاما")
    ch = characters.set_consent(ch["id"], "c.pdf", PNG, "2026-09-01", "إعلانات كاما")
    assert ch["status"] == "ready" and ch["consent"]["signed_at"] == "2026-09-01"
    synth = mk(env, name="اصطناعية")
    with pytest.raises(characters.CharacterError):
        characters.set_consent(synth["id"], "c.pdf", PNG, "2026-09-01", "x")


def test_gender_cannot_change_and_retired_are_hidden(env):
    ch = mk(env)
    with pytest.raises(characters.CharacterError):
        characters.update(ch["id"], {"gender": "m"})
    assert characters.update(ch["id"], {"persona": "جدّية"})["persona"] == "جدّية"
    characters.retire(ch["id"])
    assert characters.list_all() == [] and len(characters.list_all(True)) == 1
    assert characters.summary()["ready"] == {"m": 0, "f": 0}


def test_summary_tracks_quota_20_men_30_women(env):
    mk(env, "f", "أ"); mk(env, "m", "ب")
    s = characters.summary()
    assert s["target"] == {"m": 20, "f": 30} and s["remaining"] == {"m": 19, "f": 29}


# ───────────────────────── الترشيح والاستخدام ─────────────────────────
def test_suggest_ranks_by_category_market_and_audience_and_returns_three(env):
    good = mk(env, "f", "الأنسب", cats=("eye_care",), country="SY")
    mk(env, "f", "بعيدة", cats=("apparel",), country="SA")
    mk(env, "m", "ذكر", cats=("eye_care",), country="SY")
    mk(env, "f", "رابعة", cats=("eye_care",), country="EG")
    mk(env, "f", "مسودة", ready=False)
    b = {"category": "eye_care", "target_audience": "نساء من 30 إلى 50"}
    s = characters.suggest(b, "SY", "kama")
    assert len(s) == 3 and s[0]["character"]["id"] == good["id"]
    assert all(x["character"]["status"] == "ready" for x in s)
    assert any("سوق" in r for r in s[0]["reasons"])


def test_usage_lowers_score_and_active_ads_warn(env):
    a = mk(env, "f", "أ", cats=("eye_care",), country="SY")
    b = mk(env, "f", "ب", cats=("eye_care",), country="SY")
    br = {"category": "eye_care"}
    for i in range(3):
        characters.record_use(a["id"], "kama", "SY", f"VP-kama-{i}-v1")
    # ٣ إعلانات شغّالة (إنفاق حديث) بـ perf.db
    db = env.lib / "perf.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ad_daily (ad_name TEXT, script_id TEXT, date TEXT, spend REAL, orders INT, "
                "delivered INT, collected INT, delivery_rate REAL, cost_per_delivered REAL, engagement REAL, synced_at TEXT)")
    for i in range(3):
        con.execute("INSERT INTO ad_daily (ad_name, script_id, date, spend) VALUES (?,?,?,?)",
                    (f"x{i}", f"VP-kama-{i}-v1", date.today().isoformat(), 10))
    con.commit(); con.close()
    assert characters.active_ads(a["id"], "kama") == 3
    rep = characters.usage_report(a["id"], "kama")
    assert "3" in rep["warning"]
    top = characters.suggest(br, "SY", "kama")
    assert top[0]["character"]["id"] == b["id"]                  # الأقل استخداماً أولاً
    assert [x for x in top if x["character"]["id"] == a["id"]][0]["warning"]
    assert characters.usage_report(b["id"], "kama")["warning"] == ""


# ───────────────────────── اختيار السيناريو (محطة ٣) ─────────────────────────
def test_no_library_means_narrator_approved_but_library_requires_choice(env, monkeypatch):
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    studio_state.derive_early("s1", st.script)
    assert studio_state.state_of("s1", 3) == "approved"          # راوٍ
    mk(env)
    studio_state.derive_early("s1", st.script)
    assert studio_state.state_of("s1", 3) == "awaiting_choice"
    with pytest.raises(voice_studio.VoiceGateError):             # ما صوت قبل اختيار الشخصية
        voice_studio.produce(st.script, log=lambda *_: None)


def test_choose_records_usage_sets_state_and_new_script_starts_fresh(env, monkeypatch):
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    ch = mk(env)
    script = json.loads(st.script.read_text(encoding="utf-8"))
    characters.choose("s1", script, ch["id"])
    assert characters.chosen("s1")["character_id"] == ch["id"]
    assert studio_state.state_of("s1", 3) == "approved"
    assert characters.usage_report(ch["id"], "testp")["scripts"] == ["VP-testp-1-v1"]
    other = env.script_file("s2.json", make_script(),
                            meta={"product": "TESTP", "product_file": "testp.json", "product_code": "testp",
                                  "number": 2, "version": 1, "script_id": "VP-testp-2-v1", "pattern_id": "p1",
                                  "status": "draft"})
    assert characters.chosen(other.stem) is None                 # ما بينتقل الاختيار تلقائياً


def test_choose_refuses_unready_and_changing_marks_downstream_stale(env, monkeypatch):
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    script = json.loads(st.script.read_text(encoding="utf-8"))
    draft = mk(env, "f", "مسودة", ready=False)
    with pytest.raises(characters.CharacterError):
        characters.choose("s1", script, draft["id"])
    a, b = mk(env, "f", "أ"), mk(env, "f", "ب")
    characters.choose("s1", script, a["id"])
    for n in (4, 5):
        studio_state.set_state("s1", n, "approved")
    characters.choose("s1", script, b["id"])
    assert studio_state.state_of("s1", 3) == "approved"
    assert studio_state.state_of("s1", 4) == "stale" and studio_state.state_of("s1", 5) == "stale"


def test_chosen_character_voice_is_used_and_owner_override_wins(env, monkeypatch):
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    ch = mk(env, name="صوتها")
    characters.choose("s1", json.loads(st.script.read_text(encoding="utf-8")), ch["id"])
    seen = []
    import tts
    real = tts.speak

    def spy(text, out, ov=None, want_timing=False):
        seen.append(dict(ov or {}))
        return real(text, out, ov, want_timing)

    monkeypatch.setattr(tts, "speak", spy)
    voice_studio.produce(st.script, log=lambda *_: None)
    assert seen and seen[0]["voice"] == "VOICE_صوتها" and seen[0]["provider"] == "elevenlabs"
    seen.clear()
    voice_studio.produce(st.script, {"voice": "OWNER"}, log=lambda *_: None)
    assert seen[0]["voice"] == "OWNER"


# ───────────────────────── API ─────────────────────────
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_characters, routes_studio
    app = FastAPI()
    app.include_router(routes_characters.router)
    app.include_router(routes_studio.router)
    return TestClient(app)


def test_api_character_library_and_choice_flow(env, monkeypatch):
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    c = client()
    r = c.post("/api/characters", json={"name_ar": "ريم", "gender": "f", "age": 30, "skin": "خمرية", "hair": "بني",
                                        "persona": "دافئة", "wardrobe": {"description": "بلوزة"},
                                        "categories": ["eye_care"],
                                        "voice": {"provider": "elevenlabs", "voice_id": "V", "model": "m"}})
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["missing"]
    cid = r.json()["id"]
    for v in characters.VIEWS:
        rr = c.post(f"/api/characters/{cid}/sheet/{v}", files={"file": (f"{v}.png", PNG, "image/png")})
        assert rr.status_code == 200
    assert c.get(f"/api/characters/{cid}").json()["status"] == "ready"
    assert c.get(f"/api/characters/{cid}/sheet/front").status_code == 200
    assert c.post(f"/api/characters/{cid}/sheet/front", files={"file": ("x.gif", PNG, "image/gif")}).status_code == 400
    lst = c.get("/api/characters").json()
    assert lst["summary"]["ready"]["f"] == 1
    sug = c.get("/api/studio/s1.json/characters").json()
    assert sug["library_active"] and sug["suggestions"][0]["character"]["id"] == cid and sug["chosen"] is None
    assert c.post("/api/studio/s1.json/character", json={"character_id": "ch_f_099"}).status_code == 409
    assert c.post("/api/studio/s1.json/character", json={"character_id": cid}).status_code == 200
    assert c.get("/api/studio/s1.json/characters").json()["chosen"]["character_id"] == cid


def test_api_rejects_bad_character_ids_and_paths(env):
    c = client()
    assert c.get("/api/characters/..%2Fetc").status_code in (400, 404)
    assert c.get("/api/characters/not_an_id").status_code == 400


# ───────────────────────── برومبتات اللقطات (محطة ٦) ─────────────────────────
def approved_timeline(env, monkeypatch, with_char=False):
    st = tv.produce_ok(env, monkeypatch)
    if with_char:
        ch = mk(env, name="ريم")
        characters.choose("s1", json.loads(st.script.read_text(encoding="utf-8")), ch["id"])
    voice_studio.approve_voice(st.script)
    return st


def test_build_writes_a_prompt_for_every_shot_with_its_words_and_no_text_rule(env, monkeypatch):
    st = approved_timeline(env, monkeypatch)
    tl = timeline.load("s1")
    script = json.loads(st.script.read_text(encoding="utf-8"))
    shot_prompts.build(tl, script, "كاما", None, "kama")
    seen = set()
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            p = sh["prompt_ar"]
            assert p and len(p) <= shot_prompts.MAX_LEN
            assert "بدون أي كتابة" in p
            first_word = tl["words"][sh["word_range"][0]]["text"]
            assert first_word in p
            assert p not in seen
            seen.add(p)
            assert sh["refs"]["product_ref"] == "kama"
    assert shot_prompts.validate(tl) == []
    assert timeline.validate(tl)["ok"]                      # البرومبتات ما بتلمس التوقيت


def test_adjacent_shots_have_different_types(env, monkeypatch):
    st = approved_timeline(env, monkeypatch)
    tl = timeline.load("s1")
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            sh["type"] = "medium"                            # كلهم نفس النوع — لازم يتنوّعوا
    shot_prompts.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", None, "kama")
    for sc in tl["scenes"]:
        types = [s["type"] for s in sc["shots"]]
        assert all(a != b for a, b in zip(types, types[1:])), types


def test_character_reference_is_embedded_and_hand_shots_have_no_face(env, monkeypatch):
    st = approved_timeline(env, monkeypatch, with_char=True)
    tl = timeline.load("s1")
    ch = characters.get("ch_f_001")
    shot_prompts.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", ch, "kama")
    prompts = [(s["type"], s["prompt_ar"], s["refs"]) for sc in tl["scenes"] for s in sc["shots"]]
    assert all(r["character_id"] == "ch_f_001" for _t, _p, r in prompts)
    assert any("ريم" in p for t, p, _ in prompts if t != "hand_product")
    for t, p, _ in prompts:
        if t == "hand_product":
            assert "بدون وجه" in p


def test_validate_flags_empty_duplicate_and_missing_no_text_clause(env, monkeypatch):
    st = approved_timeline(env, monkeypatch)
    tl = timeline.load("s1")
    shot_prompts.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", None, "kama")
    a, b, c = tl["scenes"][0]["shots"][0], tl["scenes"][1]["shots"][0], tl["scenes"][2]["shots"][0]
    a["prompt_ar"] = ""
    b["prompt_ar"] = c["prompt_ar"]
    tl["scenes"][3]["shots"][0]["prompt_ar"] = "لقطة عادية بلا القاعدة"
    msgs = " | ".join(x["message"] for x in shot_prompts.validate(tl))
    assert "بلا برومبت" in msgs and "مطابق" in msgs and "بدون كتابة" in msgs


def test_set_prompt_appends_no_text_clears_translation_and_rejects_long(env, monkeypatch):
    st = approved_timeline(env, monkeypatch)
    tl = timeline.load("s1")
    shot_prompts.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", None, "kama")
    sh = tl["scenes"][0]["shots"][0]
    sh["prompt_model"] = "old english"
    out = shot_prompts.set_prompt(tl, sh["id"], "لقطة قريبة على العبوة")
    assert "بدون أي كتابة" in out["prompt_ar"] and out["prompt_model"] == "" and out["prompt_edited"]
    with pytest.raises(shot_prompts.ShotPromptError):
        shot_prompts.set_prompt(tl, sh["id"], "  ")
    with pytest.raises(shot_prompts.ShotPromptError):
        shot_prompts.set_prompt(tl, sh["id"], "س" * (shot_prompts.MAX_LEN + 1))
    with pytest.raises(shot_prompts.ShotPromptError):
        shot_prompts.set_prompt(tl, "s9c9", "x")


def test_refine_fills_model_prompt_and_falls_back_on_failure(env, monkeypatch):
    import llm
    st = approved_timeline(env, monkeypatch)
    tl = timeline.load("s1")
    shot_prompts.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", None, "kama")
    ids = [s["id"] for sc in tl["scenes"] for s in sc["shots"]]
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"shots": [
        {"id": i, "prompt_ar": f"محسّن {i}", "prompt_model": f"english {i}"} for i in ids]})
    shot_prompts.refine(tl, log=lambda *_: None)
    s0 = tl["scenes"][0]["shots"][0]
    assert s0["prompt_ar"].startswith("محسّن") and "بدون أي كتابة" in s0["prompt_ar"]
    assert s0["prompt_model"].startswith("english") and "No text" in s0["prompt_model"]

    before = json.dumps(tl, ensure_ascii=False)

    def boom(*a, **k):
        raise RuntimeError("no credit")

    monkeypatch.setattr(llm, "complete_json", boom)
    shot_prompts.refine(tl, log=lambda *_: None)
    assert json.dumps(tl, ensure_ascii=False) == before


def test_api_shot_prompts_flow_and_gates(env, monkeypatch):
    c = client()
    st = tv.produce_ok(env, monkeypatch)                     # صوت مولّد لكن غير معتمد
    assert c.post("/api/studio/s1.json/shots/build").status_code == 409
    voice_studio.approve_voice(st.script)
    r = c.post("/api/studio/s1.json/shots/build")
    assert r.status_code == 200 and r.json()["problems"] == []
    assert studio_state.state_of("s1", 6) == "awaiting_choice"
    sid = r.json()["timeline"]["scenes"][0]["shots"][0]["id"]
    e = c.put(f"/api/studio/s1.json/shots/{sid}/prompt", json={"prompt_ar": "  "})
    assert e.status_code == 409
    ok = c.put(f"/api/studio/s1.json/shots/{sid}/prompt", json={"prompt_ar": "لقطة معدّلة يدوياً"})
    assert ok.status_code == 200 and "بدون أي كتابة" in ok.json()["shot"]["prompt_ar"]
    ap = c.post("/api/studio/s1.json/shots/approve")
    assert ap.status_code == 200 and studio_state.state_of("s1", 6) == "approved"
    c.put(f"/api/studio/s1.json/shots/{sid}/prompt", json={"prompt_ar": "تعديل بعد الاعتماد"})
    assert studio_state.state_of("s1", 6) == "awaiting_choice"


def test_shots_build_needs_station_5_approved(env, monkeypatch):
    c = client()
    st = tv.produce_ok(env, monkeypatch)
    voice_studio.approve_voice(st.script)
    studio_state.set_state("s1", 5, "failed", "x")
    assert c.post("/api/studio/s1.json/shots/build").status_code == 409


def test_images_are_blocked_until_voice_is_approved(env, monkeypatch):
    import review_loop
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    ok, why = voice_studio.voice_is_approved(st.script)
    assert not ok
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import web.app as webapp
    monkeypatch.setattr(review_loop, "is_cleared", lambda p: (True, ""))
    r = TestClient(webapp.app).post("/api/images/s1.json")
    assert r.status_code == 409 and "فويس أوفر معتمد" in r.json()["detail"]
