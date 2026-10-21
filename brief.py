"""
مخطط بريف المنتج + بوابة الاكتمال.

القاعدة: الكاتب ما بيشتغل على بريف ناقص. الحقول التجارية (سعر، عرض، ضمان،
بلد، لهجة) مصدرها الـ OMS (نظام الطلبات) لما يكون متصل، وكل حقل مسحوب
بيتعلّم بمصدره بـ `_provenance` وما بيتعدّل يدوياً إلا بسبب مكتوب.

الحقول اللي إلها «لا يوجد» الصريح: العرض والضمان. فراغ الحقل = ناقص؛
تأكيد «ما في عرض» (`no_offer`) = مكتمل، والكاتب وقتها ما بيذكر عرض ولا ندرة.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import claims
import taxonomy

# (المفتاح، التسمية، النوع، المجموعة)
FIELDS = [
    ("product_name", "اسم المنتج", "text", "identity"),
    ("product_code", "كود المنتج (لاتيني — بيدخل باسم الإعلان)", "text", "identity"),
    ("category", "الفئة", "category", "identity"),
    ("country", "البلد", "country", "market"),
    ("dialect", "اللهجة", "dialect", "market"),
    ("landing_page", "اسم الصفحة (بيدخل باسم الإعلان)", "text", "market"),
    ("ops_product_id", "معرّف المنتج بالعمليات (للإطلاق)", "text", "market"),
    ("ops_store_id", "معرّف المتجر بالعمليات (للإطلاق)", "text", "market"),
    ("price", "السعر", "text", "commercial"),
    ("price_positioning", "موقع السعر", "text", "commercial"),
    ("offer", "العرض", "text", "commercial"),
    ("no_offer", "لا يوجد عرض", "bool", "commercial"),
    ("guarantee", "الضمان", "text", "commercial"),
    ("no_guarantee", "لا يوجد ضمان", "bool", "commercial"),
    ("scarcity_deadline", "تاريخ انتهاء العرض (للندرة)", "date", "commercial"),
    ("stock_units", "المخزون الفعلي (للندرة)", "number", "commercial"),
    ("core_promise", "الوعد الأساسي", "textarea", "content"),
    ("what_it_does", "شو بيعمل المنتج (آلية العمل)", "textarea", "content"),
    ("features", "مميزات المنتج", "list", "content"),
    ("target_audience", "الجمهور المستهدف", "textarea", "content"),
    ("pain_points", "نقاط الألم", "list", "content"),
    ("objections", "الاعتراضات المتوقعة", "list", "content"),
    ("proof_assets", "أصول الإثبات المتوفرة", "list", "content"),
    ("differentiator", "الميزة الفارقة", "textarea", "content"),
    ("production_constraints", "قيود الإنتاج", "textarea", "content"),
    ("forbidden_claims", "ادعاءات ممنوعة إضافية (فوق مكتبة الفئة)", "list", "safety"),
    ("market_claims_evidence", "سند ادعاءات عن منتجات السوق (إن وُجد)", "list", "safety"),
    ("brand_tone", "نبرة العلامة", "text", "content"),
    ("product_visual", "شكل المنتج (قفل بصري)", "textarea", "content"),
]
FIELD_KEYS = [f[0] for f in FIELDS]

# مطلوب قبل الكتابة. العرض والضمان: أي قيمة أو تأكيد «لا يوجد».
REQUIRED = ["category", "dialect", "core_promise", "what_it_does", "features", "pain_points",
            "objections", "proof_assets", "offer", "guarantee", "production_constraints",
            "forbidden_claims"]
# مطلوب لنسخ اسم الإعلان بس (مش للكتابة)
PUBLISH_REQUIRED = ["product_code", "country", "landing_page"]

LIST_FIELDS = {k for k, _l, t, _g in FIELDS if t == "list"}
BOOL_FIELDS = {k for k, _l, t, _g in FIELDS if t == "bool"}


class BriefIncomplete(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        labels = {k: l for k, l, _t, _g in FIELDS}
        super().__init__("البريف ناقص: " + "، ".join(labels.get(m, m) for m in missing))


def empty_brief() -> dict:
    """مخطط فاضي — ما فيه ولا قيمة من أي منتج."""
    out: dict = {}
    for k, _l, t, _g in FIELDS:
        out[k] = [] if t == "list" else (False if t == "bool" else "")
    out["previously_used_patterns"] = []
    out["_provenance"] = {}
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _filled(b: dict, key: str) -> bool:
    v = b.get(key)
    if key == "offer":
        return bool(str(v or "").strip()) or bool(b.get("no_offer"))
    if key == "guarantee":
        return bool(str(v or "").strip()) or bool(b.get("no_guarantee"))
    if key == "forbidden_claims":
        return bool(claims.effective_forbidden(b))       # المكتبة + إضافات التاجر
    if isinstance(v, list):
        return any(str(x).strip() for x in v)
    return bool(str(v or "").strip())


def completeness(b: dict) -> dict:
    missing = [k for k in REQUIRED if not _filled(b, k)]
    pub_missing = [k for k in PUBLISH_REQUIRED if not _filled(b, k)]
    done = len(REQUIRED) - len(missing)
    return {
        "score": round(100 * done / len(REQUIRED)),
        "filled": done, "total": len(REQUIRED),
        "missing": missing, "publish_missing": pub_missing,
        "ready": not missing, "publish_ready": not pub_missing,
    }


def require_complete(b: dict) -> None:
    """بوابة الكاتب: بريف ناقص = ما بيشتغل."""
    c = completeness(b)
    if not c["ready"]:
        raise BriefIncomplete(c["missing"])


def slug_code(text: str) -> str:
    """كود لاتيني آمن لاسم الإعلان: حروف وأرقام بس."""
    return re.sub(r"[^A-Za-z0-9]", "", str(text or ""))[:24]


def normalize(b: dict, file_stem: str = "") -> tuple[dict, list[dict]]:
    """
    ترحيل بريف قديم للمخطط الحالي (نسخة ثانية — الأصل بيضل بـ `_legacy`).
    الفئة/اللهجة/البلد بتتحوّل لقيم مغلقة، والفاشل بيرجع كـissue.
    """
    issues: list[dict] = []
    out = empty_brief()
    for k in FIELD_KEYS:
        if k in b:
            out[k] = b[k]
    out["previously_used_patterns"] = b.get("previously_used_patterns", [])
    out["_provenance"] = dict(b.get("_provenance") or {})
    legacy = dict(b.get("_legacy") or {})

    for kind, key, fn in (("category", "category", taxonomy.normalize_category),
                          ("dialect", "dialect", taxonomy.normalize_dialect)):
        raw = legacy.get(key, b.get(key))
        legacy.setdefault(key, raw)
        n = fn(raw)
        out[key] = n.value or ""
        if n.status != "ok" and raw:
            issues.append({"kind": kind, "raw": raw, "candidates": n.candidates, "note": n.note})

    raw_c = legacy.get("market", b.get("market") or b.get("country"))
    if raw_c:
        legacy.setdefault("market", raw_c)
        n = taxonomy.normalize_country(raw_c)
        out["country"] = n.value or ""
        if n.status != "ok":
            issues.append({"kind": "country", "raw": raw_c, "candidates": n.candidates, "note": n.note})

    if not out.get("product_code"):
        out["product_code"] = slug_code(file_stem or out.get("product_name"))
    for k in LIST_FIELDS:
        if not isinstance(out[k], list):
            out[k] = [out[k]] if out[k] else []
    out["_legacy"] = legacy
    return out, issues


def set_field(b: dict, key: str, value, source: str = "manual", reason: str = "") -> dict:
    """
    تعديل حقل مع تسجيل مصدره. حقل مسحوب من الـ OMS ما بيتعدّل يدوياً بلا سبب.
    """
    prov = b.setdefault("_provenance", {})
    cur = prov.get(key)
    if cur and cur.get("source") == "crm" and source == "manual" and not reason.strip():
        raise ValueError(f"الحقل «{key}» مسحوب من الـ OMS — التعديل اليدوي بدو سبب مكتوب")
    b[key] = value
    prov[key] = {"source": source, "at": _now(), **({"reason": reason} if reason else {})}
    return b


def load(path) -> dict:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    b, _ = normalize(raw, p.stem)
    b["_file"] = p.name
    return b
