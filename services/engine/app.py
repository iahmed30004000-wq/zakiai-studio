"""
صندوق نموذج محلي — خدمة صغيرة لكل نموذج (بديل ComfyUI).

كل نموذج (Wan، LTX، …) بيشتغل بصندوق Docker لحاله بمكتباته، وجوّاه هالخدمة نفسها:

    POST   /jobs             شغّل (صورة اختيارية + معاملات JSON)
    GET    /jobs/{id}        الحالة
    GET    /jobs/{id}/result الفيديو الناتج
    DELETE /jobs/{id}        إلغاء (لو شغّالة) أو تنظيف ملفاتها (لو خلصت)
    GET    /health           صحة الخدمة

قواعد ثابتة:
  · شغلة وحدة على كرت الشاشة بكل لحظة — **عبر كل الصناديق**: قفل ملف مشترك (gpu.lock) بمجلد مشترك.
    إذا Wan شغّال وانطلب LTX، LTX بيستنى (حالته «بانتظار الكرت») وما بينهار.
  · لما صندوق بياخد الكرت من صندوق تاني، بيطلب منه يفرّغ نموذجه من الذاكرة أول (ملف طلب بالمجلد المشترك) —
    عشان نموذجين ما يتكدّسوا بذاكرة الكرت.
  · نقص ذاكرة الكرت ← فشل المهمة برسالة عربية واضحة، والخدمة بتضل شغّالة وبتفرّغ النموذج.
  · النموذج بيتفرّغ من الذاكرة بعد دقائق خمول (إعداد).
  · توكن اختياري (ENGINE_TOKEN). الخدمة بتسمع على 0.0.0.0 جوّا الحاوية بس، والـ compose بيربطها بـ 127.0.0.1 للجهاز.
  · الأوزان بتنقرا من مجلد للقراءة فقط — الخدمة ما بتكتب عليه أبداً. وما بتكتب إلا جوّا مجلد outputs.
  · ملفات outputs القديمة بتنحذف بعد مدة (OUTPUT_KEEP_MIN)، والصورة المرفوعة بتنحذف أول ما تخلص المهمة.
"""

from __future__ import annotations

import hmac
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from services.engine.backends._introspect import EXT_OF_KIND, KIND_OF_MODE, NAME_RX as MODEL_NAME_RX, clean_extra  # noqa: E402
from services.engine.gpu import GpuLock, Handoff  # noqa: E402,F401  (انتقلوا لـ gpu.py ليستوردهم الاستوديو؛ بنعيد تصديرهم من هون)

log = logging.getLogger("engine")

OOM_MESSAGE = "الذاكرة ما كفّت — جرّب مدة أقصر أو دقة أقل"
STATUSES = ("queued", "waiting_gpu", "running", "done", "failed", "cancelled")
TERMINAL = ("done", "failed", "cancelled")
ALLOWED_PARAMS = {"mode", "prompt", "negative_prompt", "seconds", "fps", "seed", "steps", "guidance", "width", "height",
                  "model", "strength", "scale", "extra"}          # عقد v2: الصندوق العام (model/strength/scale/extra)
FAKE_ONLY_PARAMS = {"sleep", "simulate_oom", "simulate_error"}      # خطّافات اختبار — بالخلفية التجريبية بس
HIDDEN_PARAMS = FAKE_ONLY_PARAMS | {"_image2", "_image3"}
IMAGE_MODES = ("i2v", "i2i", "upscale")               # الأنماط اللي بدها صورة (i2i بيقبل صورتين مرجعيتين زيادة)
API_VERSION = 2
MEDIA_TYPES = {".mp4": "video/mp4", ".png": "image/png", ".wav": "audio/wav"}
KIND_WORD = {"image": "صورة", "video": "فيديو", "audio": "صوت"}
MAX_PROMPT_CHARS = 4000
MAX_NEGATIVE_CHARS = 2000
MAX_IMAGE_PIXELS = 64_000_000
_OUTPUT_FILE_RX = re.compile(r"^[0-9a-f]{16}(\.mp4|\.png|\.wav|_in[23]?\.(png|jpg|webp))$")


