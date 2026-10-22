"""تسجيل صوتك بمحطة الصوت بالمهمة الموجّهة (voice_upload.ingest_guided + POST /voice/upload): نفس شروط الإضافة، نفس شكل مانيفست أي مزوّد،
بوابة المدة 45–50، والاعتماد بالزر المعتاد — بتفريغ وهمي."""

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_ext_tasks import vs  # noqa: E402,F401
import test_studio_voice_timeline as tv  # noqa: E402

import config  # noqa: E402
import generate_voice  # noqa: E402
import review_loop  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import voice_studio  # noqa: E402
import voice_upload as vu  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")
QUIET = lambda m: None          # noqa: E731


def wav(path, seconds, rate=16000):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}:sample_rate={rate}", str(path)], check=True, capture_output=True)
    return Path(path)


def asr_for(script, per_word=0.4, gap=1.2, lead=0.5, skip=(), junk=False):
    """كلمات مفرّغة بتطابق نص السيناريو مشهد مشهد (بدون المشاهد المتخطّاة). junk=True: كلام مختلف تماماً."""
    t, words = lead, []
    for sc in script["scenes"]:
        if sc["scene_number"] in skip:
            continue
        toks = sc["voiceover"].split()
        for i, tok in enumerate(toks):
            words.append({"text": f"زززز{i}" if junk else tok, "start": round(t, 3), "end": round(t + per_word - 0.05, 3)})
            t += per_word
        t += gap
    return words, t


def fake_stt(monkeypatch, words):
    import stt
    monkeypatch.setattr(stt, "transcribe", lambda audio, language=None: {
        "words": words, "segments": [], "full_text": " ".join(w["text"] for w in words), "language": language or "ar", "provider": "fake", "model": "fake-1"})


def script_of(st):
    return json.loads(Path(st.script).read_text(encoding="utf-8"))


def record(tmp_path, st, **kw):
    words, total = asr_for(script_of(st), **{k: v for k, v in kw.items() if k in ("per_word", "gap", "lead", "skip", "junk")})
    return words, wav(tmp_path / "rec.wav", math.ceil(total) + 1)


def test_in_range_recording_writes_a_normal_manifest_and_waits_for_the_owner(vs, tmp_path):
    words, rec = record(tmp_path, vs)
    fake_stt(vs.mp, words)
    res = vu.ingest_guided(vs.script, rec, log=QUIET)
    assert res["ok"] and res["scenes"] == 7 and res["coverage"] == 1.0 and res["gate"]["ok"] and 45 <= res["total_sec"] <= 50
    m = voice_studio.load_manifest("s1")
    assert m["provider"] == "upload" and m["model"] == "owner" and m["source"] == "upload" and m["coverage"] == 1.0 and len(m["scenes"]) == 7
    lib = Path(config.LIBRARY_DIR)
    for e in m["scenes"]:
        f = lib / e["path"]
        assert f.is_file() and f.suffix == ".mp3" and e["provider"] == "upload" and e["timing_source"] == "stt" and e["words"]
        assert abs(vu.duration_of(f) - e["duration_sec"]) <= 0.01 and e["words"][0]["start"] >= 0 and e["text"]
        assert e["words"][-1]["end"] <= e["duration_sec"] + 0.05
        assert ":\\" not in e["path"] and ":/" not in e["path"]                              # مسار نسبي
    assert (lib / m["combined"]["path"]).is_file() and abs(m["combined"]["duration_sec"] - m["total_actual_sec"]) <= 0.3
    assert studio_state.state_of("s1", 4) == "awaiting_choice"
    assert (vu.src_dir("s1").parent.parent.parent / "voice" / "s1" / "upload_src" / "asr.json").is_file()


def test_the_normal_approval_then_builds_the_timeline_from_the_uploaded_voice(vs, tmp_path):
    words, rec = record(tmp_path, vs)
    fake_stt(vs.mp, words)
    vu.ingest_guided(vs.script, rec, log=QUIET)
    r = voice_studio.approve_voice(vs.script)
    assert r["approved"] and r["timeline_ok"] and r["timing_source"] != "estimated"          # توقيت كلمات حقيقي من التفريغ
    tl = timeline.load("s1")
    assert tl["voice"]["provider"] == "upload" and tl["voice"]["audio"].endswith("full.mp3") and len(tl["scenes"]) == 7
    assert 45_000 <= tl["voice"]["duration_ms"] <= 50_000 and studio_state.state_of("s1", 4) == "approved"


def test_a_recording_outside_45_50_fails_station_4_with_the_reason(vs, tmp_path):
    words, rec = record(tmp_path, vs, per_word=0.22, gap=0.8)                                   # أسرع بكتير ← أقصر من 45ث
    fake_stt(vs.mp, words)
    res = vu.ingest_guided(vs.script, rec, log=QUIET)
    assert not res["ok"] and "أقصر" in res["reason"] and "سجّل من جديد" in res["reason"]
    assert studio_state.state_of("s1", 4) == "failed"
    assert voice_studio.load_manifest("s1")["total_actual_sec"] < 45                          # الملفات انكتبت لتسمعها وتقرر


