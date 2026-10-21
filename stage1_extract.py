#!/usr/bin/env python3
"""
STAGE 1 — EXTRACTOR
يحوّل أي فيديو ناجح (رابط أو ملف) إلى ملف JSON منظّم:
  - الصوت مفرّغ نصياً مع الطوابع الزمنية (Whisper)
  - الفيديو مقصوص لمشاهد أوتوماتيكياً (PySceneDetect)
  - لقطة مفتاحية (frame) لكل مشهد
  - النص الظاهر على الشاشة لكل لقطة (OCR عربي + إنجليزي)
  - ربط الفويس أوفر بكل مشهد حسب التوقيت

الاستخدام:
    python stage1_extract.py "https://www.tiktok.com/@user/video/123"
    python stage1_extract.py ./ads/clarden_v3.mp4 --id clarden_v3
    python stage1_extract.py --batch links.txt
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# كونسول ويندوز افتراضياً cp1252 وبيفشل مع العربي
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _register_cuda_dlls() -> None:
    """مكتبات CUDA بتنزل جوا site-packages وويندوز ما بيدوّر فيها — لازم نسجّلها يدوياً."""
    if not hasattr(os, "add_dll_directory"):
        return
    import site
    roots = set(site.getsitepackages() + [site.getusersitepackages()])
    for root in roots:
        nvidia = Path(root) / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                pass
            # CTranslate2 بيحمّل المكتبات عبر PATH مش عبر add_dll_directory
            if str(bin_dir) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


_register_cuda_dlls()

from config import (
    RAW_DIR,
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE,
    WHISPER_LANGUAGE,
    SCENE_THRESHOLD,
    MIN_SCENE_SEC,
    OCR_LANGS,
    OCR_MIN_CONFIDENCE,
    OCR_USE_GPU,
)

# ----------------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------------


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\u0600-\u06FF-]+", "_", str(text).strip())
    return re.sub(r"_+", "_", text).strip("_")[:60] or "video"


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("[!] ffmpeg غير مثبّت. ثبّته أولاً ثم أعد المحاولة.")


def run(cmd: list) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------------------------------------------------------------------
# 1) التحميل
# ----------------------------------------------------------------------------


def fetch_video(source: str, out_dir: Path, video_id: str) -> tuple:
    """يرجّع (مسار الملف, بيانات وصفية). يقبل رابط أو ملف محلي."""
    local = Path(source)
    if local.exists():
        target = out_dir / f"{video_id}{local.suffix}"
        shutil.copy(local, target)
        return target, {"source_type": "local_file", "source": f"local:{local.name}"}

    try:
        import yt_dlp
    except ImportError:
        sys.exit("[!] ثبّت yt-dlp:  pip install yt-dlp")

    opts = {
        "outtmpl": str(out_dir / f"{video_id}.%(ext)s"),
        "format": "mp4/bestvideo+bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=True)
        path = Path(ydl.prepare_filename(info))

    meta = {
        "source_type": "url",
        "source": source,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "caption": info.get("description"),
    }
    return path, meta


def probe(video_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    vs = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    return {
        "duration_sec": round(float(data["format"].get("duration", 0)), 2),
        "width": vs.get("width"),
        "height": vs.get("height"),
        "fps": round(eval(vs.get("r_frame_rate", "0/1")), 2) if vs.get("r_frame_rate") else None,
        "aspect": f'{vs.get("width")}x{vs.get("height")}',
    }


# ----------------------------------------------------------------------------
# 2) التفريغ الصوتي
# ----------------------------------------------------------------------------


def transcribe(video_path: Path, out_dir: Path) -> dict:
    audio = out_dir / "audio.wav"
    run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio)])

    import stt
    cfg = stt.stt_config()
    print(f"      التفريغ عبر: {cfg['provider']} · {cfg['model']}")
    try:
        result = stt.transcribe(audio)
    except stt.STTError as e:
        audio.unlink(missing_ok=True)
        sys.exit(f"[!] {e}")
    finally:
        audio.unlink(missing_ok=True)

    segs = [s for s in result["segments"] if s["text"].strip()]
    write_srt(segs, out_dir / "transcript.srt")
    return {
        "language": result.get("language"),
        "language_confidence": result.get("language_confidence", 0),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "full_text": result.get("full_text") or " ".join(s["text"] for s in segs),
        "word_count": sum(len(s["text"].split()) for s in segs),
        "segments": segs,
    }


def write_srt(segments: list, path: Path) -> None:
    def ts(sec: float) -> str:
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"

    lines = []
    for i, s in enumerate(segments, 1):
        lines += [str(i), f"{ts(s['start'])} --> {ts(s['end'])}", s["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
# 3) كشف المشاهد + استخراج اللقطات
# ----------------------------------------------------------------------------


def detect_scenes(video_path: Path) -> list:
    try:
        from scenedetect import detect, ContentDetector
    except ImportError:
        sys.exit("[!] ثبّت scenedetect:  pip install scenedetect[opencv]")

    fps = probe(video_path).get("fps") or 24.0
    scenes = detect(
        str(video_path),
        ContentDetector(threshold=SCENE_THRESHOLD, min_scene_len=max(1, int(MIN_SCENE_SEC * fps))),
    )
    if not scenes:  # فيديو بلقطة واحدة متواصلة
        dur = probe(video_path)["duration_sec"]
        return [{"index": 1, "start": 0.0, "end": dur, "duration": dur}]

    return [
        {
            "index": i,
            "start": round(a.get_seconds(), 2),
            "end": round(b.get_seconds(), 2),
            "duration": round(b.get_seconds() - a.get_seconds(), 2),
        }
        for i, (a, b) in enumerate(scenes, 1)
    ]


def grab_frames(video_path: Path, scenes: list, frames_dir: Path) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    missed = 0
    for sc in scenes:
        out = frames_dir / f"scene_{sc['index']:02d}.jpg"
        mid = sc["start"] + sc["duration"] / 2
        # القفز لنص المشهد بيفشل أحياناً بآخر مشهد (المدة المعلنة أطول من الديكود الفعلي)،
        # فمنجرّب نقطة أبكر قبل ما نستسلم — لقطة ناقصة أهون من إسقاط الفيديو كله
        for target in (mid, sc["start"] + sc["duration"] * 0.25, sc["start"]):
            cmd = [
                "ffmpeg", "-y", "-ss", f"{max(0.0, target):.2f}", "-i", str(video_path),
                "-frames:v", "1", "-q:v", "3", "-vf", "scale=720:-1", str(out),
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0 and out.exists():
                sc["frame"] = str(out.relative_to(frames_dir.parent))
                break
        else:
            sc["frame"] = ""
            missed += 1
    if missed:
        print(f"      [i] تعذّر استخراج {missed} لقطة — تم تخطّيها")


# ----------------------------------------------------------------------------
# 4) OCR على اللقطات
# ----------------------------------------------------------------------------


_ocr_reader = None


def ocr_reader():
    """يُحمَّل مرة وحدة ويُعاد استخدامه — مهم بوضع الدفعة."""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        print(f"[…] تحميل OCR (GPU={OCR_USE_GPU})…")
        _ocr_reader = easyocr.Reader(OCR_LANGS, gpu=OCR_USE_GPU, verbose=False)
    return _ocr_reader


def ocr_frames(scenes: list, base_dir: Path) -> None:
    try:
        import cv2
        import easyocr  # noqa: F401
    except ImportError:
        print("[i] easyocr غير مثبّت — تم تخطي OCR.")
        for sc in scenes:
            sc["on_screen_text"] = []
        return

    import numpy as np

    reader = ocr_reader()
    for sc in scenes:
        frame = base_dir / sc.get("frame", "")
        if not frame.exists():
            sc["on_screen_text"] = []
            continue
        # OpenCV على ويندوز ما بيفتح مسارات فيها حروف غير لاتينية — نقرأ بايتات ونفك الترميز بالذاكرة
        image = cv2.imdecode(np.fromfile(str(frame), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            sc["on_screen_text"] = []
            continue
        results = reader.readtext(image)
        sc["on_screen_text"] = [
            txt.strip() for _, txt, conf in results
            if conf >= OCR_MIN_CONFIDENCE and txt.strip()
        ]


# ----------------------------------------------------------------------------
# 5) ربط الفويس أوفر بالمشاهد
# ----------------------------------------------------------------------------


def map_voiceover(scenes: list, segments: list) -> None:
    for sc in scenes:
        parts = []
        for seg in segments:
            overlap = min(sc["end"], seg["end"]) - max(sc["start"], seg["start"])
            if overlap > 0.25 * max(0.01, seg["end"] - seg["start"]):
                parts.append(seg["text"])
        sc["voiceover"] = " ".join(parts).strip()


# ----------------------------------------------------------------------------
# التشغيل
# ----------------------------------------------------------------------------


def process(source: str, video_id: str = None, force: bool = False) -> Path:
    check_ffmpeg()
    video_id = video_id or slugify(Path(source).stem if Path(source).exists() else source.split("/")[-1])
    work = Path(RAW_DIR) / video_id

    done = work / "extract.json"
    if done.exists() and not force:
        print(f"[=] متخطّى (معالَج سابقاً): {video_id}")
        return done

    work.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/5] تحميل: {video_id}")
    video_path, meta = fetch_video(source, work, video_id)
    meta.update(probe(video_path))

    print("[2/5] كشف المشاهد…")
    scenes = detect_scenes(video_path)
    print(f"      عدد المشاهد: {len(scenes)}")

    print("[3/5] استخراج اللقطات…")
    grab_frames(video_path, scenes, work / "frames")

    print("[4/5] تفريغ الصوت…")
    transcript = transcribe(video_path, work)

    print("[5/5] قراءة نصوص الشاشة (OCR)…")
    ocr_frames(scenes, work)
    map_voiceover(scenes, transcript["segments"])

    payload = {
        "video_id": video_id,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "transcript": transcript,
        "scene_count": len(scenes),
        "scenes": scenes,
    }
    out = work / "extract.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[✓] تم: {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 1 — استخراج بيانات الفيديو")
    ap.add_argument("source", nargs="?", help="رابط الفيديو أو مسار الملف")
    ap.add_argument("--id", help="اسم مخصص للفيديو")
    ap.add_argument("--batch", help="ملف نصي فيه رابط/مسار بكل سطر")
    ap.add_argument("--force", action="store_true", help="أعد المعالجة حتى لو كان معالَج سابقاً")
    args = ap.parse_args()

    if args.batch:
        links = [l.strip() for l in Path(args.batch).read_text(encoding="utf-8").splitlines() if l.strip()]
        failures = []
        for i, link in enumerate(links, 1):
            print(f"\n===== [{i}/{len(links)}] =====", flush=True)
            try:
                process(link, force=args.force)
            except Exception as e:
                print(f"[!] فشل {link}: {e}", flush=True)
                failures.append(link)
        ok = len(links) - len(failures)
        print(f"\n[✓] انتهت الدفعة: {ok} نجحت، {len(failures)} فشلت")
        if failures:
            Path("library/failed_sources.txt").write_text("\n".join(failures), encoding="utf-8")
            print("    الملفات الفاشلة في: library/failed_sources.txt")
        # فشل كامل لازم يظهر كفشل للمشغّل، مش كنجاح
        if failures and ok == 0:
            sys.exit("[!] كل العناصر فشلت — شوف الأخطاء فوق")
    elif args.source:
        process(args.source, args.id, force=args.force)
    else:
        ap.error("لازم تمرّر رابط/ملف أو --batch")


if __name__ == "__main__":
    main()
