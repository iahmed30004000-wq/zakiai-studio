"""استوديو الإنتاج — المحطة ١٠: الآهات والمونتاج والتصدير."""

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_images as ti  # noqa: E402
import test_studio_motion as tm  # noqa: E402
from test_studio_images import stage  # noqa: E402,F401
from test_studio_motion import ready  # noqa: E402,F401

import ahat  # noqa: E402
import config  # noqa: E402
import image_studio as ims  # noqa: E402
import montage  # noqa: E402
import motion  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")
SMALL = (108, 192)


def sine(path, seconds=3, freq=440):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", str(path)],
                   capture_output=True, check=True)
    return path.read_bytes()


@pytest.fixture
def animated(ready, tmp_path):
    """كل اللقطات محرّكة ومعتمدة (محطة ٩) + صوت حقيقي مدمج بمدة الخط الزمني."""
    m = motion.upsert_model(tm.model(max_sec=6))
    motion.run_all(ready.script, m["id"], 1, log=lambda *_: None)
    for sid in ready.ids:
        motion.choose(ready.script, sid, ims._shot(timeline.load("s1"), sid)[1]["motion_candidates"][0]["clip"])
    motion.approve(ready.script)
    man = json.loads((ready.env.lib / "voice" / "s1" / "voice.json").read_text(encoding="utf-8"))
    sine(ready.env.lib / man["combined"]["path"], 47)
    ready.tmp = tmp_path
    return ready


# ───────────────────────── مكتبة الآهات ─────────────────────────
def test_ahat_add_validates_and_measures_duration(env, tmp_path):
    data = sine(tmp_path / "a.wav", 4)
    t = ahat.add("آهة هادئة", "calm", "a.wav", data)
    assert t["id"] == "ah_001" and abs(t["duration_sec"] - 4) < 0.2 and not t["approved"]
    for args in (("", "calm", "a.wav", data), ("x", "loud", "a.wav", data), ("x", "calm", "a.exe", data),
                 ("x", "calm", "a.wav", b"tiny"), ("x", "calm", "a.wav", b"z" * 900)):
        with pytest.raises(ahat.AhatError):
            ahat.add(*args)
    assert ahat.add("ثانية", "warm", "b.wav", data)["id"] == "ah_002"


def test_ahat_needs_explicit_heard_confirmation_and_can_be_revoked(env, tmp_path):
    t = ahat.add("أ", "calm", "a.wav", sine(tmp_path / "a.wav"))
    with pytest.raises(ahat.AhatError):
        ahat.approve(t["id"], False)
    assert ahat.approve(t["id"], True)["approved_at"]
    assert not ahat.revoke(t["id"])["approved"]
    ahat.delete(t["id"])
    assert ahat.get(t["id"]) is None
    with pytest.raises(ahat.AhatError):
        ahat.delete("bad")


def test_script_mood_from_scene_emotions_and_suggestions_only_approved(env, tmp_path):
    tl = {"scenes": [{"emotion": "frustration"}, {"emotion": "pain / tired"}, {"emotion": "relief"}, {"emotion": "gibberish"}],
          "voice": {"duration_ms": 47000}}
    assert ahat.script_mood(tl) == "tense"
    assert ahat.script_mood({"scenes": [{"emotion": "zzz"}]}) is None
    data = sine(tmp_path / "a.wav", 60)
    tense = ahat.add("توتر", "tense", "t.wav", data)
    calm = ahat.add("هدوء", "calm", "c.wav", sine(tmp_path / "c.wav", 10))
    anyt = ahat.add("أي", "any", "y.wav", data)
    ahat.add("غير معتمد", "tense", "u.wav", data)
    for t in (tense, calm, anyt):
        ahat.approve(t["id"], True)
    r = ahat.suggest(tl)
    ids = [s["track"]["id"] for s in r["suggestions"]]
    assert ids[0] == tense["id"] and ids[-1] == calm["id"] and "ah_004" not in ids
    assert r["mood"] == "tense" and r["approved_count"] == 3 and r["total"] == 4


