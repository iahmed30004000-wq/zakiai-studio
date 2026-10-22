"""الإضافة متعددة المواقع (الجانب الخادم): مهام الصوت والصور والتحريك والآهات والموسيقى، الإعداد، الإصدار، الفحص الذاتي."""

import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_voice_timeline as tv  # noqa: E402
from test_studio_images import stage  # noqa: E402,F401
from test_studio_extension import bridge, client, png  # noqa: E402,F401

import ahat  # noqa: E402
import config  # noqa: E402
import ext_bridge  # noqa: E402
import ext_config  # noqa: E402
import ext_tasks  # noqa: E402
import generate_voice  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import review_loop  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import tts  # noqa: E402
import voice_studio  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")

# الدوال الحقيقية قبل ما تبدّلها fixtures الاستوديو بنسخ مزيّفة
REAL_AUDIO_DURATION = tts.audio_duration
REAL_CONCAT = generate_voice.concat
API = "/api/studio/s1.json/ext"
ROOT = Path(__file__).resolve().parent.parent


def H(b):
    return {"X-VP-Ext-Token": ext_bridge.token()}


# ───────────────────────── وسائط صغيرة بـ ffmpeg حقيقي ─────────────────────────
@functools.lru_cache(maxsize=None)
def mp3(sec: float) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "a.mp3"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={sec}", "-ac", "1", "-ar", "22050",
                        "-b:a", "24k", str(out)], check=True, capture_output=True)
        return out.read_bytes()


@functools.lru_cache(maxsize=None)
def mp4(sec: float) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "v.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=red:s=64x114:d={sec}:r=10", "-pix_fmt", "yuv420p", str(out)],
                       check=True, capture_output=True)
        return out.read_bytes()


def post(c, h, kind, task_id, data, site="elevenlabs", filename="x.mp3", mime="audio/mpeg"):
    return c.post(f"{API}/result", headers=h, data={"task_id": task_id, "kind": kind, "site": site},
                  files={"file": (filename, data, mime)})


def get_tasks(c, h, kind):
    r = c.get(f"{API}/tasks", params={"kind": kind}, headers=h)
    return r


# ───────────────────────── fixtures ─────────────────────────
@pytest.fixture
def real_audio(bridge, monkeypatch):
    """مدة الصوت الحقيقية (fixture الاستوديو بيثبّتها على قيمة وهمية)."""
    monkeypatch.setattr(tts, "audio_duration", REAL_AUDIO_DURATION)
    monkeypatch.setattr(generate_voice, "concat", REAL_CONCAT)
    return bridge


@pytest.fixture
def vs(env, monkeypatch):
    """سيناريو مراجَع بلا صوت مولّد بعد، وتخزين توكن بالذاكرة. التفريغ الصوتي بيفشل افتراضياً (تقدير)."""
    import secrets_store
    import stt
    store = {}
    monkeypatch.setattr(secrets_store, "get_secret", lambda n: store.get(n))
    monkeypatch.setattr(secrets_store, "set_secret", lambda n, v: store.__setitem__(n, v))
    st = tv.Studio(env, monkeypatch, [tv.IN_RANGE])
    monkeypatch.setattr(tts, "audio_duration", REAL_AUDIO_DURATION)
    monkeypatch.setattr(generate_voice, "concat", REAL_CONCAT)

    def no_stt(path):
        raise stt.STTError("ما في مفتاح")

    monkeypatch.setattr(stt, "transcribe", no_stt)
    st.stt = stt
    st.mp = monkeypatch
    return st


@pytest.fixture
def ready(stage, monkeypatch):
    """كل لقطة إلها صورة مختارة وتطابق معتمد — الشرط لتحريك المحطة 9."""
    import secrets_store
    store = {}
    monkeypatch.setattr(secrets_store, "get_secret", lambda n: store.get(n))
    monkeypatch.setattr(secrets_store, "set_secret", lambda n, v: store.__setitem__(n, v))
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    for sid in ids:
        ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
        ims.choose(stage.script, sid, ims._shot(timeline.load("s1"), sid)[1]["image"]["candidates"][0]["path"])
    ims.approve_images(stage.script)
    for sid in ids:
        ims.set_verdict(stage.script, sid, "pass")
    ims.approve_match(stage.script)
    stage.ids = ids
    return stage


def shot_of(sid):
    return ims._shot(timeline.load("s1"), sid)[1]


def sh_ms(sid):
    sh = shot_of(sid)
    return sh["end_ms"] - sh["start_ms"]


# ═══════════════════════════ الصوت (محطة 4) ═══════════════════════════
def post_all_scenes(c, h, durs, site="elevenlabs"):
    last = None
    for i, d in enumerate(durs, 1):
        last = post(c, h, "voice", f"scene_{i}", mp3(d), site)
        assert last.status_code == 200, last.text
    return last


def test_voice_tasks_carry_emotion_tag_text_and_planned_seconds(vs):
    c = client()
    r = get_tasks(c, H(vs), "voice")
    assert r.status_code == 200
    body = r.json()
    ts = body["tasks"]
    assert body["kind"] == "voice" and [t["task_id"] for t in ts] == [f"scene_{i}" for i in range(1, 8)]
    script = json.loads(vs.script.read_text(encoding="utf-8"))
    t1 = ts[0]
    assert t1["kind"] == "voice" and t1["scene"] == 1 and t1["text"] == script["scenes"][0]["voiceover"]
    assert t1["emotion_tag"] == "[دافئ]" and t1["prompt"] == f"[دافئ] {t1['text']}"
    assert t1["seconds"] == 6.0 and t1["want"] == 1 and t1["retry"] is False and t1["site_hint"] == "elevenlabs"
    assert t1["refs"] == [] and set(t1) == {"task_id", "kind", "scene", "shot_id", "prompt", "text", "emotion_tag",
                                            "seconds", "want", "refs", "site_hint", "retry"}


def test_full_voice_in_range_converts_times_words_merges_and_waits_for_owner(vs):
    stt = vs.stt

    def fake_stt(path):
        d = REAL_AUDIO_DURATION(path)
        return {"segments": [{"start": 0.0, "end": d, "text": " ".join(f"كلمة{i}" for i in range(15))}], "provider": "fake"}

    vs.mp.setattr(stt, "transcribe", fake_stt)
    c = client()
    h = H(vs)
    r = post_all_scenes(c, h, [6, 7, 7, 7, 7, 7, 6])
    assert r.json()["done"] is True and r.json()["complete"] is True and r.json()["gate"]["ok"]
    vdir = Path(config.LIBRARY_DIR) / "voice" / "s1"
    for n in range(1, 8):
        f = vdir / f"scene_{n:02d}.mp3"
        assert f.exists() and REAL_AUDIO_DURATION(f) > 5.5
    mf = voice_studio.load_manifest("s1")
    assert mf["provider"] == "extension:elevenlabs" and 45 <= mf["total_actual_sec"] <= 50
    assert all(s["provider"] == "extension:elevenlabs" and s["timing_source"] == "stt" and len(s["words"]) >= 10
               and ":\\" not in s["path"] and s["emotion_tag"] == "[دافئ]" for s in mf["scenes"])
    assert mf["combined"] and abs(mf["combined"]["duration_sec"] - mf["total_actual_sec"]) < 0.6
    assert (Path(config.LIBRARY_DIR) / mf["combined"]["path"]).exists()
    assert studio_state.state_of("s1", 4) == "awaiting_choice" and studio_state.state_of("s1", 5) == "not_started"
    assert ext_bridge.control("s1")["command"] == "idle"
    assert get_tasks(c, h, "voice").json()["tasks"] == []
    # المالك بيعتمد بسمعه ← نفس المسار الموجود بيبني خط زمني صالح
    res = voice_studio.approve_voice(vs.script)
    assert res["approved"] and res["timeline_ok"], res["errors"]
    assert timeline.validate(timeline.load("s1"))["ok"]


