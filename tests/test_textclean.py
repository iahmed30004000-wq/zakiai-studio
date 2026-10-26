"""«شيل الكتابة والعلامة المائية» من صور المنتج (اقتراح البحث 7): بيمسح الكتابة الدخيلة وبيخلّي نص الملصق."""

import io
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import product_ref  # noqa: E402
import textclean  # noqa: E402


class FakeReader:
    """بدل EasyOCR: مربعات معروفة سلفاً."""
    def __init__(self, items):
        self.items = items

    def readtext(self, _img):
        return [([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, conf) for (x0, y0, x1, y1), text, conf in self.items]


def product_with_banner():
    im = Image.new("RGB", (300, 300), (230, 230, 230))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 140, 60], fill=(0, 0, 0))            # «HOT SALE» (كتابة دخيلة)
    d.rectangle([110, 150, 190, 170], fill=(0, 0, 0))         # اسم المنتج على الملصق
    return im


def test_removes_foreign_text_and_keeps_the_label():
    im = product_with_banner()
    reader = FakeReader([((20, 20, 140, 60), "HOT SALE", 0.9), ((110, 150, 190, 170), "Glow Cream", 0.9), ((0, 0, 5, 5), "x", 0.1)])
    out, n = textclean.clean(im, keep_text="GLOW CREAM 50ml", reader=reader)
    a = np.array(out).astype(int)
    assert n == 1                                              # الكتابة الضعيفة (ثقة 0.1) ما انعدّت
    assert a[30:50, 40:120].mean() > 150                       # مكان «HOT SALE» صار فاتح متل الخلفية
    assert a[155:165, 120:180].mean() < 40                     # اسم المنتج ضل


def test_nothing_to_remove_returns_the_same_image_and_alpha_survives():
    im = Image.new("RGBA", (50, 50), (10, 20, 30, 0))
    out, n = textclean.clean(im, reader=FakeReader([]))
    assert n == 0 and out is im
    im2 = Image.new("RGBA", (80, 80), (200, 200, 200, 255))
    im2.putpixel((0, 0), (200, 200, 200, 0))
    out2, n2 = textclean.clean(im2, reader=FakeReader([((10, 10, 40, 30), "SALE", 0.8)]))
    assert n2 == 1 and out2.mode == "RGBA" and out2.getpixel((0, 0))[3] == 0


def test_upload_with_clean_counts_what_was_removed(env, monkeypatch):
    env.product("kama.json", product_name="KAMA", product_code="kama", category="eye_care", product_visual="عبوة")
    product_ref.set_details("kama", {"h": 9, "w": 3, "d": 3}, "KAMA drops", ["أبيض"], "bottle")
    seen = {}

    def fake_clean(im, keep_text="", reader=None):
        seen["keep"] = keep_text
        return im, 2
    monkeypatch.setattr(textclean, "clean", fake_clean)
    canvas = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
    canvas.paste(Image.new("RGBA", (40, 120), (30, 80, 200, 255)), (30, 40))
    b = io.BytesIO()
    canvas.save(b, "PNG")
    ref = product_ref.set_angle("kama", "front", b.getvalue(), clean_text=True)
    assert ref["meta"]["front"]["text_removed"] == 2 and "KAMA drops" in seen["keep"]
    ref = product_ref.set_angle("kama", "back", b.getvalue())                     # بلا الخيار: ما في عدّاد
    assert "text_removed" not in ref["meta"]["back"]
