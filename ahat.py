"""
مكتبة الآهات — المحطة ١٠ (الصوت).

بلا موسيقى ولا آلات: آهات بشرية فقط. المصدر: مكتبة بيعتمدها المالك **بالسمع**. توليد صوت بشري
كبديل ما هو مبني (ما في مولّد على الجهاز) — فالمكتبة هي المصدر الوحيد.

    library/ahat/<id>/track.json + audio.<ext>

النظام بيطابق مزاج السيناريو ومدته ويرشّح، والمالك بيعتمد. ما في شي بينضم للفيديو بلا اعتماد صريح.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import config

MOODS = {"calm": "هادئ", "warm": "دافئ", "hopeful": "أمل", "tense": "توتر خفيف", "uplift": "انتعاش", "any": "أي مزاج"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
# شعور المشهد ← مزاج الآهات (بنفس أسلوب وسوم الصوت: كلمات مفتاحية، وما في تطابق = ما بنخمّن)
_EMOTION_MOOD = [
    ("tense", r"tens|urgen|pressure|frustrat|pain|worr|عاجل|ضغط|ألم|قلق|إحباط|توتر"),
    ("uplift", r"excit|joy|happy|thrill|حماس|فرح|انتعاش|سعادة|انبهار"),
    ("hopeful", r"hope|relief|curio|confid|trust|أمل|ارتياح|ثقة|فضول"),
    ("warm", r"warm|comfort|empath|دفء|راحة|تعاطف"),
    ("calm", r"calm|هدوء|سكينة"),
]


class AhatError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root() -> Path:
    return Path(config.LIBRARY_DIR) / "ahat"


def _id_ok(tid: str) -> str:
    if not re.fullmatch(r"ah_\d{3}", tid or ""):
        raise AhatError("معرّف غير صالح")
    return tid


def probe_duration(p: Path) -> float:
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                     "default=noprint_wrappers=1:nokey=1", str(p)],
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def _file(tid: str) -> Path:
    return root() / _id_ok(tid) / "track.json"


def get(tid: str) -> dict | None:
    p = _file(tid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _write(t: dict) -> dict:
    p = _file(t["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
    return t


def list_all() -> list[dict]:
    out = []
    for p in sorted(root().glob("ah_*/track.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def add(name: str, mood: str, filename: str, data: bytes) -> dict:
    name = (name or "").strip()
    if not name:
        raise AhatError("اسم المقطع مطلوب")
    if mood not in MOODS:
        raise AhatError("مزاج غير معروف")
    ext = Path(filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise AhatError(f"صيغة غير مدعومة: {ext or 'بدون امتداد'}")
    if len(data) < 500:
        raise AhatError("الملف تالف أو فاضي")
    nums = [int(p.parent.name.split("_")[1]) for p in root().glob("ah_*/track.json")]
    tid = f"ah_{(max(nums) + 1 if nums else 1):03d}"
    d = root() / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / f"audio{ext}").write_bytes(data)
    dur = probe_duration(d / f"audio{ext}")
    if dur <= 0:
        (d / f"audio{ext}").unlink(missing_ok=True)
        d.rmdir()
        raise AhatError("الملف مش صوت صالح")
    return _write({"id": tid, "name": name, "mood": mood, "audio": f"audio{ext}", "duration_sec": round(dur, 2),
                   "approved": False, "approved_at": None, "created_at": _now()})


def audio_path(tid: str) -> Path | None:
    t = get(tid)
    if not t:
        return None
    p = root() / tid / t["audio"]
    return p if p.exists() else None


def approve(tid: str, heard: bool) -> dict:
    """اعتماد المالك بالسمع — لازم إقرار صريح إنه سمعه (المفروض عبر زر بعد تشغيل المقطع)."""
    t = get(tid)
    if not t:
        raise AhatError("المقطع غير موجود")
    if not heard:
        raise AhatError("الاعتماد بالسمع: شغّل المقطع أولاً وأكّد إنك سمعته")
    t["approved"], t["approved_at"] = True, _now()
    return _write(t)


def revoke(tid: str) -> dict:
    t = get(tid)
    if not t:
        raise AhatError("المقطع غير موجود")
    t["approved"], t["approved_at"] = False, None
    return _write(t)


def delete(tid: str) -> None:
    import shutil
    d = root() / _id_ok(tid)
    if not d.exists():
        raise AhatError("المقطع غير موجود")
    shutil.rmtree(d)


def script_mood(tl: dict) -> str | None:
    """المزاج الغالب بمشاعر المشاهد، أو None لو ما تطابق شي."""
    votes: dict[str, int] = {}
    for sc in tl.get("scenes", []):
        for mood, rx in _EMOTION_MOOD:
            if re.search(rx, str(sc.get("emotion") or ""), re.I):
                votes[mood] = votes.get(mood, 0) + 1
                break
    return max(votes, key=lambda k: (votes[k], k)) if votes else None


def suggest(tl: dict, top: int = 3) -> dict:
    """المعتمدة بس. الترتيب: مزاج مطابق ← مدتها قريبة من مدة الفيديو (ما تحتاج تكرار كتير)."""
    mood = script_mood(tl)
    total = tl["voice"]["duration_ms"] / 1000
    out = []
    for t in list_all():
        if not t.get("approved"):
            continue
        score, why = 0, []
        if mood and t["mood"] == mood:
            score += 50; why.append(f"مزاجه {MOODS[t['mood']]} مطابق لمزاج السيناريو")
        elif t["mood"] == "any":
            score += 20; why.append("صالح لأي مزاج")
        elif mood:
            score -= 30; why.append(f"مزاجه {MOODS[t['mood']]} مختلف عن {MOODS[mood]}")
        ratio = t["duration_sec"] / total if total else 0
        if ratio >= 1:
            score += 20; why.append("أطول من الفيديو (بلا تكرار)")
        elif ratio >= 0.5:
            score += 5; why.append("بيتكرر مرة")
        else:
            score -= 10; why.append("قصير: بيتكرر كتير")
        out.append({"track": t, "score": score, "reasons": why})
    out.sort(key=lambda r: (-r["score"], r["track"]["id"]))
    return {"mood": mood, "mood_label": MOODS.get(mood), "suggestions": out[:top],
            "approved_count": sum(1 for t in list_all() if t.get("approved")), "total": len(list_all())}
