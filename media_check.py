"""
فحص ناتج النماذج المربوطة (مكتبة النماذج) قبل ما يدخل المشروع: النوع بالمحتوى مش بالاسم، وسقوف الحجم والمدة والبكسل.

نموذج غلط أو سيرفر معطوب ممكن يرجّع ملف فاضي، صفحة خطأ HTML باسم .png، صوت صامت، أو صورة 40 ميغابكسل —
الفحص بيحوّل كل هاد لرسالة عربية واضحة (MediaCheckError) بدل ما يوصل لمونتاج أو يخرّب ملف المشروع.

  check(path, "image"|"audio"|"video") → info dict
  conform_image / conform_audio → بيطابق صيغة الملف النهائي مع امتداده (png/jpg/webp، mp3/wav)، لأن باقي النظام بيفترض الامتداد صادق.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

KINDS = ("image", "audio", "video")
MAX_BYTES = {"image": 64 * 1024 * 1024, "audio": 200 * 1024 * 1024, "video": 1024 * 1024 * 1024}
MAX_PIXELS = 100_000_000
MIN_SIDE = 64
MIN_AUDIO_SEC = 0.2
IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class MediaCheckError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        raise MediaCheckError("النموذج ما كتب أي ملف") from None


def _probe(path: Path) -> dict:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                           capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise MediaCheckError("ffprobe مش منزّل — ما بقدر أفحص ناتج النموذج") from None
    except subprocess.TimeoutExpired:
        raise MediaCheckError("فحص الملف أخد وقت كتير") from None
    if r.returncode != 0:
        raise MediaCheckError("الناتج مش ملف صوت/فيديو صالح") from None
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        raise MediaCheckError("الناتج مش ملف صوت/فيديو صالح") from None


def check_image(path: Path, *, min_side: int = MIN_SIDE) -> dict:
    from PIL import Image
    n = _size(path)
    if n == 0:
        raise MediaCheckError("النموذج رجّع ملف فاضي")
    if n > MAX_BYTES["image"]:
        raise MediaCheckError(f"الصورة أكبر من {MAX_BYTES['image'] // (1024 * 1024)} ميغا")
    try:
        with Image.open(path) as im:
            fmt, size, mode = im.format, im.size, im.mode
            if fmt not in IMAGE_FORMATS:
                raise MediaCheckError("صيغة الصورة مش مدعومة (بنقبل PNG وJPG وWEBP)")
            if size[0] * size[1] > MAX_PIXELS:
                raise MediaCheckError(f"الصورة ضخمة ({size[0]}×{size[1]}) — أكبر من {MAX_PIXELS // 1_000_000} ميغابكسل")
            im.load()
    except MediaCheckError:
        raise
    except Exception:                                                     # noqa: BLE001 — أي خلل بالقراءة = مش صورة صالحة
        raise MediaCheckError("الناتج مش صورة صالحة (غالباً صفحة خطأ من السيرفر)") from None
    if min(size) < min_side:
        raise MediaCheckError(f"الصورة صغيرة كتير ({size[0]}×{size[1]})")
    alpha = "A" in mode or mode == "P" and "transparency" in getattr(im, "info", {})
    return {"kind": "image", "format": fmt, "width": size[0], "height": size[1], "alpha": bool(alpha), "bytes": n}


def check_audio(path: Path, *, max_sec: float | None = None) -> dict:
    n = _size(path)
    if n == 0:
        raise MediaCheckError("النموذج رجّع ملف فاضي")
    if n > MAX_BYTES["audio"]:
        raise MediaCheckError(f"الصوت أكبر من {MAX_BYTES['audio'] // (1024 * 1024)} ميغا")
    d = _probe(path)
    streams = d.get("streams") or []
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise MediaCheckError("الناتج ما فيه صوت")
    try:
        dur = float((d.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur < MIN_AUDIO_SEC:
        raise MediaCheckError("الصوت قصير كتير أو فاضي")
    if max_sec and dur > max_sec:
        raise MediaCheckError(f"الصوت أطول من الحد ({int(max_sec)} ثانية)")
    return {"kind": "audio", "duration_sec": round(dur, 3), "format": (d.get("format") or {}).get("format_name", ""), "bytes": n}


def check_video(path: Path, *, max_sec: float | None = None) -> dict:
    n = _size(path)
    if n == 0:
        raise MediaCheckError("النموذج رجّع ملف فاضي")
    if n > MAX_BYTES["video"]:
        raise MediaCheckError(f"الفيديو أكبر من {MAX_BYTES['video'] // (1024 * 1024)} ميغا")
    d = _probe(path)
    v = next((s for s in d.get("streams") or [] if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    if not v:
        raise MediaCheckError("الناتج ما فيه فيديو")
    try:
        dur = float((d.get("format") or {}).get("duration") or v.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur <= 0:
        raise MediaCheckError("ما قدرت أعرف مدة الفيديو")
    if max_sec and dur > max_sec:
        raise MediaCheckError(f"الفيديو أطول من الحد ({int(max_sec)} ثانية)")
    return {"kind": "video", "duration_sec": round(dur, 3), "width": int(v.get("width") or 0), "height": int(v.get("height") or 0), "bytes": n}


def check(path, kind: str, **kw) -> dict:
    if kind not in KINDS:
        raise MediaCheckError(f"نوع ناتج غير معروف: {kind}")
    p = Path(path)
    return {"image": check_image, "audio": check_audio, "video": check_video}[kind](p, **kw)


# ── مطابقة الصيغة مع امتداد الملف النهائي ─────────────────────────────────

def conform_image(src: Path, dest: Path, *, keep_alpha: bool = False) -> dict:
    """يكتب صورة src في dest بصيغة امتداد dest (png/jpg/webp). keep_alpha: لازم الشفافية تضل (تفريغ الخلفية) — بيرفض jpg."""
    from PIL import Image
    ext = dest.suffix.lower()
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(ext)
    if not fmt:
        raise MediaCheckError(f"امتداد الصورة النهائية غير مدعوم: {ext}")
    if keep_alpha and fmt == "JPEG":
        raise MediaCheckError("النتيجة لازم تحتفظ بالشفافية — الملف النهائي لازم PNG أو WEBP")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if im.format == fmt and not (fmt == "JPEG" and im.mode not in ("RGB", "L")):
            if src.resolve() != dest.resolve():
                shutil.copyfile(src, dest)
            return {"width": im.size[0], "height": im.size[1]}
        im.load()
        out = im
        if fmt == "JPEG":
            out = im.convert("RGB")
        elif im.mode not in ("RGB", "RGBA", "L", "LA"):
            out = im.convert("RGBA" if "A" in im.mode or "transparency" in im.info else "RGB")
        out.save(dest, fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
        return {"width": im.size[0], "height": im.size[1]}


def _audio_codec(path: Path) -> str:
    for s in _probe(path).get("streams") or []:
        if s.get("codec_type") == "audio":
            return str(s.get("codec_name") or "")
    return ""


def conform_audio(src: Path, dest: Path) -> None:
    """يكتب صوت src في dest بصيغة امتداد dest. mp3 → ترميز mp3 لو مش mp3، wav → PCM 16-bit. غير هيك (m4a/ogg…) بيتحوّل بـ ffmpeg."""
    ext = dest.suffix.lower()
    codec = _audio_codec(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (ext == ".mp3" and codec == "mp3") or (ext == ".wav" and codec.startswith("pcm_")):
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
        return
    args = {".mp3": ["-codec:a", "libmp3lame", "-q:a", "3"], ".wav": ["-codec:a", "pcm_s16le"]}.get(ext)
    if args is None:
        raise MediaCheckError(f"امتداد الصوت النهائي غير مدعوم: {ext}")
    try:
        r = subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vn", *args, str(dest)], capture_output=True, timeout=600)
    except FileNotFoundError:
        raise MediaCheckError("ffmpeg مش منزّل") from None
    except subprocess.TimeoutExpired:
        raise MediaCheckError("تحويل الصوت أخد وقت أكتر من اللازم") from None
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise MediaCheckError("ما قدرت أحوّل الصوت للصيغة المطلوبة")
