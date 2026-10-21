"""فحص الفيديو الناتج بـ ffprobe مقابل الـ job. بيرجّع قائمة أخطاء بالعربي البسيط (فاضية = تمام)."""

from __future__ import annotations

from pathlib import Path

from .. import constants as C
from .probe import probe


def verify_output(mp4, job: dict, *, min_bytes: int = C.MIN_FILE_BYTES,
                  tolerance_ms: int = C.DURATION_TOLERANCE_MS) -> list[str]:
    p = Path(mp4)
    if not p.is_file():
        return ["ملف الفيديو مش موجود"]
    info = probe(p)
    if not info or not info.get("has_video"):
        return ["الملف مش فيديو صالح (أو ffprobe مش مثبّت)"]
    out = job.get("output") or {}
    w, h, fps = out.get("w", C.WIDTH), out.get("h", C.HEIGHT), out.get("fps", C.FPS)
    errors: list[str] = []
    if (info["width"], info["height"]) != (w, h):
        errors.append(f"حجم الفيديو {info['width']}x{info['height']} والمطلوب {w}x{h}")
    if abs(info["fps"] - fps) > 0.05:
        errors.append(f"عدد الإطارات بالثانية {info['fps']:.2f} والمطلوب {fps}")
    want = job.get("duration_ms")
    got = info.get("video_duration_ms") or 0
    if isinstance(want, int) and abs(got - want) > tolerance_ms:
        errors.append(f"مدة الفيديو {got} ملي ثانية والمطلوب {want} (الفرق المسموح {tolerance_ms})")
    if not info.get("has_audio"):
        errors.append("الفيديو بلا مسار صوت")
    if info["size_bytes"] <= min_bytes:
        errors.append(f"حجم الملف {info['size_bytes']} بايت — صغير كتير (الأدنى {min_bytes}) غالباً الرندر ما كمل")
    return errors