def test_voice_without_stt_falls_back_to_estimated_timing_and_says_so(vs):
    c = client()
    r = post(c, H(vs), "voice", "scene_1", mp3(6))
    assert r.status_code == 200 and r.json()["timing_source"] == "estimated" and r.json()["done"] is False
    s = voice_studio.load_manifest("s1")["scenes"][0]
    assert s["timing_source"] == "estimated" and len(s["words"]) == 15
    assert 0 < s["words"][0]["end"] <= s["duration_sec"] and s["words"][-1]["end"] <= s["duration_sec"] + 1e-6


def test_partial_voice_keeps_station_running_without_merge(vs):
    c = client()
    h = H(vs)
    for i in (1, 2, 3):
        post(c, h, "voice", f"scene_{i}", mp3(7))
    mf = voice_studio.load_manifest("s1")
    assert len(mf["scenes"]) == 3 and mf["combined"] is None
    assert studio_state.state_of("s1", 4) == "running"
    assert [t["task_id"] for t in get_tasks(c, h, "voice").json()["tasks"]] == [f"scene_{i}" for i in range(4, 8)]


def test_voice_out_of_range_fails_station_4_for_the_owner_and_never_edits_the_text(vs):
    import stage3_generate
    vs.mp.setattr(stage3_generate, "rewrite_from_review", lambda *a, **k: pytest.fail("ممنوع تعديل النص تلقائياً"))
    before = vs.script.read_bytes()
    c = client()
    r = post_all_scenes(c, H(vs), [8] * 7)
    assert r.json()["complete"] and not r.json()["gate"]["ok"] and r.json()["gate"]["direction"] == "long"
    assert studio_state.state_of("s1", 4) == "failed"
    note = studio_state.load("s1")["stations"]["4"]["note"]
    assert "أطول" in note and "القرار عندك" in note
    assert vs.script.read_bytes() == before
    with pytest.raises(voice_studio.VoiceGateError):
        voice_studio.approve_voice(vs.script)


def test_voice_too_short_is_also_a_failed_gate(vs):
    c = client()
    post_all_scenes(c, H(vs), [5] * 7)
    assert studio_state.state_of("s1", 4) == "failed"
    assert "أقصر" in studio_state.load("s1")["stations"]["4"]["note"]


def test_voice_never_skips_can_start_for_station_4(vs):
    c = client()
    h = H(vs)
    vs.mp.setattr(studio_state, "can_start", lambda stem, n: (False, "محطة الشخصية ما اعتمدت"))
    assert get_tasks(c, h, "voice").status_code == 409
    r = post(c, h, "voice", "scene_1", mp3(6))
    assert r.status_code == 409 and "الشخصية" in r.json()["detail"]
    assert not (Path(config.LIBRARY_DIR) / "voice" / "s1" / "scene_01.mp3").exists()
    assert studio_state.state_of("s1", 4) == "not_started"


def test_voice_requires_a_reviewed_script(vs):
    vs.mp.setattr(review_loop, "is_cleared", lambda p: (False, "المراجعة فيها عائق"))
    c = client()
    assert get_tasks(c, H(vs), "voice").status_code == 409
    r = post(c, H(vs), "voice", "scene_1", mp3(6))
    assert r.status_code == 409 and "عائق" in r.json()["detail"]


def test_bad_voice_uploads_are_rejected_and_change_nothing(vs):
    c = client()
    h = H(vs)
    assert post(c, h, "voice", "scene_1", b"not audio at all, just text " * 20).status_code == 409
    assert post(c, h, "voice", "scene_1", b"").status_code == 409
    assert post(c, h, "voice", "scene_99", mp3(6)).status_code == 409
    assert post(c, h, "voice", "oops", mp3(6)).status_code == 409
    assert post(c, h, "voice", "", mp3(6)).status_code == 409
    assert post(c, h, "voice", "scene_1", mp3(6), site="bing").status_code == 409
    assert post(c, h, "bogus", "scene_1", mp3(6)).status_code == 409
    assert voice_studio.load_manifest("s1") is None and studio_state.state_of("s1", 4) == "not_started"
    leftovers = [p.name for p in (Path(config.LIBRARY_DIR) / "voice" / "s1").glob("*")] if (Path(config.LIBRARY_DIR) / "voice" / "s1").exists() else []
    assert leftovers == []


def test_voice_retry_replaces_one_scene_with_prompt_override_and_only_limits_the_run(vs):
    c = client()
    h = H(vs)
    post_all_scenes(c, h, [6, 7, 7, 7, 7, 7, 6])
    r = c.post(f"{API}/retry", json={"task_id": "scene_2", "kind": "voice", "prompt": "[هادئ] نص بديل للصق"})
    assert r.status_code == 200 and r.json()["task"]["retry"] is True and r.json()["task"]["prompt"] == "[هادئ] نص بديل للصق"
    assert [t["task_id"] for t in get_tasks(c, h, "voice").json()["tasks"]] == ["scene_2"]
    old = voice_studio.load_manifest("s1")["scenes"][1]["duration_sec"]
    r2 = post(c, h, "voice", "scene_2", mp3(8))
    assert r2.status_code == 200 and r2.json()["done"] is True
    assert voice_studio.load_manifest("s1")["scenes"][1]["duration_sec"] > old + 0.5
    assert get_tasks(c, h, "voice").json()["tasks"] == []
    # only: يقصر القائمة على task_ids محدّدة
    c.post(f"{API}/retry", json={"task_id": "scene_4", "kind": "voice"})
    c.post(f"{API}/retry", json={"task_id": "scene_5", "kind": "voice"})
    assert len(get_tasks(c, h, "voice").json()["tasks"]) == 2
    c.post(f"{API}/control", json={"only": ["scene_5"], "kind": "voice", "command": "run"})
    assert [t["task_id"] for t in get_tasks(c, h, "voice").json()["tasks"]] == ["scene_5"]
    fin = post(c, h, "voice", "scene_5", mp3(7)).json()
    assert fin["done"] is True                                       # خلص النطاق المطلوب مع إن scene_4 لسا معلّقة
    ctl = ext_bridge.control("s1")
    assert ctl["command"] == "idle" and ctl["only"] is None
    assert [t["task_id"] for t in get_tasks(c, h, "voice").json()["tasks"]] == ["scene_4"]


