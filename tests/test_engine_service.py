"""خدمة صندوق النموذج (services/engine): بالخلفية التجريبية (ffmpeg) — بدون كرت ولا Docker ولا إنترنت."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.engine import app as engine_app  # noqa: E402
from services.engine.app import OOM_MESSAGE, Settings, create_app  # noqa: E402
from services.engine.backends.fake import FakeBackend  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def png(size=(64, 114), color=(30, 90, 160)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def engines(tmp_path):
    """مصنع نسخ من الخدمة بنفس مجلد القفل (مثل صندوقين على نفس الكرت)."""
    stack = ExitStack()
    made = []

    def make(name="a", **over):
        s = Settings(backend="fake", name=name, outputs=tmp_path / f"out_{name}", lock_dir=tmp_path / "locks",
                     weights_dir=tmp_path / "weights", lock_poll_sec=0.05, **over)
        app = create_app(s)
        client = stack.enter_context(TestClient(app))
        made.append(app)
        return client, app

    yield make
    stack.close()


def submit(c, image=True, token=None, **params):
    files = {"image": ("x.png", png(), "image/png")} if image else None
    h = {"X-Engine-Token": token} if token else {}
    return c.post("/jobs", data={"params": __import__("json").dumps(params)}, files=files, headers=h)


def wait(c, jid, states=("done", "failed", "cancelled"), timeout=25, token=None):
    h = {"X-Engine-Token": token} if token else {}
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/jobs/{jid}", headers=h).json()
        if j["status"] in states:
            return j
        time.sleep(0.05)
    raise AssertionError(f"المهمة ما وصلت {states}: {j}")


def probe_duration(path_or_bytes, tmp_path) -> float:
    f = tmp_path / "probe.mp4"
    f.write_bytes(path_or_bytes)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=noprint_wrappers=1:nokey=1", str(f)], capture_output=True, text=True).stdout.strip()
    return float(out)


# ───────────────────────── دورة الحياة ─────────────────────────
def test_full_job_lifecycle_with_fake_backend(engines, tmp_path):
    c, app = engines("a")
    h = c.get("/health").json()
    assert h["ok"] and h["backend"] == "fake" and h["worker_alive"] and not h["gpu_busy"] and h["tasks"] == ["i2v", "t2v"]
    r = submit(c, mode="i2v", seconds=1.5, prompt="حركة هادئة", width=96, height=160)
    assert r.status_code == 200
    jid = r.json()["id"]
    j = wait(c, jid)
    assert j["status"] == "done" and j["seconds_taken"] is not None and j["error"] is None
    assert "simulate_oom" not in j["params"]
    res = c.get(f"/jobs/{jid}/result")
    assert res.status_code == 200 and res.headers["content-type"] == "video/mp4" and res.content[4:8] == b"ftyp"
    assert abs(probe_duration(res.content, tmp_path) - 1.5) < 0.2
    out_dir = tmp_path / "out_a"
    assert (out_dir / f"{jid}.mp4").exists() and not list(out_dir.glob("*_in.*"))      # الصورة انحذفت أول ما خلصت
    # DELETE بعد الانتهاء = تنظيف الملفات، والحالة بتضل done
    d = c.delete(f"/jobs/{jid}").json()
    assert d["status"] == "done" and not (out_dir / f"{jid}.mp4").exists()
    assert c.get(f"/jobs/{jid}/result").status_code == 410
    assert c.get("/jobs/nope").status_code == 404
    # نص لفيديو بلا صورة
    j2 = wait(c, submit(c, image=False, mode="t2v", seconds=1, width=64, height=96).json()["id"])
    assert j2["status"] == "done"


def test_result_not_ready_returns_409_and_progress_shape(engines):
    c, _ = engines("a")
    jid = submit(c, mode="i2v", seconds=1, sleep=1.0).json()["id"]
    assert c.get(f"/jobs/{jid}/result").status_code == 409
    j = c.get(f"/jobs/{jid}").json()
    assert set(j["progress"]) == {"step", "total"} and j["cancelling"] is False
    wait(c, jid)


# ───────────────────────── قفل الكرت ─────────────────────────
def test_gpu_lock_second_instance_waits_then_runs_never_together(engines):
    ca, appa = engines("a")
    cb, appb = engines("b")
    ja = submit(ca, mode="i2v", seconds=1, sleep=1.5).json()["id"]
    wait(ca, ja, ("running",))
    assert ca.get("/health").json()["gpu_busy"] is True
    jb = submit(cb, mode="i2v", seconds=1).json()["id"]
    seen_waiting = False
    end = time.time() + 20
    while time.time() < end:
        sb = cb.get(f"/jobs/{jb}").json()["status"]
        sa = ca.get(f"/jobs/{ja}").json()["status"]
        if sa == "running":
            assert sb != "running"                       # أبداً مع بعض
            seen_waiting |= sb == "waiting_gpu"
        if sb in ("done", "failed"):
            break
        time.sleep(0.03)
    assert seen_waiting
    assert wait(cb, jb)["status"] == "done" and wait(ca, ja)["status"] == "done"
    jobs_a, jobs_b = appa.state.engine["jobs"], appb.state.engine["jobs"]
    assert jobs_b[jb].started_at >= jobs_a[ja].finished_at - 0.001      # التانية بدت بعد ما الأولى سلّمت الكرت
    assert ca.get("/health").json()["gpu_busy"] is False


class SpyBackend(FakeBackend):
    def __init__(self, settings, name, events):
        super().__init__(settings)
        self.name, self._events = name, events

    def generate(self, params, image, out, cancel):
        self._events.append(f"{self.name}:generate")
        super().generate(params, image, out, cancel)

    def unload(self):
        if self.loaded:
            self._events.append(f"{self.name}:unload")
        super().unload()


def test_handoff_previous_box_unloads_before_next_runs(engines, tmp_path):
    events: list[str] = []
    sa = Settings(backend="fake", name="a", outputs=tmp_path / "oa", lock_dir=tmp_path / "locks", lock_poll_sec=0.05, handoff_wait_sec=10)
    sb = Settings(backend="fake", name="b", outputs=tmp_path / "ob", lock_dir=tmp_path / "locks", lock_poll_sec=0.05, handoff_wait_sec=10)
    bea, beb = SpyBackend(sa, "a", events), SpyBackend(sb, "b", events)
    with TestClient(create_app(sa, backend=bea)) as ca, TestClient(create_app(sb, backend=beb)) as cb:
        wait(ca, submit(ca, mode="i2v", seconds=1).json()["id"])
        assert bea.loaded
        wait(cb, submit(cb, mode="i2v", seconds=1).json()["id"])
    assert events == ["a:generate", "a:unload", "b:generate"]       # أ فرّغ ذاكرته قبل ما ب يشتغل
    assert not bea.loaded and beb.loaded


# ───────────────────────── نقص الذاكرة ─────────────────────────
def test_out_of_memory_gives_arabic_message_and_service_stays_alive(engines):
    c, app = engines("a")
    j = wait(c, submit(c, mode="i2v", seconds=1, simulate_oom=True).json()["id"])
    assert j["status"] == "failed" and j["error"] == OOM_MESSAGE
    assert app.state.engine["backend"].loaded is False               # فرّغ النموذج
    assert c.get("/health").json()["ok"]
    assert wait(c, submit(c, mode="i2v", seconds=1).json()["id"])["status"] == "done"      # والخدمة بتكمل
    j2 = wait(c, submit(c, mode="i2v", seconds=1, simulate_error=True).json()["id"])
    assert j2["status"] == "failed" and "فشل التوليد" in j2["error"]
    assert c.get("/health").json()["worker_alive"]


# ───────────────────────── التوكن ─────────────────────────
def test_token_required_on_every_job_endpoint_but_not_health(engines):
    c, _ = engines("a", token="test-secret-123")
    assert c.get("/health").status_code == 200
    assert submit(c, mode="i2v").status_code == 401
    assert submit(c, mode="i2v", token="wrong").status_code == 401
    r = submit(c, mode="i2v", seconds=1, token="test-secret-123")
    assert r.status_code == 200
    jid = r.json()["id"]
    for m, u in (("get", f"/jobs/{jid}"), ("get", f"/jobs/{jid}/result"), ("delete", f"/jobs/{jid}")):
        assert getattr(c, m)(u).status_code == 401, u
        assert getattr(c, m)(u, headers={"X-Engine-Token": "wrong"}).status_code == 401, u
    assert wait(c, jid, token="test-secret-123")["status"] == "done"
    assert c.get(f"/jobs/{jid}/result", headers={"X-Engine-Token": "test-secret-123"}).status_code == 200


# ───────────────────────── الإلغاء ─────────────────────────
def test_cancel_queued_and_running_jobs(engines, tmp_path):
    c, app = engines("a")
    j1 = submit(c, mode="i2v", seconds=1, sleep=30).json()["id"]
    wait(c, j1, ("running",))
    j2 = submit(c, mode="i2v", seconds=1).json()["id"]           # بالانتظار خلف j1
    assert c.get(f"/jobs/{j2}").json()["status"] in ("queued", "waiting_gpu")
    d2 = c.delete(f"/jobs/{j2}").json()
    assert wait(c, j2)["status"] == "cancelled" and d2["id"] == j2
    d1 = c.delete(f"/jobs/{j1}").json()
    assert d1["status"] == "running" and d1["cancelling"] is True          # شغّالة: الإلغاء بيتم بين الخطوات
    t0 = time.time()
    assert wait(c, j1)["status"] == "cancelled" and time.time() - t0 < 5
    assert c.get(f"/jobs/{j1}/result").status_code == 409
    assert not list((tmp_path / "out_a").glob("*.mp4")) and not list((tmp_path / "out_a").glob("*_in.*"))
    # الخدمة بتكمل بعد الإلغاء
    assert wait(c, submit(c, mode="i2v", seconds=1).json()["id"])["status"] == "done"


def test_cancel_racing_with_worker_never_leaves_a_job_stuck(engines):
    c, _ = engines("a")
    ids = [submit(c, mode="i2v", seconds=0.5, sleep=0.05).json()["id"] for _ in range(12)]
    for i, jid in enumerate(ids):
        if i % 2:
            c.delete(f"/jobs/{jid}")
        time.sleep(0.01)
    finals = [wait(c, jid, timeout=40)["status"] for jid in ids]
    assert set(finals) <= {"done", "cancelled"} and "done" in finals
    h = c.get("/health").json()
    assert h["queued"] == 0 and h["running"] == 0
    for jid in ids:                                                # الحالة النهائية ما بتتغيّر بعد الإلغاء المتأخر
        before = c.get(f"/jobs/{jid}").json()["status"]
        c.delete(f"/jobs/{jid}")
        assert c.get(f"/jobs/{jid}").json()["status"] == before


def test_queue_limit_returns_429(engines):
    c, _ = engines("a", max_queue=2)
    first = submit(c, mode="i2v", seconds=1, sleep=30).json()["id"]
    wait(c, first, ("running",))
    submit(c, mode="i2v", seconds=1)
    submit(c, mode="i2v", seconds=1)
    r = submit(c, mode="i2v", seconds=1)
    assert r.status_code == 429 and "الطابور" in r.json()["detail"]
    c.delete(f"/jobs/{first}")


# ───────────────────────── التحقق من المدخلات ─────────────────────────
@pytest.mark.parametrize("params,needle", [
    ({"nope": 1}, "معاملات غير معروفة"),
    ({"seconds": 99}, "المدة"),
    ({"seconds": 0.1}, "المدة"),
    ({"seconds": "abc"}, "seconds"),
    ({"seconds": True}, "seconds"),
    ({"seconds": float("nan")}, "المدة"),
    ({"mode": "v2v"}, "الوضع"),
    ({"steps": 0}, "steps"),
    ({"steps": 1.5}, "steps"),
    ({"guidance": 99}, "guidance"),
    ({"fps": 2}, "fps"),
    ({"width": 256}, "العرض والارتفاع"),
    ({"width": 9999, "height": 100}, "width"),
    ({"prompt": "x" * 5000}, "prompt"),
    ({"prompt": 5}, "prompt"),
    ({"seed": -1}, "seed"),
])
def test_bad_params_are_rejected_with_arabic_reasons(engines, params, needle):
    c, _ = engines("a")
    r = submit(c, **{"mode": "i2v", "seconds": 1, **params})
    assert r.status_code == 400 and needle in r.json()["detail"], r.text


def test_bad_json_and_non_object_params(engines):
    c, _ = engines("a")
    files = {"image": ("x.png", png(), "image/png")}
    assert c.post("/jobs", data={"params": "{غلط"}, files=files).status_code == 400
    assert c.post("/jobs", data={"params": "[1,2]"}, files=files).status_code == 400


def test_image_rules_empty_missing_wrong_type_corrupt_and_too_big(engines):
    c, _ = engines("a", max_image_mb=0.01)                         # ~10KB
    p = '{"mode":"i2v","seconds":1}'
    assert c.post("/jobs", data={"params": p}).status_code == 400                                       # i2v بلا صورة
    assert c.post("/jobs", data={"params": p}, files={"image": ("x.png", b"", "image/png")}).status_code == 400   # ملف فاضي
    r = c.post("/jobs", data={"params": p}, files={"image": ("x.png", b"%PDF-1.4 not an image", "image/png")})
    assert r.status_code == 415 and "PNG" in r.json()["detail"]                                      # النوع من المحتوى مش من الاسم
    r = c.post("/jobs", data={"params": p}, files={"image": ("x.png", b"\x89PNG\r\n\x1a\n" + b"junk" * 10, "image/png")})
    assert r.status_code == 400 and "تالفة" in r.json()["detail"]
    big = io.BytesIO()
    Image.effect_noise((200, 200), 80).convert("RGB").save(big, "PNG")
    assert len(big.getvalue()) > 10_500
    r = c.post("/jobs", data={"params": p}, files={"image": ("x.png", big.getvalue(), "image/png")})
    assert r.status_code == 413
    ok = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(ok, "JPEG")
    assert c.post("/jobs", data={"params": p}, files={"image": ("x.png", ok.getvalue(), "image/png")}).status_code == 200


def test_decompression_bomb_pixels_are_refused(engines, monkeypatch):
    monkeypatch.setattr(engine_app, "MAX_IMAGE_PIXELS", 1000)
    c, _ = engines("a")
    r = c.post("/jobs", data={"params": '{"mode":"i2v","seconds":1}'}, files={"image": ("x.png", png((100, 100)), "image/png")})
    assert r.status_code == 413 and "بالبكسل" in r.json()["detail"]


def test_test_hooks_only_exist_on_fake_backend(tmp_path):
    class Real(FakeBackend):
        name = "ltx"
    s = Settings(backend="fake", outputs=tmp_path / "o", lock_dir=tmp_path / "l")
    with TestClient(create_app(s, backend=Real(s))) as c:
        for hook in ({"simulate_oom": True}, {"sleep": 5}, {"simulate_error": True}):
            r = submit(c, mode="i2v", seconds=1, **hook)
            assert r.status_code == 400 and "غير معروفة" in r.json()["detail"], hook


# ───────────────────────── الملفات ─────────────────────────
def test_never_writes_outside_outputs_even_with_hostile_filenames(engines, tmp_path):
    c, _ = engines("a")
    snapshot = {p for p in tmp_path.rglob("*")}
    for fname in ("../../evil.png", "..\\..\\evil.png", "/etc/passwd.png", "a/b/c.png", "x" * 300 + ".png"):
        r = c.post("/jobs", data={"params": '{"mode":"i2v","seconds":1}'}, files={"image": (fname, png(), "image/png")})
        assert r.status_code == 200, (fname, r.text)
        wait(c, r.json()["id"])
    new = {p for p in tmp_path.rglob("*")} - snapshot
    allowed = tmp_path / "out_a"
    legit = (allowed, tmp_path / "locks")                        # الخرج + ملفات القفل المشترك
    assert new and all(any(d in p.parents for d in legit) for p in new if p.is_file()), [str(p) for p in new]
    assert not (tmp_path.parent / "evil.png").exists() and not (tmp_path / "evil.png").exists()
    names = [p.name for p in allowed.iterdir()]
    assert all(len(n) < 40 and n.endswith(".mp4") for n in names), names      # أسماء من عندنا بس


def test_old_outputs_are_cleaned_but_live_and_foreign_files_are_kept(engines, tmp_path):
    c, app = engines("a", keep_minutes=1.0)
    out = tmp_path / "out_a"
    jid = submit(c, mode="i2v", seconds=1).json()["id"]
    wait(c, jid)
    stale = out / ("0" * 16 + ".mp4")
    stale.write_bytes(b"old")
    foreign = out / "notes.txt"
    foreign.write_text("keep me", encoding="utf-8")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    os.utime(foreign, (old, old))
    cleanup = app.state.engine["cleanup"]
    cleanup(force=True)
    assert not stale.exists() and foreign.exists()                  # القديم بالاسم المعروف بس
    assert (out / f"{jid}.mp4").exists() and c.get(f"/jobs/{jid}").status_code == 200       # الجديد باقي
    job = app.state.engine["jobs"][jid]
    job.finished_at = time.time() - 3600                           # صار قديم
    cleanup(force=True)
    assert not (out / f"{jid}.mp4").exists() and c.get(f"/jobs/{jid}").status_code == 404


# ───────────────────────── الإعدادات ونقطة التشغيل ─────────────────────────
def test_settings_from_env_and_bad_values(monkeypatch, tmp_path):
    for k, v in {"ENGINE_BACKEND": "wan", "ENGINE_TOKEN": "t", "WEIGHTS_DIR": str(tmp_path / "w"), "OUTPUT_DIR": str(tmp_path / "o"),
                 "LOCK_DIR": str(tmp_path / "l"), "IDLE_UNLOAD_MIN": "3", "MAX_SECONDS": "7"}.items():
        monkeypatch.setenv(k, v)
    s = Settings.from_env()
    assert (s.backend, s.token, s.idle_unload_min, s.max_seconds) == ("wan", "t", 3.0, 7.0)
    assert s.weights_dir == tmp_path / "w" and s.outputs == tmp_path / "o" and s.lock_dir == tmp_path / "l"
    monkeypatch.setenv("MAX_SECONDS", "كتير")
    with pytest.raises(ValueError) as e:
        Settings.from_env()
    assert "MAX_SECONDS" in str(e.value)


def test_server_refuses_open_network_without_token(monkeypatch, tmp_path):
    from services.engine import server
    monkeypatch.setenv("ENGINE_HOST", "0.0.0.0")
    monkeypatch.delenv("ENGINE_TOKEN", raising=False)
    monkeypatch.delenv("ENGINE_ALLOW_NO_TOKEN", raising=False)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "o"))
    monkeypatch.setenv("LOCK_DIR", str(tmp_path / "l"))
    with pytest.raises(SystemExit) as e:
        server.main()
    assert "ENGINE_TOKEN" in str(e.value)


def test_server_main_starts_uvicorn_with_env_settings(monkeypatch, tmp_path):
    import uvicorn
    from services.engine import server
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.setenv("ENGINE_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGINE_PORT", "8123")
    monkeypatch.setenv("ENGINE_TOKEN", "abc")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "o"))
    monkeypatch.setenv("LOCK_DIR", str(tmp_path / "l"))
    server.main()
    assert seen["host"] == "0.0.0.0" and seen["port"] == 8123 and seen["app"].title.startswith("engine:")


# ───────────────────────── الخلفيات الحقيقية (بدون diffusers) ─────────────────────────
def test_real_backends_import_without_diffusers_and_are_marked_untested():
    from services.engine.backends import get_backend, ltx, wan
    s = Settings(backend="ltx")
    assert get_backend("ltx", s).name == "ltx" and get_backend("wan", s).name == "wan"
    with pytest.raises(ValueError):
        get_backend("nope", s)
    for mod in (ltx, wan, sys.modules["services.engine.backends._diffusers"]):
        head = "\n".join(Path(mod.__file__).read_text(encoding="utf-8").splitlines()[:3])
        assert "غير مجرَّب على كرت حقيقي — ينجرّب على السيرفر" in head, mod.__name__
    for f in (ltx, wan):
        src = Path(f.__file__).read_text(encoding="utf-8")
        top = src.split("class ")[0]
        assert "import torch" not in top and "from diffusers" not in top          # الاستيراد كسول
    assert "local_files_only=True" in Path(ltx.__file__).read_text(encoding="utf-8")
    assert "local_files_only=True" in Path(wan.__file__).read_text(encoding="utf-8")


def test_common_helpers_resolution_frames_weights_and_encode(tmp_path):
    from services.engine.backends import _common as cm
    w, h = cm.fit_resolution(1080, 1920, 480 * 832, 32)
    assert w % 32 == 0 and h % 32 == 0 and w * h <= 480 * 832 and abs(w / h - 1080 / 1920) < 0.08
    assert cm.fit_resolution(100, 100, 10**9, 32, min_side=64) == (96, 96)
    assert cm.fit_resolution(2000, 100, 256 * 256, 32)[0] >= 32
    assert cm.frame_count(3, 24, 8) == 73 and cm.frame_count(3, 24, 4) == 73 and cm.frame_count(0.5, 24, 8) == 17
    assert (cm.frame_count(5, 24, 8) - 1) % 8 == 0 and cm.frame_count(5, 24, 8) >= 5 * 24
    wd = tmp_path / "w"
    (wd / "LTX-Video").mkdir(parents=True)
    with pytest.raises(RuntimeError) as e:
        cm.weights_path(wd, "LTX-Video")                               # فاضي
    assert "أوزان" in str(e.value)
    (wd / "LTX-Video" / "model_index.json").write_text("{}")
    assert cm.weights_path(wd, "LTX-Video") == (wd / "LTX-Video").resolve()
    with pytest.raises(RuntimeError):
        cm.weights_path(wd, "../etc")
    frames = [Image.new("RGB", (64, 96), (i * 10 % 255, 40, 90)) for i in range(24)]
    out = tmp_path / "e.mp4"
    cm.encode_mp4(frames, 24, out)
    assert out.exists() and abs(probe_duration(out.read_bytes(), tmp_path) - 1.0) < 0.15
    with pytest.raises(RuntimeError):
        cm.encode_mp4([], 24, tmp_path / "x.mp4")


def test_target_size_uses_image_aspect_or_explicit_size(tmp_path):
    from services.engine.backends import _common as cm
    img = tmp_path / "a.png"
    Image.new("RGB", (1080, 1920)).save(img)
    w, h = cm.target_size({}, img, 480 * 864, 32)
    assert h > w and w % 32 == 0
    assert cm.target_size({"width": 640, "height": 640}, img, 640 * 640, 32) == (640, 640)
    fitted = cm.load_image_fitted(img, 96, 160)
    assert fitted.size == (96, 160)


def test_encode_mp4_accepts_numpy_frames_like_wan_returns_by_default(tmp_path):
    """Wan بيرجّع إطارات numpy (float بين 0 و1) افتراضياً — الترميز لازم يقبلها مثل صور PIL (وهالخلل اتلقّى بمقارنة تواقيع diffusers)."""
    import numpy as np
    from services.engine.backends import _common as cm
    floats = np.stack([np.full((96, 64, 3), 0.1 * (i % 9), dtype=np.float32) for i in range(24)])
    out = tmp_path / "np.mp4"
    cm.encode_mp4(floats, 24, out)                                    # مصفوفة (F,H,W,3) كاملة
    assert out.exists() and abs(probe_duration(out.read_bytes(), tmp_path) - 1.0) < 0.15
    ints = [np.full((96, 64, 3), 120, dtype=np.uint8) for _ in range(12)]
    out2 = tmp_path / "u8.mp4"
    cm.encode_mp4(ints, 12, out2)
    assert out2.exists()
    mixed = [Image.new("RGB", (64, 96), (9, 9, 9)), np.zeros((96, 64, 3), dtype=np.float32)]
    cm.encode_mp4(mixed, 8, tmp_path / "mixed.mp4")
    with pytest.raises(RuntimeError, match="شكل الإطار"):
        cm.encode_mp4([np.zeros((96, 64), dtype=np.float32)], 8, tmp_path / "gray.mp4")


# ───────────────────────── ملفات النشر (فحص ثابت — بدون Docker) ─────────────────────────
def _yaml(name):
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_engines_compose_security_and_gpu_rules():
    d = _yaml("docker-compose.engines.yml")
    assert set(d["services"]) == {"engine", "ltx", "wan"}
    ports = {n: s["ports"] for n, s in d["services"].items()}
    assert ports == {"engine": ["127.0.0.1:8100:8000"], "ltx": ["127.0.0.1:8101:8000"], "wan": ["127.0.0.1:8102:8000"]}
    assert "profiles" not in d["services"]["engine"]                                             # الصندوق العام هو الافتراضي
    assert d["services"]["ltx"]["profiles"] == ["legacy"] and d["services"]["wan"]["profiles"] == ["legacy"]       # القديمين احتياط بس
    for n, s in d["services"].items():
        assert s["read_only"] is True and s["restart"] == "unless-stopped" and s["user"] == "10001:10001", n
        assert any(v.endswith(":/weights:ro") for v in s["volumes"]), n                    # الأوزان للقراءة فقط
        assert "engine_locks:/locks" in s["volumes"], n                                   # قفل الكرت مشترك
        assert any(t.startswith("/tmp") for t in s["tmpfs"]) and any(t.startswith("/outputs") for t in s["tmpfs"])
        dev = s["deploy"]["resources"]["reservations"]["devices"][0]
        assert dev["driver"] == "nvidia" and "gpu" in dev["capabilities"], n
        assert "/health" in " ".join(s["healthcheck"]["test"]), n
        assert s["cap_drop"] == ["ALL"] and "no-new-privileges:true" in s["security_opt"]
        assert s["environment"]["ENGINE_TOKEN"].startswith("${ENGINE_TOKEN:?")           # مطلوب من .env وما في قيمة مكتوبة
    assert d["services"]["ltx"]["environment"]["ENGINE_BACKEND"] == "ltx" and d["services"]["wan"]["environment"]["ENGINE_BACKEND"] == "wan"
    assert d["services"]["engine"]["environment"]["ENGINE_BACKEND"] == "diffusers" and d["services"]["engine"]["environment"]["ENGINE_NAME"] == "engine"
    assert d["services"]["engine"]["build"]["dockerfile"] == "services/engine/Dockerfile.diffusers"
    assert d["volumes"]["engine_locks"] == {"external": True, "name": "vidpattern_gpu_locks"}      # حجم مشترك مع الاستوديو (docker volume create)


def test_app_compose_and_env_example_have_no_secrets():
    d = _yaml("docker-compose.yml")
    app = d["services"]["app"]
    assert app["ports"] == ["127.0.0.1:8000:8000"]
    assert "./library:/app/library" in app["volumes"] and "./models:/app/models:ro" in app["volumes"]
    assert "gpu_locks:/locks" in app["volumes"] and app["environment"]["VP_GPU_LOCK_DIR"] == "/locks"        # قفل الكرت المشترك مع الصناديق
    assert d["volumes"]["gpu_locks"] == {"external": True, "name": _yaml("docker-compose.engines.yml")["volumes"]["engine_locks"]["name"]}
    ex = (ROOT / ".env.example").read_text(encoding="utf-8")
    vals = {ln.split("=", 1)[0]: ln.split("=", 1)[1].strip() for ln in ex.splitlines() if ln and not ln.startswith("#") and "=" in ln}
    assert vals["ENGINE_TOKEN"] == ""                                                    # فاضي: ما في توكن حقيقي
    blob = "\n".join((ROOT / n).read_text(encoding="utf-8") for n in
                      ("docker-compose.yml", "docker-compose.engines.yml", "Dockerfile", "services/engine/Dockerfile.ltx",
                       "services/engine/Dockerfile.wan", "services/engine/Dockerfile.diffusers", ".env.example", "README_AR_نشر_السيرفر.md"))
    import re
    assert not re.search(r"(hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ENGINE_TOKEN=[0-9a-f]{16,})", blob)
    assert ".env" in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()


def test_engine_dockerfiles_non_root_offline_and_pinned_requirements():
    import re
    for m in ("ltx", "wan", "diffusers"):
        df = (ROOT / "services" / "engine" / f"Dockerfile.{m}").read_text(encoding="utf-8")
        assert "USER 10001:10001" in df and "ffmpeg" in df and "HF_HUB_OFFLINE=1" in df and f"ENGINE_BACKEND={m}" in df
        assert "chmod 0777 /locks" in df, m                                                        # الحجم مشترك مع الاستوديو بمستخدم غير 10001
        assert df.startswith("# syntax=docker/dockerfile:1") and "FROM pytorch/pytorch:" in df and "غير مجرَّب" in df
        req = (ROOT / "services" / "engine" / f"requirements-{m}.txt").read_text(encoding="utf-8")
        lines = [ln for ln in req.splitlines() if ln.strip() and not ln.startswith("#")]
        assert lines and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*", ln) for ln in lines), lines
        assert any(ln.startswith("diffusers==") for ln in lines)
