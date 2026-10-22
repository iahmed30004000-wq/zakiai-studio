"""ربط «أوزان على السيرفر» (link_engine.py): عميل صندوق الأوزان العام. صندوق حقيقي (services/engine على uvicorn بخلفية fake-images)
+ سيرفر خام بردود مظبوطة يدوياً للحالات الغريبة. بلا كرت ولا Docker."""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import link_engine as le  # noqa: E402
import model_library as ml  # noqa: E402
import model_run as mr  # noqa: E402
import secrets_store  # noqa: E402
from endless_server import EndlessServer  # noqa: E402
from engine_box import box_factory, png, start_box  # noqa: E402,F401  (fixture + مساعدين)
from services.engine.backends.fake import FakeImagesBackend  # noqa: E402

TOKEN = "tok-FAKE-box-0123456789"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    monkeypatch.delenv("ENGINE_TOKEN", raising=False)
    monkeypatch.setattr(le, "POLL_SEC", 0.05)
    le.clear_cache()
    mem, prev = secrets_store.use_memory_backend()
    yield tmp_path
    secrets_store.restore_backend(prev)
    le.clear_cache()


class SpyBackend(FakeImagesBackend):
    """بيسجّل معاملات كل مهمة وصلت (بما فيها الصور الإضافية الداخلية)، وبيبطّئ لو طُلب، وبيفشل بنص محدد لو طُلب."""

    def __init__(self, delay: float = 0.0, fail: str | None = None):
        super().__init__(None)
        self.seen: list[dict] = []
        self.delay, self.fail = delay, fail

    def generate(self, params, image, out, cancel):
        self.seen.append({**params, "_has_image": image is not None})
        if self.fail:
            raise RuntimeError(self.fail)
        super().generate({**params, "sleep": self.delay} if self.delay else params, image, out, cancel)


def weights_model(task="image", model="demo-image", **over):
    raw = {"name": "أوزان", "task": task, "link": "weights", "enabled": True, "weights": {"model": model}, "licence": {"id": "Apache-2.0", "commercial": "yes"}}
    raw.update(over)
    return ml.create(raw)


def run(model, tmp_path, **kw):
    kw.setdefault("record", False)
    task = kw.pop("task", model["task"])
    return mr.run(model, mr.RunRequest(task=task, out=tmp_path / "out.png", **kw))


def fake_cuda(monkeypatch, free_gb=6, total_gb=24):
    mem = {"free": free_gb, "total": total_gb}
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(
        is_available=lambda: True, mem_get_info=lambda: (mem["free"] * 1024 ** 3, mem["total"] * 1024 ** 3))))
    return mem


# ── الإعداد والتوكن ───────────────────────────────────────────────────────
def test_box_url_and_token_come_from_the_library_secret_store_then_env(lib, monkeypatch):
    assert le.box_url() is None and le.token() is None
    ml.set_box("http://127.0.0.1:8100", "modellib.box.token")
    assert le.box_url() == "http://127.0.0.1:8100" and le.token() is None
    secrets_store.set_secret("modellib.box.token", TOKEN)
    monkeypatch.setenv("ENGINE_TOKEN", "env-token")
    assert le.token() == TOKEN                                             # المخزن أولى من متغير البيئة
    secrets_store.set_secret("modellib.box.token", "")
    assert le.token() == "env-token"                                       # سيرفر لينكس: الـ compose بيمرّر ENGINE_TOKEN
    ml.path().write_text(json.dumps({"version": 1, "box": {"url": "http://example.com:80"}, "models": []}), encoding="utf-8")
    assert le.box_url() is None                                            # عنوان غير مسموح بالملف = كأنو ما في صندوق


def test_status_of_an_unconfigured_or_forbidden_address_says_why(lib):
    s = le.status()
    assert s["ok"] is False and s["reason"] == "config" and "مش مربوط" in s["message"] and s["models"] == []
    bad = le.status("http://example.com:8100")
    assert bad["ok"] is False and bad["reason"] == "config" and "المضيف مش مسموح" in bad["message"]