# ═══════════════════════════ الصور (محطة 7) ═══════════════════════════
def test_image_tasks_use_shot_id_as_task_id_and_keep_the_legacy_endpoints(bridge):
    c = client()
    h = H(bridge)
    legacy = c.get(f"{API}/queue", headers=h).json()["queue"]
    ts = get_tasks(c, h, "image").json()["tasks"]
    assert [t["task_id"] for t in ts] == [q["shot_id"] for q in legacy]
    t = ts[0]
    assert t["kind"] == "image" and t["shot_id"] == t["task_id"] and t["want"] == 2 and t["prompt"] and t["seconds"] > 0
    assert any(r["name"] == "front.png" for r in t["refs"]) and t["text"] == "" and t["emotion_tag"] == ""
    a = c.get(f"{API}/asset/{t['task_id']}/0", params={"kind": "image"}, headers=h)
    assert a.status_code == 200 and a.headers["content-type"].startswith("image/")
    assert c.get(f"{API}/asset/{t['task_id']}/9", params={"kind": "image"}, headers=h).status_code == 409
    r = post(c, h, "image", t["task_id"], png(), site="chatgpt", filename="x.png", mime="image/png")
    assert r.status_code == 200 and r.json()["size"] == [512, 768] and r.json()["done"] is False
    assert shot_of(t["task_id"])["image"]["candidates"][0]["provider"] == "extension:chatgpt"
    # توافق قديم: بدون kind وبـ shot_id
    old = c.post(f"{API}/result", headers=h, data={"shot_id": t["task_id"], "site": "gemini"},
                 files={"file": ("x.png", png(), "image/png")})
    assert old.status_code == 200 and len(shot_of(t["task_id"])["image"]["candidates"]) == 2


def test_image_only_retry_and_prompt_override(bridge):
    c = client()
    h = H(bridge)
    tl = timeline.load("s1")
    sh = tl["scenes"][0]["shots"][0]
    sh["image"] = {"candidates": [{"path": "img/a.png"}, {"path": "img/b.png"}], "chosen": None}
    timeline.save("s1", tl)
    sid = sh["id"]
    assert sid not in [t["task_id"] for t in get_tasks(c, h, "image").json()["tasks"]]
    r = c.post(f"{API}/retry", json={"task_id": sid, "kind": "image", "prompt": "برومبت جديد للصورة"})
    assert r.status_code == 200
    t = r.json()["task"]
    assert t["retry"] is True and t["want"] == 1 and t["prompt"] == "برومبت جديد للصورة" and t["refs"]
    assert sid in [x["task_id"] for x in get_tasks(c, h, "image").json()["tasks"]]
    assert post(c, h, "image", sid, png(), site="gemini", filename="x.png").status_code == 200
    assert len(shot_of(sid)["image"]["candidates"]) == 3
    assert sid not in [x["task_id"] for x in get_tasks(c, h, "image").json()["tasks"]]      # العلامة انمسحت بعد النتيجة
    # only
    other = timeline.load("s1")["scenes"][0]["shots"][1]["id"]
    c.post(f"{API}/control", json={"only": [other], "kind": "image", "command": "run"})
    assert [x["task_id"] for x in get_tasks(c, h, "image").json()["tasks"]] == [other]
    for _ in range(2):
        last = post(c, h, "image", other, png(), site="gemini", filename="x.png").json()
    assert last["done"] is True and ext_bridge.control("s1")["only"] is None and ext_bridge.control("s1")["command"] == "idle"
    assert studio_state.state_of("s1", 7) == "running"                # باقي لقطات برا النطاق


def test_retry_rejects_unknown_tasks_and_kinds(bridge):
    c = client()
    assert c.post(f"{API}/retry", json={"task_id": "s9c9", "kind": "image"}).status_code == 409
    assert c.post(f"{API}/retry", json={"task_id": "s1c1", "kind": "bogus"}).status_code == 409
    assert c.post(f"{API}/retry", json={"kind": "image"}).status_code == 409
    assert c.post(f"{API}/retry", json={"task_id": "req_009", "kind": "music"}).status_code == 409
    assert not Path(ext_tasks.overrides_path("s1")).exists() or ext_tasks._marks("s1") == {}


# ═══════════════════════════ التحريك (محطة 9) ═══════════════════════════
def test_video_tasks_need_station_8_approved_and_carry_exact_seconds_and_image_ref(ready):
    c = client()
    h = H(ready)
    ts = get_tasks(c, h, "video").json()["tasks"]
    assert [t["task_id"] for t in ts] == ready.ids
    for t in ts:
        assert t["kind"] == "video" and t["shot_id"] == t["task_id"] and t["seconds"] == sh_ms(t["task_id"]) / 1000
        assert t["refs"] and t["refs"][0]["index"] == 0 and "ثانية بالضبط" in t["prompt"] and motion.validate_prompt(t["prompt"]) == []
        assert t["site_hint"] == "flow"
    a = c.get(f"{API}/asset/{ts[0]['task_id']}/0", params={"kind": "video"}, headers=h)
    assert a.status_code == 200 and a.headers["content-type"].startswith("image/")
    assert c.get(f"{API}/asset/{ts[0]['task_id']}/1", params={"kind": "video"}, headers=h).status_code == 409
    # بدون kind بالطلب ← بياخد نوع التحكم الحالي
    c.post(f"{API}/control", json={"kind": "video"})
    assert c.get(f"{API}/asset/{ts[0]['task_id']}/0", headers=h).headers["content-type"].startswith("image/")
    studio_state.set_state("s1", 8, "awaiting_choice", "x")
    assert get_tasks(c, h, "video").status_code == 409
    r = post(c, h, "video", ready.ids[0], mp4(4), site="flow", filename="v.mp4", mime="video/mp4")
    assert r.status_code == 409 and shot_of(ready.ids[0]).get("motion_candidates") is None


def test_video_result_is_fitted_to_the_shot_duration_exactly_and_becomes_a_candidate(ready):
    c = client()
    h = H(ready)
    sid = ready.ids[0]
    r = post(c, h, "video", sid, mp4(4), site="flow", filename="v.mp4", mime="video/mp4")
    assert r.status_code == 200 and r.json()["fit"] == "trimmed" and r.json()["done"] is False
    sh = shot_of(sid)
    cand = sh["motion_candidates"][0]
    assert cand["model_id"] == "ext:flow" and cand["model_name"] == "Flow (الإضافة)" and cand["duration_ms"] == sh_ms(sid)
    assert cand["lipsync"] is False and ":\\" not in cand["clip"]
    clip = motion.abs_of("s1", cand["clip"])
    assert abs(motion.probe_duration(clip) * 1000 - sh_ms(sid)) <= motion.DURATION_EPS_MS
    assert studio_state.state_of("s1", 9) == "running"
    assert sid not in [t["task_id"] for t in get_tasks(c, h, "video").json()["tasks"]]
    # اختيارها بالمسار الموجود ← مدة الحركة تساوي مدة اللقطة والخط الزمني صالح
    out = motion.choose(ready.script, sid, cand["clip"])
    assert out["motion"]["duration_ms"] == sh_ms(sid) and timeline.validate(timeline.load("s1"))["ok"]


