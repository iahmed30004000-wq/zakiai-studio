#!/usr/bin/env python3
"""
المحطتان ٤ و٥: الفويس أوفر بوابة المدة، والخط الزمني.

    python voice_studio.py produce library/scripts/X.json     # توليد + بوابة ٤٥–٥٠ + تعديل نص تلقائي
    python voice_studio.py approve library/scripts/X.json     # اعتماد سمعي ← بناء الخط الزمني

الصوت هو الساعة: ما في صورة ولا لقطة قبل صوت معتمد بمدة ٤٥–٥٠ ثانية.
تعديل النص لضبط المدة بيغيّر السيناريو، فبيبطّل مراجعته — بيرجع لحلقة المراجعة (عوائق = ٠)
قبل ما نولّد صوت من جديد.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import studio_state
import timeline


class VoiceGateError(Exception):
    """سبب عربي جاهز للعرض."""


def _voice_dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "voice" / stem


def load_manifest(stem: str) -> dict | None:
    p = _voice_dir(stem) / "voice.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def approval_path(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "studio" / stem / "voice_approval.json"


# ── بوابة المدة ─────────────────────────────────────────────────────────
def check_duration(total_sec: float) -> dict:
    lo, hi = float(config.SCRIPT_MIN_SEC), float(config.SCRIPT_MAX_SEC)
    total = round(float(total_sec), 2)
    if total < lo:
        return {"ok": False, "total_sec": total, "min": lo, "max": hi,
                "direction": "short", "delta_sec": round(lo - total, 2),
                "message": f"الصوت {total}ث أقصر من {lo:g}ث بـ {round(lo - total, 1)}ث"}
    if total > hi:
        return {"ok": False, "total_sec": total, "min": lo, "max": hi,
                "direction": "long", "delta_sec": round(total - hi, 2),
                "message": f"الصوت {total}ث أطول من {hi:g}ث بـ {round(total - hi, 1)}ث"}
    return {"ok": True, "total_sec": total, "min": lo, "max": hi, "direction": None,
            "delta_sec": 0.0, "message": f"المدة {total}ث ضمن {lo:g}–{hi:g}ث"}


def _content_hash(script: dict) -> str:
    import script_versions
    return script_versions.content_hash(script)


def _duration_finding(script: dict, manifest: dict, chk: dict) -> dict:
    """ملاحظة اصطناعية بنمرّرها لإعادة الكتابة الموجودة، بنفس شكل ملاحظات المراجِع."""
    total = manifest["total_actual_sec"]
    words = sum(len(str(s.get("text", "")).split()) for s in manifest["scenes"]) or 1
    rate = words / total if total else 2.4
    target = (chk["min"] + chk["max"]) / 2
    delta_words = round(abs(target - total) * rate)
    verb = "قصّر" if chk["direction"] == "long" else "أطِل"
    return {
        "severity": "major", "scene": None, "field": "voiceover",
        "issue": f"مدة الصوت الفعلية {total}ث والمطلوب {chk['min']:g}–{chk['max']:g}ث",
        "evidence": f"{words} كلمة بمعدل {rate:.2f} كلمة/ث",
        "fix": (f"{verb} الفويس أوفر بحوالي {delta_words} كلمة إجمالاً (والهدف قرابة {target:g}ث) "
                "موزّعة على مشهدين أو تلاتة، بدون تغيير الخطّاف ولا الوعد ولا القواعد الصارمة"),
    }


def adjust_text(script_path: Path, manifest: dict, chk: dict, log=print) -> None:
    """يعدّل نص السيناريو لضبط المدة عبر إعادة الكتابة الموجودة (نسخة +١ ونسخة سابقة محفوظة)."""
    import stage3_generate
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    finding = _duration_finding(script, manifest, chk)
    review = {"verdict": "revise", "blockers": 0, "major": 1, "minor": 0,
              "findings": [finding], "summary": finding["issue"]}
    log(f"    [تعديل] {finding['fix']}")
    stage3_generate.rewrite_from_review(script_path, review)


# ── الإنتاج ─────────────────────────────────────────────────────────────
def produce(script_path, overrides: dict | None = None, *, max_rounds: int | None = None,
            log=print) -> dict:
    """
    يولّد الصوت ويفرض بوابة المدة. خارج ٤٥–٥٠ ← تعديل نص ← مراجعة ← صوت جديد
    (حتى `STUDIO_VOICE_MAX_ROUNDS` دورات)، وبعدها needs_owner.
    """
    import generate_voice
    import review_loop
    import tts

    path = Path(script_path)
    stem = path.stem
    limit = config.STUDIO_VOICE_MAX_ROUNDS if max_rounds is None else max_rounds
    import characters
    # صوت الشخصية المختارة ثابت — اختيار المالك الصريح بالواجهة بيتغلّب عليه
    overrides = {**characters.voice_overrides(stem), **(overrides or {})}

    rounds = 0
    while True:
        ok, why = review_loop.is_cleared(path)
        if not ok:
            studio_state.set_state(stem, 4, "failed", why)
            raise VoiceGateError(why)
        studio_state.derive_early(stem, path)
        try:
            studio_state.set_state(stem, 4, "running", f"توليد الصوت (تعديلات النص حتى الآن {rounds}/{limit})")
        except studio_state.StationBlocked as e:
            raise VoiceGateError(str(e))

        try:
            manifest = generate_voice.generate(path, overrides, log=log)
        except tts.TTSError as e:
            studio_state.set_state(stem, 4, "failed", str(e))
            raise VoiceGateError(str(e))

        chk = check_duration(manifest["total_actual_sec"])
        log(f"[بوابة المدة] {chk['message']}")
        if chk["ok"]:
            studio_state.set_state(stem, 4, "awaiting_choice",
                                   "بانتظار اعتماد المالك سمعياً — " + chk["message"])
            return {"status": "awaiting_owner_approval", "gate": chk, "rounds": rounds}

        if rounds >= limit:
            why = f"{chk['message']} بعد {rounds} تعديلات نص — يحتاج قرارك"
            studio_state.set_state(stem, 4, "failed", why)
            return {"status": "needs_owner", "gate": chk, "rounds": rounds, "reason": why}

        try:
            adjust_text(path, manifest, chk, log=log)
            res = review_loop.run(path)
        except Exception as e:                       # فشل الكتابة/المراجعة = رفع للمالك
            why = f"تعذّر ضبط المدة تلقائياً: {e}"
            studio_state.set_state(stem, 4, "failed", why)
            return {"status": "needs_owner", "gate": chk, "rounds": rounds, "reason": why}
        rounds += 1
        if not res.get("approved"):
            why = f"بعد تعديل النص المراجعة ما اعتمدته: {res.get('reason')}"
            studio_state.set_state(stem, 4, "failed", why)
            return {"status": "needs_owner", "gate": chk, "rounds": rounds, "reason": why}
        # الصوت القديم صار للنص القديم — بنولّد من جديد بالحلقة


# ── الاعتماد وبناء الخط الزمني ──────────────────────────────────────────
def voice_is_approved(script_path) -> tuple[bool, str]:
    """صوت معتمد لنفس نص السيناريو الحالي؟ (شرط أي محطة بعد ٤)."""
    path = Path(script_path)
    ap = approval_path(path.stem)
    if not ap.exists():
        return False, "ما في صوت معتمد لهالسيناريو"
    rec = json.loads(ap.read_text(encoding="utf-8"))
    script = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("script_hash") != _content_hash(script):
        return False, "نص السيناريو انعدّل بعد اعتماد الصوت — لازم صوت جديد"
    return True, ""


def approve_voice(script_path, by: str = "owner") -> dict:
    """اعتماد المالك للصوت (بعد السمع). بيبني الخط الزمني ويتحقق منه."""
    import review_loop
    path = Path(script_path)
    stem = path.stem
    ok, why = review_loop.is_cleared(path)
    if not ok:
        raise VoiceGateError(why)
    manifest = load_manifest(stem)
    if not manifest:
        raise VoiceGateError("ما في صوت مولّد بعد")
    script = json.loads(path.read_text(encoding="utf-8"))

    vo_scenes = {s["scene_number"] for s in script.get("scenes", []) if (s.get("voiceover") or "").strip()}
    have = {s["scene"] for s in manifest["scenes"]}
    if vo_scenes - have:
        raise VoiceGateError(f"مشاهد بلا صوت: {sorted(vo_scenes - have)}")
    # الصوت لازم يكون لنفس نص السيناريو الحالي
    said = {s["scene"]: s.get("text", "").strip() for s in manifest["scenes"]}
    for sc in script["scenes"]:
        n = sc["scene_number"]
        if (sc.get("voiceover") or "").strip() and said.get(n) != sc["voiceover"].strip():
            raise VoiceGateError(f"مشهد {n}: الصوت لنص قديم — ولّد الصوت من جديد")

    chk = check_duration(manifest["total_actual_sec"])
    if not chk["ok"]:
        raise VoiceGateError(chk["message"])

    audio_rel = (manifest.get("combined") or {}).get("path")
    sha = ""
    if audio_rel:
        f = Path(config.LIBRARY_DIR) / audio_rel
        if f.exists():
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script_hash = _content_hash(script)

    tl = timeline.build(script, manifest, script_hash=script_hash, audio_rel=audio_rel or "",
                        approved_at=now, audio_sha256=sha)
    inherited_shots = 0
    if (script.get("_meta") or {}).get("hook_of"):                 # نسخة هوك: لقطات مشاهد 2+ بتتورّث من الفيديو الأساسي
        import hook_versions
        inherited_shots = hook_versions.overlay_timeline(stem, tl, script)
    res = timeline.validate(tl)

    ap = approval_path(stem)
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps({"approved_at": now, "by": by, "script_hash": script_hash,
                              "audio": audio_rel, "sha256": sha,
                              "duration_sec": manifest["total_actual_sec"]},
                             ensure_ascii=False, indent=2), encoding="utf-8")
    studio_state.set_state(stem, 4, "approved", "اعتمد المالك الصوت", by=by)

    if res["ok"]:
        timeline.save(stem, tl)
        studio_state.set_state(stem, 5, "approved", "الخط الزمني نظيف")
    else:
        timeline.save(stem, tl, allow_invalid=True)
        studio_state.set_state(stem, 5, "failed",
                               " | ".join(e["message"] for e in res["errors"][:3]))
    return {"approved": True, "timeline_ok": res["ok"], "errors": res["errors"],
            "warnings": res["warnings"], "timing_source": tl["voice"]["timing_source"],
            "inherited_shots": inherited_shots}


def main() -> None:
    ap = argparse.ArgumentParser(description="الفويس أوفر + الخط الزمني")
    ap.add_argument("action", choices=["produce", "approve"])
    ap.add_argument("script")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--voice")
    ap.add_argument("--max-rounds", type=int)
    args = ap.parse_args()
    ov = {k: v for k, v in {"provider": args.provider, "model": args.model,
                            "voice": args.voice}.items() if v}
    try:
        if args.action == "produce":
            r = produce(args.script, ov, max_rounds=args.max_rounds)
            print(json.dumps(r, ensure_ascii=False, indent=2))
            if r["status"] == "needs_owner":
                sys.exit(f"[!] {r['reason']}")
        else:
            print(json.dumps(approve_voice(args.script), ensure_ascii=False, indent=2))
    except VoiceGateError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
