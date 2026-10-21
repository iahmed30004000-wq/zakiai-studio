"""
تتبّع الاستهلاك والتكلفة.

ليش محلي: Anthropic ما بتوفّر endpoint للرصيد المتبقّي (بس تقارير عبر Admin API
بمفتاح إداري منفصل). بالمقابل كل رد من أي مزوّد بيرجع عدد التوكنز، فمنسجّلها
محلياً ومنحسب التكلفة من جدول أسعار — وهاد بيشتغل مع كل المزوّدين بدون صلاحيات زيادة.

بعض المزوّدين (DeepSeek) عندهم endpoint للرصيد فعلاً — منسأله مباشرة.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent / "library" / "usage.db"

# دولار لكل مليون توكن (إدخال، إخراج). تقديرية — الأسعار بتتغيّر،
# عدّلها من settings.json بمفتاح PRICING إذا اختلفت.
DEFAULT_PRICING = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.5),
    "grok-4": (3.0, 15.0),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "kimi-k2-0905-preview": (0.60, 2.50),
    "kimi-k2-turbo-preview": (1.15, 8.00),
    "qwen-max": (1.60, 6.40),
    "qwen-plus": (0.40, 1.20),
    "glm-4.6": (0.60, 2.20),
}

# مزوّدين بيوفّروا رصيد فعلي — تم التحقق منهم
BALANCE_ENDPOINTS = {
    "deepseek": {
        "url": "https://api.deepseek.com/user/balance",
        "parse": lambda d: (
            f"{d['balance_infos'][0]['total_balance']} {d['balance_infos'][0]['currency']}"
            if d.get("balance_infos") else None
        ),
    },
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                at            TEXT NOT NULL,
                task          TEXT NOT NULL,
                provider      TEXT NOT NULL,
                model         TEXT NOT NULL,
                input_tokens  INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd      REAL NOT NULL DEFAULT 0,
                ok            INTEGER NOT NULL DEFAULT 1
            )
            """
        )


def pricing() -> dict:
    """جدول الأسعار مع أي تعديل محفوظ بالإعدادات."""
    table = dict(DEFAULT_PRICING)
    try:
        import settings_io
        for model, pair in (settings_io.load().get("PRICING") or {}).items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                table[model] = (float(pair[0]), float(pair[1]))
    except Exception:
        pass
    return table


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    table = pricing()
    rate = table.get(model)
    if rate is None:
        # جرّب مطابقة جزئية — أسماء البوابات فيها بادئة مثل "anthropic/claude-sonnet-5"
        for known, pair in table.items():
            if known in model or model.endswith(known):
                rate = pair
                break
    if rate is None:
        return 0.0
    return (input_tokens / 1e6) * rate[0] + (output_tokens / 1e6) * rate[1]


def record(task: str, provider: str, model: str,
           input_tokens: int, output_tokens: int, ok: bool = True) -> None:
    init_db()
    cost = estimate_cost(model, input_tokens, output_tokens)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO calls (at, task, provider, model, input_tokens, output_tokens, cost_usd, ok) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
             task, provider, model, input_tokens, output_tokens, cost, int(ok)),
        )


def summary(days: int | None = None) -> dict:
    init_db()
    where = ""
    params: tuple = ()
    if days:
        where = "WHERE at >= datetime('now', ?)"
        params = (f"-{int(days)} days",)

    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) inp, "
            f"COALESCE(SUM(output_tokens),0) outp, COALESCE(SUM(cost_usd),0) cost "
            f"FROM calls {where}", params
        ).fetchone()
        by_model = conn.execute(
            f"SELECT model, provider, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
            f"COALESCE(SUM(input_tokens),0) inp, COALESCE(SUM(output_tokens),0) outp "
            f"FROM calls {where} GROUP BY model, provider ORDER BY cost DESC", params
        ).fetchall()
        by_task = conn.execute(
            f"SELECT task, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost "
            f"FROM calls {where} GROUP BY task ORDER BY cost DESC", params
        ).fetchall()
        recent = conn.execute(
            "SELECT at, task, provider, model, input_tokens, output_tokens, cost_usd, ok "
            "FROM calls ORDER BY id DESC LIMIT 15"
        ).fetchall()

    return {
        "calls": total["n"],
        "input_tokens": total["inp"],
        "output_tokens": total["outp"],
        "cost_usd": round(total["cost"], 4),
        "by_model": [dict(r) for r in by_model],
        "by_task": [dict(r) for r in by_task],
        "recent": [dict(r) for r in recent],
        "unpriced_models": sorted({
            r["model"] for r in by_model if estimate_cost(r["model"], 1_000_000, 0) == 0
        }),
    }


