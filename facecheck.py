#!/usr/bin/env python3
"""
فحص ثبات وجه الشخصية محلياً — بلا إنترنت وبلا مفاتيح وبلا كلفة، والصورة ما بتطلع من الجهاز.

  · الكشف: YuNet (OpenCV، رخصة MIT) · المطابقة: SFace (OpenCV، رخصة Apache-2.0). الاتنين على المعالج.
  · الموديلات بمجلد models/face/ (شوف models/README.md). ممنوع InsightFace وأخواتها: رخصتها مش تجارية.
  · بنقارن وجه الصورة (أو 3 لقطات من الفيديو) بصور الشخصية المرجعية (أمام + ثلاثة أرباع) وبناخد أعلى تطابق.
  · الحد (config.FACE_MATCH_THRESHOLD) 0.363 هو الموصى به لـ SFace بالأرقام الخام. صور الذكاء الاصطناعي مش صور كاميرا،
    فبنضبطه على صور شخصياتك الحقيقية لما تتجهّز — والرقم الخام بينعرض دايماً عشان المالك يحكم بعينه.
  · الفحص «بيعلّم» بس: ما بيرفض ولا بيمسح شي، وحكم المالك بشاشة فحص التطابق هو النهائي.

    python facecheck.py --ref أمام.png --ref ثلاثة_أرباع.png لقطة.png|فيديو.mp4
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config

MODELS = Path(config.BASE) / "models" / "face"
DETECTOR = MODELS / "face_detection_yunet_2023mar.onnx"
RECOGNIZER = MODELS / "face_recognition_sface_2021dec.onnx"
# بصمة كل ملف: بتكشف التنزيل الناقص أو الملف المبدَّل قبل ما نحمّله
SHA256 = {
    DETECTOR.name: "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    RECOGNIZER.name: "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}
DEFAULT_THRESHOLD = 0.363
DEFAULT_MIN_PX = 40
DEFAULT_FRAMES = 3
DETECT_LONG_SIDE = 960               # بنصغّر الصورة الكبيرة قبل الكشف (أسرع)؛ والمطابقة بالصورة الأصلية
SCORE_MIN = 0.7                      # ثقة الكشف الدنيا
STATUSES = ("pass", "fail", "no_face", "no_ref")

_LOCK = threading.Lock()             # موديلات OpenCV مش مأمونة بخيطين بنفس الوقت
_engine_cache: dict = {}


class FaceCheckError(Exception):
    """رسالة عربية جاهزة للعرض."""


# ── الإعدادات ────────────────────────────────────────────────────────────
def threshold() -> float:
    try:
        v = float(getattr(config, "FACE_MATCH_THRESHOLD", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return v if 0.05 <= v <= 0.95 else DEFAULT_THRESHOLD


def min_px() -> int:
    try:
        v = int(getattr(config, "FACE_MIN_PX", DEFAULT_MIN_PX))
    except (TypeError, ValueError):
        return DEFAULT_MIN_PX
    return v if 16 <= v <= 400 else DEFAULT_MIN_PX


def video_frames() -> int:
    try:
        v = int(getattr(config, "FACE_VIDEO_FRAMES", DEFAULT_FRAMES))
    except (TypeError, ValueError):
        return DEFAULT_FRAMES
    return v if 1 <= v <= 8 else DEFAULT_FRAMES


def available() -> bool:
    """الموديلات موجودة والمكتبة منزّلة (فحص سريع بلا تحميل)."""
    if not (DETECTOR.exists() and RECOGNIZER.exists()):
        return False
    import importlib.util
    return importlib.util.find_spec("cv2") is not None


def _loadable(p: Path) -> str:
    """OpenCV على ويندوز ما بيقرا مسار فيه حروف عربية (مجلد المشروع اسمه عربي) — بننسخ الملف مرة وحدة لمسار إنجليزي
    (اسمه فيه بصمته فما بيتكرر ولا بيلتبس). على غير ويندوز أو مسار إنجليزي: المسار نفسه."""
    if str(p).isascii():
        return str(p)
    import os
    import tempfile
    tag = SHA256.get(p.name, "")[:12]
    for base in (tempfile.gettempdir(), os.environ.get("PROGRAMDATA", ""), "C:\\"):
        if not base or not base.isascii() or not Path(base).is_dir():
            continue
        dest = Path(base) / "zakiai_face" / f"{tag}_{p.name}"
        try:
            if not (dest.exists() and dest.stat().st_size == p.stat().st_size):
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + f".{os.getpid()}.tmp")
                shutil.copyfile(p, tmp)
                os.replace(tmp, dest)
            return str(dest)
        except OSError:
            continue
    raise FaceCheckError("ما قدرنا نجهّز نموذج الوجه: مسار المشروع فيه حروف عربية وما لقينا مجلد إنجليزي للنسخ")


# ── المحرّك الحقيقي (OpenCV) — الاختبارات بتحقن محرّك مزيّف بنفس الواجهة ─────
class CvEngine:
    """faces(img) → [{box, score, row}] · embed(img, face) → متجه · cosine(a, b) → رقم. الصور BGR (numpy)."""

    def __init__(self) -> None:
        for f in (DETECTOR, RECOGNIZER):
            if not f.exists():
                raise FaceCheckError("نماذج فحص الوجه (YuNet + SFace) غير منزّلة بمجلد models/face/")
            if hashlib.sha256(f.read_bytes()).hexdigest() != SHA256[f.name]:
                raise FaceCheckError(f"ملف نموذج الوجه {f.name} تالف أو مبدَّل — نزّله من جديد (models/README.md)")
        try:
            import cv2
        except ImportError as e:
            raise FaceCheckError(f"مكتبة ناقصة: {e.name} — pip install opencv-python")
        if not (hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")):
            raise FaceCheckError("نسخة OpenCV المنزّلة قديمة (ما فيها كشف الوجوه) — حدّثها: pip install -U opencv-python")
        try:                                                  # تحذيرات داخلية عن «المحرّك الجديد» بتملا السجل بلا فايدة
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:                                     # noqa: BLE001
            pass
        self.cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(_loadable(DETECTOR), "", (320, 320), SCORE_MIN, 0.3, 5000)
        self._rec = cv2.FaceRecognizerSF.create(_loadable(RECOGNIZER), "")
        self.ref_cache: dict = {}

    def faces(self, img) -> list[dict]:
        import numpy as np
        h, w = img.shape[:2]
        scale = min(1.0, DETECT_LONG_SIDE / max(h, w))
        small = self.cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale)))) if scale < 1 else img
        self._det.setInputSize((small.shape[1], small.shape[0]))
        _n, rows = self._det.detect(small)
        out = []
        for r in (rows if rows is not None else []):
            r = np.array(r, dtype=np.float32)
            r[:14] /= scale                                   # إحداثيات الصورة الأصلية
            out.append({"box": tuple(int(round(v)) for v in r[:4]), "score": float(r[14]), "row": r})
        return out

    def embed(self, img, face: dict):
        return self._rec.feature(self._rec.alignCrop(img, face["row"]))

    def cosine(self, a, b) -> float:
        return float(self._rec.match(a, b, self.cv2.FaceRecognizerSF_FR_COSINE))


def _engine() -> CvEngine:
    if "e" not in _engine_cache:
        _engine_cache["e"] = CvEngine()
    return _engine_cache["e"]


# ── الصور والفيديو ───────────────────────────────────────────────────────
def _decode(data_or_path):
    import numpy as np
    from PIL import Image
    with Image.open(data_or_path) as im:
        rgb = np.asarray(im.convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])             # BGR


def _load_bgr(path):
    """PIL مش cv2.imread: ويندوز + مسار عربي = cv2 بيفشل بصمت."""
    from PIL import UnidentifiedImageError
    p = Path(path)
    if not p.exists():
        raise FaceCheckError("ملف الصورة غير موجود")
    try:
        return _decode(p)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise FaceCheckError(f"تعذّر قراءة الصورة: {p.name}") from e


def _duration(video) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                            str(video)], capture_output=True, text=True, timeout=30)
        return max(0.0, float(r.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _grab_frame(video, t: float):
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return _decode(io.BytesIO(r.stdout))
    except Exception:                                         # noqa: BLE001 — لقطة تالفة = لقطة ناقصة، مش خطأ
        return None


# ── المنطق ───────────────────────────────────────────────────────────────
def _w(face: dict) -> int:
    return int(face["box"][2])


def _usable(engine, img) -> list[dict]:
    return [f for f in engine.faces(img) if _w(f) >= min_px()]


def _ref_embeddings(engine, refs) -> tuple[list[tuple[str, object]], list[str]]:
    """متجه أكبر وجه بكل صورة مرجعية. اللي ما فيها وجه واضح بتنتخطّى (وبترجع أسماؤها)."""
    out, skipped = [], []
    cache = getattr(engine, "ref_cache", None)
    for r in refs:
        p = Path(r)
        try:
            st = p.stat()
        except OSError:
            skipped.append(p.name)
            continue
        key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
        if cache is not None and key in cache:
            emb = cache[key]
        else:
            try:
                img = _load_bgr(p)
            except FaceCheckError:
                skipped.append(p.name)
                continue
            faces = _usable(engine, img)
            emb = engine.embed(img, max(faces, key=lambda f: f["box"][2] * f["box"][3])) if faces else None
            if cache is not None:
                cache[key] = emb
        if emb is None:
            skipped.append(p.name)
        else:
            out.append((p.stem, emb))
    return out, skipped


def _best(engine, ref_embs, img) -> dict | None:
    """أعلى تطابق بين أي وجه بالصورة وأي مرجع. None لو ما في وجه بحجم كافي."""
    faces = _usable(engine, img)
    if not faces:
        return None
    best = None
    for f in faces:
        emb = engine.embed(img, f)
        for name, ref in ref_embs:
            s = float(engine.cosine(emb, ref))
            if best is None or s > best["similarity"]:
                best = {"similarity": s, "ref": name, "face_px": _w(f)}
    best["faces"] = len(faces)
    return best


def _no_ref(skipped: list[str]) -> dict:
    return {"status": "no_ref", "similarity": None, "threshold": threshold(), "faces": 0,
            "note": "ما لقينا وجه واضح بصور الشخصية المرجعية (أمام / ثلاثة أرباع) — الفحص ما بيشتغل بلاها"
                    + (f" ({'، '.join(skipped)})" if skipped else "")}


def _say(status: str, sim: float | None) -> str:
    thr = threshold()
    if status == "pass":
        return f"الوجه مطابق للشخصية (تطابق {sim:.2f}، الحد {thr:.2f})"
    if status == "fail":
        return f"الوجه تغيّر عن الشخصية (تطابق {sim:.2f} وأقل من الحد {thr:.2f})"
    return "ما انكشف وجه واضح — بعيد أو مغطّى أو مقطوع — فالفحص ما بيقدر يحكم"


def check_image(refs, image, *, engine=None) -> dict:
    """يقارن وجه الصورة بالمراجع. status: pass | fail | no_face | no_ref.
    {status, similarity, threshold, faces, face_px, ref, note}. بيرمي FaceCheckError للمشاكل التقنية (موديل ناقص، صورة تالفة)."""
    img = _load_bgr(image)
    with _LOCK:
        eng = engine or _engine()
        ref_embs, skipped = _ref_embeddings(eng, list(refs or []))
        if not ref_embs:
            return _no_ref(skipped)
        best = _best(eng, ref_embs, img)
    if best is None:
        return {"status": "no_face", "similarity": None, "threshold": threshold(), "faces": 0, "face_px": None,
                "ref": None, "note": _say("no_face", None)}
    status = "pass" if best["similarity"] >= threshold() else "fail"
    best["similarity"] = round(best["similarity"], 3)
    return {"status": status, "threshold": threshold(), **best, "note": _say(status, best["similarity"])}


def check_video(refs, video, *, frames: int | None = None, engine=None, grab=None, duration=None) -> dict:
    """يفحص N لقطات موزّعة على الفيديو (افتراضي 3). الحكم من أسوأ لقطة فيها وجه: لو الوجه انحرف بآخر الفيديو بنعرف.
    + frames: [{at, status, similarity}] لكل لقطة."""
    n = frames or video_frames()
    if grab is None:
        if not Path(video).exists():
            raise FaceCheckError("ملف الفيديو غير موجود")
        if shutil.which("ffmpeg") is None:
            raise FaceCheckError("ffmpeg مش موجود — ما بنقدر نقرأ لقطات الفيديو")
        grab = _grab_frame
        total = duration if duration is not None else _duration(video)
    else:
        total = duration if duration is not None else 1.0
    if not total or total <= 0:
        raise FaceCheckError("تعذّر قراءة مدة الفيديو")
    fracs = [(i + 0.5) / n for i in range(n)]
    with _LOCK:
        eng = engine or _engine()
        ref_embs, skipped = _ref_embeddings(eng, list(refs or []))
        if not ref_embs:
            return {**_no_ref(skipped), "frames": []}
        rows, got = [], 0
        for fr in fracs:
            img = grab(video, round(total * fr, 3))
            if img is None:
                rows.append({"at": round(fr, 2), "status": "unreadable", "similarity": None})
                continue
            got += 1
            best = _best(eng, ref_embs, img)
            if best is None:
                rows.append({"at": round(fr, 2), "status": "no_face", "similarity": None})
            else:
                s = round(best["similarity"], 3)
                rows.append({"at": round(fr, 2), "status": "pass" if s >= threshold() else "fail", "similarity": s,
                             "face_px": best["face_px"]})
    if not got:
        raise FaceCheckError("تعذّر قراءة أي لقطة من الفيديو")
    scored = [r for r in rows if r["similarity"] is not None]
    if not scored:
        return {"status": "no_face", "similarity": None, "threshold": threshold(), "frames": rows, "note": _say("no_face", None)}
    worst = min(scored, key=lambda r: r["similarity"])
    status = "pass" if all(r["status"] == "pass" for r in scored) else "fail"
    note = _say(status, worst["similarity"])
    if status == "fail":
        bad = [f"{round(r['at'] * 100)}٪" for r in scored if r["status"] == "fail"]
        note += f" — بلقطات عند {'، '.join(bad)} من الفيديو"
    elif len(scored) < len(rows):
        note += f" (انفحصت {len(scored)} من {len(rows)} لقطات؛ الباقي بلا وجه واضح)"
    return {"status": status, "similarity": worst["similarity"], "threshold": threshold(), "frames": rows, "note": note}


# ── مراجع الشخصية ────────────────────────────────────────────────────────
def character_refs(cid: str) -> list[Path]:
    """صور الوجه المرجعية للشخصية (نفس الوضعيتين اللي بتنبعت مع التوليد)."""
    import characters
    import refprompts
    out = []
    for v in refprompts.CHARACTER_FACE_VIEWS:
        p = characters.sheet_path(cid, v)
        if p:
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="فحص ثبات وجه الشخصية (محلي)")
    ap.add_argument("target", help="صورة أو فيديو")
    ap.add_argument("--ref", action="append", required=True, help="صورة وجه مرجعية (كرّرها)")
    a = ap.parse_args()
    try:
        is_video = Path(a.target).suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi"}
        r = check_video(a.ref, a.target) if is_video else check_image(a.ref, a.target)
    except FaceCheckError as e:
        sys.exit(f"[!] {e}")
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
