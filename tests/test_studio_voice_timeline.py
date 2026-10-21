"""استوديو الإنتاج — المحطتان ٤ و٥: توقيت الكلمات، بوابة المدة، الخط الزمني، حالات المحطات."""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401

import config  # noqa: E402
import generate_voice  # noqa: E402
import review_loop  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import tts  # noqa: E402
import voice_studio  # noqa: E402


# ───────────────────────── تحويل توقيت الحروف لكلمات ─────────────────────────
def test_words_from_alignment_skips_tags_and_splits_on_space():
    text = "[warm] ab c"
    n = len(text)
    starts = [i * 0.1 for i in range(n)]
    ends = [i * 0.1 + 0.1 for i in range(n)]
    w = tts.words_from_alignment(list(text), starts, ends)
    assert [x["text"] for x in w] == ["ab", "c"]
    assert w[0]["start"] == 0.7 and w[1]["end"] == 1.1


def test_estimate_words_covers_duration_and_is_flagged_by_speak():
    w = tts.estimate_words("كلمة اطول كلمة", 6.0)
    assert len(w) == 3 and w[0]["start"] == 0 and abs(w[-1]["end"] - 6.0) < 0.01


def test_emotion_tag_maps_known_and_never_guesses():
    assert tts.emotion_tag("curiosity") == "curious"
    assert tts.emotion_tag("frustration / pain") == "empathetic"
    assert tts.emotion_tag("gibberish xyz") == ""


# ───────────────────────── بناء الخط الزمني ─────────────────────────
DURS = [6.0, 7.0, 7.0, 7.0, 7.0, 7.0, 6.0]        # 47ث


def fake_voice(durs=DURS, words_per_scene=14, estimated=False):
    scenes = []
    for n, d in enumerate(durs, 1):
        text = " ".join(f"w{n}_{i}،" if i % 5 == 4 else f"w{n}_{i}" for i in range(words_per_scene))
        ws = tts.estimate_words(text, d * 0.96)          # صمت قصير بالنهاية
        scenes.append({"scene": n, "duration_sec": d, "text": text, "words": ws,
                       "timing_source": "estimated" if estimated else "provider"})
    return {"provider": "elevenlabs", "model": "eleven_v3", "voice": "v1", "scenes": scenes,
            "total_actual_sec": sum(durs), "combined": {"path": "voice/x/full.mp3"}}


def build(durs=DURS, **kw):
    return timeline.build(make_script(), fake_voice(durs, **kw))


def test_build_valid_47s_timeline():
    tl = build()
    res = timeline.validate(tl)
    assert res["ok"], res["errors"]
    assert len(tl["scenes"]) == 7
    assert tl["voice"]["duration_ms"] == 47000


def test_shots_sum_equals_voice_duration_exactly_and_no_gaps():
    tl = build()
    total = sum(sh["end_ms"] - sh["start_ms"] for sc in tl["scenes"] for sh in sc["shots"])
    assert total == tl["voice"]["duration_ms"]
    prev = 0
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            assert sh["start_ms"] == prev
            prev = sh["end_ms"]
    assert prev == 47000


def test_every_shot_boundary_is_a_word_start_and_every_shot_has_words():
    tl = build()
    starts = {w["start_ms"] for w in tl["words"]}
    for sc in tl["scenes"]:
        assert 1 <= len(sc["shots"]) <= 3
        for k, sh in enumerate(sc["shots"]):
            assert sh["word_range"][1] >= sh["word_range"][0]
            if k:
                assert sh["start_ms"] in starts


def test_shot_count_follows_duration_and_cap():
    tl = build()
    for sc, d in zip(tl["scenes"], DURS):          # ceil(مدة ÷ ٣ث): ٦ث = ٢ ، ٧ث = ٣
        assert len(sc["shots"]) == (2 if d == 6.0 else 3)
    tl2 = timeline.build(make_script(), fake_voice([2.0] + DURS[1:]))
    assert len(tl2["scenes"][0]["shots"]) == 1     # مشهد قصير = لقطة


def test_shot_max_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "STUDIO_MAX_SHOT_SEC", 6.0)
    tl = build()
    assert all(len(sc["shots"]) == 2 for sc in tl["scenes"][1:6])   # ceil(٧ ÷ ٦) = ٢
    assert len(tl["scenes"][0]["shots"]) == 1                        # ٦ ÷ ٦ = ١


