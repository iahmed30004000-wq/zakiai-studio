"""استوديو الإنتاج — المحطتان ٤ و٥ (الصوت والخط الزمني) وحالات المحطات."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api/studio")


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


@router.get("/stations")
def stations() -> list[dict]:
    import studio_state
    return [{"n": n, "key": k, "label": lbl} for n, (k, lbl) in studio_state.STATIONS.items()]


@router.get("/{filename}/state")
def state(filename: str) -> dict:
    import studio_state
    p = _script(filename)
    return {"script": p.name, "stations": studio_state.derive_early(p.stem, p)}


@router.post("/{filename}/voice")
def make_voice(filename: str, provider: str | None = None, model: str | None = None,
               voice: str | None = None) -> dict:
    """يشغّل توليد الصوت + بوابة المدة كمهمة."""
    import review_loop
    from web import jobs
    p = _script(filename)
    ok, why = review_loop.is_cleared(p)
    if not ok:
        raise HTTPException(409, why)
    cmd = ["voice_studio.py", "produce", str(p)]
    for flag, val in (("--provider", provider), ("--model", model), ("--voice", voice)):
        if val:
            cmd += [flag, val]
    return {"job_id": jobs.create_job("voice", f"فويس أوفر (بوابة المدة): {p.stem}", cmd)}


@router.post("/{filename}/voice/upload")
async def upload_voice(filename: str, file: UploadFile = File(...), language: str = Form("")) -> dict:
    """تسجيلك لمحطة الصوت (المهمة الموجّهة): بيتفرّغ وبيتطابق مع نص السيناريو وبيتقص على المشاهد كمهمة خلفية، وبعدها بتسمعه
    وبتعتمده بالزر المعتاد. بنفس شروط الإضافة (مراجعة نظيفة + المحطة 4 مسموح تبدأ). نسخ الهوك بترفض."""
    import ext_tasks
    import media_io
    import studio_gate
    import voice_upload
    from fastapi.concurrency import run_in_threadpool
    from web import jobs
    p = _script(filename)
    if studio_gate.is_free(p):
        raise HTTPException(409, "هاد مشروع حر — ارفع التسجيل من لوحة «الصوت» جواه")
    try:
        ext_tasks._voice_ready(p)
    except ext_tasks.ExtError as e:
        raise HTTPException(409, str(e))
    if ((json.loads(p.read_text(encoding="utf-8")).get("_meta")) or {}).get("hook_of"):
        raise HTTPException(409, "هاي نسخة هوك: صوت المشاهد 2–7 موروث من الفيديو الأساسي — ارفع تسجيلك لنسخة الأساس")
    kind = media_io.kind_of(file.filename)
    if kind not in ("audio", "video"):
        raise HTTPException(400, "لازم ملف صوت (mp3, wav, m4a, ogg…) أو فيديو فيه صوتك")
    d = Path(config.LIBRARY_DIR) / "voice" / p.stem / "upload_src"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"upload{Path(file.filename or '').suffix.lower()}"
    try:
        await media_io.stream_to(file, dest, media_io.MAX_AUDIO_BYTES if kind == "audio" else media_io.MAX_VIDEO_BYTES)
        info = await run_in_threadpool(media_io.probe_av, dest)
    except media_io.MediaError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(e.status, str(e))
    if not info["has_audio"]:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "الملف ما فيه صوت (جرّب ملف تسجيل صوتي أو فيديو فيه صوتك)")
    if info["duration_sec"] > voice_upload.MAX_SOURCE_SEC:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"التسجيل أطول من {int(voice_upload.MAX_SOURCE_SEC // 60)} دقايق — قسّمه")
    cmd = ["voice_upload.py", "ingest-guided", str(p), "--audio", str(dest)]
    if language.strip():
        cmd += ["--language", language.strip()]
    return {"job_id": jobs.create_job("voice", f"تفريغ تسجيلك وتقسيمه على مشاهد السيناريو: {p.stem}", cmd)}


@router.get("/{filename}/voice")
def voice_info(filename: str) -> dict:
    import voice_studio
    p = _script(filename)
    m = voice_studio.load_manifest(p.stem)
    if not m:
        raise HTTPException(404, "ما في صوت مولّد بعد")
    ok, why = voice_studio.voice_is_approved(p)
    return {"manifest": m, "gate": voice_studio.check_duration(m["total_actual_sec"]),
            "approved": ok, "approved_reason": why}


@router.get("/{filename}/voice/audio")
def voice_audio(filename: str):
    import voice_studio
    p = _script(filename)
    m = voice_studio.load_manifest(p.stem)
    rel = ((m or {}).get("combined") or {}).get("path")
    f = Path(config.LIBRARY_DIR) / rel if rel else None
    if not f or not f.exists():
        raise HTTPException(404, "الملف الصوتي المدموج غير موجود")
    return FileResponse(f, media_type="audio/mpeg")


@router.post("/{filename}/voice/approve")
def approve_voice(filename: str) -> dict:
    """اعتماد المالك للصوت (بعد السمع). الرفض برسالة عربية إذا المدة خارج ٤٥–٥٠ أو النص تغيّر."""
    import voice_studio
    p = _script(filename)
    try:
        return voice_studio.approve_voice(p)
    except voice_studio.VoiceGateError as e:
        raise HTTPException(409, str(e))


@router.get("/{filename}/timeline")
def get_timeline(filename: str) -> dict:
    import timeline
    p = _script(filename)
    tl = timeline.load(p.stem)
    if not tl:
        raise HTTPException(404, "ما في خط زمني — اعتمد الصوت أولاً")
    return {"timeline": tl, "validation": timeline.validate(tl)}


@router.put("/{filename}/timeline/boundary")
def move_boundary(filename: str, scene: int, shot: int, to_ms: int) -> dict:
    """بيحرّك حد لقطة (١-based) ويلصقه بأقرب بداية كلمة."""
    import studio_state
    import timeline
    import voice_studio
    p = _script(filename)
    ok, why = voice_studio.voice_is_approved(p)
    if not ok:
        raise HTTPException(409, why)
    tl = timeline.load(p.stem)
    if not tl:
        raise HTTPException(404, "ما في خط زمني")
    try:
        timeline.move_boundary(tl, scene, shot, to_ms)
        res = timeline.save(p.stem, tl)
    except timeline.TimelineError as e:
        raise HTTPException(409, str(e))
    studio_state.set_state(p.stem, 5, "approved", "تعديل حد لقطة")
    return {"timeline": tl, "validation": res}


# ─────────────────── المحطة ٦: برومبتات اللقطات ───────────────────
def _timeline_of(p: Path) -> dict:
    """بوابة الخط الزمني (موجّه: صوت معتمد ثم خط زمني؛ حر: الخط الزمني بس) — studio_gate."""
    import studio_gate
    try:
        return studio_gate.timeline_for(p, "ما في خط زمني — اعتمد الصوت أولاً")
    except studio_gate.GateError as e:
        raise HTTPException(e.status, str(e))


@router.post("/{filename}/shots/build")
def build_shot_prompts(filename: str, refine: bool = False) -> dict:
    """النظام بيكتب برومبت لكل لقطة (قالب قاطع + تحسين اختياري بالموديل). بيستنى معاينة المالك."""
    import brief as brief_mod
    import characters
    import review_script
    import shot_prompts
    import studio_state
    import timeline
    p = _script(filename)
    tl = _timeline_of(p)
    script = json.loads(p.read_text(encoding="utf-8"))
    ok, why = studio_state.can_start(p.stem, 6)
    if not ok:
        raise HTTPException(409, why)
    b = review_script.load_brief(script) or {}
    cur = characters.chosen(p.stem)
    ch = characters.get(cur["character_id"]) if cur else None
    product = b.get("product_name") or (script.get("_meta") or {}).get("product") or ""
    country = b.get("country") or ""
    try:
        shot_prompts.build(tl, script, product, ch, brief_mod.slug_code(b.get("product_code") or product))
        if refine:
            shot_prompts.refine(tl, ch=ch, country=country)
        shot_prompts.english_for(tl, ch, country)         # النسخة الإنجليزية اللي بتروح للموديل (فشلها ما بيوقف شي)
        timeline.save(p.stem, tl)
    except (shot_prompts.ShotPromptError, timeline.TimelineError) as e:
        raise HTTPException(409, str(e))
    studio_state.set_state(p.stem, 6, "awaiting_choice", "بانتظار معاينتك واعتمادك")
    return {"timeline": tl, "problems": shot_prompts.validate(tl)}


@router.put("/{filename}/shots/{shot_id}/prompt")
def edit_shot_prompt(filename: str, shot_id: str, payload: dict) -> dict:
    import shot_prompts
    import studio_state
    import timeline
    p = _script(filename)
    tl = _timeline_of(p)
    try:
        sh = shot_prompts.set_prompt(tl, shot_id, str(payload.get("prompt_ar") or ""))
        timeline.save(p.stem, tl)
    except (shot_prompts.ShotPromptError, timeline.TimelineError) as e:
        raise HTTPException(409, str(e))
    if studio_state.state_of(p.stem, 6) == "approved":
        studio_state.set_state(p.stem, 6, "awaiting_choice", "تعدّل برومبت بعد الاعتماد")
    return {"shot": sh, "problems": shot_prompts.validate(tl)}


@router.post("/{filename}/shots/approve")
def approve_shot_prompts(filename: str) -> dict:
    import shot_prompts
    import studio_state
    p = _script(filename)
    tl = _timeline_of(p)
    problems = shot_prompts.validate(tl)
    if problems:
        raise HTTPException(409, "؛ ".join(x["message"] for x in problems[:4]))
    studio_state.set_state(p.stem, 6, "approved", "اعتمد المالك برومبتات اللقطات")
    return {"approved": True, "shots": sum(len(s["shots"]) for s in tl["scenes"])}


# ─────────────────── المحطتان ٧ و٨: الصور وفحص التطابق ───────────────────
def _img_call(fn, *a, **k):
    import image_studio
    try:
        return fn(*a, **k)
    except image_studio.ImageStudioError as e:
        raise HTTPException(409, str(e))


@router.get("/{filename}/images/info")
def images_info(filename: str) -> dict:
    import brief as brief_mod
    import image_studio
    import product_ref
    import review_script
    import timeline
    p = _script(filename)
    tl = _timeline_of(p)
    script = json.loads(p.read_text(encoding="utf-8"))
    code = image_studio.product_code(script)
    ref = product_ref.load(code) if code else None
    sup = image_studio.refs_supported()
    routed = ([sh["id"] for sc in tl["scenes"] for sh in sc["shots"]
               if not (sh.get("image") or {}).get("candidates") and image_studio.refs_for_shot(p.stem, sh, code)]
              if not sup["supports_refs"] else [])
    return {"budget": image_studio.budget(p.stem), "product_code": code,
            "image_provider": {**sup, "note": image_studio.routed_message(sup) if routed else ""}, "ext_routed": routed,
            "product_ref": ({"missing": product_ref.missing(ref), "can_composite": product_ref.can_composite(code),
                             "label_text": ref["label_text"]} if ref else None),
            "problems": image_studio.image_problems(tl), "match_problems": image_studio.match_problems(tl)}


@router.post("/{filename}/images/generate")
def images_generate(filename: str, shot: str | None = None, n: int | None = None,
                    provider: str | None = None, model: str | None = None) -> dict:
    """يولّد ٢–٣ خيارات لكل لقطة (أو لقطة وحدة) كمهمة. بيحتاج برومبتات معتمدة (محطة ٦)."""
    import studio_gate
    import studio_state
    from web import jobs
    p = _script(filename)
    tl = _timeline_of(p)
    if studio_gate.is_free(p):                          # المشروع الحر: وصف الصورة بيكفي (بلا اعتماد محطة 6)
        shots = [sh for sc in tl["scenes"] for sh in sc["shots"] if shot is None or sh["id"] == shot]
        if not shots:
            raise HTTPException(404, "لقطة غير موجودة")
        missing = [sh["id"] for sh in shots if not (sh.get("prompt_ar") or "").strip()]
        if shot and missing:
            raise HTTPException(409, "اكتب وصف الصورة للقطة أول")
    elif studio_state.state_of(p.stem, 6) != "approved":
        raise HTTPException(409, "اعتمد برومبتات اللقطات (محطة 6) قبل الصور")
    cmd = ["image_studio.py", "gen", str(p)]
    for flag, val in (("--shot", shot), ("--n", n), ("--provider", provider), ("--model", model)):
        if val:
            cmd += [flag, str(val)]
    return {"job_id": jobs.create_job("images", f"صور اللقطات: {p.stem}" + (f" · {shot}" if shot else ""), cmd)}


@router.get("/{filename}/img/{name:path}")
def serve_img(filename: str, name: str):
    import image_studio
    p = _script(filename)
    f = image_studio.abs_of(p.stem, name)
    if not f or f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(404, "الصورة غير موجودة")
    return FileResponse(f)


@router.post("/{filename}/shots/{shot_id}/choose")
def choose_image(filename: str, shot_id: str, payload: dict) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return {"shot": _img_call(image_studio.choose, p, shot_id, str(payload.get("path") or ""))}


@router.post("/{filename}/shots/{shot_id}/upload")
async def upload_shot_media(filename: str, shot_id: str, file: UploadFile = File(...)) -> dict:
    """صورة أو فيديو من عندك للقطة (بدل التوليد). المشروع الحر: بلا شروط. المهمة الموجّهة: الصورة بعد ما تنفتح محطة الصور (7)، والفيديو بعد
    محطة التحريك (9) ومدته بتتظبط على مدة اللقطة (قص، أو مط حتى 15%، وإلا رفض)، وبيتعمل اختيار تلقائي (المحطة بتصير بانتظار اختيارك)."""
    import shutil
    import uuid
    from fastapi.concurrency import run_in_threadpool
    import free_project
    import media_io
    import studio_gate
    p = _script(filename)
    kind = media_io.kind_of(file.filename)
    if kind not in ("image", "video"):
        raise HTTPException(400, "الملف لازم صورة (png, jpg, webp) أو فيديو (mp4, mov, webm)")
    guided = not studio_gate.is_free(p)
    tmp = Path(config.LIBRARY_DIR) / "uploads" / "free_tmp" / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        dest = tmp / f"up{Path(file.filename or '').suffix.lower()}"
        try:
            await media_io.stream_to(file, dest, media_io.MAX_IMAGE_BYTES if kind == "image" else media_io.MAX_VIDEO_BYTES)
            if guided:
                return await run_in_threadpool(_guided_shot_upload, p, shot_id, kind, dest)
            import accounts
            return await run_in_threadpool(free_project.upload_to_shot, p, shot_id, dest, file.filename or "", accounts.who("owner"))
        except media_io.MediaError as e:
            raise HTTPException(e.status, str(e))
        except free_project.FreeError as e:
            raise HTTPException(e.status, str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _guided_shot_upload(p: Path, shot_id: str, kind: str, dest: Path) -> dict:
    """المهمة الموجّهة: صورة ← مرشّح + اختيار؛ فيديو ← مقطع بمدة اللقطة + اختيار. أخطاء المحطات (409) بالعربي."""
    import image_studio
    import media_io
    import motion
    try:
        if kind == "image":
            im = media_io.check_image(dest.read_bytes())
            cand = image_studio.add_upload(p, shot_id, im)
            return {"shot": image_studio.choose(p, shot_id, cand["path"], path_used="upload"), "warnings": []}
        info = media_io.check_video(dest)
        sh = motion.add_upload(p, shot_id, dest)
        warnings = [] if not info["has_audio"] else ["صوت الفيديو ما بيدخل بالمهمة الموجّهة (الصوت من الفويس أوفر)"]
        return {"shot": motion.choose(p, shot_id, sh["motion_candidates"][-1]["clip"]), "warnings": warnings}
    except (image_studio.ImageStudioError, motion.MotionError) as e:
        raise HTTPException(409, str(e))


@router.post("/{filename}/shots/{shot_id}/upscale")
def upscale_shot_image(filename: str, shot_id: str, payload: dict) -> dict:
    """تكبير خيار صورة بالذكاء محلياً (بطيء، بلا رصيد). الجسم: {path}."""
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return {"shot": _img_call(image_studio.upscale_candidate, p, shot_id, str(payload.get("path") or ""))}


@router.post("/{filename}/shots/{shot_id}/composite")
def composite_product(filename: str, shot_id: str, payload: dict | None = None) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    pl = payload or {}
    return {"shot": _img_call(image_studio.composite, p, shot_id, float(pl.get("x", 0.5)), float(pl.get("y", 0.72)))}


@router.delete("/{filename}/shots/{shot_id}/composite")
def remove_composite(filename: str, shot_id: str) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return {"shot": _img_call(image_studio.clear_composite, p, shot_id)}


@router.post("/{filename}/shots/{shot_id}/check")
def check_image(filename: str, shot_id: str) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return {"shot": _img_call(image_studio.check_shot, p, shot_id)}


@router.post("/{filename}/match/check")
def check_all_images(filename: str) -> dict:
    """يفحص كل اللقطات اللي لسا ما انفحصت (الملصق + الوجه) — الواجهة بتناديه لحالها أول ما تفتح محطة فحص التطابق."""
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return _img_call(image_studio.check_all, p)


@router.post("/{filename}/shots/{shot_id}/verdict")
def shot_verdict(filename: str, shot_id: str, payload: dict) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return _img_call(image_studio.set_verdict, p, shot_id, str(payload.get("verdict") or ""),
                     str(payload.get("note") or ""))


@router.post("/{filename}/images/approve")
def approve_images(filename: str) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return _img_call(image_studio.approve_images, p)


@router.post("/{filename}/match/approve")
def approve_match(filename: str) -> dict:
    import image_studio
    p = _script(filename)
    _timeline_of(p)
    return _img_call(image_studio.approve_match, p)
