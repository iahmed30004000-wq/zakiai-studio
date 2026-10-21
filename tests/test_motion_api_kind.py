"""تحريك اللقطات بنوع «api» (fal.ai) داخل النظام: التسجيل، الترتيب بالأرخص، السعر، سقف الإنفاق، البديل التلقائي. خادم fal مزيّف."""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage  # noqa: E402,F401
from test_studio_motion import lavfi, model, ready, tc_client  # noqa: E402,F401
from test_motion_api import fal, KEY, spec  # noqa: E402,F401

import config  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import motion_api  # noqa: E402
import production_log  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def api_model(name="Kling (fal)", cost=0.07, durations=(5, 10), **kw):
    s = spec(durations=list(durations), cost_per_sec=cost)
    d = {"name": name, "kind": "api", "api": s, "strengths": ["product", "realism"]}
    d.update(kw)
    return d


def shot_of(ready, i=0):
    sid = ready.ids[i]
    return sid, ims._shot(timeline.load("s1"), sid)[1]


# ───────── السجل والتحقق ─────────
def test_api_model_registry_derives_max_sec_default_speed_and_validates(env):
    m = motion.upsert_model(api_model())
    assert m["kind"] == "api" and m["max_sec"] == 10 and m["speed_sec_per_sec"] == 15 and m["http"] is None
    assert m["api"]["endpoint"].startswith("fal-ai/kling-video") and m["api"]["cost_per_sec"] == 0.07
    with pytest.raises(motion.MotionError, match="endpoint"):
        motion.upsert_model(api_model(api=spec(endpoint="https://evil.com/x")))
    with pytest.raises(motion.MotionError, match="{image}"):
        motion.upsert_model(api_model(api=spec(input={"prompt": "{prompt}"})))
    with pytest.raises(motion.MotionError):
        motion.upsert_model({"name": "x", "kind": "api", "max_sec": 5})            # بلا api
    upd = motion.upsert_model({"api": spec(cost_per_sec=0.05, durations=[5])}, m["id"])       # تعديل السعر
    assert upd["api"]["cost_per_sec"] == 0.05 and upd["kind"] == "api"


def test_api_model_is_excluded_until_a_key_exists(env, monkeypatch):
    m = motion.upsert_model(api_model())
    sh = {"type": "close", "start_ms": 0, "end_ms": 3000}
    monkeypatch.setattr(motion_api, "has_key", lambda: False)
    rk = motion.rank_models(sh, vram_gb=6)
    assert not rk["ranked"] and "مفتاح fal" in rk["excluded"][0]["reason"]
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    assert [r["model"]["id"] for r in motion.rank_models(sh, vram_gb=6)["ranked"]] == [m["id"]]


