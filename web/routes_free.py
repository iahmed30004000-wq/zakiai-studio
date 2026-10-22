"""المشروع الحر: إنشاء (فاضي / نص / Excel) ولوحة المشاهد واللقطات ورفع الوسائط. المنطق كله بـ free_project.py."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


def _actor() -> str:
    import accounts
    return accounts.who("owner")


def _fp(fn, *a, **k):
    """بينفّذ ويحوّل أخطاء المشروع الحر والاستيراد والوسائط لرسائل HTTP عربية."""
    import free_project
    import media_io
    import scene_import
    try:
        return fn(*a, **k)
    except free_project.FreeError as e:
        raise HTTPException(e.status, str(e))
    except scene_import.SceneImportError as e:
        raise HTTPException(400, str(e))
    except media_io.MediaError as e:
        raise HTTPException(e.status, str(e))


def _tmp_dir() -> Path:
    d = Path(config.LIBRARY_DIR) / "uploads" / "free_tmp" / uuid.uuid4().hex
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _read_xlsx(file: UploadFile) -> bytes:
    import scene_import
    data = await file.read(scene_import.MAX_BYTES + 1)
    if len(data) > scene_import.MAX_BYTES:
        raise HTTPException(413, f"الملف أكبر من {scene_import.MAX_BYTES // (1024 * 1024)} ميغا")
    return data


async def _scenes_from(text: str, file: UploadFile | None, split_sentences: bool) -> tuple[list[dict], list[str], str]:
    """(مشاهد، تنبيهات، المصدر blank|text|excel) من نص أو ملف Excel. الاتنين مع بعض = خطأ."""
    import scene_import
    has_file = bool(file is not None and (file.filename or ""))
    has_text = bool((text or "").strip())
    if has_file and has_text:
        raise HTTPException(400, "اختار نص أو ملف Excel، مش الاتنين مع بعض")
    try:
        if has_file:
            res = scene_import.parse_excel(await _read_xlsx(file))
            return res["scenes"], res["warnings"], "excel"
        if has_text:
            res = scene_import.parse_text(text, split_sentences)
            return res["scenes"], res["warnings"], "text"
    except scene_import.SceneImportError as e:
        raise HTTPException(400, str(e))
    return [], [], "blank"


# ── النموذج والإنشاء ────────────────────────────────────────────────────
@router.get("/scenes/template.xlsx")
def scenes_template() -> Response:
    """نموذج Excel للمشاهد: «اقرأني» (شرح + مثال) + «المشاهد» (قوائم منسدلة)."""
    import scene_import
    return Response(scene_import.template(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="zakiai-scenes-template.xlsx"'})


@router.post("/free/projects")
async def create_project(title: str = Form(""), product_file: str = Form(""), text: str = Form(""),
                         split_sentences: bool = Form(False), file: UploadFile | None = File(None)) -> dict:
    """مشروع حر جديد: فاضي، أو من نص، أو من Excel. بيرجّع {file, stem, warnings}."""
    import free_project
    rows, warnings, source = await _scenes_from(text, file, split_sentences)
    made = _fp(free_project.create, title, rows or None, product_file=product_file, source=source, by=_actor())
    return {**made, "warnings": warnings}


# ── اللوحة ──────────────────────────────────────────────────────────────
@router.get("/studio/{filename}/free/board")
def free_board(filename: str) -> dict:
    import free_project
    return _fp(free_project.board, _script(filename))


@router.put("/studio/{filename}/free/structure")
def free_structure(filename: str, payload: dict) -> dict:
    """حفظ بنية كاملة (مشاهد + لقطات + نصوص + مدد). بيرفض rev قديم (409)."""
    import free_project
    return _fp(free_project.apply_structure, _script(filename), payload, _actor())


@router.post("/studio/{filename}/free/import")
async def free_import(filename: str, text: str = Form(""), split_sentences: bool = Form(False), replace: bool = Form(False),
                      file: UploadFile | None = File(None)) -> dict:
    """يضيف مشاهد من نص أو Excel بآخر المشروع (أو يستبدل الكل مع replace)."""
    import free_project
    p = _script(filename)
    rows, warnings, source = await _scenes_from(text, file, split_sentences)
    if not rows:
        raise HTTPException(400, "الصق نص أو اختار ملف Excel")
    board = _fp(free_project.import_scenes, p, rows, replace=replace, by=_actor())
    return {"board": board, "warnings": warnings}


@router.post("/studio/{filename}/free/media")
async def free_media(filename: str, files: list[UploadFile] = File(...)) -> dict:
    """صور وفيديوهات: كل ملف مشهد بلقطة. بيفحص كل ملف بمحتواه (مش باسمه) قبل ما يكتب شي."""
    import free_project
    import media_io
    p = _script(filename)
    tmp = _tmp_dir()
    try:
        batch = []
        for i, up in enumerate(files):
            kind = media_io.kind_of(up.filename)
            if kind not in ("image", "video"):
                raise HTTPException(400, f"«{up.filename or 'ملف'}»: لازم صورة (png, jpg, webp) أو فيديو (mp4, mov, webm)")
            dest = tmp / f"{i:03d}{Path(up.filename or '').suffix.lower()}"
            try:
                await media_io.stream_to(up, dest, media_io.MAX_IMAGE_BYTES if kind == "image" else media_io.MAX_VIDEO_BYTES)
            except media_io.MediaError as e:
                raise HTTPException(e.status, f"«{up.filename or 'ملف'}»: {e}")
            batch.append({"kind": kind, "tmp": dest, "filename": up.filename or ""})
        return await run_in_threadpool(_fp, free_project.add_media, p, batch, _actor())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── الصوت: تسجيلك (تفريغ وقص على المشاهد) وصوت بالذكاء ──────────────────────
def _vu(fn, *a, **k):
    """بينفّذ ويحوّل أخطاء الصوت (والمشروع الحر) لرسائل HTTP عربية."""
    import free_project
    import voice_upload
    try:
        return fn(*a, **k)
    except voice_upload.VoiceUploadError as e:
        raise HTTPException(e.status, str(e))
    except free_project.FreeError as e:
        raise HTTPException(e.status, str(e))


@router.post("/studio/{filename}/free/voice/upload")
async def free_voice_upload(filename: str, file: UploadFile = File(...), fit: bool = Form(True), mode: str = Form("auto"),
                            language: str = Form("")) -> dict:
    """تسجيل صوتك (أو فيديو فيه صوتك): بيتحوّل ويتفرّغ ويتقسّم على المشاهد كمهمة خلفية. بيرجّع {job_id}.
    mode: auto (حسب وضع المشروع) | by_text | by_time | new_scenes. fit: مدة لقطات المشهد = مدة صوته."""
    import free_project
    import media_io
    import voice_upload
    from web import jobs
    p = _script(filename)
    _fp(free_project._need_free, p)
    kind = media_io.kind_of(file.filename)
    if kind not in ("audio", "video"):
        raise HTTPException(400, "لازم ملف صوت (mp3, wav, m4a, ogg…) أو فيديو فيه صوتك")
    if mode not in voice_upload.MODES:
        raise HTTPException(400, "الوضع: auto أو by_text أو by_time أو new_scenes")
    d = voice_upload.src_dir(p.stem)
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
    cmd = ["voice_upload.py", "ingest", str(p), "--audio", str(dest), "--mode", mode]
    if not fit:
        cmd.append("--no-fit")
    if language.strip():
        cmd += ["--language", language.strip()]
    return {"job_id": jobs.create_job("voice", f"تفريغ تسجيلك وتقسيمه: {p.stem}", cmd)}


@router.post("/studio/{filename}/free/voice/realign")
def free_voice_realign(filename: str, payload: dict | None = None) -> dict:
    """إعادة تقسيم التسجيل المحفوظ على المشاهد (بعد تعديل النص مثلاً) بلا تفريغ جديد. بيرجّع {result, board}."""
    import free_project
    import voice_upload
    p = _script(filename)
    pl = payload or {}
    if str(pl.get("mode") or "auto") not in voice_upload.MODES:
        raise HTTPException(400, "الوضع: auto أو by_text أو by_time أو new_scenes")
    res = _vu(voice_upload.realign_free, p, fit=bool(pl.get("fit", True)), mode=str(pl.get("mode") or "auto"), by=_actor(), log=lambda m: None)
    return {"result": res, "board": _fp(free_project.board, p)}


@router.post("/studio/{filename}/free/voice/tts")
def free_voice_tts(filename: str, payload: dict | None = None) -> dict:
    """صوت بالذكاء لمشاهد فيها كلام (بيصرف من مزوّد الصوت) كمهمة خلفية. {only_missing: true, fit: true}. بيرجّع {job_id, scenes}."""
    import tts
    import voice_upload
    from web import jobs
    p = _script(filename)
    pl = payload or {}
    only_missing = bool(pl.get("only_missing", True))
    todo = _vu(voice_upload.tts_todo, p, only_missing)
    if not tts.tts_config({}).get("api_key"):
        raise HTTPException(409, "ما في مفتاح لمزوّد الصوت — حطّه من الإعدادات (المصنع ← الصوت)")
    cmd = ["voice_upload.py", "tts", str(p)]
    if not only_missing:
        cmd.append("--all")
    if not bool(pl.get("fit", True)):
        cmd.append("--no-fit")
    return {"job_id": jobs.create_job("voice", f"صوت بالذكاء للمشروع الحر: {p.stem}", cmd), "scenes": len(todo)}


@router.delete("/studio/{filename}/free/voice")
def free_voice_delete(filename: str, purge: bool = False) -> dict:
    """بيشيل صوت كل المشاهد (المدد بتضل). المصدر بيضل لإعادة التقسيم، إلا لو purge=1. بيرجّع اللوحة."""
    import voice_upload
    return _vu(voice_upload.delete_free, _script(filename), purge=purge, by=_actor())


@router.get("/studio/{filename}/free/voice/{key}")
def free_voice_file(filename: str, key: str):
    """صوت مشهد (WAV) للتشغيل بالواجهة."""
    import free_project
    import timeline
    p = _script(filename)
    _fp(free_project._need_free, p)
    sc = next((s for s in (timeline.load(p.stem) or {}).get("scenes", []) if s.get("key") == key), None)
    rel = ((sc or {}).get("voice") or {}).get("audio")
    lib = Path(config.LIBRARY_DIR).resolve()
    f = (lib / rel).resolve() if rel else None
    if not f or not f.is_file() or lib not in f.parents:
        raise HTTPException(404, "ما في صوت لهالمشهد")
    return FileResponse(f, media_type="audio/wav")


# ── المونتاج والتنزيل (free_montage.py بيشتغل كمهمة خلفية من POST /studio/<f>/montage/render) ──
@router.put("/studio/{filename}/free/montage")
def free_montage_settings(filename: str, payload: dict) -> dict:
    """خيارات المونتاج: الكتابة على الشاشة، الموسيقى (معتمدة بس) مع مستواها، والمؤثرات بثوانيها. بيرجّع اللوحة."""
    import free_montage
    return _fp(free_montage.save_settings, _script(filename), payload)


def _download_name(title: str) -> str:
    """اسم ملف التنزيل من عنوان المشروع (عربي مسموح): بلا فواصل مسارات ولا رموز ممنوعة بويندوز."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(title or "")).strip(" ._")
    return (s[:80] or "video") + ".mp4"


@router.get("/studio/{filename}/free/render/{mode}")
def free_render_file(filename: str, mode: str, download: bool = False):
    """آخر معاينة أو تصدير للمشروع الحر. download=1 بيعطي اسم الملف من عنوان المشروع."""
    import free_montage
    import timeline
    import free_project
    p = _script(filename)
    _fp(free_project._need_free, p)                                  # المهمة الموجّهة إلها مساراتها
    if mode not in free_montage.MODES:
        raise HTTPException(404, "الملف غير موجود")
    rec = ((timeline.load(p.stem) or {}).get("render") or {}).get(mode)
    lib = Path(config.LIBRARY_DIR).resolve()
    f = (lib / rec["file"]).resolve() if rec else None
    if not f or not f.is_file() or lib not in f.parents:
        raise HTTPException(404, "الملف غير موجود")
    name = _download_name(json.loads(p.read_text(encoding="utf-8")).get("title")) if download else None
    return FileResponse(f, media_type="video/mp4", filename=name)
