"""
بنك الهوكات: كل هوك انكتب (الأساسي والبدائل) + هوكاتك اليدوية، مع نتايجها لما توصل من الـ OMS.

الفهرس بيتبني كل مرة من ملفات السيناريوهات نفسها (هي مصدر الحقيقة)، وبيتخزّن بـ library/hooks_bank.json بس اللي ما بينشتق:
الهوكات اليدوية + النجمة (⭐) + الأرشفة. هيك ما في نسخة تانية من البيانات ممكن تختلف عن السيناريو.

النتايج (تكلفة الطلب المُسلَّم والحكم) من evidence.script_verdicts: الأساسي بنتيجة سيناريوه، والبديل اللي إله نسخة فيديو بنتيجة
نسخته. هوك بلا نسخة = «لسا ما اتجرّب». الهوكات اللي نجحت (⭐ أو حكم «رابح») بتروح كأمثلة للكاتب بالسيناريوهات الجاية.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import config
import hook_versions
import script_hooks as sh

MAX_TEXT, MAX_NOTE, MAX_PRODUCT = 300, 300, 80
WRITER_EXAMPLES = 6
_KEY_RX = re.compile(r"^[\w.\-]{1,120}$")


class BankError(Exception):
    """رسالة عربية جاهزة للعرض. status: 400 بيانات، 404 مش موجود."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _file() -> Path:
    return Path(config.LIBRARY_DIR) / "hooks_bank.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {"manual": list(d.get("manual") or []), "stars": dict(d.get("stars") or {}),
            "archived": dict(d.get("archived") or {}), "next": int(d.get("next") or 1)}


def _save(d: dict) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ═════════════════ الفهرس المشتق من السيناريوهات ═════════════════
def _read(f: Path) -> dict | None:
    try:
        s = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return s if isinstance(s, dict) else None


def _category(script: dict, cache: dict) -> str | None:
    import review_script
    meta = script.get("_meta") or {}
    k = meta.get("product_file") or meta.get("product") or ""
    if k not in cache:
        try:
            cache[k] = (review_script.load_brief(script) or {}).get("category")
        except Exception:                                    # noqa: BLE001 — الفئة تحسين فقط
            cache[k] = None
    return cache[k]


def _results() -> dict[str, dict]:
    """script_id → صف حكم الأداء (فاضي لو الـ OMS مش مربوط أو ما في بيانات)."""
    try:
        import evidence
        return {r["script_id"]: r for r in evidence.script_verdicts().values() if r.get("script_id")}
    except Exception:                                        # noqa: BLE001 — البنك بيشتغل بلا نتايج
        return {}


def _result(row: dict | None) -> dict | None:
    if not row or not (row.get("spend") or row.get("delivered") or row.get("orders")):
        return None
    return {"verdict": row.get("verdict"), "reason": row.get("reason"), "delivered": row.get("delivered"), "spend": row.get("spend"),
            "cost_per_delivered": row.get("cost_per_delivered"), "cost_vs_baseline": row.get("cost_vs_baseline"), "script_id": row.get("script_id")}


def derived(results: dict | None = None) -> list[dict]:
    """كل هوكات السيناريوهات (الأساسي والبدائل). نسخ الهوك (سيناريوهات) بتنعدّ كنسخ فيديو للهوك البديل مش كهوكات جديدة."""
    results = _results() if results is None else results
    scripts = []
    for f in sorted(Path(config.SCRIPTS_DIR).glob("*.json")):
        s = _read(f)
        if s is not None:
            scripts.append((f, s))
    versions: dict[tuple[str, str], dict] = {}
    for f, s in scripts:
        hi = hook_versions.info(s)
        if hi:
            versions[(str(hi.get("base")), str(hi.get("hook_id")))] = {"file": f.name, "script_id": (s.get("_meta") or {}).get("script_id")}
    out, cache = [], {}
    for f, s in scripts:
        if hook_versions.is_version(s) or (s.get("_meta") or {}).get("mode") == "free":    # المشروع الحر ما بيدخل بنك الهوكات
            continue
        meta = s.get("_meta") or {}
        sid = meta.get("script_id") or None
        base_key = sid or f"f_{f.stem}"
        main = sh.main_id(s)
        for h in sh.hooks_of(s):
            ver = versions.get((f.stem, h["id"]))
            row = results.get(ver["script_id"]) if (ver and ver.get("script_id")) else (results.get(sid) if (h["id"] == main and sid) else None)
            out.append({
                "key": f"{base_key}.{h['id']}", "source": "script", "text": h["spoken"], "on_screen_text": h.get("on_screen_text") or "",
                "visual": h.get("visual") or "", "why": h.get("why") or "", "type": h.get("type"),
                "type_label": sh.TYPES.get(h.get("type"), "غير محدد"), "product": meta.get("product"), "product_code": meta.get("product_code"),
                "category": _category(s, cache), "script_file": f.name, "script_id": sid, "hook_id": h["id"],
                "role": "main" if h["id"] == main else ("video" if ver else "alt"), "version": ver, "result": _result(row),
                "created_at": meta.get("generated_at"), "note": ""})
    return out


