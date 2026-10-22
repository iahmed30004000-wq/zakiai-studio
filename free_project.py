"""
المشروع الحر — مشروع يدوي: مشاهد ولقطات بلا قيد 7 مشاهد ولا 45–50 ث ولا ترتيب محطات.

كل شي بيعيش بنفس ملفات المهمة الموجّهة، بس بعلامة وضع:
  · السيناريو  library/scripts/<stem>.json      _meta.mode == "free"  (مرآة للخط الزمني: هو المصدر الوحيد للحقيقة)
  · الخط الزمني library/timelines/<stem>/timeline.json   mode == "free"
        scenes[]: {n, key c001, start_ms, end_ms, voiceover, visual, emotion, voice?, shots[]}
        shots[]:  {id f001, start_ms, end_ms, type, prompt_ar, image{candidates, chosen, …}, motion?, text, still_motion, trim_in_ms, keep_audio}
  · معرّفات المشهد (key) واللقطة (id) ثابتة مهما تغيّر ترتيبها، فالصور والحركات بتمشي مع لقطتها.

الدوال كلها بتاخد مسار ملف السيناريو (Path) وبترمي FreeError برسالة عربية جاهزة (status: 400/404/409).
المهمة الموجّهة ما بتلمسها هالوحدة أبداً: كل مسار هون بيرفض سيناريو مش حر.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import media_io
import scene_import
import studio_gate
import timeline

DEFAULT_SHOT_MS = 3000
MAX_VOICEOVER = 1000
MAX_VISUAL = 1500
MAX_SHOT_TEXT = 120
MAX_EMOTION = 40
MAX_TITLE = 80
MAX_TRIM_MS = 3_600_000
STILL_MOTIONS = ("zoom_in", "zoom_out", "none")
MAX_IMAGES_PER_BATCH = 50
MAX_VIDEOS_PER_BATCH = 20
_LOCK = threading.RLock()


class FreeError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── المسارات والأسماء ───────────────────────────────────────────────────
def script_path(stem: str) -> Path:
    return Path(config.SCRIPTS_DIR) / f"{stem}.json"


def _slug(title: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", str(title or "").strip(), flags=re.UNICODE)
    return re.sub(r"_+", "_", s).strip("_")[:40] or "project"


def _new_stem(title: str) -> str:
    base = f"free__{datetime.now():%Y%m%d_%H%M}__{_slug(title)}"
    stem, k = base, 2
    while script_path(stem).exists():
        stem, k = f"{base}_{k}", k + 1
    return stem


def _script_id(stem: str) -> str:
    """معرّف فريد لكل مشروع حر (اسم ملف التصدير): FREE-<تاريخ ووقت>-<4 حروف من بصمة الاسم>."""
    import hashlib
    parts = stem.split("__")
    stamp = parts[1].replace("_", "") if len(parts) >= 3 else datetime.now().strftime("%Y%m%d%H%M")
    return f"FREE-{stamp}-{hashlib.sha1(stem.encode('utf-8')).hexdigest()[:4]}"


def _text(v, limit: int, label: str, *, keep_newlines: bool = False) -> str:
    s = str(v or "")
    s = s.strip() if keep_newlines else re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        raise FreeError(f"{label} أطول من {limit} حرف")
    return s


# ── الخط الزمني الحر ────────────────────────────────────────────────────
def new_timeline(script_id: str = "") -> dict:
    return {"schema": timeline.SCHEMA, "mode": "free", "script_id": script_id, "rev": 0, "next_scene": 0, "next_shot": 0,
            "length_ms": 0,
            "voice": {"provider": None, "model": None, "voice_id": None, "character_id": None, "audio": None,
                      "duration_ms": 0, "approved_at": "", "sha256": "", "timing_source": "none", "per_scene": True},
            "words": [], "scenes": [], "ambience": None, "sfx": [], "captions": None,
            "captions_opts": {"voice": True, "shot_text": True}, "checks_approved_by_owner": {}}


def new_shot(tl: dict, dur_ms: int = DEFAULT_SHOT_MS, text: str = "", stype: str = "medium",
             still_motion: str = "zoom_in") -> dict:
    tl["next_shot"] = int(tl.get("next_shot") or 0) + 1
    return {"id": f"f{tl['next_shot']:03d}", "start_ms": 0, "end_ms": int(dur_ms), "word_range": None,
            "type": stype if stype in timeline.SHOT_TYPES else "medium", "prompt_ar": "", "prompt_model": "",
            "refs": {"character_id": None, "product_ref": None},
            "image": {"candidates": [], "chosen": None, "upscaled": False, "path_used": None},
            "product_check": None, "face_check": None, "motion": None,
            "text": text, "still_motion": still_motion if still_motion in STILL_MOTIONS else "zoom_in",
            "trim_in_ms": 0, "keep_audio": False}


def new_scene(tl: dict, voiceover: str = "", visual: str = "", emotion: str = "") -> dict:
    tl["next_scene"] = int(tl.get("next_scene") or 0) + 1
    return {"n": tl["next_scene"], "key": f"c{tl['next_scene']:03d}", "start_ms": 0, "end_ms": 0, "word_range": None,
            "function": None, "emotion": emotion, "voiceover": voiceover, "visual": visual, "voice": None, "shots": []}


def caption_words(tl: dict) -> list[dict]:
    """كلمات الترجمة المطلقة (من صوت كل مشهد لو موجود)، مقصوصة بحدود المشهد."""
    out: list[dict] = []
    for sc in tl.get("scenes") or []:
        v = sc.get("voice") or {}
        for w in v.get("words") or []:
            a = int(sc["start_ms"]) + int(w["start_ms"])
            if a >= sc["end_ms"]:
                continue
            out.append({"i": len(out), "text": w["text"], "start_ms": a,
                        "end_ms": min(int(sc["start_ms"]) + int(w["end_ms"]), sc["end_ms"]), "scene": sc["n"]})
    return out


def retime(tl: dict) -> dict:
    """بيعيد حساب المواقع من مدد اللقطات (مدة اللقطة = end − start كما هي)، وبيرقّم المشاهد 1..N."""
    cursor = 0
    for i, sc in enumerate(tl["scenes"], 1):
        sc["n"] = i
        sc["start_ms"] = cursor
        for sh in sc["shots"]:
            dur = int(sh["end_ms"]) - int(sh["start_ms"])
            sh["start_ms"], sh["end_ms"] = cursor, cursor + dur
            cursor += dur
        sc["end_ms"] = cursor
    tl["length_ms"] = cursor
    tl.setdefault("voice", {})["duration_ms"] = cursor
    tl["words"] = caption_words(tl)
    return tl


def shot_duration(sh: dict) -> int:
    return int(sh["end_ms"]) - int(sh["start_ms"])


# ── السيناريو (مرآة) ────────────────────────────────────────────────────
def _first_sentence(text: str) -> str:
    parts = [p.strip() for p in re.split(r"(?<=[.!؟?!۔])\s+", str(text or "").strip()) if p.strip()]
    return (parts[0] if parts else "")[:160]


def _brief_of(product_file: str) -> dict | None:
    if not product_file:
        return None
    p = Path(config.PRODUCTS_DIR) / Path(product_file).name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def mirror_script(path: Path, tl: dict, *, title: str | None = None, product_file: str | None = None,
                  source: str | None = None, by: str = "") -> dict:
    """بيكتب السيناريو من الخط الزمني: المشاهد والمدد والنصوص. الخط الزمني هو المصدر الوحيد؛ هاد انعكاس للقراءة (فحص الادعاءات، البصمة)."""
    import review_script
    import script_versions
    stem = Path(path).stem
    if Path(path).exists():
        script = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        script = {"title": "", "framework": "", "hook_line": "", "cta_line": "", "pattern_slot_mapping": [], "scenes": [],
                  "_meta": {"mode": "free", "script_id": _script_id(stem), "generated_at": _now(), "status": "draft",
                            "number": None, "product": "", "product_file": "", "created_by": by}}
    meta = script.setdefault("_meta", {})
    meta["mode"] = "free"
    if source:
        meta["source"] = source
    if title is not None:
        script["title"] = title
        meta["display_name"] = f"✎ {title}"
    if product_file is not None:
        brief = _brief_of(product_file)
        meta["product_file"] = Path(product_file).name if product_file else ""
        meta["product"] = (brief or {}).get("product_name") or ""
        meta["product_code"] = (brief or {}).get("product_code") or ""
    scenes = []
    for sc in tl["scenes"]:
        shots = sc.get("shots") or []
        texts = [str(s.get("text") or "").strip() for s in shots if str(s.get("text") or "").strip()]
        vo = str(sc.get("voiceover") or "")
        scenes.append({"scene_number": sc["n"], "duration_sec": round((sc["end_ms"] - sc["start_ms"]) / 1000, 2),
                       "purpose": "", "shot_type": (shots[0].get("type") if shots else "medium") or "medium",
                       "visual": str(sc.get("visual") or ""), "voiceover": vo, "on_screen_text": " / ".join(texts),
                       "emotion": str(sc.get("emotion") or ""), "word_count": review_script.word_count(vo)})
    script["scenes"] = scenes
    script["total_duration_sec"] = round(tl["length_ms"] / 1000, 2)
    script["hook_line"] = next((_first_sentence(s["voiceover"]) for s in scenes if s["voiceover"]), "")
    meta["edited_at"] = datetime.now().isoformat(timespec="seconds")
    meta["content_hash"] = script_versions.content_hash(script)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script


# ── تحميل وحفظ ──────────────────────────────────────────────────────────
def _need_free(path: Path) -> None:
    p = Path(path)
    if not p.exists():
        raise FreeError("السيناريو غير موجود", 404)
    try:
        studio_gate.require_free(p)
    except studio_gate.GateError as e:
        raise FreeError(str(e), e.status)


def _load(path: Path) -> dict:
    _need_free(path)
    tl = timeline.load(Path(path).stem)
    if not tl or not timeline.is_free(tl):
        raise FreeError("ما في خط زمني حر لهالمشروع", 404)
    return tl


def _save(path: Path, tl: dict, *, bump: bool = True, **mirror) -> dict:
    """يحفظ الخط الزمني (بتحقق) ويعكسه بالسيناريو. bump: يزيد rev (تعديلات البنية من الواجهة)."""
    if bump:
        tl["rev"] = int(tl.get("rev") or 0) + 1
    try:
        timeline.save(Path(path).stem, tl)
    except timeline.TimelineError as e:
        raise FreeError(str(e), 409)
    mirror_script(Path(path), tl, **mirror)
    return tl


# ── إنشاء ───────────────────────────────────────────────────────────────
def _scene_from_import(tl: dict, row: dict) -> dict:
    sc = new_scene(tl, _text(row.get("voiceover"), MAX_VOICEOVER, "الكلام"), _text(row.get("visual"), MAX_VISUAL, "وصف الصورة"),
                   _text(row.get("emotion"), MAX_EMOTION, "الإحساس"))
    dur = int(round(float(row.get("duration_sec") or DEFAULT_SHOT_MS / 1000) * 1000))
    dur = min(max(dur, timeline.FREE_MIN_SHOT_MS), timeline.FREE_MAX_SHOT_MS)
    sc["shots"].append(new_shot(tl, dur, _text(row.get("on_screen_text"), MAX_SHOT_TEXT, "نص الشاشة"),
                                row.get("shot_type") or "medium"))
    return sc


def create(title: str = "", scenes: list[dict] | None = None, *, product_file: str = "", source: str = "blank",
           by: str = "") -> dict:
    """مشروع حر جديد: فاضي (مشهد بلقطة وحدة)، أو من مشاهد مستوردة. بيرجّع {file, stem, warnings}."""
    title = _text(title, MAX_TITLE, "العنوان") or "مشروع حر"
    if product_file and _brief_of(product_file) is None:
        raise FreeError("ملف المنتج غير موجود", 404)
    stem = _new_stem(title)
    path = script_path(stem)
    tl = new_timeline(_script_id(stem))
    rows = scenes or [{"voiceover": "", "visual": "", "on_screen_text": "", "duration_sec": DEFAULT_SHOT_MS / 1000}]
    if len(rows) > timeline.FREE_MAX_SCENES:
        raise FreeError(f"{len(rows)} مشهد — الحد {timeline.FREE_MAX_SCENES}")
    with _LOCK:
        for row in rows:
            tl["scenes"].append(_scene_from_import(tl, row))
        retime(tl)
        _save(path, tl, title=title, product_file=product_file, source=source, by=by)
    return {"file": path.name, "stem": stem, "warnings": []}


# ── تعديل البنية (حفظ واحد بكل شي) ───────────────────────────────────────
def _apply_shot(sh: dict, row: dict, label: str) -> None:
    if "duration_ms" in row:
        try:
            dur = int(round(float(row["duration_ms"])))
        except (TypeError, ValueError):
            raise FreeError(f"{label}: المدة مش رقم")
        if dur < timeline.FREE_MIN_SHOT_MS:
            raise FreeError(f"{label}: المدة {dur / 1000:.1f}ث أقصر من الحد ({timeline.FREE_MIN_SHOT_MS / 1000:.1f}ث)")
        if dur > timeline.FREE_MAX_SHOT_MS:
            raise FreeError(f"{label}: المدة {dur / 1000:.0f}ث أطول من الحد ({timeline.FREE_MAX_SHOT_MS // 1000}ث)")
        sh["end_ms"] = int(sh["start_ms"]) + dur
    if "text" in row:
        sh["text"] = _text(row["text"], MAX_SHOT_TEXT, f"{label}: نص الشاشة")
    if "type" in row and row["type"] in timeline.SHOT_TYPES:
        sh["type"] = row["type"]
    if "still_motion" in row:
        if row["still_motion"] not in STILL_MOTIONS:
            raise FreeError(f"{label}: حركة الصورة لازم وحدة من: تقريب، تبعيد، ثابتة")
        sh["still_motion"] = row["still_motion"]
    if "trim_in_ms" in row:
        try:
            t = int(round(float(row["trim_in_ms"] or 0)))
        except (TypeError, ValueError):
            raise FreeError(f"{label}: «يبدأ من» مش رقم")
        sh["trim_in_ms"] = min(max(t, 0), MAX_TRIM_MS)
    if "keep_audio" in row:
        sh["keep_audio"] = bool(row["keep_audio"])


def apply_structure(path: Path, payload: dict, by: str = "") -> dict:
    """يطبّق بنية كاملة: {rev, title?, product_file?, scenes:[{key?, voiceover, visual, emotion?, shots:[{id?, duration_ms, text, …}]}]}.
    key/id موجود = تعديل (وبيحافظ على صور وحركات اللقطة)، بلا key/id = جديد، وغير مذكور = انحذف. بيرفض rev قديم (409)."""
    with _LOCK:
        tl = _load(path)
        if int(payload.get("rev", -1)) != int(tl.get("rev") or 0):
            raise FreeError("في تعديل أحدث من هالنسخة — حدّث الصفحة وعيد التعديل", 409)
        rows = payload.get("scenes")
        if not isinstance(rows, list):
            raise FreeError("لازم قائمة مشاهد")
        if len(rows) > timeline.FREE_MAX_SCENES:
            raise FreeError(f"عدد المشاهد أكتر من الحد ({timeline.FREE_MAX_SCENES})")
        old_scenes = {sc["key"]: sc for sc in tl["scenes"]}
        old_shots = {sh["id"]: sh for sc in tl["scenes"] for sh in sc["shots"]}
        seen_keys: set = set()
        seen_ids: set = set()
        scenes: list[dict] = []
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise FreeError(f"مشهد {i}: شكل غير صحيح")
            key = row.get("key")
            if key:
                if key not in old_scenes:
                    raise FreeError(f"مشهد {i}: معرّف غير معروف")
                if key in seen_keys:
                    raise FreeError(f"مشهد {i}: مكرّر")
                sc = old_scenes[key]
                sc["shots"] = []
            else:
                sc = new_scene(tl)
            seen_keys.add(sc["key"])
            if "voiceover" in row:
                sc["voiceover"] = _text(row["voiceover"], MAX_VOICEOVER, f"مشهد {i}: الكلام")
            if "visual" in row:
                sc["visual"] = _text(row["visual"], MAX_VISUAL, f"مشهد {i}: وصف الصورة")
            if "emotion" in row:
                sc["emotion"] = _text(row["emotion"], MAX_EMOTION, f"مشهد {i}: الإحساس")
            shot_rows = row.get("shots")
            if not isinstance(shot_rows, list) or not shot_rows:
                raise FreeError(f"مشهد {i}: لازم لقطة وحدة على الأقل")
            if len(shot_rows) > timeline.FREE_MAX_SHOTS:
                raise FreeError(f"مشهد {i}: أكتر من {timeline.FREE_MAX_SHOTS} لقطات")
            for j, sr in enumerate(shot_rows, 1):
                if not isinstance(sr, dict):
                    raise FreeError(f"مشهد {i} لقطة {j}: شكل غير صحيح")
                sid = sr.get("id")
                if sid:
                    if sid not in old_shots:
                        raise FreeError(f"مشهد {i} لقطة {j}: معرّف غير معروف")
                    if sid in seen_ids:
                        raise FreeError(f"مشهد {i} لقطة {j}: مكرّرة")
                    sh = old_shots[sid]
                else:
                    sh = new_shot(tl)
                seen_ids.add(sh["id"])
                _apply_shot(sh, sr, f"مشهد {i} لقطة {j}")
                sc["shots"].append(sh)
            scenes.append(sc)
        tl["scenes"] = scenes
        retime(tl)
        mirror: dict = {"by": by}
        if "title" in payload:
            mirror["title"] = _text(payload.get("title"), MAX_TITLE, "العنوان") or "مشروع حر"
        if "product_file" in payload:
            pf = str(payload.get("product_file") or "")
            if pf and _brief_of(pf) is None:
                raise FreeError("ملف المنتج غير موجود", 404)
            mirror["product_file"] = pf
        _save(path, tl, **mirror)
    return board(path)


def import_scenes(path: Path, rows: list[dict], *, replace: bool = False, by: str = "") -> dict:
    """يضيف مشاهد مستوردة (نص أو Excel) بآخر المشروع، أو يستبدل كل المشاهد (replace) — الصور والحركات القديمة بتنحذف من اللوحة بس."""
    with _LOCK:
        tl = _load(path)
        if replace:
            tl["scenes"] = []
        if len(tl["scenes"]) + len(rows) > timeline.FREE_MAX_SCENES:
            raise FreeError(f"المجموع بيتجاوز {timeline.FREE_MAX_SCENES} مشهد — احذف مشاهد أو قسّم المشروع")
        for row in rows:
            tl["scenes"].append(_scene_from_import(tl, row))
        retime(tl)
        _save(path, tl, by=by)
    return board(path)


# ── الوسائط ─────────────────────────────────────────────────────────────
def _is_blank_default(tl: dict) -> bool:
    """مشروع فيه مشهد واحد ما إلو أي شي (من «فاضي»): بيتبدّل لما نضيف وسائط."""
    if len(tl["scenes"]) != 1 or len(tl["scenes"][0]["shots"]) != 1:
        return False
    sc = tl["scenes"][0]
    sh = sc["shots"][0]
    return not (sc.get("voiceover") or sc.get("visual") or sh.get("text") or (sh.get("image") or {}).get("candidates")
                or sh.get("motion") or sc.get("voice"))


def _attach_image(stem: str, tl: dict, sh: dict, im, *, provider: str = "upload", model: str = "owner") -> str:
    """بيحفظ صورة PIL كمرشّح للقطة (بذاكرة tl)، وبيرجّع مسارها النسبي. الاختيار بعدين عبر image_studio.choose."""
    import image_studio
    out = image_studio.img_dir(stem) / f"{sh['id']}_{int(time.time() * 1000)}_up.png"
    info = media_io.save_png(im, out)
    image_studio._image(sh)["candidates"].append({
        "path": image_studio._rel(stem, out), "provider": provider, "model": model, "at": _now(),
        "w": info["w"], "h": info["h"], "refs_used": [], "path_used": "upload"})
    return image_studio._rel(stem, out)


def _attach_video(stem: str, tl: dict, sh: dict, tmp: Path, filename: str, info: dict, *, set_duration: bool,
                  keep_audio: bool = False) -> str:
    """بينقل فيديو مرفوع لمجلد المقاطع كمرشّح حركة مختار. set_duration: مدة اللقطة = طول الفيديو (حد 60ث).
    keep_audio: صوت الفيديو الأصلي بيضل (لما المشهد بلا صوت تعليق) إذا الفيديو فيه صوت."""
    import shutil
    import motion
    ext = Path(filename or "").suffix.lower()
    ext = ext if ext in media_io.VIDEO_EXTS else ".mp4"
    out_dir = motion.clips_dir(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    clip = out_dir / f"{sh['id']}_{int(time.time() * 1000)}_up{ext}"
    shutil.move(str(tmp), str(clip))
    src_sec = float(info.get("duration_sec") or 0)
    if set_duration:
        sh["end_ms"] = int(sh["start_ms"]) + min(max(int(round(src_sec * 1000)), timeline.FREE_MIN_SHOT_MS), timeline.FREE_MAX_SHOT_MS)
    dur = shot_duration(sh)
    rel = motion._rel(stem, clip)
    sh.setdefault("motion_candidates", []).append({
        "clip": rel, "model_id": "upload", "model_name": "رفع يدوي", "path": "upload", "duration_ms": dur, "fit": "upload",
        "source_sec": round(src_sec, 2), "lipsync": False, "took_sec": 0.0, "at": _now()})
    sh["motion"] = {"model_id": "upload", "prompt": "", "duration_ms": dur, "clip": rel, "lipsync": False}
    sh["keep_audio"] = bool(info.get("has_audio")) and bool(keep_audio)
    return rel


def _choose_poster(path: Path, stem: str, sh_id: str, clip_abs: Path) -> None:
    """صورة غلاف الفيديو كمرشّحة ومختارة، عشان اللقطة يكون إلها صورة (للمعاينة وللتحريك بالذكاء)."""
    import image_studio
    from PIL import Image
    png = image_studio.img_dir(stem) / f"{sh_id}_{int(time.time() * 1000)}_poster.png"
    media_io.poster(clip_abs, png)
    with Image.open(png) as im:
        w, h = im.size
    tl = timeline.load(stem)
    _sc, sh = image_studio._shot(tl, sh_id)
    image_studio._image(sh)["candidates"].append({
        "path": image_studio._rel(stem, png), "provider": "upload", "model": "video-poster", "at": _now(),
        "w": w, "h": h, "refs_used": [], "path_used": "upload"})
    timeline.save(stem, tl)
    image_studio.choose(path, sh_id, image_studio._rel(stem, png), path_used="upload")


def add_media(path: Path, files: list[dict], by: str = "") -> dict:
    """ملفات مرفوعة (صور وفيديوهات) ← مشهد بلقطة لكل ملف. files: [{kind: image|video, tmp: Path, filename}] (ملفات مؤقتة جاهزة).
    بيرجّع {board, warnings}. الصورة 3ث تقريب، والفيديو بطوله (حد 60ث)."""
    import image_studio
    import motion
    stem = Path(path).stem
    warnings: list[str] = []
    made: list[tuple[str, str, Path | None]] = []        # (shot_id, kind, clip_abs)
    with _LOCK:
        tl = _load(path)
        if len([f for f in files if f["kind"] == "image"]) > MAX_IMAGES_PER_BATCH:
            raise FreeError(f"أكتر من {MAX_IMAGES_PER_BATCH} صورة بمرة وحدة — ارفعهم على دفعات")
        if len([f for f in files if f["kind"] == "video"]) > MAX_VIDEOS_PER_BATCH:
            raise FreeError(f"أكتر من {MAX_VIDEOS_PER_BATCH} فيديو بمرة وحدة — ارفعهم على دفعات")
        if _is_blank_default(tl):
            tl["scenes"] = []
        if len(tl["scenes"]) + len(files) > timeline.FREE_MAX_SCENES:
            raise FreeError(f"المجموع بيتجاوز {timeline.FREE_MAX_SCENES} مشهد")
        prepared = []
        for f in files:                                  # نفحص الكل قبل ما نكتب شي: ملف واحد خربان ما بيخرّب الدفعة بنصها
            try:
                if f["kind"] == "image":
                    prepared.append((f, media_io.check_image(Path(f["tmp"]).read_bytes()), None))
                else:
                    prepared.append((f, None, media_io.check_video(Path(f["tmp"]))))
            except media_io.MediaError as e:
                raise FreeError(f"«{f.get('filename') or 'ملف'}»: {e}", e.status)
        for f, im, info in prepared:
            sc = new_scene(tl)
            sh = new_shot(tl, DEFAULT_SHOT_MS)
            sc["shots"].append(sh)
            tl["scenes"].append(sc)
            if f["kind"] == "image":
                _attach_image(stem, tl, sh, im)
                made.append((sh["id"], "image", None))
            else:
                rel = _attach_video(stem, tl, sh, Path(f["tmp"]), f.get("filename") or "", info, set_duration=True,
                                    keep_audio=True)
                if info["duration_sec"] * 1000 > timeline.FREE_MAX_SHOT_MS:
                    warnings.append(f"«{f.get('filename') or 'فيديو'}»: أطول من {timeline.FREE_MAX_SHOT_MS // 1000}ث — خدت أول {timeline.FREE_MAX_SHOT_MS // 1000}ث")
                made.append((sh["id"], "video", motion.abs_of(stem, rel)))
        retime(tl)
        _save(path, tl, by=by)
        for sid, kind, clip_abs in made:                 # الاختيار/الغلاف بعد حفظ الخط الزمني (بيعيد قراءته ويحفظه)
            if kind == "image":
                tl2 = timeline.load(stem)
                _sc, sh = image_studio._shot(tl2, sid)
                image_studio.choose(path, sid, sh["image"]["candidates"][-1]["path"], path_used="upload")
            elif clip_abs:
                try:
                    _choose_poster(path, stem, sid, clip_abs)
                except media_io.MediaError as e:
                    warnings.append(f"لقطة {sid}: {e}")
    return {"board": board(path), "warnings": warnings}


def upload_to_shot(path: Path, shot_id: str, tmp: Path, filename: str, by: str = "") -> dict:
    """ملف واحد (صورة أو فيديو) للقطة موجودة. صورة ← مرشّح مختار. فيديو ← حركة مختارة؛ مدة اللقطة بتضل (لو المشهد إله صوت)
    أو بتصير طول الفيديو (لو بلا صوت). بيرجّع {shot, warnings}."""
    import image_studio
    import motion
    stem = Path(path).stem
    kind = media_io.kind_of(filename)
    if kind not in ("image", "video"):
        raise FreeError("الملف لازم صورة (png, jpg, webp) أو فيديو (mp4, mov, webm)")
    warnings: list[str] = []
    with _LOCK:
        tl = _load(path)
        try:
            sc, sh = image_studio._shot(tl, shot_id)
        except image_studio.ImageStudioError as e:
            raise FreeError(str(e), 404)
        try:
            if kind == "image":
                im = media_io.check_image(Path(tmp).read_bytes())
                rel = _attach_image(stem, tl, sh, im)
            else:
                info = media_io.check_video(Path(tmp))
                has_voice = bool((sc.get("voice") or {}).get("duration_ms"))
                rel = _attach_video(stem, tl, sh, Path(tmp), filename, info, set_duration=not has_voice,
                                    keep_audio=not has_voice)
                if not has_voice:
                    retime(tl)
                elif info["duration_sec"] * 1000 < shot_duration(sh) - 200:
                    warnings.append("الفيديو أقصر من اللقطة — بيتجمّد آخر كادر")
        except media_io.MediaError as e:
            raise FreeError(str(e), e.status)
        _save(path, tl, bump=False, by=by)
    if kind == "image":
        image_studio.choose(path, shot_id, rel, path_used="upload")
    else:
        clip_abs = motion.abs_of(stem, rel)
        if clip_abs:
            try:
                _choose_poster(path, stem, shot_id, clip_abs)
            except media_io.MediaError as e:
                warnings.append(str(e))
    tl = timeline.load(stem)
    _sc, sh = image_studio._shot(tl, shot_id)
    return {"shot": sh, "warnings": warnings}


# ── اللوحة (للواجهة) ────────────────────────────────────────────────────
def readiness(tl: dict) -> dict:
    shots = [sh for sc in tl["scenes"] for sh in sc["shots"]]
    no_media = [sh["id"] for sh in shots if not ((sh.get("image") or {}).get("chosen") or (sh.get("motion") or {}).get("clip"))]
    return {"scenes": len(tl["scenes"]), "shots": len(shots), "length_ms": tl.get("length_ms", 0), "no_media": no_media,
            "ready": bool(shots) and not no_media}


def advisory_checks(path: Path) -> list[dict]:
    """تنبيهات (مش منع): ادعاءات ممنوعة، كلام أسرع من الممكن، نص شاشة طويل. [{kind, scene, message}]"""
    import claims
    import review_script
    script = json.loads(Path(path).read_text(encoding="utf-8"))
    notes: list[dict] = []
    found: list[dict] = []
    try:
        brief = review_script.load_brief(script)
        if brief:
            found = claims.scan_script(script, brief)
        else:                                                               # بلا منتج: قواعد الصحة والتجميل معاً (تنبيه بس)
            seen: set = set()
            for sc in script.get("scenes", []):
                for field in ("voiceover", "on_screen_text"):
                    for cat in ("eye_care", "skincare"):
                        for f in claims.try_text(str(sc.get(field) or ""), cat):
                            if (sc.get("scene_number"), f.get("issue")) not in seen:
                                seen.add((sc.get("scene_number"), f.get("issue")))
                                found.append({**f, "scene": sc.get("scene_number")})
    except Exception:                                                       # noqa: BLE001 — التنبيهات تحسين مش شرط
        found = []
    for f in found:
        notes.append({"kind": "claim", "scene": f.get("scene"),
                      "message": f"{f.get('issue', 'ادعاء ممنوع')}" + (f" — «{f['evidence']}»" if f.get("evidence") else "")})
    for sc in script.get("scenes", []):
        dur = float(sc.get("duration_sec") or 0)
        words = review_script.word_count(sc.get("voiceover"))
        n = sc.get("scene_number")
        if dur > 0 and words / dur > review_script.WPS_MAX:
            notes.append({"kind": "pace", "scene": n, "message": f"مشهد {n}: الكلام أسرع من الممكن نطقه ({words / dur:.1f} كلمة/ث) — مدّد المشهد أو اختصر"})
        if review_script.word_count(sc.get("on_screen_text")) > 5:
            notes.append({"kind": "screen_text", "scene": n, "message": f"مشهد {n}: نص الشاشة أطول من 5 كلمات"})
    return notes


def _render_state(path: Path, tl: dict) -> dict:
    """آخر معاينة وتصدير مع علامتي «موجود» و«قديم» (اتغيّر شي بعده)."""
    try:
        import free_montage
        return free_montage.render_state(path, tl)
    except Exception:                                                       # noqa: BLE001 — معلومة مساعدة، ما بتوقف اللوحة
        return tl.get("render") or {}


def _voice_state(path: Path, tl: dict) -> dict:
    """للواجهة: معلومات آخر تسجيل/توليد، وعدد المشاهد اللي إلها صوت، وهل المصدر محفوظ (لإعادة التقسيم بلا تفريغ جديد)."""
    n = sum(1 for sc in tl["scenes"] if (sc.get("voice") or {}).get("audio"))
    try:
        import voice_upload
        d = voice_upload.src_dir(Path(path).stem)
        has_source = (d / "source.wav").is_file() and (d / "asr.json").is_file()
    except Exception:                                                       # noqa: BLE001
        has_source = False
    return {"info": tl.get("voice_info"), "scenes_with_voice": n, "has_source": has_source}


def board(path: Path) -> dict:
    """كل اللي بتحتاجه الواجهة: المشاهد واللقطات بكل حقولها + الجاهزية + التنبيهات + نتيجة التحقق."""
    tl = _load(path)
    script = json.loads(Path(path).read_text(encoding="utf-8"))
    meta = script.get("_meta") or {}
    return {"file": Path(path).name, "title": script.get("title") or "", "product_file": meta.get("product_file") or "",
            "product": meta.get("product") or "", "source": meta.get("source") or "", "rev": int(tl.get("rev") or 0),
            "length_ms": tl.get("length_ms", 0), "scenes": tl["scenes"], "ambience": tl.get("ambience"),
            "sfx": tl.get("sfx") or [], "captions_opts": tl.get("captions_opts") or {}, "render": _render_state(path, tl),
            "voice": _voice_state(path, tl),
            "readiness": readiness(tl), "advisories": advisory_checks(path), "validation": timeline.validate(tl),
            "limits": {"scenes": timeline.FREE_MAX_SCENES, "shots": timeline.FREE_MAX_SHOTS,
                       "min_shot_ms": timeline.FREE_MIN_SHOT_MS, "max_shot_ms": timeline.FREE_MAX_SHOT_MS,
                       "max_total_ms": timeline.FREE_MAX_TOTAL_MS}}