def test_status_lists_models_with_reasons_gpu_and_what_is_loaded(lib, box_factory, monkeypatch):
    fake_cuda(monkeypatch)
    box = box_factory()
    s = le.status(box.url, None)
    assert s["ok"] and s["api"] == 2 and s["legacy"] is False and s["backend"] == "fake-images" and s["gpu"] == {"free_gb": 6.0, "total_gb": 24.0}
    by = {m["name"]: m for m in s["models"]}
    assert by["demo-image"]["ok"] and not by["demo-unsafe"]["ok"] and "pickle" in by["demo-unsafe"]["reason"]
    assert "4 نموذج جاهز" in s["message"] and "1 مرفوض" in s["message"] and s["audio_max_seconds"] == 47 and "t2a" in s["tasks"]
    assert by["demo-audio"]["ok"] and by["demo-audio"]["tasks"] == ["t2a"]
    assert s["loaded_model"] is None and s["queued"] == 0
    ml.set_box(box.url)
    assert le.status()["ok"] is True                                       # بدون معاملات: الصندوق المضبوط بالمكتبة


def test_status_distinguishes_token_unreachable_and_old_boxes(lib, box_factory):
    box = box_factory(token=TOKEN)
    assert le.status(box.url, None)["reason"] == "auth"                    # /health مفتوح و/models بالتوكن
    assert le.status(box.url, "wrong")["reason"] == "auth"
    assert le.status(box.url, TOKEN)["ok"] is True
    fixed = box_factory(backend="fake")                                    # صندوق بنموذج ثابت (ltx/wan/fake) بنفس الخدمة الجديدة: /models بنموذج وحيد
    s = le.status(fixed.url, None)
    assert s["ok"] and s["legacy"] is False and [(m["name"], m["tasks"]) for m in s["models"]] == [("fake", ["i2v", "t2v"])]
    dead = box.url
    box.stop()
    d = le.status(dead, TOKEN, timeout=2)
    assert d["ok"] is False and d["reason"] == "connection" and "واقف" in d["message"]


def test_gpu_info_is_cached_and_forgets_on_refresh(lib, box_factory, monkeypatch):
    mem = fake_cuda(monkeypatch)
    assert le.gpu_info() is None                                           # ما في صندوق
    box = box_factory()
    ml.set_box(box.url)
    assert le.gpu_info() == {"free_gb": 6.0, "total_gb": 24.0}
    mem.update(free=2, total=48)
    assert le.gpu_info() == {"free_gb": 6.0, "total_gb": 24.0}             # بكاش
    assert le.gpu_info(refresh=True) == {"free_gb": 2.0, "total_gb": 48.0}
    le.clear_cache()
    assert le.gpu_info()["total_gb"] == 48.0


def test_motion_vram_comes_from_the_box_when_this_machine_has_no_card(lib, box_factory, monkeypatch):
    import motion
    fake_cuda(monkeypatch, 3, 24)
    ml.set_box(box_factory().url)
    assert motion._box_vram_gb() == 24.0                                   # الكرت كله: الصندوق بيفرّغ نموذجه قبل غيره
    le.clear_cache()
    ml.set_box(None)
    assert motion._box_vram_gb() is None


# ── التشغيل عبر المكتبة ───────────────────────────────────────────────────
def test_text_to_image_through_the_library_runs_on_the_box_and_cleans_up(lib, box_factory):
    box = box_factory()
    ml.set_box(box.url)
    m = weights_model()
    res = run(m, lib, prompt="عبوة عطر على رخام", params={"width": 96, "height": 160})
    assert res.path.exists() and res.kind == "image" and res.model_id == m["id"]
    with Image.open(res.path) as im:
        assert im.size == (96, 160)
    job = next(iter(box.jobs.values()))
    assert job.params["mode"] == "t2i" and job.params["model"] == "demo-image" and job.params["prompt"] == "عبوة عطر على رخام"
    assert job.purged is True and job.result is None                       # DELETE بالنهاية دايماً
    tmp = lib / "library" / "tmp" / "modelrun"
    assert not tmp.exists() or not list(tmp.iterdir())


