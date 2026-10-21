#!/usr/bin/env python3
"""
مسودات السيناريوهات الجديدة (لتنبيهات الإرهاق) — بتستنى موافقتك قبل أي كتابة.

كل مسودة = بريف جاهز: المنتج + أفضل نمط **مثبت** ما استُخدم لهالمنتج + أسباب الفشل المجمّعة من
الـ OMS (بلا أي بيانات زبون؛ ولو أوفلاين بنذكر إنها من آخر نسخة مخزّنة أو غير متوفرة).
التخزين: library/drafts/<id>.json — والمعرّف ثابت من (الإعلان، بداية الفترة) فالتكرار مستحيل.

    python drafts.py approve <id> [--started]
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config
import crm
import evidence

APPROVING_STALE_MIN = 30      # مسودة عالقة بـ«approving» أطول من هيك بتنفتح للمحاولة من جديد


class DraftError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _dir() -> Path:
    return Path(config.LIBRARY_DIR) / "drafts"


def draft_id(ad_name: str, since: str) -> str:
    return "dr_" + hashlib.sha1(f"fatigue|{ad_name}|{since}".encode("utf-8")).hexdigest()[:10]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _path(did: str) -> Path:
    if not did or not did.replace("_", "").isalnum():
        raise DraftError("معرّف المسودة غير صالح")
    return _dir() / f"{did}.json"


def _read(did: str) -> dict | None:
    try:
        return json.loads(_path(did).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(d: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    p = _path(d["id"])
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def get(did: str) -> dict | None:
    return _read(did)


def get_for(ad_name: str, since: str) -> dict | None:
    return _read(draft_id(ad_name, since))


# ───────────────────────────── تجهيز البريف ─────────────────────────────


def _find_product(script_meta: dict | None, product_code: str | None) -> tuple[str | None, dict]:
    """(اسم ملف المنتج، بريف) — من السيناريو أولاً، وإلا بالكود."""
    import brief
    pdir = Path(config.PRODUCTS_DIR)
    fname = (script_meta or {}).get("product_file")
    if fname and (pdir / fname).exists():
        return fname, brief.load(pdir / fname)
    for f in sorted(pdir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            b = brief.load(f)
        except (OSError, ValueError):
            continue
        if product_code and product_code in (b.get("product_code"), f.stem):
            return f.name, b
    return None, {}


def _used_patterns(file: str | None, b: dict) -> set[str]:
    used: set[str] = set()
    for f in Path(config.SCRIPTS_DIR).glob("*.json"):
        try:
            meta = (json.loads(f.read_text(encoding="utf-8")).get("_meta") or {})
        except (OSError, ValueError):
            continue
        same = ((file and meta.get("product_file") == file)
                or (b.get("product_code") and meta.get("product_code") == b["product_code"])
                or (b.get("product_name") and meta.get("product") == b["product_name"]))
        if same and meta.get("pattern_id"):
            used.add(meta["pattern_id"])
    return used


def _best_pattern(file: str | None, b: dict, today: date | None) -> tuple[dict | None, str]:
    """أفضل نمط مثبت (بدرجة الدليل) ما استُخدم لهالمنتج ومش من فئة بعيدة."""
    import taxonomy
    used = _used_patterns(file, b)
    cands = []
    for e in evidence.pattern_evidence(today).values():
        if e["evidence_level"] != "proven" or e["pattern_id"] in used:
            continue
        if taxonomy.category_distance(b.get("category"), e.get("product_category")) == "far":
            continue
        cands.append(e)
    if not cands:
        return None, ("ما في نمط مثبت جديد لهالمنتج — رح تختار المطابقة أنسب نمط، وهو غير مثبت بأداء فعلي.")
    cands.sort(key=lambda e: (-e["evidence_score"], -e["delivered"], e["pattern_id"]))
    top = cands[0]
    return ({k: top[k] for k in ("pattern_id", "name", "evidence_level", "evidence_score", "delivered",
                                 "cost_per_delivered", "cost_vs_baseline")},
            f"أفضل نمط مثبت لم يُستخدم لهذا المنتج: {top['name']} ({top['reason']})")


def _failure_block(product_code: str, country: str) -> dict:
    try:
        items = crm.fetch_failure_reasons(product_code, country)
        return {"status": "live", "as_of": _now(), "items": items}
    except crm.CRMOffline as e:
        if e.cached is not None:
            return {"status": "offline_cached", "as_of": e.cached_at, "items": e.cached}
        return {"status": "offline_none", "as_of": None, "items": []}
    except crm.CRMError as e:
        return {"status": "error", "as_of": None, "items": [], "error": str(e)}


_FAILURE_NOTE = {
    "live": "أسباب الفشل/الإرجاع (مجمّعة من الـ OMS الآن)",
    "offline_cached": "أسباب الفشل/الإرجاع — الـ OMS غير متصل، من آخر نسخة مخزّنة",
    "offline_none": "أسباب الفشل/الإرجاع غير متوفرة: الـ OMS غير متصل ولا توجد نسخة مخزّنة",
    "error": "أسباب الفشل/الإرجاع غير متوفرة: خطأ من الـ OMS",
}


def create(alert: dict, *, today: date | None = None) -> dict:
    """يجهّز مسودة من تنبيه fatigue. idempotent: نفس (الإعلان، بداية الفترة) بيرجّع الموجودة."""
    existing = get_for(alert["ad_name"], alert["since"])
    if existing:
        return existing

    scripts = evidence.load_scripts()
    sc = scripts.get(alert.get("script_id") or "")
    code = (sc or {}).get("product_code") or alert.get("product_code")
    file, b = _find_product(sc, code)
    country = alert.get("country") or b.get("country") or ""
    product_code = b.get("product_code") or code or ""

    pattern, pattern_note = _best_pattern(file, b, today)
    failures = _failure_block(product_code, country)

    lines = [f"المنتج: {b.get('product_name') or product_code} ({country or 'بلد غير محدد'})",
             f"السبب: {alert.get('detail', '')}", pattern_note, _FAILURE_NOTE[failures["status"]] + ":"]
    lines += [f"  - {i['reason']} ({i['count']})" for i in failures["items"]] or ["  - لا شي"]

    d = {
        "id": draft_id(alert["ad_name"], alert["since"]), "kind": "fatigue", "status": "pending",
        "created_at": _now(), "ad_name": alert["ad_name"], "script_id": alert.get("script_id"),
        "since": alert["since"], "alert_detail": alert.get("detail", ""),
        "product": {"code": product_code, "name": b.get("product_name"), "file": file,
                    "country": country, "category": b.get("category")},
        "suggested_pattern": pattern, "pattern_note": pattern_note,
        "failure_reasons": failures, "brief_text": "\n".join(lines),
        "approved_at": None, "result_script": None, "error": None,
    }
    _write(d)
    return d


# ───────────────────────────── دورة الحياة ─────────────────────────────


def list_drafts(status: str | None = None) -> list[dict]:
    out = []
    for f in sorted(_dir().glob("dr_*.json")) if _dir().exists() else []:
        d = _read(f.stem)
        if d and (status is None or d["status"] == status):
            out.append(d)
    return sorted(out, key=lambda d: d["created_at"], reverse=True)


def begin_approve(did: str) -> dict:
    """pending → approving (بيمنع الموافقة المزدوجة). بيرمي DraftError بعربي."""
    d = _read(did)
    if not d:
        raise DraftError("المسودة غير موجودة")
    if d["status"] == "approving":
        started = datetime.fromisoformat(d.get("approving_at") or d["created_at"])
        if datetime.now() - started < timedelta(minutes=APPROVING_STALE_MIN):
            raise DraftError("المسودة قيد الكتابة الآن")
    elif d["status"] != "pending":
        raise DraftError("المسودة مش بانتظار الموافقة (الحالة: %s)" % d["status"])
    if not d["product"].get("file"):
        raise DraftError("ما لقينا ملف المنتج لهالمسودة — ما بنقدر نكتب سيناريو")
    d["status"], d["approving_at"], d["error"] = "approving", _now(), None
    _write(d)
    return d


def approve(did: str, *, _started: bool = False) -> dict:
    """موافقة المالك → كتابة سيناريو جديد بالنمط المقترح عبر وحدة A. بيرجّع المسودة المحدّثة."""
    d = _read(did) if _started else begin_approve(did)
    if not d or d["status"] != "approving":
        raise DraftError("المسودة مش بحالة موافقة جارية")
    try:
        import stage3_generate                              # وحدة A — استيراد متأخر
        product_path = Path(config.PRODUCTS_DIR) / d["product"]["file"]
        pattern_id = (d.get("suggested_pattern") or {}).get("pattern_id")
        result = stage3_generate.write_for_product(product_path, pattern_id)
    except BaseException as e:
        d["status"], d["error"] = "pending", str(e)[:300] or type(e).__name__
        _write(d)
        raise
    d["status"], d["approved_at"] = "approved", _now()
    d["result_script"] = Path(result).name if result else None
    d["error"] = None
    _write(d)
    return d


def dismiss(did: str) -> dict:
    d = _read(did)
    if not d:
        raise DraftError("المسودة غير موجودة")
    if d["status"] != "pending":
        raise DraftError("ما بيصير نرفض مسودة حالتها: %s" % d["status"])
    d["status"], d["dismissed_at"] = "dismissed", _now()
    _write(d)
    return d


# اسم العقد بين الوكلاء: drafts.list — منعرّفه بالآخر عشان ما يحجب list المدمجة داخل الملف
list = list_drafts  # noqa: A001


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "approve":
        try:
            d = approve(argv[1], _started="--started" in argv)
        except DraftError as e:
            print(f"[!] {e}")
            return 1
        except (Exception, SystemExit) as e:
            print(f"[!] فشلت كتابة السيناريو: {e}")
            return 1
        print(f"[✓] انكتب السيناريو: {d['result_script']}")
        return 0
    print("[!] الاستعمال: python drafts.py approve <id> [--started]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
