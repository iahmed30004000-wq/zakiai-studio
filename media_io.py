"""
رفع وسائط (صور / فيديو / صوت) من المالك: فحوص صارمة بمحتوى الملف مش باسمه، نسخ مقطّع بسقف حجم، وأدوات ffmpeg صغيرة.

  · أسماء الملفات اللي بتنرفع ما بتنستعمل كمسارات أبداً — الاسم بتحدّده الاستوديو.
  · الصورة: ≤ 30 ميغا، أقصر ضلع ≥ 256 بكسل، ≤ 60 ميغابكسل، وتدوير EXIF بيتطبّق.
  · الفيديو والصوت: نسخ مقطّع (1 ميغا) لملف مؤقت بسقف (فيديو 400 ميغا، صوت 100 ميغا)، وffprobe لازم يلاقي المجرى المطلوب.
كل الأخطاء MediaError برسالة عربية جاهزة، و status (400 افتراضياً، 413 للحجم).
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 400 * 1024 * 1024
MAX_AUDIO_BYTES = 100 * 1024 * 1024
MIN_SIDE = 256
MAX_PIXELS = 60_000_000
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac", ".webm"}


class MediaError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def kind_of(filename) -> str | None:
    """image | video | audio حسب الامتداد (للتوجيه بس؛ الفحص الفعلي بالمحتوى)."""
    ext = Path(str(filename or "")).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def mb(n: int) -> str:
    return f"{n // (1024 * 1024)} ميغا"


# ── الصور ───────────────────────────────────────────────────────────────
def check_image(data: bytes):
    """بيرجّع صورة PIL (RGB، EXIF مطبّق). MediaError لو مش صورة صالحة أو صغيرة أو ضخمة."""
    from PIL import Image, ImageOps
    if not data:
        raise MediaError("الصورة فاضية")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError(f"الصورة أكبر من {mb(MAX_IMAGE_BYTES)}", 413)
    try:
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        if w * h > MAX_PIXELS:
            raise MediaError(f"الصورة ضخمة ({w}×{h}) — صغّرها لأقل من {MAX_PIXELS // 1_000_000} ميغابكسل")
        im.load()
    except MediaError:
        raise
    except Exception as e:                                            # noqa: BLE001 — أي خلل بالقراءة = مش صورة صالحة
        raise MediaError("الملف مش صورة صالحة (إذا من الآيفون HEIC حوّلها JPG أو PNG أول)") from e
    im = ImageOps.exif_transpose(im).convert("RGB")
    if min(im.size) < MIN_SIDE:
        raise MediaError(f"الصورة صغيرة ({im.size[0]}×{im.size[1]}) — أقصر ضلع لازم {MIN_SIDE} بكسل على الأقل")
    return im


def save_png(im, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "PNG")
    return {"w": im.size[0], "h": im.size[1]}


# ── الرفع المقطّع ───────────────────────────────────────────────────────
async def stream_to(upload, dest: Path, limit: int) -> int:
    """يكتب ملف مرفوع (UploadFile) لـ dest على قطع، وبيوقف ويحذف الجزئي لو تجاوز limit. بيرجّع الحجم."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise MediaError(f"الملف أكبر من {mb(limit)}", 413)
            out.write(chunk)
    if not size:
        dest.unlink(missing_ok=True)
        raise MediaError("الملف فاضي")
    return size


# ── ffprobe / ffmpeg ────────────────────────────────────────────────────
def probe_av(path: Path) -> dict:
    """{duration_sec, has_video, has_audio, width, height}. MediaError لو ffprobe ما قدر يقرأه."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                           capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise MediaError("ffprobe مش منزّل — ما بقدر أفحص الفيديو")
    except subprocess.TimeoutExpired:
        raise MediaError("فحص الملف أخد وقت كتير")
    if r.returncode != 0:
        raise MediaError("الملف مش فيديو أو صوت صالح")
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        raise MediaError("الملف مش فيديو أو صوت صالح")
    streams = d.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float((d.get("format") or {}).get("duration") or (v or a or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"duration_sec": dur, "has_video": v is not None, "has_audio": a is not None,
            "width": int((v or {}).get("width") or 0), "height": int((v or {}).get("height") or 0)}


def check_video(path: Path, max_sec: float = 600.0) -> dict:
    info = probe_av(path)
    if not info["has_video"]:
        raise MediaError("الملف ما فيه فيديو")
    if info["duration_sec"] <= 0:
        raise MediaError("ما قدرت أعرف مدة الفيديو")
    if info["duration_sec"] > max_sec:
        raise MediaError(f"الفيديو أطول من {int(max_sec // 60)} دقايق")
    return info


def poster(video: Path, dest: Path, at_sec: float = 0.0) -> Path:
    """أول كادر من الفيديو كصورة PNG (غلاف اللقطة)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-ss", f"{at_sec:.3f}", "-i", str(video), "-frames:v", "1", str(dest)],
                       capture_output=True, timeout=120)
    if r.returncode != 0 or not dest.exists():
        raise MediaError("ما قدرت أطلّع صورة من الفيديو")
    return dest