def test_all_videos_done_hands_station_9_to_the_owner(ready):
    c = client()
    h = H(ready)
    c.post(f"{API}/control", json={"kind": "video", "command": "run"})
    last = None
    for sid in ready.ids:
        last = post(c, h, "video", sid, mp4(4), site="flow", filename="v.mp4", mime="video/mp4").json()
    assert last["done"] is True and studio_state.state_of("s1", 9) == "awaiting_choice"
    assert ext_bridge.control("s1")["command"] == "idle"
    assert get_tasks(c, h, "video").json()["tasks"] == []
    # إعادة لقطة بعد ما صار عندها خيار
    r = c.post(f"{API}/retry", json={"task_id": ready.ids[1], "kind": "video", "prompt": "حركة بطيئة جداً"})
    assert r.status_code == 200 and r.json()["task"]["prompt"] == "حركة بطيئة جداً"
    post(c, h, "video", ready.ids[1], mp4(4), site="flow", filename="v.mp4", mime="video/mp4")
    sh = shot_of(ready.ids[1])
    assert len(sh["motion_candidates"]) == 2 and sh["motion_prompt"] == "حركة بطيئة جداً"


def test_video_stretch_within_limit_and_refusal_when_far_too_short(ready):
    c = client()
    h = H(ready)
    sid = ready.ids[0]
    secs = sh_ms(sid) / 1000
    r = post(c, h, "video", sid, mp4(round(secs * 0.9, 2)), site="flow", filename="v.mp4", mime="video/mp4")
    assert r.status_code == 200 and r.json()["fit"] == "stretched"
    bad = post(c, h, "video", ready.ids[1], mp4(0.5), site="flow", filename="v.mp4", mime="video/mp4")
    assert bad.status_code == 409 and "أقصر" in bad.json()["detail"]
    junk = post(c, h, "video", ready.ids[1], b"definitely not a video " * 30, site="flow", filename="v.mp4", mime="video/mp4")
    assert junk.status_code == 409
    assert post(c, h, "video", "s9c9", mp4(4), site="flow", filename="v.mp4").status_code == 409
    assert shot_of(ready.ids[1]).get("motion_candidates") is None
    clips = list(motion.clips_dir("s1").glob("*")) if motion.clips_dir("s1").exists() else []
    assert not [p for p in clips if "_raw" in p.name]                # ما بتضل ملفات خام


def test_shots_with_a_local_model_candidate_are_not_requested_unless_retried(ready):
    tl = timeline.load("s1")
    tl["scenes"][0]["shots"][0]["motion_candidates"] = [{"clip": "clips/x.mp4", "model_id": "mm_001"}]
    timeline.save("s1", tl)
    c = client()
    h = H(ready)
    sid = ready.ids[0]
    assert sid not in [t["task_id"] for t in get_tasks(c, h, "video").json()["tasks"]]
    c.post(f"{API}/retry", json={"task_id": sid, "kind": "video"})
    assert sid in [t["task_id"] for t in get_tasks(c, h, "video").json()["tasks"]]


# ═══════════════════════════ الآهات والموسيقى ═══════════════════════════
def test_requests_crud_validation_and_local_only(bridge):
    c = client()
    ext = client("8.8.8.8")
    body = {"kind": "ahat", "prompt": "تنهيدة ارتياح امرأة", "name": "تنهيدة", "mood": "warm", "seconds": 2}
    r = c.post(f"{API}/requests", json=body)
    assert r.status_code == 200 and r.json()["id"] == "req_001" and r.json()["status"] == "pending" and r.json()["seconds"] == 2.0
    m = c.post(f"{API}/requests", json={"kind": "music", "prompt": "بيانو هادئ دافئ", "name": "خلفية", "mood": "calm", "seconds": 45})
    assert m.json()["id"] == "req_002"
    st = c.get(f"{API}/status").json()
    assert [x["id"] for x in st["requests"]] == ["req_001", "req_002"] and st["kinds"]["ahat"] == 1 and st["kinds"]["music"] == 1
    for bad in ({"kind": "voice", "prompt": "x"}, {"kind": "ahat", "prompt": "  "}, {"kind": "ahat", "prompt": "x", "mood": "angry"},
                {"kind": "ahat", "prompt": "x", "seconds": 999}, {"kind": "music", "prompt": "x", "seconds": 1},
                {"kind": "music", "prompt": "x", "seconds": "abc"}, {"kind": "ahat", "prompt": "ي" * 1500}, {}):
        assert c.post(f"{API}/requests", json=bad).status_code == 409, bad
    assert ext.post(f"{API}/requests", json=body).status_code == 403
    assert ext.delete(f"{API}/requests/req_001").status_code == 403
    assert ext.post(f"{API}/retry", json={"task_id": "req_001", "kind": "ahat"}).status_code == 403
    assert c.delete(f"{API}/requests/req_001").status_code == 200
    assert c.delete(f"{API}/requests/req_001").status_code == 409
    assert [x["id"] for x in c.get(f"{API}/status").json()["requests"]] == ["req_002"]
    assert c.post(f"{API}/requests", json=body).json()["id"] == "req_003"       # الأرقام ما بتتكرر
    assert json.loads(ext_tasks.requests_path("s1").read_text(encoding="utf-8"))["requests"][0]["id"] == "req_002"


def test_music_prompt_always_demands_no_vocals_and_ahat_demands_clean_sfx(bridge):
    c = client()
    h = H(bridge)
    c.post(f"{API}/requests", json={"kind": "music", "prompt": "موسيقى دافئة بيانو.", "seconds": 40})
    c.post(f"{API}/requests", json={"kind": "music", "prompt": "upbeat song with singing and lyrics"})
    c.post(f"{API}/requests", json={"kind": "ahat", "prompt": "تنهيدة ارتياح", "seconds": 2})
    music = get_tasks(c, h, "music").json()["tasks"]
    ahat_t = get_tasks(c, h, "ahat").json()["tasks"]
    assert len(music) == 2 and len(ahat_t) == 1
    for t in music:
        assert "instrumental, no vocals, no lyrics — بلا غناء ولا كلام" in t["prompt"] and t["kind"] == "music" and t["site_hint"] == "flowmusic"
    assert music[0]["prompt"].startswith("موسيقى دافئة بيانو. instrumental") and music[0]["seconds"] == 40.0
    assert "clean, isolated sound effect, no music" in ahat_t[0]["prompt"] and ahat_t[0]["task_id"] == "req_003" and ahat_t[0]["site_hint"] == "elevenlabs"
    assert "instrumental" not in ahat_t[0]["prompt"] and "clean, isolated" not in music[0]["prompt"]