def test_a_weak_match_or_a_missing_scene_fails_with_a_clear_reason(vs, tmp_path):
    words, rec = record(tmp_path, vs, junk=True)
    fake_stt(vs.mp, words)
    res = vu.ingest_guided(vs.script, rec, log=QUIET)
    assert not res["ok"] and "المطابقة" in res["reason"] and studio_state.state_of("s1", 4) == "failed"
    sj = script_of(vs)
    for sc in sj["scenes"]:                                                                  # كلمات مميّزة لكل مشهد (نص حقيقي ما بيكرّر نفسه)
        sc["voiceover"] = " ".join(f"م{sc['scene_number']}ك{j}" for j in range(15))
    Path(vs.script).write_text(json.dumps(sj, ensure_ascii=False), encoding="utf-8")
    words, rec = record(tmp_path, vs, skip=(3,))
    fake_stt(vs.mp, words)
    res = vu.ingest_guided(vs.script, rec, log=QUIET)
    assert not res["ok"] and "3" in res["reason"] and "ما انلقى" in res["reason"]
    assert voice_studio.load_manifest("s1")["combined"] is None                               # ما ندمج ناقص


def test_same_conditions_as_the_extension_hook_versions_free_projects_and_bad_audio(vs, tmp_path):
    words, rec = record(tmp_path, vs)
    fake_stt(vs.mp, words)
    vs.mp.setattr(review_loop, "is_cleared", lambda p: (False, "السيناريو ما انراجع"))
    with pytest.raises(vu.VoiceUploadError, match="ما انراجع") as e:
        vu.ingest_guided(vs.script, rec, log=QUIET)
    assert e.value.status == 409 and not voice_studio.load_manifest("s1")
    vs.mp.setattr(review_loop, "is_cleared", lambda p: (True, ""))
    hook = vs.env.script_file("h.json", make_script(), meta={"product": "TESTP", "product_file": "testp.json", "script_id": "VP-testp-1-v1-h2", "hook_of": "s1.json", "status": "draft"})
    with pytest.raises(vu.VoiceUploadError, match="نسخة هوك") as e:
        vu.ingest_guided(hook, rec, log=QUIET)
    assert e.value.status == 409
    import free_project as fp
    free = Path(config.SCRIPTS_DIR) / fp.create("حر")["file"]
    with pytest.raises(vu.VoiceUploadError, match="مشروع حر"):
        vu.ingest_guided(free, rec, log=QUIET)
    with pytest.raises(vu.VoiceUploadError, match="قصير"):
        vu.ingest_guided(vs.script, wav(tmp_path / "tiny.wav", 0.2), log=QUIET)
    assert not voice_studio.load_manifest("s1") and studio_state.state_of("s1", 4) != "awaiting_choice"


def test_uploaded_voice_settings_are_not_inherited_as_tts_defaults(vs, tmp_path):
    words, rec = record(tmp_path, vs)
    fake_stt(vs.mp, words)
    vu.ingest_guided(vs.script, rec, log=QUIET)
    out_dir = Path(config.LIBRARY_DIR) / "voice" / "s1"
    assert generate_voice._inherited_voice_defaults(out_dir) == {}                         # provider/voice «owner» مش مزوّد TTS


# ───────────────────────── المسار والأمر ─────────────────────────
def client(vs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_studio
    app = FastAPI()
    app.include_router(routes_studio.router)
    return TestClient(app)


def test_route_validates_then_makes_a_job_and_the_cli_command_runs(vs, tmp_path, monkeypatch):
    c = client(vs)
    words, rec = record(tmp_path, vs)
    url = "/api/studio/s1.json/voice/upload"
    assert c.post(url, files={"file": ("x.png", b"123", "image/png")}).status_code == 400
    assert c.post(url, files={"file": ("bad.wav", b"not audio", "audio/wav")}).status_code == 400
    r = c.post(url, files={"file": ("rec.wav", rec.read_bytes(), "audio/wav")}, data={"language": "ar"})
    assert r.status_code == 200
    job = vs.env.jobs[-1]
    cmd = job["cmd"]
    assert job["kind"] == "voice" and cmd[:3] == ["voice_upload.py", "ingest-guided", str(vs.script)] and cmd[cmd.index("--language") + 1] == "ar"
    audio = Path(cmd[cmd.index("--audio") + 1])
    assert audio.is_file() and audio.name.startswith("upload")
    fake_stt(vs.mp, words)
    monkeypatch.setattr(sys, "argv", ["voice_upload.py", *cmd[1:]])
    vu.main()                                                                              # نفس أمر المهمة
    assert studio_state.state_of("s1", 4) == "awaiting_choice" and not audio.exists()
    monkeypatch.setattr(review_loop, "is_cleared", lambda p: (False, "السيناريو ما انراجع"))
    assert c.post(url, files={"file": ("rec.wav", rec.read_bytes(), "audio/wav")}).status_code == 409
    free = vs.env.script_file("g.json", make_script(), meta={"mode": "free", "script_id": "FREE-x"})
    assert c.post("/api/studio/g.json/voice/upload", files={"file": ("rec.wav", rec.read_bytes(), "audio/wav")}).status_code == 409
    monkeypatch.setattr(vu, "MAX_SOURCE_SEC", 1.0)
    monkeypatch.setattr(review_loop, "is_cleared", lambda p: (True, ""))
    r = c.post(url, files={"file": ("rec.wav", rec.read_bytes(), "audio/wav")})
    assert r.status_code == 400 and "أطول" in r.json()["detail"]