def _env_num(name: str, default: float, lo: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"إعداد {name} لازم رقم (القيمة: {raw!r})") from None
    if lo is not None and v < lo:
        raise ValueError(f"إعداد {name} لازم يكون ≥ {lo:g}")
    return v


@dataclass
class Settings:
    backend: str = "fake"
    name: str | None = None                 # اسم الصندوق بالمجلد المشترك (افتراضي: اسم الخلفية)
    outputs: Path = Path("outputs")
    lock_dir: Path = Path("locks")
    weights_dir: Path = Path("weights")
    idle_unload_min: float = 10.0
    token: str | None = None
    lock_poll_sec: float = 0.25
    max_seconds: float = 10.0
    audio_max_seconds: float = 47.0         # سقف مدة الصوت (t2a): Stable Audio Open بيوصل لـ 47 ثانية، فالسقف العام للفيديو (max_seconds) صغير عليه
    max_image_mb: float = 20.0
    keep_minutes: float = 120.0             # كم دقيقة بنخلّي ملفات المهمات المنتهية
    max_queue: int = 20
    max_pixels: int = 0                     # 0 = الافتراضي حسب الخلفية (دقة الصور والفيديو)
    upscale_max_pixels: int = 64_000_000    # سقف مساحة الصورة المكبّرة بالخرج (مستقل عن max_pixels: ذاك لدقة التوليد)
    offload: str = "auto"                   # auto | model | none
    handoff_wait_sec: float = 30.0          # كم ننتظر الصندوق التاني يفرّغ ذاكرته
    cleanup_every_sec: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend=os.environ.get("ENGINE_BACKEND", "fake"),
            name=os.environ.get("ENGINE_NAME") or None,
            outputs=Path(os.environ.get("OUTPUT_DIR", "outputs")),
            lock_dir=Path(os.environ.get("LOCK_DIR", "locks")),
            weights_dir=Path(os.environ.get("WEIGHTS_DIR", "weights")),
            idle_unload_min=_env_num("IDLE_UNLOAD_MIN", 10.0, 0.0),
            token=os.environ.get("ENGINE_TOKEN") or None,
            max_seconds=_env_num("MAX_SECONDS", 10.0, 0.5),
            audio_max_seconds=_env_num("AUDIO_MAX_SECONDS", 47.0, 1.0),
            max_image_mb=_env_num("MAX_IMAGE_MB", 20.0, 0.1),
            keep_minutes=_env_num("OUTPUT_KEEP_MIN", 120.0, 1.0),
            max_queue=int(_env_num("MAX_QUEUE", 20, 1)),
            max_pixels=int(_env_num("MAX_PIXELS", 0, 0)),
            upscale_max_pixels=int(_env_num("UPSCALE_MAX_PIXELS", 64_000_000, 1_000_000)),
            offload=os.environ.get("ENGINE_OFFLOAD", "auto"),
        )


class CancelEvent(threading.Event):
    """حدث الإلغاء + تقدّم الخطوات (الخلفية بتحدّث step/total من callback)."""

    def __init__(self) -> None:
        super().__init__()
        self.step = 0
        self.total = 0


@dataclass
class Job:
    id: str
    params: dict
    image: Path | None
    status: str = "queued"
    error: str | None = None
    result: Path | None = None
    purged: bool = False
    extra_images: list = field(default_factory=list)        # image2/image3 (تعديل صور بعدة مراجع)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel: CancelEvent = field(default_factory=CancelEvent)

    def public(self) -> dict:
        took = round(self.finished_at - self.started_at, 2) if (self.finished_at and self.started_at) else None
        kind = KIND_OF_MODE.get(self.params.get("mode"), "video")
        return {"id": self.id, "status": self.status, "error": self.error, "seconds_taken": took, "result_kind": kind,
                "cancelling": self.cancel.is_set() and self.status not in TERMINAL,
                "progress": {"step": self.cancel.step, "total": self.cancel.total},
                "params": {k: v for k, v in self.params.items() if k not in HIDDEN_PARAMS}}


