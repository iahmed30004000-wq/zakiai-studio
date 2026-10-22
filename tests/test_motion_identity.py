"""التحريك وثبات الشخصية: بطاقة الهوية ببرومبت الحركة، صورة النهاية، البرومبت السلبي، مراجع الشخصية، فحص وجه الفيديو والتعلّم."""

import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage  # noqa: E402,F401
from test_studio_motion import lavfi, model, ready, tc_client  # noqa: E402,F401
from test_motion_api import fal, KEY, spec  # noqa: E402,F401
from test_motion_http import box, http_model  # noqa: E402,F401

import characters  # noqa: E402
import config  # noqa: E402
import identity  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import motion_api  # noqa: E402
import production_log  # noqa: E402
import timeline  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")

CARD_START = "a 32-year-old Syrian (Levantine Arab) woman"


def arabic(t):
    return any(0x600 <= ord(c) <= 0x6FF for c in t)


def shots_of(tl):
    return [s for sc in tl["scenes"] for s in sc["shots"]]


def pick(ready, face=True):
    tl = timeline.load("s1")
    return next(s for s in shots_of(tl) if (s["type"] != "hand_product") == face)


def api_model(name="Kling (fal)", cost=0.07, **kw):
    s = spec(durations=[5, 10], cost_per_sec=cost, end_image_field="end_image_url",
             input={"prompt": "{prompt}", "start_image_url": "{image}", "duration": "{duration_str}", "generate_audio": False,
                    "negative_prompt": "blur, distort"})
    d = {"name": name, "kind": "api", "api": s, "strengths": ["product", "realism", "faces"]}
    d.update(kw)
    return d


def passing(refs, video):
    passing.calls.append(([p.name for p in refs], video.name))
    return {"status": "pass", "similarity": 0.61, "threshold": 0.363, "frames": [], "note": "الوجه مطابق"}


passing.calls = []


def failing(refs, video):
    return {"status": "fail", "similarity": 0.12, "threshold": 0.363, "frames": [], "note": "الوجه تغيّر عن الشخصية"}


# ───────────────────────── البرومبت ─────────────────────────
def test_the_english_motion_prompt_carries_the_identity_card_for_face_shots_only(env):
    ch = characters.create({"name_ar": "ريم", "gender": "f", "age": 32, "market_look": {"SY": "x"}})
    face = {"type": "medium", "motion_desc": ""}
    hand = {"type": "hand_product", "motion_desc": ""}
    p = motion.build_prompt_en(face, ch, 3000, "SY")
    assert CARD_START in p and "Identical face, hair and clothing; the face must not change." in p and not arabic(p)
    assert "Subject" not in p and p.startswith("Animate the reference image for 3.0 seconds.")
    assert CARD_START not in motion.build_prompt_en(hand, ch, 3000, "SY")
    assert "Keep the same person" not in motion.build_prompt_en(face, None, 3000, "SY")
    assert "Saudi (Gulf Arab)" in motion.build_prompt_en(face, {**ch, "market_look": {"SA": "x", "SY": "y"}}, 3000, "SA")


@pytest.mark.parametrize("desc,moves", [
    ("حركة طبيعية خفيفة للشخصية (تنفّس، تحريك رأس بسيط) والكاميرا شبه ثابتة", False),
    ("تقريب بطيء على الوجه", True), ("دفع للكاميرا للأمام", True), ("slow zoom in on her face", True), ("camera pans left", True),
    ("بانوراما أفقية", True), ("She smiles and tilts her head", False), ("تبتسم وتحرّك يدها", False), ("", False),
])
def test_camera_moves_are_told_apart_from_a_mere_mention_of_the_camera(desc, moves):
    assert bool(motion._CAMERA_MOVE_RX.search(desc)) is moves


# ───────────────────────── مدخلات الهوية ─────────────────────────
def test_face_shots_get_negatives_the_end_frame_and_the_character_sheets(ready, monkeypatch):
    ch = characters.get(ready.ch["id"])
    sh = {**pick(ready), "motion_desc": "حركة بسيطة"}
    img = ims.abs_of("s1", sh["image"]["chosen"])
    got = motion._identity_inputs(sh, ch, img, True)
    assert got["negative"] == identity.NEGATIVE and got["end_image"] == img
    assert sorted(got["refs"]) == ["front", "side", "three_quarter"] and all(p.exists() for p in got["refs"].values())
    assert motion._identity_inputs({**sh, "motion_desc": "تقريب بطيء"}, ch, img, True)["end_image"] is None       # حركة كاميرا
    monkeypatch.setattr(config, "MOTION_END_FRAME", False)
    assert motion._identity_inputs(sh, ch, img, True)["end_image"] is None and motion._identity_inputs(sh, ch, img, True)["negative"]
    assert motion._identity_inputs(sh, ch, img, False) == {"negative": "", "end_image": None, "refs": None}
    assert motion._identity_inputs(sh, None, img, True) == {"negative": "", "end_image": None, "refs": None}


