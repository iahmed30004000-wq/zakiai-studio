"""
تشغيل نموذج من مكتبة النماذج — عقد واحد لكل المهام وكل طرق الربط.

    res = model_run.run(model, RunRequest(task="image", prompt="…", out=Path(".../shot.png")))

شو بيصير:
  1. بوابة الرخصة والتفعيل (model_library.usable) — نموذج معطّل أو رخصته ما بتسمح ما بيشتغل.
  2. حجز الكرت (gpu_lease) لو النموذج بيستعمله وVP_GPU_LOCK_DIR مضبوط.
  3. الطريقة (link_std / link_cmd / …) بتكتب الناتج بمجلد مؤقت.
  4. فحص الناتج بالمحتوى (media_check): نوع، حجم، مدة، شفافية لتفريغ الخلفية — وبعدين مطابقة الصيغة مع امتداد الملف النهائي ونقل ذرّي.
  5. سطر بسجل الإنتاج لكل محاولة (نجحت/فشلت، كم أخدت، أي نموذج، أي طريقة).

الفشل = RunError(message، reason، technical). technical=True معناها عطل بالنموذج/السيرفر (مهلة، اتصال، ذاكرة، ناتج تالف…)
والمستدعي بيقرر: يرجع للطريقة الحالية لو pick() قال fallback_builtin، أو يفشل برسالة عربية. غير تقني = إلغاء، رخصة، مدخلات ناقصة.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import config
import media_check
import model_library

TASK_KIND = {"image": "image", "voice": "voice", "stt": "stt", "lipsync": "lipsync", "upscale": "upscale", "bgremove": "bgremove",
             "music": "music", "sfx": "sfx", "motion": "motion"}               # production_log.KINDS
LINK_PATH = {"std": "std", "command": "command", "app": "app", "weights": "http"}   # production_log.PATHS
OUT_KIND = {"image": "image", "upscale": "image", "bgremove": "image", "voice": "audio", "music": "audio", "sfx": "audio",
            "lipsync": "video", "stt": None}                                    # نوع الملف الناتج (stt = بيانات بس)
MAX_AUDIO_SEC = {"voice": 600.0, "music": 600.0, "sfx": 120.0}
GPU_WAIT_SEC = 900.0


class RunError(Exception):
    """فشل تشغيل نموذج. reason: timeout|connection|auth|rejected|missing|busy|oom|model_failed|bad_output|config|unsupported|licence|cancelled."""

    def __init__(self, message: str, reason: str = "model_failed", technical: bool = True):
        super().__init__(message)
        self.reason = reason
        self.technical = technical


@dataclass
class RunRequest:
    task: str
    out: Path | None = None                                                # الملف النهائي (إلا التفريغ: بيانات بس)
    prompt: str = ""
    negative: str = ""
    text: str = ""                                                         # الصوت: النص المنطوق
    image: Path | None = None                                              # التكبير/تفريغ الخلفية: الصورة. الصور: صورة التعديل
    refs: list = field(default_factory=list)                               # صور مرجعية
    audio: Path | None = None
    video: Path | None = None
    language: str | None = None
    seconds: float | None = None
    params: dict = field(default_factory=dict)                             # تغليب على معاملات النموذج (width/height/steps…)
    cancel: object | None = None                                           # أي شي فيه is_set()
    log: Callable[[str], None] | None = None
    script_stem: str | None = None
    shot_id: str | None = None
    record: bool = True                                                    # False: تجربة من الشاشة (ما بتنحسب بنسبة النجاح)


@dataclass
class RunResult:
    path: Path | None
    kind: str | None
    seconds: float
    model_id: str
    model_name: str
    info: dict = field(default_factory=dict)                              # فحص الملف: أبعاد/مدة…
    data: dict = field(default_factory=dict)                              # التفريغ: {text, language, words[], segments[]}


@dataclass
class Ctx:
    """سياق تشغيل واحد بيمرّ للطريقة (link_*)."""
    model: dict
    req: RunRequest
    params: dict
    tmp: Path
    deadline: float                                                        # time.monotonic()

    def cancelled(self) -> bool:
        c = self.req.cancel
        return bool(c is not None and c.is_set())

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def log(self, msg: str) -> None:
        if self.req.log:
            self.req.log(msg)

    def check(self) -> None:
        if self.cancelled():
            raise RunError("انلغت الشغلة", "cancelled", False)
        if self.remaining() <= 0:
            raise RunError(f"النموذج تجاوز المهلة ({int(self.model['timeout_sec'])} ثانية)", "timeout")


def tmp_root() -> Path:
    return Path(config.LIBRARY_DIR) / "tmp" / "modelrun"


def _runner(link: str):
    if link == "std":
        import link_std
        return link_std.run
    if link == "command":
        import link_cmd
        return link_cmd.run
    if link == "weights":
        import link_engine
        return link_engine.run
    if link == "app":
        import link_app
        return link_app.run
    return None


def _log_attempt(model: dict, req: RunRequest, ok: bool, seconds: float, error=None) -> None:
    if not req.record:
        return
    try:
        import production_log
        production_log.record(TASK_KIND[req.task], "ok" if ok else "failed", script_stem=req.script_stem, shot_id=req.shot_id,
                              model_id=model["id"], model_name=model["name"], path=LINK_PATH[model["link"]], seconds=seconds, error=error)
    except Exception:                                                      # noqa: BLE001 — السجل ما بيكسر الإنتاج أبداً
        pass


def run(model: dict, req: RunRequest) -> RunResult:
    task = req.task
    if task != model.get("task"):
        raise RunError(f"«{model.get('name')}» نموذج {model_library.TASK_LABELS.get(model.get('task'), '؟')} مش لهالمهمة", "unsupported", False)
    ok, why = model_library.usable(model)
    if not ok:
        raise RunError(f"«{model['name']}»: {why}", "licence" if "رخصته" in why else "config", False)
    runner = _runner(model["link"])
    if runner is None:
        raise RunError(f"ربط «{model_library.LINK_LABELS.get(model['link'], model['link'])}» لسا مش مفعّل بهالنسخة", "unsupported", False)
    if OUT_KIND[task] and not req.out:
        raise RunError("ما انحدّد ملف الناتج", "config", False)
    params = {**(model.get("params") or {}), **{k: v for k, v in (req.params or {}).items() if v not in (None, "")}}
    root = tmp_root()
    t0 = time.monotonic()
    try:
        root.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="run_", dir=root))
    except OSError:
        raise RunError("ما قدرت أجهّز مجلد مؤقت للنموذج (المجلد مقفول أو ممتلي؟)", "config", True) from None
    ctx = Ctx(model, req, params, tmp, t0 + float(model["timeout_sec"]))
    try:
        import gpu_lease
        try:
            with gpu_lease.hold(uses_gpu=bool(model.get("uses_gpu")), wait_sec=min(GPU_WAIT_SEC, float(model["timeout_sec"])), cancelled=ctx.cancelled):
                raw = runner(ctx)
        except gpu_lease.GpuBusy as e:
            raise RunError(str(e), "busy") from None
        except gpu_lease.GpuCancelled as e:
            raise RunError(str(e), "cancelled", False) from None
        result = _finish(ctx, raw, time.monotonic() - t0)
        _log_attempt(model, req, True, result.seconds)
        return result
    except RunError as e:
        _log_attempt(model, req, False, time.monotonic() - t0, f"{e.reason}: {e}")
        raise
    except Exception as e:                                                 # noqa: BLE001 — خلل غير متوقع بالطريقة: ما بنخلّيه ينهار الإنتاج
        _log_attempt(model, req, False, time.monotonic() - t0, f"unexpected: {type(e).__name__}")
        raise RunError(f"فشل غير متوقع بتشغيل النموذج ({type(e).__name__})", "model_failed") from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _finish(ctx: Ctx, raw: dict, seconds: float) -> RunResult:
    """فحص الناتج + مطابقة الصيغة + نقل ذرّي لمكانه النهائي."""
    model, req = ctx.model, ctx.req
    kind = OUT_KIND[req.task]
    data = raw.get("data") or {}
    if kind is None:                                                       # التفريغ: بيانات
        if not str(data.get("text") or "").strip() and not data.get("words"):
            raise RunError("النموذج ما رجّع نص", "bad_output")
        return RunResult(None, None, round(seconds, 2), model["id"], model["name"], {}, data)
    src = raw.get("file")
    if not src:
        raise RunError("النموذج ما كتب ملف ناتج", "bad_output")
    src = Path(src)
    try:
        kw = {"max_sec": MAX_AUDIO_SEC[req.task]} if req.task in MAX_AUDIO_SEC else {}
        info = media_check.check(src, kind, **kw)
        out = Path(req.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = out.with_name(f".{out.stem}.{os.getpid()}.part{out.suffix}")   # الامتداد نفسه: الفحص والتحويل بيعتمدوا عليه
        try:
            if kind == "image":
                if req.task == "bgremove" and not info["alpha"]:
                    raise RunError("النموذج ما رجّع صورة بخلفية شفافة", "bad_output")
                media_check.conform_image(src, staging, keep_alpha=req.task == "bgremove")
            elif kind == "audio":
                media_check.conform_audio(src, staging)
            else:
                shutil.copyfile(src, staging)
            os.replace(staging, out)
        finally:
            staging.unlink(missing_ok=True)
    except media_check.MediaCheckError as e:
        raise RunError(f"ناتج النموذج مرفوض: {e}", "bad_output") from None
    except OSError:
        raise RunError("ما قدرت أكتب ناتج النموذج بمكانه (المجلد مقفول أو ممتلي؟)", "config", True) from None
    return RunResult(out, kind, round(seconds, 2), model["id"], model["name"], info, data)


# ── ربط المكتبة بنقاط التوليد الموجودة ────────────────────────────────────
def _lib_error(error_cls, message: str, logged: bool):
    e = error_cls(message)
    e.logged = logged                     # model_run سجّل المحاولة بسجل الإنتاج: المستدعي ما يسجّلها مرة تانية
    return e


def run_via_library(task: str, req: RunRequest, override=None, *, error_cls=RuntimeError, accept=None, params_for=None) -> tuple[RunResult | None, str]:
    """يجرّب نموذج المكتبة لهالمهمة (الافتراضي، أو lib:ml_x الصريح). بيرجّع (النتيجة، ملاحظة).
    النتيجة None = كمّل بالطريقة الحالية: ما في نموذج مربوط، أو النموذج وقع تقنياً والرجوع مسموح (الملاحظة بتقول ليش).
    غير هيك بيرمي error_cls برسالة عربية — وعليه logged=True لو model_run سجّل المحاولة.
    accept(res) → سبب رفض (نص) أو None: ناتج ما بينفع للمستدعي (مثلاً تفريغ بلا توقيتات) بيعامَل كعطل تقني بالنموذج.
    params_for(model) → معاملات إضافية حسب النموذج المختار (بتغلب عليها معاملات req الصريحة)."""
    try:
        pk = model_library.pick(task, override)
    except model_library.ModelLibraryError as e:
        raise _lib_error(error_cls, str(e), False) from None
    if pk.model is None:
        return None, pk.reason
    if params_for:
        req.params = {**(params_for(pk.model) or {}), **(req.params or {})}
    try:
        res = run(pk.model, req)
        why = accept(res) if accept else None
        if why:
            raise RunError(f"ناتج النموذج ما بينفع: {why}", "bad_output", True)
        return res, ""
    except RunError as e:
        if e.technical and pk.fallback_builtin:
            return None, f"نموذج المكتبة «{pk.model['name']}» وقع ({e}) — كملنا بالطريقة الحالية"
        raise _lib_error(error_cls, f"«{pk.model['name']}»: {e}", True) from None
