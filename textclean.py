"""
«شيل الكتابة والعلامة المائية» من صورة منتج (اقتراح البحث 7).

قارئ النصوص الموجود (EasyOCR) بيلاقي مربعات الكتابة، ومنمسحها بـ OpenCV inpaint (موجود، بلا نماذج إضافية)،
فبيشتغل على الجهاز والسيرفر بالمعالج. الكتابة اللي بتشبه نص ملصق المنتج نفسه (label_text) بتضل:
هي جزء من المنتج، مش إعلان فوقه. مثال: «HOT SALE» الأحمر فوق العلبة بينشال، واسم الكريم على العلبة بيضل.
"""

from __future__ import annotations

import re

import numpy as np

MIN_CONF = 0.3                  # أقل ثقة لمربع كتابة نعتبره كتابة فعلاً
PAD = 4                         # هامش حول المربع (بكسل) عشان ما يضل أثر حروف
RADIUS = 7


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[\s\W_]+", (s or "").lower()) if len(t) >= 2}


def _keep(text: str, keep: set[str]) -> bool:
    """كتابة من ملصق المنتج نفسه (نص الملصق أو الكرتونة): بتضل."""
    got = _tokens(text)
    return bool(got) and len(got & keep) / len(got) >= 0.5


def _reader():
    import image_studio
    if image_studio._OCR is None:                       # نفس القارئ المشترك (بيتحمّل مرة وحدة)
        import config
        import easyocr
        image_studio._OCR = easyocr.Reader(list(getattr(config, "OCR_LANGS", ["ar", "en"])),
                                           gpu=bool(getattr(config, "OCR_USE_GPU", False)), verbose=False)
    return image_studio._OCR


def find_text(rgb: np.ndarray, reader=None) -> list[dict]:
    """[{box: [x0,y0,x1,y1], text, conf}] لكل مربع كتابة."""
    reader = reader or _reader()
    out = []
    for quad, text, conf in reader.readtext(rgb):
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        out.append({"box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))], "text": str(text), "conf": float(conf)})
    return out


def clean(im, keep_text: str = "", reader=None):
    """صورة PIL ← (صورة بلا كتابة دخيلة، عدد المربعات اللي انمسحت). الشفافية (لو في) بتضل متل ما هي."""
    import cv2
    from PIL import Image
    alpha = im.getchannel("A") if "A" in im.getbands() else None
    rgb = np.array(im.convert("RGB"))
    keep = _tokens(keep_text)
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    n = 0
    for t in find_text(rgb, reader):
        if t["conf"] < MIN_CONF or _keep(t["text"], keep):
            continue
        x0, y0, x1, y1 = t["box"]
        mask[max(0, y0 - PAD):y1 + PAD, max(0, x0 - PAD):x1 + PAD] = 255
        n += 1
    if not n:
        return im, 0
    out = Image.fromarray(cv2.inpaint(rgb, mask, RADIUS, cv2.INPAINT_TELEA))
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out, n
