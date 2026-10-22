"""ربط «برنامج نموذج» (app) بمكتبة النماذج: التحقق الصارم من كتلة app، والتشغيل عبر model_run على سيرفر Gradio وهمي، والرجوع للطريقة الحالية."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
import link_app  # noqa: E402
import model_library as ml  # noqa: E402
import model_run as mr  # noqa: E402
from fake_gradio import FakeGradio, wav_bytes  # noqa: E402

URL = "http://127.0.0.1:7860"
LIC = {"id": "Apache-2.0", "commercial": "yes"}


@pytest.fixture(autouse=True)
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    link_app.clear_cache()
    yield tmp_path
    link_app.clear_cache()


@pytest.fixture
def gr():
    s = FakeGradio("6").start()
    yield s
    s.stop()


def app_model(task="music", **app):
    base = {"url": URL, "api_name": "/generate", "inputs": [{"param": "prompt", "from": "prompt"}]}
    base.update(app)
    return {"name": "برنامج", "task": task, "link": "app", "licence": LIC, "app": base}


# ── التحقق ────────────────────────────────────────────────────────────────
def test_a_valid_app_model_is_stored_in_its_normal_form():
    m = ml.create(app_model(api_name="generate", inputs=[{"param": "prompt", "from": "prompt"}, {"param": "seed", "const": 7.0}, {"param": "style", "const": "x"},
                                                           {"param": "flag", "const": True}, {"param": "nothing", "const": None}]))
    assert m["link"] == "app" and m["uses_gpu"] is True and m["enabled"] is False
    assert m["app"] == {"url": URL, "api_name": "/generate", "inputs": [{"param": "prompt", "from": "prompt"}, {"param": "seed", "const": 7.0}, {"param": "style", "const": "x"},
                                                                          {"param": "flag", "const": True}, {"param": "nothing", "const": None}],
                        "output": {"index": None}, "schema_hash": None}
    assert "weights" not in m and "std" not in m and "command" not in m
    raw = json.loads(ml.path().read_text(encoding="utf-8"))
    assert raw["models"][0]["app"]["api_name"] == "/generate"
    u = ml.update(m["id"], {"app": {**m["app"], "output": {"index": 2}, "schema_hash": "abcdef0123456789"}})
    assert u["app"]["output"] == {"index": 2} and u["app"]["schema_hash"] == "abcdef0123456789" and u["task"] == "music"


@pytest.mark.parametrize("patch,msg", [
    ({"url": "http://example.com:7860"}, "المضيف مش مسموح"),
    ({"url": "https://127.0.0.1:7860"}, "http://"),
    ({"url": "http://127.0.0.1"}, "المنفذ"),
    ({"url": "http://127.0.0.1:7860/path"}, "بدون مسار"),
    ({"url": ""}, "مطلوب"),
    ({"api_name": ""}, "مطلوب"),
    ({"api_name": "/a b"}, "اسم النقطة"),
    ({"api_name": "/../etc"}, "اسم النقطة"),
    ({"api_name": "/x?y=1"}, "اسم النقطة"),
    ({"inputs": "prompt"}, "قائمة"),
    ({"inputs": [{"param": f"p{i}", "from": "prompt"} for i in range(61)]}, "لحد 60"),
    ({"inputs": [{"param": "prompt", "from": "prompt"}, {"param": "prompt", "const": 1}]}, "مكرّر"),
    ({"inputs": [{"param": "bad name", "from": "prompt"}]}, "غير صالح"),
    ({"inputs": [{"param": "prompt", "from": "prompt", "const": 1}]}, "param مع from"),
    ({"inputs": [{"param": "prompt"}]}, "param مع from"),
    ({"inputs": [{"param": "prompt", "from": "weather"}]}, "غير معروف"),
    ({"inputs": [{"param": "prompt", "from": "prompt"}, {"param": "x", "const": [1]}]}, "نص أو رقم"),
    ({"inputs": [{"param": "prompt", "from": "prompt"}, {"param": "x", "const": {"a": 1}}]}, "نص أو رقم"),
    ({"inputs": [{"param": "prompt", "from": "prompt"}, {"param": "x", "const": float("nan")}]}, "رقم غير صالح"),
    ({"inputs": [{"param": "prompt", "from": "prompt"}, {"param": "x", "const": "x" * 501}]}, "أطول من 500"),
    ({"inputs": [{"param": "prompt", "from": "prompt", "extra": 1}]}, "param مع from"),
    ({"inputs": []}, "لازم تربط معامل بـ prompt"),
    ({"output": {"index": 99}}, "خارج المعقول"),
    ({"output": {"index": "x"}}, "لازم رقم"),
    ({"output": {"kind": "image"}}, "index بس"),
    ({"schema_hash": "XYZ"}, "بصمة"),
    ({"surprise": 1}, "حقول غير معروفة"),
])
def test_strict_validation_of_the_app_block(patch, msg):
    with pytest.raises(ml.ModelLibraryError, match=msg):
        ml.create(app_model(**patch))
    assert ml.load()["models"] == []


@pytest.mark.parametrize("task,good,missing", [
    ("music", [{"param": "p", "from": "prompt"}], [{"param": "s", "from": "seconds"}]),
    ("sfx", [{"param": "p", "from": "prompt"}], []),
    ("voice", [{"param": "t", "from": "text"}], [{"param": "p", "from": "prompt"}]),
    ("stt", [{"param": "a", "from": "audio"}], [{"param": "t", "from": "text"}]),
    ("upscale", [{"param": "i", "from": "image"}], [{"param": "a", "from": "audio"}]),
    ("bgremove", [{"param": "i", "from": "image"}], []),
    ("image", [{"param": "p", "from": "prompt"}], [{"param": "i", "from": "image"}]),
    ("lipsync", [{"param": "v", "from": "video"}, {"param": "a", "from": "audio"}], [{"param": "i", "from": "image"}]),
])
def test_each_task_needs_its_own_inputs_mapped(task, good, missing):
    m = ml.create(app_model(task, inputs=good))
    assert m["task"] == task
    if missing:
        with pytest.raises(ml.ModelLibraryError, match="لازم تربط معامل بـ"):
            ml.create(app_model(task, inputs=missing))
    if task == "lipsync":
        assert ml.create(app_model(task, inputs=[{"param": "i", "from": "image"}, {"param": "a", "from": "audio"}]))                      # صورة + صوت بتكفي (مزامنة صورة)


def test_the_sources_list_stays_in_sync_between_library_and_client():
    assert ml.APP_SOURCES == link_app.SOURCES and ml.OPEN_LINKS == ("weights", "app", "std", "command")


def test_app_templates_are_open_and_make_valid_models_when_the_blanks_are_filled():
    ts = {t["id"]: t for t in ml.templates()}
    for tid, task in (("ace-step", "music"), ("wan22-s2v", "lipsync"), ("latentsync", "lipsync")):
        assert ts[tid]["link"] == "app" and ts[tid]["task"] == task
        raw = {"name": ts[tid]["name"], "task": task, "link": "app", "template": tid, "licence": {**ts[tid]["licence"]}, **json.loads(json.dumps(ts[tid]["defaults"]))}
        raw["app"] = {"url": URL, "api_name": "/run", "inputs": [{"param": "prompt", "from": "prompt"}] if task == "music" else
                      [{"param": "video", "from": "video"}, {"param": "audio", "from": "audio"}]}
        m = ml.create(raw)
        assert m["template"] == tid and m["uses_gpu"] is True
    assert ts["latentsync"]["licence"]["commercial"] == "no"
    with pytest.raises(ml.ModelLibraryError, match="بتمنع"):
        ml.update(ml.list_models()[-1]["id"], {"enabled": True})                          # ممنوعة تجارياً: ما بتتفعّل أبداً


# ── التشغيل عبر المكتبة ───────────────────────────────────────────────────
def test_run_through_the_library_converts_the_output_to_the_requested_file_type(gr, lib):
    m = ml.create({**app_model("music", url=gr.url, api_name="/music", inputs=[{"param": "prompt", "from": "prompt"}, {"param": "seconds", "from": "seconds"}]), "enabled": True})
    res = mr.run(m, mr.RunRequest(task="music", prompt="calm", seconds=1.0, out=lib / "m.mp3", record=False))
    import media_check
    assert res.path == lib / "m.mp3" and res.kind == "audio" and res.info["format"] == "wav"                  # الأصل wav
    assert media_check.check(res.path, "audio")["format"] == "mp3"                                                 # والنهائي mp3 (حسب امتداد الملف)
    img = ml.create({**app_model("image", url=gr.url, api_name="/generate", inputs=[{"param": "prompt", "from": "prompt"}, {"param": "width", "from": "width"}, {"param": "height", "from": "height"}]),
                     "enabled": True, "params": {"width": 256, "height": 384}})
    r2 = mr.run(img, mr.RunRequest(task="image", prompt="x", out=lib / "i.png", record=False))
    with Image.open(r2.path) as im:
        assert im.format == "PNG" and im.size == (256, 384)                                          # الناتج WebP تحوّل PNG حسب امتداد الملف النهائي


def test_the_attempt_is_recorded_in_the_production_log_as_an_app_path(gr, lib):
    import production_log
    m = ml.create({**app_model("music", url=gr.url, api_name="/music", inputs=[{"param": "prompt", "from": "prompt"}]), "enabled": True})
    mr.run(m, mr.RunRequest(task="music", prompt="calm", out=lib / "m.mp3", script_stem="s1", shot_id="m1"))
    row = [r for r in production_log.recent(20) if r.get("model_id") == m["id"]][0]
    assert row["kind"] == "music" and row["path"] == "app" and row["status"] == "ok"
    gr.modes["music"] = "error_null"
    with pytest.raises(mr.RunError):
        mr.run(m, mr.RunRequest(task="music", prompt="calm", out=lib / "m2.mp3", script_stem="s1", shot_id="m2"))
    bad = [r for r in production_log.recent(20) if r.get("shot_id") == "m2"][0]
    assert bad["status"] == "failed" and bad["path"] == "app"


def test_image_falls_back_to_the_current_way_when_the_app_breaks_but_music_never_does(gr, lib):
    img = ml.create({**app_model("image", url=gr.url, api_name="/generate", inputs=[{"param": "prompt", "from": "prompt"}]), "enabled": True})
    ml.set_default("image", img["id"])
    gr.modes["generate"] = "error_null"
    res, note = mr.run_via_library("image", mr.RunRequest(task="image", prompt="x", out=lib / "i.png", record=False))
    assert res is None and "وقع" in note and "الطريقة الحالية" in note
    mus = ml.create({**app_model("music", url=gr.url, api_name="/music", inputs=[{"param": "prompt", "from": "prompt"}]), "enabled": True})
    ml.set_default("music", mus["id"])
    gr.modes["music"] = "error_null"
    with pytest.raises(RuntimeError, match="البرنامج فشل"):
        mr.run_via_library("music", mr.RunRequest(task="music", prompt="x", out=lib / "m.mp3", record=False))              # الموسيقى بلا احتياط


def test_try_screen_runs_an_app_model_before_enabling(gr, lib):
    import model_tasks
    m = ml.create(app_model("music", url=gr.url, api_name="/music", inputs=[{"param": "prompt", "from": "prompt"}, {"param": "seconds", "from": "seconds"}]))      # معطّل
    assert m["enabled"] is False
    model_tasks.save_params(m["id"], {"prompt": "calm piano", "seconds": 1})
    last = model_tasks.run_try(m["id"], log=lambda *_: None)
    assert last["ok"] is True and last["kind"] == "audio" and (model_tasks.test_dir(m["id"]) / "result.mp3").exists()
    assert gr.calls[-1]["data"][0] == "calm piano"