def test_scene_without_word_timing_is_an_error_not_an_orphan_shot():
    v = fake_voice()
    v["scenes"][2]["words"] = []
    with pytest.raises(timeline.TimelineError):
        timeline.build(make_script(), v)


def test_voice_outside_45_50_fails_validation():
    tl = timeline.build(make_script(), fake_voice([5.0] * 7))          # ٣٥ث
    res = timeline.validate(tl)
    assert not res["ok"] and any(e["code"] == "voice_duration" for e in res["errors"])


def test_validation_catches_gap_and_orphan_and_bad_motion_duration():
    tl = build()
    tl["scenes"][1]["shots"][1]["start_ms"] += 50
    assert any(e["code"] in ("shot_gap", "shot_boundary") for e in timeline.validate(tl)["errors"])
    tl = build()
    tl["scenes"][0]["shots"][0]["motion"] = {"model_id": "m", "duration_ms": 1234}
    assert any(e["code"] == "motion_duration" for e in timeline.validate(tl)["errors"])
    tl = build()
    sh = tl["scenes"][0]["shots"][0]
    sh["word_range"] = [sh["word_range"][0], sh["word_range"][0] - 1]
    assert any(e["code"] == "shot_no_words" for e in timeline.validate(tl)["errors"])


def test_save_refuses_invalid_and_roundtrips_valid(env):
    tl = build()
    timeline.save("s1", tl)
    assert timeline.load("s1")["voice"]["duration_ms"] == 47000
    bad = build()
    bad["scenes"][0]["end_ms"] += 10
    with pytest.raises(timeline.TimelineError):
        timeline.save("s2", bad)
    assert timeline.load("s2") is None


def test_move_boundary_snaps_to_word_start_keeps_a_word_per_shot():
    tl = build()
    sc = tl["scenes"][1]
    mid = (sc["shots"][0]["end_ms"] + sc["shots"][1]["end_ms"]) // 2
    timeline.move_boundary(tl, 2, 1, mid + 137)
    starts = {w["start_ms"] for w in tl["words"]}
    assert sc["shots"][0]["end_ms"] in starts
    assert sc["shots"][0]["end_ms"] == sc["shots"][1]["start_ms"]
    assert timeline.validate(tl)["ok"]
    timeline.move_boundary(tl, 2, 1, 0)             # أقصى اليسار: ما بيفرّغ اللقطة
    assert sc["shots"][0]["word_range"][1] >= sc["shots"][0]["word_range"][0]
    assert timeline.validate(tl)["ok"]


def test_move_boundary_clears_motion_because_its_duration_changed():
    tl = build()
    sh = tl["scenes"][1]["shots"]
    sh[0]["motion"] = {"model_id": "m", "duration_ms": sh[0]["end_ms"] - sh[0]["start_ms"]}
    timeline.move_boundary(tl, 2, 1, sh[0]["end_ms"] + 400)
    assert sh[0]["motion"] is None


# ───────────────────────── حالات المحطات ─────────────────────────
def test_no_station_runs_before_previous_is_approved(env):
    with pytest.raises(studio_state.StationBlocked):
        studio_state.set_state("s", 7, "running")          # صور قبل صوت
    studio_state.set_state("s", 1, "approved")
    studio_state.set_state("s", 2, "running")


def test_going_back_marks_downstream_stale_without_deleting(env):
    for n in range(1, 6):
        studio_state.set_state("s", n, "approved")
    studio_state.set_state("s", 4, "running", "إعادة")
    st = {r["n"]: r["state"] for r in studio_state.summary("s")}
    assert st[4] == "running" and st[5] == "stale" and st[6] == "not_started"
    assert st[1] == st[2] == st[3] == "approved"
    assert any(e["to"] == "stale" for e in studio_state.load("s")["events"])


# ───────────────────────── بوابة المدة والإنتاج ─────────────────────────
def test_check_duration_direction_and_message():
    assert voice_studio.check_duration(47)["ok"]
    assert voice_studio.check_duration(45)["ok"] and voice_studio.check_duration(50)["ok"]
    long = voice_studio.check_duration(53.2)
    assert not long["ok"] and long["direction"] == "long" and long["delta_sec"] == 3.2
    short = voice_studio.check_duration(41)
    assert short["direction"] == "short" and "أقصر" in short["message"]