def test_ahat_and_music_arrive_unapproved_and_complete_their_requests(real_audio):
    c = client()
    h = H(real_audio)
    a = c.post(f"{API}/requests", json={"kind": "ahat", "prompt": "تنهيدة", "name": "تنهيدة ارتياح", "mood": "warm", "seconds": 2}).json()
    mu = c.post(f"{API}/requests", json={"kind": "music", "prompt": "بيانو هادئ", "name": "خلفية هادئة", "mood": "calm", "seconds": 20}).json()
    r = post(c, h, "ahat", a["id"], mp3(2), site="elevenlabs", filename="sfx.mp3")
    assert r.status_code == 200 and r.json()["approved"] is False and r.json()["done"] is True
    tr = ahat.get(r.json()["track_id"])
    assert tr["approved"] is False and tr["name"] == "تنهيدة ارتياح" and tr["mood"] == "warm" and tr["kind"] == "ahat"
    assert tr["source"] == "extension:elevenlabs" and tr["duration_sec"] > 1.5 and ahat.audio_path(tr["id"])
    m = post(c, h, "music", mu["id"], mp3(6), site="flowmusic", filename="m.webm", mime="audio/webm")
    assert m.status_code == 200 and ahat.get(m.json()["track_id"])["approved"] is False and ahat.get(m.json()["track_id"])["kind"] == "music"
    rows = {x["id"]: x for x in c.get(f"{API}/status").json()["requests"]}
    assert rows[a["id"]]["status"] == "done" and rows[a["id"]]["track_id"] == tr["id"] and rows[mu["id"]]["site"] == "flowmusic"
    assert get_tasks(c, h, "ahat").json()["tasks"] == [] and get_tasks(c, h, "music").json()["tasks"] == []
    assert ahat.suggest(timeline.load("s1"))["suggestions"] == []      # غير معتمدة ← ما بتتقترح للمونتاج
    # الطلب الخالص ما بيستقبل نتيجة تانية، لكن إعادة المحاولة بترجّعه معلّق
    assert post(c, h, "ahat", a["id"], mp3(2), site="elevenlabs").status_code == 409
    rt = c.post(f"{API}/retry", json={"task_id": a["id"], "kind": "ahat", "prompt": "تنهيدة أعمق"})
    assert rt.status_code == 200 and rt.json()["task"]["retry"] is True and rt.json()["task"]["prompt"].startswith("تنهيدة أعمق")
    r2 = post(c, h, "ahat", a["id"], mp3(2), site="elevenlabs")
    assert r2.status_code == 200 and r2.json()["track_id"] != tr["id"]
    assert len(ahat.list_all()) == 3


def test_bad_audio_for_a_request_is_rejected_and_the_request_stays_pending(real_audio):
    c = client()
    h = H(real_audio)
    a = c.post(f"{API}/requests", json={"kind": "ahat", "prompt": "تنهيدة", "seconds": 2}).json()
    assert post(c, h, "ahat", a["id"], b"garbage " * 100).status_code == 409
    assert post(c, h, "ahat", a["id"], b"").status_code == 409
    assert post(c, h, "ahat", "req_777", mp3(2)).status_code == 409
    assert post(c, h, "music", a["id"], mp3(2)).status_code == 409               # النوع ما بيطابق الطلب
    assert post(c, h, "ahat", a["id"], mp3(2), site="bing").status_code == 409
    assert ahat.list_all() == []
    assert c.get(f"{API}/status").json()["requests"][0]["status"] == "pending"


# ═══════════════════════════ التحكم: النوع، النمط، النطاق ═══════════════════════════
def test_control_accepts_kind_step_mode_only_and_rejects_bad_values(bridge):
    c = client()
    for bad in ({"kind": "bogus"}, {"step_mode": "fast_forward"}, {"only": "s1c1"}, {"only": [1, 2]}, {"only": ["x" * 80]},
                {"site": "bing"}, {"mode": "warp"}):
        assert c.post(f"{API}/control", json=bad).status_code == 409, bad
    r = c.post(f"{API}/control", json={"kind": "video", "step_mode": "one_by_one", "only": ["s1c1", "s1c2", "s1c1"], "site": "flow"}).json()
    assert r["kind"] == "video" and r["step_mode"] == "one_by_one" and r["only"] == ["s1c1", "s1c2"] and r["site"] == "flow"
    assert c.post(f"{API}/control", json={"command": "run"}).json()["only"] == ["s1c1", "s1c2"]     # ما بتنمسح لو ما انبعتت
    assert c.post(f"{API}/control", json={"only": []}).json()["only"] is None
    assert c.post(f"{API}/control", json={"only": ["a"]}).json()["only"] == ["a"]
    assert c.post(f"{API}/control", json={"only": None}).json()["only"] is None
    for s in ext_bridge.SITES:
        assert c.post(f"{API}/control", json={"site": s}).status_code == 200
    assert ext_bridge.SITES == ("gemini", "chatgpt", "aistudio", "flow", "flowmusic", "elevenlabs")
    assert c.post(f"{API}/control", json={"step_mode": "all"}).json()["step_mode"] == "all"


def test_one_by_one_pauses_for_review_after_each_successful_result(bridge):
    c = client()
    h = H(bridge)
    c.post(f"{API}/control", json={"command": "run", "step_mode": "one_by_one", "kind": "image"})
    # نتيجة فاشلة ما بتوقف
    assert post(c, h, "image", "s1c1", b"not an image", site="gemini", filename="x.png").status_code == 409
    assert ext_bridge.control("s1")["command"] == "run"
    assert post(c, h, "image", "s1c1", png(), site="gemini", filename="x.png").status_code == 200
    ctl = ext_bridge.control("s1")
    assert ctl["command"] == "pause" and ctl["stop_code"] == "review" and ctl["stop_reason"] == "راجع النتيجة ثم كمّل"
    assert c.get(f"{API}/control", headers=h).json()["command"] == "pause"
    assert ext_bridge.tail("s1", 3)[-1]["step"] == "review"
    resumed = c.post(f"{API}/control", json={"command": "run"}).json()
    assert resumed["command"] == "run" and resumed["stop_code"] is None and resumed["stop_reason"] is None
    # نمط «الكل مرة وحدة» ما بيوقف
    c.post(f"{API}/control", json={"step_mode": "all"})
    post(c, h, "image", "s1c1", png(), site="gemini", filename="x.png")
    assert ext_bridge.control("s1")["command"] == "run"


def test_one_by_one_never_overrides_a_real_stop_and_finishing_everything_goes_idle(bridge):
    c = client()
    h = H(bridge)
    c.post(f"{API}/control", json={"command": "run", "step_mode": "one_by_one"})
    c.post(f"{API}/stop", headers=h, json={"code": "verification", "reason": "تحقق", "position": {"shot_id": "s1c1"}})
    post(c, h, "image", "s1c1", png(), site="gemini", filename="x.png")
    assert ext_bridge.control("s1")["command"] == "stop" and ext_bridge.control("s1")["stop_code"] == "verification"
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    for sid in ids:
        for _ in range(2):
            last = post(c, h, "image", sid, png(), site="gemini", filename="x.png").json()
    assert last["done"] is True
    assert studio_state.state_of("s1", 7) == "awaiting_choice" and ext_bridge.control("s1")["command"] == "idle"


def test_one_by_one_also_pauses_after_voice_and_video(ready):
    c = client()
    h = H(ready)
    c.post(f"{API}/control", json={"command": "run", "step_mode": "one_by_one", "kind": "video"})
    post(c, h, "video", ready.ids[0], mp4(4), site="flow", filename="v.mp4", mime="video/mp4")
    assert ext_bridge.control("s1")["command"] == "pause" and ext_bridge.control("s1")["stop_code"] == "review"


