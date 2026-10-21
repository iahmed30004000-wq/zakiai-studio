"""
توازن المكتبة: كم نمط عندنا لكل فئة × إطار × لهجة، مقابل الحصة الدنيا لكل «فئة نشطة».

فئة نشطة = فئة منتج فعلي بمجلد products/ (بدون القالب). الحصة config.LIBRARY_QUOTA.
العدّ للأنماط الأساسية بس — النسخ المدموجة بالعنقود (cluster_role=variant) ما بتنحسب
خيار جديد، لأنها نفس الآلية.
"""

from __future__ import annotations

import json
from pathlib import Path

import config
import taxonomy

UNKNOWN = "unknown"


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def active_categories() -> list[str]:
    """فئات ملفات المنتجات (slugs مغلقة)، بترتيب أول ظهور، بدون تكرار."""
    out: list[str] = []
    for f in sorted(Path(config.PRODUCTS_DIR).glob("*.json")):
        if f.name.startswith("_"):
            continue
        d = _read_json(f)
        if not isinstance(d, dict):
            continue
        slug = taxonomy.normalize_category(d.get("category")).value
        if slug and slug not in out:
            out.append(slug)
    return out


def load_patterns() -> list[dict]:
    out = []
    for f in sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json")):
        d = _read_json(f)
        if isinstance(d, dict):
            d["_pattern_id"] = f.name.replace(".pattern.json", "")
            out.append(d)
    return out


def is_primary(p: dict) -> bool:
    return p.get("cluster_role") != "variant"


def count_in_category(patterns: list[dict], category: str | None) -> int:
    return sum(1 for p in patterns if is_primary(p) and p.get("product_category") == category)


def coverage() -> dict:
    """بحسب عقد GET /api/library/coverage."""
    quota = getattr(config, "LIBRARY_QUOTA", 10)
    patterns = load_patterns()
    primaries = [p for p in patterns if is_primary(p)]

    cells: dict[tuple, int] = {}
    for p in primaries:
        key = (p.get("product_category") or UNKNOWN, p.get("framework") or UNKNOWN,
               p.get("dialect_or_language") or UNKNOWN)
        cells[key] = cells.get(key, 0) + 1
    matrix = [{"category": c, "framework": f, "dialect": d, "count": n}
              for (c, f, d), n in sorted(cells.items())]

    active = active_categories()
    per_category, gaps = [], []
    for slug in active:
        n = count_in_category(patterns, slug)
        label = taxonomy.CATEGORY_LABELS.get(slug, slug)
        gap = max(0, quota - n)
        per_category.append({"category": slug, "label": label, "count": n,
                             "quota_met": n >= quota, "gap": gap})
        if gap:
            gaps.append({"category": slug, "label": label, "missing": gap})

    return {
        "quota": quota,
        "active_categories": active,
        "matrix": matrix,
        "per_category": per_category,
        "gaps": gaps,
        "total_patterns": len(patterns),
        "primary_patterns": len(primaries),
        "variants_not_counted": len(patterns) - len(primaries),
    }
