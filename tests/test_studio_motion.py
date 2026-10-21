"""استوديو الإنتاج — المحطة ٩: التحريك بموديلات محلية."""

import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_images as ti  # noqa: E402
from test_studio_images import stage  # noqa: E402,F401  (fixture)

import config  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def lavfi(seconds_expr="{seconds}"):
    """موديل مزيّف: ffmpeg بيولّد فيديو بالمدة المطلوبة (أو غيرها)."""
    return ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s=64x114:d={seconds_expr}:r=10", "-pix_fmt", "yuv420p", "{out}"]


def model(name="نموذج", max_sec=5, vram=4, strengths=("product", "realism"), command=None, **kw):
    return {"name": name, "max_sec": max_sec, "vram_gb": vram, "strengths": list(strengths),
            "command": command or lavfi(), "speed_sec_per_sec": 30, **kw}


# ───────────────────────── السجل ─────────────────────────
def test_registry_crud_and_validation(env):
    m = motion.upsert_model(model("أ"))
    assert m["id"] == "mm_001" and m["enabled"] and not m["lipsync"]
    assert motion.upsert_model(model("ب"))["id"] == "mm_002"
    with pytest.raises(motion.MotionError):
        motion.upsert_model({"name": "", "max_sec": 3})
    with pytest.raises(motion.MotionError):
        motion.upsert_model({"name": "x"})                                   # بلا max_sec
    with pytest.raises(motion.MotionError):
        motion.upsert_model(model("x", max_sec=999))
    with pytest.raises(motion.MotionError):
        motion.upsert_model(model("x", strengths=("magic",)))
    with pytest.raises(motion.MotionError):
        motion.upsert_model(model("x", command="python run.py"))              # لازم قائمة وسائط
    upd = motion.upsert_model({"vram_gb": 8, "enabled": False}, "mm_001")
    assert upd["vram_gb"] == 8 and not upd["enabled"] and upd["name"] == "أ"
    assert motion.upsert_model({"lipsync_command": ["x", "{video}", "{audio}", "{out}"]}, "mm_002")["lipsync"]
    motion.delete_model("mm_001")
    assert [x["id"] for x in motion.load_models()] == ["mm_002"]
    with pytest.raises(motion.MotionError):
        motion.delete_model("mm_099")


# ───────────────────────── الاختيار التلقائي ─────────────────────────
def shot(typ="close", dur=3000, desc="", char=None):
    return {"id": "s1c1", "type": typ, "start_ms": 0, "end_ms": dur, "motion_desc": desc,
            "refs": {"character_id": char}}


def test_needs_follow_type_and_camera_words():
    assert motion.needs_for(shot("hand_product"))[0] == "hand"
    assert "product" in motion.needs_for(shot("close"))
    assert "camera_motion" in motion.needs_for(shot("close", desc="تقريب بطيء بالكاميرا"))
    assert "faces" in motion.needs_for(shot("medium", char="ch_f_001"))


def test_rank_excludes_with_written_reasons_and_orders_by_strengths():
    ms = [
        {"id": "a", "name": "قصير", **model(max_sec=2), "enabled": True, "lipsync": False},
        {"id": "b", "name": "ثقيل", **model(vram=16), "enabled": True, "lipsync": False},
        {"id": "c", "name": "معطّل", **model(), "enabled": False, "lipsync": False},
        {"id": "d", "name": "بلا أمر", **{**model(), "command": None}, "enabled": True, "lipsync": False},
        {"id": "e", "name": "ممتاز", **model(strengths=("product", "realism")), "enabled": True, "lipsync": False},
        {"id": "f", "name": "ضعيف", **model(strengths=("faces",)), "enabled": True, "lipsync": False},
    ]
    r = motion.rank_models(shot("close", 3000), ms, vram_gb=6)
    assert [x["model"]["id"] for x in r["ranked"]] == ["e", "f"]
    why = {x["model"]["id"]: x["reason"] for x in r["excluded"]}
    assert "أقصر" in why["a"] and "16" in why["b"] and "6" in why["b"] and why["c"] == "معطّل" and "أمر" in why["d"]
    assert r["ranked"][0]["matched"] == ["product", "realism"] and r["ranked"][0]["eta_sec"] == 90


