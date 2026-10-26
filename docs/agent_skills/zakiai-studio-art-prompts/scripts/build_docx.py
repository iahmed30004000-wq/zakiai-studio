#!/usr/bin/env python3
"""
يبني ملف Word واحد بكل برومبتات الرسومات (قاعدة المالك الثابتة: «البرومبتات تبع الصور دائماً جمّعها وابعتها ملف ورد»).

    python build_docx.py [SPEC.json] [OUT.docx] [--pack new|all]

SPEC الافتراضي: ../references/zakiai-art.json. --pack new (الافتراضي) = برومبت الأسلوب + الجداد بس، وall = كمان القديمة (base).
التنسيق (عربي RTL + برومبت إنجليزي LTR) من refprompts.build_docx بمشروع الاستوديو، فبيطلع بنفس شكل ملفات الأوراق المرجعية.
المشروع: C:\\Users\\LOQ\\Pictures\\المشروع (أو المتغير ZAKIAI_PROJECT).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
PROJECT = Path(os.environ.get("ZAKIAI_PROJECT") or r"C:\Users\LOQ\Pictures\المشروع")


def main() -> None:
    ap = argparse.ArgumentParser(description="ملف Word واحد ببرومبتات رسومات الاستوديو")
    ap.add_argument("spec", nargs="?", default=str(HERE.parent / "references" / "zakiai-art.json"))
    ap.add_argument("out", nargs="?", default=str(PROJECT / "برومبتات_رسومات_الموقع_الجديدة.docx"))
    ap.add_argument("--pack", choices=["new", "all"], default="new")
    a = ap.parse_args()
    sys.path.insert(0, str(PROJECT))
    import refprompts                                   # noqa: E402 — بناء docx بنفس تنسيق ملفات المشروع

    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    keep = {"style", "new"} | ({"base"} if a.pack == "all" else set())
    items = []
    for it in spec["items"]:
        if it.get("pack", "new") not in keep:
            continue
        flags = []
        if it.get("file") and it["file"] != "—":
            flags += [f"الاسم: {it['file']}", f"الحجم: {it['size']}",
                      f"احفظها بـ: web\\static\\img\\art\\{it['file']}"]
        if it.get("status"):
            flags.append(f"الحالة: {'مطلوبة من جديد (23/10)' if it['status'].startswith('requested') else 'جديدة (23/10)'}")
        if it.get("where"):
            flags.append(f"وين بيركّب: {it['where']}")
        items.append({"title": re.sub(r"^\d+\.\s*", "", it["title"]), "note": it.get("note", ""), "prompt": it["prompt"], "flags": flags})
    data = refprompts.build_docx(spec["title"], spec["intro"], items)
    out = Path(a.out)
    out.write_bytes(data)
    print(f"{out}  ({len(items)} برومبت، {len(data) // 1024} كيلوبايت)")


if __name__ == "__main__":
    main()