# ═══════════════════════════ الحالة ═══════════════════════════
def test_status_adds_kinds_requests_sites_and_keeps_the_legacy_fields(bridge):
    c = client()
    st = c.get(f"{API}/status").json()
    assert set(st["kinds"]) == {"voice", "image", "video", "ahat", "music"}
    assert st["kinds"]["image"] == st["queue"] > 0 and st["next"] == "s1c1" and st["requests"] == []
    assert st["kinds"]["voice"] == 7                                    # الصوت الحالي من API ← مهام للإضافة
    assert "video" in st["blocked_kinds"] and st["kinds"]["video"] == 0     # المحطة 8 ما اعتمدت
    assert set(st["sites"]) == set(ext_bridge.SITES)
    fl = st["sites"]["flow"]
    assert set(fl["kinds"]) == {"video", "image"} and fl["verified"] is False and fl["adapter_version"] == 2
    assert st["control"]["step_mode"] == "all" and st["control"]["kind"] == "image" and st["control"]["only"] is None
    assert set(st) >= {"control", "queue", "next", "log", "modes", "mode_warning"}


def test_status_counts_voice_as_zero_with_a_reason_when_the_script_is_not_reviewed(bridge, monkeypatch):
    monkeypatch.setattr(review_loop, "is_cleared", lambda p: (False, "السيناريو ما انراجع"))
    st = client().get(f"{API}/status").json()
    assert st["kinds"]["voice"] == 0 and "ما انراجع" in st["blocked_kinds"]["voice"]


# ═══════════════════════════ التوكن والمحلي فقط ═══════════════════════════
def test_all_new_extension_endpoints_reject_missing_or_wrong_token(bridge):
    c = client()
    calls = [("get", f"{API}/tasks"), ("get", f"{API}/asset/s1c1/0"), ("post", f"{API}/result"),
             ("get", "/api/ext/config"), ("get", "/api/ext/version"), ("post", "/api/ext/selftest")]
    for m, u in calls:
        assert getattr(c, m)(u).status_code == 401, u
        assert getattr(c, m)(u, headers={"X-VP-Ext-Token": "wrong"}).status_code == 401, u
    # حتى مع ملف وحقول صالحة، بلا توكن مرفوض
    r = c.post(f"{API}/result", data={"task_id": "scene_1", "kind": "voice", "site": "elevenlabs"},
               files={"file": ("x.mp3", mp3(6), "audio/mpeg")})
    assert r.status_code == 401


def test_studio_ui_endpoints_are_local_only(bridge):
    ext = client("8.8.8.8")
    assert ext.put("/api/ext/config", json={"sites": {"flow": {"verified": True}}}).status_code == 403
    assert ext.get("/api/ext/selftest").status_code == 403
    assert ext.get("/api/ext/download").status_code == 403
    assert ext.post(f"{API}/requests", json={"kind": "ahat", "prompt": "x"}).status_code == 403
    loc = client()
    assert loc.get("/api/ext/selftest").status_code == 200 and loc.get("/api/ext/download").status_code == 200
    # التوكن بيفتح نقاط الإضافة حتى من عنوان خارجي (هي مش محلية بالتصميم)
    assert ext.get("/api/ext/version", headers=H(bridge)).status_code == 200


# ═══════════════════════════ إعداد المحوّلات ═══════════════════════════
def test_defaults_cover_six_sites_with_contract_kinds_unverified_and_selftest(env):
    cfg = ext_config.load()
    assert cfg["version"] == ext_config.DEFAULTS_VERSION == 3 and set(cfg["sites"]) == set(ext_bridge.SITES)
    want = {"elevenlabs": {"voice", "ahat"}, "chatgpt": {"image"}, "gemini": {"image"}, "aistudio": {"image"},
            "flow": {"video", "image"}, "flowmusic": {"music"}}
    for name, s in cfg["sites"].items():
        assert set(s["kinds"]) == want[name] and s["verified"] is False and s["adapter_version"] == (3 if name == "chatgpt" else 2) and s["label"]
        assert s["selftest"]["composer"] and s["newUrl"].startswith("https://") and s["hosts"]
        ext_config.validate_site(name, s)
    flow_video = cfg["sites"]["flow"]["kinds"]["video"]
    fsteps = flow_video["steps"]
    assert [x["do"] for x in fsteps if x["do"] != "click"] == ["attach", "type"] and fsteps[-1]["do"] == "click" and flow_video["result"]["type"] == "video"
    assert next(x for x in fsteps if x["do"] == "type")["text"] == "{prompt}" and flow_video["timeoutSec"] == 900
    assert cfg["sites"]["flowmusic"]["kinds"]["music"]["result"]["type"] == "audio"
    for s in cfg["sites"].values():                                    # ما في محدّد لحقول كلمات السر
        assert "password" not in json.dumps(s).lower()
    assert any("{seconds}" in st.get("text", "") for st in cfg["sites"]["elevenlabs"]["kinds"]["ahat"]["steps"])


def test_config_patch_deep_merges_bumps_version_and_persists(env):
    c = client()
    r = c.put("/api/ext/config", json={"sites": {"flow": {"verified": True, "adapter_version": 2,
                                                          "kinds": {"video": {"timeoutSec": 1200}}}}})
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["version"] == ext_config.DEFAULTS_VERSION + 1
    fv = cfg["sites"]["flow"]
    assert fv["verified"] is True and fv["adapter_version"] == 2 and fv["kinds"]["video"]["timeoutSec"] == 1200
    assert len(fv["kinds"]["video"]["steps"]) == len(ext_config.DEFAULTS["sites"]["flow"]["kinds"]["video"]["steps"]) and "image" in fv["kinds"]                  # الباقي ما انمسح
    assert cfg["sites"]["gemini"]["verified"] is False
    new_steps = [{"do": "type", "sel": ["textarea"], "text": "{prompt}"}, {"do": "wait", "ms": 500},
                 {"do": "click", "sel": ["button.go"], "optional": False}]
    c2 = c.put("/api/ext/config", json={"sites": {"flow": {"kinds": {"video": {"steps": new_steps}}}}}).json()
    assert c2["version"] == ext_config.DEFAULTS_VERSION + 2 and c2["sites"]["flow"]["kinds"]["video"]["steps"] == new_steps   # القوائم بتستبدل
    assert c2["sites"]["flow"]["kinds"]["video"]["timeoutSec"] == 1200 and c2["sites"]["flow"]["verified"] is True
    on_disk = json.loads(ext_config.adapters_path().read_text(encoding="utf-8"))
    assert on_disk["version"] == ext_config.DEFAULTS_VERSION + 2 and set(on_disk["sites"]) == {"flow"}                          # بنخزّن التعديل بس
    assert ext_config.load() == c2


def test_config_served_to_the_extension_with_token(bridge):
    c = client()
    c.put("/api/ext/config", json={"sites": {"chatgpt": {"adapter_version": 7}}})
    r = c.get("/api/ext/config", headers=H(bridge))
    assert r.status_code == 200 and r.json()["version"] == ext_config.DEFAULTS_VERSION + 1 and r.json()["sites"]["chatgpt"]["adapter_version"] == 7


