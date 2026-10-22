"""رفع صورة أو فيديو من المالك للقطة بالمهمة الموجّهة (POST /shots/{id}/upload): بنفس شروط التوليد/التحريك، واختيار تلقائي، ومدة الفيديو بتتظبط."""

import io
import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_studio_images import stage  # noqa: E402,F401
from test_ext_tasks import ready  # noqa: E402,F401
from test_free_media import make_video  # noqa: E402

import config  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def client():
    from web import routes_studio
    app = FastAPI()
    app.include_router(routes_studio.router)
    return TestClient(app)


def png_bytes(w=720, h=1280, color=(30, 160, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def shot(sid="s1c1"):
    return ims._shot(timeline.load("s1"), sid)[1]


def url(sid="s1c1"):
    return f"/api/studio/s1.json/shots/{sid}/upload"


# ───────────────────────── صورة ─────────────────────────
def test_image_upload_becomes_a_candidate_is_chosen_and_the_station_waits_for_the_owner(stage):
    c = client()
    before = len(shot()["image"]["candidates"])
    r = c.post(url(), files={"file": ("mine.png", png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    sh = shot()
    cand = sh["image"]["candidates"][-1]
    assert len(sh["image"]["candidates"]) == before + 1 and cand["provider"] == "upload" and cand["model"] == "owner"
    assert sh["image"]["path_used"] == "upload" and sh["image"]["chosen"].endswith("_1080.png") and sh["image"]["source"] == cand["path"]
    f = ims.abs_of("s1", sh["image"]["chosen"])
    assert f and Image.open(f).size == (1080, 1920)
    assert studio_state.state_of("s1", 7) == "awaiting_choice"
    assert r.json()["shot"]["id"] == "s1c1" and r.json()["warnings"] == []


def test_image_upload_is_closed_until_the_image_station_opens_and_checks_the_file(env):
    env.script_file("g.json", make_script())
    r = client().post("/api/studio/g.json/shots/s1c1/upload", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 409


def test_bad_images_and_unknown_shots_are_refused_without_changing_anything(stage):
    c = client()
    n = len(shot()["image"]["candidates"])
    assert c.post(url(), files={"file": ("small.png", png_bytes(100, 100), "image/png")}).status_code == 400
    assert c.post(url(), files={"file": ("fake.png", b"not an image", "image/png")}).status_code == 400
    assert c.post(url(), files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400
    assert c.post(url("s9c9"), files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 409
    assert len(shot()["image"]["candidates"]) == n


# ───────────────────────── فيديو ─────────────────────────
def shot_seconds(sid="s1c1"):
    sh = shot(sid)
    return (sh["end_ms"] - sh["start_ms"]) / 1000


def test_video_upload_is_fitted_to_the_shot_length_chosen_and_the_station_waits(ready, tmp_path):
    c = client()
    sec = shot_seconds()
    longer = make_video(tmp_path / "v.mp4", sec + 1.5, audio=True, size="160x288")
    r = c.post(url(), files={"file": ("v.mp4", longer.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    sh = shot()
    cand = sh["motion_candidates"][-1]
    assert cand["model_id"] == "upload" and cand["model_name"] == "رفع يدوي" and cand["fit"] == "trimmed" and cand["duration_ms"] == sh["end_ms"] - sh["start_ms"]
    assert sh["motion"]["clip"] == cand["clip"] and sh["motion"]["model_id"] == "upload" and sh["motion"]["duration_ms"] == cand["duration_ms"]
    f = motion.abs_of("s1", cand["clip"])
    assert f and abs(motion.probe_duration(f) - sec) < 0.1
    assert studio_state.state_of("s1", 9) == "awaiting_choice"
    assert any("صوت الفيديو" in w for w in r.json()["warnings"])                  # الصوت من الفويس أوفر مش من الفيديو


def test_video_slightly_shorter_is_stretched_and_much_shorter_is_refused_in_arabic(ready, tmp_path):
    c = client()
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    near, far = ids[1], ids[2]
    r = c.post(url(near), files={"file": ("v.mp4", make_video(tmp_path / "a.mp4", shot_seconds(near) * 0.92, size="160x288").read_bytes(), "video/mp4")})
    assert r.status_code == 200 and shot(near)["motion_candidates"][-1]["fit"] == "stretched"
    r = c.post(url(far), files={"file": ("v.mp4", make_video(tmp_path / "b.mp4", max(0.6, shot_seconds(far) * 0.5), size="160x288").read_bytes(), "video/mp4")})
    assert r.status_code == 409 and "الفيديو اللي رفعته مدته" in r.json()["detail"] and "الموديل" not in r.json()["detail"]
    assert not shot(far).get("motion_candidates") and not shot(far).get("motion")


def test_video_upload_is_closed_before_the_motion_station_and_rejects_non_video(stage, ready, tmp_path):
    c = client()
    r = c.post(url(), files={"file": ("v.mp4", b"not a video at all", "video/mp4")})
    assert r.status_code == 400
    a = make_video(tmp_path / "ok.mp4", shot_seconds(), size="160x288")
    assert c.post(url(), files={"file": ("ok.mp4", a.read_bytes(), "video/mp4")}).status_code == 200


def test_video_upload_before_images_and_match_are_approved_is_a_409(stage, tmp_path):
    c = client()                                                           # `stage` بس: الصور والتطابق ما اتعتمدوا ← المحطة 9 مقفولة
    a = make_video(tmp_path / "ok.mp4", shot_seconds(), size="160x288")
    r = c.post(url(), files={"file": ("ok.mp4", a.read_bytes(), "video/mp4")})
    assert r.status_code == 409 and not shot().get("motion_candidates")
