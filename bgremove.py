"""
تفريغ خلفية الصور محلياً بنموذج BiRefNet (MIT) — بلا إنترنت وبلا API.

الاستخدام: صور المنتجات والشخصيات (المنتج بخلفية شفافة لدمجه بمشهد).
الأوزان: models/BiRefNet (منزّلة مسبقاً). بنحمّلها مرة وحدة، وعلى كرت 6 جيجا بنشتغل بـ fp16؛
ولو الذاكرة ما كفّت بنرجع للمعالج تلقائياً.

    python bgremove.py صورة.jpg [خرج.png]
"""

from __future__ import annotations

import sys
from pathlib import Path

import config

MODEL_DIR = Path(config.BASE) / "models" / "BiRefNet"
SIZE = 1024                                    # حجم الاستدلال الأصلي للنموذج
_cache: dict = {}


class BgRemoveError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _library_model() -> dict | None:
    """نموذج تفريغ خلفية مربوط بمكتبة النماذج (افتراضي) وجاهز؟"""
    try:
        import model_library
        return model_library.pick("bgremove").model
    except Exception:                                  # noqa: BLE001 — خطأ مكتبة ما بيوقف الطريقة المحلية
        return None


def available() -> bool:
    return (MODEL_DIR / "model.safetensors").exists() or _library_model() is not None


def _via_library(src: Path, dest: Path, size: tuple) -> dict | None:
    """بيجرّب نموذج المكتبة (النتيجة لازم PNG شفاف — model_run بيتأكد). None = كمّل بـ BiRefNet المحلي."""
    import model_run
    import numpy as np
    from PIL import Image
    res, note = model_run.run_via_library("bgremove", model_run.RunRequest(task="bgremove", image=src, out=dest), error_cls=BgRemoveError)
    if res is None:
        if note:
            print(f"[i] {note}", flush=True)
        return None
    with Image.open(dest) as out:
        alpha = np.asarray(out.convert("RGBA").getchannel("A"))
    return {"path": str(dest), "device": "library", "size": list(size), "subject_pct": round(float((alpha > 127).mean() * 100), 1),
            "model": res.model_name, "logged": True}


def _load(device: str):
    key = device
    if key in _cache:
        return _cache[key]
    if not available():
        raise BgRemoveError("نموذج تفريغ الخلفية (BiRefNet) غير منزّل بمجلد models/BiRefNet")
    try:
        import torch
        from transformers import AutoModelForImageSegmentation
    except ImportError as e:
        raise BgRemoveError(f"مكتبة ناقصة: {e.name} — pip install transformers timm kornia einops")
    try:
        # الكود المرفق مع الأوزان (birefnet.py) انفحص يدوياً: بلا شبكة ولا تنفيذ أوامر، وbb_pretrained=false
        model = AutoModelForImageSegmentation.from_pretrained(
            str(MODEL_DIR), trust_remote_code=True, local_files_only=True)
    except Exception as e:
        raise BgRemoveError(f"تعذّر تحميل النموذج: {str(e)[:200]}")
    model.eval()
    if device == "cuda":
        model = model.half()
    _cache[key] = model.to(device)
    return _cache[key]


def _run(img, device: str, size: int):
    import numpy as np
    import torch
    from PIL import Image
    model = _load(device)
    rgb = img.convert("RGB").resize((size, size), Image.BICUBIC)
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    arr = (arr - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0)
    x = x.half().to(device) if device == "cuda" else x.to(device)
    with torch.no_grad():
        pred = model(x)[-1].sigmoid().float().cpu()[0, 0]
    mask = Image.fromarray((pred.numpy() * 255).clip(0, 255).astype("uint8")).resize(img.size, Image.BICUBIC)
    return mask


def remove_background(src, dest=None, size: int = SIZE) -> dict:
    """يفرّغ الخلفية ويحفظ PNG شفاف. بيرجّع {path, device, size, subject_pct}."""
    from PIL import Image
    src = Path(src)
    if not src.exists():
        raise BgRemoveError("ملف الصورة غير موجود")
    try:
        img = Image.open(src)
        img.load()
    except Exception:
        raise BgRemoveError("الملف مش صورة صالحة")
    dest = Path(dest) if dest else src.with_name(src.stem + "_nobg.png")
    lib = _via_library(src, dest, img.size)
    if lib is not None:
        return lib
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        mask = _run(img, device, size)
    except (RuntimeError, BgRemoveError) as e:
        if device == "cuda" and "out of memory" in str(e).lower():
            torch.cuda.empty_cache()
            _cache.pop("cuda", None)
            device = "cpu"
            mask = _run(img, device, size)         # الذاكرة ما كفّت ← المعالج (أبطأ بس بيكمّل)
        else:
            raise
    out = img.convert("RGBA")
    out.putalpha(mask)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "PNG", optimize=True)
    import numpy as np
    subject = float((np.asarray(mask) > 127).mean() * 100)
    return {"path": str(dest), "device": device, "size": list(img.size), "subject_pct": round(subject, 1)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("الاستخدام: python bgremove.py صورة.jpg [خرج.png]")
        sys.exit(2)
    try:
        r = remove_background(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    except BgRemoveError as e:
        print(f"[خطأ] {e}")
        sys.exit(1)
    print(f"[✓] {r['path']} — {r['device']} — المنتج {r['subject_pct']}٪ من الصورة".replace("٪", "%"))