def test_edit_with_references_sends_every_picture_and_respects_the_edit_capability(lib, tmp_path):
    spy = SpyBackend()
    live = start_box(tmp_path, backend_obj=spy, name="spy")
    try:
        ml.set_box(live.url)
        edit = weights_model(caps={"edit": True, "refs": True})
        pics = []
        for i, col in enumerate(((1, 1, 1), (2, 2, 2), (3, 3, 3))):
            f = lib / f"p{i}.png"
            f.write_bytes(png((64, 96), col))
            pics.append(f)
        res = run(edit, lib, prompt="غيّر الخلفية", image=pics[0], refs=pics[1:], params={"width": 4096, "height": 2048})
        assert res.path.exists()
        seen = spy.seen[-1]
        assert seen["mode"] == "i2i" and seen["_has_image"] and str(seen["_image2"]).endswith("_in2.png") and str(seen["_image3"]).endswith("_in3.png")
        assert (seen["width"], seen["height"]) == (2048, 1024)                # حد الصندوق للضلع 2048 بنفس النسبة
        plain = weights_model(name="بلا تعديل")
        with pytest.raises(mr.RunError, match="ما بيقبل صور مرجعية") as e:
            run(plain, lib, prompt="x", image=pics[0])
        assert e.value.reason == "unsupported" and not e.value.technical
        assert len(spy.seen) == 1                                             # ما وصل شي للصندوق
    finally:
        live.stop()


def test_upscale_through_the_library_returns_the_requested_scale(lib, box_factory):
    ml.set_box(box_factory().url)
    m = weights_model("upscale", "upscale-demo", caps={"scale_max": 4})
    src = lib / "s.png"
    src.write_bytes(png((40, 60)))
    for scale, size in ((None, (160, 240)), (2, (80, 120)), (3, (120, 180))):
        res = run(m, lib, image=src, params={"scale": scale} if scale else {})
        with Image.open(res.path) as im:
            assert im.size == size, scale
    for bad in (1, 8):
        with pytest.raises(mr.RunError, match="×2 أو ×3 أو ×4") as e:
            run(m, lib, image=src, params={"scale": bad})
        assert e.value.reason == "unsupported" and not e.value.technical
    with pytest.raises(mr.RunError, match="ما في صورة للتكبير") as e:
        run(m, lib)
    assert e.value.reason == "config" and not e.value.technical


def test_music_and_effects_send_t2a_with_the_requested_seconds_and_return_an_audio_file(lib, box_factory):
    box = box_factory()
    ml.set_box(box.url)
    music = weights_model("music", "demo-audio", name="موسيقى أوزان", caps={"max_sec": 47}, params={"seconds": 30})
    out = lib / "m.mp3"
    res = mr.run(music, mr.RunRequest(task="music", out=out, prompt="بيانو هادئ", seconds=4, record=False))
    assert res.path == out and res.kind == "audio" and 3.5 <= res.info["duration_sec"] <= 5 and out.read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    job = next(iter(box.jobs.values()))
    assert job.params == {"mode": "t2a", "model": "demo-audio", "prompt": "بيانو هادئ", "seconds": 4.0} and job.purged is True and job.result is None
    sfx = weights_model("sfx", "demo-audio", name="مؤثرات أوزان")
    res2 = mr.run(sfx, mr.RunRequest(task="sfx", out=lib / "s.mp3", prompt="طرق على الباب", negative="music", record=False))          # بلا مدة بالطلب ولا بالنموذج: 5 ثواني للمؤثرات
    assert 4.5 <= res2.info["duration_sec"] <= 6
    j2 = list(box.jobs.values())[-1]
    assert j2.params["seconds"] == 5.0 and j2.params["negative_prompt"] == "music"
    res3 = mr.run(music, mr.RunRequest(task="music", out=lib / "d.mp3", prompt="x", record=False))                                     # مدة النموذج الافتراضية (30)
    assert 29 <= res3.info["duration_sec"] <= 31


