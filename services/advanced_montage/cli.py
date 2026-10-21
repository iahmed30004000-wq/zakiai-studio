"""
    python -m services.advanced_montage prepare <script.json> [--library DIR] [--products DIR] [--out DIR] [--stage]
    python -m services.advanced_montage verify  <video.mp4> <job.json>
    python -m services.advanced_montage doctor
    python -m services.advanced_montage render  <script.json> [--library DIR] [--products DIR] [--out DIR] [--timeout ثواني]
    python -m services.advanced_montage still   <script.json> --frame N --png ملف.png   (لقطة فحص بصري)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapter.build_job import build_job, summarize
from .adapter.stage_media import stage_media
from .adapter.verify import verify_output
from .errors import JobError, RenderError, StageError


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")


def cmd_prepare(a) -> int:
    lib = a.library
    if lib is None:
        import config
        lib = config.LIBRARY_DIR
    job = build_job(a.script, lib, a.products)
    out = Path(a.out) if a.out else Path(lib) / "exports" / f"{Path(a.script).stem}_adv"
    out.mkdir(parents=True, exist_ok=True)
    if a.stage:
        job = stage_media(job, lib, out / "work")
    (out / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summarize(job))
    print(f"- كتبنا: {out / 'job.json'}" + (" (مع تجهيز الملفات بمجلد work)" if a.stage else ""))
    return 0


def cmd_verify(a) -> int:
    try:
        job = json.loads(Path(a.job).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("[!] ملف الـ job تالف أو مش موجود")
        return 1
    errs = verify_output(a.video, job)
    if errs:
        print("الفيديو ما طابق المواصفات:")
        for e in errs:
            print(f"- {e}")
        return 1
    print("الفيديو مطابق للمواصفات")
    return 0


def cmd_doctor(a) -> int:
    from .renderers.remotion_engine import doctor_checks
    checks = doctor_checks()
    print("فحص جاهزية المونتاج المتقدّم:")
    for c in checks:
        print(f"{'✓' if c.ok else '✗'} {c.detail}")
    bad = [c for c in checks if not c.ok]
    if bad:
        print()
        print(f"في {len(bad)} شي ناقص — صلّحه وأعد الأمر.")
        return 1
    print()
    print("كل شي جاهز. جرّب: python -m services.advanced_montage render <ملف السيناريو>")
    return 0


def cmd_render(a) -> int:
    from .pipeline import render_script
    lib = a.library
    if lib is None:
        import config
        lib = config.LIBRARY_DIR
    res = render_script(a.script, lib, a.products, a.out, timeout_s=a.timeout, concurrency=a.concurrency)
    print(summarize(res["job"]))
    if res["errors"]:
        print()
        print("الفيديو طلع بس ما طابق المواصفات (ما اننشر):")
        for e in res["errors"]:
            print(f"- {e}")
        print(f"- الملف للمراجعة: {res['video'].name} بمجلد العمل")
        return 1
    print()
    print(f"✓ خلص الرندر بـ {res['seconds']:.0f} ثانية وطابق المواصفات")
    print(f"- الفيديو: {res['published']}")
    return 0


def cmd_still(a) -> int:
    from .renderers.remotion_engine import render_still
    lib = a.library
    if lib is None:
        import config
        lib = config.LIBRARY_DIR
    job = build_job(a.script, lib, a.products)
    out = Path(a.out) if a.out else Path(lib) / "exports" / f"{Path(a.script).stem}_adv"
    p = render_still(job, out / "work", a.frame, a.png, library_dir=lib)
    print(f"- اللقطة: {p}")
    return 0


def main(argv=None) -> None:
    _utf8()
    ap = argparse.ArgumentParser(prog="python -m services.advanced_montage",
                                 description="المونتاج المتقدّم — تحضير وتحقق")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="بناء job.json من الخط الزمني المعتمد")
    p.add_argument("script")
    p.add_argument("--library")
    p.add_argument("--products")
    p.add_argument("--out")
    p.add_argument("--stage", action="store_true", help="جهّز ملفات الوسائط بمجلد work")
    v = sub.add_parser("verify", help="فحص فيديو ناتج مقابل job.json")
    v.add_argument("video")
    v.add_argument("job")
    sub.add_parser("doctor", help="فحص Node والمتصفح ومشروع Remotion")
    r = sub.add_parser("render", help="رندر كامل: تحضير + Remotion + فحص + نشر بمجلد exports")
    r.add_argument("script")
    r.add_argument("--library")
    r.add_argument("--products")
    r.add_argument("--out")
    r.add_argument("--timeout", type=int, help="مهلة كلية بالثواني")
    r.add_argument("--concurrency", type=int, help="عدد الإطارات المتوازية (الافتراضي نصف الأنوية)")
    st = sub.add_parser("still", help="لقطة PNG لإطار واحد للفحص البصري")
    st.add_argument("script")
    st.add_argument("--library")
    st.add_argument("--products")
    st.add_argument("--out")
    st.add_argument("--frame", type=int, default=0)
    st.add_argument("--png", required=True)
    a = ap.parse_args(argv)
    handlers = {"prepare": cmd_prepare, "verify": cmd_verify, "doctor": cmd_doctor, "render": cmd_render, "still": cmd_still}
    try:
        code = handlers[a.cmd](a)
    except (JobError, StageError, RenderError) as e:
        sys.exit(f"[!] {e}")
    sys.exit(code)
