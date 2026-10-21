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
from fastapi.responses import FileResponse, JSONResponse

log = logging.getLogger("engine")

OOM_MESSAGE = "الذاكرة ما كفّت — جرّب مدة أقصر أو دقة أقل"
STATUSES = ("queued", "waiting_gpu", "running", "done", "failed", "cancelled")
TERMINAL = ("done", "failed", "cancelled")
ALLOWED_PARAMS = {"mode", "prompt", "negative_prompt", "seconds", "fps", "seed", "steps", "guidance", "width", "height"}
FAKE_ONLY_PARAMS = {"sleep", "simulate_oom", "simulate_error"}      # خطّافات اختبار — بالخلفية التجريبية بس
HIDDEN_PARAMS = FAKE_ONLY_PARAMS
MAX_PROMPT_CHARS = 4000
MAX_NEGATIVE_CHARS = 2000
MAX_IMAGE_PIXELS = 64_000_000
_NAME_RX = re.compile(r"[^A-Za-z0-9_.-]")
_OUTPUT_FILE_RX = re.compile(r"^[0-9a-f]{16}(\.mp4|_in\.(png|jpg|webp))$")


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
    max_image_mb: float = 20.0
    keep_minutes: float = 120.0             # كم دقيقة بنخلّي ملفات المهمات المنتهية
    max_queue: int = 20
    max_pixels: int = 0                     # 0 = الافتراضي حسب الخلفية
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
            max_image_mb=_env_num("MAX_IMAGE_MB", 20.0, 0.1),
            keep_minutes=_env_num("OUTPUT_KEEP_MIN", 120.0, 1.0),
            max_queue=int(_env_num("MAX_QUEUE", 20, 1)),
            max_pixels=int(_env_num("MAX_PIXELS", 0, 0)),
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
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel: CancelEvent = field(default_factory=CancelEvent)

    def public(self) -> dict:
        took = round(self.finished_at - self.started_at, 2) if (self.finished_at and self.started_at) else None
        return {"id": self.id, "status": self.status, "error": self.error, "seconds_taken": took,
                "cancelling": self.cancel.is_set() and self.status not in TERMINAL,
                "progress": {"step": self.cancel.step, "total": self.cancel.total},
                "params": {k: v for k, v in self.params.items() if k not in HIDDEN_PARAMS}}


class GpuLock:
    """قفل ملف مشترك بين كل الصناديق (نفس المجلد مربوط بكلهم)."""

    def __init__(self, lock_dir: Path):
        from filelock import FileLock
        lock_dir.mkdir(parents=True, exist_ok=True)
        self.path = lock_dir / "gpu.lock"
        self._lock = FileLock(str(self.path))

    def acquire(self, timeout: float) -> bool:
        from filelock import Timeout
        try:
            self._lock.acquire(timeout=timeout)
            return True
        except Timeout:
            return False

    def release(self) -> None:
        if self._lock.is_locked:
            self._lock.release()

    @property
    def held(self) -> bool:
        return self._lock.is_locked

    def busy(self) -> bool:
        """هل في أي صندوق (حتى هاد) ماسك الكرت هلأ؟ بمحاولة قفل لحظية بنسخة منفصلة."""
        from filelock import FileLock, Timeout
        probe = FileLock(str(self.path), thread_local=False)
        try:
            probe.acquire(timeout=0)
        except Timeout:
            return True
        except OSError:
            return False
        probe.release()
        return False


class Handoff:
    """تسليم الكرت بين الصناديق: مين آخر واحد استعمله، وطلب «فرّغ نموذجك» بملفات صغيرة بالمجلد المشترك."""

    def __init__(self, lock_dir: Path, me: str):
        self.dir = lock_dir
        self.me = _NAME_RX.sub("_", me)

    def _req(self, name: str) -> Path:
        return self.dir / f"unload_{_NAME_RX.sub('_', name)}.req"

    @property
    def _last(self) -> Path:
        return self.dir / "last_user"

    def last_user(self) -> str | None:
        try:
            return self._last.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def mark_used(self) -> None:
        try:
            self._last.write_text(self.me, encoding="utf-8")
        except OSError:
            pass

    def clear_last_if_me(self) -> None:
        if self.last_user() == self.me:
            try:
                self._last.unlink()
            except OSError:
                pass

    def request_unload(self, other: str) -> None:
        try:
            self._req(other).write_text(self.me, encoding="utf-8")
        except OSError:
            pass

    def requested(self) -> bool:
        return self._req(self.me).exists()

    def done(self) -> None:
        try:
            self._req(self.me).unlink()
        except OSError:
            pass

    def pending_for(self, other: str) -> bool:
        return self._req(other).exists()


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


