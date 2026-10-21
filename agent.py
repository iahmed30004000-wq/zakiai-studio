#!/usr/bin/env python3
"""
تشغيل Zakiai Systems بلا واجهة — للاستخدام مع Windows Task Scheduler.

    python agent.py run                 # ينفّذ كل المستحق مرة وبيخرج (catch-up)
    python agent.py run --only backup_daily,queue_poll
    python agent.py run --force         # ينفّذ الكل بغض النظر عن الاستحقاق
    python agent.py status              # حالة المهام

كود الخروج: 0 = تمام (حتى لو مهمة انتخطّت لأن وحدة ناقصة)، 1 = في مهمة فشلت.
"""

import argparse
import json
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import scheduler


def _line(r: dict) -> str:
    name = r["task"]
    if not r.get("ran"):
        return f"  - {name}: تخطّي ({r.get('reason') or r.get('error')})"
    if r.get("skipped"):
        return f"  - {name}: انتخطّت — {r['skipped']}"
    if r.get("offline"):
        return f"  ~ {name}: غير متصل — {r['offline']} (رح نعيد)"
    if r.get("error"):
        return f"  ! {name}: فشل — {r['error']}"
    return f"  + {name}: تمام"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="وكيل Zakiai Systems بلا واجهة")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="نفّذ كل المستحق مرة وبيخرج")
    r.add_argument("--only", help="مهام محدّدة مفصولة بفاصلة: " + ",".join(scheduler.TASK_NAMES))
    r.add_argument("--force", action="store_true")
    r.add_argument("--json", action="store_true", help="اطبع النتيجة JSON")
    sub.add_parser("status")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        print(json.dumps(scheduler.status(), ensure_ascii=False, indent=2))
        return 0

    only = [x.strip() for x in a.only.split(",")] if a.only else None
    if only:
        bad = [x for x in only if x not in scheduler.TASK_NAMES]
        if bad:
            print(f"[!] مهام غير معروفة: {', '.join(bad)}")
            return 2
    results = scheduler.run_due(only, force=a.force)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("Zakiai Systems agent:")
        for res in results:
            print(_line(res))
    return 1 if any(r.get("error") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