def test_config_none_removes_a_kind_and_keeps_removal_over_defaults(env):
    c = client()
    r = c.put("/api/ext/config", json={"sites": {"flow": {"kinds": {"image": None}}}}).json()
    assert set(r["sites"]["flow"]["kinds"]) == {"video"}
    assert set(ext_config.load()["sites"]["flow"]["kinds"]) == {"video"}
    back = c.put("/api/ext/config", json={"sites": {"flow": {"kinds": {"image": ext_config.DEFAULTS["sites"]["flow"]["kinds"]["image"]}}}}).json()
    assert set(back["sites"]["flow"]["kinds"]) == {"video", "image"}


def good_kind(**over):
    k = {"url": "https://labs.google/fx/tools/flow", "steps": [{"do": "type", "sel": ["textarea"], "text": "{prompt}"}],
         "result": {"type": "video", "sel": ["video"]}, "timeoutSec": 100}
    k.update(over)
    return k


@pytest.mark.parametrize("patch", [
    {"sites": {"bing": {"verified": True}}},                                          # موقع غير معروف
    {"sites": {"flow": {"kinds": {"podcast": good_kind()}}}},                           # نوع غير معروف
    {"sites": {"flow": {"colour": "red"}}},                                             # حقل غير معروف بالموقع
    {"sites": {"flow": {"kinds": {"video": {"speed": 3}}}}},                            # حقل غير معروف بالنوع
    {"sites": {"flow": {"kinds": {"video": {"steps": [{"do": "hack", "sel": ["a"]}]}}}}},
    {"sites": {"flow": {"kinds": {"video": {"steps": [{"do": "click", "sel": []}]}}}}},
    {"sites": {"flow": {"kinds": {"video": {"steps": [{"do": "click", "sel": ["input[type=password]"]}]}}}}},
    {"sites": {"flow": {"kinds": {"video": {"steps": [{"do": "type", "sel": ["textarea"]}]}}}}},   # type بلا text
    {"sites": {"flow": {"kinds": {"video": {"steps": [{"do": "wait", "ms": -5}]}}}}},
    {"sites": {"flow": {"kinds": {"video": {"url": "http://labs.google/fx"}}}}},                   # http
    {"sites": {"flow": {"kinds": {"video": {"url": "https://evil.example.com/x"}}}}},              # مضيف غريب
    {"sites": {"flow": {"newUrl": "https://evil.example.com/"}}},
    {"sites": {"flow": {"hosts": ["labs.google/path"]}}},
    {"sites": {"flow": {"kinds": {"video": {"result": {"type": "image", "sel": ["img"]}}}}}},      # نتيجة ما بتطابق النوع
    {"sites": {"flow": {"kinds": {"video": {"result": {"type": "gif", "sel": ["img"]}}}}}},
    {"sites": {"flow": {"kinds": {"video": {"timeoutSec": 99999}}}}},
    {"sites": {"flow": {"kinds": {"video": {"timeoutSec": "soon"}}}}},
    {"sites": {"flow": {"verified": "yes"}}},
    {"sites": {"flow": {"adapter_version": -1}}},
    {"sites": {"flow": {"selftest": {"composer": "textarea"}}}},
    {"sites": {}}, {"nothing": 1}, {"sites": {"flow": "x"}}, {"sites": {"flow": {"label": None}}},
])
def test_config_rejects_bad_patches_and_changes_nothing(env, patch):
    c = client()
    before = ext_config.load()
    r = c.put("/api/ext/config", json=patch)
    assert r.status_code == 409, r.text
    assert any("؀" <= ch <= "ۿ" for ch in r.json()["detail"])                       # الرسالة عربية
    assert ext_config.load() == before and not ext_config.adapters_path().exists()


def test_config_hand_edited_garbage_never_breaks_loading(env):
    p = ext_config.adapters_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert ext_config.load()["version"] == ext_config.DEFAULTS_VERSION and set(ext_config.load()["sites"]) == set(ext_bridge.SITES)
    p.write_text(json.dumps({"version": 5, "sites": {"bing": {"x": 1}, "flow": {"verified": True}}}), encoding="utf-8")
    cfg = ext_config.load()
    assert cfg["version"] == 5 and "bing" not in cfg["sites"] and cfg["sites"]["flow"]["verified"] is True