# ───────────────────────── الترجمة ─────────────────────────
def test_cues_cover_all_words_in_order_within_bounds(animated):
    tl = timeline.load("s1")
    cues = montage.build_cues(tl)
    assert cues and all(c["text"].strip() for c in cues)
    joined = " ".join(c["text"] for c in cues).split()
    assert joined == [w["text"] for w in tl["words"]]
    total = tl["voice"]["duration_ms"]
    prev_end = -1
    for c in cues:
        assert 0 <= c["start_ms"] < c["end_ms"] <= total and c["end_ms"] - c["start_ms"] >= 300
        assert len(c["text"].split()) <= 5 and c["start_ms"] >= prev_end - 1
        prev_end = c["end_ms"]


def test_ass_file_has_safe_zone_and_dialogues(animated, tmp_path):
    tl = timeline.load("s1")
    cues = montage.build_cues(tl)
    montage.write_ass(cues, tmp_path / "c.ass", (1080, 1920))
    ass = (tmp_path / "c.ass").read_text(encoding="utf-8")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert ass.count("Dialogue:") == len(cues)
    style = [l for l in ass.splitlines() if l.startswith("Style:")][0].split(",")
    assert int(style[21]) == round(1920 * montage.SAFE_BOTTOM)             # MarginV: منطقة آمنة من الأسفل
    assert int(style[18]) == 2                                             # محاذاة أسفل الوسط
    assert montage._ts(3723450) == "1:02:03.45"


# ───────────────────────── العرض والتصدير ─────────────────────────
def test_render_blocked_until_motion_station_approved(ready):
    with pytest.raises(montage.MontageError):
        montage.render(ready.script, "preview", SMALL, log=lambda *_: None)


def test_preview_matches_spec_and_final_needs_a_preview_first(animated):
    tl0 = timeline.load("s1")
    with pytest.raises(montage.MontageError) as e:
        montage.render(animated.script, "final", SMALL, log=lambda *_: None)
    assert "معاينة" in str(e.value)
    r = montage.render(animated.script, "preview", SMALL, log=lambda *_: None)
    info = r["info"]
    assert (info["width"], info["height"]) == SMALL and info["has_audio"] and abs(info["fps"] - 30) < 0.5
    assert abs(info["duration_ms"] - tl0["voice"]["duration_ms"]) <= montage.DURATION_EPS_MS
    tl = timeline.load("s1")
    assert tl["render"]["preview"]["captions"] == r["cues"] and tl["captions"]["safe_bottom"] == montage.SAFE_BOTTOM
    assert ":\\" not in json.dumps(tl["render"])
    assert studio_state.state_of("s1", 10) == "awaiting_choice"


def test_final_export_is_named_by_script_id_and_can_be_redone_without_regeneration(animated):
    montage.render(animated.script, "preview", SMALL, log=lambda *_: None)
    before = json.dumps(timeline.load("s1")["scenes"], sort_keys=True)
    r = montage.render(animated.script, "final", SMALL, log=lambda *_: None)
    assert r["file"] == "exports/VP-testp-1-v1.mp4"
    out = animated.env.lib / r["file"]
    assert out.exists() and studio_state.state_of("s1", 10) == "approved"
    r2 = montage.render(animated.script, "final", SMALL, log=lambda *_: None)      # إعادة تصدير
    assert r2["file"] == r["file"]
    assert json.dumps(timeline.load("s1")["scenes"], sort_keys=True) == before      # ما تغيّر شي بالخط الزمني
    assert not list(animated.env.lib.glob("**/*_raw.mp4"))


def test_default_sizes_are_1080x1920_final_and_lower_preview():
    assert montage.FINAL_SIZE == (1080, 1920) and montage.PREVIEW_SIZE[0] * 2 == 1080 and montage.FPS == 30


