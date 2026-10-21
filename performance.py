"""
تسجيل أداء السيناريوهات المنتَجة.

السيناريو مخرَج آلي؛ الأداء شي بتضيفه إنت بعد ما تنزّل الإعلان. لهيك محفوظ
بملف منفصل بدل ما نعدّل ملفات السيناريوهات المولّدة.

النتيجة بتغذّي شغلتين:
  1. learn_patterns.py — بيستخرج أنماط جديدة من السيناريوهات الناجحة
  2. المطابقة — بتفضّل الأنماط اللي أثبتت نجاحها عندك فعلياً
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config

PERF_PATH = Path(config.LIBRARY_DIR) / "performance.json"

# الحكم على الإعلان — مرتّب من الأفضل للأسوأ
RESULTS = {
    "winner": "ناجح — شغّلته وربح",
    "ok": "متوسط — اشتغل بس مش مميّز",
    "loser": "فاشل — ما اشتغل",
    "untested": "ما انجرّب بعد",
}

# مقاييس اختيارية — كلها بتنفع للتحليل بس ولا وحدة إلزامية
METRICS = ["spend", "revenue", "roas", "ctr", "views", "orders", "cpm", "hook_rate"]


def load() -> dict:
    if PERF_PATH.exists():
        try:
            return json.loads(PERF_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save(data: dict) -> None:
    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mark(script_file: str, result: str, metrics: dict | None = None, notes: str = "") -> dict:
    if result not in RESULTS:
        raise ValueError(f"نتيجة غير معروفة: {result}")

    data = load()
    entry = data.get(script_file, {})
    entry["result"] = result
    entry["notes"] = notes
    entry["marked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    clean = {}
    for k, v in (metrics or {}).items():
        if k not in METRICS or v in ("", None):
            continue
        try:
            clean[k] = float(v)
        except (TypeError, ValueError):
            continue
    entry["metrics"] = clean

    data[script_file] = entry
    save(data)
    return entry


def get(script_file: str) -> dict:
    return load().get(script_file, {})


def by_result(result: str) -> list[str]:
    return [f for f, e in load().items() if e.get("result") == result]


def _script_pattern(script_file: str) -> str | None:
    path = Path(config.SCRIPTS_DIR) / script_file
    if not path.exists():
        return None
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return (script.get("_meta") or {}).get("pattern_id") or None


def pattern_scoreboard() -> dict:
    """
    أداء كل نمط حسب السيناريوهات اللي اتولّدت منه — مرتّب بدرجة الدليل (الأداء الفعلي من
    الـ OMS: طلبات مُسلَّمة بتكلفة منخفضة)، مش بتقييم الموديل ولا بالمشاهدات.

    المفاتيح القديمة (winner/ok/loser/win_rate/roas…) باقية لأن المطابقة بتقراها.
    الحكم على السيناريو: حكم الدليل الآلي لو موجود (winner/ok/loser)، وإلا التعليم اليدوي القديم.
    الأنماط بلا أي أداء (يدوي أو CRM) مش بالقائمة = غير مثبتة؛ evidence.pattern_evidence() فيها الكل.
    """
    try:
        import evidence
        verdicts = evidence.script_verdicts()
        pev = evidence.pattern_evidence(verdicts=verdicts)
    except Exception:
        verdicts, pev = {}, {}

    manual = load()
    board: dict[str, dict] = {}

    def entry(pid: str) -> dict:
        return board.setdefault(pid, {"winner": 0, "ok": 0, "loser": 0, "untested": 0,
                                      "scripts": [], "total_revenue": 0.0, "total_spend": 0.0})

    for script_file, v in verdicts.items():
        pid = v.get("pattern_id")
        if not pid or not (v["spend"] > 0 or v["delivered"] > 0):
            continue
        b = entry(pid)
        b[v["verdict"] if v["verdict"] in ("winner", "ok", "loser") else "untested"] += 1
        b["scripts"].append(script_file)

    for script_file, m in manual.items():
        pid = (verdicts.get(script_file) or {}).get("pattern_id") or _script_pattern(script_file)
        if not pid:
            continue
        b = entry(pid)
        if script_file not in b["scripts"]:
            b[m.get("result", "untested")] += 1
            b["scripts"].append(script_file)
        b["total_revenue"] += m.get("metrics", {}).get("revenue", 0.0)
        b["total_spend"] += m.get("metrics", {}).get("spend", 0.0)

    for pid, b in board.items():
        judged = b["winner"] + b["ok"] + b["loser"]
        b["judged"] = judged
        b["win_rate"] = round(b["winner"] / judged, 2) if judged else None
        b["roas"] = round(b["total_revenue"] / b["total_spend"], 2) if b["total_spend"] else None
        e = pev.get(pid) or {}
        b.update({
            "delivered": e.get("delivered", 0), "spend": e.get("spend", 0.0),
            "cost_per_delivered": e.get("cost_per_delivered"),
            "evidence_level": e.get("evidence_level", "unproven"),
            "evidence_score": e.get("evidence_score", 0),
            "evidence_reason": e.get("reason"),
            "cost_vs_baseline": e.get("cost_vs_baseline"),
            "reusability_opinion": e.get("reusability_opinion"),
        })
    return dict(sorted(board.items(), key=lambda kv: (-kv[1]["evidence_score"], -kv[1]["delivered"], kv[0])))
