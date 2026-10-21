"""
build_job(script_path) ← job محايد عن محرّك الرندر (JSON).

بيقرأ (بدون استيراد أي وحدة ثقيلة من المشروع، بس قراءة ملفات JSON):
  · الخط الزمني المعتمد  library/timelines/<stem>/timeline.json
  · مقطع كل لقطة: التحريك المعتمد، أو الصورة الثابتة كبديل مع تحذير
  · صوت المشاهد وتوقيت الكلمات، والآهات المعتمدة بالسمع
  · بيانات المنتج من البريف (اسم/سعر/عرض/ضمان فقط — بلا أي معرّفات أو بيانات شخصية)
كل المسارات بالـ job نسبية لمجلد المكتبة، وأي مسار خارجها = خطأ.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .. import constants as C
from ..errors import JobError
from . import captions as cap
from . import overlays as ov
from . import product as prod
from .paths import resolve_in
from .probe import probe
from .text import scan_job_for_leaks

_AHAT_ID = re.compile(r"ah_\d{3}")
VOICE_PROBE_TOLERANCE_MS = 150


def safe_name(s) -> str:
    """اسم ملف ASCII آمن (نفس قاعدة montage._safe_name) ومنع الاسم الفاضي أو اللي يبدأ بنقطة."""
    n = re.sub(r"[^A-Za-z0-9_.-]", "_", str(s or "")).lstrip(".")
    return n or "video"


def _load_json(p: Path, what: str):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise JobError(f"{what} غير موجود")
    except (json.JSONDecodeError, OSError):
        raise JobError(f"{what} تالف أو مش بصيغة JSON صحيحة")


def _lib_rel(lib: Path, p: Path) -> str:
    return p.resolve().relative_to(lib).as_posix()


def _inside_lib(lib: Path, base: Path, rel) -> Path:
    """بيحلّ `rel` تحت `base` ويتأكد إنه جوّا المكتبة كلها (ValueError لو لأ)."""
    p = resolve_in(base, rel)
    resolve_in(lib, p.relative_to(lib).as_posix())
    return p


def _check_timeline(tl: dict) -> tuple[int, list[tuple[dict, dict]]]:
    """فحص خفيف مستقل: لقطات متصلة من الصفر، مجموعها = مدة الصوت بالضبط. بيرجّع (المدة، [(مشهد، لقطة)])."""
    voice = tl.get("voice") or {}
    total = voice.get("duration_ms")
    if not isinstance(total, int) or total <= 0:
        raise JobError("الخط الزمني بلا مدة صوت صالحة")
    if not tl.get("scenes"):
        raise JobError("الخط الزمني بلا مشاهد")
    if not tl.get("words"):
        raise JobError("الخط الزمني بلا كلمات بتوقيتها")
    shots, cursor = [], 0
    for sc in tl["scenes"]:
        for sh in sc.get("shots") or []:
            a, b = sh.get("start_ms"), sh.get("end_ms")
            if not isinstance(a, int) or not isinstance(b, int) or b <= a:
                raise JobError(f"لقطة {sh.get('id')}: مدة غير صالحة")
            if a != cursor:
                raise JobError(f"لقطة {sh.get('id')}: فجوة أو تداخل مع اللي قبلها")
            cursor = b
            shots.append((sc, sh))
    if not shots:
        raise JobError("الخط الزمني بلا لقطات")
    if cursor != total:
        raise JobError(f"مجموع مدد اللقطات {cursor}ms مش مساوي لمدة الصوت {total}ms")
    return total, shots


def _build_cuts(tl: dict, stem: str, lib: Path, shots: list, warnings: list[str]) -> list[dict]:
    tdir = lib / "timelines" / stem
    cuts = []
    for n, (sc, sh) in enumerate(shots, 1):
        sid = sh["id"]
        a, b = sh["start_ms"], sh["end_ms"]
        dur = b - a
        fa, fb = cap.frame_of(a), cap.frame_of(b)
        if fb <= fa:
            raise JobError(f"لقطة {sid}: أقصر من إطار واحد")
        src = None
        mo = sh.get("motion")
        if mo and mo.get("clip"):
            try:
                p = _inside_lib(lib, tdir, mo["clip"])
            except ValueError as e:
                raise JobError(f"لقطة {sid}: مسار مقطع التحريك مرفوض ({e})")
            if mo.get("duration_ms") != dur:
                warnings.append(f"لقطة {sid}: مدة التحريك ≠ مدة اللقطة — استُعملت الصورة الثابتة")
            elif not p.is_file():
                warnings.append(f"لقطة {sid}: ملف التحريك مش موجود — استُعملت الصورة الثابتة")
            else:
                src = {"kind": "video", "library_path": _lib_rel(lib, p)}
        else:
            warnings.append(f"لقطة {sid}: ما في تحريك معتمد — استُعملت الصورة الثابتة")
        if src is None:
            im = sh.get("image") or {}
            rel = im.get("composite") or im.get("chosen")
            if not rel:
                raise JobError(f"لقطة {sid}: ما في تحريك ولا صورة معتمدة")
            try:
                p = _inside_lib(lib, tdir, rel)
            except ValueError as e:
                raise JobError(f"لقطة {sid}: مسار الصورة مرفوض ({e})")
            if not p.is_file():
                raise JobError(f"لقطة {sid}: ملف الصورة مش موجود")
            src = {"kind": "image", "library_path": _lib_rel(lib, p), "animation": "ken-burns"}
        src["src"] = None                                        # بتتعبّى بعد stage_media
        cuts.append({
            "id": sid, "index": n, "scene": sc.get("n"), "type": sh.get("type"),
            "start_ms": a, "end_ms": b, "duration_ms": dur, "start_frame": fa, "end_frame": fb,
            "source": src,
        })
    return cuts


def _audio(tl: dict, lib: Path, total: int, warnings: list[str]) -> dict:
    rel = (tl.get("voice") or {}).get("audio")
    if not rel:
        raise JobError("ملف الصوت المدموج ناقص")
    try:
        vp = resolve_in(lib, rel)
    except ValueError as e:
        raise JobError(f"مسار الصوت مرفوض ({e})")
    if not vp.is_file():
        raise JobError("ملف الصوت المدموج ناقص")
    info = probe(vp)
    if info and abs(info.get("duration_ms", 0) - total) > VOICE_PROBE_TOLERANCE_MS:
        warnings.append(f"مدة ملف الصوت {info['duration_ms']}ms تختلف عن الخط الزمني {total}ms")

    amb = tl.get("ambience") or {}
    ahat = []
    tid = amb.get("track_id")
    duck_db = float(amb.get("duck_db", C.DUCK_DB)) if amb else C.DUCK_DB
    if tid:
        if not _AHAT_ID.fullmatch(str(tid)):
            raise JobError("معرّف الآهات غير صالح")
        tdir = lib / "ahat" / tid
        t = _load_json(tdir / "track.json", "ملف الآهات")
        if not t.get("approved"):
            raise JobError("الآهات المختارة مش معتمدة بالسمع")
        try:
            ap = _inside_lib(lib, tdir, t.get("audio"))
        except ValueError as e:
            raise JobError(f"مسار الآهات مرفوض ({e})")
        if not ap.is_file():
            raise JobError("ملف الآهات ناقص")
        ahat.append({"id": tid, "library_path": _lib_rel(lib, ap), "src": None, "start_ms": 0, "end_ms": total,
                     "loop": True, "gain_db": duck_db,
                     "fade_in_s": C.AHAT_FADE_IN_S, "fade_out_s": C.AHAT_FADE_OUT_S})
    return {
        "voice": {"library_path": _lib_rel(lib, vp), "src": None, "duration_ms": total, "rate": C.AUDIO_RATE},
        "music": None,                       # المشروع آهات بشرية بس — بلا موسيقى آلية (مثل montage.py)
        "ahat": ahat,
        "duck": {"enabled": bool(ahat), "gain_db": duck_db, "threshold": C.DUCK_THRESHOLD, "ratio": C.DUCK_RATIO,
                 "attack_ms": C.DUCK_ATTACK_MS, "release_ms": C.DUCK_RELEASE_MS},
        "loudnorm": dict(C.LOUDNORM),
    }


def build_job(script_path, library_dir=None, products_dir=None) -> dict:
    sp = Path(script_path)
    stem = sp.stem
    if library_dir is None or products_dir is None:
        import config                                           # الافتراضي من إعدادات المشروع
        library_dir = library_dir if library_dir is not None else config.LIBRARY_DIR
        products_dir = products_dir if products_dir is not None else config.PRODUCTS_DIR
    lib = Path(library_dir).resolve()

    script = _load_json(sp, "ملف السيناريو")
    tl = _load_json(lib / "timelines" / stem / "timeline.json", "الخط الزمني (جهّز المحطة 5 أولاً)")
    total, shots = _check_timeline(tl)
    warnings: list[str] = []

    cuts = _build_cuts(tl, stem, lib, shots, warnings)
    captions = cap.build_captions(tl["words"], total)
    audio = _audio(tl, lib, total, warnings)

    product, notes = prod.extract_product(prod.load_brief(script, Path(products_dir)))
    warnings += notes
    scenes = [{"n": s.get("n"), "start_ms": s["start_ms"], "end_ms": s["end_ms"]} for s in tl["scenes"]]
    overlays, dropped = ov.build_overlays(product, scenes, total)

    sid = safe_name(tl.get("script_id") or (script.get("_meta") or {}).get("script_id") or stem)
    job = {
        "version": C.JOB_VERSION, "kind": C.JOB_KIND,
        "script_id": sid, "stem": safe_name(stem),
        "width": C.WIDTH, "height": C.HEIGHT, "fps": C.FPS,
        "duration_ms": total, "total_frames": cap.frame_of(total),
        "cuts": cuts, "captions": captions, "overlays": overlays, "audio": audio,
        "product": product,
        "style": {
            **C.STYLE, "highlight_word": True,
            "safe_zone": {"bottom": C.SAFE_BOTTOM, "side": C.SAFE_SIDE, "bottom_px": C.SAFE_BOTTOM_PX,
                          "side_px": C.SAFE_SIDE_PX, "rect": ov.safe_rect()},
            "caption": {"anchor": "bottom", "bottom_px": C.SAFE_BOTTOM_PX, "band_h": C.CAPTION_BAND_PX,
                        "max_chars": C.CAPTION_MAX_CHARS},
        },
        "output": {"path": f"library/exports/{sid}.mp4", "library_rel": f"exports/{sid}.mp4",
                   "w": C.WIDTH, "h": C.HEIGHT, "fps": C.FPS},
        "report": {"warnings": warnings, "dropped_overlays": dropped},
    }
    leaks = scan_job_for_leaks(job)
    if leaks:
        raise JobError("المهمة فيها بيانات ممنوعة: " + "؛ ".join(leaks[:3]))
    return copy.deepcopy(job)


def summarize(job: dict) -> str:
    """ملخص عربي بسيط للطباعة."""
    cuts = job["cuts"]
    vid = sum(1 for c in cuts if c["source"]["kind"] == "video")
    kinds = {"product": "بطاقة المنتج والسعر", "offer": "بطاقة العرض", "cta": "شاشة «اطلب هلأ»"}
    shown = "، ".join(kinds[o["type"]] for o in job["overlays"]) or "لا شي"
    n_words = sum(len(c["words"]) for c in job["captions"])
    lines = [
        f"جهّزنا مهمة المونتاج المتقدّم: {job['script_id']}",
        f"- المدة: {job['duration_ms'] / 1000:.3f} ثانية = {job['total_frames']} إطار "
        f"({job['width']}x{job['height']} بـ {job['fps']} إطار)",
        f"- اللقطات: {len(cuts)} ({vid} تحريك + {len(cuts) - vid} صورة ثابتة)",
        f"- الكلمات: {n_words} موزّعة على {len(job['captions'])} سطر ترجمة",
        f"- البطاقات الظاهرة: {shown}",
    ]
    for d in job["report"]["dropped_overlays"]:
        lines.append(f"- بطاقة محذوفة ({kinds[d['type']]}): {d['reason']}")
    ahat = job["audio"]["ahat"]
    lines.append("- الصوت: " + (f"صوت + آهات ({ahat[0]['id']}) بخفض تلقائي" if ahat else "صوت بس، بلا آهات"))
    for w in job["report"]["warnings"]:
        lines.append(f"- تنبيه: {w}")
    lines.append(f"- الملف الناتج لاحقاً: {job['output']['path']}")
    return "\n".join(lines)
