"""عقد الصندوق v2 (services/engine): صور/تعديل بمراجع/تكبير/فيديو، /models، /health (api, gpu, loaded_model)، والصناديق القديمة بلا تغيير.
بالخلفية التجريبية fake-images — بلا كرت ولا diffusers."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.dirname(__file__))

from services.engine import app as engine_app  # noqa: E402
from services.engine.app import Settings, create_app  # noqa: E402
from services.engine.backends.fake import FakeImagesBackend  # noqa: E402


def png(size=(32, 48), color=(10, 120, 200)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def engines(tmp_path):
    stack = contextlib.ExitStack()

    def make(name="a", backend="fake-images", **over):
        s = Settings(backend=backend, name=name, outputs=tmp_path / f"out_{name}", lock_dir=tmp_path / "locks", weights_dir=tmp_path / "weights",
                     lock_poll_sec=0.05, **over)
        app = create_app(s)
        return stack.enter_context(TestClient(app)), app

    yield make
    stack.close()


def submit(c, files=None, token=None, **params):
    h = {"X-Engine-Token": token} if token else {}
    return c.post("/jobs", data={"params": json.dumps(params)}, files=files, headers=h)


def wait(c, jid, token=None, timeout=25):
    h = {"X-Engine-Token": token} if token else {}
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/jobs/{jid}", headers=h).json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.03)
    raise AssertionError(f"المهمة ما خلصت: {j}")


def fetch(c, jid):
    r = c.get(f"/jobs/{jid}/result")
    assert r.status_code == 200, r.text
    return r


def img_of(r) -> Image.Image:
    im = Image.open(io.BytesIO(r.content))
    im.load()
    return im


# ── الصحة والقائمة ───────────────────────────────────────────────────────
def test_health_reports_api_version_gpu_memory_and_the_loaded_model(engines, monkeypatch):
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, mem_get_info=lambda: (10 * 1024 ** 3, 24 * 1024 ** 3)))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    c, _ = engines()
    h = c.get("/health").json()
    assert h["api"] == 2 and h["backend"] == "fake-images" and h["tasks"] == ["t2i", "i2i", "upscale", "t2v", "i2v", "t2a"]
    assert h["gpu"] == {"free_gb": 10.0, "total_gb": 24.0} and h["loaded_model"] is None
    wait(c, submit(c, mode="t2i", model="demo-image", prompt="x").json()["id"])
    assert c.get("/health").json()["loaded_model"] == "demo-image"
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)))
    assert c.get("/health").json()["gpu"] is None                          # بلا كرت: ما في أرقام (مش صفر)


def test_models_listing_is_token_protected_and_shows_why_a_model_is_refused(engines):
    c, _ = engines(token="tok-FAKE-1")
    assert c.get("/models").status_code == 401 and c.get("/models", headers={"X-Engine-Token": "x"}).status_code == 401
    r = c.get("/models", params={"refresh": 1}, headers={"X-Engine-Token": "tok-FAKE-1"})
    assert r.status_code == 200
    d = r.json()
    by = {m["name"]: m for m in d["models"]}
    assert d["api"] == 2 and d["backend"] == "fake-images" and by["demo-image"]["tasks"] == ["t2i", "i2i"] and by["demo-image"]["ok"] is True
    assert by["upscale-demo"]["tasks"] == ["upscale"] and by["demo-video"]["kind"] == "video" and by["demo-audio"]["tasks"] == ["t2a"] and by["demo-audio"]["kind"] == "audio"
    assert by["demo-unsafe"]["ok"] is False and "pickle" in by["demo-unsafe"]["reason"]
    assert {"name", "kind", "pipeline", "tasks", "size_gb", "licence", "ok", "reason"} <= set(by["demo-image"])


# ── التوليد ──────────────────────────────────────────────────────────────
def test_text_to_image_returns_a_png_with_the_right_type_and_kind(engines, tmp_path):
    c, _ = engines()
    jid = submit(c, mode="t2i", model="demo-image", prompt="عبوة عطر", width=96, height=160).json()["id"]
    j = wait(c, jid)
    assert j["status"] == "done" and j["result_kind"] == "image" and j["error"] is None
    r = fetch(c, jid)
    assert r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    im = img_of(r)
    assert im.size == (96, 160) and im.text["model"] == "demo-image" and im.text["mode"] == "t2i" and im.text["prompt"] == "عبوة عطر"
    assert (tmp_path / "out_a" / f"{jid}.png").exists() and not list((tmp_path / "out_a").glob("*.mp4"))
    d = c.delete(f"/jobs/{jid}").json()
    assert d["status"] == "done" and not (tmp_path / "out_a" / f"{jid}.png").exists() and c.get(f"/jobs/{jid}/result").status_code == 410


def test_image_edit_takes_up_to_two_extra_reference_images_and_cleans_every_upload(engines, tmp_path):
    c, _ = engines()
    files = {"image": ("a.png", png(), "image/png"), "image2": ("b.png", png(color=(1, 2, 3)), "image/png"), "image3": ("c.png", png(color=(4, 5, 6)), "image/png")}
    jid = submit(c, files, mode="i2i", model="demo-image", prompt="غيّر الخلفية", strength=0.5).json()["id"]
    j = wait(c, jid)
    assert j["status"] == "done" and j["result_kind"] == "image"
    im = img_of(fetch(c, jid))
    assert im.text["refs"] == "3" and im.text["strength"] == "0.5" and im.size == (32, 48)
    assert not list((tmp_path / "out_a").glob("*_in*")), "الصور المرفوعة (حتى الإضافية) لازم تنحذف أول ما تخلص المهمة"
    single = wait(c, submit(c, {"image": ("a.png", png(), "image/png")}, mode="i2i", model="demo-image", prompt="x").json()["id"])
    assert single["status"] == "done"


def test_extra_images_are_for_image_edit_only_and_every_upload_is_validated(engines):
    c, _ = engines()
    base = {"image": ("a.png", png(), "image/png")}
    r = submit(c, {**base, "image2": ("b.png", png(), "image/png")}, mode="i2v", model="demo-video", prompt="x")
    assert r.status_code == 400 and "image2" in r.json()["detail"]
    r = submit(c, {**base, "image2": ("b.png", b"%PDF-1.4 nope", "image/png")}, mode="i2i", model="demo-image", prompt="x")
    assert r.status_code == 415
    r = submit(c, {**base, "image3": ("c.png", b"", "image/png")}, mode="i2i", model="demo-image", prompt="x")
    assert r.status_code == 400 and "فاضية" in r.json()["detail"]
    assert submit(c, None, mode="i2i", model="demo-image", prompt="x").status_code == 400
    assert "تعديل الصورة بدّه صورة" in submit(c, None, mode="i2i", model="demo-image", prompt="x").json()["detail"]
    assert "التكبير بدّه صورة" in submit(c, None, mode="upscale", model="upscale-demo").json()["detail"]
    assert "صورة لفيديو بدّه صورة" in submit(c, None, mode="i2v", model="demo-video", prompt="x").json()["detail"]


def test_upscale_multiplies_the_size_and_validates_the_factor(engines):
    c, _ = engines()
    src = {"image": ("a.png", png((20, 30)), "image/png")}
    r4 = fetch(c, wait(c, submit(c, src, mode="upscale", model="upscale-demo").json()["id"])["id"])                # الافتراضي ×4
    assert img_of(r4).size == (80, 120)
    r3 = fetch(c, wait(c, submit(c, src, mode="upscale", model="upscale-demo", scale=3).json()["id"])["id"])
    assert img_of(r3).size == (60, 90) and img_of(r3).text["scale"] == "3"
    for bad in (1, 9, 2.5, "x", True):
        r = submit(c, src, mode="upscale", model="upscale-demo", scale=bad)
        assert r.status_code == 400 and "scale" in r.json()["detail"], bad


def test_video_modes_still_work_through_the_general_box_and_report_video_kind(engines, tmp_path):
    c, _ = engines()
    jid = submit(c, {"image": ("a.png", png((64, 96)), "image/png")}, mode="i2v", model="demo-video", seconds=1, width=64, height=96, prompt="حرّك").json()["id"]
    j = wait(c, jid)
    assert j["status"] == "done" and j["result_kind"] == "video"
    r = fetch(c, jid)
    assert r.headers["content-type"] == "video/mp4" and r.content[4:8] == b"ftyp" and (tmp_path / "out_a" / f"{jid}.mp4").exists()


def wav_info(r) -> tuple[int, int, int]:
    import wave
    with wave.open(io.BytesIO(r.content)) as w:
        return w.getnchannels(), w.getframerate(), w.getnframes()


def test_text_to_audio_returns_a_stereo_wav_with_the_audio_kind_and_cleans_up(engines, tmp_path):
    c, _ = engines()
    jid = submit(c, mode="t2a", model="demo-audio", prompt="رعد بعيد", seconds=3).json()["id"]
    j = wait(c, jid)
    assert j["status"] == "done" and j["result_kind"] == "audio" and j["error"] is None
    r = fetch(c, jid)
    assert r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF" and r.content[8:12] == b"WAVE"
    assert wav_info(r) == (2, 8000, 3 * 8000)
    assert (tmp_path / "out_a" / f"{jid}.wav").exists() and not list((tmp_path / "out_a").glob("*.png")) and not list((tmp_path / "out_a").glob("*_in*"))
    again = fetch(c, wait(c, submit(c, mode="t2a", model="demo-audio", prompt="رعد بعيد", seconds=3).json()["id"])["id"])
    other = fetch(c, wait(c, submit(c, mode="t2a", model="demo-audio", prompt="مطر خفيف", seconds=3).json()["id"])["id"])
    assert again.content == r.content and other.content != r.content                          # نغمة الصوت الوهمي من الوصف
    c.delete(f"/jobs/{jid}")
    assert not (tmp_path / "out_a" / f"{jid}.wav").exists() and c.get(f"/jobs/{jid}/result").status_code == 410


def test_audio_has_its_own_seconds_cap_separate_from_the_video_cap(engines):
    c, _ = engines(max_seconds=5, audio_max_seconds=12)
    h = c.get("/health").json()
    assert h["max_seconds"] == 5 and h["audio_max_seconds"] == 12
    assert submit(c, None, mode="t2a", model="demo-audio", prompt="x", seconds=10).status_code == 200              # فوق سقف الفيديو (5) وتحت سقف الصوت (12)
    r = submit(c, None, mode="t2a", model="demo-audio", prompt="x", seconds=13)
    assert r.status_code == 400 and "12" in r.json()["detail"] and "ثانية" in r.json()["detail"]
    r = submit(c, {"image": ("a.png", png(), "image/png")}, mode="i2v", model="demo-video", prompt="x", seconds=6)
    assert r.status_code == 400 and "5" in r.json()["detail"]                                                      # الفيديو لسا بسقفه
    assert submit(c, None, mode="t2a", model="demo-audio", prompt="x", seconds=0.2).status_code == 400


def test_audio_cap_comes_from_the_environment_with_a_safe_default(monkeypatch):
    monkeypatch.delenv("AUDIO_MAX_SECONDS", raising=False)
    assert Settings.from_env().audio_max_seconds == 47.0
    monkeypatch.setenv("AUDIO_MAX_SECONDS", "30")
    assert Settings.from_env().audio_max_seconds == 30.0
    for bad in ("abc", "0.5"):
        monkeypatch.setenv("AUDIO_MAX_SECONDS", bad)
        with pytest.raises(ValueError, match="AUDIO_MAX_SECONDS"):
            Settings.from_env()


def test_uploads_need_a_declared_length_and_the_token_is_checked_before_the_body_is_read(engines):
    c, _ = engines(token="tok-FAKE-1")
    mp = {"Content-Type": "multipart/form-data; boundary=x"}

    def chunks():                                                                         # httpx بيبعتها chunked بلا Content-Length
        yield b"--x\r\n"
    r = c.post("/jobs", content=chunks(), headers={"X-Engine-Token": "tok-FAKE-1", **mp})
    assert r.status_code == 411 and "Content-Length" in r.json()["detail"]
    r = c.post("/jobs", content=chunks(), headers=mp)                                     # بلا توكن: 401 قبل ما يتقرا الجسم
    assert r.status_code == 401
    r = c.post("/jobs", content=b"--x\r\n", headers={"X-Engine-Token": "wrong", **mp})
    assert r.status_code == 401
    assert submit(c, None, token="tok-FAKE-1", mode="t2i", model="demo-image", prompt="x").status_code == 200


def test_model_and_parameter_validation_gives_arabic_reasons(engines):
    c, _ = engines()
    cases = [
        (dict(mode="t2i", prompt="x"), "لازم تحدد النموذج"),
        (dict(mode="t2i", model="nope", prompt="x"), "مش موجود"),
        (dict(mode="t2i", model="demo-unsafe", prompt="x"), "مرفوض"),
        (dict(mode="t2i", model="demo-video", prompt="x"), "ما بيدعم النمط"),
        (dict(mode="t2i", model="../etc/passwd", prompt="x"), "حروف إنجليزية"),
        (dict(mode="t2i", model=5, prompt="x"), "حروف إنجليزية"),
        (dict(mode="t2i", model="demo-image", prompt="x", strength=2), "strength"),
        (dict(mode="t2i", model="demo-image", prompt="x", extra={"prompt": "hijack"}), "محجوز"),
        (dict(mode="t2i", model="demo-image", prompt="x", extra="nope"), "كائن"),
        (dict(mode="t2a", model="demo-image", prompt="x"), "ما بيدعم النمط"),
        (dict(mode="t2i", model="demo-audio", prompt="x"), "ما بيدعم النمط"),
    ]
    for params, needle in cases:
        r = submit(c, None, **params)
        assert r.status_code == 400 and needle in r.json()["detail"], (params, r.text)
    ok = submit(c, None, mode="t2i", model="demo-image", prompt="x", extra={"max_sequence_length": 128}, strength=None, scale=None)
    assert ok.status_code == 200


def test_cancelling_a_queued_edit_removes_all_its_uploads_and_a_running_one_stops(engines, tmp_path):
    c, _ = engines()
    first = submit(c, None, mode="t2i", model="demo-image", prompt="x", sleep=1.5).json()["id"]
    files = {"image": ("a.png", png(), "image/png"), "image2": ("b.png", png(), "image/png"), "image3": ("c.png", png(), "image/png")}
    queued = submit(c, files, mode="i2i", model="demo-image", prompt="x").json()["id"]
    out = tmp_path / "out_a"
    assert len(list(out.glob(f"{queued}_in*"))) == 3
    j = c.delete(f"/jobs/{queued}").json()
    assert j["status"] == "cancelled" and not list(out.glob(f"{queued}_in*"))
    c.delete(f"/jobs/{first}")
    assert wait(c, first)["status"] == "cancelled"
    assert not list(out.glob("*.png"))                                        # ما انكتب ناتج لمهمة ملغية


def test_backend_failures_report_the_right_word_for_the_kind(engines):
    c, _ = engines()
    j = wait(c, submit(c, None, mode="t2i", model="demo-image", prompt="x", simulate_error=True).json()["id"])
    assert j["status"] == "failed" and "فشل التوليد" in j["error"]
    j = wait(c, submit(c, None, mode="t2i", model="demo-image", prompt="x", simulate_oom=True).json()["id"])
    assert j["status"] == "failed" and j["error"] == engine_app.OOM_MESSAGE
    ok = wait(c, submit(c, None, mode="t2i", model="demo-image", prompt="x").json()["id"])                  # الخدمة ما انهارت
    assert ok["status"] == "done"


class SilentBackend(FakeImagesBackend):
    def generate(self, params, image, out, cancel):
        self.loaded = True                                                    # ما بيكتب ولا ملف


def test_a_backend_that_writes_nothing_fails_with_the_kind_word(tmp_path):
    s = Settings(backend="fake-images", name="z", outputs=tmp_path / "o", lock_dir=tmp_path / "l", lock_poll_sec=0.05)
    with TestClient(create_app(s, backend=SilentBackend(s))) as c:
        j = wait(c, submit(c, None, mode="t2i", model="demo-image", prompt="x").json()["id"])
        assert j["status"] == "failed" and j["error"] == "النموذج ما كتب صورة"


# ── الصناديق القديمة ─────────────────────────────────────────────────────
def test_old_fixed_model_boxes_keep_their_contract_and_get_the_v2_extras(engines, tmp_path):
    c, _ = engines("old", backend="fake")
    h = c.get("/health").json()
    assert h["api"] == 2 and h["tasks"] == ["i2v", "t2v"] and h["loaded_model"] is None
    m = c.get("/models").json()["models"]
    assert len(m) == 1 and m[0]["name"] == "fake" and m[0]["ok"] is True
    r = submit(c, {"image": ("a.png", png((64, 96)), "image/png")}, mode="i2v", seconds=1, width=64, height=96)
    j = wait(c, r.json()["id"])
    assert j["status"] == "done" and j["result_kind"] == "video"
    assert fetch(c, j["id"]).headers["content-type"] == "video/mp4"
    r = submit(c, None, mode="t2i", prompt="x")
    assert r.status_code == 400 and "مش مدعوم" in r.json()["detail"]
    assert submit(c, {"image": ("a.png", png(), "image/png")}, mode="i2v", seconds=1, model="whatever", extra={"a": 1}).status_code == 200      # مقبولة وبتتجاهل


def test_stale_pngs_and_extra_inputs_are_cleaned_but_foreign_files_stay(engines, tmp_path):
    c, app = engines("a", keep_minutes=1.0)
    out = tmp_path / "out_a"
    stale = [out / ("0" * 16 + ".png"), out / ("1" * 16 + ".wav"), out / ("2" * 16 + "_in2.png"), out / ("3" * 16 + "_in3.webp")]
    foreign = out / "notes.png"
    old = time.time() - 3600
    for f in stale + [foreign]:
        f.write_bytes(b"x")
        os.utime(f, (old, old))
    app.state.engine["cleanup"](force=True)
    assert not any(f.exists() for f in stale) and foreign.exists()


def test_three_reference_pictures_fit_even_though_each_is_close_to_the_per_image_limit(engines):
    """الحد 1MB لكل صورة: ثلاث صور بحجم ~0.5MB (مجموع أكبر من 1MB) لازم تنقبل، وصورة وحدة أكبر من الحد بتنرفض."""
    c, _ = engines(max_image_mb=1.0)

    def noisy(n):
        b = io.BytesIO()
        Image.effect_noise((n, n), 80).convert("RGB").save(b, "PNG")
        return b.getvalue()
    pic = noisy(420)
    assert 400_000 < len(pic) < 1_000_000
    files = {"image": ("a.png", pic, "image/png"), "image2": ("b.png", pic, "image/png"), "image3": ("c.png", pic, "image/png")}
    assert 3 * len(pic) > 1024 * 1024 + 64 * 1024                                  # مجموعها أكبر من الحد القديم للطلب كله
    r = submit(c, files, mode="i2i", model="demo-image", prompt="x")
    assert r.status_code == 200, r.text
    assert wait(c, r.json()["id"])["status"] == "done"
    big = noisy(700)
    assert len(big) > 1024 * 1024
    assert submit(c, {"image": ("a.png", big, "image/png")}, mode="i2i", model="demo-image", prompt="x").status_code == 413


def test_upscale_pixel_budget_is_its_own_setting_not_the_generation_resolution_cap(monkeypatch, tmp_path):
    s = Settings.from_env()
    assert s.upscale_max_pixels == 64_000_000
    monkeypatch.setenv("UPSCALE_MAX_PIXELS", "5000000")
    monkeypatch.setenv("MAX_PIXELS", "399360")
    s2 = Settings.from_env()
    assert s2.upscale_max_pixels == 5_000_000 and s2.max_pixels == 399360
    monkeypatch.setenv("UPSCALE_MAX_PIXELS", "10")
    with pytest.raises(ValueError, match="UPSCALE_MAX_PIXELS"):
        Settings.from_env()
