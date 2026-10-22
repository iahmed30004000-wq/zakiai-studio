"""ربط مكتبة النماذج بنقاط التوليد الموجودة (تفريغ، صوت، صور، تكبير، تفريغ خلفية، تحريك): الأولوية، الرجوع للطريقة الحالية، والسجل."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import bgremove  # noqa: E402
import config  # noqa: E402
import generate_voice  # noqa: E402
import image_studio  # noqa: E402
import imagegen  # noqa: E402
import media_check  # noqa: E402
import model_library as ml  # noqa: E402
import motion  # noqa: E402
import production_log  # noqa: E402
import secrets_store  # noqa: E402
import stt  # noqa: E402
import tts  # noqa: E402
import upscale  # noqa: E402
from fake_openai import FakeOpenAI, png_bytes, wav_bytes  # noqa: E402

SETTINGS = {}
REAL_REFS = image_studio.refs_supported                 # الأصلية (conftest بيبدّلها بنسخة «بياخد» لكل اختبار)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    SETTINGS.clear()
    for mod in (tts, stt, imagegen):                                # ما بنقرا settings.json الحقيقي
        monkeypatch.setattr(mod, "_settings", lambda: dict(SETTINGS))
    m, prev = secrets_store.use_memory_backend()
    yield tmp_path
    secrets_store.restore_backend(prev)


@pytest.fixture
def srv(lib):
    s = FakeOpenAI().start()
    yield s
    s.stop()


def std(base, task, *, default=True, name="نموذج", params=None, caps=None, std_extra=None, fallback=None):
    m = ml.create({"name": name, "task": task, "link": "std", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"},
                   "std": {"url": base, "model": "m1", **(std_extra or {})}, "params": params or {}, "caps": caps or {}})
    if default:
        ml.set_default(task, m["id"], **({"fallback_builtin": fallback} if fallback is not None else {}))
    return m


def cmd(work: Path, task, argv, *, default=True, name="أمر", params=None):
    m = ml.create({"name": name, "task": task, "link": "command", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"},
                   "command": {"argv": argv, "cwd": str(work)}, "params": params or {}})
    if default:
        ml.set_default(task, m["id"])
    return m


# ── التفريغ ───────────────────────────────────────────────────────────────

BUILTIN_STT = {"words": [{"text": "قديم", "start": 0.0, "end": 0.5}], "language": "ar", "segments": [{"start": 0.0, "end": 0.5, "text": "قديم"}], "full_text": "قديم"}


@pytest.fixture
def builtin_stt(monkeypatch):
    calls = []
    monkeypatch.setitem(stt._DISPATCH, "local", lambda cfg, audio: calls.append(str(audio)) or dict(BUILTIN_STT))
    return calls


def audio_file(lib):
    f = lib / "a.wav"
    f.write_bytes(wav_bytes(1.2))
    return f


def test_stt_without_a_library_model_is_the_builtin_method_unchanged(lib, builtin_stt):
    r = stt.transcribe(audio_file(lib), "ar")
    assert r["full_text"] == "قديم" and r["provider"] == "local_whisper" and len(builtin_stt) == 1


def test_stt_default_library_model_replaces_the_builtin_one_and_is_logged(lib, srv, builtin_stt):
    m = std(srv.base, "stt", name="Speaches")
    r = stt.transcribe(audio_file(lib), "ar")
    assert builtin_stt == [] and r["provider"] == f"lib:{m['id']}" and r["model"] == "Speaches" and r["logged"]
    assert [w["text"] for w in r["words"]] == ["مرحبا", "بكم"] and r["segments"][0]["text"] == "مرحبا بكم" and r["full_text"] == "مرحبا بكم"
    assert production_log.recent(1, "stt")[0]["model_id"] == m["id"]
    assert srv.last("/audio/transcriptions")["fields"]["language"] == ["ar"]


def test_stt_words_only_replies_still_build_segments(lib, srv, builtin_stt):
    srv.modes["stt"] = "no_words"
    std(srv.base, "stt")
    r = stt.transcribe(audio_file(lib))
    assert r["segments"] and r["words"] == []


def test_stt_falls_back_to_the_builtin_on_a_technical_failure_and_says_so(lib, srv, builtin_stt, capsys):
    std(srv.base, "stt")
    srv.modes["stt"] = "error500"
    r = stt.transcribe(audio_file(lib))
    assert r["full_text"] == "قديم" and len(builtin_stt) == 1
    assert "كملنا بالطريقة الحالية" in capsys.readouterr().out
    assert production_log.recent(1, "stt")[0]["status"] == "failed"


def test_stt_reply_without_any_timing_counts_as_a_failure(lib, srv, builtin_stt):
    srv.transcript = {"text": "نص بلا توقيت"}
    std(srv.base, "stt")
    assert stt.transcribe(audio_file(lib))["full_text"] == "قديم"


def test_stt_without_fallback_the_failure_is_surfaced(lib, srv, builtin_stt):
    std(srv.base, "stt", name="سيرفري", fallback=False)
    srv.modes["stt"] = "error500"
    with pytest.raises(stt.STTError, match="«سيرفري»") as e:
        stt.transcribe(audio_file(lib))
    assert getattr(e.value, "logged", False) and builtin_stt == []


def test_stt_explicit_choices(lib, srv, builtin_stt):
    std(srv.base, "stt", default=False)
    assert stt.transcribe(audio_file(lib))["provider"] == "local_whisper"                    # بلا افتراضي: الطريقة الحالية
    assert stt.transcribe(audio_file(lib), via="lib:ml_001")["provider"] == "lib:ml_001"
    ml.set_default("stt", "ml_001")
    assert stt.transcribe(audio_file(lib), via="openai")["provider"] == "local_whisper"       # مزوّد صريح بيغلب الافتراضي
    with pytest.raises(stt.STTError, match="مش موجود"):
        stt.transcribe(audio_file(lib), via="lib:ml_404")
    SETTINGS["STT"] = {"provider": "lib:ml_001"}                                              # مختار بالإعدادات
    ml.set_default("stt", None)
    assert stt.transcribe(audio_file(lib))["provider"] == "lib:ml_001"


# ── الصوت ─────────────────────────────────────────────────────────────────

def fake_elevenlabs(monkeypatch):
    calls = []

    def fn(cfg, text, out):
        calls.append(cfg["provider"])
        out.write_bytes(wav_bytes(1.0))
        return None
    monkeypatch.setitem(tts._DISPATCH, "elevenlabs", fn)
    SETTINGS["TTS"] = {"provider": "elevenlabs", "api_key": "el-FAKE-0123456789", "voice": "v1"}
    return calls


def fake_words(monkeypatch):
    monkeypatch.setattr(stt, "transcribe", lambda audio, language=None, via=None: {"words": [{"text": "كلمة", "start": 0.1, "end": 0.4}, {"text": "تانية", "start": 0.5, "end": 0.9}]})


def test_voice_without_a_library_model_is_unchanged(lib, monkeypatch):
    calls = fake_elevenlabs(monkeypatch)
    r = tts.speak("نص", lib / "a.mp3", {}, want_timing=False)
    assert calls == ["elevenlabs"] and r["provider"] == "elevenlabs" and "logged" not in r


def test_voice_library_default_speaks_through_the_model_with_word_timing(lib, srv, monkeypatch):
    calls = fake_elevenlabs(monkeypatch)
    fake_words(monkeypatch)
    m = std(srv.base, "voice", name="Chatterbox", params={"voice": "ahmad"})
    out = lib / "v" / "scene_01.mp3"
    with tts.log_context("S1", "scene_1"):
        r = tts.speak("كلمة تانية", out, {}, want_timing=True)
    assert calls == [] and r["provider"] == f"lib:{m['id']}" and r["model"] == "Chatterbox" and r["voice"] == "ahmad" and r["logged"]
    assert media_check._audio_codec(out) == "mp3" and 0.4 < r["duration_sec"] < 1.0
    assert [w["text"] for w in r["words"]] == ["كلمة", "تانية"] and r["timing_source"] == "stt"
    assert srv.last("/audio/speech")["json"]["voice"] == "ahmad"
    row = production_log.recent(1, "voice")[0]
    assert (row["script_stem"], row["shot_id"], row["model_id"], row["path"]) == ("S1", "scene_1", m["id"], "std")


def test_voice_explicit_provider_model_or_voice_keeps_the_builtin_method(lib, srv, monkeypatch):
    calls = fake_elevenlabs(monkeypatch)
    std(srv.base, "voice")
    for ov in ({"provider": "elevenlabs"}, {"model": "eleven_v3"}, {"voice": "other"}):
        calls.clear()
        assert tts.speak("نص", lib / "a.mp3", ov)["provider"] == "elevenlabs" and calls == ["elevenlabs"], ov     # صوت الشخصية بيضل الغالب
    assert tts.tts_config(library=False)["provider"] == "elevenlabs"                                        # صفحة الإعدادات = الطريقة الحالية
    assert tts.tts_config()["provider"] == "lib:ml_001" and tts.tts_config()["kind"] == "library"
    assert tts.tts_config({"provider": "lib:ml_001", "voice": "x"})["voice"] == "x"


def test_voice_failure_is_never_replaced_by_another_voice(lib, srv, monkeypatch):
    calls = fake_elevenlabs(monkeypatch)
    std(srv.base, "voice", name="صوتي")
    srv.modes["speech"] = "error500"
    with pytest.raises(tts.TTSError, match="«صوتي»") as e:
        tts.speak("نص", lib / "a.mp3", {})
    assert getattr(e.value, "logged", False) and calls == []
    assert not (lib / "a.mp3").exists()


def test_voice_saved_or_explicit_library_choice_that_is_gone_fails_loudly(lib, srv, monkeypatch):
    calls = fake_elevenlabs(monkeypatch)
    SETTINGS["TTS"]["provider"] = "lib:ml_404"
    assert tts.tts_config()["library_error"]
    with pytest.raises(tts.TTSError, match="مش موجود"):
        tts.speak("نص", lib / "a.mp3", {})
    with pytest.raises(tts.TTSError, match="مش موجود"):
        tts.speak("نص", lib / "a.mp3", {"provider": "lib:ml_404"})
    assert calls == []


def test_generate_voice_end_to_end_with_a_library_model_makes_one_log_row_per_scene(lib, srv, monkeypatch):
    fake_words(monkeypatch)
    m = std(srv.base, "voice", name="Chatterbox", params={"voice": "ahmad"})
    script = lib / "library" / "scripts" / "VARA__ad__1.json"
    script.parent.mkdir(parents=True)
    script.write_text(json.dumps({"scenes": [{"scene_number": 1, "voiceover": "كلمة تانية", "duration_sec": 1.0},
                                             {"scene_number": 2, "voiceover": "كلمة تانية كمان", "duration_sec": 1.0}]}), encoding="utf-8")
    man = generate_voice.generate(script, {}, log=lambda *_: None)
    assert man["provider"] == f"lib:{m['id']}" and man["model"] == "Chatterbox" and man["voice"] == "ahmad"
    assert [s["scene"] for s in man["scenes"]] == [1, 2] and all(s["words"] and s["timing_source"] == "stt" for s in man["scenes"])
    assert man["combined"] and (lib / "library" / man["combined"]["path"]).is_file()                       # الدمج بـ -c copy اشتغل: كلهم mp3 حقيقي
    rows = production_log.recent(10, "voice")
    assert sorted(r["shot_id"] for r in rows) == ["scene_1", "scene_2"] and {r["path"] for r in rows} == {"std"} and {r["status"] for r in rows} == {"ok"}


# ── الصور ─────────────────────────────────────────────────────────────────

def builtin_image(monkeypatch):
    calls = []

    def fn(cfg, prompt, out, refs=None):
        calls.append(cfg["provider"])
        out.write_bytes(png_bytes(600, 900))
    monkeypatch.setitem(imagegen._DISPATCH, "openai", fn)
    SETTINGS["IMAGE"] = {"provider": "openai", "api_key": "sk-FAKE-0123456789abcdef"}
    return calls


def test_images_without_a_library_model_are_unchanged(lib, monkeypatch):
    calls = builtin_image(monkeypatch)
    r = imagegen.generate("زجاجة", lib / "a.png", {})
    assert calls == ["openai"] and r["provider"] == "openai" and "logged" not in r


def test_images_library_default_generates_with_a_vertical_default_size_and_the_no_text_rule(lib, srv, monkeypatch):
    calls = builtin_image(monkeypatch)
    m = std(srv.base, "image", name="FLUX محلي")
    with imagegen.log_context("S1", "f001"):
        r = imagegen.generate("زجاجة عطر", lib / "shots" / "a.png", {})
    sent = srv.last("/images/generations")["json"]
    assert calls == [] and r["provider"] == "FLUX محلي" and r["model"] == m["id"] and r["logged"] and Path(r["path"]).is_file()
    assert sent["size"] == "768x1344" and "زجاجة عطر" in sent["prompt"] and imagegen.NO_TEXT_RULE in sent["prompt"]
    row = production_log.recent(1, "image")[0]
    assert (row["script_stem"], row["shot_id"], row["model_id"], row["path"]) == ("S1", "f001", m["id"], "std")
    srv.requests.clear()
    pinned = std(srv.base, "image", name="مقاس مضبوط", std_extra={"size": "1024x1536"})
    ml.set_default("image", pinned["id"])
    imagegen.generate("x", lib / "b.png", {})
    assert srv.last("/images/generations")["json"]["size"] == "1024x1536"                                  # مقاس المالك ما بينداس عليه


def test_images_explicit_provider_wins_and_a_library_choice_can_be_explicit_too(lib, srv, monkeypatch):
    calls = builtin_image(monkeypatch)
    std(srv.base, "image", default=False)
    imagegen.generate("x", lib / "a.png", {})
    assert calls == ["openai"]                                                                             # بلا افتراضي
    imagegen.generate("x", lib / "b.png", {"provider": "lib:ml_001"})
    assert calls == ["openai"] and srv.last("/images/generations")                                         # صريح: المكتبة
    ml.set_default("image", "ml_001")
    imagegen.generate("x", lib / "c.png", {"provider": "openai"})
    assert calls == ["openai", "openai"]                                                                    # مزوّد صريح بيغلب الافتراضي


def test_images_library_failure_falls_back_to_the_current_provider_with_a_note(lib, srv, monkeypatch):
    calls = builtin_image(monkeypatch)
    std(srv.base, "image")
    srv.modes["images"] = "error500"
    r = imagegen.generate("x", lib / "a.png", {})
    assert calls == ["openai"] and r["provider"] == "openai" and "كملنا بالطريقة الحالية" in r["library_note"]
    ml.set_default("image", "ml_001", fallback_builtin=False)
    with pytest.raises(imagegen.ImageError, match="«نموذج»") as e:
        imagegen.generate("x", lib / "b.png", {})
    assert getattr(e.value, "logged", False) and calls == ["openai"]


def test_images_fallback_without_a_builtin_key_says_both(lib, srv, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    std(srv.base, "image")
    srv.modes["images"] = "error500"
    with pytest.raises(imagegen.ImageError, match="كملنا بالطريقة الحالية.*ما في مفتاح"):
        imagegen.generate("x", lib / "a.png", {})


def test_refs_supported_follows_the_library_model_capabilities(lib, srv):
    plain = std(srv.base, "image", name="بلا مراجع")
    assert REAL_REFS() == {"provider": "بلا مراجع", "model": plain["id"], "supports_refs": False}
    ed = std(srv.base, "image", name="تعديل", caps={"refs": True, "edit": True})
    assert REAL_REFS() == {"provider": "تعديل", "model": ed["id"], "supports_refs": True}
    assert REAL_REFS({"provider": f"lib:{plain['id']}"})["supports_refs"] is False
    SETTINGS["IMAGE"] = {"provider": "unorouter"}
    assert REAL_REFS({"provider": "unorouter"}) == {"provider": "unorouter", "model": "gpt-image-2", "supports_refs": False}
    ml.set_default("image", None)
    assert REAL_REFS()["provider"] == "unorouter"


# ── التكبير وتفريغ الخلفية ────────────────────────────────────────────────

def work_scripts(lib):
    w = lib / "work"
    w.mkdir()
    (w / "up2.py").write_text("import sys\nfrom PIL import Image\nim = Image.open(sys.argv[1])\nim.resize((im.width * 2, im.height * 2)).save(sys.argv[2])\n", encoding="utf-8")
    (w / "bg.py").write_text("import sys\nfrom PIL import Image\nim = Image.open(sys.argv[1]).convert('RGBA')\nim.putalpha(Image.new('L', im.size, 255))\nim.crop((0, 0, 60, 60)).resize((120, 120)).save(sys.argv[2])\n", encoding="utf-8")
    (w / "flat.py").write_text("import sys\nfrom PIL import Image\nImage.open(sys.argv[1]).convert('RGB').save(sys.argv[2])\n", encoding="utf-8")
    return w


def test_upscale_library_model_makes_the_method_available_and_does_the_work(lib, monkeypatch):
    from PIL import Image
    w = work_scripts(lib)
    monkeypatch.setattr(upscale, "WEIGHTS", lib / "no-weights.pth")
    assert upscale.available() is False
    m = cmd(w, "upscale", [sys.executable, "up2.py", "{image}", "{out}", "{scale}"], params={"scale": 2})
    assert upscale.available() is True
    src = lib / "s.png"
    Image.new("RGB", (200, 300), (9, 9, 9)).save(src)
    r = upscale.upscale_image(src, lib / "x" / "big.png", scale=2)
    assert r["device"] == "library" and r["from"] == [200, 300] and r["to"] == [400, 600] and r["model"] == "أمر" and r["logged"]
    assert production_log.recent(1, "upscale")[0]["model_id"] == m["id"]


def test_upscale_falls_back_to_the_local_model_when_the_library_one_fails(lib, monkeypatch, capsys):
    import numpy as np
    from PIL import Image
    w = work_scripts(lib)
    (w / "boom.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    cmd(w, "upscale", [sys.executable, "boom.py", "{image}", "{out}"])
    monkeypatch.setattr(upscale, "WEIGHTS", lib / "weights.pth")
    (lib / "weights.pth").write_bytes(b"x")
    monkeypatch.setattr(upscale, "_model", lambda device: object())
    monkeypatch.setattr(upscale, "_tile_upscale", lambda arr, model, device, tile, pad: np.repeat(np.repeat(arr, 4, 0), 4, 1))
    src = lib / "s.png"
    Image.new("RGB", (50, 60), (9, 9, 9)).save(src)
    r = upscale.upscale_image(src, lib / "big.png", scale=4)
    assert r["device"] in ("cpu", "cuda") and r["to"] == [200, 240]
    assert "كملنا بالطريقة الحالية" in capsys.readouterr().out


def test_bgremove_library_model_must_return_transparency_else_the_builtin_runs(lib, monkeypatch, capsys):
    from PIL import Image
    w = work_scripts(lib)
    monkeypatch.setattr(bgremove, "MODEL_DIR", lib / "no-birefnet")
    assert bgremove.available() is False
    good = cmd(w, "bgremove", [sys.executable, "bg.py", "{image}", "{out}"])
    assert bgremove.available() is True
    src = lib / "p.png"
    Image.new("RGB", (200, 200), (200, 10, 10)).save(src)
    r = bgremove.remove_background(src, lib / "o" / "cut.png")
    assert r["device"] == "library" and r["subject_pct"] == 100.0 and r["model"] == "أمر" and r["logged"]
    import product_ref
    assert product_ref._auto_remove_background(Image.new("RGB", (200, 200), (1, 2, 3))).mode == "RGBA"       # product_ref ما احتاج أي تعديل
    flat = cmd(w, "bgremove", [sys.executable, "flat.py", "{image}", "{out}"], name="مسطّح")
    monkeypatch.setattr(bgremove, "_run", lambda img, device, size: Image.new("L", img.size, 255))
    r2 = bgremove.remove_background(src, lib / "o" / "cut2.png")
    assert r2["device"] in ("cpu", "cuda") and "كملنا بالطريقة الحالية" in capsys.readouterr().out
    assert flat["name"] == "مسطّح"


# ── التحريك ───────────────────────────────────────────────────────────────

def test_motion_pin_picks_the_pinned_model_only_when_it_is_runnable_for_the_shot(lib, monkeypatch):
    a, b, c = ({"id": f"mm_00{i}", "name": f"m{i}"} for i in (1, 2, 3))
    ranked = [{"model": a}, {"model": b}, {"model": c}]
    monkeypatch.setattr(motion, "load_models", lambda: [{**x, "enabled": True} for x in (a, b, c)])
    assert motion._pinned_default() is None and motion._primary(ranked, None) is a
    ml.set_default("motion", "mm_003")
    assert motion._pinned_default() == "mm_003" and motion._primary(ranked, motion._pinned_default()) is c
    assert motion._primary(ranked[:2], "mm_003") is a                                    # المثبّت مستبعد للقطة: الأعلى ترتيباً
    ml.path().write_text("{broken", encoding="utf-8")
    assert motion._pinned_default() is None                                              # مكتبة تالفة ما بتكسر التحريك
