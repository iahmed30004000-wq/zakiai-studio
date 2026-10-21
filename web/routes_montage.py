"""المحطة ١٠: مكتبة الآهات + المونتاج والتصدير."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api")


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


def _tl(p: Path) -> dict:
    import timeline
    import voice_studio
    ok, why = voice_studio.voice_is_approved(p)
    if not ok:
        raise HTTPException(409, why)
    tl = timeline.load(p.stem)
    if not tl:
        raise HTTPException(404, "ما في خط زمني")
    return tl


def _a(fn, *a, **k):
    import ahat
    try:
        return fn(*a, **k)
    except ahat.AhatError as e:
        raise HTTPException(409, str(e))


def _final_engine() -> str:
    """من settings.json مباشرة (مش من config المحمّل بالذاكرة) عشان تغيير المالك يبان فوراً."""
    import settings_io
    return "remotion" if settings_io.load().get("MONTAGE_FINAL_ENGINE") == "remotion" else "ffmpeg"


def _mt(fn, *a, **k):
    import montage
    try:
        return fn(*a, **k)
    except montage.MontageError as e:
        raise HTTPException(409, str(e))


# ── مكتبة الآهات ────────────────────────────────────────────────────────
@router.get("/ahat")
def list_ahat() -> dict:
    import ahat
    return {"tracks": ahat.list_all(), "moods": ahat.MOODS}


@router.post("/ahat")
async def add_ahat(file: UploadFile = File(...), name: str = Form(""), mood: str = Form("any")) -> dict:
    import ahat
    return _a(ahat.add, name, mood, file.filename or "", await file.read())


@router.post("/ahat/{tid}/approve")
def approve_ahat(tid: str, payload: dict) -> dict:
    import ahat
    return _a(ahat.approve, tid, bool(payload.get("heard")))


@router.post("/ahat/{tid}/revoke")
def revoke_ahat(tid: str) -> dict:
    import ahat
    return _a(ahat.revoke, tid)


@router.delete("/ahat/{tid}")
def delete_ahat(tid: str) -> dict:
    import ahat
    _a(ahat.delete, tid)
    return {"ok": True}


@router.get("/ahat/{tid}/audio")
def ahat_audio(tid: str):
    import ahat
    try:
        p = ahat.audio_path(tid)
    except ahat.AhatError as e:
        raise HTTPException(400, str(e))
    if not p:
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(p)


# ── المونتاج ────────────────────────────────────────────────────────────
@router.get("/studio/{filename}/montage/info")
def montage_info(filename: str) -> dict:
    import ahat
    import montage
    p = _script(filename)
    tl = _tl(p)
    sug = ahat.suggest(tl)
    cues = montage.build_cues(tl)
    r = tl.get("render") or {}
    return {"ahat": {**sug, "suggestions": [{**s, "track": s["track"]} for s in sug["suggestions"]]},
            "ambience": tl.get("ambience"), "render": r, "duration_ms": tl["voice"]["duration_ms"],
            "cues": len(cues), "cue_sample": cues[:6], "safe_bottom": montage.SAFE_BOTTOM,
            "sizes": {"preview": list(montage.PREVIEW_SIZE), "final": list(montage.FINAL_SIZE)},
            "can_final": bool(r.get("preview")), "final_engine": _final_engine(),
            "clips_ready": all((s.get("motion") or {}).get("clip") for sc in tl["scenes"] for s in sc["shots"])}


@router.post("/studio/{filename}/ambience")
def set_ambience(filename: str, payload: dict) -> dict:
    import montage
    p = _script(filename)
    _tl(p)
    return {"ambience": _mt(montage.choose_ahat, p, payload.get("track_id") or None, float(payload.get("duck_db", -14)))}


@router.post("/studio/{filename}/montage/render")
def render_montage(filename: str, mode: str = "preview") -> dict:
    import studio_state
    from web import jobs
    p = _script(filename)
    tl = _tl(p)
    if mode not in ("preview", "final", "advanced"):
        raise HTTPException(400, "الوضع: preview أو final أو advanced")
    ok, why = studio_state.can_start(p.stem, 10)
    if not ok:
        raise HTTPException(409, why)
    if mode in ("final", "advanced") and not (tl.get("render") or {}).get("preview"):
        raise HTTPException(409, "لازم معاينة كاملة قبل التصدير النهائي")
    if mode == "advanced":
        return {"job_id": jobs.create_job("montage", f"تصدير متقدّم: {p.stem}", ["montage_advanced.py", str(p)])}
    return {"job_id": jobs.create_job("montage", f"{'تصدير' if mode == 'final' else 'معاينة'}: {p.stem}",
                                      ["montage.py", mode, str(p)])}


@router.get("/montage/advanced/doctor")
def advanced_doctor() -> dict:
    """جاهزية المونتاج المتقدّم (Node/Chrome/حزم Remotion/الخطوط) — بدون رندر."""
    try:
        from services.advanced_montage.renderers import remotion_engine as re_
        re_.ensure_ready()
        return {"ready": True, "message": "جاهز"}
    except Exception as e:  # أخطاء البيئة عربية جاهزة
        return {"ready": False, "message": str(e)[:300]}


@router.get("/studio/{filename}/render/{mode}")
def get_render(filename: str, mode: str):
    p = _script(filename)
    import timeline
    tl = timeline.load(p.stem) or {}
    rec = (tl.get("render") or {}).get(mode)
    f = (Path(config.LIBRARY_DIR) / rec["file"]) if rec else None
    if mode not in ("preview", "final") or not f or not f.exists():
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(f, media_type="video/mp4", filename=f.name if mode == "final" else None)


# ─────────────────── المحطة ١١: الإطلاق ───────────────────
def _ln(fn, *a, **k):
    import launch
    try:
        return fn(*a, **k)
    except launch.LaunchError as e:
        raise HTTPException(e.http if e.http in (403, 404) else 409, {"code": e.code, "message": str(e)})


@router.get("/studio/{filename}/launch/info")
def launch_info(filename: str) -> dict:
    import launch
    p = _script(filename)
    _tl(p)
    return launch.info(p)


@router.post("/studio/{filename}/launch")
def launch_send(filename: str, payload: dict) -> dict:
    """سؤال واحد: mode = active|test. طلب واحد، وما بيتكرر لنفس (vp_id, mode)."""
    import launch
    p = _script(filename)
    _tl(p)
    return _ln(launch.send, p, str(payload.get("mode") or ""), confirm=bool(payload.get("confirm")))


@router.post("/studio/{filename}/launch/refresh")
def launch_refresh(filename: str, payload: dict) -> dict:
    import launch
    p = _script(filename)
    _tl(p)
    return _ln(launch.refresh, p, str(payload.get("mode") or ""))


@router.post("/studio/{filename}/launch/cancel")
def launch_cancel(filename: str, payload: dict) -> dict:
    import launch
    p = _script(filename)
    _tl(p)
    return _ln(launch.cancel, p, str(payload.get("mode") or ""))
