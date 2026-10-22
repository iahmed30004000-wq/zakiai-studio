"""المحطة ٩: سجل موديلات التحريك المحلية + تشغيل التحريك واختياره."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api")


def _m(fn, *a, **k):
    import motion
    try:
        return fn(*a, **k)
    except motion.MotionError as e:
        raise HTTPException(409, str(e))


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


def _tl(p: Path) -> dict:
    import studio_gate
    try:
        return studio_gate.timeline_for(p, "ما في خط زمني")
    except studio_gate.GateError as e:
        raise HTTPException(e.status, str(e))


# ── السجل ───────────────────────────────────────────────────────────────
def _token_set(cfg: dict) -> bool:
    """هل في توكن محفوظ لهالصندوق؟ (بس نعم/لا — القيمة ما بتطلع أبداً)"""
    name = (cfg or {}).get("token_secret")
    if not name:
        return False
    try:
        import secrets_store
        return bool(secrets_store.get_secret(name))
    except Exception:
        return False


@router.get("/motion-models")
def list_models() -> dict:
    import motion
    models = []
    for m in motion.load_models():
        if m.get("kind") == "http" and m.get("http"):
            m = {**m, "http": {**m["http"], "token_set": _token_set(m["http"])}}
        models.append(m)
    return {"models": models, "strengths": motion.STRENGTHS, "vram_gb": motion.available_vram_gb(),
            "placeholders": list(motion.PLACEHOLDERS), "kinds": motion.KINDS, "http_modes": list(motion.HTTP_MODES)}


@router.post("/motion-models")
def add_model(payload: dict) -> dict:
    import motion
    try:
        return motion.upsert_model(payload)
    except motion.MotionError as e:
        raise HTTPException(400, str(e))


@router.put("/motion-models/{model_id}")
def edit_model(model_id: str, payload: dict) -> dict:
    import motion
    try:
        return motion.upsert_model(payload, model_id)
    except motion.MotionError as e:
        raise HTTPException(400, str(e))


@router.delete("/motion-models/{model_id}")
def remove_model(model_id: str) -> dict:
    import motion
    try:
        motion.delete_model(model_id)
    except motion.MotionError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/motion/models/{model_id}/probe")
def probe_model(model_id: str) -> dict:
    """يفحص صندوق نموذج (http): شغّال؟ محمّل؟ في طابور؟ الكرت مشغول؟ ما بيرمي على أخطاء الاتصال — بيرجّع السبب."""
    import motion
    if not any(m["id"] == model_id for m in motion.load_models()):
        raise HTTPException(404, "الموديل غير موجود")
    return _m(motion.probe, model_id)


@router.put("/motion/models/{model_id}/token")
def set_model_token(model_id: str, payload: dict) -> dict:
    """يحفظ توكن الصندوق بمخزن الأسرار (باسم token_secret الخاص بالموديل). القيمة ما بترجع ولا بتنكتب بالسجل."""
    import motion
    import secrets_store
    m = next((x for x in motion.load_models() if x["id"] == model_id), None)
    if not m:
        raise HTTPException(404, "الموديل غير موجود")
    name = (m.get("http") or {}).get("token_secret")
    if m.get("kind") != "http" or not name:
        raise HTTPException(409, "حط «اسم مفتاح التوكن» بإعدادات الصندوق أول واحفظ")
    token = payload.get("token")
    if token is not None and not isinstance(token, str):
        raise HTTPException(400, "التوكن لازم نص")
    try:
        secrets_store.set_secret(name, (token or "").strip())
    except secrets_store.SecretsError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "token_set": _token_set(m["http"])}


# ── سجل الإنتاج ──────────────────────────────────────────────────────────
@router.get("/production-log")
def production_log_list(kind: str | None = None, limit: int = 30) -> dict:
    """آخر محاولات الإنتاج (تحريك/صورة/صوت/…) بنجاحها وفشلها + إحصاء."""
    import production_log
    if kind is not None and kind not in production_log.KINDS:
        raise HTTPException(400, f"نوع غير معروف — المتاح: {', '.join(production_log.KINDS)}")
    if not 1 <= limit <= 500:
        raise HTTPException(400, "limit بين 1 و500")
    return {"items": production_log.recent(limit, kind), "stats": production_log.stats(kind)}


# ── لقطات السيناريو ─────────────────────────────────────────────────────
@router.get("/studio/{filename}/motion/info")
def motion_info(filename: str) -> dict:
    import motion
    p = _script(filename)
    tl = _tl(p)
    models = motion.load_models()
    vram = motion.available_vram_gb()
    shots = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            rk = motion.rank_models(sh, models, vram, bool(sh.get("talking")))
            shots.append({
                "id": sh["id"], "scene": sc["n"], "type": sh["type"], "duration_ms": sh["end_ms"] - sh["start_ms"],
                "motion_desc": sh.get("motion_desc") or motion.default_motion_desc(sh),
                "talking": bool(sh.get("talking")), "motion": sh.get("motion"), "camera_preset": sh.get("camera_preset"),
                "candidates": sh.get("motion_candidates", []), "has_image": bool((sh.get("image") or {}).get("chosen")),
                "ranked": [{"id": r["model"]["id"], "name": r["model"]["name"], "score": r["score"],
                            "matched": r["matched"], "eta_sec": r["eta_sec"], "est_cost_usd": r.get("est_cost_usd"),
                            "face_rate": r.get("face_rate"), "path": motion._path_of(r["model"])} for r in rk["ranked"]],
                "excluded": [{"id": e["model"]["id"], "name": e["model"]["name"], "reason": e["reason"]} for e in rk["excluded"]],
                "needs": rk["needs"]})
    return {"vram_gb": vram, "models": len(models), "shots": shots, "problems": motion.problems(tl),
            "eta_total_sec": sum((s["ranked"][0]["eta_sec"] if s["ranked"] else 0) for s in shots if not s["motion"])}


@router.put("/studio/{filename}/shots/{shot_id}/motion-desc")
def set_desc(filename: str, shot_id: str, payload: dict) -> dict:
    import motion
    p = _script(filename)
    _tl(p)
    return {"shot": _m(motion.set_desc, p, shot_id, str(payload.get("desc") or ""),
                       payload.get("talking") if "talking" in payload else None)}


@router.post("/studio/{filename}/motion/run")
def run_motion(filename: str, shot: str | None = None, model: str | None = None, n: int = 1) -> dict:
    """يشغّل التحريك كمهمة (طابور كرت الشاشة: تقدّم/إيقاف/استئناف من لوحة المهام). بيحتاج تطابق معتمد (محطة ٨)."""
    import studio_state
    from web import jobs
    p = _script(filename)
    _tl(p)
    ok, why = studio_state.can_start(p.stem, 9)
    if not ok:
        raise HTTPException(409, why)
    if not 1 <= n <= 3:
        raise HTTPException(400, "n بين 1 و3")
    cmd = ["motion.py", "run", str(p), "--n", str(n)]
    if shot:
        cmd += ["--shot", shot]
    if model:
        cmd += ["--model", model]
    return {"job_id": jobs.create_job("motion", f"تحريك: {p.stem}" + (f" · {shot}" if shot else ""), cmd)}


@router.post("/studio/{filename}/shots/{shot_id}/motion/choose")
def choose_motion(filename: str, shot_id: str, payload: dict) -> dict:
    import motion
    p = _script(filename)
    _tl(p)
    return {"shot": _m(motion.choose, p, shot_id, str(payload.get("clip") or ""))}


@router.post("/studio/{filename}/motion/approve")
def approve_motion(filename: str) -> dict:
    import motion
    p = _script(filename)
    _tl(p)
    return _m(motion.approve, p)


_FREE_CLIP_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}


@router.get("/studio/{filename}/clip/{name:path}")
def serve_clip(filename: str, name: str):
    import motion
    import studio_gate
    p = _script(filename)
    f = motion.abs_of(p.stem, name)
    ext = f.suffix.lower() if f else ""
    if not f or not (ext == ".mp4" or (ext in _FREE_CLIP_TYPES and studio_gate.is_free(p))):
        raise HTTPException(404, "المقطع غير موجود")
    return FileResponse(f, media_type=_FREE_CLIP_TYPES.get(ext, "video/mp4"))


# ── التحريك بالـ API (fal.ai) ────────────────────────────────────────────
def _settings_write(mutator) -> None:
    import settings_io
    data = settings_io.load()
    mutator(data)
    settings_io.save(data)


@router.get("/motion/api")
def api_overview() -> dict:
    """حالة التحريك بالـ API: هل في مفتاح، السقف، والقوالب الجاهزة مع تقدير سعر لقطة 4 ثواني. المفتاح نفسه ما بيطلع أبداً."""
    import motion
    import motion_api
    presets = []
    for key, p in motion_api.PRESETS.items():
        spec = motion_api.validate_spec(p)
        presets.append({"key": key, "name": p["name"], "endpoint": p["endpoint"], "cost_per_sec": p["cost_per_sec"],
                        "durations": p["durations"], "strengths": p["strengths"], "note": p["note"],
                        "est_cost_4s": motion_api.estimate_cost(spec, 4)})
    return {"provider": "fal", "has_key": motion_api.has_key(), "cap_usd": float(getattr(config, "MOTION_API_CAP_USD", 15.0)),
            "presets": presets, "models": [m["id"] for m in motion.load_models() if m.get("kind") == "api"],
            "price_note": "الأسعار تقديرية من صفحات fal.ai وبتتغيّر — تأكّد منها وعدّلها بسجل الموديلات.",
            "privacy_note": "صورة اللقطة والبرومبت بينبعتوا لـ fal.ai (برّا جهازك). وما بينبعت أي شي تاني."}


@router.put("/motion/api/key")
def api_set_key(payload: dict) -> dict:
    """يحفظ مفتاح fal بمخزن الأسرار. المالك بيكتبه بنفسه بالواجهة (مش بالمحادثة)."""
    import motion_api
    try:
        motion_api.set_key(payload.get("api_key"))
    except motion_api.ApiMotionError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "has_key": motion_api.has_key()}


@router.delete("/motion/api/key")
def api_clear_key() -> dict:
    import motion_api

    def clear(d):
        ((d.get("MOTION_API") or {}).get("fal") or {}).pop("api_key", None)
    _settings_write(clear)
    return {"ok": True, "has_key": motion_api.has_key()}


@router.put("/motion/api/cap")
def api_set_cap(payload: dict) -> dict:
    """سقف إنفاق التحريك بالـ API لكل سيناريو (دولار)."""
    try:
        cap = float(payload.get("cap_usd"))
    except (TypeError, ValueError):
        raise HTTPException(400, "السقف لازم يكون رقم")
    if not 0 <= cap <= 1000:
        raise HTTPException(400, "السقف بين 0 و1000 دولار")
    _settings_write(lambda d: d.__setitem__("MOTION_API_CAP_USD", cap))
    config.MOTION_API_CAP_USD = cap
    return {"ok": True, "cap_usd": cap}


@router.post("/motion/api/preset/{key}")
def api_add_preset(key: str) -> dict:
    """بيضيف نموذج API جاهز (Kling/Hailuo/Grok) لسجل الموديلات. بتقدر تعدّل سعره وإعداداته بعدين."""
    import motion
    import motion_api
    p = motion_api.PRESETS.get(key)
    if not p:
        raise HTTPException(404, "قالب غير معروف")
    if any(m.get("kind") == "api" and (m.get("api") or {}).get("endpoint") == p["endpoint"] for m in motion.load_models()):
        raise HTTPException(409, "هالنموذج مضاف أصلاً")
    try:
        return motion.upsert_model({"name": p["name"], "kind": "api", "strengths": p["strengths"], "max_sec": p["max_sec"],
                                    "api": {k: p[k] for k in ("provider", "endpoint", "input", "durations", "cost_per_sec", "end_image_field") if k in p}})
    except motion.MotionError as e:
        raise HTTPException(400, str(e))


@router.get("/studio/{filename}/motion/estimate")
def motion_estimate(filename: str, model: str | None = None) -> dict:
    """تقدير تكلفة تحريك اللقطات الباقية قبل ما ننفّق (لكل لقطة الموديل الأول بالترتيب أو الموديل المحدّد)."""
    import motion
    p = _script(filename)
    _tl(p)
    return _m(motion.estimate_script, p, model)
