"""ربط النماذج المحلية بالنظام: تكبير خيارات الصور بالذكاء، وتفريغ خلفية زوايا المنتج تلقائياً. النماذج نفسها مزيّفة هون (سريع)."""

import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_studio_images import stage, gen_and_choose  # noqa: E402,F401

import image_studio as ims  # noqa: E402
import product_ref  # noqa: E402
import timeline  # noqa: E402
import upscale  # noqa: E402
import bgremove  # noqa: E402


# ───────── تكبير خيار صورة بالذكاء ─────────
def _fake_upscale(monkeypatch, scale_seen):
    def fake(src, dest, scale=4, **k):
        scale_seen.append(scale)
        im = Image.open(src)
        Image.new("RGB", (im.width * scale, im.height * scale), (10, 20, 30)).save(dest, "PNG")
        return {"path": str(dest), "device": "cpu", "from": list(im.size), "to": [im.width * scale, im.height * scale]}
    monkeypatch.setattr(upscale, "upscale_image", fake)
    monkeypatch.setattr(upscale, "available", lambda: True)


def test_upscale_candidate_adds_a_1080x1920_candidate_without_touching_the_choice(stage, monkeypatch):
    seen = []
    _fake_upscale(monkeypatch, seen)
    sid, cand = gen_and_choose(stage)                           # 1024×1536 ← ×2
    sh = ims.upscale_candidate(stage.script, sid, cand)
    cands = sh["image"]["candidates"]
    new = cands[-1]
    assert seen == [2] and len(cands) >= 2 and new["provider"] == "local" and new["model"] == "Real-ESRGAN"
    assert new["from"] == cand and (new["w"], new["h"]) == (1080, 1920)
    assert Image.open(ims.abs_of("s1", new["path"])).size == (1080, 1920)
    assert not sh["image"].get("chosen")                         # التكبير بيضيف خيار، ما بيختار عن المالك
    assert not list(ims.img_dir("s1").glob("*_raw.png"))         # ما بقي ملف مؤقت


def test_upscale_candidate_uses_x4_for_small_sources(stage, monkeypatch):
    seen = []
    _fake_upscale(monkeypatch, seen)
    stage.size = (400, 600)
    sid, cand = gen_and_choose(stage)
    ims.upscale_candidate(stage.script, sid, cand)
    assert seen == [4]


def test_upscale_candidate_errors_are_arabic_and_clean(stage, monkeypatch):
    sid, cand = gen_and_choose(stage)
    with pytest.raises(ims.ImageStudioError, match="مش من مرشّحات"):
        ims.upscale_candidate(stage.script, sid, "img/other.png")
    monkeypatch.setattr(upscale, "available", lambda: False)
    with pytest.raises(ims.ImageStudioError, match="غير منزّل"):
        ims.upscale_candidate(stage.script, sid, cand)
    monkeypatch.setattr(upscale, "available", lambda: True)

    def boom(*a, **k):
        raise upscale.UpscaleError("الذاكرة ما كفّت")
    monkeypatch.setattr(upscale, "upscale_image", boom)
    with pytest.raises(ims.ImageStudioError, match="الذاكرة"):
        ims.upscale_candidate(stage.script, sid, cand)
    assert not list(ims.img_dir("s1").glob("*_ai*.png"))


# ───────── تفريغ خلفية زاوية المنتج تلقائياً ─────────
def _jpg(size=(80, 60)):
    b = io.BytesIO()
    Image.new("RGB", size, (150, 160, 170)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture
def pref(env, monkeypatch):
    return env


def _fake_bg(monkeypatch):
    def fake(src, dest=None, size=1024):
        im = Image.open(src).convert("RGBA")
        a = Image.new("L", im.size, 0)
        a.paste(255, (10, 10, im.width - 10, im.height - 10))
        im.putalpha(a)
        im.save(dest, "PNG")
        return {"path": str(dest), "device": "cpu", "size": list(im.size), "subject_pct": 50.0}
    monkeypatch.setattr(bgremove, "remove_background", fake)
    monkeypatch.setattr(bgremove, "available", lambda: True)


def test_jpg_is_rejected_without_auto_and_accepted_with_it(pref, monkeypatch):
    _fake_bg(monkeypatch)
    with pytest.raises(product_ref.ProductRefError, match="فرّغ|مفرَّغ"):
        product_ref.set_angle("kama", "front", _jpg())
    ref = product_ref.set_angle("kama", "front", _jpg(), auto_remove=True)
    p = product_ref.angle_path("kama", "front")
    assert ref["angles"]["front"] and p
    out = Image.open(p)
    assert out.mode == "RGBA" and out.getchannel("A").getextrema()[0] == 0           # فيه شفافية فعلاً


def test_auto_flag_keeps_an_already_transparent_png_untouched(pref, monkeypatch):
    called = []
    monkeypatch.setattr(bgremove, "remove_background", lambda *a, **k: called.append(1))
    b = io.BytesIO()
    im = Image.new("RGBA", (40, 40), (200, 30, 30, 255))
    im.putpixel((0, 0), (0, 0, 0, 0))
    im.save(b, "PNG")
    product_ref.set_angle("kama", "back", b.getvalue(), auto_remove=True)
    assert called == []                                                               # الشفاف جاهز: ما في داعي نفرّغ


def test_auto_remove_without_the_model_gives_a_clear_message(pref, monkeypatch):
    monkeypatch.setattr(bgremove, "available", lambda: False)
    with pytest.raises(product_ref.ProductRefError, match="غير منزّل"):
        product_ref.set_angle("kama", "front", _jpg(), auto_remove=True)


def test_upload_route_passes_the_auto_flag(pref, monkeypatch):
    from fastapi.testclient import TestClient
    from web.app import app
    _fake_bg(monkeypatch)
    c = TestClient(app)
    r = c.post("/api/product-refs/kama/angle/front", files={"file": ("a.jpg", _jpg(), "image/jpeg")})
    assert r.status_code == 400
    r = c.post("/api/product-refs/kama/angle/front?auto=1", files={"file": ("a.jpg", _jpg(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["angles"]["front"]
