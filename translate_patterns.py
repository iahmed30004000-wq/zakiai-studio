#!/usr/bin/env python3
"""
ترجمة أنماط المكتبة للعربي (بتعبّي طبقة العربي الناقصة بس؛ الأصل الإنجليزي ما بينلمس).

الاستخدام:
    python translate_patterns.py --status             كم نمط/نص لسا ناقص
    python translate_patterns.py --limit 2            تجربة على نمطين (راجع الجودة قبل الباقي)
    python translate_patterns.py                      كل الناقص (قابل للاستئناف إذا انقطع)
    python translate_patterns.py --ids a,b            أنماط محدّدة
    python translate_patterns.py --rollback           يرجّع آخر تشغيلة (والنمط اللي تعدّل بعدها ما بينلمس)
    python translate_patterns.py --rollback ar_20261021_1530

كل تشغيلة بتنسخ كل ملف قبل ما تعدّله لـ library/_backups/ar_<وقت>/ مع manifest فيه بصمة الملف قبل وبعد.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# كونسول ويندوز افتراضياً cp1252 وبيفشل مع العربي
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config
import pattern_i18n
import pattern_store
from llm_errors import exit_on_api_error


MAX_FAIL_STREAK = 3          # بعد 3 فشل متتالي المشكلة غالباً بالمفتاح أو الاتصال: ما منكمّل نحرق وقت ومحاولات


def backups_dir() -> Path:
    return Path(config.PATTERNS_DIR).parent / "_backups"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(folder: Path, manifest: dict) -> None:
    pattern_store.write_atomic(folder / "manifest.json", manifest)


def run(ids: list[str] | None = None, limit: int | None = None, *, ask=None, on_progress=None, auto: bool = False) -> dict:
    """يترجم الناقص. بيرجّع {done, failed, stamp, remaining}.
    auto: الترجمة التلقائية (بتتخطّى الأنماط اللي وصلت حد المحاولات). on_progress(معالَج, الكل) بعد كل نمط."""
    pool = pattern_i18n.auto_todo() if auto else pattern_i18n.pending_patterns()
    todo = [(pid, n) for pid, n in pool if not ids or pid in ids]
    if limit:
        todo = todo[:limit]
    if not todo:
        print("[i] ما في شي ناقص ترجمة.")
        return {"done": 0, "failed": [], "stamp": None, "remaining": 0}

    stamp = "ar_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = backups_dir() / stamp
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"stamp": stamp, "created_at": datetime.now().isoformat(timespec="seconds"), "files": {}}
    _write_manifest(folder, manifest)
    print(f"[i] {len(todo)} نمط للترجمة — نسخة احتياطية: {folder}")

    done, failed, streak, aborted = 0, [], 0, False
    for i, (pid, n) in enumerate(todo, 1):
        if on_progress:
            on_progress(i - 1, len(todo))
        src = Path(config.PATTERNS_DIR) / f"{pid}.pattern.json"
        before = _sha(src)
        shutil.copy2(src, folder / src.name)
        print(f"[{i}/{len(todo)}] {pid} — {n} نص…", flush=True)
        try:
            res = pattern_i18n.translate_pattern(pid, ask=ask)
        except pattern_i18n.TranslateError as e:
            failed.append({"id": pid, "error": str(e)})
            print(f"    [!] {e}")
            (folder / src.name).unlink(missing_ok=True)
            streak += 1
            if streak >= MAX_FAIL_STREAK:
                print(f"[!] وقفت بعد {streak} فشل متتالي — غالباً المشكلة بالمفتاح أو الاتصال، صلّحها وأعد التشغيل.")
                aborted = True
                break
            continue
        streak = 0
        manifest["files"][pid] = {"before": before, "after": _sha(src), "applied": res["applied"]}
        _write_manifest(folder, manifest)
        n_try = pattern_i18n.record_attempt(pid, complete=not res["pending"])
        if res["pending"]:
            print(f"    [!] بقي {res['pending']} نص بلا ترجمة (محاولة {n_try} من {pattern_i18n.MAX_ATTEMPTS})")
        else:
            done += 1
    if on_progress and not aborted:
        on_progress(len(todo), len(todo))
    if not manifest["files"]:                                   # ما انترجم شي ← ما في داعي لمجلد النسخة الفاضي
        shutil.rmtree(folder, ignore_errors=True)
        stamp = None
    else:
        try:
            import clusters
            clusters.apply()
        except Exception as e:                                  # noqa: BLE001
            print(f"    [!] تحديث العناقيد تأجّل: {e}")
    left = len(pattern_i18n.pending_patterns())
    print(f"[✓] تمّت ترجمة {done} نمط، فشل {len(failed)}، بقي {left} نمط ناقص.")
    return {"done": done, "failed": failed, "stamp": stamp, "remaining": left}


def latest_stamp() -> str | None:
    folders = sorted(p.name for p in backups_dir().glob("ar_*") if (p / "manifest.json").exists())
    return folders[-1] if folders else None


def rollback(stamp: str | None = None) -> dict:
    """يرجّع ملفات تشغيلة. الملف اللي تعدّل بعد الترجمة (غير بصمته) ما بينلمس — ما بنضيّع تعديل المالك."""
    stamp = stamp or latest_stamp()
    if not stamp:
        print("[i] ما في نسخة احتياطية.")
        return {"restored": [], "skipped": []}
    folder = backups_dir() / Path(stamp).name
    mf = folder / "manifest.json"
    if not mf.exists():
        raise SystemExit(f"[!] ما في manifest بـ {folder}")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    restored, skipped = [], []
    with pattern_store.locked():
        for pid, info in manifest.get("files", {}).items():
            cur = Path(config.PATTERNS_DIR) / f"{pid}.pattern.json"
            bak = folder / f"{pid}.pattern.json"
            if not bak.exists() or not cur.exists():
                skipped.append({"id": pid, "why": "الملف أو نسخته مش موجودة"})
            elif _sha(cur) != info.get("after"):
                skipped.append({"id": pid, "why": "تعدّل بعد الترجمة — ما انلمس"})
            else:
                shutil.copy2(bak, cur)
                restored.append(pid)
    try:
        import clusters
        clusters.apply()
    except Exception:                                           # noqa: BLE001
        pass
    print(f"[✓] رجع {len(restored)} نمط، وتخطّى {len(skipped)}.")
    for s in skipped:
        print(f"    - {s['id']}: {s['why']}")
    return {"restored": restored, "skipped": skipped}


def status() -> dict:
    pend = pattern_i18n.pending_patterns()
    total = len(pattern_store.list_ids())
    print(f"[i] {len(pend)} نمط من {total} فيه نص لسا بالإنجليزي ({sum(n for _, n in pend)} نص).")
    return {"patterns": total, "pending_patterns": len(pend), "pending_keys": sum(n for _, n in pend)}


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="ترجمة أنماط المكتبة للعربي")
    ap.add_argument("--status", action="store_true", help="كم ناقص (بدون ترجمة)")
    ap.add_argument("--limit", type=int, help="حد أقصى لعدد الأنماط (للتجربة)")
    ap.add_argument("--ids", help="معرّفات مفصولة بفاصلة")
    ap.add_argument("--rollback", nargs="?", const="", metavar="STAMP", help="رجّع تشغيلة (الأخيرة إذا ما انحدد)")
    args = ap.parse_args()
    if args.rollback is not None:
        rollback(args.rollback or None)
    elif args.status:
        status()
    else:
        res = run([x for x in (args.ids or "").split(",") if x] or None, args.limit)
        if res["failed"] and not res["done"]:
            sys.exit(1)                                         # المهمة بالواجهة لازم تظهر «فشلت» مش «خلصت»


if __name__ == "__main__":
    main()
