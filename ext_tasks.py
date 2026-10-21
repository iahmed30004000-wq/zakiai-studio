"""
طابور المهام الموحّد للإضافة متعددة المواقع (راجع ext_contract.md الفقرات 1 و2 و3).

  · بناء المهام لكل نوع: voice (محطة 4) · image (محطة 7) · video (محطة 9) · ahat وmusic (طلبات المالك).
  · طلبات الآهات والموسيقى بملف library/studio/<stem>/ext_requests.json (إضافة/حذف/حالة).
  · الإعادة (retry) وتعديل البرومبت بملف library/studio/<stem>/ext_overrides.json.
  · استقبال النتائج بكل نوع وتحديث مكانها بالاستوديو، بدون تخطّي أي شرط بدء محطة (can_start).

قواعد ثابتة:
  · الصوت: التوقيت بعد التنزيل بـ stt، وإذا فشل أو ما في مفتاح فتقدير تقريبي ظاهر (timing_source=estimated).
  · بوابة المدة بعد اكتمال كل المشاهد: داخل النطاق ← المحطة 4 بتنتظر سمع المالك، خارجه ← المحطة 4 failed
    والمالك بيقرر (ما في تعديل نص تلقائي هون).
  · الموسيقى دايماً بلا غناء، والآهات/الموسيقى بتدخل المكتبة غير معتمدة وبتنتظر سمع المالك.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import ext_bridge
import ext_config
import studio_state
import timeline
from ext_bridge import ExtError

AHAT_SUFFIX = "clean, isolated sound effect, no music"
MUSIC_SUFFIX = "instrumental, no vocals, no lyrics — بلا غناء ولا كلام"
REQUEST_KINDS = ("ahat", "music")
MAX_AUDIO_BYTES = 60 * 1024 * 1024
MAX_VIDEO_BYTES = 400 * 1024 * 1024
MAX_REQUESTS = 60
MAX_PROMPT = 4000
MAX_REQUEST_PROMPT = 1000
MIN_AUDIO_SEC = 0.3
SECONDS_RANGE = {"ahat": (0.5, 30.0), "music": (5.0, 300.0)}
SECONDS_DEFAULT = {"ahat": 2.0, "music": 30.0}
DRIFT_WARN = 0.6                                                   # نفس عتبة generate_voice

# وسم الإحساس بالعربي (مقابل مفاتيح tts.emotion_tag الإنجليزية)
EMOTION_AR = {"curious": "فضولي", "excited": "متحمس", "empathetic": "متعاطف",
              "confident": "واثق", "urgent": "مستعجل", "warm": "دافئ"}
# ترتيب تفضيل المواقع لكل نوع (بس لاقتراح site_hint)
PREFERENCE = {"voice": ("elevenlabs", "aistudio"), "image": ("chatgpt", "gemini", "aistudio", "flow"),
              "video": ("flow",), "ahat": ("elevenlabs", "flow"), "music": ("flowmusic", "elevenlabs")}
_AUDIO_IN = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".webm", ".flac", ".aac", ".mp4"}
_VIDEO_IN = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── ملفات الحالة ────────────────────────────────────────────────────────
def _dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "studio" / stem


def _load_json(p: Path, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return default


def _dump_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def requests_path(stem: str) -> Path:
    return _dir(stem) / "ext_requests.json"


def overrides_path(stem: str) -> Path:
    return _dir(stem) / "ext_overrides.json"


# ── طلبات الآهات والموسيقى ──────────────────────────────────────────────
def _requests(stem: str) -> list[dict]:
    d = _load_json(requests_path(stem), {"requests": []})
    r = d.get("requests") if isinstance(d, dict) else None
    return r if isinstance(r, list) else []


def _save_requests(stem: str, rows: list[dict]) -> None:
    _dump_json(requests_path(stem), {"requests": rows})


def list_requests(stem: str) -> list[dict]:
    return _requests(stem)


def _norm_id(rid: str) -> str:
    rid = str(rid or "").strip()
    return f"req_{int(rid):03d}" if rid.isdigit() else rid


def add_request(stem: str, kind: str, prompt: str, name: str = "", mood: str = "any", seconds=None) -> dict:
    import ahat
    if kind not in REQUEST_KINDS:
        raise ExtError("النوع: ahat (آهة/مؤثر) أو music (موسيقى)")
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ExtError("اكتب وصف المطلوب")
    if len(prompt) > MAX_REQUEST_PROMPT:
        raise ExtError(f"الوصف أطول من {MAX_REQUEST_PROMPT} حرف")
    mood = mood or "any"
    if mood not in ahat.MOODS:
        raise ExtError("مزاج غير معروف: " + " أو ".join(ahat.MOODS))
    lo, hi = SECONDS_RANGE[kind]
    if seconds in (None, ""):
        seconds = SECONDS_DEFAULT[kind]
    try:
        seconds = round(float(seconds), 1)
    except (TypeError, ValueError):
        raise ExtError("المدة لازم رقم بالثواني")
    if not lo <= seconds <= hi:
        raise ExtError(f"المدة لهالنوع بين {lo:g} و{hi:g} ثانية")
    name = str(name or "").strip()[:80] or prompt[:40]
    rows = _requests(stem)
    if sum(1 for r in rows if r.get("status") == "pending") >= MAX_REQUESTS:
        raise ExtError(f"عندك {MAX_REQUESTS} طلب معلّق — خلّص أو احذف منهم أول")
    nums = [int(m.group(1)) for r in rows if (m := re.fullmatch(r"req_(\d+)", str(r.get("id", ""))))]
    row = {"id": f"req_{(max(nums) + 1 if nums else 1):03d}", "kind": kind, "prompt": prompt, "name": name,
           "mood": mood, "seconds": seconds, "status": "pending", "track_id": None, "site": None,
           "created_at": _now(), "done_at": None}
    rows.append(row)
    _save_requests(stem, rows)
    return row


def delete_request(stem: str, rid: str) -> None:
    rid = _norm_id(rid)
    rows = _requests(stem)
    if not any(r.get("id") == rid for r in rows):
        raise ExtError("الطلب غير موجود")
    _save_requests(stem, [r for r in rows if r.get("id") != rid])
    for kind in REQUEST_KINDS:
        _clear_retry(stem, kind, rid)


# ── علامات الإعادة (retry) وتعديل البرومبت ──────────────────────────────
def _marks(stem: str) -> dict:
    d = _load_json(overrides_path(stem), {"retry": {}})
    r = d.get("retry") if isinstance(d, dict) else None
    return r if isinstance(r, dict) else {}


def _set_retry(stem: str, kind: str, task_id: str, prompt: str | None) -> None:
    m = _marks(stem)
    m[f"{kind}:{task_id}"] = {"prompt": prompt or None, "at": _now()}
    _dump_json(overrides_path(stem), {"retry": m})


def _clear_retry(stem: str, kind: str, task_id: str) -> None:
    m = _marks(stem)
    if m.pop(f"{kind}:{task_id}", None) is not None:
        _dump_json(overrides_path(stem), {"retry": m})


# ── بناء المهام ─────────────────────────────────────────────────────────
def _site_hint(kind: str, ctl: dict) -> str | None:
    cfg = ext_config.load()["sites"]
    cur = ctl.get("site")
    if cur and kind in (cfg.get(cur) or {}).get("kinds", {}):
        return cur
    for s in PREFERENCE.get(kind, ()):
        if kind in (cfg.get(s) or {}).get("kinds", {}):
            return s
    return None


def _task(kind: str, task_id: str, ctl: dict, *, scene=None, shot_id=None, prompt="", text="", emotion_tag="",
          seconds=0.0, want=1, refs=None, retry=False) -> dict:
    return {"task_id": task_id, "kind": kind, "scene": scene, "shot_id": shot_id, "prompt": prompt, "text": text,
            "emotion_tag": emotion_tag, "seconds": round(float(seconds or 0), 3), "want": want,
            "refs": refs or [], "site_hint": None, "retry": bool(retry)}


def _read_script(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ExtError("ملف السيناريو تالف أو غير موجود")


def _emotion_tag(sc: dict) -> str:
    import tts
    key = tts.emotion_tag(sc.get("emotion"))
    return f"[{EMOTION_AR[key]}]" if key in EMOTION_AR else ""


def _voice_dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "voice" / stem


def _voice_ready(path: Path) -> None:
    """شروط بدء الصوت: سيناريو معتمد المراجعة + محطة 4 مسموح تبدأ. بدون تخطّي أي شي."""
    import review_loop
    ok, why = review_loop.is_cleared(path)
    if not ok:
        raise ExtError(why)
    try:
        studio_state.derive_early(path.stem, path)                   # نفس اللي بتعمله الواجهة بكل فتح
    except Exception:
        pass
    ok, why = studio_state.can_start(path.stem, 4)
    if not ok:
        raise ExtError(why)


def _voice_tasks(path: Path, ctl: dict, marks: dict) -> list[dict]:
    import voice_studio
    stem = path.stem
    _voice_ready(path)
    script = _read_script(path)
    man = voice_studio.load_manifest(stem) or {}
    by = {s.get("scene"): s for s in man.get("scenes", [])}
    inherited = {n for n in (man.get("inherited") or []) if isinstance(n, int)}      # نسخة هوك: صوت موروث من الأساسي
    lib = Path(config.LIBRARY_DIR)
    out = []
    for sc in script.get("scenes", []):
        n = sc.get("scene_number")
        text = (sc.get("voiceover") or "").strip()
        if not text or not isinstance(n, int):
            continue
        tid = f"scene_{n}"
        mark = marks.get(f"voice:{tid}")
        e = by.get(n)
        have = bool(e and str(e.get("provider", "")).startswith("extension:")
                    and str(e.get("text", "")).strip() == text and (lib / str(e.get("path", ""))).is_file())
        if n in inherited and not mark and e and str(e.get("text", "")).strip() == text and (lib / str(e.get("path", ""))).is_file():
            have = True
        if have and not mark:
            continue
        tag = _emotion_tag(sc)
        prompt = (mark or {}).get("prompt") or (f"{tag} {text}" if tag else text)
        out.append(_task("voice", tid, ctl, scene=n, prompt=prompt, text=text, emotion_tag=tag,
                         seconds=sc.get("duration_sec") or 0, retry=bool(mark)))
    return sorted(out, key=lambda t: t["scene"])


def _image_tasks(path: Path, ctl: dict, marks: dict) -> list[dict]:
    import image_studio
    stem = path.stem
    base = {q["shot_id"]: q for q in ext_bridge.build_queue(path)}        # بيرمي ExtError لو المحطة 6 مش معتمدة
    tl = timeline.load(stem)
    script = _read_script(path)
    code = image_studio.product_code(script)
    out = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            sid = sh["id"]
            mark = marks.get(f"image:{sid}")
            q = base.get(sid)
            if not q and not mark:
                continue
            dur = (sh["end_ms"] - sh["start_ms"]) / 1000
            if q:
                prompt, want, refs = q["prompt"], q["want"], q["refs"]
            else:                                                     # إعادة لقطة عندها خيارات كفاية
                prompt = (sh.get("prompt_model") or sh.get("prompt_ar") or "").strip()
                if not prompt:
                    continue
                refs = [{"index": i, "name": r.name} for i, r in enumerate(ext_bridge._refs(stem, sh, code))]
                want = 1
            if mark and mark.get("prompt"):
                prompt = mark["prompt"]
            out.append(_task("image", sid, ctl, scene=sc["n"], shot_id=sid, prompt=prompt, seconds=dur, want=want,
                             refs=refs, retry=bool(mark)))
    return out


def _video_tasks(path: Path, ctl: dict, marks: dict) -> list[dict]:
    import characters
    import image_studio
    import motion
    stem = path.stem
    ok, why = studio_state.can_start(stem, 9)                         # لازم فحص التطابق (محطة 8) معتمد
    if not ok:
        raise ExtError(why)
    tl = timeline.load(stem)
    if not tl:
        raise ExtError("ما في خط زمني")
    cur = characters.chosen(stem)
    ch = characters.get(cur["character_id"]) if cur else None
    out = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            mark = marks.get(f"video:{sh['id']}")
            rel = motion._final_image(sh)
            if not rel or not image_studio.abs_of(stem, rel):
                continue                                              # بلا صورة نهائية معتمدة
            if sh.get("motion_candidates") and not mark:
                continue
            dur_ms = sh["end_ms"] - sh["start_ms"]
            if mark and mark.get("prompt"):
                prompt = mark["prompt"]
            else:
                try:
                    prompt = motion.build_prompt(sh, sc, ch, dur_ms)
                except motion.MotionError as e:
                    raise ExtError(f"لقطة {sh['id']}: {e}")
            out.append(_task("video", sh["id"], ctl, scene=sc["n"], shot_id=sh["id"], prompt=prompt,
                             seconds=dur_ms / 1000, refs=[{"index": 0, "name": Path(rel).name}], retry=bool(mark)))
    return out


def _with_suffix(prompt: str, kind: str) -> str:
    suffix = MUSIC_SUFFIX if kind == "music" else AHAT_SUFFIX
    return f"{prompt.strip().rstrip('.،؛;:')}. {suffix}"


def _request_tasks(kind: str):
    def build(path: Path, ctl: dict, marks: dict) -> list[dict]:
        out = []
        for r in _requests(path.stem):
            if r.get("kind") != kind or r.get("status") != "pending":
                continue
            out.append(_task(kind, r["id"], ctl, prompt=_with_suffix(r["prompt"], kind), seconds=r.get("seconds") or 0,
                             retry=f"{kind}:{r['id']}" in marks))
        return out
    return build


_BUILDERS = {"voice": _voice_tasks, "image": _image_tasks, "video": _video_tasks,
             "ahat": _request_tasks("ahat"), "music": _request_tasks("music")}


def tasks(script_path, kind: str, apply_only: bool = True) -> list[dict]:
    """المهام المعلّقة لنوع. apply_only=True بيحترم control.only (قائمة task_id)."""
    if kind not in ext_bridge.KINDS:
        raise ExtError("النوع: " + " أو ".join(ext_bridge.KINDS))
    path = Path(script_path)
    ctl = ext_bridge.control(path.stem)
    out = _BUILDERS[kind](path, ctl, _marks(path.stem))
    hint = _site_hint(kind, ctl)
    for t in out:
        t["site_hint"] = hint
    only = ctl.get("only")
    if apply_only and only:
        keep = set(only)
        out = [t for t in out if t["task_id"] in keep]
    return out


def counts(script_path) -> tuple[dict, dict]:
    """({kind: عدد المعلّق}, {kind: سبب الحجب}) — للوحة الحالة."""
    n, blocked = {}, {}
    for kind in ext_bridge.KINDS:
        try:
            n[kind] = len(tasks(script_path, kind, apply_only=False))
        except ExtError as e:
            n[kind], blocked[kind] = 0, str(e)
    return n, blocked


def asset_path(script_path, kind: str, task_id: str, index: int) -> Path:
    """ملف مرفق مهمة: مراجع الصور (image) أو الصورة النهائية للتحريك (video، index 0)."""
    path = Path(script_path)
    if kind == "image":
        return ext_bridge.ref_path(path, task_id, index)
    if kind == "video":
        import image_studio
        import motion
        stem = path.stem
        try:
            tl = motion._load(stem)
            _sc, sh = motion._shot(tl, task_id)
        except motion.MotionError as e:
            raise ExtError(str(e))
        rel = motion._final_image(sh)
        p = image_studio.abs_of(stem, rel) if rel else None
        if index != 0 or not p:
            raise ExtError("مرجع غير موجود")
        return p
    raise ExtError("هالنوع ما إله مرفقات")


# ── استقبال النتائج: مساعدات ────────────────────────────────────────────
def _check_blob(data: bytes, limit: int, what: str) -> None:
    if not data:
        raise ExtError(f"ملف {what} فاضي")
    if len(data) > limit:
        raise ExtError(f"ملف {what} كبير كتير (الحد {limit // (1024 * 1024)}MB)")


def _convert_audio(data: bytes, filename: str, dest: Path) -> float:
    """أي صوت ← mp3 بـ ffmpeg. بيرجّع المدة بالثواني، وبيرمي ExtError لو الملف مش صوت صالح."""
    import tts
    ext = Path(filename or "").suffix.lower()
    ext = ext if ext in _AUDIO_IN else ".bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_name(dest.name + ".raw" + ext)
    raw.write_bytes(data)
    try:
        r = subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-vn", "-codec:a", "libmp3lame", "-q:a", "3",
                            "-f", "mp3", str(dest)], capture_output=True, timeout=300)
    except FileNotFoundError:
        dest.unlink(missing_ok=True)
        raise ExtError("ffmpeg غير مثبّت على الجهاز")
    except subprocess.TimeoutExpired:
        dest.unlink(missing_ok=True)
        raise ExtError("تحويل الصوت أخد وقت أكتر من اللازم")
    finally:
        raw.unlink(missing_ok=True)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 200:
        dest.unlink(missing_ok=True)
        raise ExtError("الملف مش صوت صالح")
    dur = tts.audio_duration(dest)
    if dur < MIN_AUDIO_SEC:
        dest.unlink(missing_ok=True)
        raise ExtError("الملف الصوتي قصير كتير — غالباً مش النتيجة الكاملة")
    return dur


def align_to_script(asr: list[dict], text: str, duration: float) -> list[dict]:
    """كلمات النص الأصلي (اللي بتظهر بالترجمة) بتوقيت التفريغ الصوتي.
    التفريغ ممكن يكتب الكلمة غير شكل (تشكيل/همزة/دمج كلمتين)، فبنربط بالترتيب: كل كلمة من النص بتاخد
    مجال الكلمات المقابلة إلها من التفريغ بالنسبة (أكتر من واحدة إذا التفريغ فيه كلمات أكتر)."""
    toks = text.split()
    m, n = len(asr), len(toks)
    if not toks or not m:
        return []
    out = []
    for i, tok in enumerate(toks):
        lo = i * m // n
        hi = max(lo, -(-(i + 1) * m // n) - 1)              # سقف القسمة
        st = float(asr[lo]["start"])
        en = float(asr[min(hi, m - 1)]["end"])
        st = min(max(st, 0.0), duration)
        en = min(max(en, st), duration)
        out.append({"text": tok, "start": round(st, 3), "end": round(en, 3)})
    for a, b in zip(out, out[1:]):                           # ما يتداخلوا: نهاية الكلمة ≤ بداية اللي بعدها
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    return out


def _words(mp3: Path, text: str, duration: float) -> tuple[list[dict], str]:
    """كلمات بتوقيتها: التفريغ الصوتي أولاً، وإذا فشل أو ما في مفتاح ← تقدير بنسبة طول الكلمة."""
    import tts
    try:
        import stt
        res = stt.transcribe(mp3)
        if res.get("words"):                                  # توقيت كل كلمة (Whisper المحلي)
            aligned = align_to_script(res["words"], text, duration)
            if aligned:
                return aligned, "stt"
        words = []
        for seg in res.get("segments", []):
            s, e = float(seg["start"]), float(seg["end"])
            toks = " ".join(str(seg.get("text", "")).split())
            for w in tts.estimate_words(toks, max(e - s, 0.01)):
                st = min(s + w["start"], duration)
                words.append({"text": w["text"], "start": round(st, 3), "end": round(min(max(s + w["end"], st), duration), 3)})
        if words:
            return words, "stt"
    except Exception:
        pass
    return tts.estimate_words(text, duration), "estimated"


def _concat(files: list[Path], out: Path) -> bool:
    """دمج المقاطع: نسخ مباشر، وإذا فشل (مواصفات مختلفة) إعادة ترميز."""
    import generate_voice
    if generate_voice.concat(files, out):
        return True
    listing = out.parent / "_concat2.txt"
    listing.write_text("\n".join(f"file '{f.name}'" for f in files), encoding="utf-8")
    try:
        r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-codec:a", "libmp3lame",
                            "-q:a", "3", str(out)], cwd=str(out.parent), capture_output=True, timeout=600)
        return r.returncode == 0 and out.exists()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    finally:
        listing.unlink(missing_ok=True)


# ── استقبال الصوت ───────────────────────────────────────────────────────
def _receive_voice(path: Path, task_id: str, data: bytes, site: str, filename: str) -> dict:
    import generate_voice
    import voice_studio
    stem = path.stem
    m = re.fullmatch(r"scene_(\d+)", task_id or "")
    if not m:
        raise ExtError("معرّف مهمة الصوت لازم يكون scene_<رقم المشهد>")
    n = int(m.group(1))
    script = _read_script(path)
    scenes = [s for s in script.get("scenes", []) if (s.get("voiceover") or "").strip()]
    sc = next((s for s in scenes if s.get("scene_number") == n), None)
    if not sc:
        raise ExtError(f"مشهد {n} مش موجود أو بلا كلام")
    _voice_ready(path)
    _check_blob(data, MAX_AUDIO_BYTES, "الصوت")
    text = sc["voiceover"].strip()
    out_dir = _voice_dir(stem)
    target = out_dir / f"scene_{n:02d}.mp3"
    staging = out_dir / f"scene_{n:02d}.new.mp3"
    dur = _convert_audio(data, filename, staging)
    try:
        studio_state.set_state(stem, 4, "running", f"وصل صوت مشهد {n} من الإضافة")
    except studio_state.StationBlocked as e:
        staging.unlink(missing_ok=True)
        raise ExtError(str(e))
    os.replace(staging, target)

    words, src = _words(target, text, dur)
    planned = float(sc.get("duration_sec") or 0)
    entry = {"path": generate_voice._rel(target), "duration_sec": dur, "provider": f"extension:{site}",
             "model": "web", "voice": "web", "words": words, "timing_source": src, "scene": n,
             "planned_sec": planned, "drift_sec": round(dur - planned, 2), "text": text,
             "emotion_tag": _emotion_tag(sc)}

    old = voice_studio.load_manifest(stem) or {}
    by = {s["scene"]: s for s in old.get("scenes", []) if isinstance(s.get("scene"), int)}
    by[n] = entry
    need = {s["scene_number"]: s["voiceover"].strip() for s in scenes}
    mscenes = sorted((s for k, s in by.items() if k in need), key=lambda s: s["scene"])
    lib = Path(config.LIBRARY_DIR)
    complete = all(k in by and str(by[k].get("text", "")).strip() == need[k] and (lib / by[k]["path"]).is_file()
                   for k in need)
    combined = None
    if complete:
        full = out_dir / "full.mp3"
        if _concat([out_dir / Path(s["path"]).name for s in mscenes], full):
            combined = {"path": generate_voice._rel(full), "duration_sec": _duration(full)}
    total_actual = round(sum(s["duration_sec"] for s in mscenes), 2)
    total_planned = round(sum(s.get("planned_sec", 0) for s in mscenes), 2)
    providers = {s.get("provider") for s in mscenes}
    manifest = {
        "script": path.name, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": providers.pop() if len(providers) == 1 else "mixed", "model": "web", "voice": "web",
        "scenes": mscenes, "total_actual_sec": total_actual, "total_planned_sec": total_planned,
        "total_drift_sec": round(total_actual - total_planned, 2),
        "scenes_off": [s["scene"] for s in mscenes if abs(s.get("drift_sec", 0)) > DRIFT_WARN],
        "combined": combined,
    }
    if old.get("inherited"):
        manifest["inherited"] = old["inherited"]                      # الموروث بيضل معلّم (بتتحقق منه _voice_tasks كل مرة)
    _dump_json(out_dir / "voice.json", manifest)

    gate = None
    if complete:
        gate = voice_studio.check_duration(total_actual)
        if gate["ok"]:
            studio_state.set_state(stem, 4, "awaiting_choice", "بانتظار اعتماد المالك سمعياً — " + gate["message"])
        else:
            studio_state.set_state(stem, 4, "failed", gate["message"] + " — القرار عندك: عدّل نص السيناريو أو أعد توليد مشاهد من الإضافة")
    else:
        have = sum(1 for k in need if k in by and str(by[k].get("text", "")).strip() == need[k])
        studio_state.set_state(stem, 4, "running", f"وصل صوت {have} من {len(need)} مشاهد")
    return {"kind": "voice", "scene": n, "duration_sec": dur, "timing_source": src, "complete": complete,
            "gate": gate, "total_sec": total_actual}


def _duration(p: Path) -> float:
    import tts
    return tts.audio_duration(p)


# ── استقبال الفيديو ─────────────────────────────────────────────────────
def _receive_video(path: Path, task_id: str, data: bytes, site: str, filename: str) -> dict:
    import image_studio
    import motion
    stem = path.stem
    ok, why = studio_state.can_start(stem, 9)
    if not ok:
        raise ExtError(why)
    _check_blob(data, MAX_VIDEO_BYTES, "الفيديو")
    try:
        tl = motion._load(stem)
        _sc, sh = motion._shot(tl, task_id)
    except motion.MotionError as e:
        raise ExtError(str(e))
    rel = motion._final_image(sh)
    if not rel or not image_studio.abs_of(stem, rel):
        raise ExtError(f"لقطة {task_id}: ما في صورة معتمدة")
    dur_ms = sh["end_ms"] - sh["start_ms"]
    out_dir = motion.clips_dir(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "").suffix.lower()
    ext = ext if ext in _VIDEO_IN else ".mp4"
    stamp = int(time.time() * 1000)
    raw = out_dir / f"{task_id}_{stamp}_ext_raw{ext}"
    final = out_dir / f"{task_id}_{stamp}_ext.mp4"
    raw.write_bytes(data)
    try:
        fit = motion.fit_duration(raw, final, dur_ms)                 # مدة الحركة = مدة اللقطة بالضبط
    except motion.MotionError as e:
        final.unlink(missing_ok=True)
        raise ExtError(str(e).replace("الموديل", "الموقع"))
    finally:
        raw.unlink(missing_ok=True)
    try:
        studio_state.set_state(stem, 9, "running", f"وصلت حركة {task_id} من الإضافة")
    except studio_state.StationBlocked as e:
        final.unlink(missing_ok=True)
        raise ExtError(str(e))

    mark = _marks(stem).get(f"video:{task_id}") or {}
    tl = motion._load(stem)
    sc, sh = motion._shot(tl, task_id)
    if mark.get("prompt"):
        sh["motion_prompt"] = mark["prompt"]
    elif not sh.get("motion_prompt"):
        try:
            import characters
            cur = characters.chosen(stem)
            sh["motion_prompt"] = motion.build_prompt(sh, sc, characters.get(cur["character_id"]) if cur else None, dur_ms)
        except Exception:
            pass
    sh.setdefault("motion_candidates", []).append({
        "clip": motion._rel(stem, final), "model_id": f"ext:{site}", "model_name": f"{ext_config.site_label(site)} (الإضافة)",
        "duration_ms": dur_ms, "fit": fit["how"], "source_sec": fit["source_sec"], "lipsync": False, "took_sec": 0.0,
        "at": _now()})
    timeline.save(stem, tl)
    left = tasks(path, "video", apply_only=False)
    if not left:
        studio_state.set_state(stem, 9, "awaiting_choice", "بانتظار اختيارك لحركة كل لقطة")
    ext_bridge.append_log(stem, {"step": "result", "shot": task_id, "msg": f"وصلت حركة {dur_ms / 1000:.1f}ث من {site} ({fit['how']})"})
    return {"kind": "video", "shot": task_id, "duration_ms": dur_ms, "fit": fit["how"], "left": len(left)}


# ── استقبال الآهات والموسيقى ────────────────────────────────────────────
def _receive_request(path: Path, kind: str, task_id: str, data: bytes, site: str, filename: str) -> dict:
    import ahat
    stem = path.stem
    rows = _requests(stem)
    r = next((x for x in rows if x.get("id") == task_id and x.get("kind") == kind), None)
    if not r:
        raise ExtError("الطلب غير موجود")
    if r.get("status") != "pending":
        raise ExtError("هالطلب خلص من قبل — أعد المحاولة منه إذا بدك نسخة تانية")
    _check_blob(data, MAX_AUDIO_BYTES, "الصوت")
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "x.mp3"
        dur = _convert_audio(data, filename, mp3)
        blob = mp3.read_bytes()
    try:
        t = ahat.add(r.get("name") or r["prompt"][:40], r.get("mood") or "any", "ext.mp3", blob)
    except ahat.AhatError as e:
        raise ExtError(str(e))
    t.update(source=f"extension:{site}", kind=kind, request_id=task_id, from_script=stem)
    ahat._write(t)                                                   # غير معتمدة: بتنتظر سمع المالك
    r.update(status="done", track_id=t["id"], site=site, done_at=_now())
    _save_requests(stem, rows)
    ext_bridge.append_log(stem, {"step": "result", "shot": task_id, "msg": f"وصل {'موسيقى' if kind == 'music' else 'مؤثر'} {dur:.1f}ث من {site}"})
    return {"kind": kind, "request": task_id, "track_id": t["id"], "duration_sec": t["duration_sec"], "approved": False}


# ── نقطة الاستقبال الموحّدة ─────────────────────────────────────────────
def receive(script_path, kind: str, task_id: str, data: bytes, site: str, filename: str = "") -> dict:
    """نتيجة رجعت من الإضافة ← مكانها بالاستوديو. بيرجّع {done, ...}. وضع «لقطة لقطة» بيوقف بعد النجاح."""
    path = Path(script_path)
    stem = path.stem
    if kind not in ext_bridge.KINDS:
        raise ExtError("النوع: " + " أو ".join(ext_bridge.KINDS))
    if site not in ext_bridge.SITES:
        raise ExtError("موقع غير معروف")
    task_id = str(task_id or "").strip()
    if not task_id:
        raise ExtError("معرّف المهمة (task_id) مطلوب")
    try:
        if kind == "image":
            out = ext_bridge.add_candidate(path, task_id, data, site)
            ext_bridge.finish_if_done(path)                          # كل الطابور خلص ← المحطة 7 بتنتظر اختيارك
        elif kind == "voice":
            out = _receive_voice(path, task_id, data, site, filename)
        elif kind == "video":
            out = _receive_video(path, task_id, data, site, filename)
        else:
            out = _receive_request(path, kind, task_id, data, site, filename)
    except ExtError as e:
        _log_attempt(kind, "failed", stem, task_id, site, str(e))
        raise
    _log_attempt(kind, "ok", stem, task_id, site)
    _clear_retry(stem, kind, task_id)
    ext_bridge.review_pause(stem)
    out["done"] = _finish(path, kind)
    return out


def _log_attempt(kind: str, status: str, stem: str, task_id: str, site: str, error=None) -> None:
    """سجل الإنتاج: كل نتيجة من الإضافة (الزمن مجهول: الإضافة بتشتغل بحسابات المالك)."""
    import production_log
    production_log.record("motion" if kind == "video" else kind, status, script_stem=stem, shot_id=task_id,
                          model_id=f"ext:{site}", model_name=site,
                          path="extension", error=error)


def _finish(path: Path, kind: str) -> bool:
    """ما بقي مهام ضمن النطاق المطلوب (only) ← الأمر idle والنطاق بيتصفّر."""
    try:
        left = tasks(path, kind, apply_only=True)
    except ExtError:
        left = []
    if left:
        return False
    ext_bridge.set_control(path.stem, "idle", only=None)
    return True


# ── إعادة لقطة/مشهد ─────────────────────────────────────────────────────
def retry(script_path, task_id: str, kind: str, prompt: str | None = None) -> dict:
    """يجبر مهمة جديدة (want=1) حتى لو عندها خيارات كفاية، ويستبدل البرومبت لو انبعت."""
    path = Path(script_path)
    stem = path.stem
    if kind not in ext_bridge.KINDS:
        raise ExtError("النوع: " + " أو ".join(ext_bridge.KINDS))
    task_id = str(task_id or "").strip()
    if not task_id:
        raise ExtError("معرّف المهمة (task_id) مطلوب")
    prompt = (str(prompt).strip() or None) if prompt is not None else None
    if prompt and len(prompt) > MAX_PROMPT:
        raise ExtError(f"البرومبت أطول من {MAX_PROMPT} حرف")
    if kind in REQUEST_KINDS:
        rows = _requests(stem)
        r = next((x for x in rows if x.get("id") == _norm_id(task_id) and x.get("kind") == kind), None)
        if not r:
            raise ExtError("الطلب غير موجود")
        task_id = r["id"]
        if prompt:
            if len(prompt) > MAX_REQUEST_PROMPT:
                raise ExtError(f"الوصف أطول من {MAX_REQUEST_PROMPT} حرف")
            r["prompt"] = prompt
        r.update(status="pending", done_at=None)
        _save_requests(stem, rows)
        _set_retry(stem, kind, task_id, None)
    else:
        _set_retry(stem, kind, task_id, prompt)
    try:
        found = [t for t in tasks(path, kind, apply_only=False) if t["task_id"] == task_id]
    except ExtError:
        _clear_retry(stem, kind, task_id)
        raise
    if not found:
        _clear_retry(stem, kind, task_id)
        raise ExtError("ما لقيت هالمهمة (لقطة أو مشهد غير موجود، أو ما إلها صورة معتمدة)")
    return found[0]