def test_audio_errors_are_clear_and_the_box_cap_is_reported(lib, box_factory):
    box = box_factory(audio_max_seconds=10)
    ml.set_box(box.url)
    m = weights_model("music", "demo-audio")
    with pytest.raises(mr.RunError, match="وصف للصوت") as e:
        mr.run(m, mr.RunRequest(task="music", out=lib / "x.mp3", prompt="  ", record=False))
    assert e.value.reason == "config" and not e.value.technical
    with pytest.raises(mr.RunError, match="المدة لازم بين 0.5 و10") as e:
        mr.run(m, mr.RunRequest(task="music", out=lib / "x.mp3", prompt="x", seconds=30, record=False))
    assert e.value.reason == "rejected"
    wrong = weights_model("music", "demo-image", name="نموذج صور")
    with pytest.raises(mr.RunError, match="ما بيدعم النمط") as e:
        mr.run(wrong, mr.RunRequest(task="music", out=lib / "y.mp3", prompt="x", seconds=3, record=False))
    assert e.value.reason == "rejected" and not list((lib / "library" / "tmp" / "modelrun").glob("*"))


def test_an_endless_health_or_error_body_is_cut_while_downloading(lib):
    big = EndlessServer(only="/health")
    try:
        s = le.status(big.url, None)
        assert s["ok"] is False and s["reason"] == "bad_output" and "أكبر من الحد" in s["message"]
        assert big.sent < 16 * 1024 * 1024, big.sent                                  # سقف /health (1MB) بينطبق أثناء التنزيل
    finally:
        big.stop()
    err = EndlessServer(status=500)
    try:
        ml.set_box(err.url)
        with pytest.raises(mr.RunError, match="الصندوق رفض الطلب: رد 500") as e:
            run(weights_model(), lib, prompt="x")
        assert e.value.reason == "model_failed" and err.sent < 16 * 1024 * 1024, err.sent
    finally:
        err.stop()
    monkey = EndlessServer(only="/health")
    try:
        old = le.BODY_MAX_SEC
        le.BODY_MAX_SEC = -1.0                                                          # جسم بيطوّل أكتر من الوقت المسموح = قطع
        try:
            s = le.status(monkey.url, None)
        finally:
            le.BODY_MAX_SEC = old
        assert s["ok"] is False and s["reason"] == "timeout" and "طوّل كتير" in s["message"]
    finally:
        monkey.stop()


def test_errors_say_what_happened_and_which_ones_may_fall_back(lib, box_factory):
    m = weights_model()
    with pytest.raises(mr.RunError, match="مش مربوط") as e:                  # ما في صندوق مضبوط
        run(m, lib, prompt="x")
    assert e.value.reason == "config" and not e.value.technical
    box = box_factory(token=TOKEN)
    ml.set_box(box.url)
    with pytest.raises(mr.RunError, match="توكن صندوق الأوزان") as e:
        run(m, lib, prompt="x")
    assert e.value.reason == "auth" and e.value.technical
    secrets_store.set_secret("modellib.box.token", TOKEN)
    ml.set_box(box.url, "modellib.box.token")
    assert run(m, lib, prompt="x").path.exists()                              # التوكن من المخزن
    ghost = weights_model(model="Ghost", name="غايب")
    with pytest.raises(mr.RunError, match="الصندوق رفض الطلب: النموذج «Ghost» مش موجود") as e:
        run(ghost, lib, prompt="x")
    assert e.value.reason == "rejected" and e.value.technical
    unsafe = weights_model(model="demo-unsafe", name="غير آمن")
    with pytest.raises(mr.RunError, match="مرفوض"):
        run(unsafe, lib, prompt="x")
    with pytest.raises(mr.RunError, match="وصف للصورة") as e:
        run(m, lib, prompt="   ")
    assert not e.value.technical