# ═══════════════════════════ الإصدار والتنزيل ═══════════════════════════
def test_version_matches_the_manifest_and_download_zip_is_named_after_it(bridge):
    c = client()
    ver = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]
    v = c.get("/api/ext/version", headers=H(bridge)).json()
    assert v == {"latest": ver, "download_url": "/api/ext/download"}
    r = c.get("/api/ext/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert f'filename="zakiai-extension-{ver}.zip"' in r.headers["content-disposition"]
    import io
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "manifest.json" in names and "background.js" in names and "content.js" in names and any(n.startswith("lib/") for n in names)
    assert z.testzip() is None
    for n in names:
        assert not n.startswith(("/", "\\")) and ".." not in n.split("/") and ":" not in n and "\\" not in n
        low = Path(n).name.lower()
        assert not low.startswith("tmp") and "__pycache__" not in n and not low.endswith((".pyc", ".zip", ".log"))
    assert json.loads(z.read("manifest.json"))["version"] == ver


def test_download_excludes_temp_test_hidden_files_and_symlinks(bridge, monkeypatch, tmp_path):
    fake = tmp_path / "ext_src"
    (fake / "lib").mkdir(parents=True)
    (fake / "__pycache__").mkdir()
    (fake / ".git").mkdir()
    (fake / "manifest.json").write_text(json.dumps({"version": "9.8.7-beta"}), encoding="utf-8")
    (fake / "background.js").write_text("// ok", encoding="utf-8")
    (fake / "lib" / "pace.js").write_text("// ok", encoding="utf-8")
    for junk in ("tmpab12cd.js", "test_x.js", "pace.test.js", "old.zip", "notes.log", ".env", "__pycache__/x.pyc", ".git/config"):
        (fake / junk).write_text("junk", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")
    try:
        (fake / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    monkeypatch.setattr(ext_bridge, "extension_dir", lambda: fake)
    name, data = ext_bridge.build_zip()
    assert name == "zakiai-extension-9.8.7-beta.zip"
    import io
    names = sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == ["background.js", "lib/pace.js", "manifest.json"]
    assert b"top secret" not in data
    # نسخة بلا manifest ← رسالة عربية مش انهيار
    (fake / "manifest.json").unlink()
    r = client().get("/api/ext/download")
    assert r.status_code == 409 and "manifest" in r.json()["detail"]


def test_version_reports_an_arabic_error_when_manifest_is_missing(bridge, monkeypatch, tmp_path):
    monkeypatch.setattr(ext_bridge, "extension_dir", lambda: tmp_path / "nowhere")
    r = client().get("/api/ext/version", headers=H(bridge))
    assert r.status_code == 409 and any("؀" <= ch <= "ۿ" for ch in r.json()["detail"])


# ═══════════════════════════ الفحص الذاتي ═══════════════════════════
def test_selftest_is_stored_per_site_and_kind_and_listed_locally(bridge):
    c = client()
    h = H(bridge)
    ok = c.post("/api/ext/selftest", headers=h, json={"site": "flow", "kind": "video", "ok": False, "adapter_version": 1,
                                                       "missing": ["composer", "button.generate"]})
    assert ok.status_code == 200 and ok.json()["missing"] == ["composer", "button.generate"] and ok.json()["checked_at"]
    c.post("/api/ext/selftest", headers=h, json={"site": "elevenlabs", "ok": True, "adapter_version": 1, "missing": []})
    c.post("/api/ext/selftest", headers=h, json={"site": "flow", "kind": "video", "ok": True, "adapter_version": 2})
    res = c.get("/api/ext/selftest").json()["results"]
    assert [(r["site"], r["kind"], r["ok"], r["adapter_version"]) for r in res] == [("elevenlabs", None, True, 1), ("flow", "video", True, 2)]
    assert set(res[0]) == {"site", "kind", "ok", "adapter_version", "missing", "checked_at"}


@pytest.mark.parametrize("body", [
    {"site": "bing", "ok": True, "adapter_version": 1, "missing": []},
    {"site": "flow", "kind": "podcast", "ok": True, "adapter_version": 1, "missing": []},
    {"site": "flow", "ok": "yes", "adapter_version": 1, "missing": []},
    {"site": "flow", "ok": True, "adapter_version": "x", "missing": []},
    {"site": "flow", "ok": True, "adapter_version": 1, "missing": "composer"},
    {"site": "flow", "ok": True, "adapter_version": 1, "missing": [1, 2]},
    {"site": "flow", "ok": True, "adapter_version": 1, "missing": ["x"] * 80},
    {},
])
def test_selftest_rejects_bad_reports(bridge, body):
    c = client()
    assert c.post("/api/ext/selftest", headers=H(bridge), json=body).status_code == 409
    assert c.get("/api/ext/selftest").json()["results"] == []


# ═══════════════════════════ لا مفاتيح بالملفات ═══════════════════════════
def test_token_never_lands_in_any_ext_file(ready):
    c = client()
    h = H(ready)
    c.post(f"{API}/requests", json={"kind": "ahat", "prompt": "x"})
    c.post(f"{API}/retry", json={"task_id": ready.ids[0], "kind": "video"})
    c.put("/api/ext/config", json={"sites": {"flow": {"verified": True}}})
    c.post("/api/ext/selftest", headers=h, json={"site": "flow", "ok": True, "adapter_version": 1, "missing": []})
    tok = ext_bridge.token()
    for f in Path(ready.env.root).rglob("*"):
        if f.is_file() and f.suffix in (".json", ".jsonl", ".txt", ".log"):
            assert tok not in f.read_text(encoding="utf-8", errors="ignore"), f


# ───────── ربط كلمات النص بتوقيت التفريغ الصوتي (Whisper المحلي) ─────────
def test_align_to_script_keeps_script_words_with_asr_times_and_never_overlaps():
    import ext_tasks
    asr = [{"text": "بدون", "start": 0.1, "end": 0.5}, {"text": "الم", "start": 0.5, "end": 0.7},
           {"text": "ألم", "start": 0.7, "end": 1.0}, {"text": "خلال", "start": 1.2, "end": 1.6}]
    out = ext_tasks.align_to_script(asr, "بدون ألم خلال دقائق", 2.0)
    assert [w["text"] for w in out] == ["بدون", "ألم", "خلال", "دقائق"]       # النص الأصلي هو اللي بيظهر
    assert out[0]["start"] == 0.1 and out[-1]["end"] <= 2.0
    assert all(a["end"] <= b["start"] + 1e-9 and a["start"] <= a["end"] for a, b in zip(out, out[1:]))
    assert ext_tasks.align_to_script([], "كلمة", 1.0) == [] and ext_tasks.align_to_script(asr, "", 1.0) == []


def test_align_to_script_clamps_times_to_audio_duration():
    import ext_tasks
    asr = [{"text": "a", "start": 0.0, "end": 5.0}, {"text": "b", "start": 5.0, "end": 9.0}]
    out = ext_tasks.align_to_script(asr, "واحد اثنين", 3.0)
    assert out[-1]["end"] <= 3.0 and out[0]["start"] >= 0


def test_local_whisper_falls_back_to_cpu_when_cuda_libraries_are_missing(monkeypatch):
    import stt
    calls = []

    class W:                                    # كلمة وهمية بتوقيت
        word, start, end = " مرحبا", 0.0, 0.5

    class Seg:
        start, end, text, words = 0.0, 0.5, " مرحبا", [W()]

    class Info:
        language, language_probability = "ar", 0.99

    class Model:
        def __init__(self, cpu): self.cpu = cpu
        def transcribe(self, *a, **k):
            if not self.cpu:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return iter([Seg()]), Info()

    def fake_model(name, force_cpu=False):
        calls.append(force_cpu)
        return Model(force_cpu)

    monkeypatch.setattr(stt, "_local_model", fake_model)
    monkeypatch.setattr(stt.config, "WHISPER_DEVICE", "cuda")
    out = stt._local_whisper({"model": "large-v3", "language": "ar"}, Path("x.wav"))
    assert calls == [False, True]                                       # جرّب الكرت ثم المعالج
    assert out["words"] == [{"text": "مرحبا", "start": 0.0, "end": 0.5}] and out["full_text"] == "مرحبا"



def test_an_extension_upload_never_overwrites_a_request_that_changed_while_it_was_converting(real_audio, monkeypatch):
    c = client()
    h = H(real_audio)
    a = c.post(f"{API}/requests", json={"kind": "ahat", "prompt": "تنهيدة", "name": "تنهيدة", "mood": "warm", "seconds": 2}).json()
    real = ext_tasks._convert_audio

    def convert_while_the_owner_starts_a_model_generation(data, filename, out):
        ext_tasks.mark_local("s1", a["id"])                                  # أثناء ما الإضافة بتحوّل الصوت: بلّش توليد بنموذج المكتبة
        return real(data, filename, out)
    monkeypatch.setattr(ext_tasks, "_convert_audio", convert_while_the_owner_starts_a_model_generation)
    r = post(c, h, "ahat", a["id"], mp3(2), site="elevenlabs")
    assert r.status_code == 409 and "اتغيّر أثناء الرفع" in r.json()["detail"]
    row = ext_tasks.list_requests("s1")[0]
    assert row["status"] == "local" and row.get("track_id") is None             # بلا ما انكتب فوق حالة الطلب
    assert len(ahat.list_all()) == 1 and ahat.list_all()[0]["approved"] is False   # والمقطع دخل المكتبة غير معتمد
    monkeypatch.setattr(ext_tasks, "_convert_audio", real)
    again = post(c, h, "ahat", a["id"], mp3(2), site="elevenlabs")
    assert again.status_code == 409 and "عم يتولّد" in again.json()["detail"]    # وهو شغّال: الرفع التاني مرفوض بوضوح
