"""
تكبير الصور محلياً بـ Real-ESRGAN (BSD) عبر مكتبة spandrel — بلا إنترنت.

الأوزان: models/RealESRGAN_x4plus.pth. الصورة بتتقسّم لقطع (tiles) عشان كرت 6 جيجا ما يخلص ذاكرتو،
والذاكرة لو ما كفّت بنرجع للمعالج تلقائياً.

    python upscale.py صورة.jpg [خرج.png] [--scale 2|4]
"""

from __future__ import annotations

import sys
from pathlib import Path

import config

WEIGHTS = Path(config.BASE) / "models" / "RealESRGAN_x4plus.pth"
_cache: dict = {}


class UpscaleError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _library_model() -> dict | None:
    """نموذج تكبير مربوط بمكتبة النماذج (افتراضي) وجاهز؟"""
    try:
        import model_library
        return model_library.pick("upscale").model
    except Exception:                                  # noqa: BLE001 — خطأ مكتبة ما بيوقف الطريقة المحلية
        return None


def available() -> bool:
    return WEIGHTS.exists() or _library_model() is not None


def _via_library(src: Path, dest: Path, scale: int, size: tuple) -> dict | None:
    """بيجرّب نموذج المكتبة. None = كمّل بـ Real-ESRGAN المحلي (ما في نموذج، أو وقع تقنياً والرجوع مسموح)."""
    import model_run
    from PIL import Image
    res, note = model_run.run_via_library("upscale", model_run.RunRequest(task="upscale", image=src, out=dest, params={"scale": scale}),
                                          error_cls=UpscaleError)
    if res is None:
        if note:
            print(f"[i] {note}", flush=True)
        return None
    with Image.open(dest) as big:
        to = list(big.size)
    return {"path": str(dest), "device": "library", "from": list(size), "to": to, "model": res.model_name, "logged": True}


def _model(device: str):
    if device in _cache:
        return _cache[device]
    if not available():
        raise UpscaleError("نموذج التكبير (Real-ESRGAN) غير منزّل بمجلد models/")
    try:
        import torch
        from spandrel import ImageModelDescriptor, ModelLoader
    except ImportError as e:
        raise UpscaleError(f"مكتبة ناقصة: {e.name} — pip install spandrel")
    # spandrel بيحمّل أوزان tensors بس (weights_only) — ما بينفّذ كود من الملف
    desc = ModelLoader().load_from_file(str(WEIGHTS))
    if not isinstance(desc, ImageModelDescriptor):
        raise UpscaleError("ملف الأوزان مش نموذج تكبير صور")
    desc.eval()
    m = desc.to(device)
    if device == "cuda":
        m = m.half()
    _cache[device] = m
    return m


def _tile_upscale(arr, model, device: str, tile: int, pad: int):
    import numpy as np
    import torch
    h, w, _ = arr.shape
    s = model.scale
    out = np.zeros((h * s, w * s, 3), dtype=np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
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


def upscale_image(src, dest=None, scale: int = 4, tile: int = 192, pad: int = 12) -> dict:
    """يكبّر الصورة ×2 أو ×4 ويحفظ PNG. بيرجّع {path, device, from, to}."""
    import numpy as np
    from PIL import Image
    if scale not in (2, 4):
        raise UpscaleError("التكبير ×2 أو ×4 بس")
    src = Path(src)
    if not src.exists():
        raise UpscaleError("ملف الصورة غير موجود")
    try:
        img = Image.open(src)
        img.load()
    except Exception:
        raise UpscaleError("الملف مش صورة صالحة")
    dest = Path(dest) if dest else src.with_name(f"{src.stem}_x{scale}.png")
    lib = _via_library(src, dest, scale, img.size)
    if lib is not None:
        return lib
    import torch
    rgb = img.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        big = _tile_upscale(arr, _model(device), device, tile, pad)
    except RuntimeError as e:
        if device == "cuda" and "out of memory" in str(e).lower():
            torch.cuda.empty_cache()
            _cache.pop("cuda", None)
            device = "cpu"
            big = _tile_upscale(arr, _model(device), device, tile, pad)
        else:
            raise
    res = Image.fromarray((big * 255).round().astype("uint8"))
    if scale == 2:
        res = res.resize((rgb.width * 2, rgb.height * 2), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    res.save(dest, "PNG", optimize=True)
    return {"path": str(dest), "device": device, "from": list(img.size), "to": list(res.size)}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sc = 2 if "--scale" in sys.argv and sys.argv[sys.argv.index("--scale") + 1] == "2" else 4
    args = [a for a in args if a not in ("2", "4")]
    if not args:
        print("الاستخدام: python upscale.py صورة.jpg [خرج.png] [--scale 2|4]")
        sys.exit(2)
    try:
        r = upscale_image(args[0], args[1] if len(args) > 1 else None, scale=sc)
    except UpscaleError as e:
        print(f"[خطأ] {e}")
        sys.exit(1)
    print(f"[✓] {r['path']} — {r['device']} — {r['from'][0]}×{r['from'][1]} ← {r['to'][0]}×{r['to'][1]}")
