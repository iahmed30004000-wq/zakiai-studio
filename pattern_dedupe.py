"""
كشف تشابه الأنماط — بدون أي نداء API.

الفكرة: نمطين متطابقين فعلياً بيشتركوا بالبصمة البنيوية (الإطار + نوع الهوك +
تسلسل وظائف المشاهد + آلية الإثبات)، حتى لو أسماءهم مختلفة تماماً.
المقارنة بالاسم لحالها ما بتكفي: "Luxury Dupe Reveal" و"The Dupe Showdown"
ممكن يكونوا نفس النمط، و"Us vs Them" ممكن يكون إطار لنمطين مختلفين كلياً.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

# معايَرة على المكتبة الفعلية: الأزواج المكررة طلعت 0.65–0.74
# والمختلفة كلياً 0.25–0.29، فالفصل بينهم واسع ومريح.
DUPLICATE_THRESHOLD = 0.62
SIMILAR_THRESHOLD = 0.45

_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "with", "then", "for", "in", "on",
    "by", "its", "it", "into", "at", "as", "that", "this", "from",
}


def norm(text) -> str:
    text = str(text or "").casefold()
    text = re.sub(r"[^\w؀-ۿ\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text) -> set[str]:
    return {w for w in norm(text).split() if w not in _STOP and len(w) > 2}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def ratio(a, b) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def blueprint_functions(p: dict) -> list[str]:
    return [norm(s.get("function")) for s in p.get("scene_blueprint", []) if isinstance(s, dict)]


def beat_similarity(a: dict, b: dict) -> float:
    """تشابه تسلسل وظائف المشاهد — أهم إشارة: نفس العظام يعني نفس النمط."""
    fa, fb = blueprint_functions(a), blueprint_functions(b)
    if not fa or not fb:
        return 0.0
    # تشابه المحتوى الكلي
    content = jaccard(tokens(" ".join(fa)), tokens(" ".join(fb)))
    # تشابه الترتيب: نقارن كل خانة بمقابلتها بالموضع
    pairs = min(len(fa), len(fb))
    ordered = sum(ratio(fa[i], fb[i]) for i in range(pairs)) / pairs if pairs else 0.0
    # عقوبة لو عدد الخانات مختلف كتير
    length_penalty = min(len(fa), len(fb)) / max(len(fa), len(fb))
    return (0.55 * content + 0.45 * ordered) * length_penalty


def similarity(a: dict, b: dict) -> tuple[float, dict]:
    """يرجع (الدرجة الكلية، تفصيل المكوّنات)."""
    parts = {
        "framework": ratio(a.get("framework"), b.get("framework")),
        "hook": ratio((a.get("hook") or {}).get("type"), (b.get("hook") or {}).get("type")),
        "proof": ratio(a.get("proof_mechanism"), b.get("proof_mechanism")),
        "summary": jaccard(tokens(a.get("one_line_summary")), tokens(b.get("one_line_summary"))),
        "beats": beat_similarity(a, b),
        "name": ratio(a.get("pattern_name"), b.get("pattern_name")),
    }
    # الأوزان معايَرة على بيانات فعلية، مش تخمين:
    # الملخص والعظام بيكتبهم الموديل بصياغة حرة مستقلة لكل فيديو، فتشابههم
    # اللفظي ~18% للمكرر و~19% للمختلف — يعني ضجيج، لهيك وزنهم منخفض.
    # الاسم والإطار والهوك هم اللي بيفصلوا فعلياً بين المكرر والمختلف.
    weights = {"name": 0.30, "framework": 0.25, "hook": 0.20,
               "proof": 0.15, "summary": 0.05, "beats": 0.05}
    score = sum(parts[k] * w for k, w in weights.items())
    return score, parts


def load_library(patterns_dir) -> list[dict]:
    out = []
    for f in sorted(Path(patterns_dir).glob("*.pattern.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        p["_file"] = f.name
        p["_pattern_id"] = f.name.replace(".pattern.json", "")
        out.append(p)
    return out


def find_duplicates(candidate: dict, library: list[dict], limit: int = 3) -> list[dict]:
    """أقرب الأنماط الموجودة للمرشّح، مرتّبة تنازلياً."""
    scored = []
    for existing in library:
        if existing.get("_pattern_id") == candidate.get("_pattern_id"):
            continue
        score, parts = similarity(candidate, existing)
        if score >= SIMILAR_THRESHOLD:
            scored.append({
                "pattern_id": existing.get("_pattern_id"),
                "pattern_name": existing.get("pattern_name"),
                "score": round(score, 3),
                "is_duplicate": score >= DUPLICATE_THRESHOLD,
                "parts": {k: round(v, 2) for k, v in parts.items()},
            })
    scored.sort(key=lambda x: -x["score"])
    return scored[:limit]


def describe(matches: list[dict]) -> str:
    if not matches:
        return ""
    top = matches[0]
    kind = "مكرر" if top["is_duplicate"] else "قريب"
    lines = [f"[{kind}] أقرب نمط موجود: {top['pattern_name']} ({top['pattern_id']}) — تشابه {top['score']:.0%}"]
    p = top["parts"]
    lines.append(
        f"        العظام {p['beats']:.0%} · الملخص {p['summary']:.0%} · "
        f"الإطار {p['framework']:.0%} · الهوك {p['hook']:.0%}"
    )
    for m in matches[1:]:
        lines.append(f"        وكمان: {m['pattern_name']} — {m['score']:.0%}")
    return "\n".join(lines)