def test_talking_shots_need_a_lipsync_capable_model():
    ms = [{"id": "a", "name": "بلا شفاه", **model(), "enabled": True, "lipsync": False},
          {"id": "b", "name": "بشفاه", **model(lipsync_command=["x"]), "enabled": True, "lipsync": True}]
    r = motion.rank_models(shot("medium", char="ch_f_001"), ms, vram_gb=8, talking=True)
    assert [x["model"]["id"] for x in r["ranked"]] == ["b"] and "شفاه" in r["excluded"][0]["reason"]


# ───────────────────────── برومبت الحركة ─────────────────────────
def test_prompt_has_seven_ordered_sections_within_limit():
    p = motion.build_prompt(shot("close"), {"emotion": "calm"}, None, 3200)
    assert "3.2 ثانية" in p and len(p) <= motion.MAX_PROMPT
    pos = [p.index(f"{i}. {k}:") for i, k in enumerate(motion.SECTIONS, 1)]
    assert pos == sorted(pos) and motion.validate_prompt(p) == []
    assert "أي كتابة" in p and "لا تغيّر عبوة المنتج" in p


def test_prompt_names_the_character_but_hand_shots_have_no_face():
    ch = {"name_ar": "ريم"}
    assert "ريم" in motion.build_prompt(shot("medium"), {}, ch, 3000)
    assert "ريم" not in motion.build_prompt(shot("hand_product"), {}, ch, 3000)


def test_prompt_is_trimmed_then_rejected_beyond_2000_chars():
    long = shot("close", desc="حركة " * 300)
    with pytest.raises(motion.MotionError) as e:
        motion.build_prompt(long, {"emotion": "x" * 800}, None, 3000)
    assert "وصف الحركة طويل" in str(e.value)
    mid = shot("close", desc="حركة طويلة " * 50)              # 550 حرف: مقبول، والأجواء بتنقصّ
    assert len(motion.build_prompt(mid, {"emotion": "x" * 1500}, None, 3000)) <= motion.MAX_PROMPT
    assert motion.validate_prompt("ناقص") != []


# ───────────────────────── ضبط المدة ─────────────────────────
def make_clip(path, sec):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=red:s=64x114:d={sec}:r=10", "-pix_fmt", "yuv420p", str(path)],
                   capture_output=True, check=True)


@pytest.mark.parametrize("src_sec,how", [(5.0, "trimmed"), (3.0, "exact"), (2.7, "stretched")])
def test_fit_duration_is_exact_within_tolerance(tmp_path, src_sec, how):
    src = tmp_path / "a.mp4"
    make_clip(src, src_sec)
    r = motion.fit_duration(src, tmp_path / "o.mp4", 3000)
    assert r["how"] == how
    assert abs(motion.probe_duration(tmp_path / "o.mp4") * 1000 - 3000) <= motion.DURATION_EPS_MS


def test_fit_duration_fails_when_far_too_short_or_garbage(tmp_path):
    src = tmp_path / "a.mp4"
    make_clip(src, 1.0)
    with pytest.raises(motion.MotionError) as e:
        motion.fit_duration(src, tmp_path / "o.mp4", 3000)
    assert "أقصر" in str(e.value)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not video")
    with pytest.raises(motion.MotionError):
        motion.fit_duration(bad, tmp_path / "o2.mp4", 3000)


# ───────────────────────── التشغيل ─────────────────────────
@pytest.fixture
def ready(stage):
    """كل لقطة إلها صورة مختارة وتطابق معتمد — الشرط لبدء التحريك."""
    tl = timeline.load("s1")
    ids = [s["id"] for sc in tl["scenes"] for s in sc["shots"]]
    for sid in ids:
        ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
        ims.choose(stage.script, sid, ims._shot(timeline.load("s1"), sid)[1]["image"]["candidates"][0]["path"])
    ims.approve_images(stage.script)
    for sid in ids:
        ims.set_verdict(stage.script, sid, "pass")
    ims.approve_match(stage.script)
    stage.ids = ids
    return stage


def test_motion_needs_approved_match_station(stage):
    motion.upsert_model(model())
    with pytest.raises(motion.MotionError):
        motion.run_shot(stage.script, "s1c1", log=lambda *_: None)


