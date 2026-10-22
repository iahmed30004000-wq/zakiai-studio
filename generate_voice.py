#!/usr/bin/env python3
"""
مرحلة الفويس أوفر — بتحوّل سيناريو مُعتمَد لملفات صوتية.

بتولّد مقطع لكل مشهد + ملف كامل مدموج، وبتقارن **المدة الفعلية** بالمخطّطة.
هالمقارنة هي الفايدة الأساسية: السيناريو بيقدّر المدة بحساب الكلمات، والصوت
الحقيقي بيطلع أطول أو أقصر — وهاد اللي بيكسر المونتاج إذا ما انكشف بدري.

    python generate_voice.py library/scripts/VARA__x__2026.json
    python generate_voice.py <script> --voice <id> --model eleven_v3
"""

import argparse
import json
import time
import subprocess
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config
import production_log
from config import LIBRARY_DIR
import review_loop
import tts

VOICE_DIR = Path(LIBRARY_DIR) / "voice"

# فرق مقبول بين المدة الفعلية والمخطّطة قبل ما ننبّه
DRIFT_WARN = 0.6


def concat(files: list[Path], out: Path) -> bool:
    """يدمج المقاطع بملف واحد عبر ffmpeg."""
    listing = out.parent / "_concat.txt"
    listing.write_text(
        "\n".join(f"file '{f.name}'" for f in files), encoding="utf-8"
    )
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", str(out)],
            cwd=str(out.parent), check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False
    finally:
        listing.unlink(missing_ok=True)


def _rel(p: str | Path) -> str:
    """مسار نسبي لجذر المكتبة (بلا مسار ويندوز مطلق بالمانيفست)."""
    try:
        return Path(p).resolve().relative_to(Path(config.LIBRARY_DIR).resolve()).as_posix()
    except ValueError:
        return Path(p).name


def _inherited_scenes(out_dir: Path, script: dict) -> set[int]:
    """مشاهد صوتها موروث من الفيديو الأساسي (نسخة هوك): inherited بالمانيفست + نصها نفس نص السيناريو + ملفها موجود.
    المشهد الموروث اللي نصه تغيّر أو ملفه ناقص بيتولّد من جديد عادي."""
    mf = out_dir / "voice.json"
    if not mf.exists():
        return set()
    try:
        old = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    want = {s.get("scene_number"): (s.get("voiceover") or "").strip() for s in script.get("scenes", [])}
    by = {s.get("scene"): s for s in old.get("scenes", [])}
    lib = Path(config.LIBRARY_DIR)
    out = set()
    for n in old.get("inherited") or []:
        e = by.get(n)
        if e and want.get(n) and str(e.get("text", "")).strip() == want[n] and (lib / str(e.get("path", ""))).is_file():
            out.add(n)
    return out


