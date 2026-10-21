"""
عناقيد الأنماط المتشابهة — دمج منطقي بدون حذف ولا نمط.

كل عنقود = نمط أساسي + نسخ (variants). الأصل بيضل كما هو على القرص، والعنقود
مجرد وسم: `cluster_id` و`cluster_role` (primary | variant) بكل ملف نمط، وملف
`library/clusters.json` فيه الفهرس.

ليش عنقود نجمي مش اتصال متسلسل: لو A~B وB~C وA≁C، الاتصال المتسلسل بيلمّهم
كلهم بعنقود وحدة ضخم. هون كل نمط بيتقارن بالأساسي بس.
الأساسي = الأعلى قابلية نقل، وعند التعادل الأغنى مخططاً.
"""

from __future__ import annotations

import json
from pathlib import Path

import config
import pattern_dedupe
import pattern_text

CLUSTERS_PATH = Path(config.LIBRARY_DIR) / "clusters.json"


def _rank(p: dict):
    return (-(p.get("reusability_score") or 0), -len(p.get("scene_blueprint") or []),
            str(p.get("_pattern_id")))


def build(patterns: list[dict], threshold: float | None = None) -> list[dict]:
    """يبني العناقيد بالذاكرة (ما بيكتب شي). المدخل: أنماط فيها _pattern_id."""
    thr = threshold if threshold is not None else pattern_dedupe.DUPLICATE_THRESHOLD
    clusters: list[dict] = []
    for p in sorted(patterns, key=_rank):
        placed = False
        for c in clusters:
            score, _ = pattern_dedupe.similarity(p, c["_primary"])
            if score >= thr:
                c["variants"].append({"pattern_id": p["_pattern_id"], "score": round(score, 3)})
                placed = True
                break
        if not placed:
            clusters.append({"_primary": p, "primary": p["_pattern_id"], "variants": []})

    out = []
    for i, c in enumerate(clusters, 1):
        out.append({
            "cluster_id": f"cl_{i:03d}",
            "primary": c["primary"],
            "primary_name": pattern_text.display_name(c["_primary"]),
            "variants": c["variants"],
            "size": 1 + len(c["variants"]),
        })
    return out


def apply(patterns_dir: Path | None = None, threshold: float | None = None) -> dict:
    """بيبني ويكتب: الفهرس + الوسوم على ملفات الأنماط. آمن للتكرار."""
    pdir = Path(patterns_dir or config.PATTERNS_DIR)
    files = sorted(pdir.glob("*.pattern.json"))
    patterns = []
    for f in files:
        p = json.loads(f.read_text(encoding="utf-8"))
        p["_pattern_id"] = f.name.replace(".pattern.json", "")
        patterns.append(p)

    clusters = build(patterns, threshold)
    role = {}
    for c in clusters:
        role[c["primary"]] = (c["cluster_id"], "primary")
        for v in c["variants"]:
            role[v["pattern_id"]] = (c["cluster_id"], "variant")

    # مرحلة الكتابة تحت القفل: بنعيد قراءة كل ملف قبل ما نكتب وسم العنقود، فتعديل المالك اللي صار أثناء الحساب ما بينضرب
    import pattern_store
    changed = 0
    with pattern_store.locked(directory=pdir):
        for f, p in zip(files, patterns):
            cid, r = role[p["_pattern_id"]]
            if p.get("cluster_id") != cid or p.get("cluster_role") != r:
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue                                          # انحذف/اتأرشف أثناء الحساب
                raw["cluster_id"], raw["cluster_role"] = cid, r
                pattern_store.write_atomic(f, raw)
                changed += 1

        CLUSTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CLUSTERS_PATH.write_text(json.dumps({"threshold": threshold or pattern_dedupe.DUPLICATE_THRESHOLD,
                                             "clusters": clusters}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    multi = [c for c in clusters if c["size"] > 1]
    return {"patterns": len(patterns), "clusters": len(clusters),
            "merged_clusters": len(multi), "variants": sum(len(c["variants"]) for c in clusters),
            "files_updated": changed}


def load() -> list[dict]:
    if CLUSTERS_PATH.exists():
        try:
            return json.loads(CLUSTERS_PATH.read_text(encoding="utf-8")).get("clusters", [])
        except json.JSONDecodeError:
            return []
    return []


def primaries() -> set[str]:
    """معرّفات الأنماط الأساسية — المطابقة بتشتغل عليهم مش على النسخ."""
    cl = load()
    return {c["primary"] for c in cl} if cl else set()