def test_run_shot_produces_exact_duration_clip_and_choose_sets_motion(ready):
    m = motion.upsert_model(model(max_sec=6))
    sid = ready.ids[0]
    r = motion.run_shot(ready.script, sid, log=lambda *_: None)
    assert r["model"] == m["id"] and len(r["made"]) == 1
    tl = timeline.load("s1")
    sh = ims._shot(tl, sid)[1]
    dur = sh["end_ms"] - sh["start_ms"]
    cand = sh["motion_candidates"][0]
    assert cand["duration_ms"] == dur and ":\\" not in cand["clip"]
    clip = motion.abs_of("s1", cand["clip"])
    assert abs(motion.probe_duration(clip) * 1000 - dur) <= motion.DURATION_EPS_MS
    assert motion.validate_prompt(sh["motion_prompt"]) == []
    assert studio_state.state_of("s1", 9) == "awaiting_choice"
    out = motion.choose(ready.script, sid, cand["clip"])
    assert out["motion"]["duration_ms"] == dur and timeline.validate(timeline.load("s1"))["ok"]
    with pytest.raises(motion.MotionError):
        motion.choose(ready.script, sid, "clips/other.mp4")


def test_two_options_and_model_too_short_is_refused_with_reason(ready):
    motion.upsert_model(model("قصير", max_sec=1))
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], log=lambda *_: None)
    assert "ما في موديل مناسب" in str(e.value) and "أقصر" in str(e.value)
    good = motion.upsert_model(model("جيد", max_sec=6))
    r = motion.run_shot(ready.script, ready.ids[0], good["id"], n=2, log=lambda *_: None)
    assert len(r["made"]) == 2
    short = [x for x in motion.load_models() if x["name"] == "قصير"][0]
    with pytest.raises(motion.MotionError) as e2:
        motion.run_shot(ready.script, ready.ids[0], short["id"], log=lambda *_: None)
    assert "ما بيناسب اللقطة" in str(e2.value)


def test_model_failures_mark_station_failed_with_message(ready):
    bad = motion.upsert_model(model("معطوب", max_sec=6, command=["python", "-c", "import sys; sys.exit(3)", "{out}"]))
    with pytest.raises(motion.MotionError) as e:
        motion.run_shot(ready.script, ready.ids[0], bad["id"], log=lambda *_: None)
    assert "فشل" in str(e.value) and studio_state.state_of("s1", 9) == "failed"
    nofile = motion.upsert_model(model("بلا خرج", max_sec=6, command=["python", "-c", "pass", "{out}"]))
    with pytest.raises(motion.MotionError) as e2:
        motion.run_shot(ready.script, ready.ids[0], nofile["id"], log=lambda *_: None)
    assert "ما كتب" in str(e2.value)
    tooshort = motion.upsert_model(model("أقصر من المطلوب", max_sec=6, command=lavfi("0.4")))
    with pytest.raises(motion.MotionError) as e3:
        motion.run_shot(ready.script, ready.ids[0], tooshort["id"], log=lambda *_: None)
    assert "أقصر من الحد" in str(e3.value)


def test_approve_needs_every_shot_with_motion_of_exact_duration(ready):
    m = motion.upsert_model(model(max_sec=6))
    for sid in ready.ids[:2]:
        motion.run_shot(ready.script, sid, m["id"], log=lambda *_: None)
        motion.choose(ready.script, sid, ims._shot(timeline.load("s1"), sid)[1]["motion_candidates"][0]["clip"])
    with pytest.raises(motion.MotionError) as e:
        motion.approve(ready.script)
    assert "ما في حركة" in str(e.value)
    res = motion.run_all(ready.script, m["id"], 1, log=lambda *_: None)
    assert not res["failed"] and len(res["done"]) == len(ready.ids) - 2
    for sid in ready.ids[2:]:
        motion.choose(ready.script, sid, ims._shot(timeline.load("s1"), sid)[1]["motion_candidates"][0]["clip"])
    assert motion.approve(ready.script)["approved"] and studio_state.state_of("s1", 9) == "approved"
    tl = timeline.load("s1")
    assert timeline.validate(tl)["ok"]
    # تحريك حد لقطة بعد الاعتماد بيمسح حركة اللقطتين — لازم إعادة
    sc = tl["scenes"][1]
    timeline.move_boundary(tl, sc["n"], 1, sc["shots"][0]["end_ms"] + 300)
    assert sc["shots"][0]["motion"] is None and sc["shots"][1]["motion"] is None
    assert len(motion.problems(tl)) == 2