@pytest.mark.parametrize("text,reason", [("CUDA out of memory. Tried to allocate 2.00 GiB", "oom"), ("خطأ تجريبي", "model_failed")])
def test_the_box_failing_or_running_out_of_memory_is_a_technical_error(lib, tmp_path, text, reason):
    live = start_box(tmp_path, backend_obj=SpyBackend(fail=text), name=f"b{reason}")
    try:
        ml.set_box(live.url)
        with pytest.raises(mr.RunError) as e:
            run(weights_model(), lib, prompt="x")
        assert e.value.reason == reason and e.value.technical
        assert ("الذاكرة ما كفّت" in str(e.value)) == (reason == "oom")
    finally:
        live.stop()


def test_cancel_stops_the_box_job_and_timeout_does_the_same(lib, tmp_path):
    slow = SpyBackend(delay=4.0)
    live = start_box(tmp_path, backend_obj=slow, name="slow")
    try:
        ml.set_box(live.url)
        m = weights_model()
        flag = threading.Event()
        threading.Timer(0.6, flag.set).start()
        t0 = time.monotonic()
        with pytest.raises(mr.RunError, match="انلغت") as e:
            run(m, lib, prompt="x", cancel=flag)
        assert e.value.reason == "cancelled" and not e.value.technical and time.monotonic() - t0 < 3.5
        job = next(iter(live.jobs.values()))
        end = time.time() + 5
        while job.status not in ("cancelled", "done", "failed") and time.time() < end:
            time.sleep(0.05)
        assert job.status == "cancelled" and job.result is None            # DELETE بعت إلغاء للصندوق قبل ما تخلص الأربع ثواني
        req = mr.RunRequest(task="image", prompt="x", out=lib / "t.png", record=False)       # مهلة: Ctx بموعد نهائي قريب
        ctx = mr.Ctx({**m, "timeout_sec": 10}, req, {}, lib, time.monotonic() + 0.5)
        with pytest.raises(mr.RunError, match="تجاوز المهلة") as e:
            le.run(ctx)
        assert e.value.reason == "timeout" and e.value.technical
    finally:
        live.stop()


# ── ردود غريبة من سيرفر خام ───────────────────────────────────────────────
class RawBox:
    """سيرفر http صغير بيقلّد صندوق بردود مظبوطة يدوياً."""

    def __init__(self, **cfg):
        self.cfg = {"health": {"ok": True, "api": 2, "backend": "raw", "tasks": ["t2i"]}, "submit": (200, {"id": "abc123"}),
                    "status": (200, {"status": "done", "result_kind": "image"}), "result": (200, png((32, 32))), "models": (200, {"models": []})}
        self.cfg.update(cfg)
        self.hits: list[str] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, code, body, ctype="application/json", extra=None):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _go(self):
                outer.hits.append(f"{self.command} {self.path.split('?')[0]}")
                n = int(self.headers.get("Content-Length") or 0)
                while n > 0:
                    n -= len(self.rfile.read(min(n, 65536)) or b"") or n
                p = self.path.split("?")[0]
                if self.command == "DELETE":
                    return self._send(200, {"status": "done"})
                if p == "/health":
                    return self._send(200, outer.cfg["health"])
                if p == "/models":
                    return self._send(*outer.cfg["models"])
                if p == "/jobs" and self.command == "POST":
                    code, body = outer.cfg["submit"]
                    if code == 302:
                        return self._send(302, b"", extra={"Location": "http://example.com/steal"})
                    return self._send(code, body)
                if p.endswith("/result"):
                    code, body = outer.cfg["result"]
                    return self._send(code, body, "image/png")
                if p.startswith("/jobs/"):
                    return self._send(*outer.cfg["status"])
                self._send(404, {"detail": "no"})

            do_GET = do_POST = do_DELETE = _go

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def raw_box(lib):
    made = []

    def make(**cfg):
        b = RawBox(**cfg)
        made.append(b)
        ml.set_box(b.url)
        return b

    yield make
    for b in made:
        b.close()


