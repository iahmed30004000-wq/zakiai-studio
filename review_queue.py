"""
طابور المراجعة — كل قيمة ما انطابقت بشكل قاطع بتنرفع هون بدل ما تنخمّن.

العنصر: {id, kind, pattern_id, raw, candidates, note, applied, status, resolved_value}
  kind: dialect | framework | category | framework_order | country
  applied=True يعني طُبّقت قيمة مؤقتة وبس بتنتظر تأكيد (مثل ترتيب إطارين مدموجين).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config

QUEUE_PATH = Path(config.LIBRARY_DIR) / "review_queue.json"

_KIND_KEY = {"dialect": "dialect_or_language", "framework": "framework",
             "category": "product_category"}


def _load() -> list[dict]:
    if QUEUE_PATH.exists():
        try:
            return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _save(items: list[dict]) -> None:
    """كتابة ذرّية (ملف مؤقت ثم استبدال): انقطاع النور بنص الكتابة ما بيخرّب الطابور."""
    import os
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_PATH.with_name(QUEUE_PATH.name + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, QUEUE_PATH)


def add(kind: str, pattern_id: str, raw, candidates=None, note: str = "",
        applied: bool = False) -> dict:
    """بيضيف عنصر مرة وحدة — نفس (kind, pattern_id) المفتوح ما بيتكرر."""
    items = _load()
    for it in items:
        if it["kind"] == kind and it["pattern_id"] == pattern_id and it["status"] == "open":
            return it
    item = {
        "id": f"rq_{len(items) + 1:04d}", "kind": kind, "pattern_id": pattern_id,
        "raw": raw, "candidates": candidates or [], "note": note, "applied": applied,
        "status": "open", "resolved_value": None,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    items.append(item)
    _save(items)
    return item


def list_items(status: str | None = "open") -> list[dict]:
    items = _load()
    return [i for i in items if status is None or i["status"] == status]


def resolve(item_id: str, value: str, secondary: str | None = None) -> dict:
    """بيثبّت قرار المراجع على ملف النمط نفسه."""
    import taxonomy
    items = _load()
    it = next((i for i in items if i["id"] == item_id), None)
    if not it:
        raise KeyError("عنصر غير موجود")

    valid = {"dialect": taxonomy.DIALECTS, "framework": taxonomy.FRAMEWORKS,
             "framework_order": taxonomy.FRAMEWORKS, "category": taxonomy.CATEGORIES,
             "country": taxonomy.COUNTRIES}[it["kind"]]
    if value not in valid:
        raise ValueError(f"القيمة '{value}' مش من القائمة المغلقة")
    if secondary and secondary not in taxonomy.FRAMEWORKS:
        raise ValueError(f"الإطار الثانوي '{secondary}' مش من القائمة")

    if it["kind"] == "country":          # عنصر منتج مش نمط: pattern_id = "product:<stem>"
        import brief
        stem = str(it["pattern_id"]).split(":", 1)[-1]
        prod = Path(config.PRODUCTS_DIR) / f"{stem}.json"
        if prod.exists():
            data = json.loads(prod.read_text(encoding="utf-8"))
            brief.set_field(data, "country", value, source="manual", reason="حسم طابور المراجعة")
            prod.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        it["status"], it["resolved_value"] = "resolved", value
        it["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(items)
        return it

    import pattern_store
    pf = Path(config.PATTERNS_DIR) / f"{it['pattern_id']}.pattern.json"
    if pf.exists():
        with pattern_store.locked():
            p = json.loads(pf.read_text(encoding="utf-8"))
            locked_key = {"dialect": "dialect_or_language", "framework": "framework", "framework_order": "framework", "category": "product_category"}[it["kind"]]
            if it["kind"] == "dialect":
                p["dialect_or_language"] = value
            elif it["kind"] in ("framework", "framework_order"):
                p["framework"] = value
                p["framework_secondary"] = secondary if secondary != value else None
            elif it["kind"] == "category":
                p["product_category"] = value
            # هل بقي شي مفتوح على هالنمط؟
            rest = [i for i in items if i["pattern_id"] == it["pattern_id"]
                    and i["status"] == "open" and i["id"] != item_id and not i["applied"]]
            tax = p.setdefault("_taxonomy", {})
            tax["complete"] = not rest
            tax["locked"] = sorted(set(tax.get("locked") or []) | {locked_key})        # قرار بشري: ما بيرجع ينحسب من _legacy
            pattern_store.write_atomic(pf, p)

    it["status"], it["resolved_value"] = "resolved", value
    it["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(items)
    return it


def restore(snapshot: list[dict]) -> None:
    """للتراجع — بيرجّع الطابور كما كان."""
    _save(snapshot)


def open_count(pattern_id: str, applied: bool | None = None) -> int:
    """كم بند مفتوح على هالنمط (applied: بس المطبَّقة مؤقتاً/بس غير المطبَّقة، أو None للكل)."""
    return sum(1 for i in _load() if i["pattern_id"] == pattern_id and i["status"] == "open"
               and (applied is None or bool(i.get("applied")) == applied))


def close_for_pattern(pattern_id: str, values: dict, by: str = "owner") -> int:
    """المالك عدّل القيمة من المحرّر ← بنسكّر بنودها المفتوحة. values: {kind: القيمة الجديدة}."""
    items = _load()
    n = 0
    for it in items:
        if it["pattern_id"] == pattern_id and it["status"] == "open" and it["kind"] in values:
            it["status"], it["resolved_value"] = "resolved", values[it["kind"]]
            it["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            it["resolved_by"] = by
            n += 1
    if n:
        _save(items)
    return n


def dismiss_for_pattern(pattern_id: str, note: str = "") -> int:
    """نمط انأرشف ← بنود مراجعته المفتوحة ما إلها معنى."""
    items = _load()
    n = 0
    for it in items:
        if it["pattern_id"] == pattern_id and it["status"] == "open":
            it["status"], it["note"] = "dismissed", note or it.get("note", "")
            it["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            n += 1
    if n:
        _save(items)
    return n
