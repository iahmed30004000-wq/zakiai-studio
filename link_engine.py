"""
ربط «أوزان على السيرفر» (weights): صندوق الأوزان العام (services/engine، ENGINE_BACKEND=diffusers) — عميل http.

    POST /jobs (params JSON + image/image2/image3)  ←  GET /jobs/{id} (استطلاع)  ←  GET /jobs/{id}/result  ←  DELETE /jobs/{id}
    GET  /health   صحة الصندوق وذاكرة الكرت والنموذج المحمّل          GET /models   النماذج اللي بمجلد الأوزان (بالتوكن)

نسخة مقصودة من عميل التحريك (motion._run_http): اختبارات التحريك بتبدّل motion._engine_call فما منشارك الدوال.
الفرق: عنوان الصندوق وتوكنه من مكتبة النماذج (box: url + token_secret) مش من كل نموذج — صندوق واحد على السيرفر، والنموذج بيتحدّد
باسم مجلد أوزانه (weights.model). الصور (t2i/i2i) والتكبير (upscale) والموسيقى والمؤثرات (t2a) هون؛ التحريك بيمرّ من سجل موديلات التحريك (kind=http + model).

قواعد ثابتة (نفس عميل التحريك والواجهة القياسية):
  · العنوان بيمرّ على net_allow (http فقط، 127.x أو اسم docker، منفذ صريح)، وكل نداء بيتلحم عبر net_allow.join.
  · بلا بروكسي من البيئة (trust_env=False)، وبلا تحويلات أبداً، وبسقوف حجم للرد.
  · التوكن من مخزن الأسرار باسم box.token_secret، وإلا من متغير البيئة ENGINE_TOKEN (سيرفر لينكس: الـ compose بيمرّره من .env).
    بيروح بترويسة X-Engine-Token بس — ما بيتسجّل ولا بيظهر بأي رسالة.
  · DELETE /jobs/{id} بالنهاية دايماً (إلغاء لو لسا شغّالة، تنظيف لو خلصت) — حتى لو انلغت الشغلة أو خلصت المهلة عنا.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from pathlib import Path

import net_allow
from model_run import Ctx, RunError

CONNECT_TIMEOUT = 10
CALL_TIMEOUT = 30                      # مهلة نداء واحد (مش مهلة الشغلة كلها)
POLL_SEC = 1.0
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 256 * 1024 * 1024
MAX_UPLOAD_MB = 18                     # أكبر من هيك الصورة بتنضغط JPEG قبل الإرسال (حد الصندوق 20)
ENGINE_MAX_SIDE = 2048                 # حد الصندوق لأبعاد الصورة المطلوبة
OOM_MARK = "الذاكرة ما كفّت"
API_MIN = 2                            # عقد الصندوق العام (v2): الصناديق الأقدم (ltx/wan) بلا /models وبلا أنماط الصور
JOB_ID_RX = re.compile(r"[A-Za-z0-9_-]{1,64}")
GPU_TTL_SEC = 30.0
GPU_FAIL_TTL_SEC = 10.0
MAX_DETAIL_BYTES = 64 * 1024                           # رد خطأ: ما بنقرا أكتر من هيك
BODY_MAX_SEC = 120.0                                   # جسم رد JSON واحد: لو طوّل أكتر من هيك بنقطعه
_DETAIL_RX = re.compile(r"\s+")

_gpu_cache: dict = {"key": None, "at": 0.0, "val": None}
_gpu_lock = threading.Lock()


# ── الإعداد: الصندوق من مكتبة النماذج ────────────────────────────────────
def token() -> str | None:
    """توكن الصندوق: مخزن الأسرار (اسمه بإعداد الصندوق) ثم ENGINE_TOKEN. None = بلا توكن."""
    name = None
    try:
        import model_library
        name = model_library.load()["box"].get("token_secret")
    except Exception:                                  # noqa: BLE001 — مكتبة تالفة: منكمّل بدون
        pass
    v = None
    if name:
        try:
            import secrets_store
            v = secrets_store.get_secret(name) or None
        except Exception:                              # noqa: BLE001 — مخزن غير متاح
            v = None
    return v or os.environ.get("ENGINE_TOKEN") or None


def box_url() -> str | None:
    """عنوان صندوق الأوزان المنظَّف من المكتبة، أو None لو ما انربط."""
    try:
        import model_library
        url = model_library.load()["box"].get("url")
    except Exception:                                  # noqa: BLE001
        return None
    if not url:
        return None
    try:
        return net_allow.validate(url, subject="عنوان صندوق الأوزان", example="http://127.0.0.1:8100")
    except net_allow.NetAllowError:
        return None


def session(tok: str | None = None):
    import requests
    s = requests.Session()
    s.trust_env = False                                # ما نمرّر النداء عبر أي بروكسي من البيئة
    if tok:
        s.headers["X-Engine-Token"] = tok
    return s


def _detail(resp) -> str:
    try:
        raw = b""
        for chunk in resp.iter_content(8192):          # بسقف: رد خطأ ضخم ما بيتحمّل كله بالذاكرة
            raw += chunk
            if len(raw) >= MAX_DETAIL_BYTES:
                break
        d = json.loads(raw.decode("utf-8", "replace"))
        msg = d.get("detail") if isinstance(d, dict) else None
        if isinstance(msg, (list, dict)):
            msg = json.dumps(msg, ensure_ascii=False)
        if msg:
            return _DETAIL_RX.sub(" ", str(msg))[:200]
    except Exception:                                  # noqa: BLE001
        pass
    return f"رد {resp.status_code}"


def _call(sess, method: str, base: str, path: str, ctx: Ctx | None = None, *, timeout: float | None = None, stream: bool = True, **kw):
    """نداء واحد للصندوق: كل فشل بيتحوّل لـ RunError بسبب واضح. بلا تحويلات أبداً."""
    import requests
    if ctx is not None:
        ctx.check()
    try:
        url = net_allow.join(base, path)
    except net_allow.NetAllowError as e:
        raise RunError(str(e), "config") from None
    try:
        r = sess.request(method, url, timeout=(CONNECT_TIMEOUT, max(1.0, timeout or CALL_TIMEOUT)), allow_redirects=False, stream=stream, **kw)
    except requests.exceptions.ConnectTimeout:
        raise RunError("صندوق الأوزان ما ردّ بوقت الاتصال", "connection") from None
    except requests.exceptions.ReadTimeout:
        raise RunError("صندوق الأوزان تأخر بالرد", "timeout") from None
    except requests.exceptions.RequestException:
        raise RunError("ما قدرت أتصل بصندوق الأوزان — واقف أو العنوان غلط", "connection") from None
    code = r.status_code
    if 300 <= code < 400:
        r.close()
        raise RunError("الصندوق حاول يحوّلنا لعنوان ثاني — التحويلات ممنوعة", "connection")
    if code == 401:
        r.close()
        raise RunError("توكن صندوق الأوزان غلط أو ناقص — راجع توكن الصندوق بمكتبة النماذج", "auth")
    if code == 404:
        msg = _detail(r)
        r.close()
        raise RunError(f"الصندوق ما عنده هالمسار أو المهمة ({msg})", "missing")
    if code == 429:
        r.close()
        raise RunError("طابور الصندوق ممتلئ — جرّب بعد شوي", "busy")
    if code >= 400:
        msg = _detail(r)
        r.close()
        raise RunError(f"الصندوق رفض الطلب: {msg}", "oom" if OOM_MARK in msg else ("rejected" if code < 500 else "model_failed"))
    return r


def _body(resp, cap: int) -> bytes:
    chunks, got, t_end = [], 0, time.monotonic() + BODY_MAX_SEC
    try:
        for chunk in resp.iter_content(1 << 16):
            got += len(chunk)
            if got > cap:
                raise RunError("رد الصندوق أكبر من الحد المسموح", "bad_output")
            if time.monotonic() > t_end:
                raise RunError("رد الصندوق طوّل كتير (بيجي بالقطّارة)", "timeout")
            chunks.append(chunk)
    except RunError:
        raise
    except Exception:                                  # noqa: BLE001
        raise RunError("انقطع تنزيل الرد من الصندوق", "connection") from None
    finally:
        resp.close()
    return b"".join(chunks)


def _json(resp, cap: int = MAX_JSON_BYTES) -> dict:
    raw = _body(resp, cap)
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise RunError("رد الصندوق مش JSON مفهوم", "bad_output") from None
    if not isinstance(d, dict):
        raise RunError("رد الصندوق مش بالشكل المتوقع", "bad_output")
    return d


# ── فحص الصندوق ──────────────────────────────────────────────────────────
def _fail(reason: str, message: str, **extra) -> dict:
    return {"ok": False, "reason": reason, "message": message, "models": [], "api": None, "gpu": None, "loaded_model": None, **extra}


def status(url: str | None = None, tok: str | None = None, *, refresh: bool = False, timeout: float = 8) -> dict:
    """حالة الصندوق: {ok, reason, message, url, api, backend, tasks, gpu{free_gb,total_gb}, loaded_model, queued, running, models[]}.
    ما بيرمي — بيرجّع السبب. بدون معاملات: الصندوق المضبوط بالمكتبة. صندوق قديم (ltx/wan: بلا /models) = models بنموذج وحيد ثابت."""
    try:
        base = net_allow.validate(url if url is not None else box_url(), subject="عنوان صندوق الأوزان", example="http://127.0.0.1:8100")
    except net_allow.NetAllowError as e:
        return _fail("config", str(e) if url else "صندوق الأوزان مش مربوط — حط عنوانه (مثال: http://engine:8000)", url=None)
    sess = session(tok if tok is not None else token())
    try:
        h = _json(_call(sess, "GET", base, "/health", None, timeout=timeout), 1024 * 1024)
        if not h.get("ok"):
            return _fail("model_failed", "الصندوق رد لكن مش بحالة سليمة", url=base)
        out = {"ok": True, "reason": "", "message": "", "url": base, "api": h.get("api"), "backend": h.get("backend"), "tasks": list(h.get("tasks") or []),
               "gpu": h.get("gpu") if isinstance(h.get("gpu"), dict) else None, "loaded_model": h.get("loaded_model"), "queued": int(h.get("queued") or 0),
               "running": int(h.get("running") or 0), "gpu_busy": bool(h.get("gpu_busy")), "models": [], "legacy": not h.get("api"),
               "audio_max_seconds": h.get("audio_max_seconds") if isinstance(h.get("audio_max_seconds"), (int, float)) and not isinstance(h.get("audio_max_seconds"), bool) else None}
        if out["legacy"]:
            out["message"] = f"الصندوق شغّال ({h.get('backend')}) بنموذج ثابت — للصور والتكبير لازم الصندوق العام (api 2)"
            out["models"] = [{"name": h.get("backend") or "?", "kind": "video", "tasks": out["tasks"], "ok": True, "reason": "", "size_gb": None,
                              "licence": {"id": "غير معروفة", "commercial": "unknown"}, "pipeline": "", "family": "", "note": "صندوق بنموذج ثابت"}]
            return out
        r = _json(_call(sess, "GET", base, "/models", None, timeout=timeout, params={"refresh": "1"} if refresh else None), 4 * 1024 * 1024)
        models = [m for m in (r.get("models") if isinstance(r.get("models"), list) else []) if isinstance(m, dict) and isinstance(m.get("name"), str)]
        out["models"] = models[:500]
        good = sum(1 for m in out["models"] if m.get("ok"))
        out["message"] = f"الصندوق شغّال — {good} نموذج جاهز" + (f" و{len(out['models']) - good} مرفوض" if len(out["models"]) > good else "")
        return out
    except RunError as e:
        return _fail(e.reason, str(e), url=base)
    finally:
        sess.close()


def gpu_info(*, refresh: bool = False) -> dict | None:
    """ذاكرة كرت الصندوق {free_gb, total_gb} (بكاش 30 ثانية) أو None لو ما في صندوق/ما رد. بيستعملها التحريك والنظرة العامة."""
    base = box_url()
    if not base:
        return None
    now = time.monotonic()
    with _gpu_lock:
        c = _gpu_cache
        if not refresh and c["key"] == base and now - c["at"] < (GPU_TTL_SEC if c["val"] else GPU_FAIL_TTL_SEC):
            return dict(c["val"]) if c["val"] else None
    val = None
    sess = session(token())
    try:
        h = _json(_call(sess, "GET", base, "/health", None, timeout=4), 1024 * 1024)
        g = h.get("gpu")
        if isinstance(g, dict) and isinstance(g.get("total_gb"), (int, float)):
            val = {"free_gb": float(g.get("free_gb") or 0), "total_gb": float(g["total_gb"])}
    except RunError:
        val = None
    finally:
        sess.close()
    with _gpu_lock:
        _gpu_cache.update(key=base, at=now, val=val)
    return dict(val) if val else None


def clear_cache() -> None:
    with _gpu_lock:
        _gpu_cache.update(key=None, at=0.0, val=None)


# ── التشغيل ──────────────────────────────────────────────────────────────
def _image_payload(img: Path) -> tuple[bytes, str]:
    """بايتات الصورة ونوعها. لو أكبر من الحد أو بصيغة غريبة بتتحوّل JPEG."""
    try:
        data = Path(img).read_bytes()
    except OSError:
        raise RunError("ما قدرت أقرا الصورة", "config", False) from None
    kind = ("image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if data.startswith(b"\xff\xd8\xff")
            else "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None)
    if kind and len(data) <= MAX_UPLOAD_MB * 1024 * 1024:
        return data, kind
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=92)
    except Exception:                                  # noqa: BLE001
        raise RunError("الصورة تالفة أو بصيغة مش مدعومة", "config", False) from None
    return buf.getvalue(), "image/jpeg"


def _uploads(paths: list) -> dict:
    files = {}
    for i, p in enumerate(paths[:3]):
        data, mime = _image_payload(Path(p))
        name = "image" if i == 0 else f"image{i + 1}"
        files[name] = (name + (".png" if mime == "image/png" else ".webp" if mime == "image/webp" else ".jpg"), data, mime)
    return files


def _size(p: dict) -> dict:
    """العرض والارتفاع المطلوبين (لو انحددوا) بحدود الصندوق (≤ 2048 للضلع)، بنفس النسبة."""
    if not (p.get("width") and p.get("height")):
        return {}
    w, h = int(p["width"]), int(p["height"])
    scale = min(1.0, ENGINE_MAX_SIDE / max(w, h))
    return {"width": max(64, int(w * scale)), "height": max(64, int(h * scale))}


def _run_job(ctx: Ctx, sess, base: str, params: dict, files: dict | None, want_kind: str) -> Path:
    """POST ← استطلاع ← تنزيل النتيجة ← (دايماً) DELETE."""
    jid = None
    try:
        r = _call(sess, "POST", base, "/jobs", ctx, data={"params": json.dumps(params, ensure_ascii=False)}, files=files or None)
        jid = _json(r).get("id")
        if not isinstance(jid, str) or not JOB_ID_RX.fullmatch(jid):
            jid = None
            raise RunError("رد الصندوق غير مفهوم (ما في رقم مهمة)", "bad_output")
        ctx.log(f"[الصندوق] {base} ({params['mode']}، {params['model']})")
        last = None
        while True:
            ctx.check()                                 # إلغاء أو مهلة ← RunError، والـ finally بيلغي المهمة بالصندوق
            st = _json(_call(sess, "GET", base, f"/jobs/{jid}", ctx))
            status_, pr = st.get("status"), st.get("progress") or {}
            tag = (status_, pr.get("step"))
            if tag != last:
                last = tag
                ctx.log(f"[الصندوق] {status_}" + (f" {pr.get('step')}/{pr.get('total')}" if pr.get("total") else ""))
            if status_ == "done":
                break
            if status_ == "failed":
                err = str(st.get("error") or "فشل بدون سبب")
                raise RunError(f"الصندوق فشل: {err}", "oom" if OOM_MARK in err else "model_failed")
            if status_ == "cancelled":
                raise RunError("الصندوق ألغى المهمة", "model_failed")
            time.sleep(max(0.0, min(POLL_SEC, ctx.remaining())))
        kind = st.get("result_kind")
        if kind and kind != want_kind:
            raise RunError(f"الصندوق رجّع {kind} بدل {want_kind}", "bad_output")
        resp = _call(sess, "GET", base, f"/jobs/{jid}/result", ctx, stream=True, timeout=max(CALL_TIMEOUT, min(300.0, ctx.remaining())))
        out = ctx.tmp / "result.bin"
        got = 0
        try:
            with open(out, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    got += len(chunk)
                    if got > MAX_RESULT_BYTES:
                        raise RunError("ناتج الصندوق أكبر من الحد المسموح", "bad_output")
                    f.write(chunk)
        except RunError:
            raise
        except Exception:                               # noqa: BLE001
            raise RunError("انقطع تنزيل الناتج من الصندوق", "connection") from None
        finally:
            resp.close()
        if got == 0:
            raise RunError("الصندوق رجّع ملف فاضي", "bad_output")
        return out
    finally:
        if jid:
            try:
                _call(sess, "DELETE", base, f"/jobs/{jid}", None, timeout=5).close()
            except Exception:                           # noqa: BLE001 — تنظيف بقدر الإمكان
                pass


def _image(ctx: Ctx, sess, base: str) -> dict:
    m, cfg, p, req = ctx.model, ctx.model["weights"], ctx.params, ctx.req
    prompt = req.prompt.strip()
    if not prompt:
        raise RunError("ما في وصف للصورة", "config", False)
    refs = [Path(x) for x in ([req.image] if req.image else []) + list(req.refs or [])]
    caps = m.get("caps") or {}
    if refs and not caps.get("edit") and not caps.get("refs"):
        raise RunError("هالنموذج ما بيقبل صور مرجعية", "unsupported", False)
    params: dict = {"mode": "i2i" if refs else "t2i", "model": cfg["model"], "prompt": prompt, **_size(p)}
    neg = (req.negative or p.get("negative") or "").strip()
    if neg:
        params["negative_prompt"] = neg[:1900]
    steps = cfg.get("steps") or p.get("steps")
    guidance = cfg.get("guidance") if cfg.get("guidance") is not None else p.get("guidance")
    if steps:
        params["steps"] = int(steps)
    if guidance is not None:
        params["guidance"] = float(guidance)
    if p.get("seed") not in (None, ""):
        params["seed"] = int(p["seed"])
    return {"file": _run_job(ctx, sess, base, params, _uploads(refs) if refs else None, "image"), "data": {}}


def _upscale(ctx: Ctx, sess, base: str) -> dict:
    cfg, p, req = ctx.model["weights"], ctx.params, ctx.req
    if not req.image:
        raise RunError("ما في صورة للتكبير", "config", False)
    scale = int(p.get("scale") or 4)
    if not 2 <= scale <= 4:
        raise RunError("تكبير الصندوق ×2 أو ×3 أو ×4 بس", "unsupported", False)
    params = {"mode": "upscale", "model": cfg["model"], "scale": scale}
    return {"file": _run_job(ctx, sess, base, params, _uploads([req.image]), "image"), "data": {}}


def _audio(ctx: Ctx, sess, base: str) -> dict:
    """موسيقى أو مؤثر (t2a). المدة من الطلب؛ سقف الصندوق (AUDIO_MAX_SECONDS، 47 افتراضياً) بيرد 400 بسبب عربي لو تجاوزناه (والاستوديو بيفحص caps.max_sec قبل)."""
    cfg, p, req = ctx.model["weights"], ctx.params, ctx.req
    prompt = req.prompt.strip()
    if not prompt:
        raise RunError("ما في وصف للصوت", "config", False)
    try:
        secs = float(req.seconds or p.get("seconds") or (30.0 if req.task == "music" else 5.0))
    except (TypeError, ValueError):
        raise RunError("المدة لازم رقم بالثواني", "config", False) from None
    params: dict = {"mode": "t2a", "model": cfg["model"], "prompt": prompt, "seconds": round(max(0.5, secs), 2)}
    neg = (req.negative or p.get("negative") or "").strip()
    if neg:
        params["negative_prompt"] = neg[:1900]
    steps = cfg.get("steps") or p.get("steps")
    guidance = cfg.get("guidance") if cfg.get("guidance") is not None else p.get("guidance")
    if steps:
        params["steps"] = int(steps)
    if guidance is not None:
        params["guidance"] = float(guidance)
    if p.get("seed") not in (None, ""):
        params["seed"] = int(p["seed"])
    return {"file": _run_job(ctx, sess, base, params, None, "audio"), "data": {}}


TASKS = {"image": _image, "upscale": _upscale, "music": _audio, "sfx": _audio}


def run(ctx: Ctx) -> dict:
    fn = TASKS.get(ctx.req.task)
    if fn is None:
        raise RunError("ربط الأوزان بيخدم الصور والتكبير والموسيقى والمؤثرات (والتحريك من سجل موديلات التحريك)", "unsupported", False)
    base = box_url()
    if not base:
        raise RunError("صندوق الأوزان مش مربوط — حط عنوانه بمكتبة النماذج (مثال: http://engine:8000)", "config", False)
    sess = session(token())
    try:
        return fn(ctx, sess, base)
    finally:
        sess.close()
