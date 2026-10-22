"""الواجهة القياسية (link_std) عبر model_run مع سيرفر OpenAI وهمي: صور/صوت/تفريغ، ترجمة الأخطاء، الأمان، وسجل الإنتاج."""

import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
import link_std  # noqa: E402
import media_check  # noqa: E402
import model_library as ml  # noqa: E402
import model_run as mr  # noqa: E402
import production_log  # noqa: E402
import secrets_store  # noqa: E402
from fake_openai import FakeOpenAI, png_bytes, wav_bytes  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    m, prev = secrets_store.use_memory_backend()
    yield tmp_path
    secrets_store.restore_backend(prev)


@pytest.fixture
def srv(lib):
    s = FakeOpenAI().start()
    yield s
    s.stop()


def std_model(base, task="image", *, std=None, caps=None, params=None, **kw):
    raw = {"name": "نموذج وهمي", "task": task, "link": "std", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"},
           "std": {"url": base, "model": "flux", **(std or {})}, "caps": caps or {}, "params": params or {}, **kw}
    return ml.create(raw)


def tmp_dirs():
    root = mr.tmp_root()
    return [p for p in root.iterdir()] if root.exists() else []


# ── فحص السيرفر ───────────────────────────────────────────────────────────

def test_probe_lists_models_and_skips_junk(srv):
    r = link_std.probe(srv.base)
    assert r["ok"] and r["models"] == ["flux", "whisper-large"] and "2 موديل" in r["message"]
    assert srv.last("/models")["auth"] is None


def test_probe_reports_reasons_instead_of_raising(lib):
    assert link_std.probe("http://example.com:80/v1")["reason"] == "config"             # بره قائمة السماح: ما بنبعت أي طلب
    s = FakeOpenAI().start()
    base = s.base
    s.stop()
    assert link_std.probe(base)["reason"] == "connection"
    s = FakeOpenAI(token="tok-FAKE-1234567890").start()
    try:
        assert link_std.probe(s.base)["reason"] == "auth"
        ok = link_std.probe(s.base, "tok-FAKE-1234567890")
        assert ok["ok"] and s.last("/models")["auth"] == "Bearer tok-FAKE-1234567890"
    finally:
        s.stop()
    s = FakeOpenAI().start()
    try:
        s.modes["models"] = "notfound"
        assert link_std.probe(s.base)["reason"] == "missing"
    finally:
        s.stop()


def test_session_never_trusts_environment_proxies():
    s = link_std.session("t")
    assert s.trust_env is False and s.headers["Authorization"] == "Bearer t"
    assert "Authorization" not in link_std.session().headers


# ── الصور ─────────────────────────────────────────────────────────────────

def test_image_generation_end_to_end_and_it_is_logged(srv, lib, monkeypatch):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")                                    # لو استعملنا البروكسي بتفشل
    m = std_model(srv.base)
    out = lib / "shots" / "s.png"
    res = mr.run(m, mr.RunRequest(task="image", prompt="عطر على رخام", out=out, script_stem="S1", shot_id="f001"))
    assert res.path == out and out.is_file() and res.kind == "image" and res.info["width"] == 512 and res.model_id == m["id"]
    sent = srv.last("/images/generations")["json"]
    assert sent == {"model": "flux", "prompt": "عطر على رخام", "n": 1, "size": "1024x1024", "response_format": "b64_json"}
    assert tmp_dirs() == []
    rows = production_log.recent(5, "image")
    assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["path"] == "std" and rows[0]["model_id"] == m["id"]
    assert rows[0]["script_stem"] == "S1" and rows[0]["shot_id"] == "f001" and rows[0]["seconds"] is not None


def test_size_comes_from_call_params_then_model_config(srv, lib):
    m = std_model(srv.base, std={"size": "768x768"}, params={"width": 512, "height": 512})
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "a.png", params={"width": 576, "height": 1024}))
    assert srv.last("/images/generations")["json"]["size"] == "576x1024"
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "b.png"))
    assert srv.last("/images/generations")["json"]["size"] == "512x512"
    m2 = std_model(srv.base, std={"size": "768x768"})
    mr.run(m2, mr.RunRequest(task="image", prompt="x", out=lib / "c.png"))
    assert srv.last("/images/generations")["json"]["size"] == "768x768"


