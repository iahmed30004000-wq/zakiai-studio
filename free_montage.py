#!/usr/bin/env python3
"""
مونتاج «المشروع الحر» (ffmpeg): لقطات (صور بحركة بسيطة أو فيديوهات) + صوت كل مشهد + موسيقى + مؤثرات + ترجمة.

    python free_montage.py preview library/scripts/free__X.json     # معاينة بدقة مخفّضة
    python free_montage.py final   library/scripts/free__X.json     # 1080×1920 · 30 إطار · exports/<معرّف المشروع>.mp4

بلا قيود المهمة الموجّهة (7 مشاهد، 45–50 ث، ترتيب محطات). montage.py (مونتاج المهمة الموجّهة) ما بنلمسه:
بنستعير منه أدوات ما فيها منطق (probe، الخطوط، الترجمة بالكلمات، أبعاد الجودة).

  · كل لقطة ← مقطع بعدد إطارات دقيق، مخزّن بالكاش (render/segments/<لقطة>_<بصمة>.mp4)؛ تعديل لقطة بيعيد مقطعها بس.
  · المقاطع بتنجمع بـ concat (بلا إعادة ترميز)، وبعدين تمريرة أخيرة: ترجمة + صوت (صوت كل مشهد، موسيقى بخفض تحت الصوت، مؤثرات) + loudnorm.
  · كل تصدير بياخد بصمة المحتوى؛ لو اتغيّر شي بعده بتصير شارة «قديم» (stale) وبتعيد التصدير.
  · الترجمة: كلام الصوت (من توقيت كلمات صوت المشهد) تحت، ونص اللقطات فوق. النص بينظّف من أكواد ASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import montage
import timeline

VER = 1                                  # بيتغيّر لما تتغيّر طريقة الرندر (بيبطّل الكاش والبصمات القديمة)
FPS = montage.FPS
FINAL_SIZE = montage.FINAL_SIZE
PREVIEW_SIZE = montage.PREVIEW_SIZE
EPS_MS = montage.DURATION_EPS_MS
SAFE_BOTTOM = montage.SAFE_BOTTOM
ZOOM = 0.10                              # قد إيش بتقرّب/بتبعّد الصورة خلال اللقطة (10%)
MUSIC_DEFAULT_DB = -14.0
MUSIC_DB_RANGE = (-40.0, 0.0)
SFX_DB_RANGE = (-30.0, 6.0)
MAX_SFX = 20
MODES = ("preview", "final")


class FreeMontageError(montage.MontageError):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return montage._now()


def work_dir(stem: str) -> Path:
    return montage.work_dir(stem)


# ── المصادر ─────────────────────────────────────────────────────────────
def _voice_path(v: dict | None) -> Path | None:
    """ملف صوت المشهد (بالنسبة لمجلد المكتبة) لو موجود، وإلا None. ما بنقبل مسار برّا المكتبة."""
    rel = (v or {}).get("audio")
    if not rel:
        return None
    lib = Path(config.LIBRARY_DIR).resolve()
    p = (lib / rel).resolve()
    try:
        p.relative_to(lib)
    except ValueError:
        return None
    return p if p.is_file() else None


def sources(stem: str, tl: dict) -> dict[str, tuple[str, Path]]:
    """مصدر كل لقطة: فيديو (إذا إلها مقطع) أو صورة. بيرمي رسالة عربية فيها اللقطات الناقصة."""
    import image_studio
    import motion
    out: dict[str, tuple[str, Path]] = {}
    missing: list[str] = []
    for sc in tl.get("scenes") or []:
        for sh in sc.get("shots") or []:
            clip = (sh.get("motion") or {}).get("clip")
            img = (sh.get("image") or {}).get("chosen")
            cp = motion.abs_of(stem, clip) if clip else None
            ip = image_studio.abs_of(stem, img) if img else None
            if cp and cp.exists():
                out[sh["id"]] = ("video", cp)
            elif ip and ip.exists():
                out[sh["id"]] = ("image", ip)
            else:
                missing.append(sh["id"])
    if missing:
        raise FreeMontageError(f"ما في صورة أو فيديو للقطات: {'، '.join(missing[:6])}{' …' if len(missing) > 6 else ''} — ارفع أو ولّد لكل لقطة")
    return out


def sounds(tl: dict) -> tuple[tuple[Path, float] | None, list[dict]]:
    """الموسيقى (ملف + مستوى dB) والمؤثرات [{path, at_ms, gain_db}] — المعتمدة بالسمع بس."""
    import ahat
    music = None
    amb = tl.get("ambience") or {}
    if amb.get("track_id"):
        t = ahat.get(amb["track_id"])
        if not t or not t.get("approved"):
            raise FreeMontageError("الموسيقى المختارة مش معتمدة بالسمع — اعتمدها من «الأصوات» أول")
        p = ahat.audio_path(amb["track_id"])
        if not p:
            raise FreeMontageError("ملف الموسيقى ناقص")
        music = (p, float(amb.get("duck_db", MUSIC_DEFAULT_DB)))
    fx: list[dict] = []
    for e in tl.get("sfx") or []:
        t = ahat.get(e.get("track_id") or "")
        if not t or not t.get("approved"):
            raise FreeMontageError(f"المؤثر «{(t or {}).get('name') or e.get('track_id')}» مش معتمد بالسمع")
        p = ahat.audio_path(e["track_id"])
        if not p:
            raise FreeMontageError(f"ملف المؤثر «{t.get('name')}» ناقص")
        fx.append({"path": p, "at_ms": int(e.get("at_ms") or 0), "gain_db": float(e.get("gain_db") or 0.0)})
    return music, fx


# ── البصمة (هل التصدير قديم؟) ────────────────────────────────────────────
def _stat(p: Path | None):
    try:
        st = p.stat()                    # type: ignore[union-attr]
        return [p.name, st.st_size, int(st.st_mtime)]      # type: ignore[union-attr]
    except (OSError, AttributeError):
        return None


def fingerprint(stem: str, tl: dict, mode: str, size: tuple[int, int] | None = None) -> str:
    """بصمة كل شي بيأثر على الناتج: البنية والمدد والنصوص وملفات الوسائط والصوت والموسيقى والمؤثرات والجودة."""
    import ahat
    import image_studio
    import motion
    size = size or (PREVIEW_SIZE if mode == "preview" else FINAL_SIZE)
    scenes = []
    for sc in tl.get("scenes") or []:
        shots = []
        for sh in sc.get("shots") or []:
            clip = (sh.get("motion") or {}).get("clip")
            img = (sh.get("image") or {}).get("chosen")
            shots.append([sh.get("id"), sh.get("start_ms"), sh.get("end_ms"), sh.get("trim_in_ms", 0), bool(sh.get("keep_audio")),
                          sh.get("still_motion"), sh.get("text") or "", _stat(motion.abs_of(stem, clip) if clip else None),
                          _stat(image_studio.abs_of(stem, img) if img else None)])
        voice = sc.get("voice") or {}
        scenes.append([sc.get("key"), sc.get("start_ms"), sc.get("end_ms"), _stat(_voice_path(voice)), shots,
                       hashlib.sha1(json.dumps(voice.get("words") or [], ensure_ascii=False).encode("utf-8")).hexdigest()[:8]])
    amb = tl.get("ambience") or {}

    def track(tid):                                       # الملف + هل لسا معتمد (سحب الاعتماد بيخلّي التصدير «قديم»)
        return [_stat(ahat.audio_path(tid)), bool((ahat.get(tid) or {}).get("approved"))] if tid and re.fullmatch(r"ah_\d{3}", str(tid)) else None
    music = [amb.get("track_id"), amb.get("duck_db"), track(amb.get("track_id"))] + ([True] if amb.get("beat_snap") else [])
    fx = [[e.get("track_id"), e.get("at_ms"), e.get("gain_db"), track(e.get("track_id"))] for e in tl.get("sfx") or []]
    raw = json.dumps([VER, mode, list(size), scenes, tl.get("captions_opts") or {}, music, fx], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def render_state(path, tl: dict | None = None) -> dict:
    """حالة المعاينة والتصدير للواجهة: {preview|final: {…، exists، stale}} (غير موجود = مش مذكور)."""
    stem = Path(path).stem
    tl = tl if tl is not None else (timeline.load(stem) or {})
    out: dict = {}
    for mode in MODES:
        rec = (tl.get("render") or {}).get(mode)
        if not rec:
            continue
        f = Path(config.LIBRARY_DIR) / rec["file"]
        try:
            stale = rec.get("fingerprint") != fingerprint(stem, tl, mode, tuple(rec.get("size") or ()) or None)
        except Exception:                                   # noqa: BLE001 — الحالة معلومة مساعدة، ما بتوقف اللوحة
            stale = True
        out[mode] = {**rec, "exists": f.is_file(), "stale": stale}
    return out


# ── الترجمة ─────────────────────────────────────────────────────────────
def ass_text(s) -> str:
    """نص آمن جوّا سطر Dialogue: بلا أكواد {…} ولا شرطات \\ ولا أسطر جديدة."""
    t = re.sub(r"[{}\\]", "", str(s or ""))
    return re.sub(r"\s+", " ", t).strip()


def cues_of(tl: dict) -> tuple[list[dict], list[dict]]:
    """(ترجمة كلام الصوت، نص اللقطات) حسب خيارات المالك."""
    opts = tl.get("captions_opts") or {}
    voice: list[dict] = []
    if opts.get("voice", True) and tl.get("words"):
        voice = [{**c, "text": ass_text(c["text"])} for c in montage.build_cues(tl) if ass_text(c["text"])]
    text: list[dict] = []
    if opts.get("shot_text", True):
        for sc in tl.get("scenes") or []:
            for sh in sc.get("shots") or []:
                t = ass_text(sh.get("text"))
                if t:
                    text.append({"start_ms": int(sh["start_ms"]), "end_ms": int(sh["end_ms"]), "text": t})
    return voice, text


def write_ass(voice: list[dict], text: list[dict], path: Path, size: tuple[int, int]) -> None:
    w, h = size
    ml, mv = round(w * montage.SAFE_SIDE), round(h * SAFE_BOTTOM)
    top = round(h * 0.12)
    ol = max(2, round(3 * h / 1920))
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Voice,Tahoma,{round(64 * h / 1920)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{ol},0,2,{ml},{ml},{mv},1\n"
        f"Style: Text,Tahoma,{round(72 * h / 1920)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{ol + 1},0,8,{ml},{ml},{top},1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = [f"Dialogue: 0,{montage._ts(c['start_ms'])},{montage._ts(c['end_ms'])},Voice,,0,0,0,,{c['text']}" for c in voice]
    lines += [f"Dialogue: 1,{montage._ts(c['start_ms'])},{montage._ts(c['end_ms'])},Text,,0,0,0,,{c['text']}" for c in text]
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ── ffmpeg ──────────────────────────────────────────────────────────────
def _run(cmd: list[str], cwd: Path, what: str) -> None:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise FreeMontageError(f"فشل ffmpeg ({what}): " + (r.stderr or "")[-400:])


def _frames(sh: dict) -> int:
    """عدد إطارات اللقطة: بالتراكم من حدود الـ ms (مجموع الإطارات = مجموع الفيديو بلا انحراف)."""
    return max(1, round(int(sh["end_ms"]) * FPS / 1000) - round(int(sh["start_ms"]) * FPS / 1000))


def _seg_key(kind: str, src: Path, sh: dict, size: tuple[int, int], n: int) -> str:
    st = src.stat()
    raw = "|".join(str(x) for x in (VER, kind, src.name, st.st_size, int(st.st_mtime), sh.get("trim_in_ms") or 0,
                                    sh.get("still_motion") or "zoom_in", size, n, FPS))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def segment_command(kind: str, src: Path, sh: dict, size: tuple[int, int], n: int, out: Path) -> list[str]:
    W, H = size
    small = W <= 540
    enc = ["-an", "-c:v", "libx264", "-preset", "ultrafast" if small else "veryfast", "-crf", "20" if small else "14",
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-frames:v", str(n), "-movflags", "+faststart", str(out)]
    fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    d_s = n / FPS
    if kind == "video":
        clip_s = (montage.probe(src).get("duration_ms") or 0) / 1000
        trim = max(0.0, min(float(sh.get("trim_in_ms") or 0) / 1000, max(0.0, clip_s - 0.2)))
        pad = max(0.0, d_s - max(0.0, clip_s - trim)) + 0.5            # فيديو أقصر من اللقطة: بيتجمّد آخر كادر
        vf = f"{fit},fps={FPS},tpad=stop_mode=clone:stop_duration={pad:.3f}"
        return ["ffmpeg", "-y", "-ss", f"{trim:.3f}", "-i", str(src), "-vf", vf] + enc
    mo = sh.get("still_motion") or "zoom_in"
    if mo == "none":
        return ["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(src), "-vf", f"{fit},format=yuv420p"] + enc
    z = f"1+{ZOOM}*on/{n}" if mo == "zoom_in" else f"{1 + ZOOM:g}-{ZOOM}*on/{n}"
    vf = (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,crop={2 * W}:{2 * H},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
    return ["ffmpeg", "-y", "-i", str(src), "-vf", vf] + enc


def make_segment(wd: Path, sh: dict, kind: str, src: Path, size: tuple[int, int]) -> tuple[Path, bool]:
    """(مسار المقطع، من الكاش؟). بيكتب لملف مؤقت وبيبدّل ذرّياً عشان ما ينقبل مقطع ناقص."""
    n = _frames(sh)
    d = wd / "segments"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{sh['id']}_{_seg_key(kind, src, sh, size, n)}.mp4"
    if out.is_file() and out.stat().st_size > 0:
        return out, True
    part = d / f"{out.stem}.part.mp4"
    try:
        _run(segment_command(kind, src, sh, size, n, part), wd, f"لقطة {sh['id']}")
        os.replace(part, out)
    finally:
        part.unlink(missing_ok=True)
    return out, False


def lane_command(tl: dict, srcs: dict[str, tuple[str, Path]], out: Path) -> tuple[list[str], bool]:
    """مسار الصوت الأساسي: صوت كل مشهد بمكانه بالضبط (أو صمت)، + صوت الفيديوهات اللي المالك حابب يبقيه. (أمر، في صوت؟)"""
    scenes = tl["scenes"]
    cmd = ["ffmpeg", "-y"]
    parts: list[str] = []
    labels: list[str] = []
    idx = 0
    has_voice = False
    for i, sc in enumerate(scenes):
        dur = (int(sc["end_ms"]) - int(sc["start_ms"])) / 1000
        vp = _voice_path(sc.get("voice"))
        if vp:
            cmd += ["-i", str(vp)]
            parts.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={dur:.3f},atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[s{i}]")
            idx += 1
            has_voice = True
        else:
            parts.append(f"anullsrc=r=48000:cl=stereo:d={dur:.3f}[s{i}]")
        labels.append(f"[s{i}]")
    parts.append("".join(labels) + f"concat=n={len(scenes)}:v=0:a=1[lane0]")
    kept: list[str] = []
    for sc in scenes:
        for sh in sc["shots"]:
            kind, src = srcs[sh["id"]]
            if not (sh.get("keep_audio") and kind == "video" and montage.probe(src).get("has_audio")):
                continue
            dur = (int(sh["end_ms"]) - int(sh["start_ms"])) / 1000
            trim = max(0.0, float(sh.get("trim_in_ms") or 0) / 1000)
            at = int(sh["start_ms"])
            cmd += ["-ss", f"{trim:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
            parts.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={dur:.3f},atrim=0:{dur:.3f},"
                         f"asetpts=PTS-STARTPTS,adelay={at}|{at}[k{len(kept)}]")
            kept.append(f"[k{len(kept)}]")
            idx += 1
            has_voice = True
    if kept:
        parts.append("[lane0]" + "".join(kept) + f"amix=inputs={1 + len(kept)}:duration=first:normalize=0[lane]")
    else:
        parts.append("[lane0]anull[lane]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[lane]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)]
    return cmd, has_voice


def final_command(video: Path, lane: Path, music, fx: list[dict], has_voice: bool, out: Path, size: tuple[int, int], dur_s: float,
                  preview: bool, burn: bool, fonts_opt: str) -> list[str]:
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(lane)]
    parts: list[str] = []
    n = 2
    if music:
        cmd += ["-i", str(music[0])]
        mi, vol = n, round(10 ** (music[1] / 20), 3)
        n += 1
        parts.append(f"[1:a]aresample=48000,asplit=2[ls][lm]" if has_voice else "[1:a]aresample=48000[lm]")
        parts.append(f"[{mi}:a]aresample=48000,aformat=channel_layouts=stereo,aloop=loop=-1:size=2000000000,atrim=0:{dur_s:.3f},"
                     f"asetpts=PTS-STARTPTS,volume={vol},afade=t=in:d=1,afade=t=out:st={max(0.0, dur_s - 1.5):.3f}:d=1.5[amb]")
        if has_voice:                                     # الموسيقى بتنخفض تحت الصوت
            parts.append("[amb][ls]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=400[duck]")
            parts.append("[lm][duck]amix=inputs=2:duration=first:normalize=0[m0]")
        else:
            parts.append("[lm][amb]amix=inputs=2:duration=first:normalize=0[m0]")
        base = "[m0]"
    else:
        parts.append("[1:a]aresample=48000[m0]")
        base = "[m0]"
    tags = []
    for j, e in enumerate(fx):
        cmd += ["-i", str(e["path"])]
        at = int(e["at_ms"])
        parts.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={e['gain_db']:.1f}dB,adelay={at}|{at}[x{j}]")
        tags.append(f"[x{j}]")
        n += 1
    if tags:
        parts.append(base + "".join(tags) + f"amix=inputs={1 + len(tags)}:duration=first:normalize=0[mix]")
    else:
        parts.append(f"{base}anull[mix]")
    audible = bool(music) or bool(fx) or has_voice
    parts.append("[mix]loudnorm=I=-16:TP=-1.5:LRA=11[a]" if audible else "[mix]anull[a]")
    if burn:
        parts.append(f"[0:v]subtitles=captions.ass{fonts_opt}[v]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]" if burn else "0:v", "-map", "[a]", "-t", f"{dur_s:.3f}"]
    if burn:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast" if preview else "medium", "-crf", "28" if preview else "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    return cmd


# ── الرندر ──────────────────────────────────────────────────────────────
def preflight(path) -> dict:
    """فحص سريع قبل ما نبدأ مهمة: لقطات ناقصة؟ مشروع فاضي؟ (بيرمي رسالة عربية)."""
    import studio_gate
    p = Path(path)
    if not studio_gate.is_free(p):
        raise FreeMontageError("هاد مش مشروع حر — مونتاج المهمة الموجّهة غير هيك")
    tl = timeline.load(p.stem)
    if not tl or not timeline.is_free(tl) or not any(sc.get("shots") for sc in tl.get("scenes") or []):
        raise FreeMontageError("ما في لقطات — ضيف مشاهد وصور أو فيديوهات أول")
    sources(p.stem, tl)
    sounds(tl)
    return {"scenes": len(tl["scenes"]), "length_ms": tl["length_ms"]}


def render(script_path, mode: str = "preview", size: tuple[int, int] | None = None, log=print) -> dict:
    if mode not in MODES:
        raise FreeMontageError("الوضع: preview أو final")
    path = Path(script_path)
    stem = path.stem
    preflight(path)
    tl = timeline.load(stem)
    srcs = sources(stem, tl)
    music, fx = sounds(tl)
    size = size or (PREVIEW_SIZE if mode == "preview" else FINAL_SIZE)
    total_ms = int(tl["length_ms"])
    fp = fingerprint(stem, tl, mode, size)                 # بصمة اللقطة وقت البدء: أي تعديل بعدها بيخلّي التصدير «قديم»
    if music and (tl.get("ambience") or {}).get("beat_snap"):
        import beats                                       # القص على الإيقاع: حدود اللقطات جوّا المشهد على أقرب ضربة
        info = beats.detect(music[0])
        tl, moved = beats.snap_timeline(tl, beats.looped(info, total_ms))
        log(f"[…] إيقاع الموسيقى {info['bpm']:g} ضربة/دقيقة · {moved} قطع انزاح على الضربة")
    shots = [sh for sc in tl["scenes"] for sh in sc["shots"]]
    wd = work_dir(stem)
    wd.mkdir(parents=True, exist_ok=True)
    log(f"[…] {mode}: {len(shots)} لقطة · {len(tl['scenes'])} مشهد · {size[0]}x{size[1]} · {total_ms / 1000:.1f}ث")

    segs: list[Path] = []
    reused = 0
    for i, sh in enumerate(shots, 1):
        kind, src = srcs[sh["id"]]
        seg, cached = make_segment(wd, sh, kind, src, size)
        reused += int(cached)
        segs.append(seg)
        log(f"  [{i}/{len(shots)}] لقطة {sh['id']} ({'فيديو' if kind == 'video' else 'صورة'})" + (" — من الكاش" if cached else ""))
    seg_dir = wd / "segments"
    (seg_dir / f"list_{mode}.txt").write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    video = wd / f"video_{mode}.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"segments/list_{mode}.txt", "-c", "copy", "-movflags", "+faststart", video.name],
         wd, "دمج المقاطع")

    lane = wd / f"lane_{mode}.wav"
    cmd, has_voice = lane_command(tl, srcs, lane.resolve())
    _run(cmd, wd, "مسار الصوت")

    vcues, tcues = cues_of(tl)
    burn = bool(vcues or tcues)
    if burn:
        write_ass(vcues, tcues, wd / "captions.ass", size)
    sid = montage._safe_name(tl.get("script_id") or (json.loads(path.read_text(encoding="utf-8")).get("_meta") or {}).get("script_id") or stem)
    if mode == "final":
        montage.exports_dir().mkdir(parents=True, exist_ok=True)
        out = montage.exports_dir() / f"{sid}.mp4"
    else:
        out = wd / "preview.mp4"
    part = out.with_name(out.stem + ".part.mp4")
    try:
        _run(final_command(video, lane, music, fx, has_voice, part.resolve(), size, total_ms / 1000, mode == "preview", burn,
                           montage._prepare_fonts(wd) if burn else ""), wd, "التمريرة الأخيرة")
        os.replace(part, out)
    finally:
        part.unlink(missing_ok=True)

    info = montage.probe(out)
    problems = []
    if (info.get("width"), info.get("height")) != size:
        problems.append(f"الأبعاد {info.get('width')}x{info.get('height')} ≠ {size[0]}x{size[1]}")
    if abs(info.get("duration_ms", 0) - total_ms) > EPS_MS:
        problems.append(f"المدة {info.get('duration_ms')}ms ≠ مدة المشروع {total_ms}ms")
    if not info.get("has_audio"):
        problems.append("بلا مسار صوت")
    if abs(info.get("fps", 0) - FPS) > 0.5:
        problems.append(f"معدل الإطارات {info.get('fps'):.1f} ≠ {FPS}")
    if problems:
        out.unlink(missing_ok=True)
        raise FreeMontageError("الناتج ما طابق المواصفات: " + "؛ ".join(problems))

    rel = out.resolve().relative_to(Path(config.LIBRARY_DIR).resolve()).as_posix()
    tl2 = timeline.load(stem)                              # إعادة قراءة: المالك ممكن عدّل أثناء الرندر
    tl2.setdefault("render", {})[mode] = {"file": rel, "at": _now(), "size": list(size), "duration_ms": info["duration_ms"], "fingerprint": fp,
                                          "cues": {"voice": len(vcues), "text": len(tcues)}, "music": bool(music), "sfx": len(fx),
                                          "segments": {"total": len(segs), "cached": reused}}
    timeline.save(stem, tl2)
    if mode == "final":                                    # المشروع الحر ما إلو محطات: التصدير النهائي هو لحظة درايف
        import drive_sync
        drive_sync.request_ad(stem)
    return {"mode": mode, "file": rel, "info": info, "cues": {"voice": len(vcues), "text": len(tcues)}, "segments": {"total": len(segs), "cached": reused}}


# ── إعدادات المونتاج (من الواجهة) ────────────────────────────────────────
def save_settings(script_path, payload: dict) -> dict:
    """بيحفظ خيارات المونتاج: {captions:{voice,shot_text}, music:{track_id,level_db}|null, sfx:[{track_id,at_ms,gain_db}]}.
    المفاتيح الغايبة ما بتتغيّر. الأصوات لازم تكون معتمدة بالسمع. بيرمي free_project.FreeError (400/409) برسالة عربية."""
    import ahat
    import free_project
    FE = free_project.FreeError
    if not isinstance(payload, dict):
        raise FE("شكل غير صحيح")
    path = Path(script_path)
    with free_project._LOCK:
        tl = free_project._load(path)
        if "captions" in payload:
            c = payload["captions"]
            if not isinstance(c, dict):
                raise FE("خيارات الكتابة غير صحيحة")
            opts = dict(tl.get("captions_opts") or {})
            for k in ("voice", "shot_text"):
                if k in c:
                    opts[k] = bool(c[k])
            tl["captions_opts"] = opts
        if "music" in payload:
            m = payload["music"]
            if not m:
                tl["ambience"] = None
            else:
                if not isinstance(m, dict) or not m.get("track_id"):
                    raise FE("اختار مقطع الموسيقى")
                t = ahat.get(str(m["track_id"])) if re.fullmatch(r"ah_\d{3}", str(m["track_id"])) else None
                if not t:
                    raise FE("المقطع غير موجود", 404)
                if not t.get("approved"):
                    raise FE("المقطع مش معتمد بالسمع — اعتمده أول", 409)
                try:
                    lvl = float(m.get("level_db", MUSIC_DEFAULT_DB))
                except (TypeError, ValueError):
                    raise FE("مستوى الموسيقى لازم يكون رقم")
                if not MUSIC_DB_RANGE[0] <= lvl <= MUSIC_DB_RANGE[1]:
                    raise FE(f"مستوى الموسيقى بين {MUSIC_DB_RANGE[0]:g} و{MUSIC_DB_RANGE[1]:g} dB")
                tl["ambience"] = {"track_id": t["id"], "approved": True, "duck_db": round(lvl, 1)}
                if m.get("beat_snap"):                     # القص على الإيقاع (بينحفظ بس لما يكون مفعّل)
                    tl["ambience"]["beat_snap"] = True
        if "sfx" in payload:
            rows = payload["sfx"]
            if not isinstance(rows, list):
                raise FE("المؤثرات لازم قائمة")
            if len(rows) > MAX_SFX:
                raise FE(f"أكتر من {MAX_SFX} مؤثر")
            fx = []
            for i, e in enumerate(rows, 1):
                if not isinstance(e, dict):
                    raise FE(f"مؤثر {i}: شكل غير صحيح")
                tid = str(e.get("track_id") or "")
                t = ahat.get(tid) if re.fullmatch(r"ah_\d{3}", tid) else None
                if not t:
                    raise FE(f"مؤثر {i}: المقطع غير موجود", 404)
                if not t.get("approved"):
                    raise FE(f"مؤثر {i}: «{t.get('name')}» مش معتمد بالسمع — اعتمده أول", 409)
                try:
                    at = int(round(float(e.get("at_ms"))))
                    gain = float(e.get("gain_db", 0))
                except (TypeError, ValueError):
                    raise FE(f"مؤثر {i}: الوقت والمستوى لازم يكونوا أرقام")
                if not 0 <= at < max(1, int(tl.get("length_ms") or 0)):
                    raise FE(f"مؤثر {i}: الوقت لازم يكون ضمن مدة المشروع (0–{int(tl.get('length_ms') or 0) / 1000:.1f}ث)")
                if not SFX_DB_RANGE[0] <= gain <= SFX_DB_RANGE[1]:
                    raise FE(f"مؤثر {i}: المستوى بين {SFX_DB_RANGE[0]:g} و{SFX_DB_RANGE[1]:g} dB")
                fx.append({"track_id": t["id"], "at_ms": at, "gain_db": round(gain, 1)})
            tl["sfx"] = sorted(fx, key=lambda x: x["at_ms"])
        free_project._save(path, tl, bump=False)
    return free_project.board(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="مونتاج المشروع الحر")
    ap.add_argument("mode", choices=list(MODES))
    ap.add_argument("script")
    a = ap.parse_args()
    try:
        print(json.dumps(render(a.script, a.mode, log=lambda m, **k: print(m, flush=True)), ensure_ascii=False, indent=2))
    except montage.MontageError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
