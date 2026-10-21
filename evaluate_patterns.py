#!/usr/bin/env python3
"""
تقييم جودة مكتبة الأنماط — بدون استدعاء API.
يقيس اكتمال الحقول، تنوّع الأطر، والتكرار بين الأنماط، ويطلع تقرير مختصر.

    python evaluate_patterns.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import PATTERNS_DIR

# حقول لازم تكون موجودة ومعبّاة بأي نمط صالح
REQUIRED = [
    "pattern_name", "framework", "one_line_summary", "hook",
    "emotional_arc", "product_entry_sec", "proof_mechanism",
    "cta", "pacing", "scene_blueprint", "why_it_works",
    "best_for", "avoid_for", "reusability_score",
]


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip() or v.strip() in {"غير محدد", "unknown", "N/A"}
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def main() -> None:
    files = sorted(Path(PATTERNS_DIR).glob("*.pattern.json"))
    if not files:
        sys.exit(f"[!] ما في أنماط في {PATTERNS_DIR}")

    patterns, incomplete = [], []
    for f in files:
        p = json.loads(f.read_text(encoding="utf-8"))
        p["_file"] = f.name
        patterns.append(p)
        missing = [k for k in REQUIRED if is_empty(p.get(k))]
        if missing:
            incomplete.append((f.name, missing))

    print(f"عدد الأنماط: {len(patterns)}\n")

    # 1) الاكتمال
    print("── الاكتمال ──")
    if incomplete:
        print(f"  {len(incomplete)} نمط فيه حقول ناقصة:")
        for name, missing in incomplete[:8]:
            print(f"    {name}: {', '.join(missing)}")
    else:
        print("  كل الأنماط مكتملة الحقول")

    # 2) التنوّع — أطر مكررة تعني تحليل سطحي
    print("\n── التنوّع ──")
    frameworks = Counter(p.get("framework", "—") for p in patterns)
    print(f"  أطر مختلفة: {len(frameworks)} من {len(patterns)} نمط")
    for fw, n in frameworks.most_common(6):
        bar = "█" * n
        print(f"    {n:2}× {bar} {fw}")

    hooks = Counter((p.get("hook") or {}).get("type", "—") for p in patterns)
    print(f"  أنواع هوك مختلفة: {len(hooks)}")

    # 3) التكرار الحرفي — نفس الملخص لفيديوهين مختلفين = تحليل قالبي
    print("\n── التكرار ──")
    summaries = Counter(p.get("one_line_summary", "") for p in patterns)
    dupes = {s: n for s, n in summaries.items() if n > 1 and s}
    if dupes:
        print(f"  [!] {len(dupes)} ملخص مكرر حرفياً بين أنماط مختلفة")
        for s, n in list(dupes.items())[:3]:
            print(f"    {n}× {s[:90]}")
    else:
        print("  ما في ملخصات مكررة")

    # 4) قابلية إعادة الاستخدام
    print("\n── قابلية إعادة الاستخدام ──")
    scores = [p.get("reusability_score") for p in patterns if isinstance(p.get("reusability_score"), (int, float))]
    if scores:
        print(f"  المتوسط: {sum(scores)/len(scores):.1f}/10 | الأعلى: {max(scores)} | الأدنى: {min(scores)}")
        strong = [p for p in patterns if isinstance(p.get("reusability_score"), (int, float)) and p["reusability_score"] >= 7]
        print(f"  أنماط قوية (7+): {len(strong)}")
        for p in sorted(strong, key=lambda x: -x["reusability_score"])[:5]:
            print(f"    {p['reusability_score']}/10 — {p.get('pattern_name')} ({p.get('framework')})")

    # 5) التكرار البنيوي — أهم من التكرار الحرفي
    print("\n── تكرار بنيوي ──")
    import pattern_dedupe
    lib = pattern_dedupe.load_library(PATTERNS_DIR)
    pairs = []
    for i, a in enumerate(lib):
        for b in lib[i + 1:]:
            score, _ = pattern_dedupe.similarity(a, b)
            if score >= pattern_dedupe.SIMILAR_THRESHOLD:
                pairs.append((score, a, b))
    pairs.sort(key=lambda x: -x[0])
    dupes = [p for p in pairs if p[0] >= pattern_dedupe.DUPLICATE_THRESHOLD]
    if dupes:
        print(f"  [!] {len(dupes)} زوج مكرر — يستاهلوا دمج أو حذف:")
        for score, a, b in dupes[:6]:
            print(f"    {score:.0%}  {a.get('pattern_name')}  ↔  {b.get('pattern_name')}")
    else:
        print("  ما في أنماط مكررة")
    near = len(pairs) - len(dupes)
    if near:
        print(f"  {near} زوج متقارب (تحت عتبة التكرار) — طبيعي بنفس المجال")

    # 6) عمق المخطط
    print("\n── عمق المخطط ──")
    blens = [len(p.get("scene_blueprint", [])) for p in patterns]
    if blens:
        print(f"  متوسط مشاهد المخطط: {sum(blens)/len(blens):.1f}")
        thin = sum(1 for b in blens if b < 5)
        if thin:
            print(f"  [!] {thin} نمط مخططه أقل من 5 مشاهد (تحليل ضحل)")


if __name__ == "__main__":
    main()