def test_the_final_file_format_follows_its_extension(srv, lib):
    m = std_model(srv.base)
    out = lib / "shot.jpg"
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=out))
    assert out.read_bytes()[:3] == b"\xff\xd8\xff"                                        # PNG من السيرفر ← JPEG حسب الامتداد


def test_token_comes_from_the_secret_store_and_never_leaks(lib):
    s = FakeOpenAI(token="tok-FAKE-1234567890").start()
    try:
        m = std_model(s.base, std={"token_secret": "modellib.ml_001.token"})
        req = mr.RunRequest(task="image", prompt="x", out=lib / "a.png")
        with pytest.raises(mr.RunError) as bad:                                           # التوكن لسا ما انحفظ ← السيرفر بيرفض
            mr.run(m, req)
        assert bad.value.reason == "auth" and bad.value.technical
        secrets_store.set_secret("modellib.ml_001.token", "tok-FAKE-1234567890")
        mr.run(m, req)
        assert s.last("/images/generations")["auth"] == "Bearer tok-FAKE-1234567890"
        secrets_store.set_secret("modellib.ml_001.token", "tok-WRONG-9999999999")
        with pytest.raises(mr.RunError) as wrong:
            mr.run(m, req)
        blob = str(wrong.value) + repr(production_log.recent(10)) + repr(m)
        assert "tok-WRONG" not in blob and "tok-FAKE" not in blob
    finally:
        s.stop()


def test_image_url_results_are_only_followed_on_the_same_host(srv, lib):
    m = std_model(srv.base)
    srv.modes["images"] = "url"
    res = mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "u.png"))
    assert res.path.is_file() and any(r["path"] == "/files/x.png" for r in srv.requests)
    for mode in ("foreign_url", "userinfo_url"):
        srv.modes["images"] = mode
        n = len(srv.requests)
        with pytest.raises(mr.RunError, match="غير آمن|مضيف") as e:
            mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "n.png"))
        assert e.value.reason == "bad_output" and len(srv.requests) == n + 1               # ما بعتنا ولا طلب للمضيف الغريب
    assert not (lib / "n.png").exists()


@pytest.mark.parametrize("mode", ["html", "tiny", "empty", "notjson"])
def test_junk_image_replies_are_rejected_before_they_reach_the_project(srv, lib, mode):
    srv.modes["images"] = mode
    with pytest.raises(mr.RunError) as e:
        mr.run(std_model(srv.base), mr.RunRequest(task="image", prompt="x", out=lib / "j.png"))
    assert e.value.reason == "bad_output" and e.value.technical and not (lib / "j.png").exists() and tmp_dirs() == []


@pytest.mark.parametrize("mode,reason,msg", [
    ("error500", "model_failed", "boom internal"), ("oom", "oom", "out of memory"), ("bad400", "rejected", "size not supported"),
    ("notfound", "missing", "/v1"), ("busy", "busy", "مشغول"), ("redirect", "connection", "التحويلات ممنوعة"),
])
def test_server_failures_become_clear_arabic_reasons_and_are_logged(srv, lib, mode, reason, msg):
    srv.modes["images"] = mode
    with pytest.raises(mr.RunError) as e:
        mr.run(std_model(srv.base), mr.RunRequest(task="image", prompt="x", out=lib / "f.png"))
    assert e.value.reason == reason and e.value.technical and msg in str(e.value)
    row = production_log.recent(1, "image")[0]
    assert row["status"] == "failed" and row["error"].startswith(reason)


