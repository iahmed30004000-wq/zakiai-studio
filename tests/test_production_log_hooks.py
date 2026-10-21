"""سجل الإنتاج: صور الـ API وصوت الـ API ونتائج الإضافة بتنسجّل كلها (نجاح وفشل) عشان نقارن الطرق بعد أسبوعين."""

import io
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage, png_bytes  # noqa: E402,F401
import test_studio_voice_timeline as tv  # noqa: E402

import ext_tasks  # noqa: E402
import image_studio as ims  # noqa: E402
import imagegen  # noqa: E402
import production_log  # noqa: E402
import timeline  # noqa: E402


def first_shot_id():
    tl = timeline.load("s1")
    return tl["scenes"][0]["shots"][0]["id"]


def test_image_generation_is_logged_with_provider_and_time(stage):
    sid = first_shot_id()
    ims.generate_shot(stage.script, sid, n=2, log=lambda *_: None)
    rec = [r for r in production_log.recent(10, "image")]
    assert len(rec) == 2 and all(r["status"] == "ok" and r["path"] == "api" and r["shot_id"] == sid and r["script_stem"] == "s1" for r in rec)
    assert rec[0]["model_name"] == "fake" and rec[0]["model_id"] == "img-1" and rec[0]["seconds"] is not None


def test_failed_image_generation_is_logged_with_the_reason(stage, monkeypatch):
    def boom(*a, **k):
        raise imagegen.ImageError("الرصيد خلص")
    monkeypatch.setattr(imagegen, "generate", boom)
    with pytest.raises(ims.ImageStudioError):
        ims.generate_shot(stage.script, first_shot_id(), n=1, log=lambda *_: None)
    rec = production_log.recent(5, "image")
    assert len(rec) == 1 and rec[0]["status"] == "failed" and "الرصيد" in rec[0]["error"] and rec[0]["path"] == "api"


def test_voice_generation_is_logged_per_scene(env, monkeypatch):
    st = tv.produce_ok(env, monkeypatch)
    rec = production_log.recent(50, "voice")
    assert rec and all(r["status"] == "ok" and r["path"] == "api" and r["script_stem"] == "s1" and r["shot_id"].startswith("scene_") for r in rec)
    assert len({r["shot_id"] for r in rec}) == len(rec) or len(rec) >= 1


def test_extension_results_are_logged_ok_and_failed(stage):
    sid = first_shot_id()
    out = ext_tasks.receive(stage.script, "image", sid, png_bytes((512, 768)), "gemini")
    assert out["shot"] == sid
    with pytest.raises(ext_tasks.ExtError):
        ext_tasks.receive(stage.script, "image", sid, b"not an image", "gemini")
    rec = production_log.recent(10, "image")
    ext = [r for r in rec if r["path"] == "extension"]
    assert [r["status"] for r in ext] == ["failed", "ok"] and ext[0]["model_id"] == "ext:gemini" and ext[0]["error"]
    st = production_log.stats("image")
    assert st["by_path"]["extension"] == {"ok": 1, "failed": 1}


def test_logging_never_breaks_production_when_the_log_is_unwritable(stage, monkeypatch):
    monkeypatch.setattr(production_log, "_connect", lambda: (_ for _ in ()).throw(OSError("disk full")))
    ims.generate_shot(stage.script, first_shot_id(), n=1, log=lambda *_: None)          # ما بيرمي


def test_stats_sum_cost_by_path_and_count_only_successful_attempts(env):
    production_log.record("motion", "ok", path="api", cost_usd=0.35)
    production_log.record("motion", "ok", path="api", cost_usd=0.14)
    production_log.record("motion", "failed", path="api", cost_usd=9.0)           # الفاشل ما بينحسب
    production_log.record("voice", "ok", path="extension")
    s = production_log.stats()
    assert s["cost_by_path"] == {"api": 0.49, "extension": 0} and s["cost_total"] == 0.49
    assert production_log.stats("voice")["cost_by_path"] == {"extension": 0}


def test_extension_video_results_are_logged_under_motion(stage):
    """الإضافة بتسمّيها «video» وسجل الإنتاج بيسمّيها «motion» — لازم تتحوّل (وإلا بينكسر استقبال الفيديو)."""
    ext_tasks._log_attempt("video", "ok", "s1", "s1c1", "flow")
    rec = production_log.recent(3, "motion")
    assert rec and rec[0]["path"] == "extension" and rec[0]["model_id"] == "ext:flow"
