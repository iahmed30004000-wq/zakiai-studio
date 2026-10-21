#!/usr/bin/env python3
"""
عميل الـ OMS — قراءة فقط، والاتصال دايماً من الجهاز باتجاه السيرفر (سحب مش دفع).

    python crm.py sync      # يسحب الأداء من آخر مزامنة ناجحة لليوم
    python crm.py status

القواعد:
  - HTTPS إجباري (إلا localhost للتطوير). التوكن من مخزن الأسرار وما بينكتب بأي ملف.
  - الجهاز ممكن يكون مطفي: المزامنة بتكمّل من آخر نقطة ناجحة (مع رجعة أيام لأن حالات
    التسليم بتنضج متأخرة)، والكتابة upsert فما في تكرار ولا يوم بيضيع.
  - أرقام مجمّعة لكل (إعلان، يوم) فقط. أي حقل مش بالقائمة البيضاء بيتشال قبل الحفظ.
  - بلا اتصال: آخر بيانات مخزّنة بتضل مستخدمة، ومعها تاريخها.
عقد الطرف التاني: CRM_CONTRACT.md
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import requests

import adname
import config

PERF_PATH = "/api/vidpattern/ad-performance"
FACTS_PATH = "/api/vidpattern/product-market"
FAILURES_PATH = "/api/vidpattern/failure-reasons"

# التسليم بالـ COD بينضج بعد أيام من الطلب، فكل مزامنة بتعيد سحب آخر أيام
RESYNC_LOOKBACK_DAYS = 14
INITIAL_BACKFILL_DAYS = 60
WINDOW_DAYS = 31                      # سقف نطاق الطلب الواحد
CONNECT_TIMEOUT, READ_TIMEOUT = 5, 30
MAX_FAILURE_REASONS = 20

# أي مفتاح غير هدول بيتشال بدون حفظ — مبدأ عدم تخزين بيانات زبائن
ROW_KEYS = ("ad_name", "date", "spend", "orders", "delivered", "collected",
            "delivery_rate", "cost_per_delivered", "engagement")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _cfg(name: str, default):
    return getattr(config, name, default)


class CRMError(Exception):
    """رفض أو شكل غلط (4xx / استجابة مش مطابقة للعقد) — إعادة المحاولة ما بتفيد."""


class CRMOffline(Exception):
    """شبكة / 5xx / انقطاع. `cached`/`cached_at`: آخر بيانات مخزّنة (لو موجودة)."""

    def __init__(self, message: str = "", cached=None, cached_at: str | None = None):
        super().__init__(message)
        self.cached = cached
        self.cached_at = cached_at


class CRMNotConfigured(CRMOffline):
    """ما في base_url أو توكن — بنعاملها كأوفلاين عشان الاستهلاك يظل على المخزّن."""


# ───────────────────────────── الإعدادات والتوكن ─────────────────────────────


def _lib() -> Path:
    return Path(config.LIBRARY_DIR)


def _read_settings_file() -> dict:
    try:
        return json.loads(Path(config.SETTINGS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def base_url() -> str:
    try:
        import settings_io
        cfg = settings_io.load()
    except Exception:
        cfg = _read_settings_file()
    return str((cfg.get("CRM") or {}).get("base_url") or "").strip().rstrip("/")


def get_token() -> str | None:
    tok = None
    try:
        import secrets_store
        tok = secrets_store.get_secret("crm_token")
    except Exception:
        tok = None
    # للاختبار فقط — ما بنكتبه ولا بنخزّنه
    return tok or os.environ.get("VP_CRM_TOKEN") or None


def validate_base_url(url: str) -> str:
    """يرجّع العنوان منظّف أو يرمي CRMError. https إجباري عدا localhost."""
    url = str(url or "").strip().rstrip("/")
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if not host or p.scheme not in ("http", "https"):
        raise CRMError("عنوان الـ OMS غير صالح — لازم يبدأ بـ https://")
    if p.scheme != "https" and host not in _LOCAL_HOSTS:
        raise CRMError("الاتصال بالـ OMS لازم يكون HTTPS (http مسموح فقط لـ localhost)")
    if p.username or p.password or p.query or p.fragment:
        raise CRMError("عنوان الـ OMS لازم يكون بلا بيانات دخول أو باراميترات")
    return url


def is_configured() -> bool:
    return bool(base_url()) and bool(get_token())


class CRMClient:
    def __init__(self, url: str, token: str):
        self.base_url = validate_base_url(url)
        self._token = token

    def _request(self, method: str, path: str, **kw):
        try:
            r = requests.request(
                method, self.base_url + path,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=False,       # التحويل ممكن يودّي التوكن لمضيف تاني
                **kw,
            )
        except requests.exceptions.SSLError:
            raise CRMError("شهادة HTTPS للـ OMS غير صالحة")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            raise CRMOffline("تعذّر الوصول للـ OMS (شبكة أو السيرفر مطفي)")
        except requests.exceptions.RequestException as e:
            raise CRMError(f"طلب غير صالح للـ OMS: {type(e).__name__}")

        code = r.status_code
        if code >= 500:
            raise CRMOffline(f"الـ OMS غير متاح مؤقتاً (HTTP {code})")
        if code in (401, 403):
            raise CRMError("الـ OMS رفض التوكن — تأكد منه بالإعدادات")
        if 300 <= code < 400:
            raise CRMError(f"الـ OMS حوّل الطلب (HTTP {code}) — تحقق من العنوان")
        if code >= 400:
            raise CRMError(f"الـ OMS رفض الطلب (HTTP {code})")
        try:
            return r.json()
        except ValueError:
            raise CRMError("استجابة الـ OMS مش JSON صالح")

    def get(self, path: str, **kw):
        return self._request("GET", path, **kw)

    def post(self, path: str, **kw):
        return self._request("POST", path, **kw)

    def put(self, path: str, **kw):
        return self._request("PUT", path, **kw)


def get_client() -> CRMClient:
    url, tok = base_url(), get_token()
    if not url:
        raise CRMNotConfigured("عنوان الـ OMS غير مضبوط بالإعدادات")
    if not tok:
        raise CRMNotConfigured("توكن الـ OMS غير مضبوط")
    return CRMClient(url, tok)


# ───────────────────────────── تخزين الأداء اليومي ─────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ad_daily (
    ad_name TEXT NOT NULL,
    script_id TEXT,
    date TEXT NOT NULL,
    spend REAL NOT NULL DEFAULT 0,
    orders INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    collected INTEGER NOT NULL DEFAULT 0,
    delivery_rate REAL,
    cost_per_delivered REAL,
    engagement REAL,
    synced_at TEXT,
    PRIMARY KEY (ad_name, date)
);
CREATE INDEX IF NOT EXISTS idx_ad_daily_script ON ad_daily(script_id);
"""


