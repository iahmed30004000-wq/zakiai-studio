#!/usr/bin/env python3
"""
التصدير النهائي بالمونتاج المتقدّم (Remotion) — بديل اختياري لـ `montage.py final`.

    python montage_advanced.py library/scripts/X.json

نفس شروط التصدير العادي (آهات/تحريك معتمد + معاينة كاملة)، وبينشر بنفس المكان (library/exports/<script_id>.mp4)
وبيسجّل render.final بالخط الزمني بنفس الشكل، فمحطة الإطلاق ما بتحس بالفرق.
الأمان: الناتج بيتفحص (أبعاد/مدة/صوت) قبل النشر. لو فشل الرندر أو الفحص ما بينلمس التصدير العادي القديم وحالة المحطة بترجع كما كانت.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import studio_state
import timeline
import montage


def run(script_path, log=print) -> dict:
    path = Path(script_path)
    stem = path.stem
    ok, why = studio_state.can_start(stem, 10)
    if not ok:
        raise montage.MontageError(why)
    tl = timeline.load(stem)
    if not tl:
        raise montage.MontageError("ما في خط زمني")
    import motion
    probs = motion.problems(tl)
    if probs:
        raise montage.MontageError("؛ ".join(p["message"] for p in probs[:3]))
    if not (tl.get("render") or {}).get("preview"):
        raise montage.MontageError("لازم معاينة كاملة قبل التصدير النهائي")
    prev_state = studio_state.state_of(stem, 10)
    studio_state.set_state(stem, 10, "running", "تصدير نهائي بالمونتاج المتقدّم")
    try:
        from services.advanced_montage.errors import JobError, RenderError
        from services.advanced_montage.pipeline import render_script
        try:
            res = render_script(path, config.LIBRARY_DIR, log=log)
        except (JobError, RenderError) as e:
            raise montage.MontageError(str(e)) from None
        if res["errors"]:
            raise montage.MontageError("الفيديو طلع بس ما طابق المواصفات (ما اننشر): " + "؛ ".join(res["errors"]))
        out = Path(res["published"])
        info = montage.probe(out)
        rel = out.resolve().relative_to(Path(config.LIBRARY_DIR).resolve()).as_posix()
        tl = timeline.load(stem)
        tl.setdefault("render", {})["final"] = {"file": rel, "at": montage._now(), "size": [info.get("width"), info.get("height")],
                                                "duration_ms": info["duration_ms"], "ahat": bool((tl.get("ambience") or {}).get("track_id")),
                                                "captions": len(montage.build_cues(tl)), "engine": "remotion"}
        timeline.save(stem, tl)
        studio_state.set_state(stem, 10, "approved", f"صُدِّر {out.name} (متقدّم)")
        return {"mode": "advanced", "file": rel, "info": info, "seconds": round(res["seconds"])}
    except BaseException:
        studio_state.set_state(stem, 10, prev_state if prev_state in ("approved", "awaiting_choice") else "awaiting_choice",
                               "فشل المونتاج المتقدّم — التصدير السابق (إن وُجد) سليم")
        raise


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("الاستعمال: python montage_advanced.py library/scripts/X.json")
    try:
        print(json.dumps(run(sys.argv[1]), ensure_ascii=False, indent=2, default=str))
    except montage.MontageError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
