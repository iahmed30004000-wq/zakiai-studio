"""
مهام مكتبة النماذج — «جرّب»: تشغيل نموذج بعيّنة جاهزة (أو بملفاتك) قبل ما تعتمده أو بأي وقت، ونتيجته بتنحفظ للمعاينة.

    python model_tasks.py try ml_001        (بتنشغّل كمهمة خلفية من الواجهة؛ المعاملات بملف params.json جنب الملفات)

المجلد: library/model_tests/<ml_id>/
    params.json   مدخلات المالك النصية (prompt, text, seconds, language) — بيكتبها مسار الواجهة قبل المهمة
    in/           ملفات رفعها المالك للتجربة (image.* · audio.* · video.*)
    result.*      آخر ناتج (صورة png، صوت mp3، فيديو mp4)
    last.json     ملخّص آخر تجربة (نجحت؟ كم أخدت؟ شو الناتج؟ سبب الفشل بالعربي)

القواعد:
  · التجربة بتشتغل حتى لو النموذج لسا معطّل (نجرّب قبل ما نفعّل)، بس بوابة الرخصة بتضل: «ممنوع» ما بيتجرّب، والمشروط لازم تأكيدك.
  · ما بتنحسب بسجل الإنتاج (نسبة النجاح بتعدّ الإنتاج الفعلي بس).
  · أدخل الصورة/الصوت/الفيديو من المالك بنفس سقوف وفحوص الرفع بالمشروع الحر (media_io).
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import model_library
import model_run

SAMPLES = {
    "image": {"prompt": "a glass perfume bottle on white marble, soft studio lighting, vertical product photo, no text"},
    "voice": {"text": "أهلاً وسهلاً، هذا اختبار صوت من مكتبة النماذج."},
    "music": {"prompt": "calm lo-fi background music, soft piano, warm", "seconds": 10},
    "sfx": {"prompt": "short soft whoosh transition", "seconds": 2},
}
NEEDS_UPLOAD = {"stt": ("audio", "ارفع تسجيل صوتي قصير (جملة أو جملتين) للتجربة"),
                "lipsync": ("video", "ارفع فيديو فيه وجه + تسجيل صوتي للتجربة")}
OUT_EXT = {"image": ".png", "upscale": ".png", "bgremove": ".png", "voice": ".mp3", "music": ".mp3", "sfx": ".mp3", "lipsync": ".mp4"}
IN_NAMES = ("image", "audio", "video")
MAX_TEXT = 500


class TryError(Exception):
    """رسالة عربية جاهزة للعرض."""


def root() -> Path:
    return Path(config.LIBRARY_DIR) / "model_tests"


def test_dir(model_id: str) -> Path:
    if not model_library.ID_RX.fullmatch(str(model_id or "")):
        raise TryError("معرّف النموذج غير صالح")
    return root() / model_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_params(raw) -> dict:
    """مدخلات التجربة النصية: prompt/text/language نصوص ≤ 500، seconds رقم 0.5–120."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k in ("prompt", "text", "language"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            if "\x00" in v or len(v.strip()) > MAX_TEXT:
                raise TryError(f"{k}: أطول من {MAX_TEXT} حرف")
            out[k] = v.strip()
    if raw.get("seconds") not in (None, ""):
        try:
            sec = float(raw["seconds"])
        except (TypeError, ValueError):
            raise TryError("المدة: لازم رقم") from None
        if not 0.5 <= sec <= 120:
            raise TryError("المدة: بين 0.5 و120 ثانية")
        out["seconds"] = sec
    return out


