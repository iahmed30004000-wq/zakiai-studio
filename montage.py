#!/usr/bin/env python3
"""
المحطة ١٠: الآهات والمونتاج (ffmpeg).

    python montage.py preview library/scripts/X.json     # معاينة كاملة بدقة مخفّضة
    python montage.py final   library/scripts/X.json     # تصدير 1080×1920 · 30 إطار · اسم الملف = معرّف السيناريو

  · الخط الزمني بيتبنى من حركات اللقطات المعتمدة (مدة كل لقطة من الصوت).
  · ترجمة عربية مؤقّتة بالكلمات، بمنطقة آمنة من الأسفل لواجهات ميتا وتيك توك (libass + fribidi + harfbuzz للوصل والاتجاه).
    التشكيل: بيطلع بنص السيناريو كما هو — **ما بيتولّد تشكيل آلي** (ما في موديل تشكيل على الجهاز).
  · آهات بشرية بس، بخفض تلقائي (sidechain) تحت الصوت. بلا آهات = بلا مسار موسيقي.
  · صوت معايَر (loudnorm -16 LUFS). إعادة التصدير بلا إعادة توليد أي شي.
  · القطع بين المشاهد قطع مباشر (الانتقالات البسيطة لسا ما انبنت).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import studio_state
import timeline

FINAL_SIZE = (1080, 1920)
PREVIEW_SIZE = (540, 960)
FPS = 30
SAFE_BOTTOM = 0.22          # منطقة آمنة من الأسفل (واجهات ميتا/تيك توك)
SAFE_SIDE = 0.06
DURATION_EPS_MS = 150
_PUNCT = "،,.؟?!؛"


class MontageError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def work_dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "timelines" / stem / "render"


def exports_dir() -> Path:
    return Path(config.LIBRARY_DIR) / "exports"


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "video")


# ── الترجمة ─────────────────────────────────────────────────────────────
def build_cues(tl: dict, max_words: int = 5, max_chars: int = 32, gap_ms: int = 350) -> list[dict]:
    """مجموعات كلمات مؤقّتة بتوقيت الكلمات نفسه. بتقطع عند علامة ترقيم أو وقفة أو طول."""
    cues, cur = [], []
    words = tl["words"]

    def flush():
        nonlocal cur
        if cur:
            cues.append({"start_ms": cur[0]["start_ms"], "end_ms": cur[-1]["end_ms"],
                         "text": " ".join(w["text"] for w in cur)})
            cur = []

    for i, w in enumerate(words):
        cur.append(w)
        text_len = len(" ".join(x["text"] for x in cur))
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (len(cur) >= max_words or text_len >= max_chars or w["text"][-1:] in _PUNCT
                or (nxt and nxt["start_ms"] - w["end_ms"] > gap_ms)):
            flush()
    flush()
    total = tl["voice"]["duration_ms"]
    for k, c in enumerate(cues):                          # نمدّد النهاية شوي (حتى بداية اللي بعدها)
        nxt = cues[k + 1]["start_ms"] if k + 1 < len(cues) else total
        c["end_ms"] = max(c["end_ms"], min(nxt, c["end_ms"] + 250))
        if c["end_ms"] - c["start_ms"] < 300:
            c["end_ms"] = min(total, c["start_ms"] + 300)
    return cues


def _ts(ms: int) -> str:
    cs = round(ms / 10)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(cues: list[dict], path: Path, size: tuple[int, int]) -> None:
    w, h = size
    fs = round(64 * h / 1920)
    ml, mv = round(w * SAFE_SIDE), round(h * SAFE_BOTTOM)
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,Tahoma,{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(2, round(3 * h / 1920))},0,2,{ml},{ml},{mv},1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = [f"Dialogue: 0,{_ts(c['start_ms'])},{_ts(c['end_ms'])},Default,,0,0,0,,{c['text']}" for c in cues]
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ── ffmpeg ──────────────────────────────────────────────────────────────
def probe(path: Path) -> dict:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                           capture_output=True, text=True, check=True)
        d = json.loads(r.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return {}
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    return {"width": v.get("width"), "height": v.get("height"), "fps": (float(num) / float(den)) if float(den) else 0,
            "duration_ms": round(float(d.get("format", {}).get("duration", 0)) * 1000), "has_audio": bool(a),
            "audio_rate": int(a.get("sample_rate", 0) or 0)}


def _prepare_fonts(wd: Path) -> str:
    """بننسخ خط عربي من خطوط النظام لمجلد العرض ونستخدمه بمسار نسبي (تجنّب مشاكل «C:» بفلاتر ffmpeg)."""
    import shutil
    src = Path("C:/Windows/Fonts")
    names = ("tahoma.ttf", "tahomabd.ttf", "arial.ttf", "arialbd.ttf", "segoeui.ttf")
    found = [src / n for n in names if (src / n).exists()] if src.exists() else []
    if not found:
        return ""
    d = wd / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    for f in found:
        if not (d / f.name).exists():
            shutil.copy2(f, d / f.name)
    return ":fontsdir=fonts"


def _inputs(stem: str, tl: dict) -> tuple[list[Path], Path, Path | None]:
    import motion
    clips = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            mo = sh.get("motion")
            p = motion.abs_of(stem, mo["clip"]) if mo and mo.get("clip") else None
            if not p:
                raise MontageError(f"لقطة {sh['id']}: ما في مقطع حركة")
            clips.append(p)
    rel = (tl["voice"] or {}).get("audio")
    voice = (Path(config.LIBRARY_DIR) / rel) if rel else None
    if not voice or not voice.exists():
        raise MontageError("ملف الصوت المدموج ناقص")
    amb = tl.get("ambience") or {}
    ahat_p = None
    if amb.get("track_id"):
        import ahat
        t = ahat.get(amb["track_id"])
        if not t or not t.get("approved"):
            raise MontageError("الآهات المختارة مش معتمدة بالسمع")
        ahat_p = ahat.audio_path(amb["track_id"])
        if not ahat_p:
            raise MontageError("ملف الآهات ناقص")
    return clips, voice, ahat_p


def build_command(clips: list[Path], voice: Path, ahat_p: Path | None, out: Path, size: tuple[int, int],
                  dur_s: float, preview: bool, duck_db: float = -14.0, fonts_opt: str = "") -> list[str]:
    W, H = size
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += ["-i", str(voice)]
    vi = len(clips)
    parts = []
    for i in range(len(clips)):
        parts.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[vc]")
    parts.append(f"[vc]subtitles=captions.ass{fonts_opt}[v]")
    if ahat_p:
        cmd += ["-i", str(ahat_p)]
        ai = vi + 1
        vol = round(10 ** (duck_db / 20), 3)
        parts.append(f"[{vi}:a]aresample=48000,asplit=2[vs][vm]")
        parts.append(f"[{ai}:a]aresample=48000,aloop=loop=-1:size=2000000000,atrim=0:{dur_s:.3f},asetpts=PTS-STARTPTS,"
                     f"volume={vol},afade=t=in:d=1,afade=t=out:st={max(0.0, dur_s - 1.5):.3f}:d=1.5[amb]")
        parts.append("[amb][vs]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=400[duck]")
        parts.append("[vm][duck]amix=inputs=2:duration=first:normalize=0[mix]")
    else:
        parts.append(f"[{vi}:a]aresample=48000[mix]")
    parts.append("[mix]loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-t", f"{dur_s:.3f}",
            "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium", "-crf", "28" if preview else "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out)]
    return cmd


def render(script_path, mode: str = "preview", size: tuple[int, int] | None = None, log=print) -> dict:
    if mode not in ("preview", "final"):
        raise MontageError("الوضع: preview أو final")
    path = Path(script_path)
    stem = path.stem
    ok, why = studio_state.can_start(stem, 10)
    if not ok:
        raise MontageError(why)
    tl = timeline.load(stem)
    if not tl:
        raise MontageError("ما في خط زمني")
    import motion
    probs = motion.problems(tl)
    if probs:
        raise MontageError("؛ ".join(p["message"] for p in probs[:3]))
    if mode == "final" and not (tl.get("render") or {}).get("preview"):
        raise MontageError("لازم معاينة كاملة قبل التصدير النهائي")
    clips, voice, ahat_p = _inputs(stem, tl)
    size = size or (PREVIEW_SIZE if mode == "preview" else FINAL_SIZE)
    dur_ms = tl["voice"]["duration_ms"]
    wd = work_dir(stem)
    wd.mkdir(parents=True, exist_ok=True)
    cues = build_cues(tl)
    write_ass(cues, wd / "captions.ass", size)

    script = json.loads(path.read_text(encoding="utf-8"))
    sid = _safe_name(tl.get("script_id") or (script.get("_meta") or {}).get("script_id") or stem)
    if mode == "final":
        exports_dir().mkdir(parents=True, exist_ok=True)
        out = exports_dir() / f"{sid}.mp4"
    else:
        out = wd / "preview.mp4"
    studio_state.set_state(stem, 10, "running", "تصدير نهائي" if mode == "final" else "معاينة")
    amb = tl.get("ambience") or {}
    cmd = build_command(clips, voice, ahat_p, out.resolve(), size, dur_ms / 1000, mode == "preview",
                        float(amb.get("duck_db", -14)), _prepare_fonts(wd))
    log(f"[…] {mode}: {len(clips)} مقطع · {size[0]}x{size[1]} · {len(cues)} ترجمة" + (" · آهات" if ahat_p else " · بلا آهات"))
    r = subprocess.run(cmd, cwd=str(wd), capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        studio_state.set_state(stem, 10, "failed", "فشل ffmpeg")
        raise MontageError("فشل ffmpeg: " + (r.stderr or "")[-400:])
    info = probe(out)
    problems = []
    if (info.get("width"), info.get("height")) != size:
        problems.append(f"الأبعاد {info.get('width')}x{info.get('height')} ≠ {size[0]}x{size[1]}")
    if abs(info.get("duration_ms", 0) - dur_ms) > DURATION_EPS_MS:
        problems.append(f"المدة {info.get('duration_ms')}ms ≠ مدة الصوت {dur_ms}ms")
    if not info.get("has_audio"):
        problems.append("بلا مسار صوت")
    if abs(info.get("fps", 0) - FPS) > 0.5:
        problems.append(f"معدل الإطارات {info.get('fps'):.1f} ≠ {FPS}")
    if problems:
        studio_state.set_state(stem, 10, "failed", "؛ ".join(problems))
        raise MontageError("الناتج ما طابق المواصفات: " + "؛ ".join(problems))

    rel = out.resolve().relative_to(Path(config.LIBRARY_DIR).resolve()).as_posix()
    tl = timeline.load(stem)
    tl.setdefault("render", {})[mode] = {"file": rel, "at": _now(), "size": list(size), "duration_ms": info["duration_ms"],
                                         "ahat": bool(ahat_p), "captions": len(cues)}
    tl["captions"] = {"ass": f"render/captions.ass", "style": "identity", "cues": len(cues), "safe_bottom": SAFE_BOTTOM}
    timeline.save(stem, tl)
    if mode == "final":
        studio_state.set_state(stem, 10, "approved", f"صُدِّر {out.name}")
    else:
        studio_state.set_state(stem, 10, "awaiting_choice", "بانتظار معاينتك ثم التصدير النهائي")
    return {"mode": mode, "file": rel, "info": info, "cues": len(cues)}


def choose_ahat(script_path, track_id: str | None, duck_db: float = -14.0) -> dict:
    """بيثبّت الآهات المعتمدة للسيناريو (أو بيشيلها). بيبطّل المعاينة/التصدير القديمين."""
    stem = Path(script_path).stem
    tl = timeline.load(stem)
    if not tl:
        raise MontageError("ما في خط زمني")
    if track_id:
        import ahat
        t = ahat.get(track_id)
        if not t:
            raise MontageError("المقطع غير موجود")
        if not t.get("approved"):
            raise MontageError("المقطع مش معتمد بالسمع — اعتمده أول")
        tl["ambience"] = {"track_id": track_id, "approved": True, "duck_db": float(duck_db)}
    else:
        tl["ambience"] = None
    tl.pop("render", None)
    timeline.save(stem, tl)
    if studio_state.state_of(stem, 10) in ("approved", "awaiting_choice"):
        studio_state.set_state(stem, 10, "awaiting_choice", "تغيّرت الآهات — أعد المعاينة")
    return tl.get("ambience") or {}


def main() -> None:
    ap = argparse.ArgumentParser(description="مونتاج وتصدير")
    ap.add_argument("mode", choices=["preview", "final"])
    ap.add_argument("script")
    a = ap.parse_args()
    try:
        if a.mode == "final" and getattr(config, "MONTAGE_FINAL_ENGINE", "ffmpeg") == "remotion":
            import montage_advanced                  # المتقدّم أول، ولو فشل بنكمّل بالعادي (تصديرك السابق ما بينلمس)
            try:
                print(json.dumps(montage_advanced.run(a.script), ensure_ascii=False, indent=2, default=str))
                return
            except Exception as e:                   # أي فشل (مش بس MontageError): الإنتاج ما بيوقف
                print(f"[!] فشل المونتاج المتقدّم: {e}", flush=True)
                print("[…] برجع للتصدير العادي (ffmpeg)…", flush=True)
        print(json.dumps(render(a.script, a.mode), ensure_ascii=False, indent=2))
    except MontageError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