def _inherited_voice_defaults(out_dir: Path) -> dict:
    """صوت الفيديو الأساسي (مزوّد/موديل/صوت) كقيم افتراضية لمشهد النسخة، عشان الصوت يضل نفسه بين النسخ."""
    try:
        m = json.loads((out_dir / "voice.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for k in ("provider", "model", "voice"):
        v = str(m.get(k) or "")
        if v and v not in ("web", "mixed", "upload", "owner") and not v.startswith("extension:"):
            out[k] = v
    return out


def generate(path: Path, overrides: dict, scene: int | None = None,
             emotion_tags: bool = True, log=print) -> dict:
    """
    يولّد الصوت لكل مشهد (أو مشهد واحد) ويكتب voice.json مع **توقيت الكلمات**.
    بيرمي tts.TTSError / SystemExit-free: الأخطاء استثناءات عادية للمستدعي.
    """
    script = json.loads(Path(path).read_text(encoding="utf-8"))
    out_dir = Path(config.LIBRARY_DIR) / "voice" / Path(path).stem
    inherited = _inherited_scenes(out_dir, script) if not scene else set()       # نسخة هوك: مشاهد 2+ جاهزة
    if inherited:
        overrides = {**_inherited_voice_defaults(out_dir), **overrides}
    cfg = tts.tts_config(overrides)
    perf = tts.performance_note(cfg)
    log(f"[i] {cfg['provider']} · {cfg['model']} · صوت {cfg['voice']}")
    if perf:
        log(f"[i] الأداء: {perf}")

    out_dir.mkdir(parents=True, exist_ok=True)

    scenes = script.get("scenes", [])
    if scene:
        scenes = [s for s in scenes if s.get("scene_number") == scene]
        if not scenes:
            raise tts.TTSError(f"ما في مشهد رقم {scene}")
    if inherited:
        scenes = [s for s in scenes if s.get("scene_number") not in inherited]
        log(f"[i] صوت المشاهد {sorted(inherited)} موروث من الفيديو الأساسي — بنولّد الباقي بس")

    v3 = "v3" in str(cfg.get("model", ""))
    results, drifts = [], []
    for sc in scenes:
        n = sc.get("scene_number")
        text = (sc.get("voiceover") or "").strip()
        if not text:
            log(f"  [=] مشهد {n}: بدون كلام — متخطّى")
            continue

        # وسم الشعور: بس مع v3، وبس لو المالك ما حدّد نبرة بنفسه
        ov = dict(overrides)
        tag = ""
        if emotion_tags and v3 and not overrides.get("tone"):
            tag = tts.emotion_tag(sc.get("emotion"))
            if tag:
                ov["tone"] = tag

        target = out_dir / f"scene_{n:02d}.mp3"
        log(f"  [..] مشهد {n}…" + (f" [{tag}]" if tag else ""))
        t_tts = time.time()
        try:
            with tts.log_context(Path(path).stem, f"scene_{n}"):
                r = tts.speak(text, target, ov, want_timing=True)
        except tts.TTSError as e:
            if not getattr(e, "logged", False):                    # نموذج المكتبة: model_run سجّل المحاولة
                production_log.record("voice", "failed", script_stem=Path(path).stem, shot_id=f"scene_{n}", model_name=cfg["provider"],
                                      model_id=cfg.get("model"), path="api", seconds=time.time() - t_tts, error=str(e))
            raise
        if not r.get("logged"):
            production_log.record("voice", "ok", script_stem=Path(path).stem, shot_id=f"scene_{n}", model_name=cfg["provider"],
                                  model_id=cfg.get("model"), path="api", seconds=time.time() - t_tts)
        planned = float(sc.get("duration_sec") or 0)
        drift = round(r["duration_sec"] - planned, 2)
        r.update({"scene": n, "planned_sec": planned, "drift_sec": drift, "text": text,
                  "emotion_tag": tag, "path": _rel(r["path"])})
        results.append(r)
        if abs(drift) > DRIFT_WARN:
            drifts.append(r)
            sign = "أطول" if drift > 0 else "أقصر"
            log(f"       {r['duration_sec']}ث مقابل {planned}ث مخطّطة — {sign} بـ{abs(drift)}ث")
        else:
            log(f"       {r['duration_sec']}ث ✓")

    if not results:
        raise tts.TTSError("ما في ولا مقطع اتولّد")

    # الدمج بس لما نكون ولّدنا كل المشاهد
    combined = None
    all_with_vo = [s for s in script.get("scenes", []) if (s.get("voiceover") or "").strip()]
    if not scene and len(results) == len(all_with_vo):
        files = [out_dir / Path(r["path"]).name for r in sorted(results, key=lambda x: x["scene"])]
        full = out_dir / "full.mp3"
        if concat(files, full):
            combined = {"path": _rel(full), "duration_sec": tts.audio_duration(full)}

    total_actual = round(sum(r["duration_sec"] for r in results), 2)
    total_planned = round(sum(r["planned_sec"] for r in results), 2)

    manifest = {
        "script": Path(path).name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": cfg["provider"], "model": cfg["model"], "voice": cfg["voice"],
        "scenes": sorted(results, key=lambda x: x["scene"]),
        "total_actual_sec": total_actual,
        "total_planned_sec": total_planned,
        "total_drift_sec": round(total_actual - total_planned, 2),
        "scenes_off": [r["scene"] for r in drifts],
        "combined": combined,
    }
    mf = out_dir / "voice.json"
    # لو ولّدنا مشهد واحد (أو مشاهد النسخة غير الموروثة)، ادمج مع المانيفست القديم بدل ما نمسحه
    if (scene or inherited) and mf.exists():
        old = json.loads(mf.read_text(encoding="utf-8"))
        by_scene = {s["scene"]: s for s in old.get("scenes", [])}
        by_scene.update({r["scene"]: r for r in results})
        manifest["scenes"] = sorted(by_scene.values(), key=lambda x: x["scene"])
        manifest["total_actual_sec"] = round(sum(s["duration_sec"] for s in manifest["scenes"]), 2)
        # الدمج القديم صار قديم بعد تغيير مشهد — بنعيده
        files = [out_dir / Path(s["path"]).name for s in manifest["scenes"]]
        full = out_dir / "full.mp3"
        if all((f).exists() for f in files) and concat(files, full):
            manifest["combined"] = {"path": _rel(full), "duration_sec": tts.audio_duration(full)}
        else:
            manifest["combined"] = None
        if inherited:
            manifest["inherited"] = sorted(inherited)
            manifest["total_planned_sec"] = round(sum(s.get("planned_sec", 0) for s in manifest["scenes"]), 2)
            manifest["total_drift_sec"] = round(manifest["total_actual_sec"] - manifest["total_planned_sec"], 2)
            manifest["scenes_off"] = [s["scene"] for s in manifest["scenes"] if abs(s.get("drift_sec", 0)) > DRIFT_WARN]
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"[✓] {len(results)} مقطع | الفعلي {total_actual}ث مقابل {total_planned}ث مخطّطة")
    if drifts:
        log(f"    [!] {len(drifts)} مشهد فرقه أكبر من {DRIFT_WARN}ث — عدّل النص أو المدة")
    return manifest


def main() -> None:
    import job_signals
    job_signals.install()
    ap = argparse.ArgumentParser(description="توليد الفويس أوفر")
    ap.add_argument("script", help="مسار ملف السيناريو")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--voice")
    ap.add_argument("--speed", type=float)
    ap.add_argument("--gender", help="female / male")
    ap.add_argument("--age", help="young / adult / mature / senior")
    ap.add_argument("--dialect", help="ar-SY / ar-EG / ar-SA / ar-MA / ar-XA")
    ap.add_argument("--tone", help="warm / energetic / confident / intimate / urgent …")
    ap.add_argument("--instructions", help="تعليمة أداء حرة")
    ap.add_argument("--scene", type=int, help="ولّد مشهد واحد بس (لإعادة المحاولة)")
    ap.add_argument("--no-emotion-tags", action="store_true", help="بلا وسوم مشاعر (eleven_v3)")
    args = ap.parse_args()

    path = Path(args.script)
    if not path.exists():
        sys.exit(f"[!] السيناريو غير موجود: {path}")
    _ok, _why = review_loop.is_cleared(path)
    if not _ok:
        sys.exit(f"[!] ما بيشتغل: {_why}. الإنتاج بيبدأ بعد مراجعة بعوائق = 0 وبمحتوى ما انعدّل بعدها.")

    overrides = {k: v for k, v in {
        "provider": args.provider, "model": args.model, "voice": args.voice,
        "speed": args.speed, "gender": args.gender, "age": args.age,
        "dialect": args.dialect, "tone": args.tone, "instructions": args.instructions,
    }.items() if v}
    try:
        manifest = generate(path, overrides, args.scene, not args.no_emotion_tags)
    except tts.TTSError as e:
        sys.exit(f"[!] {e}")
    print(f"    {VOICE_DIR / path.stem}")


if __name__ == "__main__":
    main()
