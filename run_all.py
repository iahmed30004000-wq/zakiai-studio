#!/usr/bin/env python3
"""
RUN ALL — يشغّل السلسلة كاملة أو من مرحلة معيّنة.

    # السلسلة كاملة: حصاد → استخراج → تشريح → سيناريو
    python run_all.py --source tiktok --query "كريم ازالة الشعر" --product products/vara.json

    # عندي روابط جاهزة، ابدأ من المرحلة 1
    python run_all.py --links library/links.txt --product products/vara.json

    # عندي مكتبة أنماط جاهزة، ولّد سيناريو بس
    python run_all.py --product products/vara.json --from 3
"""

import argparse
import subprocess
import sys
from pathlib import Path

# كونسول ويندوز افتراضياً cp1252 وبيفشل مع العربي
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import RAW_DIR, PATTERNS_DIR, LIBRARY_DIR

PY = sys.executable


def step(title: str, cmd: list) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")
    result = subprocess.run([PY] + cmd)
    if result.returncode != 0:
        sys.exit(f"[!] توقفت عند: {title}")


def main() -> None:
    ap = argparse.ArgumentParser(description="تشغيل السلسلة كاملة")
    ap.add_argument("--product", help="مسار ملف المنتج JSON")
    ap.add_argument("--source", choices=["tiktok", "adlibrary", "reels"])
    ap.add_argument("--query", help="كلمة البحث للحصاد")
    ap.add_argument("--hashtag")
    ap.add_argument("--country", default="SY")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--links", help="ملف روابط جاهز (يتخطى المرحلة 0)")
    ap.add_argument("--pattern", help="فرض نمط محدد بالمرحلة 3")
    ap.add_argument("--from", dest="start", type=int, default=0,
                    help="ابدأ من مرحلة: 0 حصاد | 1 استخراج | 2 تشريح | 3 سيناريو")
    args = ap.parse_args()

    links = Path(args.links) if args.links else Path(LIBRARY_DIR) / "links.txt"

    # ── المرحلة 0 ────────────────────────────────────────────────────────
    if args.start <= 0 and args.source and not args.links:
        cmd = ["stage0_harvest.py", args.source, "--limit", str(args.limit),
               "--country", args.country]
        cmd += ["--hashtag", args.hashtag] if args.hashtag else ["--query", args.query]
        step("المرحلة 0 — حصاد الفيديوهات", cmd)
        step("المرحلة 0 — دمج الروابط", ["stage0_harvest.py", "--merge"])

    # ── المرحلة 1 ────────────────────────────────────────────────────────
    if args.start <= 1:
        if not links.exists():
            sys.exit(f"[!] ما في ملف روابط: {links}")
        step("المرحلة 1 — استخراج النصوص واللقطات", ["stage1_extract.py", "--batch", str(links)])

    # ── المرحلة 2 ────────────────────────────────────────────────────────
    if args.start <= 2:
        if not list(Path(RAW_DIR).glob("*/extract.json")):
            sys.exit("[!] ما في مخرجات من المرحلة 1.")
        step("المرحلة 2 — تشريح الأنماط", ["stage2_pattern.py", "--all"])

    # ── المرحلة 3 ────────────────────────────────────────────────────────
    if args.product:
        count = len(list(Path(PATTERNS_DIR).glob("*.pattern.json")))
        if count == 0:
            sys.exit("[!] مكتبة الأنماط فاضية.")
        if count < 8:
            print(f"\n[!] تنبيه: عندك {count} نمط بس — الجودة بتصير أفضل بعد 20+ نمط.")
        cmd = ["stage3_generate.py", args.product]
        if args.pattern:
            cmd += ["--pattern", args.pattern]
        step("المرحلة 3 — مطابقة وتوليد السيناريو", cmd)
    else:
        print("\n[i] ما مرّرت --product، فوقفنا عند بناء مكتبة الأنماط.")

    print("\n[✓] خلصت السلسلة.")


if __name__ == "__main__":
    main()