def perf_db_path() -> Path:
    return _lib() / "perf.db"


def _connect() -> sqlite3.Connection:
    path = perf_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _num(raw: dict, key: str, *, required: bool, integer: bool = False):
    v = raw.get(key)
    if v is None or v == "":
        if required:
            raise CRMError(f"استجابة الـ OMS ناقصة: الحقل «{key}»")
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CRMError(f"استجابة الـ OMS: قيمة غير رقمية بالحقل «{key}»")
    if f < 0 or f != f:
        raise CRMError(f"استجابة الـ OMS: قيمة سالبة/غير صالحة بالحقل «{key}»")
    return int(round(f)) if integer else f


def _clean_row(raw) -> dict:
    if not isinstance(raw, dict):
        raise CRMError("استجابة الـ OMS: صف الأداء مش كائن")
    name = str(raw.get("ad_name") or "").strip()
    if not name:
        raise CRMError("استجابة الـ OMS: صف بلا ad_name")
    try:
        day = datetime.strptime(str(raw.get("date") or ""), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise CRMError("استجابة الـ OMS: تاريخ غير صالح (المطلوب YYYY-MM-DD)")

    orders = _num(raw, "orders", required=True, integer=True)
    delivered = _num(raw, "delivered", required=True, integer=True)
    spend = _num(raw, "spend", required=True)
    rate = _num(raw, "delivery_rate", required=False)
    cpd = _num(raw, "cost_per_delivered", required=False)
    return {
        "ad_name": name, "date": day, "spend": spend, "orders": orders,
        "delivered": delivered,
        "collected": _num(raw, "collected", required=False, integer=True) or 0,
        "delivery_rate": rate if rate is not None else (round(delivered / orders, 4) if orders else None),
        "cost_per_delivered": cpd if cpd is not None else (round(spend / delivered, 4) if delivered else None),
        "engagement": _num(raw, "engagement", required=False),
    }


def parse_rows(payload) -> list[dict]:
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise CRMError('استجابة الـ OMS: المتوقع {"rows": [...]}')
    return [_clean_row(r) for r in rows]


def _script_of(ad_name: str) -> str | None:
    """الخانة الخامسة باسم الإعلان أول، وإلا تسجيل المالك للإعلان بالحساب الإعلاني (placements.py) — ما بنخمّن أبداً."""
    sid = adname.parse(ad_name)["script_id"]
    if sid:
        return sid
    try:
        import placements
        return placements.script_for(ad_name)
    except Exception:
        return None


def relink_scripts() -> int:
    """صفوف أداء مخزّنة بلا script_id وإلها تسجيل بالحساب الإعلاني ← بنربطها هلأ. بيرجّع عدد أسماء الإعلانات اللي انربطت."""
    if not perf_db_path().exists():
        return 0
    n = 0
    with _connect() as conn:
        names = [r[0] for r in conn.execute("SELECT DISTINCT ad_name FROM ad_daily WHERE script_id IS NULL")]
        for nm in names:
            sid = _script_of(nm)
            if sid:
                conn.execute("UPDATE ad_daily SET script_id=? WHERE ad_name=? AND script_id IS NULL", (sid, nm))
                n += 1
    return n


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    now = _now()
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO ad_daily (ad_name, script_id, date, spend, orders, delivered, collected,
                                     delivery_rate, cost_per_delivered, engagement, synced_at)
               VALUES (:ad_name, :script_id, :date, :spend, :orders, :delivered, :collected,
                       :delivery_rate, :cost_per_delivered, :engagement, :synced_at)
               ON CONFLICT(ad_name, date) DO UPDATE SET
                 script_id=excluded.script_id, spend=excluded.spend, orders=excluded.orders,
                 delivered=excluded.delivered, collected=excluded.collected,
                 delivery_rate=excluded.delivery_rate, cost_per_delivered=excluded.cost_per_delivered,
                 engagement=excluded.engagement, synced_at=excluded.synced_at""",
            [{**{k: r[k] for k in ROW_KEYS},
              "script_id": _script_of(r["ad_name"]), "synced_at": now} for r in rows],
        )
    return len(rows)


def perf_rows(since: str | None = None, until: str | None = None, *,
              vp_only: bool = False, ad_name: str | None = None) -> list[dict]:
    """صفوف الأداء المخزّنة (بدون شبكة). since/until شاملة."""
    if not perf_db_path().exists():
        return []
    q, args = "SELECT * FROM ad_daily WHERE 1=1", []
    if since:
        q += " AND date >= ?"
        args.append(since)
    if until:
        q += " AND date <= ?"
        args.append(until)
    if vp_only:
        q += " AND script_id IS NOT NULL"
    if ad_name:
        q += " AND ad_name = ?"
        args.append(ad_name)
    q += " ORDER BY ad_name, date"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]


# ───────────────────────────── حالة المزامنة ─────────────────────────────


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _state_path() -> Path:
    return _lib() / "sync_state.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def sync_state() -> dict:
    st = _read_json(_state_path(), {})
    return {
        "last_success": st.get("last_success"), "last_attempt": st.get("last_attempt"),
        "last_error": st.get("last_error"), "synced_through": st.get("synced_through"),
        "rows": st.get("rows", 0),
    }


def data_as_of() -> str | None:
    """تاريخ آخر مزامنة ناجحة — الأرقام المخزّنة بتنسب إله لما ما في اتصال."""
    return sync_state()["last_success"]


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        nxt = min(cur + timedelta(days=WINDOW_DAYS - 1), end)
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


def sync_performance(*, today: date | None = None) -> dict:
    """
    يسحب من آخر مزامنة ناجحة لليوم. الحالة (`synced_through`) بتتقدّم بس لما كل النطاقات
    تنجح؛ فأي فشل نص الطريق بيعيد نفس النطاق بالمرة الجاية والـ upsert بيمنع التكرار.
    """
    today = today or date.today()
    st = sync_state()
    if st["synced_through"]:
        through = datetime.strptime(st["synced_through"], "%Y-%m-%d").date()
        start = through - timedelta(days=int(_cfg("CRM_RESYNC_LOOKBACK_DAYS", RESYNC_LOOKBACK_DAYS)))
    else:
        start = today - timedelta(days=int(_cfg("CRM_INITIAL_BACKFILL_DAYS", INITIAL_BACKFILL_DAYS)))
    start = min(start, today)
    result = {"ok": False, "rows": 0, "from": start.isoformat(), "to": today.isoformat()}

    def fail(msg: str, offline: bool) -> dict:
        _write_json(_state_path(), {**_read_json(_state_path(), {}),
                                    "last_attempt": _now(), "last_error": msg})
        return {**result, "error": msg, "offline": offline}

    try:
        client = get_client()
        total = 0
        for a, b in _windows(start, today):
            payload = client.get(PERF_PATH, params={"since": a.isoformat(), "until": b.isoformat()})
            total += upsert_rows(parse_rows(payload))
    except CRMOffline as e:
        return fail(str(e) or "الـ OMS غير متاح", True)
    except CRMError as e:
        return fail(str(e), False)

    now = _now()
    _write_json(_state_path(), {"last_success": now, "last_attempt": now, "last_error": None,
                                "synced_through": today.isoformat(), "rows": total})
    return {**result, "ok": True, "rows": total}


# ───────────────────────────── حقائق المنتج وأسباب الفشل ─────────────────────────────


def _cache_path(kind: str, product_code: str, country: str) -> Path:
    def part(s):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", str(s or "")).strip("_") or "x"
    return _lib() / "crm_cache" / f"{kind}__{part(product_code)}__{part(country)}.json"


def _read_cache(kind: str, product_code: str, country: str):
    c = _read_json(_cache_path(kind, product_code, country), None)
    if isinstance(c, dict) and "data" in c:
        return c["data"], c.get("fetched_at")
    return None, None


def _write_cache(kind: str, product_code: str, country: str, data) -> str:
    at = _now()
    _write_json(_cache_path(kind, product_code, country), {"fetched_at": at, "data": data})
    return at


def _fetch_cached(kind: str, path: str, product_code: str, country: str, normalize):
    try:
        payload = get_client().get(path, params={"product": product_code, "country": country})
    except CRMOffline as e:
        e.cached, e.cached_at = _read_cache(kind, product_code, country)
        raise
    data = normalize(payload)
    _write_cache(kind, product_code, country, data)
    return data


def _text(v) -> str:
    return str(v).strip() if v not in (None, "") else ""


def _money(v) -> str:
    if isinstance(v, dict):
        if v.get("display"):
            return _text(v["display"])
        amount, cur = v.get("amount"), _text(v.get("currency"))
        return f"{amount:g} {cur}".strip() if isinstance(amount, (int, float)) else ""
    return _text(v)


def _normalize_market(payload) -> dict:
    """بيرجّع بس اللي الـ OMS قاله فعلاً — غياب حقل ≠ «ما في»، فما بنمسح شي من البريف."""
    if not isinstance(payload, dict):
        raise CRMError("استجابة product-market لازم تكون كائن")
    out: dict = {}
    price = _money(payload.get("price"))
    if price:
        out["price"] = price
    if "offer_tiers" in payload:
        tiers = []
        for t in payload.get("offer_tiers") or []:
            if isinstance(t, dict):
                label = _text(t.get("label"))
                qty, tprice = t.get("qty"), _money(t.get("price"))
                tiers.append(label or (f"{qty} بـ {tprice}" if qty and tprice else tprice))
        tiers = [t for t in tiers if t]
        out["offer"], out["no_offer"] = "؛ ".join(tiers), not tiers
    if "guarantee" in payload:
        g = payload.get("guarantee")
        guarantee = _text(g.get("text") if isinstance(g, dict) else g)
        out["guarantee"], out["no_guarantee"] = guarantee, not guarantee
    for key in ("country", "dialect"):
        v = _text(payload.get(key))
        if v:
            out[key] = v.upper() if key == "country" else v.lower()
    d = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
    out["_extras"] = {
        "cod": bool(payload.get("cod")),
        "delivery_days_min": d.get("days_min"), "delivery_days_max": d.get("days_max"),
        "delivery_fee": d.get("fee"), "delivery_note": _text(d.get("note")),
    }
    return out


def fetch_product_facts(product_code: str, country: str) -> dict:
    """
    حقائق تجارية بمفاتيح البريف: price offer no_offer guarantee no_guarantee country dialect.
    بيرمي CRMOffline (وعليه `.cached`/`.cached_at` لو في نسخة مخزّنة) أو CRMError.
    الحقول الزيادة (دفع عند الاستلام/توصيل) بتنحفظ بالمخزن: `market_extras()`.
    """
    data = _fetch_cached("facts", FACTS_PATH, product_code, country, _normalize_market)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def cached_product_facts(product_code: str, country: str):
    data, at = _read_cache("facts", product_code, country)
    return ({k: v for k, v in data.items() if not k.startswith("_")} if data else None), at


def market_extras(product_code: str, country: str) -> dict:
    data, _ = _read_cache("facts", product_code, country)
    return dict((data or {}).get("_extras") or {})


_PII_RX = re.compile(r"\d{6,}|@|https?://", re.I)


def _normalize_failures(payload) -> list[dict]:
    items = payload.get("reasons") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise CRMError('استجابة failure-reasons: المتوقع {"reasons": [...]}')
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        reason = re.sub(r"\s+", " ", _text(it.get("reason")))[:80]
        try:
            count = int(it.get("count"))
        except (TypeError, ValueError):
            continue
        # سبب حرّ فيه رقم طويل/بريد/رابط = احتمال بيانات زبون → بيتشال
        if reason and count > 0 and not _PII_RX.search(reason):
            out.append({"reason": reason, "count": count})
    out.sort(key=lambda x: -x["count"])
    return out[:MAX_FAILURE_REASONS]


def fetch_failure_reasons(product_code: str, country: str) -> list[dict]:
    """أسباب فشل/إرجاع مجمّعة `[{reason, count}]` — بلا أي بيانات زبون."""
    return _fetch_cached("failures", FAILURES_PATH, product_code, country, _normalize_failures)


def cached_failure_reasons(product_code: str, country: str):
    return _read_cache("failures", product_code, country)


# ───────────────────────────── CLI (للمهام) ─────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd == "sync":
        r = sync_performance()
        if r["ok"]:
            print(f"[✓] تمت المزامنة: {r['rows']} صف ({r['from']} → {r['to']})")
            return 0
        print(f"[!] فشلت المزامنة: {r['error']}")
        return 1
    if cmd == "status":
        st = sync_state()
        print(f"مضبوط: {is_configured()} | آخر نجاح: {st['last_success'] or '—'} | آخر خطأ: {st['last_error'] or '—'}")
        return 0
    print("[!] الأوامر: sync | status")
    return 2


if __name__ == "__main__":
    sys.exit(main())
