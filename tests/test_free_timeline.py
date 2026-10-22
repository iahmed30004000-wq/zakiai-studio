"""الخط الزمني الحر: قواعد التحقق (timeline._validate_free) — والمهمة الموجّهة ما بتتأثر."""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import timeline  # noqa: E402


def shot(sid, a, b, **kw):
    return {"id": sid, "start_ms": a, "end_ms": b, **kw}


def free_tl(scenes=None, length=None):
    scenes = scenes if scenes is not None else [
        {"n": 1, "key": "c001", "start_ms": 0, "end_ms": 5000,
         "shots": [shot("f001", 0, 3000, image={"chosen": "img/a.png"}), shot("f002", 3000, 5000, motion={"clip": "clips/a.mp4", "duration_ms": 2000})]},
        {"n": 2, "key": "c002", "start_ms": 5000, "end_ms": 8000, "shots": [shot("f003", 5000, 8000, image={"chosen": "img/b.png"})]},
    ]
    return {"mode": "free", "scenes": scenes, "length_ms": length if length is not None else (scenes[-1]["end_ms"] if scenes else 0)}


def codes(res, key="errors"):
    return {e["code"] for e in res[key]}


def test_a_valid_free_timeline_has_no_errors_and_no_forty_five_second_rule():
    res = timeline.validate(free_tl())
    assert res["ok"] and not res["errors"] and not res["warnings"]            # 8 ثواني، 2 مشهد، بلا كلمات: مسموح بالحر


def test_empty_free_timeline_is_ok_with_a_note():
    res = timeline.validate(free_tl([]))
    assert res["ok"] and codes(res, "warnings") == {"no_scenes"}


def test_gaps_overlaps_and_wrong_ends_are_errors():
    tl = free_tl()
    tl["scenes"][0]["shots"][1]["start_ms"] = 3500                              # فجوة بعد اللقطة الأولى
    assert {"shot_gap"} <= codes(timeline.validate(tl))
    tl = free_tl()
    tl["scenes"][1]["start_ms"] = 5500
    assert {"scene_gap"} <= codes(timeline.validate(tl))
    tl = free_tl()
    tl["scenes"][0]["end_ms"] = 4000
    assert "scene_end" in codes(timeline.validate(tl))
    tl = free_tl()
    tl["length_ms"] = 9000
    assert "sum_mismatch" in codes(timeline.validate(tl))


def test_shot_duration_limits():
    tl = free_tl()
    tl["scenes"][1]["shots"] = [shot("f003", 5000, 5300, image={"chosen": "x"})]
    tl["scenes"][1]["end_ms"], tl["length_ms"] = 5300, 5300
    assert "shot_short" in codes(timeline.validate(tl))
    tl = free_tl()
    tl["scenes"][1]["shots"] = [shot("f003", 5000, 5000 + 61_000, image={"chosen": "x"})]
    tl["scenes"][1]["end_ms"] = tl["length_ms"] = 66_000
    assert "shot_long" in codes(timeline.validate(tl))
    tl = free_tl()
    tl["scenes"][1]["shots"] = [shot("f003", 5000, 5000, image={"chosen": "x"})]
    tl["scenes"][1]["end_ms"] = tl["length_ms"] = 5000
    assert "shot_zero" in codes(timeline.validate(tl))


def test_counts_and_total_limits():
    many = [{"n": i, "key": f"c{i:03d}", "start_ms": (i - 1) * 1000, "end_ms": i * 1000,
             "shots": [shot(f"f{i:03d}", (i - 1) * 1000, i * 1000 - 0, image={"chosen": "x"})]} for i in range(1, 42)]
    for sc in many:
        sc["shots"][0]["end_ms"] = sc["end_ms"]
    res = timeline.validate(free_tl(many))
    assert "scene_count" in codes(res)
    nine = [shot(f"f{i}", i * 600, (i + 1) * 600, image={"chosen": "x"}) for i in range(9)]
    tl = free_tl([{"n": 1, "key": "c001", "start_ms": 0, "end_ms": 5400, "shots": nine}])
    assert "shot_count" in codes(timeline.validate(tl))
    tl = free_tl([{"n": 1, "key": "c001", "start_ms": 0, "end_ms": 5000, "shots": []}])
    assert "shot_count" in codes(timeline.validate(tl))
    long_scenes = [{"n": i, "key": f"c{i}", "start_ms": (i - 1) * 60_000, "end_ms": i * 60_000,
                    "shots": [shot(f"f{i}", (i - 1) * 60_000, i * 60_000, image={"chosen": "x"})]} for i in range(1, 7)]
    assert "total_long" in codes(timeline.validate(free_tl(long_scenes)))


def test_ids_must_be_present_and_unique():
    tl = free_tl()
    tl["scenes"][1]["shots"][0]["id"] = "f001"
    assert "shot_id" in codes(timeline.validate(tl))
    tl = free_tl()
    tl["scenes"][1]["key"] = "c001"
    assert "scene_key" in codes(timeline.validate(tl))
    tl = free_tl()
    del tl["scenes"][0]["key"]
    assert "scene_key" in codes(timeline.validate(tl))


def test_warnings_for_missing_media_motion_mismatch_and_long_voice():
    tl = free_tl()
    tl["scenes"][1]["shots"][0] = shot("f003", 5000, 8000)                       # بلا صورة ولا فيديو
    tl["scenes"][0]["shots"][1]["motion"]["duration_ms"] = 1500                  # فيديو أقصر من اللقطة
    tl["scenes"][0]["voice"] = {"duration_ms": 9000}                             # صوت أطول من المشهد
    res = timeline.validate(tl)
    assert res["ok"]
    assert codes(res, "warnings") == {"shot_no_media", "motion_duration", "voice_long"}


def test_a_timeline_without_mode_still_uses_the_guided_rules():
    tl = copy.deepcopy(free_tl())
    del tl["mode"]
    res = timeline.validate(tl)
    assert not res["ok"] and {"scene_count", "voice_duration"} <= codes(res)
    assert not timeline.is_free(tl) and timeline.is_free(free_tl()) and not timeline.is_free(None)


def test_save_refuses_an_invalid_free_timeline_and_accepts_a_valid_one(env):
    import pytest
    bad = free_tl()
    bad["scenes"][0]["shots"][1]["start_ms"] = 3500
    with pytest.raises(timeline.TimelineError) as e:
        timeline.save("fx", bad)
    assert "خط زمني غير صالح" in str(e.value) and not timeline.path_for("fx").exists()
    assert timeline.save("fx", free_tl())["ok"] and timeline.load("fx")["mode"] == "free"
