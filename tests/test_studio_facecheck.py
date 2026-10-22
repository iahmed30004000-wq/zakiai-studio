"""محطة فحص التطابق (٨) + فحص الوجه المحلي: نتيجة كل لقطة، التسجيل لنموذج الصور، منع الاعتماد، والفحص الجماعي."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage, gen_and_choose, first_shot  # noqa: E402,F401
import test_studio_characters_shots as tc  # noqa: E402

import facecheck  # noqa: E402
import image_studio as ims  # noqa: E402
import production_log  # noqa: E402
import timeline  # noqa: E402


def face_returning(status, sim=None, **kw):
    def f(refs, img):
        f.calls.append((list(refs), img))
        return {"status": status, "similarity": sim, "threshold": 0.363, "faces": 1 if sim is not None else 0, "note": "نتيجة تجريبية", **kw}

    f.calls = []
    return f


def chosen(stage, typ="medium"):
    sid, cand = gen_and_choose(stage, typ)
    ims.choose(stage.script, sid, cand)
    return sid


def choose_all(stage):
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    for sid in ids:
        ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
        ims.choose(stage.script, sid, ims._shot(timeline.load("s1"), sid)[1]["image"]["candidates"][-1]["path"])
    return ids


NO_OCR = lambda p: ""  # noqa: E731


def test_a_passing_face_is_stored_and_logged_for_the_image_model(stage):
    sid = chosen(stage)
    f = face_returning("pass", 0.71)
    fc = ims.check_shot(stage.script, sid, ocr=NO_OCR, face=f)["face_check"]
    sh = ims._shot(timeline.load("s1"), sid)[1]
    assert fc["status"] == "pass" and fc["similarity"] == 0.71 and fc["image"] == sh["image"]["chosen"] and fc["logged"] == fc["image"]
    refs, img = f.calls[0]
    assert [r.stem for r in refs] == ["front", "three_quarter"] and img.name.endswith("_1080.png")
    rows = production_log.recent(10, "face_image")
    assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["score"] == 0.71 and rows[0]["shot_id"] == sid
    assert rows[0]["model_id"] == "img-1" and rows[0]["model_name"] == "fake" and rows[0]["path"] == "api" and rows[0]["script_stem"] == "s1"


def test_an_ai_upscaled_candidate_is_logged_for_the_model_that_made_the_original(stage):
    sid = chosen(stage)
    tl = timeline.load("s1")
    im = ims._shot(tl, sid)[1]["image"]
    orig = im["source"]
    im["candidates"].append({"path": orig.replace(".png", "_ai.png"), "provider": "local", "model": "Real-ESRGAN", "at": "x", "w": 1080, "h": 1920,
                             "refs_used": [], "path_used": "upscale", "from": orig})
    im["source"] = im["candidates"][-1]["path"]
    timeline.save("s1", tl)
    ims.check_shot(stage.script, sid, ocr=NO_OCR, face=face_returning("pass", 0.5))
    row = production_log.recent(1, "face_image")[0]
    assert row["model_id"] == "img-1" and row["model_name"] == "fake" and row["path"] == "api"


def test_extension_images_are_logged_under_the_extension_path(stage):
    sid = chosen(stage)
    tl = timeline.load("s1")
    c = ims._shot(tl, sid)[1]["image"]["candidates"][0]
    c.update(provider="extension:chatgpt", model="gpt-image", path_used="extension")
    timeline.save("s1", tl)
    ims.check_shot(stage.script, sid, ocr=NO_OCR, face=face_returning("fail", 0.1))
    row = production_log.recent(1, "face_image")[0]
    assert row["path"] == "extension" and row["model_id"] == "gpt-image" and row["status"] == "failed"


def test_rechecking_the_same_image_is_not_logged_twice_but_a_new_image_is(stage):
    sid = chosen(stage)
    f = face_returning("pass", 0.5)
    ims.check_shot(stage.script, sid, ocr=NO_OCR, face=f)
    ims.check_shot(stage.script, sid, ocr=NO_OCR, face=f)
    assert len(production_log.recent(10, "face_image")) == 1
    ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
    ims.choose(stage.script, sid, ims._shot(timeline.load("s1"), sid)[1]["image"]["candidates"][-1]["path"])
    assert ims._shot(timeline.load("s1"), sid)[1]["face_check"] is None           # الاختيار الجديد بيمسح الفحص القديم
    ims.check_shot(stage.script, sid, ocr=NO_OCR, face=f)
    assert len(production_log.recent(10, "face_image")) == 2


def test_a_changed_face_blocks_approval_until_the_owner_decides(stage):
    sid = chosen(stage)
    fc = ims.check_shot(stage.script, sid, ocr=NO_OCR, face=face_returning("fail", 0.12))["face_check"]
    assert fc["status"] == "fail"
    msg = [p["message"] for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid]
    assert len(msg) == 1 and "الوجه تغيّر" in msg[0] and "اعتمد صراحة" in msg[0]
    ims.set_verdict(stage.script, sid, "override", "الوجه قريب كفاية للإعلان")
    assert not [p for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid]
    row = production_log.recent(10, "face_image")[0]
    assert row["status"] == "failed" and row["score"] == 0.12
    ims.set_verdict(stage.script, sid, "pass")
    assert not [p for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid]


def test_the_owner_verdict_fail_still_wins_over_a_passing_face(stage):
    sid = chosen(stage)
    ims.check_shot(stage.script, sid, ocr=NO_OCR, face=face_returning("pass", 0.8))
    ims.set_verdict(stage.script, sid, "fail", "التعبير مش مناسب")
    assert "ساقطة بحكم المالك" in [p["message"] for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid][0]


@pytest.mark.parametrize("status", ["no_face", "no_ref"])
def test_undecided_results_are_not_logged_and_do_not_add_a_blocker(stage, status):
    sid = chosen(stage)
    fc = ims.check_shot(stage.script, sid, ocr=NO_OCR, face=face_returning(status))["face_check"]
    assert fc["status"] == status and "logged" not in fc
    assert production_log.recent(10, "face_image") == []
    assert "بانتظار حكمك" in [p["message"] for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid][0]


def test_technical_problems_become_unchecked_with_the_reason(stage):
    sid = chosen(stage)

    def missing(refs, img):
        raise facecheck.FaceCheckError("نماذج فحص الوجه (YuNet + SFace) غير منزّلة بمجلد models/face/")

    def weird(refs, img):
        raise RuntimeError("boom")

    a = ims.check_shot(stage.script, sid, ocr=NO_OCR, face=missing)["face_check"]
    assert a["status"] == "unchecked" and a["similarity"] is None and "غير منزّلة" in a["note"]
    b = ims.check_shot(stage.script, sid, ocr=NO_OCR, face=weird)["face_check"]
    assert b["status"] == "unchecked" and "RuntimeError" in b["note"] and "boom" not in b["note"]
    assert production_log.recent(10, "face_image") == []


def test_hand_shots_and_shots_without_a_character_are_not_face_checked(stage):
    hid, hcand = gen_and_choose(stage, "hand_product")
    ims.choose(stage.script, hid, hcand)
    f = face_returning("pass", 0.9)
    assert ims.check_shot(stage.script, hid, ocr=NO_OCR, face=f)["face_check"] is None and f.calls == []
    sid = chosen(stage)
    tl = timeline.load("s1")
    ims._shot(tl, sid)[1]["refs"]["character_id"] = None
    timeline.save("s1", tl)
    assert ims.check_shot(stage.script, sid, ocr=NO_OCR, face=f)["face_check"] is None and f.calls == []


def test_the_label_check_still_works_next_to_the_face_check(stage):
    import product_ref
    product_ref.set_details("testp", label_text="ماء الكمأة قطرة عينية")
    sid = chosen(stage, "close")
    sh = ims.check_shot(stage.script, sid, ocr=lambda p: "ماء الكمأة قطرة عينية", face=face_returning("pass", 0.6))
    assert sh["product_check"]["status"] == "pass" and sh["face_check"]["status"] == "pass"


# ───────────────────────── الفحص الجماعي ─────────────────────────
def test_check_all_checks_every_shot_once_and_only_the_changed_ones_afterwards(stage):
    import product_ref
    product_ref.set_details("testp", label_text="ماء الكمأة قطرة عينية")
    ids = choose_all(stage)
    f = face_returning("pass", 0.55)
    ocr_calls = []
    r = ims.check_all(stage.script, ocr=lambda p: ocr_calls.append(p) or "", face=f)
    assert r["checked"] == ids and r["failed"] == []
    tl = timeline.load("s1")
    face_shots = [s["id"] for sc in tl["scenes"] for s in sc["shots"] if s["type"] != "hand_product"]
    assert len(f.calls) == len(face_shots) and len(ocr_calls) == len(ids)
    assert all(ims._shot(tl, i)[1]["product_check"] is not None for i in ids)
    again = ims.check_all(stage.script, ocr=NO_OCR, face=f)
    assert again == {"checked": [], "failed": []} and len(f.calls) == len(face_shots)
    one = face_shots[0]
    ims.generate_shot(stage.script, one, n=1, log=lambda *_: None)
    ims.choose(stage.script, one, ims._shot(timeline.load("s1"), one)[1]["image"]["candidates"][-1]["path"])
    assert ims.check_all(stage.script, ocr=NO_OCR, face=f)["checked"] == [one]


def test_check_all_reruns_only_the_missing_part(stage):
    import product_ref
    product_ref.set_details("testp", label_text="ماء الكمأة قطرة عينية")
    sid = chosen(stage)
    ocr_calls = []
    ims.check_shot(stage.script, sid, ocr=lambda p: ocr_calls.append(1) or "", face=face_returning("pass", 0.5), faces=False)
    assert ims._shot(timeline.load("s1"), sid)[1]["face_check"] is None and len(ocr_calls) == 1
    f = face_returning("pass", 0.5)
    r = ims.check_all(stage.script, ocr=lambda p: ocr_calls.append(1) or "", face=f)
    assert r["checked"] == [sid] and len(ocr_calls) == 1 and len(f.calls) == 1               # الملصق ما انعاد
    ims.check_all(stage.script, ocr=NO_OCR, face=f, only_missing=False)
    assert len(f.calls) == 2


def test_check_all_skips_shots_without_a_final_image(stage):
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    assert ims.check_all(stage.script, ocr=NO_OCR, face=face_returning("pass", 0.5)) == {"checked": [], "failed": []}
    sid = chosen(stage)
    assert ims.check_all(stage.script, ocr=NO_OCR, face=face_returning("pass", 0.5))["checked"] == [sid] and len(ids) > 1


# ───────────────────────── التعلّم ─────────────────────────
def test_face_rates_per_model_count_only_decisive_checks(stage):
    for model, status, score in (("m_good", "ok", .7), ("m_good", "ok", .6), ("m_good", "failed", .2), ("m_bad", "failed", .1)):
        production_log.record("face_image", status, model_id=model, model_name=model.upper(), score=score)
    production_log.record("face_video", "ok", model_id="v1", score=.9)
    r = production_log.face_rates("face_image")
    assert r["m_good"] == {"name": "M_GOOD", "checks": 3, "passed": 2, "rate": 0.667, "avg_score": 0.5}
    assert r["m_bad"]["rate"] == 0.0 and "v1" not in r
    assert production_log.face_rates("face_video")["v1"]["rate"] == 1.0
    with pytest.raises(ValueError):
        production_log.face_rates("motion")


def test_face_rates_are_empty_without_a_database_or_models(env):
    assert production_log.face_rates("face_image") == {}
    production_log.record("face_image", "ok", model_id=None, score=.5)
    assert production_log.face_rates("face_image") == {}


# ───────────────────────── المسار ─────────────────────────
def test_the_route_checks_everything_missing_in_one_call(stage, monkeypatch):
    ids = choose_all(stage)
    monkeypatch.setattr(ims, "_easyocr_read", lambda p: "")
    f = face_returning("fail", 0.1)
    monkeypatch.setattr(facecheck, "check_image", f)
    c = tc.client()
    r = c.post("/api/studio/s1.json/match/check")
    assert r.status_code == 200 and r.json() == {"checked": ids, "failed": []}
    tl = timeline.load("s1")
    assert any(sh["face_check"] and sh["face_check"]["status"] == "fail" for sc in tl["scenes"] for sh in sc["shots"])
    assert c.post("/api/studio/s1.json/match/check").json()["checked"] == []                 # ما بتنعاد
    info = c.get("/api/studio/s1.json/images/info").json()
    assert any("الوجه تغيّر" in p["message"] for p in info["match_problems"])