# ═════════════════ القائمة ═════════════════
def _manual_entries(d: dict) -> list[dict]:
    return [{"key": m["id"], "source": "manual", "text": m["text"], "on_screen_text": "", "visual": "", "why": "", "type": m.get("type"),
             "type_label": sh.TYPES.get(m.get("type"), "غير محدد"), "product": m.get("product") or None, "product_code": None, "category": None,
             "script_file": None, "script_id": None, "hook_id": None, "role": "manual", "version": None, "result": None,
             "created_at": m.get("created_at"), "note": m.get("note") or ""} for m in d["manual"]]


def entries(results: dict | None = None) -> list[dict]:
    d = _load()
    out = derived(results) + _manual_entries(d)
    for e in out:
        e["star"] = bool(d["stars"].get(e["key"]))
        e["archived"] = bool(d["archived"].get(e["key"]))
    return out


def list_entries(*, product: str | None = None, type: str | None = None, star: bool = False, q: str | None = None,
                 include_archived: bool = False, role: str | None = None) -> dict:
    allx = entries()
    live = [e for e in allx if include_archived or not e["archived"]]
    items = [e for e in live
             if (not product or (e.get("product") or "") == product)
             and (not type or e.get("type") == type)
             and (not role or e["role"] == role)
             and (not star or e["star"])
             and (not q or q.casefold() in " ".join(str(e.get(k) or "") for k in ("text", "on_screen_text", "visual", "product", "note")).casefold())]
    order = {"winner": 0, "ok": 1, "loser": 3}                    # مجرّب بلا حكم (insufficient) = 2، وغير مجرّب = 4
    items.sort(key=lambda e: str(e.get("created_at") or ""), reverse=True)                      # الأحدث أول ضمن نفس الفئة
    items.sort(key=lambda e: (not e["star"], order.get((e["result"] or {}).get("verdict"), 2 if e["result"] else 4)))
    return {"items": items,
            "counts": {"total": len(live), "starred": sum(1 for e in live if e["star"]), "tested": sum(1 for e in live if e["result"]),
                       "winners": sum(1 for e in live if (e["result"] or {}).get("verdict") == "winner"), "archived": sum(1 for e in allx if e["archived"])},
            "products": sorted({e["product"] for e in live if e.get("product")}), "types": dict(sh.TYPES)}


# ═════════════════ اليدوي والنجمة والأرشفة ═════════════════
def _clean(text, limit: int, label: str, *, required: bool = False) -> str:
    v = " ".join(str(text or "").split())
    if required and len(v) < 3:
        raise BankError(f"«{label}» لازم يكون 3 أحرف على الأقل")
    if len(v) > limit:
        raise BankError(f"«{label}» أطول من {limit} حرف")
    return v


def add_manual(text, type=None, product=None, note="", by: str = "owner") -> dict:
    d = _load()
    row = {"id": f"m_{d['next']}", "text": _clean(text, MAX_TEXT, "نص الهوك", required=True),
           "type": type if type in sh.TYPES else None, "product": _clean(product, MAX_PRODUCT, "المنتج") or None,
           "note": _clean(note, MAX_NOTE, "الملاحظة"), "created_at": _now(), "by": by}
    d["manual"].append(row)
    d["next"] += 1
    _save(d)
    return next(e for e in entries() if e["key"] == row["id"])