def save_params(model_id: str, raw) -> dict:
    d = test_dir(model_id)
    d.mkdir(parents=True, exist_ok=True)
    p = clean_params(raw)
    (d / "params.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return p


def input_path(model_id: str, name: str) -> Path | None:
    d = test_dir(model_id) / "in"
    if name not in IN_NAMES or not d.is_dir():
        return None
    return next((f for f in sorted(d.glob(f"{name}.*")) if f.is_file()), None)


def sample_image(path: Path) -> Path:
    """صورة عيّنة بسيطة (خلفية متدرّجة + «عبوة» ملوّنة) لتجربة التكبير وتفريغ الخلفية — بلا ملف مرفق بالمستودع."""
    from PIL import Image, ImageDraw
    w, h = 256, 384
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (220 - y // 6, 225 - x // 8, 235 - y // 10)
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((88, 130, 168, 310), radius=14, fill=(190, 40, 60), outline=(255, 255, 255), width=3)
    dr.rectangle((106, 96, 150, 134), fill=(235, 235, 235))
    dr.ellipse((100, 190, 156, 246), fill=(255, 220, 120))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG")
    return path


def _request(model: dict, d: Path, params: dict) -> model_run.RunRequest:
    task = model["task"]
    sample = SAMPLES.get(task, {})
    p = {**sample, **params}
    out = d / f"result{OUT_EXT[task]}" if task in OUT_EXT else None
    req = model_run.RunRequest(task=task, out=out, record=False, script_stem="_try", language=p.get("language"), seconds=p.get("seconds"))
    if task in ("image", "music", "sfx"):
        req.prompt = p.get("prompt", "")
    if task == "voice":
        req.text = p.get("text", "")
    if task in ("upscale", "bgremove"):
        req.image = input_path(model["id"], "image") or sample_image(d / "sample.png")
    if task == "image" and input_path(model["id"], "image"):
        req.refs = [input_path(model["id"], "image")]                # صورة مرجعية للتعديل (لو النموذج بيقبل)
    if task in NEEDS_UPLOAD:
        need, why = NEEDS_UPLOAD[task]
        req.audio = input_path(model["id"], "audio")
        req.video = input_path(model["id"], "video")
        if task == "stt" and not req.audio:
            raise TryError(why)
        if task == "lipsync" and not (req.video and req.audio):
            raise TryError(why)
    return req


def run_try(model_id: str, log=print) -> dict:
    """يشغّل التجربة ويكتب last.json. بيرمي TryError بسبب مفهوم (مش موجود/رخصة/ناقص مدخل/وقع النموذج)."""
    m = model_library.get(model_id)
    if not m:
        raise TryError("النموذج مش موجود")
    ok, why = model_library.licence_gate(m)
    if not ok:
        raise TryError(f"«{m['name']}»: {why}")
    d = test_dir(model_id)
    d.mkdir(parents=True, exist_ok=True)
    for old in list(d.glob("result.*")) + [d / "last.json"]:
        old.unlink(missing_ok=True)                                  # ما نعرض ناتج قديم مكان تجربة فاشلة
    try:
        params = json.loads((d / "params.json").read_text(encoding="utf-8")) if (d / "params.json").is_file() else {}
    except (OSError, ValueError):
        params = {}
    req = _request(m, d, params)
    req.log = log
    last = {"at": _now(), "task": m["task"], "model": m["name"]}
    t0 = time.monotonic()
    try:
        res = model_run.run({**m, "enabled": True}, req)             # التجربة قبل التفعيل (بوابة الرخصة فوق بتضل)
    except model_run.RunError as e:
        last.update(ok=False, reason=e.reason, message=str(e), seconds=round(time.monotonic() - t0, 1))
        (d / "last.json").write_text(json.dumps(last, ensure_ascii=False), encoding="utf-8")
        raise TryError(str(e)) from None
    last.update(ok=True, seconds=res.seconds, kind=res.kind, file=res.path.name if res.path else None, info=res.info)
    if m["task"] == "stt":
        w = res.data.get("words") or []
        last["data"] = {"text": str(res.data.get("text") or "")[:2000], "language": res.data.get("language") or "", "words": len(w),
                        "word_timing": bool(w), "segments": len(res.data.get("segments") or [])}
    (d / "last.json").write_text(json.dumps(last, ensure_ascii=False), encoding="utf-8")
    return last


def last_result(model_id: str) -> dict | None:
    try:
        return json.loads((test_dir(model_id) / "last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TryError):
        return None


def result_file(model_id: str) -> Path | None:
    last = last_result(model_id)
    if not last or not last.get("ok") or not last.get("file"):
        return None
    f = test_dir(model_id) / Path(last["file"]).name
    return f if f.is_file() else None


def clear(model_id: str) -> None:
    shutil.rmtree(test_dir(model_id), ignore_errors=True)


def main() -> None:
    import argparse
    import job_signals
    job_signals.install()
    ap = argparse.ArgumentParser(description="جرّب نموذج من مكتبة النماذج")
    ap.add_argument("action", choices=["try"])
    ap.add_argument("model_id")
    a = ap.parse_args()
    log = lambda m: print(m, flush=True)                              # noqa: E731
    try:
        last = run_try(a.model_id, log=log)
    except TryError as e:
        sys.exit(f"[!] {e}")
    log(f"[✓] {last['model']} — {last['seconds']} ثانية")


if __name__ == "__main__":
    main()