class Studio:
    """بيئة إنتاج صوت بمزوّد مزيّف — بلا شبكة."""

    def __init__(self, env, monkeypatch, durs):
        self.env, self.mp = env, monkeypatch
        self.durs = list(durs)          # مدد المشاهد بكل جولة توليد (قائمة من قوائم)
        self.round = 0
        self.speak_calls = 0
        self.script = env.script_file("s1.json", make_script())
        env.product()
        env.pattern("p1")
        monkeypatch.setattr(review_loop, "is_cleared", lambda p: (True, ""))
        monkeypatch.setattr(tts, "tts_config", lambda o=None: {
            "provider": "elevenlabs", "model": "eleven_v3", "voice": "v1", "tone": ""})
        monkeypatch.setattr(tts, "performance_note", lambda c: "")

        def speak(text, out, ov=None, want_timing=False):
            self.speak_calls += 1
            n = int(out.stem.split("_")[1])
            d = self.durs[min(self.round, len(self.durs) - 1)][n - 1]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x" * 600)
            return {"path": str(out), "duration_sec": d, "provider": "elevenlabs",
                    "model": "eleven_v3", "voice": "v1",
                    "words": tts.estimate_words(text, d * 0.97), "timing_source": "provider"}

        monkeypatch.setattr(tts, "speak", speak)

        def concat(files, out):
            out.write_bytes(b"y" * 600)
            return True

        monkeypatch.setattr(generate_voice, "concat", concat)
        monkeypatch.setattr(tts, "audio_duration",
                            lambda p: sum(self.durs[min(self.round, len(self.durs) - 1)]))


IN_RANGE = [6.0, 7.0, 7.0, 7.0, 7.0, 7.0, 6.0]        # 47
TOO_LONG = [8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 7.0]         # 55


def test_produce_in_range_awaits_owner_and_writes_relative_paths(env, monkeypatch):
    st = Studio(env, monkeypatch, [IN_RANGE])
    r = voice_studio.produce(st.script, log=lambda *_: None)
    assert r["status"] == "awaiting_owner_approval" and r["gate"]["ok"]
    m = voice_studio.load_manifest("s1")
    assert m["total_actual_sec"] == 47 and all("words" in s for s in m["scenes"])
    blob = json.dumps(m)
    assert ":\\" not in blob and ":/" not in blob                 # ما في مسار ويندوز مطلق
    assert studio_state.state_of("s1", 4) == "awaiting_choice"
    assert studio_state.state_of("s1", 3) == "approved"           # راوٍ بلا شخصية (المكتبة فاضية)


def test_produce_out_of_range_rewrites_text_reviews_then_regenerates(env, monkeypatch):
    st = Studio(env, monkeypatch, [TOO_LONG, IN_RANGE])
    rewrites, reviews = [], []

    def fake_rewrite(path, review):
        rewrites.append(review["findings"][0])
        st.round = 1                          # الصوت الجديد بنطلع بمدة مقبولة
        return path

    import stage3_generate
    monkeypatch.setattr(stage3_generate, "rewrite_from_review", fake_rewrite)
    monkeypatch.setattr(review_loop, "run", lambda p: reviews.append(1) or {"approved": True})

    r = voice_studio.produce(st.script, log=lambda *_: None)
    assert r["status"] == "awaiting_owner_approval" and r["rounds"] == 1
    assert len(rewrites) == 1 and "قصّر" in rewrites[0]["fix"] and "55" in rewrites[0]["issue"]
    assert len(reviews) == 1                                       # تعديل النص رجع لحلقة المراجعة


def test_produce_gives_up_after_max_rounds_and_escalates(env, monkeypatch):
    st = Studio(env, monkeypatch, [TOO_LONG])
    import stage3_generate
    monkeypatch.setattr(stage3_generate, "rewrite_from_review", lambda p, r: p)
    monkeypatch.setattr(review_loop, "run", lambda p: {"approved": True})
    r = voice_studio.produce(st.script, log=lambda *_: None)
    assert r["status"] == "needs_owner" and r["rounds"] == config.STUDIO_VOICE_MAX_ROUNDS
    assert studio_state.state_of("s1", 4) == "failed"


def test_produce_stops_if_rewritten_script_fails_review(env, monkeypatch):
    st = Studio(env, monkeypatch, [TOO_LONG])
    import stage3_generate
    monkeypatch.setattr(stage3_generate, "rewrite_from_review", lambda p, r: p)
    monkeypatch.setattr(review_loop, "run", lambda p: {"approved": False, "reason": "blocker"})
    r = voice_studio.produce(st.script, log=lambda *_: None)
    assert r["status"] == "needs_owner" and "blocker" in r["reason"]
    assert st.speak_calls == 7                                     # ما ولّد صوت لنص ما اعتُمد