def test_connection_refused_timeout_and_cancel(srv, lib):
    m = std_model(srv.base)
    srv.modes["images"] = "slow"
    m["timeout_sec"] = 1
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "t.png"))
    assert e.value.reason == "timeout" and e.value.technical
    ev = threading.Event()
    ev.set()
    srv.modes["images"] = ""
    m["timeout_sec"] = 60
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "c.png", cancel=ev))
    assert e.value.reason == "cancelled" and e.value.technical is False
    srv.stop()
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "d.png"))
    assert e.value.reason == "connection" and "واقف" in str(e.value)


def test_image_edit_uses_the_multipart_endpoint_only_when_the_model_supports_refs(srv, lib):
    ref1, ref2 = lib / "r1.png", lib / "r2.png"
    ref1.write_bytes(png_bytes(300, 300))
    ref2.write_bytes(png_bytes(320, 320))
    m = std_model(srv.base, caps={"edit": True, "refs": True})
    mr.run(m, mr.RunRequest(task="image", prompt="غيّر الخلفية", out=lib / "e.png", refs=[ref1]))
    f = srv.last("/images/edits")["fields"]
    assert f["prompt"] == ["غيّر الخلفية"] and f["model"] == ["flux"] and f["image"][0]["size"] > 100 and "image[]" not in f
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "e2.png", refs=[ref1, ref2]))
    f = srv.last("/images/edits")["fields"]
    assert len(f["image[]"]) == 2
    plain = std_model(srv.base)
    n = len(srv.requests)
    with pytest.raises(mr.RunError) as e:
        mr.run(plain, mr.RunRequest(task="image", prompt="x", out=lib / "e3.png", refs=[ref1]))
    assert e.value.reason == "unsupported" and not e.value.technical and len(srv.requests) == n


def test_missing_inputs_are_owner_errors_not_server_calls(srv, lib):
    m = std_model(srv.base)
    n = len(srv.requests)
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="  ", out=lib / "a.png"))
    assert e.value.reason == "config" and not e.value.technical and len(srv.requests) == n
    with pytest.raises(mr.RunError, match="ملف الناتج"):
        mr.run(m, mr.RunRequest(task="image", prompt="x"))


# ── الصوت ─────────────────────────────────────────────────────────────────

def test_voice_becomes_a_real_mp3_when_the_path_says_mp3(srv, lib):
    m = std_model(srv.base, "voice", std={"model": "tts-1", "response_format": "wav"}, params={"voice": "ahmad", "speed": 1.2})
    out = lib / "voice" / "scene_01.mp3"
    res = mr.run(m, mr.RunRequest(task="voice", text="أهلاً وسهلاً", out=out))
    assert res.kind == "audio" and 0.4 < res.info["duration_sec"] < 1.0
    assert media_check._audio_codec(out) == "mp3"                                          # مش WAV باسم mp3 (concat -c copy بيخرب)
    sent = srv.last("/audio/speech")["json"]
    assert sent == {"model": "tts-1", "input": "أهلاً وسهلاً", "voice": "ahmad", "response_format": "wav", "speed": 1.2}
    mr.run(std_model(srv.base, "voice"), mr.RunRequest(task="voice", text="x y", out=lib / "v.wav"))
    sent = srv.last("/audio/speech")["json"]
    assert "speed" not in sent and sent["voice"] == "alloy" and sent["response_format"] == "mp3"
    assert media_check._audio_codec(lib / "v.wav").startswith("pcm_")


def test_voice_failures(srv, lib):
    m = std_model(srv.base, "voice")
    for mode, msg in (("json_error", "voice not found"), ("garbage", "مرفوض"), ("silence_empty", "مرفوض|فاضي")):
        srv.modes["speech"] = mode
        with pytest.raises(mr.RunError, match=msg) as e:
            mr.run(m, mr.RunRequest(task="voice", text="x", out=lib / "v.mp3"))
        assert e.value.reason == "bad_output" and not (lib / "v.mp3").exists()
    srv.modes["speech"] = ""
    n = len(srv.requests)
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="voice", text="   ", out=lib / "v.mp3"))
    assert e.value.reason == "config" and not e.value.technical and len(srv.requests) == n


# ── التفريغ ───────────────────────────────────────────────────────────────

