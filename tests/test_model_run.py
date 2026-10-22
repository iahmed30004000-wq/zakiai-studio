"""model_run: البوابات (تفعيل/رخصة/مهمة/طريقة)، قفل الكرت، فحص الناتج وتحويله، السجل، وتنظيف المؤقت — بمشغّل وهمي."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
import media_check  # noqa: E402
import model_library as ml  # noqa: E402
import model_run as mr  # noqa: E402
import production_log  # noqa: E402
from fake_openai import png_bytes, wav_bytes  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    return tmp_path


def model(task="image", **kw):
    link = kw.pop("link", "command")
    argv = {"image": ["x", "{prompt}", "{out}"], "voice": ["x", "{text}", "{out}"], "stt": ["x", "{audio}", "{out}"], "lipsync": ["x", "{video}", "{audio}", "{out}"],
            "upscale": ["x", "{image}", "{out}"], "bgremove": ["x", "{image}", "{out}"], "music": ["x", "{prompt}", "{out}"], "sfx": ["x", "{prompt}", "{out}"]}[task]
    raw = {"name": "م", "task": task, "link": link, "enabled": True, "licence": {"id": "MIT", "commercial": "yes"}, "command": {"argv": argv}, **kw}
    return ml.create(raw)


def fake(monkeypatch, fn):
    monkeypatch.setattr(mr, "_runner", lambda link: fn)


def write_png(ctx, **kw):
    f = ctx.tmp / "r.png"
    f.write_bytes(png_bytes(**kw))
    return {"file": f, "data": {}}


def tmp_dirs():
    root = mr.tmp_root()
    return list(root.iterdir()) if root.exists() else []


# ── البوابات ──────────────────────────────────────────────────────────────

def test_wrong_task_disabled_and_licence_are_refused_before_anything_runs(lib, monkeypatch):
    called = []
    fake(monkeypatch, lambda ctx: called.append(1) or write_png(ctx))
    m = model("image")
    with pytest.raises(mr.RunError, match="مش لهالمهمة") as e:
        mr.run(m, mr.RunRequest(task="voice", text="x", out=lib / "a.mp3"))
    assert e.value.reason == "unsupported" and not e.value.technical
    off = ml.update(m["id"], {"enabled": False})
    with pytest.raises(mr.RunError, match="معطّل") as e:
        mr.run(off, mr.RunRequest(task="image", prompt="x", out=lib / "a.png"))
    assert e.value.reason == "config" and not e.value.technical
    raw = json.loads(ml.path().read_text(encoding="utf-8"))
    raw["models"][0].update(enabled=True, licence={"id": "NC", "commercial": "no", "confirmed_by_owner": False, "note": ""})
    ml.path().write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(mr.RunError, match="رخصته") as e:
        mr.run(ml.get(m["id"]), mr.RunRequest(task="image", prompt="x", out=lib / "a.png"))
    assert e.value.reason == "licence" and not e.value.technical
    assert called == [] and tmp_dirs() == [] and not (lib / "a.png").exists()


def test_every_open_link_has_a_runner_and_an_unknown_one_says_so(lib):
    for link in ml.LINKS:
        assert mr._runner(link) is not None, link
    assert mr._runner("telepathy") is None
    bad = {"id": "ml_001", "name": "غريب", "task": "music", "link": "telepathy", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"}, "timeout_sec": 30}
    with pytest.raises(mr.RunError, match="لسا مش مفعّل") as e:
        mr.run(bad, mr.RunRequest(task="music", prompt="x", out=lib / "w.mp3"))
    assert e.value.reason == "unsupported" and not e.value.technical


def test_an_output_path_is_required_except_for_transcription(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: write_png(ctx))
    with pytest.raises(mr.RunError, match="ملف الناتج"):
        mr.run(model("image"), mr.RunRequest(task="image", prompt="x"))


# ── الناتج ────────────────────────────────────────────────────────────────

def test_call_params_override_model_params_but_empty_values_do_not(lib, monkeypatch):
    seen = {}
    fake(monkeypatch, lambda ctx: seen.update(ctx.params) or write_png(ctx))
    m = model("image", params={"width": 640, "steps": 20})
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "a.png", params={"width": 320, "steps": "", "height": None, "seed": 7}))
    assert seen == {"width": 320, "steps": 20, "seed": 7}


def test_final_file_is_atomic_and_follows_the_extension(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: write_png(ctx))
    out = lib / "deep" / "er" / "shot.webp"
    res = mr.run(model("image"), mr.RunRequest(task="image", prompt="x", out=out))
    assert out.read_bytes()[:4] == b"RIFF" and res.info["format"] == "PNG" and res.path == out
    assert sorted(p.name for p in out.parent.iterdir()) == ["shot.webp"]                   # بلا ملفات مؤقتة (.part) جنبه


def test_a_bad_output_leaves_no_file_no_part_and_no_temp_dir(lib, monkeypatch):
    def junk(ctx):
        f = ctx.tmp / "r.png"
        f.write_bytes(b"<html>error page</html>")
        return {"file": f, "data": {}}
    fake(monkeypatch, junk)
    out = lib / "o" / "shot.png"
    with pytest.raises(mr.RunError, match="ناتج النموذج مرفوض") as e:
        mr.run(model("image"), mr.RunRequest(task="image", prompt="x", out=out))
    assert e.value.reason == "bad_output" and e.value.technical
    assert not out.exists() and (not out.parent.exists() or list(out.parent.iterdir()) == []) and tmp_dirs() == []


def test_an_existing_file_survives_a_failed_regeneration(lib, monkeypatch):
    out = lib / "shot.png"
    out.write_bytes(png_bytes(300, 300))
    before = out.read_bytes()
    fake(monkeypatch, lambda ctx: {"file": None, "data": {}})
    with pytest.raises(mr.RunError, match="ما كتب ملف ناتج"):
        mr.run(model("image"), mr.RunRequest(task="image", prompt="x", out=out))
    assert out.read_bytes() == before


def test_audio_length_cap_and_video_copy(lib, monkeypatch):
    def wav(ctx):
        f = ctx.tmp / "r.wav"
        f.write_bytes(wav_bytes(0.6))
        return {"file": f, "data": {}}
    fake(monkeypatch, wav)
    with monkeypatch.context() as mp:
        mp.setattr(mr, "MAX_AUDIO_SEC", {"voice": 0.3})
        with pytest.raises(mr.RunError, match="أطول من الحد") as e:
            mr.run(model("voice"), mr.RunRequest(task="voice", text="x", out=lib / "v.mp3"))
        assert e.value.reason == "bad_output"

    def vid(ctx):
        f = ctx.tmp / "r.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-t", "1", "-pix_fmt", "yuv420p", str(f)], capture_output=True, check=True)
        return {"file": f, "data": {}}
    monkeypatch.setattr(mr, "_runner", lambda link: vid)
    res = mr.run(model("lipsync"), mr.RunRequest(task="lipsync", video=lib / "in.mp4", audio=lib / "in.wav", out=lib / "lip.mp4"))
    assert res.kind == "video" and res.info["width"] == 160 and (lib / "lip.mp4").is_file()


def test_transcription_has_data_and_no_file(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: {"file": None, "data": {"text": "نص", "words": [], "segments": [], "language": "ar"}})
    res = mr.run(model("stt"), mr.RunRequest(task="stt", audio=lib / "a.wav"))
    assert res.path is None and res.data["text"] == "نص" and res.kind is None
    fake(monkeypatch, lambda ctx: {"file": None, "data": {"text": "  ", "words": []}})
    with pytest.raises(mr.RunError, match="ما رجّع نص"):
        mr.run(model("stt"), mr.RunRequest(task="stt", audio=lib / "a.wav"))


# ── السجل والأخطاء غير المتوقعة ────────────────────────────────────────────

def test_every_attempt_is_logged_with_the_task_kind_and_link_path(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: write_png(ctx))
    m = model("image")
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "a.png", script_stem="S", shot_id="f9"))
    fake(monkeypatch, lambda ctx: (_ for _ in ()).throw(mr.RunError("وقع", "connection")))
    with pytest.raises(mr.RunError):
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "b.png"))
    ok, bad = production_log.recent(2, "image")[::-1]
    assert (ok["status"], ok["path"], ok["script_stem"], ok["shot_id"], ok["model_id"], ok["model_name"]) == ("ok", "command", "S", "f9", m["id"], "م")
    assert bad["status"] == "failed" and bad["error"] == "connection: وقع"
    stats = production_log.stats("image")
    assert stats["by_path"]["command"] == {"ok": 1, "failed": 1}


def test_a_broken_log_never_breaks_production(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: write_png(ctx))
    import production_log as pl
    monkeypatch.setattr(pl, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db locked")))
    assert mr.run(model("image"), mr.RunRequest(task="image", prompt="x", out=lib / "a.png")).path.is_file()


def test_an_unexpected_exception_becomes_a_generic_technical_error_without_leaking_it(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: (_ for _ in ()).throw(ValueError("password=hunter2 in /srv/secret/path")))
    with pytest.raises(mr.RunError) as e:
        mr.run(model("image"), mr.RunRequest(task="image", prompt="x", out=lib / "a.png"))
    assert e.value.reason == "model_failed" and e.value.technical and "ValueError" in str(e.value) and "hunter2" not in str(e.value)
    assert "hunter2" not in repr(production_log.recent(1)) and tmp_dirs() == []


def test_a_media_task_logs_under_its_own_kind(lib, monkeypatch):
    fake(monkeypatch, lambda ctx: {"file": None, "data": {"text": "x", "words": []}})
    mr.run(model("stt"), mr.RunRequest(task="stt", audio=lib / "a.wav"))
    assert production_log.recent(1, "stt")[0]["status"] == "ok"
    assert set(mr.TASK_KIND.values()) <= set(production_log.KINDS) and set(mr.LINK_PATH.values()) <= set(production_log.PATHS)


# ── قفل الكرت ─────────────────────────────────────────────────────────────

def test_gpu_models_hold_the_shared_lock_while_they_run(lib, monkeypatch):
    pytest.importorskip("filelock")
    from services.engine.gpu import GpuLock
    monkeypatch.setenv("VP_GPU_LOCK_DIR", str(lib / "locks"))
    seen = {}

    def runner(ctx):
        seen["busy"] = GpuLock(lib / "locks").busy()
        return write_png(ctx)
    fake(monkeypatch, runner)
    m = model("image")
    assert m["uses_gpu"] is True
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "a.png"))
    assert seen["busy"] is True and GpuLock(lib / "locks").busy() is False                # انمسك وقت التشغيل وانفرج بعده
    cpu = ml.update(m["id"], {"uses_gpu": False})
    mr.run(cpu, mr.RunRequest(task="image", prompt="x", out=lib / "b.png"))
    assert seen["busy"] is False                                                           # نموذج ما بيستعمل الكرت: بلا قفل


def test_a_busy_gpu_is_a_technical_busy_error_and_cancel_while_waiting_is_not(lib, monkeypatch):
    pytest.importorskip("filelock")
    from services.engine.gpu import GpuLock
    monkeypatch.setenv("VP_GPU_LOCK_DIR", str(lib / "locks"))
    ran = []
    fake(monkeypatch, lambda ctx: ran.append(1) or write_png(ctx))
    got, done = threading.Event(), threading.Event()

    def other_box():
        lock = GpuLock(lib / "locks")
        assert lock.acquire(timeout=2)
        got.set()
        done.wait(30)
        lock.release()
    t = threading.Thread(target=other_box)
    t.start()
    assert got.wait(3)
    try:
        m = model("image")
        m["timeout_sec"] = 1
        with pytest.raises(mr.RunError, match="الكرت مشغول") as e:
            mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "a.png"))
        assert e.value.reason == "busy" and e.value.technical
        ev = threading.Event()
        threading.Timer(0.4, ev.set).start()
        m["timeout_sec"] = 30
        with pytest.raises(mr.RunError) as e:
            mr.run(m, mr.RunRequest(task="image", prompt="x", out=lib / "b.png", cancel=ev))
        assert e.value.reason == "cancelled" and not e.value.technical
        assert ran == [] and tmp_dirs() == []
    finally:
        done.set()
        t.join()
