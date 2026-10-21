#!/usr/bin/env python3
"""
ترحيل المرحلة ١ — تنظيف البيانات بلا ميزات جديدة.

    python migrate_phase1.py --dry-run          # شو رح يتغيّر بدون ما يكتب
    python migrate_phase1.py                    # نسخة احتياطية أول، بعدين الترحيل
    python migrate_phase1.py --rollback <مجلد>   # يرجّع كل شي كما كان

بيعمل:
  ١. تصنيف مغلق للنمط: اللهجة · الإطار (أساسي + ثانوي) · الفئة — والأصل بـ `_legacy`
  ٢. القيمة اللي ما انطابقت بشكل قاطع = طابور مراجعة (ما بتنخمّن)
  ٣. عناقيد التكرار (وسم فقط — ما بيتحذف نمط)
  ٤. مسارات ويندوز المطلقة ← نسبية (الأصول) أو اسم ملف (مصدر الفيديو)
  ٥. ترحيل بريفات المنتجات + القالب يصير مخطط فاضي
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import brief
import clusters
import config
import review_queue
import taxonomy

LIB = Path(config.LIBRARY_DIR)
PRODUCTS = Path(config.PRODUCTS_DIR)
BACKUPS = LIB / "_backups"
ASSETS_DIR = LIB / "assets"

_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?!/))")


def rel_source(value):
    """مسار مطلق ← `local:<اسم الملف>`. الروابط والقيم الأخرى بتضل."""
    if isinstance(value, str) and _ABS.match(value.strip()):
        name = re.split(r"[\\/]", value.strip())[-1]
        return f"local:{name}"
    return value


def _rj(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _wj(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _targets() -> list[Path]:
    files = list((LIB / "patterns").glob("*.pattern.json"))
    files += list((LIB / "raw").glob("*/extract.json"))
    files += [ASSETS_DIR / "assets.json"] if (ASSETS_DIR / "assets.json").exists() else []
    files += list(PRODUCTS.glob("*.json"))
    files += [p for p in (LIB / "review_queue.json", LIB / "clusters.json") if p.exists()]
    return files


# ── نسخة احتياطية + تراجع ────────────────────────────────────────────────
def backup() -> Path:
    dest = BACKUPS / f"phase1_{datetime.now():%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True)
    root = LIB.parent
    saved = []
    for f in _targets():
        rel = f.relative_to(root)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest / rel)
        saved.append(str(rel).replace("\\", "/"))
    absent = [n for n in ("library/review_queue.json", "library/clusters.json") if n not in saved]
    _wj(dest / "manifest.json", {"phase": 1, "created_at": datetime.now().isoformat(timespec="seconds"),
                                 "files": saved, "absent_before": absent})
    return dest


def rollback(path: str) -> None:
    src = Path(path)
    mf = _rj(src / "manifest.json")
    root = LIB.parent
    for rel in mf["files"]:
        shutil.copy2(src / rel, root / rel)
    for rel in mf.get("absent_before", []):
        (root / rel).unlink(missing_ok=True)
    # الوسوم اللي انضافت لأنماط جديدة بعد النسخة ما بتنمسح — بس الملفات المنسوخة رجعت كما كانت
    print(f"[✓] رجّعت {len(mf['files'])} ملف من {src.name}")


# ── الترحيل ─────────────────────────────────────────────────────────────
def migrate_patterns(dry: bool) -> dict:
    stats = {"patterns": 0, "clean": 0, "review": 0, "confirm": 0, "paths_fixed": 0}
    for f in sorted((LIB / "patterns").glob("*.pattern.json")):
        pid = f.name.replace(".pattern.json", "")
        p = _rj(f)
        stats["patterns"] += 1
        p, issues = taxonomy.apply_to_pattern(p)

        src = p.get("_source") or {}
        fixed = rel_source(src.get("source"))
        if fixed != src.get("source"):
            src["source"] = fixed
            p["_source"] = src
            stats["paths_fixed"] += 1

        open_ = [i for i in issues if not i["applied"]]
        stats["review"] += bool(open_)
        stats["confirm"] += sum(1 for i in issues if i["applied"])
        stats["clean"] += not issues
        if not dry:
            for i in issues:
                review_queue.add(i["kind"], pid, i["raw"], i["candidates"], i["note"], i["applied"])
            _wj(f, p)
    return stats


def migrate_extracts(dry: bool) -> int:
    n = 0
    for f in (LIB / "raw").glob("*/extract.json"):
        d = _rj(f)
        meta = d.get("meta") or {}
        fixed = rel_source(meta.get("source"))
        if fixed != meta.get("source"):
            meta["source"], d["meta"] = fixed, meta
            n += 1
            if not dry:
                _wj(f, d)
    return n


def migrate_assets(dry: bool) -> int:
    idx = ASSETS_DIR / "assets.json"
    if not idx.exists():
        return 0
    data, n = _rj(idx), 0
    for a in data.values():
        pth = a.get("path", "")
        if _ABS.match(pth):
            a["path"] = re.split(r"[\\/]", pth)[-1]       # نسبي لمجلد الأصول
            n += 1
    if n and not dry:
        _wj(idx, data)
    return n


def migrate_products(dry: bool) -> list[dict]:
    report = []
    for f in sorted(PRODUCTS.glob("*.json")):
        if f.name.startswith("_"):
            continue
        raw = _rj(f)
        b, issues = brief.normalize(raw, f.stem)
        extra = {k: v for k, v in raw.items() if k not in brief.FIELD_KEYS
                 and k not in ("previously_used_patterns", "_provenance", "_legacy", "market")}
        if extra:
            b["_legacy"]["extra"] = extra
        c = brief.completeness(b)
        report.append({"file": f.name, "issues": issues, "score": c["score"], "missing": c["missing"]})
        if not dry:
            _wj(f, b)
            for i in issues:
                review_queue.add(i["kind"], f"product:{f.stem}", i["raw"], i["candidates"], i["note"])
    if not dry:
        _wj(PRODUCTS / "_template.json", brief.empty_brief())
    return report


def run(dry: bool) -> None:
    if not dry:
        bk = backup()
        print(f"[i] نسخة احتياطية: {bk}")
    ps = migrate_patterns(dry)
    ex = migrate_extracts(dry)
    ax = migrate_assets(dry)
    pr = migrate_products(dry)
    cl = clusters.apply() if not dry else {"note": "تخطّيت العناقيد بالتجربة"}

    print(f"\nالأنماط: {ps['patterns']} | نظيفة {ps['clean']} | بدها مراجعة {ps['review']} "
          f"| بدها تأكيد ترتيب {ps['confirm']}")
    print(f"مسارات مطلقة صُلّحت: أنماط {ps['paths_fixed']} · استخراجات {ex} · أصول {ax}")
    for r in pr:
        print(f"بريف {r['file']}: اكتمال {r['score']}% — ناقص {r['missing']}"
              + (f" | مراجعة {[i['kind'] for i in r['issues']]}" if r["issues"] else ""))
    print("العناقيد:", cl)
    if not dry:
        _wj(LIB / "migration_report_phase1.json",
            {"at": datetime.now().isoformat(timespec="seconds"), "patterns": ps,
             "extracts_paths": ex, "assets_paths": ax, "products": pr, "clusters": cl,
             "backup": str(bk.relative_to(LIB.parent)).replace(chr(92), "/")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", metavar="DIR")
    a = ap.parse_args()
    if a.rollback:
        rollback(a.rollback)
    else:
        run(a.dry_run)