# ───────────────────────── التشغيل الفعلي ─────────────────────────
def run(ready, sid, face=passing, **kw):
    return motion.run_shot(ready.script, sid, log=lambda *_: None, face_check=face, **kw)


def body_of(fal):
    return next(b for m, p, a, b in fal.requests if m == "POST")


def test_an_api_face_shot_sends_the_identity_prompt_end_frame_and_negatives(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    m = motion.upsert_model(api_model())
    sh = pick(ready)
    passing.calls.clear()
    run(ready, sh["id"])
    body = body_of(fal)
    assert CARD_START in body["prompt"] and not arabic(body["prompt"]) and body["end_image_url"].startswith("data:image/jpeg;base64,")
    assert body["negative_prompt"].startswith("blur, distort") and "East Asian facial features" in body["negative_prompt"]
    cand = ims._shot(timeline.load("s1"), sh["id"])[1]["motion_candidates"][0]
    assert cand["model_id"] == m["id"] and cand["face"]["status"] == "pass" and cand["face"]["similarity"] == 0.61 and cand["face"]["at"]
    assert passing.calls == [(["front.png", "three_quarter.png"], cand["clip"].split("/")[-1])]
    row = production_log.recent(5, "face_video")[0]
    assert row["status"] == "ok" and row["model_id"] == m["id"] and row["score"] == 0.61 and row["path"] == "api" and row["shot_id"] == sh["id"]


def test_a_hand_shot_has_no_identity_extras_and_no_face_check(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    motion.upsert_model(api_model())
    hand = pick(ready, face=False)
    passing.calls.clear()
    run(ready, hand["id"])
    body = body_of(fal)
    assert "end_image_url" not in body and body["negative_prompt"] == "blur, distort" and CARD_START not in body["prompt"]
    assert "face" not in ims._shot(timeline.load("s1"), hand["id"])[1]["motion_candidates"][0] and passing.calls == []
    assert production_log.recent(5, "face_video") == []


def test_a_camera_move_skips_the_end_frame_but_keeps_the_negatives(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    motion.upsert_model(api_model())
    sh = pick(ready)
    motion.set_desc(ready.script, sh["id"], "تقريب بطيء على وجهها")
    run(ready, sh["id"])
    body = body_of(fal)
    assert "end_image_url" not in body and "East Asian facial features" in body["negative_prompt"]


def test_a_changed_face_is_flagged_on_the_candidate_and_logged_as_a_failure(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    m = motion.upsert_model(api_model())
    sh = pick(ready)
    lines = []
    motion.run_shot(ready.script, sh["id"], log=lines.append, face_check=failing)
    cand = ims._shot(timeline.load("s1"), sh["id"])[1]["motion_candidates"][0]
    assert cand["face"]["status"] == "fail" and any("الوجه تغيّر بفيديو" in x for x in lines)
    assert production_log.recent(5, "face_video")[0]["status"] == "failed"
    assert production_log.face_rates("face_video")[m["id"]] == {"name": "Kling (fal)", "checks": 1, "passed": 0, "rate": 0.0, "avg_score": 0.12}
    assert motion.choose(ready.script, sh["id"], cand["clip"])["motion"]["clip"] == cand["clip"]            # التحذير مش منع: المالك بيقرر


def test_inconclusive_checks_are_stored_but_never_logged(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    motion.upsert_model(api_model())
    sh = pick(ready)
    run(ready, sh["id"], face=lambda refs, video: {"status": "no_face", "similarity": None, "frames": [], "note": "x"})
    assert ims._shot(timeline.load("s1"), sh["id"])[1]["motion_candidates"][0]["face"]["status"] == "no_face"
    assert production_log.recent(5, "face_video") == []


def test_a_broken_face_check_never_stops_the_production(ready, fal, monkeypatch):
    import facecheck
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    motion.upsert_model(api_model())
    a, b = [s["id"] for s in shots_of(timeline.load("s1")) if s["type"] != "hand_product"][:2]

    def missing(refs, video):
        raise facecheck.FaceCheckError("نماذج فحص الوجه غير منزّلة")

    def weird(refs, video):
        raise RuntimeError("secret internal detail")

    run(ready, a, face=missing)
    run(ready, b, face=weird)
    fa = ims._shot(timeline.load("s1"), a)[1]["motion_candidates"][0]["face"]
    fb = ims._shot(timeline.load("s1"), b)[1]["motion_candidates"][0]["face"]
    assert fa["status"] == "unchecked" and "غير منزّلة" in fa["note"]
    assert fb["status"] == "unchecked" and "RuntimeError" in fb["note"] and "secret" not in fb["note"]
    assert production_log.recent(5, "face_video") == []


def test_http_boxes_get_the_english_prompt_and_identity_negatives_for_face_shots(ready, box, monkeypatch):
    monkeypatch.setattr(motion, "HTTP_POLL_SEC", 0.05)
    motion.upsert_model(http_model(box(), "LTX", strengths=("faces", "realism", "product", "hand")))
    seen = []
    real = motion._engine_call

    def spy(sess, method, base, path, **kw):
        if method == "POST" and path == "/jobs":
            seen.append(json.loads(kw["data"]["params"]))
        return real(sess, method, base, path, **kw)

    monkeypatch.setattr(motion, "_engine_call", spy)
    face, hand = pick(ready), pick(ready, face=False)
    run(ready, face["id"])
    run(ready, hand["id"])
    f, h = seen
    assert CARD_START in f["prompt"] and not arabic(f["prompt"])
    assert f["negative_prompt"].startswith(motion.HTTP_NEGATIVE) and "East Asian facial features" in f["negative_prompt"]
    assert "negative_prompt" not in h and not arabic(h["prompt"])                                   # اليد: سلبي الباكند الافتراضي


# ───────────────────────── التعلّم والترتيب ─────────────────────────
def log_faces(model_id, passed, failed):
    for _ in range(passed):
        production_log.record("face_video", "ok", model_id=model_id, model_name=model_id, score=0.6)
    for _ in range(failed):
        production_log.record("face_video", "failed", model_id=model_id, model_name=model_id, score=0.1)


def test_the_ranking_prefers_the_model_that_keeps_the_face(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    a = motion.upsert_model(api_model("وفيّ للوجه", cost=0.07))
    b = motion.upsert_model(api_model("ببدّل الوجه", cost=0.04))                                        # أرخص بشوي
    shot = {"type": "medium", "start_ms": 0, "end_ms": 3000, "refs": {"character_id": "ch_f_001"}}
    assert [r["model"]["id"] for r in motion.rank_models(shot, vram_gb=6)["ranked"]] == [b["id"], a["id"]]
    log_faces(a["id"], 4, 0)
    log_faces(b["id"], 0, 4)
    r = motion.rank_models(shot, vram_gb=6)["ranked"]
    assert [x["model"]["id"] for x in r] == [a["id"], b["id"]]
    assert r[0]["face_bonus"] == 5.0 and r[1]["face_bonus"] == -5.0
    assert r[0]["face_rate"]["rate"] == 1.0 and r[1]["face_rate"]["checks"] == 4


def test_a_few_checks_are_not_enough_to_move_the_ranking(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    a = motion.upsert_model(api_model("أ", cost=0.07))
    b = motion.upsert_model(api_model("ب", cost=0.04))
    log_faces(a["id"], motion.FACE_MIN_CHECKS - 1, 0)
    shot = {"type": "medium", "start_ms": 0, "end_ms": 3000, "refs": {"character_id": "ch_f_001"}}
    r = motion.rank_models(shot, vram_gb=6)["ranked"]
    assert r[0]["model"]["id"] == b["id"] and all(x["face_bonus"] == 0 for x in r)
    assert next(x for x in r if x["model"]["id"] == a["id"])["face_rate"]["checks"] == motion.FACE_MIN_CHECKS - 1


def test_shots_without_a_face_ignore_the_face_record(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    a = motion.upsert_model(api_model("أ", cost=0.07))
    b = motion.upsert_model(api_model("ب", cost=0.04))
    log_faces(a["id"], 5, 0)
    log_faces(b["id"], 0, 5)
    base = {"start_ms": 0, "end_ms": 3000}
    for shot in ({**base, "type": "hand_product", "refs": {"character_id": "ch_f_001"}}, {**base, "type": "close"},
                 {**base, "type": "medium"}):                                          # يد، بلا شخصية، بلا شخصية
        assert all(x["face_bonus"] == 0 and x["face_rate"] is None for x in motion.rank_models(shot, vram_gb=6)["ranked"])


def test_the_info_route_exposes_the_face_rate_and_the_candidates_face_result(ready, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    m = motion.upsert_model(api_model("Kling"))
    log_faces(m["id"], 3, 1)
    d = tc_client().get("/api/studio/s1.json/motion/info").json()
    face = next(s for s in d["shots"] if s["type"] != "hand_product")
    assert face["ranked"][0]["face_rate"]["checks"] == 4 and face["ranked"][0]["face_rate"]["rate"] == 0.75
    hand = next(s for s in d["shots"] if s["type"] == "hand_product")
    assert hand["ranked"][0]["face_rate"] is None


def test_the_chosen_character_remembers_the_briefs_country(ready):
    assert characters.chosen("s1")["country"] == "SY"
