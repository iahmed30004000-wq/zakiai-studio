"""مكتبة النماذج: «زي كونفي» بلا تعقيده — لكل مهمة نموذج بتربطه وبتجرّبه وبتخلّيه الافتراضي. المنطق بـ model_library / model_run / model_tasks.

كل التوكنات بمخزن الأسرار (modellib.<id>.token): ما بتنكتب بملف المكتبة وما بترجع بأي رد (بس «محفوظ؟ نعم/لا»).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api/model-library")

MEDIA_TYPES = {".png": "image/png", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}
UPLOAD_KINDS = {"image": "image", "audio": "audio", "video": "video"}


def _actor() -> str:
    import accounts
    return accounts.who("المالك")


def _status(msg: str) -> int:
    return 404 if "مش موجود" in msg and "النموذج" in msg[:20] else 400


def _guard(fn, *a, **k):
    """أخطاء المكتبة والتجربة والأسرار ← رسائل HTTP عربية."""
    import model_library
    import model_tasks
    import secrets_store
    try:
        return fn(*a, **k)
    except model_library.ModelLibraryError as e:
        raise HTTPException(_status(str(e)), str(e))
    except model_tasks.TryError as e:
        raise HTTPException(_status(str(e)), str(e))
    except secrets_store.SecretsError as e:
        raise HTTPException(409, str(e))


# ── الصورة العامة ────────────────────────────────────────────────────────
def _builtin(task: str) -> dict:
    """«الطريقة الحالية» لكل مهمة (اللي بتشتغل لو ما في نموذج افتراضي بالمكتبة): {label, ok}. أي خلل بقراءتها = «—»."""
    try:
        if task == "image":
            import imagegen
            c = imagegen.image_config()
            return {"label": f"{imagegen.IMAGE_PRESETS.get(c['provider'], {}).get('label', c['provider'])} · {c['model']}", "ok": bool(c["api_key"])}
        if task == "voice":
            import tts
            c = tts.tts_config(library=False)
            return {"label": f"{tts.TTS_PRESETS.get(c['provider'], {}).get('label', c['provider'])} · {c['model']}", "ok": bool(c["api_key"])}
        if task == "stt":
            import stt
            c = stt.stt_config()
            return {"label": f"{stt.STT_PRESETS.get(c['provider'], {}).get('label', c['provider'])} · {c['model']}", "ok": bool(c["api_key"]) or c["kind"] == "local"}
        if task == "upscale":
            import upscale
            return {"label": "Real-ESRGAN (محلي)", "ok": upscale.WEIGHTS.exists()}
        if task == "bgremove":
            import bgremove
            return {"label": "BiRefNet (محلي)", "ok": (bgremove.MODEL_DIR / "model.safetensors").exists()}
        if task == "lipsync":
            return {"label": "أمر المزامنة بموديل التحريك المختار", "ok": None}
        if task in ("music", "sfx"):
            return {"label": "الإضافة (طلبات الآهات والموسيقى)", "ok": None}
        if task == "motion":
            return {"label": "سجل موديلات التحريك", "ok": None}
    except Exception:                                                 # noqa: BLE001 — الصفحة ما بتوقع لأن إعداد تالف
        pass
    return {"label": "—", "ok": None}


def _task_stats() -> dict:
    """{model_id: {attempts, ok, failed, avg_seconds}} من سجل الإنتاج."""
    try:
        import production_log
        return {r["model_id"]: {"attempts": r["attempts"], "ok": r["ok"] or 0, "failed": r["failed"] or 0, "avg_seconds": r["avg_seconds"]}
                for r in production_log.stats()["by_model"] if r.get("model_id")}
    except Exception:                                                 # noqa: BLE001
        return {}


def _motion_models() -> list[dict]:
    try:
        import motion
        return [{"id": m["id"], "name": m["name"], "kind": m.get("kind", "command"), "enabled": m.get("enabled", True) is not False,
                 "max_sec": m.get("max_sec"), "vram_gb": m.get("vram_gb"), "lipsync": bool(m.get("lipsync")),
                 "box_model": (m.get("http") or {}).get("model") if m.get("kind") == "http" else None} for m in motion.load_models()]
    except Exception:                                                 # noqa: BLE001
        return []


def _gpu() -> dict:
    out = {"vram_gb": None, "busy": None, "lock_enabled": False}
    try:
        import gpu_lease
        out["lock_enabled"], out["busy"] = gpu_lease.enabled(), gpu_lease.busy()
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        import motion
        out["vram_gb"] = motion.available_vram_gb()
    except Exception:                                                 # noqa: BLE001
        pass
    try:                                                              # صندوق الأوزان مربوط وردّ: كرته (الكلي والحر) — الأرقام اللي بتهم السيرفر
        import link_engine
        info = link_engine.gpu_info()
        if info:
            out["box_gpu"] = info
    except Exception:                                                 # noqa: BLE001
        pass
    return out


def overview() -> dict:
    import model_library as ml
    problem = None
    try:
        doc = ml.load()
    except ml.ModelLibraryError as e:
        doc, problem = ml._blank(), str(e)                           # ملف تالف: الصفحة بتنفتح فاضية مع السبب (ما بنكتب فوقه)
    stats = _task_stats()
    tasks = []
    for t in ml.TASKS:
        cfg = doc["tasks"][t]
        if t == "motion":
            models = _motion_models()
        else:
            models = []
            for m in doc["models"]:
                if m["task"] == t:
                    pub = ml.public(m)
                    pub["stats"] = stats.get(m["id"])
                    models.append(pub)
        tasks.append({"task": t, "label": ml.TASK_LABELS[t], "default": cfg["default"], "fallback_builtin": cfg["fallback_builtin"],
                      "can_fallback": t not in ml.NO_FALLBACK, "builtin": _builtin(t), "models": models})
    return {"tasks": tasks, "box": doc["box"], "problem": problem, "gpu": _gpu(),
            "links": [{"id": l, "label": ml.LINK_LABELS[l], "open": l in ml.OPEN_LINKS, "tasks": list(ml.LINK_TASKS[l])} for l in ml.LINKS],
            "path": str(ml.path())}


@router.get("")
def get_overview() -> dict:
    return overview()


@router.get("/templates")
def get_templates() -> dict:
    import model_library as ml
    items = []
    for t in _guard(ml.templates):
        item = {**t, "open": t["link"] in ml.OPEN_LINKS and t["task"] in ml.LIBRARY_TASKS, "task_label": ml.TASK_LABELS[t["task"]],
                "link_label": ml.LINK_LABELS[t["link"]], "commercial_label": ml.COMMERCIAL_LABELS[t["licence"]["commercial"]]}
        if t["task"] == "motion" and t["link"] == "weights":
            item["registry"] = "motion"                                    # التحريك بسجله الخاص: بيتضاف من بطاقة التحريك مش من المعالج
        items.append(item)
    return {"templates": items}


@router.get("/choices")
def get_choices(task: str) -> dict:
    """نماذج المكتبة الصالحة لمهمة (لقوائم الاختيار بمحطات الإنتاج): الافتراضي أول."""
    import model_library as ml
    if task not in ml.LIBRARY_TASKS:
        raise HTTPException(400, "مهمة غير معروفة")
    doc = _guard(ml.load)
    default = doc["tasks"][task]["default"]
    out = []
    for m in doc["models"]:
        if m["task"] != task:
            continue
        ok, why = ml.usable(m)
        out.append({"id": m["id"], "name": m["name"], "usable": ok, "reason": why, "voice": (m.get("params") or {}).get("voice", ""),
                    "refs": bool((m.get("caps") or {}).get("refs") or (m.get("caps") or {}).get("edit"))})
    return {"task": task, "default": default, "models": out}


# ── النماذج ──────────────────────────────────────────────────────────────
def _split_token(payload: dict) -> tuple[dict, str | None]:
    if not isinstance(payload, dict):
        raise HTTPException(400, "جسم الطلب لازم كائن")
    body = dict(payload)
    token = body.pop("token", None)
    if token is not None and not isinstance(token, str):
        raise HTTPException(400, "التوكن لازم نص")
    return body, token


def _apply_token(model_id: str, token: str | None) -> dict:
    """يحفظ/يمسح توكن نموذج std بمخزن الأسرار باسمه الثابت، ويربط اسمه بإعدادات النموذج."""
    import model_library as ml
    import secrets_store
    m = ml.get(model_id)
    if not m or m["link"] != "std":
        raise HTTPException(409, "التوكن بس لنموذج «سيرفر بواجهة OpenAI»")
    name = ml.token_secret_name(model_id)
    secrets_store.set_secret(name, (token or "").strip())
    std_cfg = {**m["std"], "token_secret": name if (token or "").strip() else None}
    return ml.update(model_id, {"std": std_cfg})


@router.post("/models")
def create_model(payload: dict) -> dict:
    import model_library as ml
    body, token = _split_token(payload)
    m = _guard(ml.create, body, by=_actor())
    if token and token.strip():
        try:
            m = _guard(_apply_token, m["id"], token)
        except HTTPException:
            ml.delete(m["id"])                                         # ما نخلّي نموذج نصف مضبوط (مفتاحه ما انحفظ)
            raise
    return {"model": ml.public(m)}


@router.put("/models/{model_id}")
def edit_model(model_id: str, payload: dict) -> dict:
    import model_library as ml
    body, token = _split_token(payload)
    if body:
        m = _guard(ml.update, model_id, body, by=_actor())
    else:
        m = _guard(ml.get, model_id)
        if not m:
            raise HTTPException(404, "النموذج مش موجود")
    if token is not None:
        m = _guard(_apply_token, model_id, token)
    return {"model": ml.public(m)}


@router.delete("/models/{model_id}")
def delete_model(model_id: str) -> dict:
    import model_library as ml
    import model_tasks
    if not _guard(ml.delete, model_id):
        raise HTTPException(404, "النموذج مش موجود")
    try:
        model_tasks.clear(model_id)
    except Exception:                                                 # noqa: BLE001 — تنظيف التجارب مش شرط
        pass
    return {"ok": True}


@router.put("/tasks/{task}/default")
def set_default(task: str, payload: dict) -> dict:
    import model_library as ml
    if not isinstance(payload, dict) or set(payload) - {"model_id", "fallback_builtin"}:
        raise HTTPException(400, "الحقول: model_id و fallback_builtin بس")
    kw = {"fallback_builtin": payload["fallback_builtin"]} if "fallback_builtin" in payload else {}
    return {"task": task, **_guard(ml.set_default, task, payload.get("model_id") or None, **kw)}


@router.get("/box")
async def get_box(refresh: bool = False) -> dict:
    """حالة صندوق الأوزان: شغّال؟ وشو نماذجه (اسم، أنماط، حجم، رخصة من README، صالح أو مرفوض وليش)؟ وذاكرة الكرت. ما بيرمي — بيرجّع السبب."""
    import link_engine
    import model_library as ml
    box = _guard(ml.load)["box"]
    st = await run_in_threadpool(link_engine.status, None, None, refresh=refresh)
    return {**st, "configured": bool(box["url"]), "box": box, "token_set": bool(link_engine.token())}


@router.put("/box")
def set_box(payload: dict) -> dict:
    """صندوق الأوزان: العنوان (قائمة السماح) والتوكن (بمخزن الأسرار باسم modellib.box.token)."""
    import model_library as ml
    import secrets_store
    if not isinstance(payload, dict) or set(payload) - {"url", "token"}:
        raise HTTPException(400, "الحقول: url و token بس")
    token = payload.get("token")
    if token is not None and not isinstance(token, str):
        raise HTTPException(400, "التوكن لازم نص")
    name = "modellib.box.token"
    cur = _guard(ml.load)["box"]
    secret = cur.get("token_secret") if token is None else (name if token.strip() else None)      # بلا token بالطلب: بنضل على اللي كان
    box = _guard(ml.set_box, payload.get("url"), secret)
    if token is not None:
        _guard(secrets_store.set_secret, name, token.strip())
    try:
        import link_engine
        link_engine.clear_cache()                                          # عنوان/توكن جديد: ذاكرة الكرت المخزّنة بتنسى
    except Exception:                                                      # noqa: BLE001
        pass
    return {"box": box, "token_set": _guard(lambda: bool(secrets_store.get_secret(name)))}


# ── فحص برنامج Gradio (قبل الحفظ): نقاطه ومعاملاتها واقتراح الربط للمهمة ──────
@router.get("/app/inspect")
async def inspect_app(url: str, task: str | None = None) -> dict:
    """يقرا برنامج Gradio (أو أحدث من 4): نقاطه، معاملات كل نقطة وأنواعها، وبصمة شكلها، ومقترح ربط لمهمة. ما بيرمي — بيرجّع السبب."""
    import link_app
    import model_library as ml
    if task is not None and task not in ml.LIBRARY_TASKS:
        raise HTTPException(400, "مهمة غير معروفة")
    return await run_in_threadpool(link_app.inspect, url, task)


# ── فحص سيرفر قياسي (قبل الحفظ) ──────────────────────────────────────────
@router.post("/probe")
async def probe(payload: dict) -> dict:
    """GET /models على السيرفر: شغّال؟ وشو موديلاته؟ بيجرّب بالتوكن اللي بالطلب، أو توكن نموذج محفوظ (model_id). ما بيرمي — بيرجّع السبب."""
    import link_std
    import model_library as ml
    import secrets_store
    if not isinstance(payload, dict):
        raise HTTPException(400, "جسم الطلب لازم كائن")
    token = payload.get("token")
    if (token is None or token == "") and payload.get("model_id"):
        m = ml.get(str(payload["model_id"]))
        name = ((m or {}).get("std") or {}).get("token_secret")
        try:
            token = secrets_store.get_secret(name) if name else None
        except secrets_store.SecretsError:
            token = None
    if token is not None and not isinstance(token, str):
        raise HTTPException(400, "التوكن لازم نص")
    return await run_in_threadpool(link_std.probe, str(payload.get("url") or ""), (token or "").strip() or None)


# ── «جرّب» ───────────────────────────────────────────────────────────────
@router.post("/models/{model_id}/test/inputs")
async def upload_test_input(model_id: str, name: str = Form(...), file: UploadFile = File(...)) -> dict:
    """ملف للتجربة (صورة/تسجيل/فيديو) بنفس سقوف وفحوص الرفع بالمشروع الحر. الاسم بتحدّده الاستوديو."""
    import media_io
    import model_library as ml
    import model_tasks
    if not ml.get(model_id):
        raise HTTPException(404, "النموذج مش موجود")
    if name not in UPLOAD_KINDS:
        raise HTTPException(400, "نوع الملف: image أو audio أو video")
    d = model_tasks.test_dir(model_id) / "in"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{name}.*"):
        old.unlink(missing_ok=True)
    try:
        if name == "image":
            raw = await file.read(media_io.MAX_IMAGE_BYTES + 1)
            im = await run_in_threadpool(media_io.check_image, raw)
            await run_in_threadpool(media_io.save_png, im, d / "image.png")
        else:
            ext = Path(file.filename or "").suffix.lower()
            if media_io.kind_of(f"x{ext}") not in ("audio", "video"):
                raise media_io.MediaError("امتداد الملف غير مدعوم")
            dest = d / f"{name}{ext}"
            await media_io.stream_to(file, dest, media_io.MAX_AUDIO_BYTES if name == "audio" else media_io.MAX_VIDEO_BYTES)
            info = await run_in_threadpool(media_io.probe_av, dest)
            if (name == "audio" and not info["has_audio"]) or (name == "video" and not info["has_video"]):
                dest.unlink(missing_ok=True)
                raise media_io.MediaError("الملف ما فيه " + ("صوت" if name == "audio" else "فيديو"))
            if info["duration_sec"] > 600:
                dest.unlink(missing_ok=True)
                raise media_io.MediaError("الملف أطول من 10 دقايق — قصّه للتجربة")
    except media_io.MediaError as e:
        raise HTTPException(e.status, str(e))
    return {"ok": True, "name": name}


@router.post("/models/{model_id}/try")
def try_model(model_id: str, payload: dict | None = None) -> dict:
    """يشغّل «جرّب» كمهمة خلفية (الصور والصوت ممكن ياخدوا دقايق). النتيجة بـ GET …/test. بيشتغل حتى لو النموذج لسا معطّل."""
    import model_library as ml
    import model_tasks
    from web import jobs
    m = _guard(lambda: ml.get(model_id))
    if not m:
        raise HTTPException(404, "النموذج مش موجود")
    ok, why = ml.licence_gate(m)
    if not ok:
        raise HTTPException(409, f"«{m['name']}»: {why}")
    _guard(model_tasks.save_params, model_id, payload or {})
    return {"job_id": jobs.create_job("model", f"جرّب نموذج «{m['name']}» ({ml.TASK_LABELS[m['task']]})", ["model_tasks.py", "try", model_id])}


@router.get("/models/{model_id}/test")
def get_test(model_id: str) -> dict:
    import model_tasks
    last = _guard(lambda: model_tasks.last_result(model_id))
    return {"last": last, "has_file": bool(last and model_tasks.result_file(model_id))}


@router.get("/models/{model_id}/test/file")
def get_test_file(model_id: str):
    import model_tasks
    f = _guard(lambda: model_tasks.result_file(model_id))
    if not f:
        raise HTTPException(404, "ما في ناتج تجربة")
    return FileResponse(f, media_type=MEDIA_TYPES.get(f.suffix.lower(), "application/octet-stream"), headers={"Cache-Control": "no-store"})