# ───────── الترتيب بالأرخص ضمن المناسب ─────────
def test_ranking_prefers_free_local_then_cheaper_api_when_fit_is_equal(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    exp = motion.upsert_model(api_model("غالي", cost=0.30))
    cheap = motion.upsert_model(api_model("رخيص", cost=0.04))
    local = motion.upsert_model(model("محلي", vram=2))
    sh = {"type": "close", "start_ms": 0, "end_ms": 3000}
    r = motion.rank_models(sh, vram_gb=6)["ranked"]
    assert [x["model"]["id"] for x in r] == [local["id"], cheap["id"], exp["id"]]
    assert r[0]["est_cost_usd"] == 0 and r[1]["est_cost_usd"] == pytest.approx(0.20) and r[2]["est_cost_usd"] == pytest.approx(1.5)


def test_fit_beats_price(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    pricey_fit = motion.upsert_model(api_model("مناسب غالي", cost=0.30))                      # product+realism
    cheap_unfit = motion.upsert_model(api_model("رخيص غير مناسب", cost=0.01, strengths=[]))
    sh = {"type": "close", "start_ms": 0, "end_ms": 3000}
    ids = [x["model"]["id"] for x in motion.rank_models(sh, vram_gb=6)["ranked"]]
    assert ids == [pricey_fit["id"], cheap_unfit["id"]]


def test_shot_longer_than_the_api_max_is_excluded(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    motion.upsert_model(api_model(durations=(5,)))
    rk = motion.rank_models({"type": "wide", "start_ms": 0, "end_ms": 6500}, vram_gb=6)
    assert not rk["ranked"] and "أقصى مدة" in rk["excluded"][0]["reason"]


# ───────── التشغيل الفعلي + السعر + السجل ─────────
def test_run_shot_over_fal_makes_exact_duration_candidate_with_cost_and_english_prompt(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    m = motion.upsert_model(api_model())
    sid, sh = shot_of(ready)
    dur = sh["end_ms"] - sh["start_ms"]
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    lines = []
    r = motion.run_shot(ready.script, sid, log=lines.append)
    assert r["model"] == m["id"] and r["fallbacks"] == 0
    cand = ims._shot(timeline.load("s1"), sid)[1]["motion_candidates"][0]
    assert cand["path"] == "api" and cand["model_id"] == m["id"] and cand["duration_ms"] == dur
    assert cand["cost_usd"] == pytest.approx(0.35)                                   # 5 ثواني × 0.07 حتى لو اللقطة 3 ثواني
    sub = next(x for x in fal.requests if x[0] == "POST")[3]
    assert sub["prompt"].startswith("Animate the reference image") and not any("؀" <= c <= "ۿ" for c in sub["prompt"])
    assert sub["start_image_url"].startswith("data:image/jpeg;base64,") and sub["generate_audio"] is False
    rec = production_log.recent(5, "motion")[0]
    assert rec["path"] == "api" and rec["status"] == "ok" and rec["cost_usd"] == pytest.approx(0.35)
    assert production_log.spent("s1", "motion") == pytest.approx(0.35)
    assert studio_state.state_of("s1", 9) == "awaiting_choice"
    assert KEY not in " ".join(lines)


def test_api_failure_falls_back_to_the_local_model_and_is_logged(ready, fal, monkeypatch):
    fal.submit_status = 402                                                          # رصيد fal خلص
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    api = motion.upsert_model(api_model(strengths=["product", "realism", "faces"]))     # الأفضل ملاءمة
    local = motion.upsert_model(model("محلي", vram=2))
    sid, _sh = shot_of(ready)
    r = motion.run_shot(ready.script, sid, log=lambda *_: None)
    assert r["model"] == local["id"] and r["fallbacks"] == 1
    cand = ims._shot(timeline.load("s1"), sid)[1]["motion_candidates"][0]
    assert cand["fallback_from"] == api["id"] and cand["path"] == "command" and "cost_usd" not in cand
    rec = production_log.recent(5, "motion")
    assert [x["status"] for x in rec][:2] == ["ok", "failed"] and "رصيد" in (rec[1]["error"] or "")
    assert production_log.spent("s1", "motion") == 0


def test_api_only_and_it_fails_gives_a_plain_arabic_message_and_marks_the_station_failed(ready, fal, monkeypatch):
    fal.submit_status = 401
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    motion.upsert_model(api_model())
    sid, _sh = shot_of(ready)
    with pytest.raises(motion.MotionError, match="مفتاح fal مرفوض"):
        motion.run_shot(ready.script, sid, log=lambda *_: None)
    assert studio_state.state_of("s1", 9) == "failed"


# ───────── سقف الإنفاق ─────────
def test_spending_cap_blocks_api_and_uses_the_free_local_model(ready, fal, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(config, "MOTION_API_CAP_USD", 0.30)                          # أقل من تكلفة لقطة (0.35)
    api = motion.upsert_model(api_model(strengths=["product", "realism", "faces"]))
    local = motion.upsert_model(model("محلي", vram=2))
    sid, _sh = shot_of(ready)
    lines = []
    r = motion.run_shot(ready.script, sid, log=lines.append)
    assert r["model"] == local["id"]
    assert not [x for x in fal.requests if x[0] == "POST"]                           # ما انبعت ولا طلب لـ fal
    assert any("سقف" in x for x in lines)


def test_spending_cap_with_only_api_fails_with_the_cap_message(ready, fal, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(config, "MOTION_API_CAP_USD", 0.10)
    motion.upsert_model(api_model())
    sid, _sh = shot_of(ready)
    with pytest.raises(motion.MotionError, match="سقف إنفاق"):
        motion.run_shot(ready.script, sid, log=lambda *_: None)
    assert not fal.requests


def test_cap_counts_what_was_already_spent_on_this_script(ready, fal, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(config, "MOTION_API_CAP_USD", 0.50)
    m = motion.upsert_model(api_model())
    production_log.record("motion", "ok", script_stem="s1", shot_id="x", model_id=m["id"], path="api", cost_usd=0.40)
    sid, _sh = shot_of(ready)
    with pytest.raises(motion.MotionError, match="سقف إنفاق"):
        motion.run_shot(ready.script, sid, log=lambda *_: None)                      # 0.40 + 0.35 > 0.50
    production_log.record("motion", "failed", script_stem="s1", model_id=m["id"], path="api", cost_usd=9)   # الفاشل ما بينحسب


# ───────── تقدير تكلفة السيناريو ─────────
def test_estimate_script_sums_cost_per_shot_and_flags_cap(ready, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(config, "MOTION_API_CAP_USD", 1.0)
    motion.upsert_model(api_model())
    est = motion.estimate_script(ready.script)
    n = len(ready.ids)
    assert len(est["shots"]) == n and all(s["path"] == "api" for s in est["shots"])
    assert est["total_usd"] == pytest.approx(sum(s["cost_usd"] for s in est["shots"]), abs=0.01) and est["total_usd"] > 0
    assert est["cap_usd"] == 1.0 and est["over_cap"] == (est["total_usd"] > 1.0) and est["unknown_prices"] == 0
    local = motion.upsert_model(model("محلي", vram=2))
    est2 = motion.estimate_script(ready.script)
    assert est2["total_usd"] == 0 and all(s["path"] == "command" for s in est2["shots"])          # المجاني بيتقدّم
    assert motion.estimate_script(ready.script, model_id=local["id"])["total_usd"] == 0


def test_english_prompt_uses_latin_custom_desc_else_defaults_and_never_arabic():
    sh = {"type": "hand_product", "motion_desc": "اليد ترفع المنتج ببطء"}
    p = motion.build_prompt_en(sh, None, 3400)
    assert "3.4 seconds" in p and "hand slowly lifts" in p and not any("؀" <= c <= "ۿ" for c in p)
    sh2 = {"type": "close", "motion_desc": "Slow orbit around the bottle, light glints on the label"}
    assert "Slow orbit around the bottle" in motion.build_prompt_en(sh2, None, 2000)
    sh3 = {"type": "close", "motion_desc": "تقريب بطيء"}                                # وصف عربي فيه حركة كاميرا → الوصف الافتراضي + تلميح الكاميرا
    assert "smooth camera move" in motion.build_prompt_en(sh3, None, 3000)
    sh4 = {"type": "medium", "motion_desc": "حركة خفيفة"}
    assert "same person" in motion.build_prompt_en(sh4, {"name_ar": "ريم"}, 3000) and "same person" not in motion.build_prompt_en(sh4, None, 3000)
    assert len(motion.build_prompt_en({"type": "wide", "motion_desc": "x" * 600, "api_desc_en": "y" * 3000}, None, 1000)) <= 1500
