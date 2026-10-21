#!/usr/bin/env python3
"""
كشف إرهاق الإعلان (المرحلة 6) — لإعلانات VP فقط (اللي بخانة VP- باسمها).

الإرهاق = تكلفة الطلب المُسلَّم (إنفاق ÷ مُسلَّم لكل يوم) بترتفع FATIGUE_DAYS أيام متتالية
(7 ارتفاعات يوماً بيوم = 8 نقاط) **ومعدل التفاعل بينزل** بنفس الفترة.

القواعد الصارمة (تحفّظ متعمَّد ضد الإنذار الكاذب):
  - أيام متتالية بالتقويم؛ يوم ناقص أو يوم بلا مُسلَّم بيكسر السلسلة.
  - الأيام غير الناضجة (PERF_MATURITY_DAYS) خارج الحساب — وإلا كل إعلان جديد بيبان «متعب».
  - التفاعل نازل = متوسط آخر ثلث النقاط أقل ≥5% من أول ثلث + ميل خطي سالب، وبيانات تفاعل لـ≥75% من النقاط.
  - ما في بيانات تفاعل كافية، أو حجم المُسلَّم بالفترة أقل من MIN_DELIVERED → `watch` (أضعف) مش fatigue.
  - تكلفة ترتفع 7 أيام والتفاعل مش نازل → `watch` بتوضيح إنه مش إرهاق مؤكد.
كل تنبيه fatigue بيجهّز مسودة (drafts.py) بتستنى موافقة قبل أي كتابة.
"""

from __future__ import annotations

import hashlib
import math
import sys
from datetime import date, datetime, timedelta

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import adname
import config
import crm
import evidence

ENGAGEMENT_MIN_DROP = 0.05        # هبوط التفاعل الأدنى (نسبي) بين أول الفترة وآخرها
ENGAGEMENT_MIN_COVERAGE = 0.75    # نسبة النقاط اللي لازم فيها بيانات تفاعل
MAX_STALE_DAYS = 2                # آخر نقطة لازم تكون قريبة من آخر يوم ناضج

last_errors: list[str] = []


def fatigue_days() -> int:
    return int(getattr(config, "FATIGUE_DAYS", 7))


def _slope(ys: list[float]) -> float:
    n = len(ys)
    mx, my = (n - 1) / 2, sum(ys) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den if den else 0.0


def _engagement_trend(points: list[dict]) -> dict:
    """{'state': 'falling'|'not_falling'|'no_data', 'start', 'end'}"""
    vals = [p["engagement"] for p in points if p["engagement"] is not None]
    if len(vals) < max(4, math.ceil(ENGAGEMENT_MIN_COVERAGE * len(points))):
        return {"state": "no_data", "start": None, "end": None}
    k = max(1, len(vals) // 3)
    start, end = sum(vals[:k]) / k, sum(vals[-k:]) / k
    falling = end < start * (1 - ENGAGEMENT_MIN_DROP) and _slope(vals) < 0
    return {"state": "falling" if falling else "not_falling", "start": start, "end": end}


def _alert_id(kind: str, ad_name: str, since: str) -> str:
    return "al_" + hashlib.sha1(f"{kind}|{ad_name}|{since}".encode("utf-8")).hexdigest()[:10]


def scan(today: date | None = None) -> list[dict]:
    """بيقرأ perf.db المخزّن بس (بدون شبكة) وبيرجع كل التنبيهات الحالية."""
    today = today or evidence.today()
    need = fatigue_days()
    cut = evidence.cutoff(today)
    rows = crm.perf_rows(until=cut.isoformat(), vp_only=True)

    series: dict[str, list[dict]] = {}
    for r in rows:
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        cpd = (r["spend"] / r["delivered"]) if r["delivered"] and r["delivered"] > 0 else None
        series.setdefault(r["ad_name"], []).append(
            {"date": d, "cpd": cpd, "engagement": r["engagement"], "delivered": r["delivered"] or 0,
             "script_id": r["script_id"]})

    alerts: list[dict] = []
    for ad_name, pts in sorted(series.items()):
        pts.sort(key=lambda p: p["date"])
        if pts[-1]["date"] < cut - timedelta(days=MAX_STALE_DAYS):
            continue                                    # الإعلان وقف أو بياناته قديمة

        rises, i = 0, len(pts) - 1
        while i > 0:
            a, b = pts[i - 1], pts[i]
            if a["cpd"] is None or b["cpd"] is None or (b["date"] - a["date"]).days != 1 or b["cpd"] <= a["cpd"]:
                break
            rises += 1
            i -= 1
        if rises < need:
            continue

        window = pts[len(pts) - rises - 1:]
        since = window[0]["date"].isoformat()
        eng = _engagement_trend(window)
        delivered = sum(p["delivered"] for p in window)
        cost = f"تكلفة الطلب المُسلَّم ارتفعت {rises} أيام متتالية ({window[0]['cpd']:.2f} ← {window[-1]['cpd']:.2f})"

        low_volume = delivered < evidence.min_delivered()
        if eng["state"] == "falling" and not low_volume:
            kind, detail = "fatigue", (f"{cost} والتفاعل نازل ({eng['start']:.2%} ← {eng['end']:.2%}) — "
                                       "علامة إرهاق. جاهز بريف لسيناريو جديد بانتظار موافقتك.")
        elif eng["state"] == "falling":
            kind, detail = "watch", (f"{cost} والتفاعل نازل، بس المُسلَّم بالفترة {delivered} أقل من "
                                     f"{evidence.min_delivered()} — البيانات قليلة للجزم بالإرهاق.")
        elif eng["state"] == "no_data":
            kind, detail = "watch", f"{cost}. ما في بيانات تفاعل كافية للحكم بالإرهاق."
        else:
            kind, detail = "watch", f"{cost} بس التفاعل مش نازل — مش إرهاق مؤكد، راقب."

        parsed = adname.parse(ad_name)
        alerts.append({
            "id": _alert_id(kind, ad_name, since), "ad_name": ad_name,
            "script_id": pts[-1]["script_id"], "type": kind, "since": since,
            "until": window[-1]["date"].isoformat(), "days": rises, "detail": detail,
            "product_code": parsed["product"], "country": parsed["country"],
        })
    return alerts


def current_alerts(today: date | None = None) -> list[dict]:
    """التنبيهات + draft_id لو في مسودة. المسودة المرفوضة (dismissed) بتخفي التنبيه."""
    import drafts
    out = []
    for a in scan(today):
        d = drafts.get_for(a["ad_name"], a["since"]) if a["type"] == "fatigue" else None
        if d and d["status"] == "dismissed":
            continue
        out.append({**a, **({"draft_id": d["id"], "draft_status": d["status"]} if d else {})})
    return out


def scan_and_draft(today: date | None = None) -> list[str]:
    """
    idempotent: لكل تنبيه fatigue بلا مسودة (نفس الإعلان + نفس بداية الفترة) بيجهّز مسودة.
    بيرجع معرّفات المسودات **الجديدة** بس.
    """
    import drafts
    del last_errors[:]
    created: list[str] = []
    for a in scan(today):
        if a["type"] != "fatigue" or drafts.get_for(a["ad_name"], a["since"]):
            continue
        try:
            created.append(drafts.create(a, today=today)["id"])
        except Exception as e:
            last_errors.append(f"{a['ad_name']}: {e}")
    return created


def main() -> int:
    ids = scan_and_draft()
    print(f"[✓] مسودات جديدة: {len(ids)}" + ("".join(f"\n    {i}" for i in ids)))
    for err in last_errors:
        print(f"[!] {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