@pytest.mark.parametrize("cfg,reason,needle,job_made", [
    ({"submit": (302, {})}, "connection", "التحويلات ممنوعة", False),
    ({"submit": (200, {"id": "../etc"})}, "bad_output", "رقم مهمة", False),
    ({"submit": (200, {"nope": 1})}, "bad_output", "رقم مهمة", False),
    ({"submit": (429, {"detail": "full"})}, "busy", "طابور", False),
    ({"submit": (404, {"detail": "x"})}, "missing", "ما عنده", False),
    ({"submit": (500, {"detail": "boom"})}, "model_failed", "boom", False),
    ({"submit": (400, {"detail": "الذاكرة ما كفّت"})}, "oom", "الذاكرة", False),
    ({"status": (200, {"status": "failed", "error": "فشل التوليد: x"})}, "model_failed", "الصندوق فشل: فشل التوليد: x", True),
    ({"status": (200, {"status": "failed", "error": "الذاكرة ما كفّت — جرّب مدة أقصر"})}, "oom", "الذاكرة", True),
    ({"status": (200, {"status": "cancelled"})}, "model_failed", "ألغى", True),
    ({"status": (200, {"status": "done", "result_kind": "video"})}, "bad_output", "رجّع video بدل image", True),
    ({"result": (200, b"")}, "bad_output", "فاضي", True),
    ({"result": (410, {"detail": "gone"})}, "rejected", "gone", True),
])
def test_strange_box_replies_become_clear_errors(lib, raw_box, cfg, reason, needle, job_made):
    b = raw_box(**cfg)
    with pytest.raises(mr.RunError, match=needle) as e:
        run(weights_model(), lib, prompt="x")
    assert e.value.reason == reason and e.value.technical
    assert ("DELETE /jobs/abc123" in b.hits) == job_made                      # كل مهمة اتعملت بالصندوق بتنحذف حتى لو فشلت


def test_an_oversized_result_is_cut_and_a_good_one_is_accepted(lib, raw_box, monkeypatch):
    raw_box(result=(200, png((64, 64))))
    m = weights_model()
    assert run(m, lib, prompt="x").path.exists()
    monkeypatch.setattr(le, "MAX_RESULT_BYTES", 100)
    with pytest.raises(mr.RunError, match="أكبر من الحد") as e:
        run(m, lib, prompt="x")
    assert e.value.reason == "bad_output"


def test_a_non_image_result_is_refused_by_the_content_check(lib, raw_box):
    raw_box(result=(200, b"%PDF-1.4 not an image at all"))
    with pytest.raises(mr.RunError, match="ناتج النموذج مرفوض") as e:
        run(weights_model(), lib, prompt="x")
    assert e.value.reason == "bad_output"


def test_health_replies_that_make_no_sense_are_reported_not_raised(lib, raw_box):
    b = raw_box(health={"ok": False})
    assert le.status()["reason"] == "model_failed"
    b.cfg["health"] = {"ok": True, "api": 2, "backend": "raw", "tasks": []}
    b.cfg["models"] = (200, {"models": "nope"})
    assert le.status()["ok"] is True and le.status()["models"] == []
    b.cfg["models"] = (401, {"detail": "no"})
    assert le.status()["reason"] == "auth"
    b.cfg["health"] = {"ok": True}                                           # بلا api = صندوق قديم
    assert le.status()["legacy"] is True