def test_talking_shot_uses_lipsync_command(ready):
    import subprocess
    man = json.loads((ready.env.lib / "voice" / "s1" / "voice.json").read_text(encoding="utf-8"))
    audio = ready.env.lib / man["combined"]["path"]
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=50", str(audio)], capture_output=True, check=True)
    lip = ["ffmpeg", "-y", "-i", "{video}", "-c", "copy", "{out}"]
    plain = motion.upsert_model(model("بلا شفاه", max_sec=6))
    m = motion.upsert_model(model("بشفاه", max_sec=6, lipsync_command=lip))
    sid = next(s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"] if s["type"] == "medium")
    motion.set_desc(ready.script, sid, "تتكلم للكاميرا", talking=True)
    with pytest.raises(motion.MotionError):
        motion.run_shot(ready.script, sid, plain["id"], log=lambda *_: None)
    motion.run_shot(ready.script, sid, m["id"], log=lambda *_: None)
    c = ims._shot(timeline.load("s1"), sid)[1]["motion_candidates"][0]
    assert c["lipsync"] and motion.abs_of("s1", c["clip"])
    dur = ims._shot(timeline.load("s1"), sid)[1]
    assert abs(motion.probe_duration(motion.abs_of("s1", c["clip"])) * 1000 - (dur["end_ms"] - dur["start_ms"])) <= motion.DURATION_EPS_MS
    motion.choose(ready.script, sid, c["clip"])
    assert not [p for p in motion.problems(timeline.load("s1")) if p["shot"] == sid]


def test_talking_without_lipsync_clip_is_a_problem():
    tl = {"scenes": [{"n": 1, "shots": [{"id": "s1c1", "start_ms": 0, "end_ms": 3000, "talking": True,
                                          "motion": {"clip": "clips/x.mp4", "duration_ms": 3000, "lipsync": False}}]}]}
    assert "مزامنة شفاه" in motion.problems(tl)[0]["message"]


# ───────────────────────── API ─────────────────────────
def test_api_registry_info_run_and_gates(ready):
    c = tc_client()
    r = c.post("/api/motion-models", json=model("موديلي", max_sec=6))
    assert r.status_code == 200 and c.post("/api/motion-models", json={"name": ""}).status_code == 400
    mid = r.json()["id"]
    assert c.get("/api/motion-models").json()["models"][0]["id"] == mid
    assert c.put(f"/api/motion-models/{mid}", json={"max_sec": -1}).status_code == 400
    info = c.get("/api/studio/s1.json/motion/info").json()
    assert len(info["shots"]) == len(ready.ids) and info["shots"][0]["ranked"][0]["id"] == mid
    assert info["eta_total_sec"] > 0 and info["problems"]
    assert c.post("/api/studio/s1.json/motion/run?n=9").status_code == 400
    assert c.post("/api/studio/s1.json/motion/run?shot=s1c1&model=" + mid).status_code == 200
    assert ready.env.jobs[-1]["cmd"][:2] == ["motion.py", "run"] and "--shot" in ready.env.jobs[-1]["cmd"]
    d = c.put("/api/studio/s1.json/shots/s1c1/motion-desc", json={"desc": "حركة جديدة", "talking": True})
    assert d.status_code == 200 and d.json()["shot"]["talking"] is True
    assert c.put("/api/studio/s1.json/shots/s1c1/motion-desc", json={"desc": " "}).status_code == 409
    assert c.post("/api/studio/s1.json/motion/approve").status_code == 409
    assert c.delete(f"/api/motion-models/{mid}").status_code == 200
    assert c.delete(f"/api/motion-models/{mid}").status_code == 404


def test_api_run_blocked_before_match_approved_and_clip_paths_are_safe(ready):
    c = tc_client()
    studio_state.set_state("s1", 8, "awaiting_choice", "x")
    assert c.post("/api/studio/s1.json/motion/run").status_code == 409
    assert c.get("/api/studio/s1.json/clip/..%2F..%2Fstate.json").status_code == 404
    assert c.get("/api/studio/s1.json/clip/img/whatever.png").status_code == 404


def tc_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_motion, routes_studio
    app = FastAPI()
    app.include_router(routes_motion.router)
    app.include_router(routes_studio.router)
    return TestClient(app)