def test_transcription_returns_words_with_timing_and_sends_the_right_form(srv, lib):
    audio = lib / "a.wav"
    audio.write_bytes(wav_bytes(1.2))
    m = std_model(srv.base, "stt", std={"model": "whisper-large"}, params={"language": "ar"})
    res = mr.run(m, mr.RunRequest(task="stt", audio=audio))
    assert res.path is None and res.kind is None
    d = res.data
    assert d["text"] == "مرحبا بكم" and d["language"] == "ar"
    assert d["words"] == [{"text": "مرحبا", "start": 0.0, "end": 0.5}, {"text": "بكم", "start": 0.6, "end": 1.1}]
    assert d["segments"] == [{"text": "مرحبا بكم", "start": 0.0, "end": 1.1}]
    f = srv.last("/audio/transcriptions")["fields"]
    assert f["model"] == ["whisper-large"] and f["response_format"] == ["verbose_json"] and f["language"] == ["ar"]
    assert f["timestamp_granularities[]"] == ["word", "segment"] and f["file"][0]["size"] > 1000
    res = mr.run(m, mr.RunRequest(task="stt", audio=audio, language="en"))
    assert srv.last("/audio/transcriptions")["fields"]["language"] == ["en"]


def test_transcription_shapes_other_servers_use(srv, lib):
    audio = lib / "a.wav"
    audio.write_bytes(wav_bytes(1.2))
    m = std_model(srv.base, "stt", std={"model": "w"})
    srv.modes["stt"] = "words_in_segments"
    assert [w["text"] for w in mr.run(m, mr.RunRequest(task="stt", audio=audio)).data["words"]] == ["مرحبا", "بكم"]
    srv.modes["stt"] = "no_words"
    d = mr.run(m, mr.RunRequest(task="stt", audio=audio)).data
    assert d["words"] == [] and d["text"] == "مرحبا بكم" and d["segments"]                 # بلا كلمات: المقاطع بتكفي للتقدير
    srv.modes["stt"] = "empty"
    with pytest.raises(mr.RunError, match="ما رجّع نص") as e:
        mr.run(m, mr.RunRequest(task="stt", audio=audio))
    assert e.value.reason == "bad_output"
    with pytest.raises(mr.RunError, match="ملف صوت") as e:
        mr.run(m, mr.RunRequest(task="stt"))
    assert not e.value.technical


def test_normalize_transcript_drops_broken_words():
    d = link_std.normalize_transcript({"text": " نص ", "words": [{"word": "أ", "start": "0.1", "end": 0.3}, {"word": "", "start": 0, "end": 1},
                                                                  {"word": "ب", "start": 0.5, "end": 0.4}, {"word": "ج"}, "junk"], "segments": ["junk"]})
    assert d == {"text": "نص", "language": "", "words": [{"text": "أ", "start": 0.1, "end": 0.3}], "segments": []}
    assert link_std.normalize_transcript({"segments": [{"text": "س", "start": 0, "end": 1}]})["text"] == "س"


def test_the_std_link_serves_only_image_voice_and_stt(srv, lib):
    ctx = mr.Ctx(std_model(srv.base), mr.RunRequest(task="lipsync"), {}, lib, 1e12)
    with pytest.raises(mr.RunError, match="الصور والصوت والتفريغ") as e:
        link_std.run(ctx)
    assert e.value.reason == "unsupported" and not e.value.technical


def test_an_endless_models_or_error_body_is_cut_while_downloading():
    from endless_server import EndlessServer
    big = EndlessServer(only="/v1/models")
    try:
        r = link_std.probe(big.url + "/v1")
        assert r["ok"] is False and r["reason"] == "bad_output" and "أكبر من الحد" in r["message"] and big.sent < 16 * 1024 * 1024, big.sent
    finally:
        big.stop()
    err = EndlessServer(status=500)
    try:
        r = link_std.probe(err.url + "/v1")
        assert r["ok"] is False and "رد 500" in r["message"] and err.sent < 16 * 1024 * 1024, err.sent
    finally:
        err.stop()