def test_ambience_requires_owner_approved_track_and_is_ducked_under_voice(animated, tmp_path):
    t = ahat.add("هدوء", "calm", "c.wav", sine(tmp_path / "c.wav", 10))
    with pytest.raises(montage.MontageError):
        montage.choose_ahat(animated.script, t["id"])                             # مش معتمدة
    with pytest.raises(montage.MontageError):
        montage.choose_ahat(animated.script, "ah_099")
    ahat.approve(t["id"], True)
    assert montage.choose_ahat(animated.script, t["id"])["duck_db"] == -14
    cmd = montage.build_command([tmp_path / "a.mp4"], tmp_path / "v.mp3", tmp_path / "ah.wav", tmp_path / "o.mp4",
                                SMALL, 47.0, True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in graph and "loudnorm=I=-16" in graph and "aloop" in graph and "afade" in graph
    no_amb = montage.build_command([tmp_path / "a.mp4"], tmp_path / "v.mp3", None, tmp_path / "o.mp4", SMALL, 47.0, True)
    g2 = no_amb[no_amb.index("-filter_complex") + 1]
    assert "sidechaincompress" not in g2 and "loudnorm=I=-16" in g2               # بلا آهات = بلا مسار موسيقي


def test_render_with_ahat_and_changing_it_invalidates_previous_renders(animated, tmp_path):
    t = ahat.add("هدوء", "calm", "c.wav", sine(tmp_path / "c.wav", 10))
    ahat.approve(t["id"], True)
    montage.choose_ahat(animated.script, t["id"])
    r = montage.render(animated.script, "preview", SMALL, log=lambda *_: None)
    assert r["info"]["has_audio"] and timeline.load("s1")["render"]["preview"]["ahat"] is True
    montage.render(animated.script, "final", SMALL, log=lambda *_: None)
    assert studio_state.state_of("s1", 10) == "approved"
    montage.choose_ahat(animated.script, None)                                   # شيل الآهات
    tl = timeline.load("s1")
    assert tl["ambience"] is None and "render" not in tl
    assert studio_state.state_of("s1", 10) == "awaiting_choice"
    with pytest.raises(montage.MontageError):
        montage.render(animated.script, "final", SMALL, log=lambda *_: None)      # لازم معاينة جديدة


def test_render_refuses_ahat_revoked_after_selection(animated, tmp_path):
    t = ahat.add("هدوء", "calm", "c.wav", sine(tmp_path / "c.wav", 10))
    ahat.approve(t["id"], True)
    montage.choose_ahat(animated.script, t["id"])
    ahat.revoke(t["id"])
    with pytest.raises(montage.MontageError) as e:
        montage.render(animated.script, "preview", SMALL, log=lambda *_: None)
    assert "معتمدة بالسمع" in str(e.value)


# ───────────────────────── API ─────────────────────────
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_montage
    app = FastAPI()
    app.include_router(routes_montage.router)
    return TestClient(app)


def test_api_ahat_library_flow(env, tmp_path):
    c = client()
    data = sine(tmp_path / "a.wav", 5)
    r = c.post("/api/ahat", files={"file": ("a.wav", data, "audio/wav")}, data={"name": "هدوء", "mood": "calm"})
    assert r.status_code == 200 and r.json()["id"] == "ah_001"
    assert c.post("/api/ahat", files={"file": ("a.exe", data, "audio/wav")}, data={"name": "x", "mood": "calm"}).status_code == 409
    assert c.post("/api/ahat/ah_001/approve", json={"heard": False}).status_code == 409
    assert c.post("/api/ahat/ah_001/approve", json={"heard": True}).json()["approved"]
    assert c.get("/api/ahat/ah_001/audio").status_code == 200
    assert c.get("/api/ahat/bad/audio").status_code == 400
    assert len(c.get("/api/ahat").json()["tracks"]) == 1
    assert c.delete("/api/ahat/ah_001").status_code == 200


def test_api_montage_flow(animated, tmp_path, monkeypatch):
    c = client()
    info = c.get("/api/studio/s1.json/montage/info").json()
    assert info["clips_ready"] and info["cues"] > 0 and not info["can_final"] and info["sizes"]["final"] == [1080, 1920]
    assert c.post("/api/studio/s1.json/montage/render?mode=bogus").status_code == 400
    assert c.post("/api/studio/s1.json/montage/render?mode=final").status_code == 409          # بلا معاينة
    assert c.post("/api/studio/s1.json/montage/render?mode=preview").status_code == 200
    assert animated.env.jobs[-1]["cmd"][:2] == ["montage.py", "preview"]
    assert c.get("/api/studio/s1.json/render/preview").status_code == 404
    montage.render(animated.script, "preview", SMALL, log=lambda *_: None)
    assert c.get("/api/studio/s1.json/render/preview").status_code == 200
    assert c.get("/api/studio/s1.json/render/../final").status_code in (404, 400)
    assert c.post("/api/studio/s1.json/montage/render?mode=final").status_code == 200
    assert c.post("/api/studio/s1.json/ambience", json={"track_id": "ah_009"}).status_code == 409
    assert c.post("/api/studio/s1.json/ambience", json={"track_id": None}).status_code == 200
