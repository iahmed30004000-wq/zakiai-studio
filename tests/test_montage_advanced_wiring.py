"""ربط المونتاج المتقدّم (Remotion) بالمحطة ١٠: الرندر نفسه مزيّف هون (الاختبار الحقيقي بـ test_advanced_montage.py)."""

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage  # noqa: E402,F401
from test_studio_motion import ready  # noqa: E402,F401
from test_studio_montage import animated, SMALL, client  # noqa: E402,F401

import montage  # noqa: E402
import montage_advanced  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
from services.advanced_montage import pipeline  # noqa: E402
from services.advanced_montage.errors import RenderError  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def fake_video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=108x192:d=1:r=30", "-f", "lavfi", "-i", "sine=d=1",
                    "-shortest", "-pix_fmt", "yuv420p", str(path)], capture_output=True, check=True)
    return path


def with_preview(animated):
    montage.render(animated.script, "preview", SMALL, log=lambda *_: None)


def test_advanced_final_records_the_same_shape_as_the_normal_final(animated, monkeypatch):
    with_preview(animated)
    out = animated.env.lib / "exports" / "VP-testp-1-v1.mp4"
    monkeypatch.setattr(pipeline, "render_script", lambda *a, **k: {"published": fake_video(out), "errors": [], "seconds": 3.2, "job": {}})
    r = montage_advanced.run(animated.script, log=lambda *_: None)
    rec = timeline.load("s1")["render"]["final"]
    assert r["file"] == "exports/VP-testp-1-v1.mp4" and rec["file"] == r["file"] and rec["engine"] == "remotion"
    assert set(rec) >= {"file", "at", "size", "duration_ms", "ahat", "captions"} and ":\\" not in str(rec)
    assert studio_state.state_of("s1", 10) == "approved"


def test_advanced_needs_a_preview_first(animated):
    with pytest.raises(montage.MontageError, match="معاينة"):
        montage_advanced.run(animated.script, log=lambda *_: None)


@pytest.mark.parametrize("boom", [RenderError("Node.js مش مثبّت"), None])
def test_failed_advanced_leaves_the_previous_normal_final_untouched(animated, monkeypatch, boom):
    with_preview(animated)
    montage.render(animated.script, "final", SMALL, log=lambda *_: None)
    before = timeline.load("s1")["render"]["final"]
    exp = animated.env.lib / before["file"]
    size_before = exp.stat().st_size
    def fake(*a, **k):
        if boom:
            raise boom
        return {"published": None, "errors": ["المدة غلط"], "seconds": 1, "job": {}, "video": exp}
    monkeypatch.setattr(pipeline, "render_script", fake)
    with pytest.raises(montage.MontageError):
        montage_advanced.run(animated.script, log=lambda *_: None)
    assert timeline.load("s1")["render"]["final"] == before and exp.stat().st_size == size_before
    assert studio_state.state_of("s1", 10) == "approved"


def test_route_accepts_advanced_only_after_a_preview(animated):
    c = client()
    assert c.post("/api/studio/s1.json/montage/render?mode=advanced").status_code == 409
    with_preview(animated)
    assert c.post("/api/studio/s1.json/montage/render?mode=advanced").status_code == 200
    assert animated.env.jobs[-1]["cmd"][0] == "montage_advanced.py"
    assert c.post("/api/studio/s1.json/montage/render?mode=bogus").status_code == 400


def test_doctor_route_reports_missing_environment_in_arabic(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_montage
    from services.advanced_montage.renderers import remotion_engine as eng

    def nope():
        raise RenderError("Node.js مش مثبّت")
    monkeypatch.setattr(eng, "ensure_ready", nope)
    app = FastAPI()
    app.include_router(routes_montage.router)
    d = TestClient(app).get("/api/montage/advanced/doctor").json()
    assert d["ready"] is False and "Node" in d["message"]


# ───────── المحرّك الافتراضي للتصدير النهائي ─────────
def test_engine_setting_defaults_to_ffmpeg_and_is_reported(animated, monkeypatch):
    import settings_io
    assert client().get("/api/studio/s1.json/montage/info").json()["final_engine"] == "ffmpeg"
    monkeypatch.setattr(settings_io, "load", lambda *a, **k: {"MONTAGE_FINAL_ENGINE": "remotion"})
    assert client().get("/api/studio/s1.json/montage/info").json()["final_engine"] == "remotion"
    monkeypatch.setattr(settings_io, "load", lambda *a, **k: {"MONTAGE_FINAL_ENGINE": "garbage"})
    assert client().get("/api/studio/s1.json/montage/info").json()["final_engine"] == "ffmpeg"


def test_engine_is_an_overridable_setting():
    import config
    assert "MONTAGE_FINAL_ENGINE" in config.OVERRIDABLE and config.MONTAGE_FINAL_ENGINE == "ffmpeg"


def run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["montage.py", *argv])
    montage.main()


def test_final_with_remotion_engine_uses_advanced_and_skips_ffmpeg(animated, monkeypatch, capsys):
    with_preview(animated)
    monkeypatch.setattr(montage.config, "MONTAGE_FINAL_ENGINE", "remotion", raising=False)
    calls = []
    monkeypatch.setattr(montage_advanced, "run", lambda path, log=print: calls.append("adv") or {"mode": "advanced"})
    monkeypatch.setattr(montage, "render", lambda *a, **k: calls.append("ffmpeg") or {})
    run_main(monkeypatch, "final", str(animated.script))
    assert calls == ["adv"]


@pytest.mark.parametrize("boom", [montage.MontageError("Chrome مش موجود"), KeyError("x")])
def test_advanced_failure_falls_back_to_the_normal_final(animated, monkeypatch, capsys, boom):
    with_preview(animated)
    monkeypatch.setattr(montage.config, "MONTAGE_FINAL_ENGINE", "remotion", raising=False)

    def bad(path, log=print):
        raise boom
    monkeypatch.setattr(montage_advanced, "run", bad)
    run_main(monkeypatch, "final", str(animated.script))
    out = capsys.readouterr().out
    assert "فشل المونتاج المتقدّم" in out and "ffmpeg" in out
    rec = timeline.load("s1")["render"]["final"]
    assert rec["file"] == "exports/VP-testp-1-v1.mp4" and "engine" not in rec            # طلع بالعادي فعلاً


def test_preview_and_default_final_never_touch_remotion(animated, monkeypatch):
    monkeypatch.setattr(montage_advanced, "run", lambda *a, **k: pytest.fail("ما لازم ينادى"))
    monkeypatch.setattr(montage.config, "MONTAGE_FINAL_ENGINE", "remotion", raising=False)
    run_main(monkeypatch, "preview", str(animated.script))                                # المعاينة دايماً ffmpeg
    monkeypatch.setattr(montage.config, "MONTAGE_FINAL_ENGINE", "ffmpeg", raising=False)
    run_main(monkeypatch, "final", str(animated.script))
