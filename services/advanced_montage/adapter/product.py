"""بيانات المنتج للبطاقات: من بريف المنتج، بحقول مسموحة بس (بلا أي معرّفات عمليات أو روابط أو بيانات شخصية)."""

from __future__ import annotations

import json
from pathlib import Path

from .text import find_sensitive, latin_digits

FIELDS = ("name", "price", "currency", "offer", "guarantee", "scarcity_deadline", "stock_units")
_LABEL = {"name": "اسم المنتج", "price": "السعر", "currency": "العملة", "offer": "العرض", "guarantee": "الضمان",
          "scarcity_deadline": "تاريخ الندرة", "stock_units": "المخزون"}


def load_brief(script: dict, products_dir: Path) -> dict | None:
    """نفس قاعدة review_script.load_brief: من `_meta.product_file`، وإلا بالبحث باسم المنتج."""
    meta = script.get("_meta") or {}
    pdir = Path(products_dir)
    pf = meta.get("product_file")
    try:
        if pf:
            p = pdir / Path(str(pf)).name
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if meta.get("product") and pdir.exists():
            for f in sorted(pdir.glob("*.json")):
                if f.name.startswith("_"):
                    continue
                d = json.loads(f.read_text(encoding="utf-8"))
                if d.get("product_name") == meta["product"]:
                    return d
    except (json.JSONDecodeError, OSError):
        return None
    return None


def extract_product(brief: dict | None) -> tuple[dict, list[str]]:
    """({name, price, currency, offer, guarantee, scarcity_deadline, stock_units}, ملاحظات عربية).
    القيمة الفاضية تضل فاضية — ما بنخترع شي. وأي حقل فيه إيميل/رابط/هاتف/مفتاح بيتحذف مع ملاحظة."""
    notes: list[str] = []
    out = {k: "" for k in FIELDS}
    if not brief:
        return out, ["بريف المنتج مش موجود — ما في بيانات للبطاقات"]
    raw = {
        "name": brief.get("product_name"), "price": brief.get("price"), "currency": brief.get("currency"),
        "offer": brief.get("offer"), "guarantee": brief.get("guarantee"),
        "scarcity_deadline": brief.get("scarcity_deadline"), "stock_units": brief.get("stock_units"),
    }
    if brief.get("no_offer"):
        raw["offer"] = ""
    if brief.get("no_guarantee"):
        raw["guarantee"] = ""
    for k, v in raw.items():
        t = latin_digits(v).strip() if v is not None else ""
        if t:
            why = find_sensitive(t, check_phone=(k != "price"))
            if why:
                notes.append(f"حقل «{_LABEL[k]}» {why} — انحذف من المهمة")
                t = ""
        out[k] = t
    return out, notes
