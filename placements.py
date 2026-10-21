"""
تسجيل الإعلان المنشور بالحساب الإعلاني (ميتا · تيك توك · سناب · جوجل · أخرى).

بعد ما الإعلان ينطلق من الحساب الإعلاني، المالك بيسجّل هون: أي منصة، أي حساب، أي حملة، اسم الإعلان ورقمه…
مصدر التسجيل: إدخال يدوي (الأساس)، أو اختيار من حملات العمليات (OMS) لما تتوفر نقطتها.

الفايدة العملية: الربط بين إعلان شغّال وسيناريو VidPattern كان بالخانة الخامسة باسم الإعلان (adname.py) وبس.
إعلان اسمه ما فيه VP-… (أو غيّروا اسمه بالحساب) كان بيضل بره حلقة التعلّم. هلأ لو سجّلت اسمه كما هو بالحساب،
مزامنة الأداء بتربطه بسيناريوه بدون تخمين (script_for) — والتخزين محلي بملف لكل سيناريو.

قواعد:
  · ما في أسرار ولا توكنات ولا بيانات زبائن (إيميل/هاتف) بأي حقل نصي.
  · ما في اتصال بأي منصة إعلانية من هون — التسجيل نص بس. (التوكنات والمزامنة عند العمليات.)
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import config

PLATFORMS = {"meta": "ميتا (فيسبوك/إنستغرام)", "tiktok": "تيك توك", "snapchat": "سناب شات", "google": "جوجل/يوتيوب", "other": "منصة أخرى"}
STATUSES = {"published": "منشور", "paused": "موقوف", "ended": "منتهي", "draft": "مسودة"}
SOURCES = ("manual", "oms", "facebook")
MAX_ENTRIES = 60
_ID_RX = re.compile(r"[A-Za-z0-9_.:\-]{1,64}")
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RX = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-]{8,}\d)(?!\d)")
_AD_NAME_PARTS = 5


class PlacementError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file(vp_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(vp_id or ""))
    if not safe:
        raise PlacementError("ما في معرّف للسيناريو (script_id) — صدّر الفيديو أول")
    return Path(config.LIBRARY_DIR) / "placements" / f"{safe}.json"


def list_for(vp_id: str) -> list[dict]:
    try:
        p = _file(vp_id)
    except PlacementError:
        return []
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write(vp_id: str, entries: list[dict]) -> None:
    p = _file(vp_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ── التحقق ──────────────────────────────────────────────────────────────
def _text(d: dict, key: str, label: str, limit: int, *, required: bool = False, pii_check: bool = False) -> str:
    v = " ".join(str(d.get(key) or "").split())
    if required and not v:
        raise PlacementError(f"«{label}» مطلوب")
    if len(v) > limit:
        raise PlacementError(f"«{label}» أطول من {limit} حرف")
    if pii_check and (_EMAIL_RX.search(v) or _PHONE_RX.search(v)):
        raise PlacementError(f"«{label}»: ما بنخزّن إيميلات أو أرقام هواتف — شيلها")
    return v


def _ident(d: dict, key: str, label: str) -> str:
    v = str(d.get(key) or "").strip()
    if not v:
        return ""
    if not _ID_RX.fullmatch(v):
        raise PlacementError(f"«{label}»: أحرف إنجليزية وأرقام و _ . : - بس (حتى 64)")
    return v


def clean(d: dict) -> dict:
    """يتحقق من بيانات التسجيل ويرجّع نسخة منظّفة. الرسائل عربية."""
    if not isinstance(d, dict):
        raise PlacementError("بيانات التسجيل غير صالحة")
    platform = str(d.get("platform") or "").strip()
    if platform not in PLATFORMS:
        raise PlacementError("اختار المنصة: " + "، ".join(PLATFORMS.values()))
    status = str(d.get("status") or "published").strip()
    if status not in STATUSES:
        raise PlacementError("الحالة: " + "، ".join(STATUSES.values()))
    source = str(d.get("source") or "manual").strip()
    if source not in SOURCES:
        raise PlacementError("مصدر غير معروف")
    ad_name = _text(d, "ad_name", "اسم الإعلان", 200, required=True)
    if "\n" in str(d.get("ad_name") or "") or "\r" in str(d.get("ad_name") or ""):
        raise PlacementError("اسم الإعلان سطر واحد")
    url = str(d.get("ad_url") or "").strip()
    if url and (not url.lower().startswith("https://") or len(url) > 500 or re.search(r"\s", url)):
        raise PlacementError("رابط الإعلان لازم يبدأ بـ https:// وبدون مسافات")
    published = str(d.get("published_at") or "").strip()
    if published:
        try:
            date.fromisoformat(published)
        except ValueError:
            raise PlacementError("تاريخ النشر بصيغة YYYY-MM-DD")
    budget = d.get("budget_daily")
    if budget in (None, ""):
        budget = None
    else:
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            raise PlacementError("الميزانية اليومية لازم تكون رقم")
        if not 0 <= budget <= 10_000_000:
            raise PlacementError("الميزانية اليومية خارج المعقول")
    out = {
        "platform": platform, "status": status, "source": source,
        "ad_account_name": _text(d, "ad_account_name", "اسم الحساب الإعلاني", 80, pii_check=True),
        "ad_account_id": _ident(d, "ad_account_id", "رقم الحساب الإعلاني"),
        "campaign_name": _text(d, "campaign_name", "اسم الحملة", 120, pii_check=True),
        "campaign_id": _ident(d, "campaign_id", "رقم الحملة"),
        "adset_name": _text(d, "adset_name", "اسم المجموعة الإعلانية", 120, pii_check=True),
        "ad_name": ad_name, "ad_id": _ident(d, "ad_id", "رقم الإعلان"), "ad_url": url,
        "published_at": published, "budget_daily": budget,
        "currency": _text(d, "currency", "العملة", 8).upper(),
        "oms_campaign_code": _ident(d, "oms_campaign_code", "كود حملة العمليات"),
        "notes": _text(d, "notes", "الملاحظات", 500, pii_check=True),
    }
    if not (out["ad_account_name"] or out["ad_account_id"]):
        raise PlacementError("اكتب اسم الحساب الإعلاني أو رقمه")
    return out


def _same_ad(a: dict, b: dict) -> bool:
    if a["platform"] != b["platform"]:
        return False
    if a.get("ad_id") and b.get("ad_id"):                         # رقمان معروفان: القرار بالرقم (إعلانين بنفس الاسم = إعلانين)
        return a["ad_id"] == b["ad_id"]
    return _norm(a["ad_name"]) == _norm(b["ad_name"]) and (a.get("ad_account_id") or "") == (b.get("ad_account_id") or "")


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


# ── العمليات ────────────────────────────────────────────────────────────
def add(vp_id: str, data: dict) -> dict:
    new = clean(data)
    entries = list_for(vp_id)
    if len(entries) >= MAX_ENTRIES:
        raise PlacementError(f"وصلت الحد ({MAX_ENTRIES} تسجيل) لهالسيناريو")
    if any(_same_ad(new, e) for e in entries):
        raise PlacementError("هالإعلان مسجّل أصلاً بنفس المنصة — عدّله بدل ما تكرّره")
    entry = {"id": "pl_" + uuid.uuid4().hex[:10], **new, "created_at": _now(), "updated_at": _now()}
    entries.append(entry)
    _write(vp_id, entries)
    _relink()
    return entry


def update(vp_id: str, entry_id: str, data: dict) -> dict:
    entries = list_for(vp_id)
    cur = next((e for e in entries if e["id"] == entry_id), None)
    if not cur:
        raise PlacementError("التسجيل غير موجود")
    new = clean({**cur, **(data or {})})
    if any(e["id"] != entry_id and _same_ad(new, e) for e in entries):
        raise PlacementError("هالتعديل بيطابق إعلان تاني مسجّل")
    cur.update(new)
    cur["updated_at"] = _now()
    _write(vp_id, entries)
    _relink()
    return cur


def delete(vp_id: str, entry_id: str) -> None:
    entries = list_for(vp_id)
    if not any(e["id"] == entry_id for e in entries):
        raise PlacementError("التسجيل غير موجود")
    _write(vp_id, [e for e in entries if e["id"] != entry_id])


# ── اقتراح اسم الإعلان ──────────────────────────────────────────────────
def suggest_ad_name(script_path) -> dict:
    """الاسم بالصيغة المعتمدة (بلد|منتج|صفحة|video|VP-…) أو الناقص منه. بدون ما نخمّن."""
    import adname
    import brief as brief_mod
    path = Path(script_path)
    meta = (json.loads(path.read_text(encoding="utf-8")).get("_meta") or {})
    sid = meta.get("script_id")
    product_file = meta.get("product_file")
    ppath = Path(config.PRODUCTS_DIR) / Path(product_file).name if product_file else None
    b = brief_mod.load(ppath) if ppath and ppath.exists() else None
    missing = []
    if b is None:
        missing.append("ملف المنتج")
    else:
        missing += [dict((k, l) for k, l, _t, _g in brief_mod.FIELDS).get(k, k) for k in brief_mod.completeness(b)["publish_missing"]]
    if not adname.is_script_id(sid):
        missing.append("script_id")
    if missing:
        return {"ad_name": None, "missing": missing, "script_id": sid}
    return {"ad_name": adname.build(b["country"], b["product_code"], b["landing_page"], sid), "missing": [], "script_id": sid}


# ── الربط بالأداء ───────────────────────────────────────────────────────
def _all_entries() -> list[tuple[str, dict]]:
    d = Path(config.LIBRARY_DIR) / "placements"
    out = []
    if d.exists():
        for f in d.glob("*.json"):
            try:
                for e in json.loads(f.read_text(encoding="utf-8")):
                    out.append((f.stem, e))
            except (OSError, json.JSONDecodeError):
                continue
    return out


def script_for(ad_name: str) -> str | None:
    """script_id لإعلان مسجّل باسمه (للمزامنة لما اسمه ما فيه VP-…). None لو غير مسجّل أو مسجّل لسيناريوهين (غموض)."""
    n = _norm(ad_name)
    if not n:
        return None
    hits = {sid for sid, e in _all_entries() if _norm(e.get("ad_name")) == n}
    if len(hits) != 1:
        return None
    sid = next(iter(hits))
    try:
        import adname
        return sid if adname.is_script_id(sid) else None
    except Exception:
        return None


def _relink() -> None:
    """صفوف أداء مخزّنة بلا script_id وإلها تسجيل ← بنربطها هلأ (بدون انتظار المزامنة الجاية)."""
    try:
        import crm
        crm.relink_scripts()
    except Exception:
        pass


# ── حسابات وحملات العمليات (قراءة فقط، لو النقطة متوفرة) ─────────────────────
OMS_PATH = "/api/vidpattern/ad-campaigns"
_PLATFORM_FROM_OMS = {"META": "meta", "TIKTOK": "tiktok", "SNAPCHAT": "snapchat", "GOOGLE": "google"}


def _s(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def oms_options() -> dict:
    """حسابات وحملات العمليات لاختيارها بدل الكتابة. المتوقع: {accounts:[…], campaigns:[…]} بدون أي توكن.
    لو النقطة مش موجودة أو العمليات مش مربوطة ← available=False مع السبب، والإدخال اليدوي بيكفي."""
    try:
        import crm
        if not crm.is_configured():
            return {"available": False, "reason": "العمليات مش مربوطة بعد (العنوان والتوكنات من الإعدادات) — ادخل يدوياً", "accounts": [], "campaigns": []}
        data = crm.get_client().get(OMS_PATH)
    except Exception:
        return {"available": False, "reason": "العمليات ما عندها نقطة حملات للقراءة بعد — ادخل يدوياً", "accounts": [], "campaigns": []}
    if not isinstance(data, dict):
        return {"available": False, "reason": "رد العمليات غير مفهوم — ادخل يدوياً", "accounts": [], "campaigns": []}
    accounts, campaigns = [], []
    for a in (data.get("accounts") or [])[:100]:
        if isinstance(a, dict):
            accounts.append({"platform": _PLATFORM_FROM_OMS.get(str(a.get("platform", "")).upper(), "other"),
                             "account_id": _s(a.get("accountId") or a.get("account_id"), 64),
                             "account_name": _s(a.get("accountName") or a.get("account_name"), 80),
                             "currency": _s(a.get("currency"), 8).upper()})
    for c in (data.get("campaigns") or [])[:300]:
        if isinstance(c, dict):
            campaigns.append({"platform": _PLATFORM_FROM_OMS.get(str(c.get("platform", "")).upper(), "other"),
                              "campaign_id": _s(c.get("externalId") or c.get("external_id"), 64),
                              "campaign_name": _s(c.get("name"), 120), "oms_campaign_code": _s(c.get("code"), 40),
                              "status": _s(c.get("status"), 12).upper(),
                              "account_id": _s(c.get("accountId") or c.get("account_id"), 64)})
    return {"available": True, "reason": "", "accounts": accounts, "campaigns": campaigns}