def validate_params(p: dict, tasks: tuple[str, ...], backend_name: str, max_seconds: float) -> dict:
    allowed = set(ALLOWED_PARAMS) | (FAKE_ONLY_PARAMS if backend_name == "fake" else set())
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
    if not 0.5 <= sec <= max_seconds:
        raise HTTPException(400, f"المدة لازم بين 0.5 و{max_seconds:g} ثانية")
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
        j.image, j.result, j.purged = None, None, True

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
            live = {p for j in jobs.values() for p in (j.image, j.result) if p}
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
            try:
                handoff._req(prev).unlink()
            except OSError:
                pass

    def _run_job(job: Job) -> None:
        got = False
        out = s.outputs / f"{job.id}.mp4"
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
            be.generate(job.params, job.image, out, job.cancel)
            if job.cancel.is_set():
                _rm(out)
                _finish(job, "cancelled")
            elif not out.exists() or out.stat().st_size == 0:
                _finish(job, "failed", "النموذج ما كتب فيديو")
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

    @app.middleware("http")
    async def _limit_upload(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/jobs":
            cl = request.headers.get("content-length")
            try:
                too_big = cl is not None and int(cl) > max_image_bytes + 64 * 1024
            except ValueError:
                too_big = True
            if too_big:
                return JSONResponse({"detail": f"الطلب أكبر من الحد ({s.max_image_mb:g}MB للصورة)"}, status_code=413)
        return await call_next(request)

    def _auth(tok: str | None) -> None:
        if s.token and not (tok and hmac.compare_digest(tok.encode("utf-8"), s.token.encode("utf-8"))):
            raise HTTPException(401, "توكن الصندوق غير صالح")

    @app.get("/health")
    def health() -> dict:
        with cv:
            queued = sum(1 for j in jobs.values() if j.status in ("queued", "waiting_gpu"))
            running = sum(1 for j in jobs.values() if j.status == "running")
        t = state["thread"]
        return {"ok": True, "backend": be.name, "name": me, "tasks": list(be.tasks), "loaded": be.loaded,
                "queued": queued, "running": running, "gpu_lock_held_here": lock.held, "gpu_busy": lock.busy(),
                "worker_alive": bool(t and t.is_alive()), "max_seconds": s.max_seconds}

    @app.post("/jobs")
    async def submit(params: str = Form("{}"), image: UploadFile | None = File(None),
                     x_engine_token: str | None = Header(None)) -> dict:
        _auth(x_engine_token)
        try:
            p = json.loads(params or "{}")
        except json.JSONDecodeError:
            raise HTTPException(400, "المعاملات لازم تكون JSON") from None
        if not isinstance(p, dict):
            raise HTTPException(400, "المعاملات لازم تكون كائن JSON")
        p = validate_params(p, be.tasks, be.name, s.max_seconds)
        data = b""
        ext = ".png"
        if image is not None and p["mode"] == "i2v":
            data = await image.read(max_image_bytes + 1)
            if not data:
                raise HTTPException(400, "الصورة فاضية")
            if len(data) > max_image_bytes:
                raise HTTPException(413, f"الصورة أكبر من الحد ({s.max_image_mb:g}MB)")
            sniffed = _sniff_image(data)
            if sniffed is None:
                raise HTTPException(415, "نوع الصورة مش مدعوم — PNG أو JPG أو WEBP بس")
            ext = sniffed
            _check_image(data)
        elif p["mode"] == "i2v":
            raise HTTPException(400, "وضع صورة لفيديو بدّه صورة")
        _ensure_worker()
        jid = uuid.uuid4().hex[:16]
        img_path: Path | None = None
        with cv:
            waiting = sum(1 for j in jobs.values() if j.status in ("queued", "waiting_gpu"))
            if waiting >= s.max_queue:
                raise HTTPException(429, f"الطابور ممتلئ ({s.max_queue} مهمة) — استنى شوي")
            if data:
                img_path = s.outputs / f"{jid}_in{ext}"        # الاسم من عندنا بس: ما بنستعمل اسم ملف العميل
                img_path.write_bytes(data)
            job = Job(id=jid, params=p, image=img_path)
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
        return FileResponse(j.result, media_type="video/mp4")

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
            cv.notify_all()
        return j.public()

    app.state.engine = {"settings": s, "backend": be, "jobs": jobs, "lock": lock, "cleanup": _cleanup, "name": me}
    return app
