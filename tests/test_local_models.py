"""النماذج المحلية على جهاز المالك: تفريغ الخلفية (BiRefNet) والتكبير (Real-ESRGAN). الاختبارات الثقيلة بتنتخطّى لو الأوزان مش منزّلة."""

import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import bgremove  # noqa: E402
import upscale  # noqa: E402


def test_errors_are_plain_arabic_messages(tmp_path):
    with pytest.raises(bgremove.BgRemoveError, match="غير موجود"):
        bgremove.remove_background(tmp_path / "nope.png")
    with pytest.raises(upscale.UpscaleError, match="غير موجود"):
        upscale.upscale_image(tmp_path / "nope.png")
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(bgremove.BgRemoveError, match="مش صورة"):
        bgremove.remove_background(bad)
    with pytest.raises(upscale.UpscaleError, match="مش صورة"):
        upscale.upscale_image(bad)
    ok = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(ok)
    with pytest.raises(upscale.UpscaleError, match="×2 أو ×4"):
        upscale.upscale_image(ok, scale=3)


def test_missing_weights_give_a_clear_message(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(img)
    monkeypatch.setattr(upscale, "WEIGHTS", tmp_path / "none.pth")
    monkeypatch.setattr(bgremove, "MODEL_DIR", tmp_path / "none")
    upscale._cache.clear()
    bgremove._cache.clear()
    with pytest.raises(upscale.UpscaleError, match="غير منزّل"):
        upscale.upscale_image(img)
    with pytest.raises(bgremove.BgRemoveError, match="غير منزّل"):
        bgremove.remove_background(img)


@pytest.mark.skipif(not upscale.available(), reason="أوزان Real-ESRGAN غير منزّلة")
def test_upscale_x4_and_x2_produce_exact_sizes_with_tiling(tmp_path):
    src = tmp_path / "s.png"
    img = Image.new("RGB", (70, 50), (30, 60, 120))            # أكبر من حجم القطعة الصغيرة بالاختبار → بيتقسّم لقطع
    for x in range(70):
        img.putpixel((x, 25), (255, 220, 80))
    img.save(src)
    r4 = upscale.upscale_image(src, tmp_path / "o4.png", scale=4, tile=32, pad=6)
    assert r4["to"] == [280, 200] and Image.open(r4["path"]).size == (280, 200)
    r2 = upscale.upscale_image(src, tmp_path / "o2.png", scale=2, tile=32, pad=6)
    assert r2["to"] == [140, 100]
    out = Image.open(r4["path"]).convert("RGB")
    assert out.getpixel((140, 100))[0] > 150 or out.getpixel((140, 104))[0] > 150      # خط الأصفر بقي ظاهر


@pytest.mark.skipif(not bgremove.available() or not os.environ.get("VP_SLOW_TESTS"),
                    reason="تفريغ الخلفية ثقيل (أول تشغيل دقائق) — شغّله بـ VP_SLOW_TESTS=1")
def test_background_removal_makes_transparent_png(tmp_path):
    src = tmp_path / "p.jpg"
    img = Image.new("RGB", (400, 400), (150, 160, 170))
    for x in range(120, 280):
        for y in range(100, 300):
            img.putpixel((x, y), (200, 140, 30))
    img.save(src)
    r = bgremove.remove_background(src, tmp_path / "o.png", size=512)
    out = Image.open(r["path"])
    assert out.mode == "RGBA" and out.size == (400, 400)
    assert out.getpixel((5, 5))[3] < 60 and r["subject_pct"] > 5


# ───────── مكتبات CUDA لـ Whisper (cuda_dlls) ─────────
def test_cuda_dlls_adds_nvidia_bin_dirs_once_and_only_on_windows(tmp_path, monkeypatch):
    from pathlib import Path
    import cuda_dlls
    for sub in ("cublas", "cudnn", "other"):
        (tmp_path / "nvidia" / sub / "bin").mkdir(parents=True)
    monkeypatch.setattr(cuda_dlls, "_site_dirs", lambda: [tmp_path])
    monkeypatch.setattr(cuda_dlls, "_added", [])
    monkeypatch.setattr(cuda_dlls, "_done", False)
    monkeypatch.setattr(cuda_dlls, "_on_windows", lambda: True)
    monkeypatch.setattr(cuda_dlls.os, "add_dll_directory", lambda p: None, raising=False)
    monkeypatch.setenv("PATH", "C:\base")
    added = cuda_dlls.register()
    assert [Path(a).parent.name for a in added] == ["cublas", "cudnn"]                 # "other" ما بينضاف
    assert os.environ["PATH"].startswith(added[-1]) and "C:\base" in os.environ["PATH"]
    assert cuda_dlls.register() == added and os.environ["PATH"].count(added[0]) == 1    # مرة وحدة بس


def test_cuda_dlls_does_nothing_off_windows(monkeypatch):
    import cuda_dlls
    monkeypatch.setattr(cuda_dlls, "_added", [])
    monkeypatch.setattr(cuda_dlls, "_done", False)
    monkeypatch.setattr(cuda_dlls, "_on_windows", lambda: False)
    assert cuda_dlls.register() == []


def test_whisper_gpu_defaults_fit_a_6gb_card():
    import config
    assert config.WHISPER_COMPUTE == "int8_float16" and config.WHISPER_DEVICE == "cuda"