def _manual_index(d: dict, key: str) -> int:
    i = next((i for i, m in enumerate(d["manual"]) if m["id"] == key), None)
    if i is None:
        raise BankError("الهوك اليدوي غير موجود", 404)
    return i


def update_manual(key: str, **fields) -> dict:
    d = _load()
    m = d["manual"][_manual_index(d, key)]
    if "text" in fields:
        m["text"] = _clean(fields["text"], MAX_TEXT, "نص الهوك", required=True)
    if "type" in fields:
        m["type"] = fields["type"] if fields["type"] in sh.TYPES else None
    if "product" in fields:
        m["product"] = _clean(fields["product"], MAX_PRODUCT, "المنتج") or None
    if "note" in fields:
        m["note"] = _clean(fields["note"], MAX_NOTE, "الملاحظة")
    _save(d)
    return next(e for e in entries() if e["key"] == key)


def delete_manual(key: str) -> None:
    d = _load()
    d["manual"].pop(_manual_index(d, key))
    d["stars"].pop(key, None)
    d["archived"].pop(key, None)
    _save(d)


def _require(key: str) -> None:
    if not _KEY_RX.match(str(key or "")) or not any(e["key"] == key for e in entries({})):
        raise BankError("الهوك غير موجود بالبنك", 404)


def set_star(key: str, on: bool) -> dict:
    _require(key)
    d = _load()
    if on:
        d["stars"][key] = True
    else:
        d["stars"].pop(key, None)
    _save(d)
    return next(e for e in entries({}) if e["key"] == key)


def set_archived(key: str, on: bool) -> dict:
    _require(key)
    d = _load()
    if on:
        d["archived"][key] = True
    else:
        d["archived"].pop(key, None)
    _save(d)
    return next(e for e in entries({}) if e["key"] == key)


# ═════════════════ أمثلة الكاتب ═════════════════
def _summary(e: dict) -> str | None:
    r = e.get("result")
    if not r:
        return None
    parts = [r.get("verdict") or ""]
    if r.get("cost_vs_baseline") is not None:
        parts.append(f"cost per delivered order {round(r['cost_vs_baseline'] * 100)}% of the product baseline")
    if r.get("delivered"):
        parts.append(f"{r['delivered']} delivered orders")
    return " — ".join(p for p in parts if p) or None


def writer_examples(category: str | None = None, limit: int = WRITER_EXAMPLES) -> list[dict]:
    """هوكات نجحت (⭐ أو حكم رابح) كأمثلة للكاتب: نفس فئة المنتج أول، والأقوى (الأرخص بالنتايج) أول."""
    pool = [e for e in entries() if not e["archived"] and e["text"] and (e["star"] or (e["result"] or {}).get("verdict") == "winner")]

    def rank(e):
        r = e.get("result") or {}
        same = 0 if (category and e.get("category") == category) else 1
        win = 0 if r.get("verdict") == "winner" else 1
        return (same, win, r.get("cost_vs_baseline") if r.get("cost_vs_baseline") is not None else 9, 0 if e["star"] else 1)

    out, seen = [], set()
    for e in sorted(pool, key=rank):
        k = " ".join(e["text"].split())
        if k in seen:
            continue
        seen.add(k)
        out.append({"type": e.get("type") or "other", "text": e["text"], "product": e.get("product"), "starred_by_owner": e["star"],
                    "result": _summary(e)})
        if len(out) >= limit:
            break
    return out


def writer_block(examples: list[dict]) -> str:
    """كتلة برومبت الكاتب (فاضية لو ما في أمثلة)."""
    if not examples:
        return ""
    return ("## HOOK EXAMPLES THAT WORKED\n"
            "These opening lines earned their place: the owner starred them or they delivered orders cheaply. Learn the MECHANISM "
            "(the kind of tension, the rhythm, how it enters the problem), never the wording — the \"already used\" registry still "
            "forbids repeating any of them.\n"
            f"{json.dumps(examples, ensure_ascii=False, indent=2)}\n\n")
