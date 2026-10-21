"""
دليل الأداء الفعلي — من perf.db (الـ OMS) + السيناريوهات.

القاعدة المؤسسة: النمط الجيد هو الي جاب طلبات **مُسلَّمة** بتكلفة منخفضة — مش الي الموديل
قيّمه عالي ولا الي جاب مشاهدات. `reusability_score` رأي فقط؛ درجة الدليل هي اللي بتقود.

المعادلات (ثوابت مسمّاة بالأسفل، وأي `config.X` بنفس الاسم بيغلبها):

  تكلفة الطلب المُسلَّم (cpd)  = الإنفاق ÷ المُسلَّم
  خط الأساس للسيناريو         = وسيط cpd لسيناريوهات نفس (المنتج، البلد) اللي فيها مُسلَّم ≥ MIN_DELIVERED
                                 (لازم ≥ MIN_BASELINE_SCRIPTS منها، وإلا ما في حكم — الوسيط من سيناريو
                                 أو اثنين هو تقريباً السيناريو نفسه)
  حكم السيناريو               = winner لو cpd ≤ 0.8×الأساس · loser لو ≥ 1.25×الأساس · وإلا ok
                                 (النسبتان متناظرتان بالمقياس اللوغاريتمي: 0.8 = 1/1.25)
                                 insufficient لو المُسلَّم < MIN_DELIVERED أو ما في أساس

  للنمط:
    rel   = الإنفاق الفعلي ÷ الإنفاق المتوقع بتكلفة الأساس (Σ مُسلَّم_i × أساس_i)   [1 = عند الأساس]
    كفاءة = clamp(50 − 50·log2(rel), 0..100)   [rel=0.5→100 · 1→50 · 2→0؛ بلا أساس → 50 محايد]
    عيّنة = 1 − e^(−المُسلَّم / 100)            [20→0.18 · 60→0.45 · 100→0.63 · 200→0.86 · 300→0.95]
    evidence_score = round(كفاءة × عيّنة)

  ليش الضرب: الكفاءة العالية على عيّنة صغيرة ما بتستاهل ثقة، والحجم الكبير بتكلفة سيئة ما بيرفع شي.
  بلا أساس السقف 50 — ما منقدر ندّعي كفاءة بلا مقارنة.

  evidence_level: unproven لو المُسلَّم < MIN_DELIVERED · proven لو المُسلَّم ≥ 3×MIN_DELIVERED
  وعبر ≥ 2 سيناريو وrel ≤ 1 (بتكلفة الأساس أو أفضل) · وإلا weak.

النضج: التسليم بالـ COD بيوصل بعد أيام من الطلب، فأحدث `PERF_MATURITY_DAYS` أيام بتنشال من كل الحسابات
(وإلا بتظهر تكلفة كل إعلان جديد أغلى مما هي).

بلا اتصال: كل شي بيشتغل من آخر بيانات مخزّنة، والنتايج فيها `as_of` (تاريخ آخر مزامنة ناجحة).
إعلان بلا `script_id` (خانة VP-) بره الحساب كلياً.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import adname
import config
import crm
import pattern_text

MIN_BASELINE_SCRIPTS = 3
WINNER_RATIO = 0.80
LOSER_RATIO = 1.25
SATURATION_DELIVERED = 100.0
PROVEN_DELIVERED_FACTOR = 3
PROVEN_MIN_SCRIPTS = 2
PERF_MATURITY_DAYS = 3


def _cfg(name: str, default):
    return getattr(config, name, default)


def min_delivered() -> int:
    return int(_cfg("MIN_DELIVERED", 20))


def maturity_days() -> int:
    return int(_cfg("PERF_MATURITY_DAYS", PERF_MATURITY_DAYS))


def today() -> date:
    return date.today()


def cutoff(day: date | None = None) -> date:
    """آخر يوم ناضج مسموح استخدامه."""
    return (day or today()) - timedelta(days=maturity_days())


# ───────────────────────────── تحميل السيناريوهات ─────────────────────────────


def load_scripts() -> dict[str, dict]:
    """script_id → {file, pattern_id, product_code, product, product_file}. السيناريو بلا script_id بره."""
    out: dict[str, dict] = {}
    for f in sorted(Path(config.SCRIPTS_DIR).glob("*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta = s.get("_meta") or {}
        sid = meta.get("script_id")
        if not adname.is_script_id(sid):
            continue
        hook_of = meta.get("hook_of") if isinstance(meta.get("hook_of"), dict) else {}
        out[sid] = {"file": f.name, "pattern_id": meta.get("pattern_id"),
                    "product_code": meta.get("product_code") or None,
                    "product": meta.get("product"), "product_file": meta.get("product_file"),
                    # نسخ الهوك بتنجمع مع الإعلان الأساسي: هي نفس السيناريو بافتتاحية تانية، مش سيناريوهات مستقلة
                    "group": hook_of.get("base_script_id") or sid}
    return out


def _load_patterns() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[f.name.replace(".pattern.json", "")] = p
    return out


def _aggregate(today: date | None) -> dict[str, dict]:
    """script_id → مجاميع الأداء الناضج (كل إعلانات السيناريو مجموعة)."""
    rows = crm.perf_rows(until=cutoff(today).isoformat(), vp_only=True)
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.setdefault(r["script_id"], {
            "spend": 0.0, "orders": 0, "delivered": 0, "collected": 0,
            "first": r["date"], "last": r["date"], "_days": set(), "_countries": {}, "_product": None})
        a["spend"] += r["spend"] or 0.0
        a["orders"] += r["orders"] or 0
        a["delivered"] += r["delivered"] or 0
        a["collected"] += r["collected"] or 0
        a["first"], a["last"] = min(a["first"], r["date"]), max(a["last"], r["date"])
        a["_days"].add(r["date"])
        parsed = adname.parse(r["ad_name"])
        if parsed["country"]:
            a["_countries"][parsed["country"]] = a["_countries"].get(parsed["country"], 0) + (r["spend"] or 0)
        a["_product"] = a["_product"] or parsed["product"]
    for a in agg.values():
        c = a.pop("_countries")
        a["country"] = max(c, key=c.get) if c else None
        a["days"] = len(a.pop("_days"))
    return agg


def _cpd(spend: float, delivered: int) -> float | None:
    return round(spend / delivered, 4) if delivered > 0 else None


# ───────────────────────────── أحكام السيناريوهات ─────────────────────────────


def script_verdicts(today: date | None = None) -> dict[str, dict]:
    """{script_file: {...}} لكل سيناريو له script_id (بلا بيانات → insufficient)."""
    scripts, agg = load_scripts(), _aggregate(today)
    as_of = crm.data_as_of()
    min_d = min_delivered()

    rows: list[dict] = []
    raw: dict[str, tuple[float, int]] = {}
    for sid, sc in scripts.items():
        a = agg.get(sid) or {"spend": 0.0, "orders": 0, "delivered": 0, "collected": 0,
                             "first": None, "last": None, "country": None, "days": 0, "_product": None}
        raw[sid] = (a["spend"], a["delivered"])
        rows.append({
            "script_file": sc["file"], "script_id": sid, "group": sc["group"], "pattern_id": sc["pattern_id"],
            "product_code": sc["product_code"] or a.get("_product"), "country": a["country"],
            "spend": round(a["spend"], 2), "orders": a["orders"], "delivered": a["delivered"],
            "collected": a["collected"],
            "delivery_rate": round(a["delivered"] / a["orders"], 4) if a["orders"] else None,
            "cost_per_delivered": _cpd(a["spend"], a["delivered"]),
            "days": a["days"], "first_date": a["first"], "last_date": a["last"], "as_of": as_of,
        })

    # عيّنة وحدة لكل مجموعة هوك (الأساسي + نسخه مجموعين)، وإلا 3 نسخ من نفس السيناريو بتملّي خط الأساس لحالها
    by_group: dict[tuple, list[float | int]] = {}
    for r in rows:
        spend, delivered = raw[r["script_id"]]
        g = by_group.setdefault((r["product_code"], r["country"], r["group"]), [0.0, 0])
        g[0] += spend
        g[1] += delivered
    groups: dict[tuple, list[float]] = {}
    for (pc, ctry, _grp), (spend, delivered) in by_group.items():
        cpd = _cpd(spend, delivered)
        if delivered >= min_d and cpd is not None:
            groups.setdefault((pc, ctry), []).append(cpd)
    need = int(_cfg("MIN_BASELINE_SCRIPTS", MIN_BASELINE_SCRIPTS))
    win_r, lose_r = float(_cfg("WINNER_RATIO", WINNER_RATIO)), float(_cfg("LOSER_RATIO", LOSER_RATIO))

    out: dict[str, dict] = {}
    for r in rows:
        costs = groups.get((r["product_code"], r["country"]), [])
        base = round(statistics.median(costs), 4) if len(costs) >= need else None
        r["baseline_cpd"], r["cost_vs_baseline"] = base, None

        if r["spend"] == 0 and r["orders"] == 0:
            verdict, reason = "insufficient", "لا توجد بيانات أداء ناضجة بعد"
        elif r["delivered"] < min_d:
            verdict = "insufficient"
            reason = f"مُسلَّم {r['delivered']} أقل من الحد الأدنى {min_d} — لا حكم بعد"
        elif base is None:
            verdict = "insufficient"
            reason = (f"لا خط أساس كافٍ لنفس المنتج والبلد (يلزم {need} سيناريوهات على الأقل "
                      f"بمُسلَّم ≥ {min_d}، عندنا {len(costs)})")
        else:
            ratio = r["cost_per_delivered"] / base
            r["cost_vs_baseline"] = round(ratio, 3)
            detail = (f"تكلفة الطلب المُسلَّم {r['cost_per_delivered']:.2f} = {ratio:.0%} "
                      f"من وسيط المنتج/البلد ({base:.2f}) على {r['delivered']} طلب مُسلَّم")
            if ratio <= win_r:
                verdict, reason = "winner", f"أرخص بوضوح: {detail}"
            elif ratio >= lose_r:
                verdict, reason = "loser", f"أغلى بوضوح: {detail}"
            else:
                verdict, reason = "ok", f"ضمن المعتاد: {detail}"
        r["verdict"], r["reason"] = verdict, reason
        out[r["script_file"]] = r
    return out


# ───────────────────────────── دليل الأنماط ─────────────────────────────


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def pattern_evidence(today: date | None = None, verdicts: dict | None = None) -> dict[str, dict]:
    """
    {pattern_id: {...}} لكل نمط بالمكتبة + أي نمط مذكور بسيناريو. نمط بلا أداء = unproven بدرجة 0.
    """
    verdicts = script_verdicts(today) if verdicts is None else verdicts
    patterns = _load_patterns()
    as_of = crm.data_as_of()
    min_d = min_delivered()

    by_pattern: dict[str, list[dict]] = {}
    for v in verdicts.values():
        if v["pattern_id"]:
            by_pattern.setdefault(v["pattern_id"], []).append(v)

    out: dict[str, dict] = {}
    for pid in sorted(set(patterns) | set(by_pattern)):
        vs = by_pattern.get(pid, [])
        with_data = [v for v in vs if v["spend"] > 0 or v["delivered"] > 0]
        spend = round(sum(v["spend"] for v in with_data), 2)
        delivered = sum(v["delivered"] for v in with_data)
        orders = sum(v["orders"] for v in with_data)

        based = [v for v in with_data if v["baseline_cpd"]]
        expected = sum(v["delivered"] * v["baseline_cpd"] for v in based)
        rel = (sum(v["spend"] for v in based) / expected) if expected > 0 else None
        efficiency = 50.0 if rel is None else _clamp(50 - 50 * math.log2(max(rel, 1e-6)))
        sample = 1 - math.exp(-delivered / float(_cfg("SATURATION_DELIVERED", SATURATION_DELIVERED)))
        score = round(efficiency * sample)

        n_scripts = len({v.get("group") or v["script_id"] for v in with_data if v["delivered"] > 0})   # نسخ الهوك = سيناريو وحد
        proven_at = int(_cfg("PROVEN_DELIVERED_FACTOR", PROVEN_DELIVERED_FACTOR)) * min_d
        min_scripts = int(_cfg("PROVEN_MIN_SCRIPTS", PROVEN_MIN_SCRIPTS))

        if delivered < min_d:
            level = "unproven"
            reason = (f"غير مثبت: مُسلَّم {delivered} من أصل {min_d} مطلوب" if with_data
                      else "غير مثبت: لا أداء فعلي مسجّل لهذا النمط")
        elif rel is None:
            level, reason = "weak", "ضعيف: لا خط أساس للمقارنة بعد"
        elif delivered < proven_at:
            level, reason = "weak", f"ضعيف: مُسلَّم {delivered} أقل من {proven_at} المطلوب للإثبات"
        elif n_scripts < min_scripts:
            level, reason = "weak", f"ضعيف: سيناريو واحد فقط — الإثبات بيلزمه {min_scripts} على الأقل"
        elif rel > 1.0:
            level, reason = "weak", f"ضعيف: تكلفته {rel:.0%} من الأساس (أغلى من المعتاد)"
        else:
            level = "proven"
            reason = f"مثبت: {delivered} طلب مُسلَّم عبر {n_scripts} سيناريو بتكلفة {rel:.0%} من الأساس"

        p = patterns.get(pid) or {}
        out[pid] = {
            "pattern_id": pid, "name": pattern_text.display_name(p) or pid,
            "delivered": delivered, "spend": spend, "orders": orders,
            "cost_per_delivered": _cpd(spend, delivered),
            "scripts": n_scripts, "scripts_total": len(vs),
            "cost_vs_baseline": round(rel, 3) if rel is not None else None,
            "baseline_available": rel is not None,
            "evidence_score": score, "evidence_level": level, "reason": reason,
            "reusability_opinion": p.get("reusability_score"),
            "product_category": p.get("product_category"),
            "as_of": as_of,
        }
    return out


def _opinion(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def ranked_patterns(today: date | None = None) -> list[dict]:
    """الأنماط مرتّبة بدرجة الدليل (الرأي بيكسر التعادل بس)."""
    return sorted(pattern_evidence(today).values(),
                  key=lambda e: (-e["evidence_score"], -(e["delivered"]),
                                 -_opinion(e["reusability_opinion"]), e["pattern_id"]))
