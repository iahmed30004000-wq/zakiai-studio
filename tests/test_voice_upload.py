"""رفع تسجيل صوتي للمشروع الحر (voice_upload): تقسيم حسب النص أو الوقت أو مشاهد جديدة، ضبط المدد، إعادة التقسيم، الحذف، وصوت بالذكاء — بتفريغ وهمي."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401

import config  # noqa: E402
import free_montage as fm  # noqa: E402
import free_project as fp  # noqa: E402
import montage  # noqa: E402
import timeline  # noqa: E402
import voice_upload as vu  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")
QUIET = lambda m: None          # noqa: E731


def wav(path, seconds=10.0, rate=16000, freq=300):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate={rate}", str(path)], check=True, capture_output=True)
    return Path(path)


def W(text, a, b):
    return {"text": text, "start": a, "end": b}


def fake_stt(monkeypatch, words, segments=None, calls=None):
    import stt

    def fn(audio, language=None):
        if calls is not None:
            calls.append((str(audio), language))
        return {"words": words, "segments": segments if segments is not None else [{"start": words[0]["start"], "end": words[-1]["end"], "text": " ".join(w["text"] for w in words)}] if words else [],
                "full_text": " ".join(w["text"] for w in words), "language": language or "ar", "provider": "fake", "model": "fake-1"}
    monkeypatch.setattr(stt, "transcribe", fn)


def sp(made):
    return Path(config.SCRIPTS_DIR) / made["file"]


def png_file(tmp_path):
    f = Path(tmp_path) / "x.png"
    Image.new("RGB", (20, 20)).save(f)
    return f


def rows(*texts, dur=3.0):
    return [{"voiceover": t, "visual": "", "on_screen_text": "", "duration_sec": dur} for t in texts]


# ثلاث جمل بوقفات: 0.5–2.5 ثم 4.0–6.0 ثم 8.0–9.5 (تسجيل 10 ثواني)
S1, S2, S3 = "ليش عيونك بتتعب آخر النهار", "جرّبي القطرة اللطيفة", "اطلبها هلأ"
ASR = [W("ليش", 0.5, 0.9), W("عيونك", 1.0, 1.5), W("بتتعب", 1.6, 2.0), W("آخر", 2.05, 2.3), W("النهار", 2.35, 2.5),
       W("جربي", 4.0, 4.6), W("القطره", 4.7, 5.3), W("اللطيفه", 5.4, 6.0),
       W("اطلبها", 8.0, 8.7), W("هلا", 8.8, 9.5)]


def free_with_text(tmp_path):
    return sp(fp.create("نص", rows(S1, S2, S3)))


# ───────────────────────── حسب النص ─────────────────────────
def test_recording_is_split_by_the_written_text_and_scene_lengths_follow_the_voice(env, tmp_path, monkeypatch):
    p = free_with_text(tmp_path)
    fake_stt(monkeypatch, ASR)
    res = vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    assert res["mode"] == "by_text" and res["voiced"] == 3 and res["coverage"] == 1.0 and res["warnings"] == []
    tl = timeline.load(p.stem)
    assert tl["rev"] == 2 and timeline.validate(tl)["ok"]
    spans = []
    for sc in tl["scenes"]:
        v = sc["voice"]
        f = Path(config.LIBRARY_DIR) / v["audio"]
        assert f.is_file() and f.suffix == ".wav" and v["source"] == "upload" and v["timing"] == "stt"
        assert abs(vu.duration_of(f) * 1000 - v["duration_ms"]) <= 2
        assert sum(sh["end_ms"] - sh["start_ms"] for sh in sc["shots"]) == v["duration_ms"]            # الصوت هو الساعة
        assert sc["end_ms"] - sc["start_ms"] == v["duration_ms"]
        spans.append(v["span_ms"])
    assert spans[0][0] == 300 and spans[0][1] == 2850                         # قبل أول كلمة 0.2ث وبعد آخر كلمة 0.35ث
    assert spans[0][1] <= spans[1][0] and spans[1][1] <= spans[2][0]           # بلا تداخل، والصمت الطويل بينهم انشال
    assert tl["length_ms"] == sum(s["voice"]["duration_ms"] for s in tl["scenes"]) and 7000 < tl["length_ms"] < 7300     # 10ث تسجيل ← 7.15ث بعد شيل الصمت
    assert [w["text"] for w in tl["scenes"][1]["voice"]["words"]] == ["جرّبي", "القطرة", "اللطيفة"]     # كلمات المالك مش المفرّغة
    assert tl["words"] and tl["words"][0]["start_ms"] == tl["scenes"][0]["voice"]["words"][0]["start_ms"]
    assert tl["voice_info"]["mode"] == "by_text" and tl["voice_info"]["coverage"] == 1.0 and tl["voice_info"]["asr"]["provider"] == "fake"
    src = vu.src_dir(p.stem)
    assert (src / "source.wav").is_file() and (src / "asr.json").is_file() and not (src / "source.tmp.wav").exists()
    assert not list(vu.voice_dir(p.stem).glob("_tmp_*")) and len(list(vu.voice_dir(p.stem).glob("*.wav"))) == 3
    assert json.loads(p.read_text(encoding="utf-8"))["total_duration_sec"] == pytest.approx(tl["length_ms"] / 1000, abs=0.01)


def test_realign_uses_the_saved_transcript_and_follows_text_edits(env, tmp_path, monkeypatch):
    p = free_with_text(tmp_path)
    calls = []
    fake_stt(monkeypatch, ASR, calls=calls)
    vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    assert len(calls) == 1
    import stt
    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: pytest.fail("لازم ما يفرّغ من جديد"))
    b = fp.board(p)
    s = {"rev": b["rev"], "scenes": [{"key": sc["key"], "voiceover": sc["voiceover"] if i != 2 else "", "shots": [{"id": sh["id"], "duration_ms": sh["end_ms"] - sh["start_ms"]} for sh in sc["shots"]]} for i, sc in enumerate(b["scenes"])]}
    fp.apply_structure(p, s)                                                  # مسحنا كلام المشهد 3
    res = vu.realign_free(p, log=QUIET)
    tl = timeline.load(p.stem)
    assert res["voiced"] == 2 and tl["scenes"][2]["voice"] is None and tl["scenes"][0]["voice"] and len(calls) == 1
    assert not (Path(config.LIBRARY_DIR) / "timelines" / p.stem / "voice" / "c003.wav").exists()      # ملف صوته القديم انشال
    with pytest.raises(vu.VoiceUploadError) as e:
        vu.realign_free(sp(fp.create("بلا تسجيل", rows("كلام"))), log=QUIET)
    assert e.value.status == 404


def test_weak_match_warns_but_still_works_and_a_scene_with_no_speech_is_left_silent(env, tmp_path, monkeypatch):
    # المشهد الأول مكتوب بكلام أكتر من المسموع (3 كلمات طابقت من 8): بيحذّر بس بيضل إله صوت لأن في كلام مسموع بمكانه
    p = sp(fp.create("ضعيف", rows("ليش عيونك بتتعب كلام غريب جداً هون", S2, "عبارة ما انقالت أبداً")))
    fake_stt(monkeypatch, ASR[:8])
    res = vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    tl = timeline.load(p.stem)
    assert res["coverage"] is not None and res["coverage"] < 0.7 and res["voiced"] == 2
    assert tl["scenes"][0]["voice"] and tl["scenes"][1]["voice"] and tl["scenes"][2]["voice"] is None          # الأخير ما انقال: بلا صوت
    assert any("ما انلقى" in w or "ما انلقى كلامه" in w for w in res["warnings"]) and timeline.load(p.stem)["voice_info"]["coverage"] == res["coverage"]


def test_no_fit_keeps_shot_durations_and_a_voice_longer_than_its_scene_only_warns(env, tmp_path, monkeypatch):
    p = sp(fp.create("بلا ضبط", rows(S1, S2, S3, dur=1.0)))
    fake_stt(monkeypatch, ASR)
    vu.ingest_free(p, wav(tmp_path / "rec.wav"), fit=False, log=QUIET)
    tl = timeline.load(p.stem)
    assert [sc["end_ms"] - sc["start_ms"] for sc in tl["scenes"]] == [1000, 1000, 1000] and tl["voice_info"]["fit"] is False
    res = timeline.validate(tl)
    assert res["ok"] and any(w["code"] == "voice_long" for w in res["warnings"])


def test_multi_shot_scene_is_scaled_proportionally_to_the_voice(env, tmp_path, monkeypatch):
    p = sp(fp.create("لقطتين", rows(S1)))
    b = fp.board(p)
    sc = b["scenes"][0]
    fp.apply_structure(p, {"rev": b["rev"], "scenes": [{"key": sc["key"], "shots": [{"id": sc["shots"][0]["id"], "duration_ms": 3000}, {"duration_ms": 1000}]}]})
    fake_stt(monkeypatch, ASR[:5])
    vu.ingest_free(p, wav(tmp_path / "rec.wav", 3.0), log=QUIET)
    sc = timeline.load(p.stem)["scenes"][0]
    d = [sh["end_ms"] - sh["start_ms"] for sh in sc["shots"]]
    assert sum(d) == sc["voice"]["duration_ms"] and d[0] > d[1] >= 500 and abs(d[0] / d[1] - 3) < 0.5


def test_fit_shots_respects_shot_limits():
    sc = {"shots": [{"start_ms": 0, "end_ms": 3000}, {"start_ms": 3000, "end_ms": 4000}]}
    vu.fit_shots(sc, 100)                                                       # أقل من الحد: 0.5ث لكل لقطة
    assert [s["end_ms"] - s["start_ms"] for s in sc["shots"]] == [500, 500]
    sc = {"shots": [{"start_ms": 0, "end_ms": 3000}]}
    vu.fit_shots(sc, 999_999)
    assert sc["shots"][0]["end_ms"] == timeline.FREE_MAX_SHOT_MS


# ───────────────────────── حسب الوقت ومشاهد جديدة ─────────────────────────
def media_project(tmp_path, n=3):
    made = fp.create("وسائط")
    p = sp(made)
    files = []
    for i in range(n):
        im = tmp_path / f"i{i}.png"
        Image.new("RGB", (320, 480), (40 * i + 20, 80, 120)).save(im)
        files.append({"kind": "image", "tmp": im, "filename": im.name})
    fp.add_media(p, files)
    return p


def test_recording_is_distributed_over_scenes_without_text_by_time(env, tmp_path, monkeypatch):
    p = media_project(tmp_path)                                                 # 3 مشاهد × 3ث، بلا كلام
    fake_stt(monkeypatch, ASR)
    res = vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    tl = timeline.load(p.stem)
    assert res["mode"] == "by_time" and res["coverage"] is None and res["voiced"] == 3
    assert [sc["voiceover"] for sc in tl["scenes"]] == ["ليش عيونك بتتعب آخر النهار", "جربي القطره اللطيفه", "اطلبها هلا"]        # الجملة صارت كلام المشهد
    assert all(sc["voice"] and sc["voice"]["words"] for sc in tl["scenes"]) and timeline.validate(tl)["ok"]
    assert tl["scenes"][0]["shots"][0]["image"]["chosen"]                        # الصور بقيت


def test_by_time_with_fewer_sentences_than_scenes_leaves_some_scenes_silent_with_a_warning(env, tmp_path, monkeypatch):
    p = media_project(tmp_path, 5)
    fake_stt(monkeypatch, ASR[:5])                                              # جملة وحدة بس
    res = vu.ingest_free(p, wav(tmp_path / "rec.wav", 4.0), log=QUIET)
    tl = timeline.load(p.stem)
    assert res["voiced"] == 1 and sum(1 for sc in tl["scenes"] if sc["voice"]) == 1
    assert any("بلا صوت" in w for w in res["warnings"])


def test_blank_project_gets_a_scene_per_sentence(env, tmp_path, monkeypatch):
    p = sp(fp.create("فاضي"))
    fake_stt(monkeypatch, ASR)
    res = vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    tl = timeline.load(p.stem)
    assert res["mode"] == "new_scenes" and len(tl["scenes"]) == 3 and all(sc["voice"] for sc in tl["scenes"])
    assert tl["scenes"][1]["voiceover"] == "جربي القطره اللطيفه" and not any(sh["image"]["chosen"] for sc in tl["scenes"] for sh in sc["shots"])
    assert [sc["key"] for sc in tl["scenes"]] == ["c002", "c003", "c004"] and timeline.validate(tl)["ok"]
    with pytest.raises(vu.VoiceUploadError, match="فيه مشاهد"):
        vu.apply_plan(p, vu.load_asr(p.stem), vu.src_dir(p.stem) / "source.wav", "new_scenes", log=QUIET)


def test_many_sentences_are_grouped_to_respect_the_scene_limit(env, tmp_path, monkeypatch):
    p = sp(fp.create("كتير"))
    words = [W(f"كلمة{i}", i * 2.0, i * 2.0 + 1.0) for i in range(60)]
    words = [w for w in words]
    fake_stt(monkeypatch, words)
    vu.ingest_free(p, wav(tmp_path / "rec.wav", 120.0, rate=8000), log=QUIET)
    tl = timeline.load(p.stem)
    assert len(tl["scenes"]) <= timeline.FREE_MAX_SCENES and all(sc["voice"] for sc in tl["scenes"])
    assert sum(len(sc["voice"]["words"]) for sc in tl["scenes"]) >= 58


# ───────────────────────── الأخطاء ─────────────────────────
def test_bad_inputs_fail_with_clear_arabic_messages_and_write_nothing(env, tmp_path, monkeypatch):
    p = free_with_text(tmp_path)
    fake_stt(monkeypatch, ASR)
    with pytest.raises(vu.VoiceUploadError, match="ما فيه صوت"):
        vu.ingest_free(p, png_file(tmp_path), log=QUIET)
    with pytest.raises(vu.VoiceUploadError, match="قصير"):
        vu.ingest_free(p, wav(tmp_path / "short.wav", 0.3), log=QUIET)
    monkeypatch.setattr(vu, "MAX_SOURCE_SEC", 5.0)
    with pytest.raises(vu.VoiceUploadError, match="أطول"):
        vu.ingest_free(p, wav(tmp_path / "long.wav", 8.0), log=QUIET)
    monkeypatch.setattr(vu, "MAX_SOURCE_SEC", 600.0)
    fake_stt(monkeypatch, [], segments=[])
    with pytest.raises(vu.VoiceUploadError, match="ما انسمع كلام"):
        vu.ingest_free(p, wav(tmp_path / "quiet.wav"), log=QUIET)
    import stt

    def boom(*a, **k):
        raise stt.STTError("مفتاح غلط")
    monkeypatch.setattr(stt, "transcribe", boom)
    with pytest.raises(vu.VoiceUploadError, match="فشل التفريغ: مفتاح غلط") as e:
        vu.ingest_free(p, wav(tmp_path / "ok.wav"), log=QUIET)
    assert e.value.status == 502
    tl = timeline.load(p.stem)
    assert tl["rev"] == 1 and all(sc.get("voice") is None for sc in tl["scenes"]) and not vu.voice_dir(p.stem).exists()
    env.script_file("g.json", make_script())
    with pytest.raises(vu.VoiceUploadError, match="مش مشروع حر"):
        vu.ingest_free(env.scripts / "g.json", wav(tmp_path / "g.wav"), log=QUIET)


def test_segments_without_word_timing_get_estimated_words(env, tmp_path, monkeypatch):
    p = free_with_text(tmp_path)
    fake_stt(monkeypatch, [], segments=[{"start": 0.5, "end": 2.5, "text": S1}, {"start": 4.0, "end": 6.0, "text": S2}, {"start": 8.0, "end": 9.5, "text": S3}])
    res = vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    tl = timeline.load(p.stem)
    assert res["voiced"] == 3 and tl["voice_info"]["asr"]["timing"] == "estimated" and tl["scenes"][0]["voice"]["timing"] == "estimated"


def test_project_changed_while_cutting_aborts_instead_of_overwriting(env, tmp_path, monkeypatch):
    p = free_with_text(tmp_path)
    fake_stt(monkeypatch, ASR)
    real = vu.cut_wav
    state = {"n": 0}

    def sneaky(src, a, b, dst):
        state["n"] += 1
        if state["n"] == 1:                                                    # المالك أضاف مشهد أثناء القص
            bd = fp.board(p)
            fp.apply_structure(p, {"rev": bd["rev"], "scenes": [{"key": s["key"], "shots": [{"id": s["shots"][0]["id"], "duration_ms": 3000}]} for s in bd["scenes"]] + [{"shots": [{"duration_ms": 1000}]}]})
        return real(src, a, b, dst)
    monkeypatch.setattr(vu, "cut_wav", sneaky)
    with pytest.raises(vu.VoiceUploadError, match="تغيّرت مشاهد") as e:
        vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    assert e.value.status == 409
    tl = timeline.load(p.stem)
    assert len(tl["scenes"]) == 4 and all(sc.get("voice") is None for sc in tl["scenes"]) and not list(vu.voice_dir(p.stem).glob("_tmp_*"))


# ───────────────────────── الحذف ─────────────────────────
def test_delete_removes_scene_voices_but_keeps_the_source_for_a_later_realign(env, tmp_path, monkeypatch):
    p = free_with_text(tmp_path)
    fake_stt(monkeypatch, ASR)
    vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    b = vu.delete_free(p)
    tl = timeline.load(p.stem)
    assert all(sc["voice"] is None for sc in tl["scenes"]) and "voice_info" not in tl and not list(vu.voice_dir(p.stem).glob("*.wav"))
    assert (vu.src_dir(p.stem) / "source.wav").is_file() and b["rev"] == tl["rev"]
    assert vu.realign_free(p, log=QUIET)["voiced"] == 3                           # بلا تفريغ جديد
    vu.delete_free(p, purge=True)
    assert not vu.src_dir(p.stem).exists()


# ───────────────────────── صوت بالذكاء ─────────────────────────
def fake_tts(monkeypatch, fail_on=None, calls=None):
    import tts

    def speak(text, out_path, overrides=None, want_timing=False):
        if calls is not None:
            calls.append(text)
        if fail_on and fail_on in text:
            raise tts.TTSError("رصيد المزوّد خلص")
        wav(out_path.with_suffix(".src.wav"), 2.0)
        shutil.copy(out_path.with_suffix(".src.wav"), out_path)
        out_path.with_suffix(".src.wav").unlink()
        toks = text.split()
        return {"path": str(out_path), "duration_sec": 2.0, "provider": "fake", "model": "m1", "voice": "v1",
                "words": [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, t in enumerate(toks)], "timing_source": "provider"}
    monkeypatch.setattr(tts, "speak", speak)


def test_tts_makes_a_voice_per_scene_with_text_and_only_redoes_what_changed(env, tmp_path, monkeypatch):
    p = sp(fp.create("ذكاء", rows(S1, "", S3)))
    calls = []
    fake_tts(monkeypatch, calls=calls)
    res = vu.tts_free(p, log=QUIET)
    tl = timeline.load(p.stem)
    assert res["voiced"] == 2 and calls == [S1, S3] and tl["scenes"][1]["voice"] is None
    v = tl["scenes"][0]["voice"]
    assert v["source"] == "tts" and v["provider"] == "fake" and v["voice_id"] == "v1" and v["timing"] == "provider" and v["text"] == S1
    assert tl["scenes"][0]["end_ms"] - tl["scenes"][0]["start_ms"] == v["duration_ms"] and abs(vu.duration_of(Path(config.LIBRARY_DIR) / v["audio"]) - 2.0) < 0.05
    assert tl["voice_info"]["source"] == "tts" and timeline.validate(tl)["ok"]
    with pytest.raises(vu.VoiceUploadError, match="بحاجة لصوت"):
        vu.tts_free(p, log=QUIET)
    b = fp.board(p)
    fp.apply_structure(p, {"rev": b["rev"], "scenes": [{"key": sc["key"], "voiceover": "نص جديد للمشهد" if i == 2 else sc["voiceover"],
                                                         "shots": [{"id": sh["id"], "duration_ms": sh["end_ms"] - sh["start_ms"]} for sh in sc["shots"]]} for i, sc in enumerate(b["scenes"])]})
    calls.clear()
    vu.tts_free(p, log=QUIET)
    assert calls == ["نص جديد للمشهد"]                                          # المشهد اللي نصه تغيّر بس
    calls.clear()
    vu.tts_free(p, only_missing=False, log=QUIET)
    assert len(calls) == 2


def test_tts_failure_stops_cleanly_and_keeps_what_was_already_made(env, tmp_path, monkeypatch):
    p = sp(fp.create("فشل", rows(S1, S2)))
    fake_tts(monkeypatch, fail_on="القطرة")
    with pytest.raises(vu.VoiceUploadError, match="رصيد المزوّد خلص") as e:
        vu.tts_free(p, log=QUIET)
    assert e.value.status == 502
    tl = timeline.load(p.stem)
    assert tl["scenes"][0]["voice"] and tl["scenes"][1]["voice"] is None            # الأول انحفظ والتاني لا
    assert not list(vu.voice_dir(p.stem).glob("*.mp3"))


def test_voice_feeds_the_montage_with_the_audio_at_its_scene_and_word_captions(env, tmp_path, monkeypatch):
    p = media_project(tmp_path, 2)
    b = fp.board(p)
    fp.apply_structure(p, {"rev": b["rev"], "scenes": [{"key": sc["key"], "voiceover": t, "shots": [{"id": sc["shots"][0]["id"], "duration_ms": 3000}]} for sc, t in zip(b["scenes"], (S1, S2))]})
    fake_stt(monkeypatch, [W("ليش", 0.5, 0.9), W("عيونك", 1.0, 1.5), W("بتتعب", 1.6, 2.0), W("آخر", 2.05, 2.3), W("النهار", 2.35, 2.5), W("جربي", 4.0, 4.6), W("القطره", 4.7, 5.3), W("اللطيفه", 5.4, 6.0)])
    vu.ingest_free(p, wav(tmp_path / "rec.wav", 7.0), log=QUIET)
    r = fm.render(p, "preview", size=(90, 160), log=QUIET)
    tl = timeline.load(p.stem)
    info = montage.probe(Path(config.LIBRARY_DIR) / r["file"])
    assert r["cues"]["voice"] >= 2 and info["has_audio"] and abs(info["duration_ms"] - tl["length_ms"]) <= fm.EPS_MS


# ───────────────────────── المسارات ─────────────────────────
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_free
    app = FastAPI()
    app.include_router(routes_free.router)
    return TestClient(app)


def test_upload_route_validates_stores_the_file_and_makes_a_job_that_the_cli_can_run(env, tmp_path, monkeypatch):
    from test_free_media import make_video
    c = client()
    f = c.post("/api/free/projects", data={"title": "ص", "text": f"{S1}\n\n{S2}\n\n{S3}"}).json()["file"]
    p = Path(config.SCRIPTS_DIR) / f
    rec = wav(tmp_path / "r.wav", 10.0)
    r = c.post(f"/api/studio/{f}/free/voice/upload", files={"file": ("r.wav", rec.read_bytes(), "audio/wav")}, data={"fit": "false", "mode": "by_text", "language": "ar"})
    assert r.status_code == 200 and r.json()["job_id"].startswith("job")
    job = env.jobs[-1]
    cmd = job["cmd"]
    assert job["kind"] == "voice" and cmd[:3] == ["voice_upload.py", "ingest", str(p)] and "--no-fit" in cmd
    assert cmd[cmd.index("--mode") + 1] == "by_text" and cmd[cmd.index("--language") + 1] == "ar" and Path(cmd[cmd.index("--audio") + 1]).is_file()
    # نشغّل نفس الأمر فعلياً (بتفريغ وهمي): بيشتغل، وبيشيل الأصل المرفوع بعد التحويل
    calls = []
    fake_stt(monkeypatch, ASR, calls=calls)
    monkeypatch.setattr(sys, "argv", ["voice_upload.py", *cmd[1:]])
    vu.main()
    tl = timeline.load(p.stem)
    assert all(sc["voice"] for sc in tl["scenes"]) and calls[0][1] == "ar" and tl["voice_info"]["fit"] is False
    assert not Path(cmd[cmd.index("--audio") + 1]).exists()
    b = c.get(f"/api/studio/{f}/free/board").json()
    assert b["voice"]["scenes_with_voice"] == 3 and b["voice"]["has_source"] and b["voice"]["info"]["mode"] == "by_text"


def test_upload_route_rejects_bad_files_modes_and_guided_scripts(env, tmp_path, monkeypatch):
    from test_free_media import make_video
    c = client()
    f = c.post("/api/free/projects", data={"title": "ص"}).json()["file"]
    url = f"/api/studio/{f}/free/voice/upload"
    rec = wav(tmp_path / "r.wav", 2.0).read_bytes()
    r = c.post(url, files={"file": ("x.png", b"123", "image/png")})
    assert r.status_code == 400 and "ملف صوت" in r.json()["detail"]
    assert c.post(url, files={"file": ("r.wav", rec, "audio/wav")}, data={"mode": "zzz"}).status_code == 400
    silent = make_video(tmp_path / "s.mp4", 1, audio=False, size="160x288")
    r = c.post(url, files={"file": ("s.mp4", silent.read_bytes(), "video/mp4")})
    assert r.status_code == 400 and "ما فيه صوت" in r.json()["detail"]
    r = c.post(url, files={"file": ("bad.wav", b"not audio at all", "audio/wav")})
    assert r.status_code == 400
    monkeypatch.setattr(vu, "MAX_SOURCE_SEC", 1.0)
    r = c.post(url, files={"file": ("r.wav", rec, "audio/wav")})
    assert r.status_code == 400 and "أطول" in r.json()["detail"]
    assert not list(vu.src_dir(Path(f).stem).glob("upload*")) and not env.jobs
    env.script_file("g.json", make_script())
    assert c.post("/api/studio/g.json/free/voice/upload", files={"file": ("r.wav", rec, "audio/wav")}).status_code == 409
    withaudio = make_video(tmp_path / "a.mp4", 2, audio=True, size="160x288")
    monkeypatch.setattr(vu, "MAX_SOURCE_SEC", 600.0)
    assert c.post(url, files={"file": ("a.mp4", withaudio.read_bytes(), "video/mp4")}).status_code == 200            # فيديو فيه صوتك مقبول


def test_realign_delete_and_file_routes(env, tmp_path, monkeypatch):
    c = client()
    f = c.post("/api/free/projects", data={"title": "ص", "text": f"{S1}\n\n{S2}\n\n{S3}"}).json()["file"]
    p = Path(config.SCRIPTS_DIR) / f
    assert c.post(f"/api/studio/{f}/free/voice/realign", json={}).status_code == 404                   # لسا ما في تسجيل
    fake_stt(monkeypatch, ASR)
    vu.ingest_free(p, wav(tmp_path / "rec.wav"), log=QUIET)
    r = c.post(f"/api/studio/{f}/free/voice/realign", json={"fit": False})
    assert r.status_code == 200 and r.json()["result"]["voiced"] == 3 and r.json()["board"]["voice"]["info"]["fit"] is False
    assert c.post(f"/api/studio/{f}/free/voice/realign", json={"mode": "zzz"}).status_code == 400
    key = r.json()["board"]["scenes"][0]["key"]
    a = c.get(f"/api/studio/{f}/free/voice/{key}")
    assert a.status_code == 200 and a.headers["content-type"] == "audio/wav" and a.content[:4] == b"RIFF"
    assert c.get(f"/api/studio/{f}/free/voice/c999").status_code == 404
    d = c.delete(f"/api/studio/{f}/free/voice")
    assert d.status_code == 200 and d.json()["voice"]["scenes_with_voice"] == 0 and d.json()["voice"]["has_source"] is True
    assert c.get(f"/api/studio/{f}/free/voice/{key}").status_code == 404
    assert c.delete(f"/api/studio/{f}/free/voice", params={"purge": "1"}).json()["voice"]["has_source"] is False
    env.script_file("g.json", make_script())
    assert c.delete("/api/studio/g.json/free/voice").status_code == 409 and c.get("/api/studio/g.json/free/voice/c001").status_code == 409


def test_tts_route_needs_a_key_and_something_to_voice_then_makes_a_job(env, tmp_path, monkeypatch):
    import tts
    c = client()
    f = c.post("/api/free/projects", data={"title": "ص", "text": f"{S1}\n\n\n\n{S2}"}).json()["file"]
    p = Path(config.SCRIPTS_DIR) / f
    monkeypatch.setattr(tts, "tts_config", lambda o=None: {"api_key": "", "provider": "elevenlabs", "model": "m", "voice": "v"})
    r = c.post(f"/api/studio/{f}/free/voice/tts", json={})
    assert r.status_code == 409 and "مفتاح" in r.json()["detail"]
    monkeypatch.setattr(tts, "tts_config", lambda o=None: {"api_key": "k", "provider": "elevenlabs", "model": "m", "voice": "v"})
    r = c.post(f"/api/studio/{f}/free/voice/tts", json={"only_missing": False, "fit": False})
    assert r.status_code == 200 and r.json()["scenes"] == 2
    assert env.jobs[-1]["cmd"] == ["voice_upload.py", "tts", str(p), "--all", "--no-fit"]
    c.post(f"/api/studio/{f}/free/voice/tts")
    assert env.jobs[-1]["cmd"] == ["voice_upload.py", "tts", str(p)]
    empty = c.post("/api/free/projects", data={"title": "فاضي"}).json()["file"]
    r = c.post(f"/api/studio/{empty}/free/voice/tts", json={})
    assert r.status_code == 409 and "بحاجة لصوت" in r.json()["detail"]
    fake_tts(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["voice_upload.py", "tts", str(p)])
    vu.main()                                                                                              # نفس الأمر بيشتغل
    assert c.get(f"/api/studio/{f}/free/board").json()["voice"]["scenes_with_voice"] == 2
    r = c.post(f"/api/studio/{f}/free/voice/tts", json={})
    assert r.status_code == 409                                                                            # الكل إله صوت


def test_tts_route_takes_an_explicit_library_model_and_rejects_anything_else(env, monkeypatch):
    """اختيار النموذج بالشغلة السريعة: lib:ml_xxx بس، وبيوصل للأمر وللإعداد؛ أي قيمة غريبة = 400."""
    import tts
    c = client()
    f = c.post("/api/free/projects", data={"title": "ص", "text": f"{S1}\n\n\n\n{S2}"}).json()["file"]
    p = Path(config.SCRIPTS_DIR) / f
    seen = []
    monkeypatch.setattr(tts, "tts_config", lambda o=None: (seen.append(dict(o or {})) or {"api_key": "k", "provider": "x", "model": "m", "voice": "v"}))
    r = c.post(f"/api/studio/{f}/free/voice/tts", json={"provider": "lib:ml_002", "only_missing": False})
    assert r.status_code == 200, r.text
    assert env.jobs[-1]["cmd"] == ["voice_upload.py", "tts", str(p), "--all", "--provider", "lib:ml_002"]
    assert {"provider": "lib:ml_002"} in seen
    for bad in ("elevenlabs", "lib:../x", 7, "lib:ml_1"):
        assert c.post(f"/api/studio/{f}/free/voice/tts", json={"provider": bad}).status_code == 400, bad


# ───────── تنظيف التسجيل (اقتراح البحث 2) ─────────
def _noisy(path, seconds=4.0):
    """كلام مزيّف (نغمة) فوق ضجة ثابتة متل المكيّف — نفس شكل تسجيل الموبايل بالسيارة."""
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}:sample_rate=48000",
                    "-f", "lavfi", "-i", f"anoisesrc=color=white:amplitude=0.08:duration={seconds}:sample_rate=48000",
                    "-filter_complex", "amix=inputs=2:normalize=0", str(path)], check=True, capture_output=True)
    return Path(path)


def _noise_floor_db(p):
    """مستوى الضجة: علوّ الصوت بعد ما نشيل نغمة الكلام (300Hz) بفلتر قاطع."""
    out = subprocess.run(["ffmpeg", "-i", str(p), "-af", "bandreject=f=300:width_type=h:w=80,volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(out.split("mean_volume:")[1].split("dB")[0])


def test_to_wav_cleans_steady_noise_and_keeps_the_length(tmp_path, monkeypatch):
    src = _noisy(tmp_path / "car.wav")
    monkeypatch.setattr(vu, "VOICE_CLEAN", False)
    raw_d = vu.to_wav(src, tmp_path / "raw.wav")
    monkeypatch.setattr(vu, "VOICE_CLEAN", True)
    clean_d = vu.to_wav(src, tmp_path / "clean.wav")
    assert abs(clean_d - raw_d) < 0.05                       # المدة ما بتتغيّر (توقيت المهمة الموجّهة)
    assert _noise_floor_db(tmp_path / "clean.wav") < _noise_floor_db(tmp_path / "raw.wav") - 4   # الضجة نزلت 4dB على الأقل (انقاس: 6.4)
