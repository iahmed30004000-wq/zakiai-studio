"""
تكبير الصور بالصندوق: ملفات مجلد upscale/ (Real-ESRGAN وأمثاله) عبر spandrel. spandrel بيحمّل tensors بس (weights_only) — ما بينفّذ كود من الملف.
الصورة بتتقسّم لقطع (tiles) عشان ذاكرة الكرت ما تخلص، والذاكرة لو ما كفّت بنرجع للمعالج.

الاستيراد الثقيل (torch / spandrel / numpy) داخل الدوال: الملف بينقرأ بدونهم.
"""

from __future__ import annotations

from pathlib import Path

_cache: dict = {}


def load_model(path: Path, device: str):
    """نموذج التكبير (مرة وحدة لكل ملف وجهاز)."""
    key = (str(path), device)
    if key in _cache:
        return _cache[key]
    from spandrel import ImageModelDescriptor, ModelLoader
    desc = ModelLoader().load_from_file(str(path))
    if not isinstance(desc, ImageModelDescriptor):
        raise RuntimeError("الملف مش نموذج تكبير صور")
    desc.eval()
    m = desc.to(device)
    if device == "cuda":
        m = m.half()
    _cache.clear()                                    # نموذج وحدة محمّل بكل لحظة
    _cache[key] = m
    return m


def clear() -> None:
    _cache.clear()


def tile_upscale(arr, model, device: str, tile: int = 192, pad: int = 12, cancel=None):
    """بيرجّع المصفوفة المكبّرة (بمقياس النموذج الأصلي)، أو None لو انلغت الشغلة بين قطعتين."""
    import numpy as np
    import torch
    h, w, _ = arr.shape
    s = model.scale
    out = np.zeros((h * s, w * s, 3), dtype=np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            if cancel is not None and cancel.is_set():
                return None
            y0, x0 = max(y - pad, 0), max(x - pad, 0)
            y1, x1 = min(y + tile + pad, h), min(x + tile + pad, w)
            t = torch.from_numpy(arr[y0:y1, x0:x1].transpose(2, 0, 1)).unsqueeze(0)
            t = t.half().to(device) if device == "cuda" else t.to(device)
            with torch.no_grad():
                r = model(t).float().clamp(0, 1).cpu()[0].numpy().transpose(1, 2, 0)
            ty0, tx0 = (y - y0) * s, (x - x0) * s
            th, tw = min(tile, h - y) * s, min(tile, w - x) * s
            out[y * s:y * s + th, x * s:x * s + tw] = r[ty0:ty0 + th, tx0:tx0 + tw]
    return out


def upscale_file(model_path: Path, src: Path, out: Path, scale: int, max_pixels: int, cancel=None) -> None:
    """src ← out (PNG) مكبّرة ×scale (2..4). max_pixels: سقف مساحة الخرج (حماية الذاكرة)."""
    import numpy as np
    import torch
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        rgb = ImageOps.exif_transpose(im).convert("RGB")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(model_path, device)
    eff = max(scale, int(getattr(model, "scale", scale) or scale))              # المصفوفة بتتحجز بمقياس النموذج الأصلي (×4 حتى لو طلبت ×2)، والتصغير بعدين
    if rgb.width * rgb.height * eff * eff > max_pixels:
        raise RuntimeError(f"الصورة كبيرة للتكبير ×{scale} ({rgb.width}×{rgb.height}) — الحد {max_pixels // 1_000_000} ميغابكسل بالخرج (النموذج بيكبّر ×{eff} داخلياً)")
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    try:
        big = tile_upscale(arr, model, device, cancel=cancel)
    except RuntimeError as e:
        if device == "cuda" and "out of memory" in str(e).lower():
            torch.cuda.empty_cache()
            clear()
            big = tile_upscale(arr, load_model(model_path, "cpu"), "cpu", cancel=cancel)      # على المعالج: بطيء، بس بينلغي بين القطع
        else:
            raise
    if big is None or (cancel is not None and cancel.is_set()):
        return
    np.multiply(big, 255.0, out=big)                                            # على نفس المصفوفة: بلا نسخ float إضافية (3 جيجا لصورة كبيرة)
    np.rint(big, out=big)
    res = Image.fromarray(big.astype("uint8"))
    del big
    target = (rgb.width * scale, rgb.height * scale)
    if res.size != target:
        res = res.resize(target, Image.LANCZOS)
    res.save(out, "PNG", optimize=True)
