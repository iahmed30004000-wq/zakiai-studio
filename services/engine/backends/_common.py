"""
أدوات مشتركة للخلفيات الحقيقية (ltx / wan). ما بتستورد torch ولا diffusers بالأعلى،
فالملف بينقرأ وبينفحص بدون ما تكون مكتبات الكرت منزّلة.
"""

from __future__ import annotations

import gc
import math
import os
import subprocess
from pathlib import Path

OOM_MESSAGE = "الذاكرة ما كفّت — جرّب مدة أقصر أو دقة أقل"


class Cancelled(Exception):
    """بتتطلع من callback الخطوات لما المالك يلغي المهمة."""


def force_offline() -> None:
    """الصندوق ما بيحمّل أي شي من الإنترنت: الأوزان من مجلد محلي بس."""
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[k] = "1"


def free_memory() -> None:
    """تفريغ الذاكرة: جامع القمامة + كاش الكرت (لو torch موجود)."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


def weights_path(weights_dir: Path, sub: str) -> Path:
    """مسار أوزان نموذج داخل WEIGHTS_DIR. بيتأكد إنه فعلاً جوّا المجلد وموجود."""
    base = Path(weights_dir).resolve()
    p = (base / sub).resolve()
    if base != p and base not in p.parents:
        raise RuntimeError("مسار الأوزان خارج المجلد المسموح")
    if not p.is_dir() or not any(p.iterdir()):
        raise RuntimeError(f"أوزان النموذج مش موجودة بالمجلد: {sub} (راجع README_AR_نشر_السيرفر.md)")
    return p


def fit_resolution(w: int, h: int, max_pixels: int, multiple: int = 32, min_side: int = 256) -> tuple[int, int]:
    """نفس نسبة الأبعاد، بدون ما نتجاوز max_pixels، وكل بُعد من مضاعفات `multiple`."""
    w, h = max(1, int(w)), max(1, int(h))
    scale = min(1.0, math.sqrt(max_pixels / (w * h)))
    nw = max(min_side, int(w * scale) // multiple * multiple)
    nh = max(min_side, int(h * scale) // multiple * multiple)
    # التقريب لتحت ممكن يخلّي المساحة أصغر بشوي؛ التقريب للأعلى بحالة نقص الحد الأدنى بس
    while nw * nh > max_pixels and (nw > min_side or nh > min_side):
        if nw >= nh and nw > min_side:
            nw -= multiple
        elif nh > min_side:
            nh -= multiple
        else:
            break
    return nw, nh


def frame_count(seconds: float, fps: int, step: int) -> int:
    """أقرب عدد إطارات من الشكل step*k+1 بحيث المدة ≥ المطلوب (الحاجة: LTX=8k+1، Wan=4k+1)."""
    need = max(1, math.ceil(seconds * fps))
    k = max(1, math.ceil((need - 1) / step))
    return k * step + 1


def load_image_fitted(path: Path, w: int, h: int):
    """الصورة بنفس نسبة الهدف (قص من النص) بالحجم المطلوب."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return ImageOps.fit(im, (w, h), method=Image.LANCZOS, centering=(0.5, 0.5))


def target_size(params: dict, image: Path | None, max_pixels: int, multiple: int) -> tuple[int, int]:
    if params.get("width") and params.get("height"):
        w, h = int(params["width"]), int(params["height"])
    elif image is not None:
        from PIL import Image
        with Image.open(image) as im:
            w, h = im.size
    else:
        w, h = 9, 16
    return fit_resolution(w, h, max_pixels, multiple)


def encode_mp4(frames, fps: int, out: Path) -> None:
    """إطارات PIL ← mp4 (h264) بـ ffmpeg عبر pipe. بدون ملفات مؤقتة."""
    frames = list(frames)
    if not frames:
        raise RuntimeError("النموذج ما طلّع إطارات")
    w, h = frames[0].size
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(int(fps)), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in frames:
            p.stdin.write(f.convert("RGB").tobytes())
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0:
        raise RuntimeError("ffmpeg فشل بتحويل الإطارات لفيديو: " + err[-200:])