# ── حدود الإنفاق ─────────────────────────────────────────────────────────
# SETTINGS["SPEND_LIMITS"] = {"daily_usd": 5, "monthly_usd": 100}. فاضي أو صفر = بلا حد.
# الإنفاق تقديري (توكنز × جدول الأسعار)، ومحسوب من نداءات الموديلات المسجّلة بـ calls.


class SpendLimitReached(Exception):
    """الإنفاق التقديري وصل الحد — الرسالة عربية جاهزة للعرض."""


def _local_period_start_utc(period: str) -> str:
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        start = start.replace(day=1)
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


def spent_since(period: str) -> float:
    """الإنفاق التقديري باليوم أو الشهر الحالي (بتوقيت الجهاز)."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) c FROM calls WHERE at >= ?",
            (_local_period_start_utc(period),),
        ).fetchone()
    return float(row["c"])


def get_limits() -> dict:
    import settings_io
    raw = settings_io.load().get("SPEND_LIMITS") or {}
    out = {}
    for key in ("daily_usd", "monthly_usd"):
        try:
            v = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        out[key] = v if v > 0 else None
    return out


def set_limits(daily_usd, monthly_usd) -> dict:
    import settings_io
    vals = {}
    for key, v in (("daily_usd", daily_usd), ("monthly_usd", monthly_usd)):
        if v in (None, ""):
            vals[key] = None
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError("الحد لازم يكون رقم بالدولار")
        if f < 0:
            raise ValueError("الحد ما بيكون سالب")
        vals[key] = f or None

    def mutate(d: dict) -> None:
        d["SPEND_LIMITS"] = {k: v for k, v in vals.items()}

    settings_io.update(mutate)
    return get_limits()


def limit_status() -> dict:
    limits = get_limits()
    day, month = spent_since("day"), spent_since("month")
    reasons = []
    if limits["daily_usd"] is not None and day >= limits["daily_usd"]:
        reasons.append(
            f"وصلت حد الإنفاق اليومي (${day:.2f} من ${limits['daily_usd']:.2f}) — "
            "ارفع الحد من الإعدادات أو استنى لبكرا"
        )
    if limits["monthly_usd"] is not None and month >= limits["monthly_usd"]:
        reasons.append(
            f"وصلت حد الإنفاق الشهري (${month:.2f} من ${limits['monthly_usd']:.2f}) — "
            "ارفع الحد من الإعدادات أو استنى للشهر الجاي"
        )
    return {
        "limits": limits,
        "spent": {"daily_usd": round(day, 4), "monthly_usd": round(month, 4)},
        "blocked": bool(reasons),
        "reason": reasons[0] if reasons else None,
    }


def check_spend_limits() -> None:
    """يرمي SpendLimitReached إذا وصل أي حد. بيتنادى قبل كل نداء موديل."""
    st = limit_status()
    if st["blocked"]:
        raise SpendLimitReached(st["reason"])


def provider_balance(provider: str, api_key: str) -> dict:
    """يسأل المزوّد عن رصيده لو كان بيدعم ذلك."""
    spec = BALANCE_ENDPOINTS.get(provider)
    if not spec:
        return {"supported": False,
                "reason": f"{provider} ما بيوفّر استعلام رصيد عبر الـ API"}
    if not api_key:
        return {"supported": True, "error": "ما في مفتاح لهالمزوّد"}
    try:
        r = requests.get(spec["url"], headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    except requests.RequestException as e:
        return {"supported": True, "error": f"فشل الاتصال: {e}"}
    if r.status_code != 200:
        return {"supported": True, "error": f"رد {r.status_code}: {r.text[:150]}"}
    try:
        return {"supported": True, "balance": spec["parse"](r.json())}
    except (ValueError, KeyError, IndexError) as e:
        return {"supported": True, "error": f"رد غير متوقّع: {e}"}