def test_produce_refuses_uncleared_script(env, monkeypatch):
    st = Studio(env, monkeypatch, [IN_RANGE])
    monkeypatch.setattr(review_loop, "is_cleared", lambda p: (False, "عوائق 1"))
    with pytest.raises(voice_studio.VoiceGateError):
        voice_studio.produce(st.script, log=lambda *_: None)
    assert st.speak_calls == 0


# ───────────────────────── الاعتماد ─────────────────────────
def produce_ok(env, monkeypatch, durs=IN_RANGE):
    st = Studio(env, monkeypatch, [durs])
    voice_studio.produce(st.script, log=lambda *_: None)
    return st


def test_approve_builds_valid_timeline_and_marks_stations(env, monkeypatch):
    st = produce_ok(env, monkeypatch)
    r = voice_studio.approve_voice(st.script)
    assert r["approved"] and r["timeline_ok"], r["errors"]
    assert studio_state.state_of("s1", 4) == "approved"
    assert studio_state.state_of("s1", 5) == "approved"
    tl = timeline.load("s1")
    assert tl["voice"]["duration_ms"] == 47000 and tl["voice"]["sha256"]
    assert voice_studio.voice_is_approved(st.script) == (True, "")


def test_approve_blocked_when_duration_out_of_range(env, monkeypatch):
    st = Studio(env, monkeypatch, [TOO_LONG])
    import stage3_generate
    monkeypatch.setattr(stage3_generate, "rewrite_from_review", lambda p, r: p)
    monkeypatch.setattr(review_loop, "run", lambda p: {"approved": True})
    voice_studio.produce(st.script, log=lambda *_: None)
    with pytest.raises(voice_studio.VoiceGateError):
        voice_studio.approve_voice(st.script)
    assert timeline.load("s1") is None


def test_editing_script_after_approval_invalidates_the_voice(env, monkeypatch):
    st = produce_ok(env, monkeypatch)
    voice_studio.approve_voice(st.script)
    d = json.loads(st.script.read_text(encoding="utf-8"))
    d["scenes"][0]["voiceover"] += " كلمة زيادة"
    st.script.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    ok, why = voice_studio.voice_is_approved(st.script)
    assert not ok and "انعدّل" in why
    with pytest.raises(voice_studio.VoiceGateError):
        voice_studio.approve_voice(st.script)            # الصوت لنص قديم


def test_regenerating_voice_after_approval_makes_timeline_stale(env, monkeypatch):
    st = produce_ok(env, monkeypatch)
    voice_studio.approve_voice(st.script)
    voice_studio.produce(st.script, log=lambda *_: None)          # إعادة توليد
    assert studio_state.state_of("s1", 5) == "stale"


# ───────────────────────── API ─────────────────────────
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_studio
    app = FastAPI()
    app.include_router(routes_studio.router)
    return TestClient(app)


def test_api_flow_state_voice_approve_timeline_and_move(env, monkeypatch):
    st = produce_ok(env, monkeypatch)
    c = client()
    assert c.get("/api/studio/s1.json/state").status_code == 200
    v = c.get("/api/studio/s1.json/voice").json()
    assert v["gate"]["ok"] and not v["approved"]
    assert c.get("/api/studio/s1.json/timeline").status_code == 404
    assert c.post("/api/studio/s1.json/voice/approve").status_code == 200
    body = c.get("/api/studio/s1.json/timeline").json()
    assert body["validation"]["ok"]
    sc = body["timeline"]["scenes"][1]
    r = c.put("/api/studio/s1.json/timeline/boundary",
              params={"scene": 2, "shot": 1, "to_ms": sc["shots"][0]["end_ms"] + 300})
    assert r.status_code == 200 and r.json()["validation"]["ok"]


def test_api_voice_job_refuses_uncleared_script(env, monkeypatch):
    st = Studio(env, monkeypatch, [IN_RANGE])
    monkeypatch.setattr(review_loop, "is_cleared", lambda p: (False, "مراجعة قديمة"))
    r = client().post("/api/studio/s1.json/voice")
    assert r.status_code == 409 and "مراجعة قديمة" in r.json()["detail"]
    assert env.jobs == []


def test_api_approve_rejects_with_arabic_reason(env, monkeypatch):
    Studio(env, monkeypatch, [IN_RANGE])
    r = client().post("/api/studio/s1.json/voice/approve")
    assert r.status_code == 409 and "صوت" in r.json()["detail"]
