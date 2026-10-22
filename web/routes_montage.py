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
    import studio_gate
    try:
        return studio_gate.timeline_for(p, "ما في خط زمني")
    except studio_gate.GateError as e:
        raise HTTPException(e.status, str(e))


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


def _sound_job(label: str, cmd: list[str]) -> dict:
    from web import jobs
    return {"job_id": jobs.create_job("sound", label, cmd)}


def _sg(fn, *a, **k):
    import sound_gen
    try:
        return fn(*a, **k)
    except sound_gen.SoundGenError as e:
        raise HTTPException(409, str(e))


@router.post("/ahat/generate")
def generate_ahat(payload: dict) -> dict:
    """يولّد موسيقى أو مؤثر بنموذج مكتبة النماذج (مهمة خلفية). المقطع بينزل غير معتمد وبينتظر سمعك."""
    import sound_gen
    if not isinstance(payload, dict) or set(payload) - {"kind", "prompt", "seconds", "name", "mood", "model"}:
        raise HTTPException(400, "الحقول: kind وprompt وseconds وname وmood وmodel بس")
    c = _sg(sound_gen.check, payload.get("kind"), payload.get("prompt"), payload.get("seconds"), payload.get("name") or "", payload.get("mood") or "any", payload.get("model"))
    _sg(sound_gen.preflight, c["kind"], c["model"], c["seconds"])         # نرفض هلأ لو ما في نموذج جاهز (أو مدتك أطول من أقصاه) بدل ما تفشل المهمة بعدين
    cmd = ["sound_gen.py", "free", "--kind", c["kind"], "--prompt", c["prompt"], "--seconds", str(c["seconds"]), "--name", c["name"], "--mood", c["mood"]]
    if c["model"]:
        cmd += ["--model", c["model"]]
    return _sound_job(f"توليد {sound_gen.LABEL[c['kind']]}: {c['name']}", cmd)


@router.post("/studio/{filename}/sounds/{rid}/generate")
def generate_sound_for_request(filename: str, rid: str, payload: dict | None = None) -> dict:
    """يولّد طلب آهة/موسيقى معلّق بسيناريو بنموذج المكتبة (بدل الإضافة). المقطع بينزل غير معتمد والطلب بيتقفل."""
    import ext_tasks
    import sound_gen
    p = _script(filename)
    model = (payload or {}).get("model") if isinstance(payload, dict) else None
    row = next((r for r in ext_tasks.list_requests(p.stem) if r.get("id") == ext_tasks._norm_id(rid) and r.get("kind") in ext_tasks.REQUEST_KINDS), None)
    if row is None:
        raise HTTPException(404, "الطلب غير موجود")
    if row.get("status") == "local":
        raise HTTPException(409, "هالطلب عم يتولّد بنموذج المكتبة هلأ — استنى يخلص")
    if row.get("status") != "pending":
        raise HTTPException(409, "هالطلب خلص من قبل — اطلب نسخة جديدة إذا بدك")
    if model not in (None, "") and (not isinstance(model, str) or not model.startswith("lib:")):
        raise HTTPException(400, "النموذج: lib:ml_001 (من مكتبة النماذج) أو فاضي للافتراضي")
    _sg(sound_gen.preflight, row["kind"], model or None, row.get("seconds"))
    cmd = ["sound_gen.py", "request", str(p), row["id"]] + (["--model", model] if model else [])
    return _sound_job(f"توليد {sound_gen.LABEL[row['kind']]} لطلب {row['id']}: {p.stem}", cmd)


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


def _free_render(p: Path, mode: str) -> dict:
    """المشروع الحر: free_montage.py (ffmpeg). التصدير النهائي بلا معاينة مسموح، والمتقدّم (Remotion) لسا مش للحر."""
    import free_montage
    from web import jobs
    if mode == "advanced":
        raise HTTPException(409, "المونتاج المتقدّم مش متاح للمشروع الحر لسا — استعمل «التصدير النهائي»")
    if mode not in free_montage.MODES:
        raise HTTPException(400, "الوضع: preview أو final")
    try:
        free_montage.preflight(p)
    except free_montage.FreeMontageError as e:
        raise HTTPException(409, str(e))
    return {"job_id": jobs.create_job("montage", f"{'تصدير' if mode == 'final' else 'معاينة'} المشروع الحر: {p.stem}",
                                      ["free_montage.py", mode, str(p)])}


@router.post("/studio/{filename}/montage/render")
def render_montage(filename: str, mode: str = "preview") -> dict:
    import studio_gate
    import studio_state
    from web import jobs
    p = _script(filename)
    if studio_gate.is_free(p):
        return _free_render(p, mode)
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


def _guided_only(p: Path) -> None:
    """المشروع الحر ما بينطلق للعمليات (طرف الـ OMS لسا ما انبنى، وما إله رقم إعلان VP-): بيخلص بفيديو بتنزّله."""
    import studio_gate
    if studio_gate.is_free(p):
        raise HTTPException(409, {"code": "free_project", "message": "المشروع الحر ما بينطلق للعمليات — نزّل الفيديو"})


@router.get("/studio/{filename}/launch/info")
def launch_info(filename: str) -> dict:
    import launch
    p = _script(filename)
    _guided_only(p)
    _tl(p)
    return launch.info(p)


@router.post("/studio/{filename}/launch")
def launch_send(filename: str, payload: dict) -> dict:
    """سؤال واحد: mode = active|test. طلب واحد، وما بيتكرر لنفس (vp_id, mode)."""
    import launch
    p = _script(filename)
    _guided_only(p)
    _tl(p)
    return _ln(launch.send, p, str(payload.get("mode") or ""), confirm=bool(payload.get("confirm")))


@router.post("/studio/{filename}/launch/refresh")
def launch_refresh(filename: str, payload: dict) -> dict:
    import launch
    p = _script(filename)
    _guided_only(p)
    _tl(p)
    return _ln(launch.refresh, p, str(payload.get("mode") or ""))


@router.post("/studio/{filename}/launch/cancel")
def launch_cancel(filename: str, payload: dict) -> dict:
    import launch
    p = _script(filename)
    _guided_only(p)
    _tl(p)
    return _ln(launch.cancel, p, str(payload.get("mode") or ""))
