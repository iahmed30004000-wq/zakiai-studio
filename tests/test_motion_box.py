"""التحريك عبر صندوق الأوزان العام: موديل التحريك kind=http + model (اسم مجلد الأوزان). صندوق حقيقي (fake-images) على uvicorn بخيط."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import motion  # noqa: E402
from engine_box import box_factory, png  # noqa: E402,F401  (fixture + مساعد)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


@pytest.fixture(autouse=True)
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    monkeypatch.setattr(motion, "HTTP_POLL_SEC", 0.05)


def general(url, model, mode="i2v", **http):
    return {"name": f"عام {model}", "kind": "http", "max_sec": 6, "vram_gb": 4, "speed_sec_per_sec": 30,
            "http": {"url": url, "mode": mode, "model": model, **http}}


def test_run_http_sends_the_model_name_and_returns_a_video(tmp_path, box_factory):
    box = box_factory()
    m = motion.upsert_model(general(box.url, "demo-video"))
    assert m["http"]["model"] == "demo-video"
    src = tmp_path / "frame.png"
    src.write_bytes(png((64, 96)))
    raw = tmp_path / "raw.mp4"
    logs = []
    motion._run_http(m, src, "حرّك العبوة", 1.0, 64, 96, raw, 30, logs.append)
    assert raw.exists() and raw.read_bytes()[4:8] == b"ftyp"
    job = next(iter(box.jobs.values()))
    assert job.params["model"] == "demo-video" and job.params["mode"] == "i2v" and job.purged is True
    t2v = motion.upsert_model(general(box.url, "demo-video", mode="t2v"))
    raw2 = tmp_path / "raw2.mp4"
    motion._run_http(t2v, None, "مشهد", 1.0, 64, 96, raw2, 30, logs.append)
    assert raw2.exists()


def test_old_fixed_boxes_get_no_model_key(tmp_path, box_factory):
    box = box_factory(backend="fake")
    m = motion.upsert_model({"name": "ثابت", "kind": "http", "max_sec": 6, "http": {"url": box.url, "mode": "i2v"}})
    assert m["http"]["model"] is None
    src = tmp_path / "frame.png"
    src.write_bytes(png((64, 96)))
    motion._run_http(m, src, "x", 1.0, 64, 96, tmp_path / "r.mp4", 30, lambda *_: None)
    assert "model" not in next(iter(box.jobs.values())).params


def test_probe_checks_the_model_exists_is_safe_and_supports_the_mode(box_factory):
    box = box_factory()
    ok = motion.probe(motion.upsert_model(general(box.url, "demo-video"))["id"])
    assert ok["ok"] is True and ok["backend"] == "fake-images" and "loaded_model" in ok and "gpu" in ok
    cases = [("Ghost", "i2v", "مش موجود بمجلد أوزان"), ("demo-unsafe", "i2v", "مرفوض"), ("demo-image", "i2v", "ما بيدعم الوضع i2v"),
            ]
    for model, mode, needle in cases[:3]:
        p = motion.probe(motion.upsert_model(general(box.url, model, mode=mode))["id"])
        assert p["ok"] is False and needle in p["reason"], (model, p)


def test_probe_on_a_fixed_model_box_refuses_a_model_name_and_a_box_without_the_mode(box_factory):
    import http.server
    import json
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "backend": "ltx", "tasks": ["i2v"], "loaded": False, "queued": 0, "running": 0}).encode()
            self.send_response(404 if self.path.startswith("/jobs/probe-token") else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        p = motion.probe(motion.upsert_model(general(url, "demo-video"))["id"])
        assert p["ok"] is False and "نموذج ثابت" in p["reason"]                   # صندوق قديم (بلا api) ما بيعرف أسماء نماذج
        t = motion.probe(motion.upsert_model({"name": "ت", "kind": "http", "max_sec": 5, "http": {"url": url, "mode": "t2v"}})["id"])
        assert t["ok"] is False and "ما بيدعم الوضع t2v" in t["reason"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_rank_models_accepts_a_general_box_model_like_any_http_model():
    shot = {"id": "s1c1", "type": "close", "start_ms": 0, "end_ms": 3000, "motion_desc": "", "refs": {}}
    m = motion.upsert_model({**general("http://engine:8000", "Wan2.2-TI2V-5B-Diffusers"), "strengths": ["product", "realism"], "vram_gb": 24})
    rk = motion.rank_models(shot, [m], vram_gb=48)
    assert [r["model"]["id"] for r in rk["ranked"]] == [m["id"]]
    small = motion.rank_models(shot, [m], vram_gb=16)                          # كرت أصغر من اللازم: استبعاد بسبب مكتوب
    assert not small["ranked"] and "24GB" in small["excluded"][0]["reason"]
