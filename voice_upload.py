#!/usr/bin/env python3
"""
صوت المالك: رفع تسجيل ← تفريغ ← قص على المشاهد، وصوت بالذكاء (TTS) لمشاهد المشروع الحر.

    python voice_upload.py ingest  library/scripts/free__X.json --audio rec.m4a [--no-fit] [--mode auto|by_text|by_time|new_scenes] [--language ar]
    python voice_upload.py realign library/scripts/free__X.json [--no-fit] [--mode …]      # إعادة التقسيم من التفريغ المحفوظ (بلا تفريغ جديد)
    python voice_upload.py tts     library/scripts/free__X.json [--all] [--no-fit]        # صوت بالذكاء لمشاهد فيها كلام (بيصرف من مزوّد الصوت)

المشروع الحر (كل مشهد إله ملف صوت خاص فيه، بيمشي مع مشهده لو رتّبت المشاهد):
  · by_text:   المشاهد فيها نص ← بنطابق النص المكتوب مع المسموع (ar_align) وبنقص التسجيل على حدود المشاهد.
  · by_time:   المشاهد بلا نص (صور/فيديوهات بس) ← بنوزّع جمل التسجيل على المشاهد حسب مددها، والجملة بتصير كلام المشهد.
  · new_scenes: مشروع فاضي ← كل جملة (أو مجموعة جمل) بتصير مشهد.
  · fit: مدة لقطات المشهد بتتعدّل لتساوي مدة صوته (الصوت هو الساعة). بلا fit: المدد بتضل، والصوت بيتقصّ أو بيتمدّ بصمت.

المصدر المحوّل (source.wav) والتفريغ (asr.json) بيتحفظوا بـ timelines/<stem>/voice_src، فإعادة التقسيم وتعديل النص بلا تفريغ جديد.
الأزمنة بالثواني داخل التفريغ، وبالميلي ثانية داخل الخط الزمني. بيرمي VoiceUploadError برسائل عربية جاهزة.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import ar_align
import config
import timeline

MAX_SOURCE_SEC = 600.0
MIN_SOURCE_SEC = 0.8
MIN_COVERAGE = 0.5                       # تحت هالنسبة بنحذّر: المسموع بيختلف كتير عن المكتوب
MODES = ("auto", "by_text", "by_time", "new_scenes")
FADE_S = 0.01


class VoiceUploadError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── المسارات ────────────────────────────────────────────────────────────
def lib() -> Path:
    return Path(config.LIBRARY_DIR)


def src_dir(stem: str) -> Path:
    return lib() / "timelines" / stem / "voice_src"


def voice_dir(stem: str) -> Path:
    return lib() / "timelines" / stem / "voice"


def rel(p: Path) -> str:
    return Path(p).resolve().relative_to(lib().resolve()).as_posix()


# ── ffmpeg ──────────────────────────────────────────────────────────────
def _run(cmd: list[str], what: str, timeout: int = 900, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=str(cwd) if cwd else None)
    except FileNotFoundError:
        raise VoiceUploadError("ffmpeg مش مثبّت على الجهاز", 500)
    except subprocess.TimeoutExpired:
        raise VoiceUploadError(f"انتهت المهلة ({what})", 500)
    if r.returncode != 0:
        raise VoiceUploadError(f"فشل {what}: " + (r.stderr or "")[-300:], 400)
    return r.stderr


def duration_of(p: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                             capture_output=True, text=True, check=True).stdout.strip()
        return round(float(out), 3)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def has_audio(p: Path) -> bool:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True, check=True).stdout.strip()
        return out == "audio"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def to_wav(src: Path, dst: Path) -> float:
    """أي صوت أو فيديو فيه صوت ← WAV مونو 48kHz. بيرجّع المدة بالثواني."""
    if not has_audio(src):
        raise VoiceUploadError("الملف ما فيه صوت (جرّب ملف تسجيل صوتي أو فيديو فيه صوتك)")
    d0 = duration_of(src)
    if d0 > MAX_SOURCE_SEC:                                # قبل التحويل: ما منحوّل ساعة صوت وبعدين نرفضها
        raise VoiceUploadError(f"التسجيل أطول من {int(MAX_SOURCE_SEC // 60)} دقايق — قسّمه")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(dst)], "تحويل الصوت")
    d = duration_of(dst)
    if d < MIN_SOURCE_SEC:
        dst.unlink(missing_ok=True)
        raise VoiceUploadError("التسجيل قصير جداً أو فاضي")
    return d


def cut_wav(src: Path, a: float, b: float, dst: Path) -> float:
    """مقطع [a, b] بالثواني من WAV، بتلاشي خفيف (10ms) على الأطراف عشان ما يطلع طقطقة. بيرجّع مدته."""
    d = max(0.05, float(b) - float(a))
    dst.parent.mkdir(parents=True, exist_ok=True)
    fade = min(FADE_S, d / 4)
    _run(["ffmpeg", "-y", "-ss", f"{max(0.0, a):.3f}", "-t", f"{d:.3f}", "-i", str(src), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le",
          "-af", f"afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, d - fade):.3f}:d={fade:.3f}", str(dst)], "قص الصوت")
    return duration_of(dst)


# ── التفريغ ─────────────────────────────────────────────────────────────
def _asr_path(stem: str) -> Path:
    return src_dir(stem) / "asr.json"


def load_asr(stem: str) -> dict | None:
    try:
        return json.loads(_asr_path(stem).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def transcribe(wav: Path, duration: float, language: str | None = None) -> dict:
    """كلمات مفرّغة بتوقيتها: Whisper المحلي (لكل كلمة) أو مقاطع المزوّد مع تقدير توقيت الكلمات. {words, segments, full_text, language, provider, model, timing}"""
    import stt
    import tts
    try:
        res = stt.transcribe(wav, language) if language else stt.transcribe(wav)
    except stt.STTError as e:
        raise VoiceUploadError(f"فشل التفريغ: {e}", 502)
    words = [{"text": str(w["text"]).strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
             for w in (res.get("words") or []) if str(w.get("text", "")).strip()]
    timing = "stt"
    if not words:                                          # مزوّد بلا توقيت كلمات: نقدّرها داخل كل مقطع
        timing = "estimated"
        for seg in res.get("segments") or []:
            s, e = float(seg["start"]), float(seg["end"])
            for w in tts.estimate_words(" ".join(str(seg.get("text", "")).split()), max(e - s, 0.01)):
                words.append({"text": w["text"], "start": round(min(s + w["start"], duration), 3), "end": round(min(s + w["end"], duration), 3)})
    if not words:
        raise VoiceUploadError("ما انسمع كلام بالتسجيل (تأكد إنه فيه صوتك وإن الميكروفون كان شغّال)")
    return {"words": words, "segments": res.get("segments") or [], "full_text": res.get("full_text") or " ".join(w["text"] for w in words),
            "language": res.get("language") or "", "provider": res.get("provider") or "", "model": res.get("model") or "",
            "timing": timing, "duration": duration, "at": _now()}


def prepare_source(audio: Path, d: Path, language: str | None = None, log=print) -> tuple[dict, Path]:
    """تحويل التسجيل لـ WAV + تفريغه + حفظ source.wav وasr.json بالمجلد d (للمشروع الحر والمهمة الموجّهة). بيرجّع (التفريغ، مسار source.wav).
    الأصل المرفوع للمشروع (اسمه upload*) بينشال بعد التحويل؛ ملفات المالك التانية ما بتنلمس."""
    d.mkdir(parents=True, exist_ok=True)
    a = Path(audio)
    own = a.parent.resolve() == d.resolve() and a.name.startswith("upload")
    tmp = d / "source.tmp.wav"
    log("[…] تحويل الصوت…")
    try:
        dur = to_wav(a, tmp)
    finally:
        if own:
            a.unlink(missing_ok=True)
    log(f"[…] تفريغ {dur:.0f}ث (بياخد وقت حسب موديل التفريغ)…")
    t0 = time.time()
    try:
        asr = transcribe(tmp, dur, language)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    log(f"[✓] انسمع {len(asr['words'])} كلمة ({time.time() - t0:.0f}ث) — {asr['provider']} {asr['model']}")
    tmp.replace(d / "source.wav")
    (d / "asr.json").write_text(json.dumps(asr, ensure_ascii=False, indent=2), encoding="utf-8")
    return asr, d / "source.wav"


# ── خطة التقسيم (المشروع الحر) ───────────────────────────────────────────
def _scene_texts(tl: dict) -> list[str]:
    return [str(sc.get("voiceover") or "").strip() for sc in tl.get("scenes") or []]


def decide_mode(tl: dict, mode: str = "auto") -> str:
    if mode not in MODES:
        raise VoiceUploadError("الوضع: auto أو by_text أو by_time أو new_scenes")
    if mode != "auto":
        return mode
    import free_project as fp
    if any(_scene_texts(tl)):
        return "by_text"
    if not tl.get("scenes") or fp._is_blank_default(tl):
        return "new_scenes"
    return "by_time"


def _rel_words(words: list[dict], a: float, b: float) -> list[dict]:
    """كلمات المقطع [a, b] بأزمنة نسبية لبدايته (ms)."""
    out = []
    span = max(0.0, b - a)
    for w in words:
        if w["end"] <= a or w["start"] >= b:
            continue
        st = min(max(w["start"] - a, 0.0), span)
        en = min(max(w["end"] - a, st), span)
        out.append({"text": w["text"], "start_ms": round(st * 1000), "end_ms": round(en * 1000)})
    return out


def plan(tl: dict, asr: dict, mode: str = "auto") -> dict:
    """بيحسب التقسيم بلا ما يكتب شي: {mode, coverage, warnings, scenes:[{index|new, text, slice:(a,b)|None, words:[…]}]}.
    index = رقم المشهد الموجود (0-based)، و new=True لمشهد بيتولّد من جملة."""
    mode = decide_mode(tl, mode)
    words, total = asr["words"], float(asr["duration"])
    warnings: list[str] = []
    scenes_in = tl.get("scenes") or []
    items: list[dict] = []
    coverage = None
    if mode == "by_text":
        counts, flat = [], []
        for t in _scene_texts(tl):
            ws = ar_align.words_of(t)
            counts.append(len(ws))
            flat.extend(ws)
        if not flat:
            raise VoiceUploadError("ما في نص مكتوب بالمشاهد — اكتب «الكلام» لمشهد على الأقل أو استعمل التوزيع حسب الوقت")
        al = ar_align.align(flat, words, total)
        coverage = al["coverage"]
        if coverage < MIN_COVERAGE:
            warnings.append(f"المطابقة ضعيفة ({round(coverage * 100)}%): المسموع بيختلف عن المكتوب — راجع النص أو سجّل من جديد ثم أعد «التقسيم».")
        sp = ar_align.spans(al["words"], counts)
        for k, span in enumerate(sp):                      # مشهد نصه انوزّع بالاستيفاء بس ما في كلام مسموع بمكانه = غايب عن التسجيل
            if span is not None and not any(w["end"] > span[0] + 0.05 and w["start"] < span[1] - 0.05 for w in words):
                sp[k] = None
        cp = ar_align.cut_points(sp, total)
        pos = 0
        for k, c in enumerate(counts):
            seg_words = al["words"][pos:pos + c]
            pos += c
            if cp[k] is None:
                items.append({"index": k, "slice": None})
                continue
            a, b = cp[k]
            rel_ws = [{"text": w["word"], "start_ms": round(min(max(w["start"] - a, 0.0), b - a) * 1000), "end_ms": round(min(max(w["end"] - a, 0.0), b - a) * 1000)}
                      for w in seg_words]
            items.append({"index": k, "slice": (a, b), "words": rel_ws})
        silent = sum(1 for it in items if it["slice"] is None and _scene_texts(tl)[it["index"]])
        if silent:
            warnings.append(f"{silent} مشهد فيه نص بس ما انلقى كلامه بالتسجيل.")
    else:
        sents = ar_align.sentences(words)
        if not sents:
            raise VoiceUploadError("ما انسمع كلام بالتسجيل")
        if mode == "by_time":
            durs = [max(0.0, (int(sc["end_ms"]) - int(sc["start_ms"])) / 1000) for sc in scenes_in]
            groups = ar_align.assign_by_time(sents, durs, total)
            idx = list(range(len(scenes_in)))
        else:                                              # new_scenes
            n = min(len(sents), timeline.FREE_MAX_SCENES)
            groups = ar_align.balanced(sents, n)
            idx = [None] * n
        sp = [(sents[g[0]]["start"], sents[g[-1]]["end"]) if g else None for g in groups]
        cp = ar_align.cut_points(sp, total)
        for k, g in enumerate(groups):
            if not g:
                items.append({"index": idx[k], "slice": None, "new": idx[k] is None})
                continue
            a, b = cp[k]
            items.append({"index": idx[k], "new": idx[k] is None, "slice": (a, b), "text": " ".join(sents[i]["text"] for i in g).strip(),
                          "words": _rel_words(words, a, b)})
        if mode == "by_time":
            empty = sum(1 for it in items if it["slice"] is None)
            if empty:
                warnings.append(f"{empty} مشهد ما إله كلام: التسجيل ما كفى لتوزيعه على كل المشاهد (بيضلوا بلا صوت).")
            if len(sents) < len(scenes_in) // 2:
                warnings.append("جمل التسجيل أقل بكتير من المشاهد — جرّب تسجيل أطول أو قلّل المشاهد.")
    return {"mode": mode, "coverage": coverage, "warnings": warnings, "scenes": items}


# ── تطبيق الخطة على الخط الزمني ──────────────────────────────────────────
def fit_shots(sc: dict, target_ms: int) -> None:
    """مدد لقطات المشهد بتتمدّد/بتنكمش بالنسبة لتصير مجموعها = target_ms (ضمن حدود اللقطة 0.5–60ث)."""
    shots = sc["shots"]
    lo, hi = timeline.FREE_MIN_SHOT_MS, timeline.FREE_MAX_SHOT_MS
    target = min(max(int(target_ms), lo * len(shots)), hi * len(shots))
    cur = [int(sh["end_ms"]) - int(sh["start_ms"]) for sh in shots]
    total = sum(cur) or 1
    new = [min(max(round(d * target / total), lo), hi) for d in cur]
    diff = target - sum(new)
    for k in reversed(range(len(new))):
        if not diff:
            break
        adj = min(max(new[k] + diff, lo), hi) - new[k]
        new[k] += adj
        diff -= adj
    for sh, d in zip(shots, new):
        sh["end_ms"] = int(sh["start_ms"]) + d


def _clear_scene_voices(stem: str, tl: dict) -> None:
    d = voice_dir(stem)
    keep = {Path(sc["voice"]["audio"]).name for sc in tl.get("scenes") or [] if (sc.get("voice") or {}).get("audio")}
    if d.exists():
        for f in d.glob("*.wav"):
            if f.name not in keep:
                f.unlink(missing_ok=True)


def _info(tl: dict, **kw) -> None:
    info = dict(tl.get("voice_info") or {})
    info.update(kw)
    tl["voice_info"] = info


def _free_only(path) -> None:
    import free_project as fp
    try:
        fp._need_free(Path(path))
    except fp.FreeError as e:
        raise VoiceUploadError(str(e), e.status)


def apply_plan(path, asr: dict, source: Path, mode: str = "auto", fit: bool = True, by: str = "", log=print) -> dict:
    """بيقص ويكتب بمرحلتين: (1) خطة وقص الملفات بلا قفل (بطيء)، (2) إعادة قراءة الخط الزمني وتطبيق الخطة وحفظ واحد (سريع) —
    وإذا تغيّرت مشاهد المشروع بين المرحلتين بيوقف برسالة بدل ما يكتب فوق شغل المالك. بيرجّع {mode, coverage, warnings, voiced, scenes}."""
    import free_project as fp
    path = Path(path)
    stem = path.stem
    tl0 = fp._load(path)
    pl = plan(tl0, asr, mode)
    mode = pl["mode"]
    blank0 = not tl0["scenes"] or fp._is_blank_default(tl0)
    if mode == "new_scenes" and not blank0:
        raise VoiceUploadError("المشروع فيه مشاهد — استعمل التوزيع حسب النص أو حسب الوقت")
    keys0 = [sc["key"] for sc in tl0["scenes"]]
    vdir = voice_dir(stem)
    vdir.mkdir(parents=True, exist_ok=True)
    cut: dict[int, tuple[Path, float]] = {}
    for i, it in enumerate(pl["scenes"]):
        if it["slice"] is None:
            continue
        tmp = vdir / f"_tmp_{i}.wav"
        cut[i] = (tmp, cut_wav(source, it["slice"][0], it["slice"][1], tmp))
        log(f"  [✓] مقطع {len(cut)}: {cut[i][1]:.1f}ث")
    try:
        with fp._LOCK:
            tl = fp._load(path)
            if [sc["key"] for sc in tl["scenes"]] != keys0 or (mode == "new_scenes" and not (not tl["scenes"] or fp._is_blank_default(tl))):
                raise VoiceUploadError("تغيّرت مشاهد المشروع أثناء المعالجة — أعد «التقسيم»", 409)
            if mode == "new_scenes":
                tl["scenes"] = []
                for it in pl["scenes"]:
                    if it["slice"] is not None:
                        sc = fp.new_scene(tl, voiceover=it["text"])
                        sc["shots"].append(fp.new_shot(tl, max(timeline.FREE_MIN_SHOT_MS, min(timeline.FREE_MAX_SHOT_MS, round((it["slice"][1] - it["slice"][0]) * 1000)))))
                        tl["scenes"].append(sc)
                        it["scene"] = sc
            else:
                for it in pl["scenes"]:
                    it["scene"] = tl["scenes"][it["index"]]
                    if mode == "by_time" and it.get("text") is not None:
                        it["scene"]["voiceover"] = it["text"]
            voiced = 0
            for i, it in enumerate(pl["scenes"]):
                sc = it.get("scene")
                if sc is None:
                    continue
                if it["slice"] is None:
                    sc["voice"] = None
                    continue
                tmp, d = cut[i]
                out = vdir / f"{sc['key']}.wav"
                tmp.replace(out)
                a, b = it["slice"]
                sc["voice"] = {"audio": rel(out), "duration_ms": round(d * 1000), "source": "upload", "words": it.get("words") or [],
                               "timing": asr.get("timing", "stt"), "text": str(sc.get("voiceover") or "").strip(), "span_ms": [round(a * 1000), round(b * 1000)]}
                if fit:
                    fit_shots(sc, max(timeline.FREE_MIN_SHOT_MS, round(d * 1000)))
                voiced += 1
            _clear_scene_voices(stem, tl)
            fp.retime(tl)
            _info(tl, source="upload", mode=mode, at=_now(), coverage=pl["coverage"], warnings=pl["warnings"], fit=bool(fit),
                  asr={"provider": asr.get("provider"), "model": asr.get("model"), "language": asr.get("language"), "duration_s": asr.get("duration"),
                       "timing": asr.get("timing")})
            try:
                fp._save(path, tl, by=by)
            except fp.FreeError as e:
                raise VoiceUploadError(str(e), e.status)
    finally:
        for tmp, _d in cut.values():
            tmp.unlink(missing_ok=True)
    return {"mode": mode, "coverage": pl["coverage"], "warnings": pl["warnings"], "voiced": voiced, "scenes": len(tl["scenes"])}


# ── الواجهة الرئيسية (المشروع الحر) ──────────────────────────────────────
def ingest_free(path, audio: Path, *, fit: bool = True, mode: str = "auto", language: str | None = None, by: str = "", log=print) -> dict:
    """تسجيل جديد: تحويل ← تفريغ ← حفظ المصدر والتفريغ ← تقسيم على المشاهد."""
    path = Path(path)
    _free_only(path)                                       # المهمة الموجّهة ليها مسارها
    stem = path.stem
    d = src_dir(stem)
    asr, source = prepare_source(audio, d, language, log)
    res = apply_plan(path, asr, source, mode, fit, by, log)
    log(f"[✓] {res['voiced']} مشهد صار إله صوت" + (f" · مطابقة {round(res['coverage'] * 100)}%" if res["coverage"] is not None else ""))
    return res


def realign_free(path, *, fit: bool = True, mode: str = "auto", by: str = "", log=print) -> dict:
    """إعادة التقسيم من التفريغ والمصدر المحفوظين (بعد تعديل نص المشاهد مثلاً) — بلا تفريغ جديد."""
    path = Path(path)
    _free_only(path)
    asr, source = load_asr(path.stem), src_dir(path.stem) / "source.wav"
    if not asr or not source.is_file():
        raise VoiceUploadError("ما في تسجيل محفوظ لهالمشروع — ارفع تسجيل أول", 404)
    return apply_plan(path, asr, source, mode, fit, by, log)


def delete_free(path, *, purge: bool = False, by: str = "") -> dict:
    """بيشيل صوت كل المشاهد (مدد اللقطات بتضل). المصدر والتفريغ بيضلوا لإعادة التقسيم، إلا لو purge."""
    import free_project as fp
    import shutil
    path = Path(path)
    stem = path.stem
    _free_only(path)
    with fp._LOCK:
        tl = fp._load(path)
        for sc in tl["scenes"]:
            sc["voice"] = None
        tl.pop("voice_info", None)
        fp.retime(tl)
        fp._save(path, tl, by=by)
    shutil.rmtree(voice_dir(stem), ignore_errors=True)
    if purge:
        shutil.rmtree(src_dir(stem), ignore_errors=True)
    return fp.board(path)


# ── صوت بالذكاء للمشروع الحر ─────────────────────────────────────────────
def tts_todo(path, only_missing: bool = True) -> list[tuple[str, str]]:
    """[(مفتاح المشهد، النص)] اللي بدها صوت بالذكاء: فيها كلام، وبلا صوت أو نصها اتغيّر عن نص صوتها (إلا لو only_missing=False)."""
    import free_project as fp
    path = Path(path)
    _free_only(path)
    todo = []
    for sc in fp._load(path)["scenes"]:
        text = str(sc.get("voiceover") or "").strip()
        v = sc.get("voice") or {}
        if not text:
            continue
        if only_missing and v.get("audio") and v.get("text") == text and (lib() / v["audio"]).is_file():
            continue
        todo.append((sc["key"], text))
    if not todo:
        raise VoiceUploadError("ما في مشهد بحاجة لصوت — اكتب «الكلام» لمشهد أول (أو ولّد الكل)", 409)
    return todo


def tts_free(path, *, only_missing: bool = True, overrides: dict | None = None, fit: bool = True, by: str = "", log=print) -> dict:
    """tts.speak لكل مشهد فيه كلام (بس اللي بلا صوت أو نصه اتغيّر، إلا لو only_missing=False). حفظ بعد كل مشهد."""
    import free_project as fp
    import production_log
    import tts
    path = Path(path)
    stem = path.stem
    todo = tts_todo(path, only_missing)
    cfg = tts.tts_config(overrides or {})
    log(f"[i] {cfg['provider']} · {cfg['model']} · صوت {cfg['voice']} — {len(todo)} مشهد")
    vdir = voice_dir(stem)
    vdir.mkdir(parents=True, exist_ok=True)
    done = 0
    for key, text in todo:
        mp3 = vdir / f"{key}.tts.mp3"
        t0 = time.time()
        try:
            with tts.log_context(stem, key):
                r = tts.speak(text, mp3, overrides or {}, want_timing=True)
        except tts.TTSError as e:
            if not getattr(e, "logged", False):                    # نموذج المكتبة: model_run سجّل المحاولة
                production_log.record("voice", "failed", script_stem=stem, shot_id=key, model_name=cfg["provider"], model_id=cfg.get("model"),
                                      path="api", seconds=time.time() - t0, error=str(e))
            raise VoiceUploadError(f"فشل توليد صوت المشهد {key}: {e}", 502)
        if not r.get("logged"):
            production_log.record("voice", "ok", script_stem=stem, shot_id=key, model_name=cfg["provider"], model_id=cfg.get("model"), path="api",
                                  seconds=time.time() - t0)
        wav = vdir / f"{key}.wav"
        _run(["ffmpeg", "-y", "-i", str(mp3), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], "تحويل صوت المشهد")
        mp3.unlink(missing_ok=True)
        d = duration_of(wav)
        words = [{"text": w["text"], "start_ms": round(float(w["start"]) * 1000), "end_ms": round(float(w["end"]) * 1000)} for w in r.get("words") or []]
        with fp._LOCK:
            tl = fp._load(path)
            sc = next((s for s in tl["scenes"] if s["key"] == key), None)
            if sc is None:                                 # انحذف المشهد أثناء التوليد
                wav.unlink(missing_ok=True)
                continue
            sc["voice"] = {"audio": rel(wav), "duration_ms": round(d * 1000), "source": "tts", "provider": r.get("provider"), "model": r.get("model"),
                           "voice_id": r.get("voice"), "words": words, "timing": r.get("timing_source", "estimated"), "text": text}
            if fit:
                fit_shots(sc, max(timeline.FREE_MIN_SHOT_MS, round(d * 1000)))
            fp.retime(tl)
            _info(tl, source="tts" if all((s.get("voice") or {}).get("source") == "tts" for s in tl["scenes"] if s.get("voice")) else "mixed", at=_now())
            try:
                fp._save(path, tl, by=by)
            except fp.FreeError as e:
                raise VoiceUploadError(str(e), e.status)
        done += 1
        log(f"  [✓] مشهد {key}: {d:.1f}ث ({done}/{len(todo)})")
    return {"voiced": done, "provider": cfg["provider"], "model": cfg["model"]}


# ── المهمة الموجّهة: تسجيلك بمحطة الصوت (4) ───────────────────────────────
def _mp3(wav: Path, out: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3", "-ar", "44100", "-ac", "1", str(out)], "ترميز mp3")


def _concat_mp3(files: list[Path], out: Path) -> bool:
    """دمج مقاطع المشاهد بملف واحد بنفس ترتيبها (الخط الزمني بيحسب حدود المشاهد من مجموع مددها)."""
    lst = out.parent / "_concat_upload.txt"
    lst.write_text("\n".join(f"file '{f.name}'" for f in files), encoding="utf-8")
    try:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name], "دمج الصوت", cwd=out.parent)
        return out.is_file()
    except VoiceUploadError:
        return False
    finally:
        lst.unlink(missing_ok=True)


def ingest_guided(path, audio: Path | None, *, language: str | None = None, log=print, prepared: tuple[dict, Path] | None = None) -> dict:
    """تسجيلك لمهمة موجّهة: نفس شروط الإضافة (مراجعة نظيفة + المحطة 4 مسموح تبدأ)، بيطابق نص السيناريو، وبيكتب scene_NN.mp3
    وfull.mp3 وvoice.json بنفس شكل أي مزوّد (provider: upload). بعدها المحطة 4: «ناطرة اختيارك» لو المدة ضمن 45–50 والمطابقة
    مقبولة، وإلا «ساقطة» بسبب واضح. الاعتماد بالزر الحالي بعد السماع (approve_voice).
    prepared = (تفريغ، ملف WAV) جاهزين من مسار تاني (مثلاً «ابدأ من تسجيلك») فما منفرّغ مرتين."""
    import ext_tasks
    import studio_state
    import voice_studio
    path = Path(path)
    stem = path.stem
    script = json.loads(path.read_text(encoding="utf-8"))
    meta = script.get("_meta") or {}
    if meta.get("mode") == "free":
        raise VoiceUploadError("هاد مشروع حر — الصوت من لوحة «الصوت» جواه", 409)
    if meta.get("hook_of"):
        raise VoiceUploadError("هاي نسخة هوك: صوت المشاهد 2–7 موروث من الفيديو الأساسي — ارفع تسجيلك لنسخة الأساس", 409)
    try:
        ext_tasks._voice_ready(path)
    except ext_tasks.ExtError as e:
        raise VoiceUploadError(str(e), 409)
    scenes = script.get("scenes") or []
    texts = [str(s.get("voiceover") or "").strip() for s in scenes]
    if not any(texts):
        raise VoiceUploadError("ما في كلام (voiceover) بالسيناريو")
    out_dir = lib() / "voice" / stem
    src = out_dir / "upload_src"
    src.mkdir(parents=True, exist_ok=True)
    if prepared is None:
        asr, wav = prepare_source(audio, src, language, log)
    else:
        asr, wav = prepared
        if Path(wav).resolve() != (src / "source.wav").resolve():
            shutil.copy2(wav, src / "source.wav")
        (src / "asr.json").write_text(json.dumps(asr, ensure_ascii=False, indent=2), encoding="utf-8")
        wav = src / "source.wav"
    try:
        studio_state.set_state(stem, 4, "running", "تفريغ تسجيلك وتقسيمه على المشاهد")
    except studio_state.StationBlocked as e:
        raise VoiceUploadError(str(e), 409)
    try:
        pl = plan({"scenes": [{"voiceover": t} for t in texts]}, asr, "by_text")
        entries, files = [], []
        for it in pl["scenes"]:
            if it["slice"] is None:
                continue
            k = it["index"]
            n = scenes[k].get("scene_number")
            tmp = out_dir / f"_up_{k}.wav"
            cut_wav(wav, it["slice"][0], it["slice"][1], tmp)
            mp3 = out_dir / f"scene_{n:02d}.mp3"
            _mp3(tmp, mp3)
            tmp.unlink(missing_ok=True)
            d = duration_of(mp3)
            planned = float(scenes[k].get("duration_sec") or 0)
            entries.append({"path": rel(mp3), "duration_sec": round(d, 2), "provider": "upload", "model": "owner", "voice": "owner",
                            "words": [{"text": w["text"], "start": w["start_ms"] / 1000, "end": w["end_ms"] / 1000} for w in it["words"]],
                            "timing_source": "stt", "scene": n, "planned_sec": planned, "drift_sec": round(d - planned, 2), "text": texts[k], "emotion_tag": ""})
            files.append(mp3)
            log(f"  [✓] مشهد {n}: {d:.1f}ث")
        missing = [scenes[it["index"]].get("scene_number") for it in pl["scenes"] if it["slice"] is None and texts[it["index"]]]
        complete = not missing and bool(entries)
        combined = None
        if complete:
            full = out_dir / "full.mp3"
            if _concat_mp3(files, full):
                combined = {"path": rel(full), "duration_sec": duration_of(full)}
        total = round(sum(e["duration_sec"] for e in entries), 2)
        planned_total = round(sum(e["planned_sec"] for e in entries), 2)
        manifest = {"script": path.name, "generated_at": datetime.now().isoformat(timespec="seconds"), "provider": "upload", "model": "owner", "voice": "owner",
                    "scenes": entries, "total_actual_sec": total, "total_planned_sec": planned_total, "total_drift_sec": round(total - planned_total, 2),
                    "scenes_off": [e["scene"] for e in entries if abs(e["drift_sec"]) > 0.6], "combined": combined, "source": "upload",
                    "coverage": pl["coverage"], "asr": {"provider": asr["provider"], "model": asr["model"], "language": asr["language"], "timing": asr["timing"]}}
        (out_dir / "voice.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        gate = voice_studio.check_duration(total) if complete else None
        if missing:
            why = f"مشهد {'، '.join(str(n) for n in missing)} ما انلقى كلامه بالتسجيل — راجع النص أو سجّل من جديد"
            studio_state.set_state(stem, 4, "failed", why)
        elif pl["coverage"] < MIN_COVERAGE:
            why = f"المطابقة {round(pl['coverage'] * 100)}% — المسموع بيختلف كتير عن نص السيناريو. سجّل من جديد أو عدّل النص"
            studio_state.set_state(stem, 4, "failed", why)
        elif not gate["ok"]:
            why = gate["message"] + " — سجّل من جديد بالمدة المناسبة"
            studio_state.set_state(stem, 4, "failed", why)
        else:
            why = ""
            studio_state.set_state(stem, 4, "awaiting_choice", "بانتظار اعتماد المالك سمعياً — " + gate["message"])
    except Exception as e:
        try:
            studio_state.set_state(stem, 4, "failed", str(e)[:200])
        except Exception:                                  # noqa: BLE001
            pass
        raise
    log(f"[✓] {len(entries)} مشهد · {total}ث · مطابقة {round(pl['coverage'] * 100)}%" + (f" — {why}" if why else ""))
    return {"scenes": len(entries), "total_sec": total, "coverage": pl["coverage"], "ok": not why, "reason": why, "gate": gate}


def main() -> None:
    import job_signals
    job_signals.install()
    ap = argparse.ArgumentParser(description="صوت المالك للمشروع الحر")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "realign", "tts", "ingest-guided"):
        sp = sub.add_parser(name)
        sp.add_argument("script")
        if name != "ingest-guided":
            sp.add_argument("--no-fit", action="store_true")
        if name in ("ingest", "realign"):
            sp.add_argument("--mode", default="auto", choices=list(MODES))
        if name in ("ingest", "ingest-guided"):
            sp.add_argument("--audio", required=True)
            sp.add_argument("--language")
        if name == "tts":
            sp.add_argument("--all", action="store_true")
    a = ap.parse_args()
    log = lambda m: print(m, flush=True)          # noqa: E731
    try:
        if a.cmd == "ingest-guided":
            res = ingest_guided(a.script, Path(a.audio), language=a.language, log=log)
            if not res["ok"]:
                sys.exit(f"[!] {res['reason']}")
        elif a.cmd == "ingest":
            res = ingest_free(a.script, Path(a.audio), fit=not a.no_fit, mode=a.mode, language=a.language, log=log)
        elif a.cmd == "realign":
            res = realign_free(a.script, fit=not a.no_fit, mode=a.mode, log=log)
        else:
            res = tts_free(a.script, only_missing=not a.all, fit=not a.no_fit, log=log)
    except VoiceUploadError as e:
        sys.exit(f"[!] {e}")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
