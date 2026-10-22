"""فحوص الوسائط المرفوعة (media_io): صور، رفع مقطّع بسقف، وffprobe."""

import asyncio
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))

import media_io  # noqa: E402

FFMPEG = shutil.which("ffmpeg") is not None


def png(w=320, h=480, color=(10, 120, 200), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, fmt)
    return buf.getvalue()


def test_kind_of_routes_by_extension_only():
    assert media_io.kind_of("a.PNG") == "image" and media_io.kind_of("x.jpeg") == "image" and media_io.kind_of("x.webp") == "image"
    assert media_io.kind_of("v.mp4") == "video" and media_io.kind_of("v.MOV") == "video"
    assert media_io.kind_of("a.mp3") == "audio" and media_io.kind_of("a.wav") == "audio"
    for bad in ("a.exe", "a.pdf", "noext", "", None, "a.png.exe"):
        assert media_io.kind_of(bad) is None, bad


def test_check_image_accepts_real_images_in_all_formats_and_returns_rgb():
    for fmt in ("PNG", "JPEG", "WEBP"):
        im = media_io.check_image(png(fmt=fmt))
        assert im.mode == "RGB" and im.size == (320, 480)


def test_check_image_rejects_non_images_small_and_empty():
    for bad in (b"", b"not an image", b"\x89PNG\r\n\x1a\n" + b"0" * 50):
        with pytest.raises(media_io.MediaError):
            media_io.check_image(bad)
    with pytest.raises(media_io.MediaError) as e:
        media_io.check_image(png(100, 100))
    assert "256" in str(e.value)


def test_check_image_size_and_pixel_limits(monkeypatch):
    monkeypatch.setattr(media_io, "MAX_IMAGE_BYTES", 1000)
    with pytest.raises(media_io.MediaError) as e:
        media_io.check_image(png(600, 900))
    assert e.value.status == 413
    monkeypatch.setattr(media_io, "MAX_IMAGE_BYTES", 30 * 1024 * 1024)
    monkeypatch.setattr(media_io, "MAX_PIXELS", 100_000)
    with pytest.raises(media_io.MediaError) as e:
        media_io.check_image(png(600, 900))
    assert "ضخمة" in str(e.value)


def test_check_image_applies_exif_orientation():
    im = Image.new("RGB", (400, 300), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6                                                  # يدور 90 درجة
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    out = media_io.check_image(buf.getvalue())
    assert out.size == (300, 400)


def test_save_png_creates_folders(tmp_path):
    out = tmp_path / "a" / "b" / "x.png"
    info = media_io.save_png(Image.new("RGB", (300, 300)), out)
    assert out.exists() and info == {"w": 300, "h": 300}


class FakeUpload:
    def __init__(self, data: bytes):
        self.buf = io.BytesIO(data)

    async def read(self, n=-1):
        return self.buf.read(n)


def test_stream_to_copies_in_chunks_and_enforces_the_limit(tmp_path):
    dest = tmp_path / "up" / "f.bin"
    data = b"x" * (2 * 1024 * 1024 + 5)
    assert asyncio.run(media_io.stream_to(FakeUpload(data), dest, 10 * 1024 * 1024)) == len(data) and dest.read_bytes() == data
    over = tmp_path / "over.bin"
    with pytest.raises(media_io.MediaError) as e:
        asyncio.run(media_io.stream_to(FakeUpload(data), over, 1024 * 1024))
    assert e.value.status == 413 and not over.exists()                 # الجزئي بينحذف
    empty = tmp_path / "empty.bin"
    with pytest.raises(media_io.MediaError):
        asyncio.run(media_io.stream_to(FakeUpload(b""), empty, 100))
    assert not empty.exists()


def make_video(path: Path, seconds=2, audio=False, size="160x288"):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={size}:d={seconds}:r=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg غير متوفر")
def test_probe_and_check_video_and_poster(tmp_path):
    v = make_video(tmp_path / "a.mp4", 2, audio=True)
    info = media_io.check_video(v)
    assert info["has_video"] and info["has_audio"] and (info["width"], info["height"]) == (160, 288) and 1.8 < info["duration_sec"] < 2.3
    silent = media_io.probe_av(make_video(tmp_path / "s.mp4", 1))
    assert silent["has_video"] and not silent["has_audio"]
    p = media_io.poster(v, tmp_path / "p" / "poster.png")
    assert p.exists() and Image.open(p).size == (160, 288)
    with pytest.raises(media_io.MediaError) as e:
        media_io.check_video(v, max_sec=1)
    assert "أطول" in str(e.value)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg غير متوفر")
def test_non_media_files_are_rejected_by_content(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"this is not a video" * 10)
    with pytest.raises(media_io.MediaError):
        media_io.check_video(fake)
    with pytest.raises(media_io.MediaError):
        media_io.poster(fake, tmp_path / "x.png")
    audio_only = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio_only)], check=True, capture_output=True)
    with pytest.raises(media_io.MediaError) as e:
        media_io.check_video(audio_only)
    assert "ما فيه فيديو" in str(e.value)