def _is_oom(e: BaseException) -> bool:
    name = type(e).__name__
    msg = str(e).lower()
    return name in ("OutOfMemoryError", "MemoryError") or "out of memory" in msg


def _sniff_image(data: bytes) -> str | None:
    """نوع الصورة من البايتات الأولى (مش من اسم الملف اللي بيبعته العميل)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _check_image(data: bytes) -> None:
    """رأس الصورة سليم وحجمها بالبكسل معقول (حماية من قنبلة الضغط)."""
    try:
        from PIL import Image
    except ImportError:                      # pragma: no cover - PIL موجود بصور الصناديق
        return
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w * h > MAX_IMAGE_PIXELS:
                raise HTTPException(413, f"الصورة كبيرة بالبكسل ({w}×{h}) — الحد {MAX_IMAGE_PIXELS // 1_000_000} ميغابكسل")
            im.verify()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "الصورة تالفة أو مش مقروءة") from None


def _num(p: dict, key: str, lo: float, hi: float, *, integer: bool = False, label: str | None = None):
    v = p[key]
    label = label or key
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise HTTPException(400, f"{label} لازم رقم")
    if integer and (isinstance(v, float) and not v.is_integer()):
        raise HTTPException(400, f"{label} لازم رقم صحيح")
    if not lo <= v <= hi:                    # بيرفض NaN كمان
        raise HTTPException(400, f"{label} لازم بين {lo:g} و{hi:g}")
    return int(v) if integer else float(v)


def validate_params(p: dict, tasks: tuple[str, ...], backend_name: str, max_seconds: float, audio_max_seconds: float = 47.0) -> dict:
    allowed = set(ALLOWED_PARAMS) | (FAKE_ONLY_PARAMS if backend_name.startswith("fake") else set())
    unknown = set(p) - allowed
    if unknown:
        raise HTTPException(400, f"معاملات غير معروفة: {sorted(unknown)}")
    out = dict(p)
    mode = out.get("mode", "i2v")
    if mode not in tasks:
        raise HTTPException(400, f"الوضع {mode} مش مدعوم بهالنموذج ({', '.join(tasks)})")
    out["mode"] = mode
    sec = out.get("seconds", 3)
    if isinstance(sec, bool) or not isinstance(sec, (int, float)):
        raise HTTPException(400, "seconds لازم رقم")
    limit = audio_max_seconds if mode == "t2a" else max_seconds
    if not 0.5 <= sec <= limit:
        raise HTTPException(400, f"المدة لازم بين 0.5 و{limit:g} ثانية")
    out["seconds"] = float(sec)
    for k, lim in (("prompt", MAX_PROMPT_CHARS), ("negative_prompt", MAX_NEGATIVE_CHARS)):
        if k in out:
            if not isinstance(out[k], str):
                raise HTTPException(400, f"{k} لازم نص")
            if len(out[k]) > lim:
                raise HTTPException(400, f"{k} أطول من {lim} حرف")
    if "fps" in out:
        out["fps"] = _num(out, "fps", 8, 60, integer=True)
    if "seed" in out and out["seed"] is not None:
        out["seed"] = _num(out, "seed", 0, 2 ** 31 - 1, integer=True)
    if "steps" in out and out["steps"] is not None:
        out["steps"] = _num(out, "steps", 1, 200, integer=True)
    if "guidance" in out and out["guidance"] is not None:
        out["guidance"] = _num(out, "guidance", 0, 30)
    if ("width" in out) != ("height" in out):
        raise HTTPException(400, "العرض والارتفاع بيجوا مع بعض")
    for k in ("width", "height"):
        if k in out:
            out[k] = _num(out, k, 64, 2048, integer=True)
    if "model" in out and out["model"] is not None:
        if not isinstance(out["model"], str) or not MODEL_NAME_RX.fullmatch(out["model"]):
            raise HTTPException(400, "اسم النموذج: حروف إنجليزية وأرقام و _ - . بس")
    if "strength" in out and out["strength"] is not None:
        out["strength"] = _num(out, "strength", 0, 1)
    if "scale" in out and out["scale"] is not None:
        out["scale"] = _num(out, "scale", 2, 4, integer=True)
    if "extra" in out:
        try:
            out["extra"] = clean_extra(out["extra"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    if "sleep" in out:
        out["sleep"] = _num(out, "sleep", 0, 120)
    return out


def create_app(settings: Settings | None = None, backend=None) -> FastAPI:
    from services.engine.backends import get_backend

    s = settings or Settings.from_env()
    s.outputs.mkdir(parents=True, exist_ok=True)
    be = backend or get_backend(s.backend, s)
    me = s.name or be.name
    lock = GpuLock(s.lock_dir)
    handoff = Handoff(s.lock_dir, me)
    outputs_root = s.outputs.resolve()
    max_image_bytes = int(s.max_image_mb * 1024 * 1024)
    jobs: dict[str, Job] = {}
    order: list[str] = []
    cv = threading.Condition()                       # يحمي حالات المهمات كلها (تقدّم/إلغاء/اختيار التالية)
    state = {"last_used": 0.0, "stop": False, "last_cleanup": 0.0, "thread": None}

    # ── ملفات ──
    def _inside_outputs(p: Path) -> bool:
        try:
            r = p.resolve()
        except OSError:
            return False
        return outputs_root in r.parents

    def _rm(p: Path | None) -> None:
        if p is not None and _inside_outputs(p):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def _purge_files(j: Job) -> None:
        _rm(j.image)
        _rm(j.result)
        for x in j.extra_images:
            _rm(x)
        j.image, j.result, j.extra_images, j.purged = None, None, [], True

    def _cleanup(force: bool = False) -> None:
        now = time.time()
        if not force and now - state["last_cleanup"] < s.cleanup_every_sec:
            return
        state["last_cleanup"] = now
        ttl = s.keep_minutes * 60
        with cv:
            stale = [j for j in jobs.values() if j.status in TERMINAL and j.finished_at and now - j.finished_at > ttl]
            for j in stale:
                _purge_files(j)
                jobs.pop(j.id, None)
                if j.id in order:
                    order.remove(j.id)
            live = {p for j in jobs.values() for p in (j.image, j.result, *j.extra_images) if p}
            live_names = {p.name for p in live}
        try:
            for f in s.outputs.iterdir():
                if f.name in live_names:
                    continue
                if f.is_file() and _OUTPUT_FILE_RX.match(f.name) and now - f.stat().st_mtime > ttl:
                    _rm(f)
        except OSError:
            pass

    # ── حالات المهمة (كلها تحت قفل cv) ──
    def _finish(job: Job, status: str, error: str | None = None, result: Path | None = None) -> None:
        with cv:
            if job.status in TERMINAL:
                return
            job.status, job.error, job.result, job.finished_at = status, error, result, time.time()
            _rm(job.image)                           # الصورة المرفوعة ما بقى إلها لزوم
            job.image = None
            for x in job.extra_images:
                _rm(x)
            job.extra_images = []
            cv.notify_all()

    def _serve_handoff() -> None:
        if handoff.requested():
            if be.loaded:
                try:
                    be.unload()
                except Exception:
                    log.exception("تفريغ النموذج فشل")
            handoff.clear_last_if_me()
            handoff.done()

    def _wait_other_unload(job: Job) -> None:
        prev = handoff.last_user()
        if not prev or prev == handoff.me:
            return
        handoff.request_unload(prev)
        end = time.time() + s.handoff_wait_sec
        while handoff.pending_for(prev) and time.time() < end and not job.cancel.is_set() and not state["stop"]:
            time.sleep(0.05)
        if handoff.pending_for(prev):               # الصندوق التاني ما ردّ: نكمّل (ممكن واقف أصلاً)
            handoff.withdraw(prev)

    def _run_job(job: Job) -> None:
        got = False
        kind = KIND_OF_MODE.get(job.params.get("mode"), "video")
        out = s.outputs / f"{job.id}{EXT_OF_KIND[kind]}"
        try:
            while not (job.cancel.is_set() or state["stop"]):
                if lock.acquire(timeout=s.lock_poll_sec):
                    got = True
                    break
                _serve_handoff()                    # لو صندوق تاني بيطلب منا نفرّغ وإحنا بنستنى
            if not got or job.cancel.is_set():
                _finish(job, "cancelled")
                return
            _wait_other_unload(job)
            if job.cancel.is_set():
                _finish(job, "cancelled")
                return
            with cv:
                if job.status in TERMINAL:
                    return
                job.status, job.started_at = "running", time.time()
            gen_params = {**job.params, **{f"_image{i + 2}": x for i, x in enumerate(job.extra_images[:2])}}
            be.generate(gen_params, job.image, out, job.cancel)
            if job.cancel.is_set():
                _rm(out)
                _finish(job, "cancelled")
            elif not out.exists() or out.stat().st_size == 0:
                _finish(job, "failed", f"النموذج ما كتب {KIND_WORD[kind]}")
            else:
                _finish(job, "done", result=out)
        except Exception as e:                       # الخدمة ما لازم تنهار أبداً
            _rm(out)
            if _is_oom(e):
                _finish(job, "failed", OOM_MESSAGE)
                try:
                    be.unload()
                except Exception:
                    pass
            else:
                log.exception("فشل التوليد")
                _finish(job, "failed", f"فشل التوليد: {str(e)[:300]}")
        finally:
            state["last_used"] = time.time()
            if got:
                if be.loaded:
                    handoff.mark_used()
                else:
                    handoff.clear_last_if_me()
                lock.release()
            if job.status not in TERMINAL:           # حماية: ما نخلّي مهمة معلّقة بحالة غير نهائية
                _finish(job, "failed", "توقفت المهمة بشكل غير متوقع")

    def _tick() -> None:
        with cv:
            job = next((jobs[i] for i in order if i in jobs and jobs[i].status == "queued"), None)
            if job is None:
                cv.wait(timeout=0.5)
            else:
                job.status = "waiting_gpu"
        if job is None:
            _serve_handoff()
            if be.loaded and state["last_used"] and time.time() - state["last_used"] > s.idle_unload_min * 60:
                be.unload()                          # خمول: تفريغ النموذج من الذاكرة
                handoff.clear_last_if_me()
            _cleanup()
            return
        _run_job(job)
        _cleanup()                                   # حتى مع طابور مزدحم (بدل ما نستنى فراغه): tmpfs المخرجات محدود

    def worker() -> None:
        while not state["stop"]:
            try:
                _tick()
            except Exception:
                log.exception("خطأ بحلقة العامل")
                time.sleep(0.5)

    def _ensure_worker() -> None:
        t = state["thread"]
        if t is None or not t.is_alive():
            state["stop"] = False
            t = threading.Thread(target=worker, daemon=True, name=f"engine-worker-{me}")
            state["thread"] = t
            t.start()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _ensure_worker()
        if be.name in ("diffusers", "ltx", "wan"):          # أول /health بيستورد torch (ثواني): نسخّنه بالخلفية عشان فحص صحة Docker ما يتأخر
            threading.Thread(target=_gpu, daemon=True, name="engine-gpu-probe").start()
        yield
        state["stop"] = True
        with cv:
            cv.notify_all()
        t = state["thread"]
        if t is not None:
            t.join(timeout=5)
        if lock.held:                               # حماية: ما نترك القفل ماسوك
            lock.release()

    app = FastAPI(title=f"engine:{me}", lifespan=lifespan)

    def _token_ok(tok: str | None) -> bool:
        return not s.token or bool(tok and hmac.compare_digest(tok.encode("utf-8"), s.token.encode("utf-8")))

    @app.middleware("http")
    async def _limit_upload(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/jobs":
            if not _token_ok(request.headers.get("x-engine-token")):         # التوكن قبل ما يتقرا الجسم: طلب غير مصرّح ما بيخزّن شي بـ /tmp
                return JSONResponse({"detail": "توكن الصندوق غير صالح"}, status_code=401)
            cl = request.headers.get("content-length")
            if cl is None:                                                      # رفع بالقطع بلا طول معلن = ما في سقف: ممنوع (عملاؤنا كلهم بيبعتوا الطول)
                return JSONResponse({"detail": "لازم ترويسة Content-Length (الرفع بالقطع مش مدعوم)"}, status_code=411)
            try:
                too_big = int(cl) > 3 * max_image_bytes + 64 * 1024            # لحد 3 صور (image + image2 + image3)، وكل وحدة بتتفحص لحالها
            except ValueError:
                too_big = True
            if too_big:
                return JSONResponse({"detail": f"الطلب أكبر من الحد ({s.max_image_mb:g}MB للصورة)"}, status_code=413)
        return await call_next(request)

    def _auth(tok: str | None) -> None:
        if not _token_ok(tok):
            raise HTTPException(401, "توكن الصندوق غير صالح")

    def _gpu() -> dict | None:
        """ذاكرة الكرت (GB) لو torch موجود وفي كرت — الاستوديو بيعتمد عليها لاختيار موديل التحريك."""
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                return {"free_gb": round(free / 1024 ** 3, 1), "total_gb": round(total / 1024 ** 3, 1)}
        except Exception:
            pass
        return None

    @app.get("/health")
    def health() -> dict:
        with cv:
            queued = sum(1 for j in jobs.values() if j.status in ("queued", "waiting_gpu"))
            running = sum(1 for j in jobs.values() if j.status == "running")
        t = state["thread"]
        return {"ok": True, "api": API_VERSION, "backend": be.name, "name": me, "tasks": list(be.tasks), "loaded": be.loaded, "loaded_model": be.loaded_model, "gpu": _gpu(),
                "queued": queued, "running": running, "gpu_lock_held_here": lock.held, "gpu_busy": lock.busy(),
                "worker_alive": bool(t and t.is_alive()), "max_seconds": s.max_seconds, "audio_max_seconds": s.audio_max_seconds}

    @app.get("/models")
    def models(refresh: bool = False, x_engine_token: str | None = Header(None)) -> dict:
        """النماذج اللي بالصندوق: الاسم والنوع والأنماط والحجم والرخصة (للمساعدة) وصلاحيته مع سبب الرفض."""
        _auth(x_engine_token)
        return {"api": API_VERSION, "backend": be.name, "models": be.list_models(refresh)}

    async def _read_upload(up: UploadFile, label: str) -> tuple[bytes, str]:
        data = await up.read(max_image_bytes + 1)
        if not data:
            raise HTTPException(400, f"{label} فاضية")
        if len(data) > max_image_bytes:
            raise HTTPException(413, f"{label} أكبر من الحد ({s.max_image_mb:g}MB)")
        sniffed = _sniff_image(data)
        if sniffed is None:
            raise HTTPException(415, "نوع الصورة مش مدعوم — PNG أو JPG أو WEBP بس")
        _check_image(data)
        return data, sniffed

    @app.post("/jobs")
    async def submit(params: str = Form("{}"), image: UploadFile | None = File(None), image2: UploadFile | None = File(None),
                     image3: UploadFile | None = File(None), x_engine_token: str | None = Header(None)) -> dict:
        _auth(x_engine_token)
        try:
            p = json.loads(params or "{}")
        except json.JSONDecodeError:
            raise HTTPException(400, "المعاملات لازم تكون JSON") from None
        if not isinstance(p, dict):
            raise HTTPException(400, "المعاملات لازم تكون كائن JSON")
        p = validate_params(p, be.tasks, be.name, s.max_seconds, s.audio_max_seconds)
        try:
            p = await run_in_threadpool(be.validate_params, p)                  # بيمسح مجلد الأوزان لو الاسم مجهول: خارج حلقة الأحداث (/health ما بيتأخر)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        mode = p["mode"]
        uploads: list[tuple[bytes, str]] = []
        if mode in IMAGE_MODES:
            if image is None:
                raise HTTPException(400, {"i2v": "وضع صورة لفيديو بدّه صورة", "i2i": "تعديل الصورة بدّه صورة", "upscale": "التكبير بدّه صورة"}[mode])
            uploads.append(await _read_upload(image, "الصورة"))
            extras = [x for x in (image2, image3) if x is not None]
            if extras and mode != "i2i":
                raise HTTPException(400, "الصور الإضافية (image2/image3) بس لتعديل الصور (i2i)")
            for k, up in enumerate(extras, 2):
                uploads.append(await _read_upload(up, f"الصورة {k}"))
        _ensure_worker()
        jid = uuid.uuid4().hex[:16]
        img_path: Path | None = None
        more: list[Path] = []
        with cv:
            waiting = sum(1 for j in jobs.values() if j.status in ("queued", "waiting_gpu"))
            if waiting >= s.max_queue:
                raise HTTPException(429, f"الطابور ممتلئ ({s.max_queue} مهمة) — استنى شوي")
            for k, (data, ext) in enumerate(uploads):
                f = s.outputs / (f"{jid}_in{ext}" if k == 0 else f"{jid}_in{k + 1}{ext}")      # الاسم من عندنا بس: ما بنستعمل اسم ملف العميل
                f.write_bytes(data)
                if k == 0:
                    img_path = f
                else:
                    more.append(f)
            job = Job(id=jid, params=p, image=img_path, extra_images=more)
            jobs[jid] = job
            order.append(jid)
            cv.notify_all()
        return {"id": jid, "status": job.status}

    def _get(jid: str) -> Job:
        j = jobs.get(jid)
        if not j:
            raise HTTPException(404, "المهمة غير موجودة")
        return j

    @app.get("/jobs/{jid}")
    def status(jid: str, x_engine_token: str | None = Header(None)) -> dict:
        _auth(x_engine_token)
        return _get(jid).public()

    @app.get("/jobs/{jid}/result")
    def result(jid: str, x_engine_token: str | None = Header(None)):
        _auth(x_engine_token)
        j = _get(jid)
        if j.purged:
            raise HTTPException(410, "ملف المهمة انحذف")
        if j.status != "done" or not j.result or not _inside_outputs(j.result) or not j.result.exists():
            raise HTTPException(409, f"المهمة مش جاهزة (الحالة: {j.status})")
        return FileResponse(j.result, media_type=MEDIA_TYPES.get(j.result.suffix.lower(), "application/octet-stream"))

    @app.delete("/jobs/{jid}")
    def cancel(jid: str, x_engine_token: str | None = Header(None)) -> dict:
        _auth(x_engine_token)
        j = _get(jid)
        with cv:
            if j.status in TERMINAL:
                _purge_files(j)                      # خلصت: بس نظّف ملفاتها (الحالة بتضل كما هي)
                return j.public()
            j.cancel.set()
            if j.status == "queued":                 # ما استلمها العامل بعد: نلغيها هون تحت نفس القفل
                j.status, j.finished_at = "cancelled", time.time()
                _rm(j.image)
                j.image = None
                for x in j.extra_images:
                    _rm(x)
                j.extra_images = []
            cv.notify_all()
        return j.public()

    app.state.engine = {"settings": s, "backend": be, "jobs": jobs, "lock": lock, "cleanup": _cleanup, "name": me}
    return app
