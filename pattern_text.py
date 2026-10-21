"""
طبقة العربي للأنماط — دوال صافية (بلا قراءة ولا كتابة ملفات).

الفكرة: الأصل الإنجليزي بالحقول العليا بيضل كما هو لأنو بصمة كشف التكرار والعناقيد (pattern_dedupe / clusters)
معايَرة عليه. العربي بيتخزّن بجنبه:

    p["ar"]                       نصوص النمط (كل مفتاح موجود بيغلب حتى لو فاضي: لما تمسح حقل ما يرجع الإنجليزي)
    p["scene_blueprint"][i]["ar"] نصوص كل مشهد (جوّا المشهد نفسه، فإضافة/حذف/ترتيب المشاهد ما بيزحزح النصوص)
    p["ar"]["_legacy"]            القيم الأصلية المعروضة بطابور المراجعة

الأنماط اليدوية/Excel: العربي هو النص الأول بالحقول العليا، وأي تعديل بعدين بيروح لـ ar (نفس القاعدة).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re

import pattern_fields as pf

TEXT_PATHS = [f["path"] for f in pf.FIELDS if f["type"] in ("text", "textarea")]
LIST_PATHS = [f["path"] for f in pf.FIELDS if f["type"] == "list"]
SCENE_KEYS = pf.SCENE_TEXT_KEYS
SCENE_NUM_KEYS = [f["key"] for f in pf.SCENE_FIELDS if f["type"] == "number"]
LEGACY_KEYS = ("dialect_or_language", "framework", "product_category")

_AR_RX = re.compile(r"[؀-ۿ]")
_LAT_RX = re.compile(r"[A-Za-z]")
_DIGITS_ONLY = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def is_arabic(s) -> bool:
    """نص عربي: الحروف العربية ≥ 50% من كل الحروف (عربي + لاتيني)."""
    s = str(s or "")
    a, lat = len(_AR_RX.findall(s)), len(_LAT_RX.findall(s))
    return a > 0 and a >= (a + lat) * 0.5


def digits_to_latin(s: str) -> str:
    return str(s).translate(_DIGITS_ONLY)


# ═════════════════ العرض ═════════════════
def localized(p: dict) -> dict:
    """نسخة النمط بالعربي: كل مفتاح موجود بـ ar بيحلّ مكان الأصل (حتى لو فاضي)، وبدون مفتاح ar نفسه."""
    v = copy.deepcopy(p)
    ar = v.pop("ar", None) or {}
    for path in TEXT_PATHS + LIST_PATHS:
        if pf.has_path(ar, path):
            pf.set_path(v, path, copy.deepcopy(pf.get_path(ar, path)))
    for sc in v.get("scene_blueprint") or []:
        if isinstance(sc, dict):
            sar = sc.pop("ar", None) or {}
            for k in SCENE_KEYS:
                if k in sar:
                    sc[k] = sar[k]
    return v


def display_name(p: dict) -> str:
    n = (p.get("ar") or {}).get("pattern_name")
    return n if isinstance(n, str) and n.strip() else str(p.get("pattern_name") or "")


def for_model(p: dict) -> dict:
    """اللي بيروح للكاتب والمراجع والمطابق: العرض العربي بدون المفاتيح الداخلية (_*) ووسوم العناقيد."""
    v = localized(p)
    return {k: val for k, val in v.items() if not k.startswith("_") and not k.startswith("cluster_")}


def editable(p: dict) -> dict:
    """اللي بيشوفه ويعدّله المحرّر: كل حقول المخطط (بالعربي) + المشاهد (كل مشهد معه _k = ترتيبه الأصلي)."""
    v = localized(p)
    out: dict = {}
    for spec in pf.FIELDS:
        val = pf.get_path(v, spec["path"])
        if val is None and spec["type"] == "list":
            val = []
        pf.set_path(out, spec["path"], val)
    scenes = []
    for i, sc in enumerate(v.get("scene_blueprint") or []):
        sc = sc if isinstance(sc, dict) else {}
        scenes.append({**{k: sc.get(k) for k in SCENE_KEYS + SCENE_NUM_KEYS}, "slot": i + 1, "_k": i})
    out["scene_blueprint"] = scenes
    return out


def rev(p: dict) -> str:
    """بصمة النسخة المعروضة بالمحرّر (تغيّر cluster_id لحاله ما بيسبّب تعارض)."""
    raw = json.dumps(editable(p), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ═════════════════ الدمج بعد التعديل ═════════════════
def merge_edit(p: dict, fields: dict) -> dict:
    """
    يطبّق حقول المحرّر (بعد pattern_fields.validate) على نسخة من النمط:
    النصوص ← ar، الأرقام والقيم المغلقة ← الحقول العليا، المشاهد بتنعاد بناءها حسب _k. أي مفتاح برّا المخطط بيضل متل ما هو.
    """
    q = copy.deepcopy(p)
    ar = q.setdefault("ar", {})
    cur = localized(p)                                               # اللي كان ظاهر للمحرّر: النص اللي ما اتغيّر ما بيتجمّد بـ ar
    for spec in pf.FIELDS:
        path, kind = spec["path"], spec["type"]
        if not pf.has_path(fields, path):
            continue
        val = pf.get_path(fields, path)
        if kind in ("text", "textarea"):
            if (val or "") != (pf.get_path(cur, path) or ""):
                pf.set_path(ar, path, val)
        elif kind == "list":
            if list(val or []) != list(pf.get_path(cur, path) or []):
                pf.set_path(ar, path, list(val or []))
        else:
            pf.set_path(q, path, val)
    if "scene_blueprint" in fields:
        old = q.get("scene_blueprint") or []
        new = []
        for i, sc in enumerate(fields["scene_blueprint"] or [], 1):
            k = sc.get("_k")
            if isinstance(k, int) and 0 <= k < len(old) and isinstance(old[k], dict):
                row = copy.deepcopy(old[k])
                shown = {**old[k], **(old[k].get("ar") or {})}
                for key in SCENE_KEYS:
                    if (sc.get(key) or "") != (shown.get(key) or ""):
                        row.setdefault("ar", {})[key] = sc.get(key) or ""
            else:                                                   # مشهد جديد: نصه العربي هو الأول
                row = {key: sc.get(key) or "" for key in SCENE_KEYS}
            for key in SCENE_NUM_KEYS:
                row[key] = sc.get(key)
            row["slot"] = i
            new.append(row)
        q["scene_blueprint"] = new
        pace = q.setdefault("pacing", {})
        pace["scene_count"] = len(new)
        total = pace.get("total_duration_sec")
        if not total:
            s = round(sum((s.get("duration_sec") or 0) for s in new), 2)
            if s > 0:
                pace["total_duration_sec"] = total = s
        if total and new:
            pace["avg_scene_sec"] = round(total / len(new), 2)
    if not ar:
        q.pop("ar", None)
    return q


# ═════════════════ الترجمة ═════════════════
def _scalar_items(p: dict):
    for path in TEXT_PATHS:
        v = pf.get_path(p, path)
        if isinstance(v, str) and v.strip():
            yield path, v


def missing_ar_keys(p: dict) -> list[str]:
    """مفاتيح النصوص الحرة اللي لسا ما إلها عربي (والأصل مش عربي أصلاً)، بشكل مسطّح:
    path | path.i (القوائم: لو بند وحد ناقص بنبعت كل بنود القائمة) | scene_blueprint.i.key | _legacy.key."""
    ar = p.get("ar") or {}
    out: list[str] = []
    for path, v in _scalar_items(p):
        if not pf.has_path(ar, path) and not is_arabic(v):
            out.append(path)
    for path in LIST_PATHS:
        items = pf.get_path(p, path)
        if pf.has_path(ar, path) or not isinstance(items, list):
            continue
        texts = [str(x) for x in items]
        if any(t.strip() and not is_arabic(t) for t in texts):
            out.extend(f"{path}.{i}" for i, t in enumerate(texts) if t.strip())
    for i, sc in enumerate(p.get("scene_blueprint") or []):
        if not isinstance(sc, dict):
            continue
        sar = sc.get("ar") or {}
        for k in SCENE_KEYS:
            v = sc.get(k)
            if isinstance(v, str) and v.strip() and k not in sar and not is_arabic(v):
                out.append(f"scene_blueprint.{i}.{k}")
    leg, lar = p.get("_legacy") or {}, ar.get("_legacy") or {}
    for k in LEGACY_KEYS:
        v = leg.get(k)
        if isinstance(v, str) and v.strip() and k not in lar and not is_arabic(v):
            out.append(f"_legacy.{k}")
    return out


def extract_texts(p: dict) -> dict[str, str]:
    """{مفتاح مسطّح: النص الأصلي} للنصوص الناقصة عربي."""
    out = {}
    for key in missing_ar_keys(p):
        parts = key.split(".")
        if parts[0] == "scene_blueprint":
            out[key] = str((p["scene_blueprint"][int(parts[1])]).get(parts[2]))
        elif parts[0] == "_legacy":
            out[key] = str((p.get("_legacy") or {}).get(parts[1]))
        elif parts[-1].isdigit() and ".".join(parts[:-1]) in LIST_PATHS:
            out[key] = str(pf.get_path(p, ".".join(parts[:-1]))[int(parts[-1])])
        else:
            out[key] = str(pf.get_path(p, key))
    return out


def apply_ar(p: dict, flat: dict) -> tuple[dict, int]:
    """يعبّي ar من ترجمة مسطّحة {مفتاح: نص عربي}. بيعبّي الناقص بس (ما بيكتب فوق عربي موجود)، وبيحوّل الأرقام لـ 0-9.
    القائمة ما بتنكتب إلا كاملة (كل بنودها). بيرجّع (النمط، عدد المفاتيح اللي انطبّقت)."""
    q = copy.deepcopy(p)
    ar = q.setdefault("ar", {})
    n = 0
    lists: dict[str, dict[int, str]] = {}
    scenes = q.get("scene_blueprint") or []
    for key, val in flat.items():
        if not isinstance(val, str) or not val.strip():
            continue
        val = digits_to_latin(val).strip()
        parts = key.split(".")
        if parts[0] == "scene_blueprint" and len(parts) == 3 and parts[1].isdigit() and parts[2] in SCENE_KEYS:
            i = int(parts[1])
            if i < len(scenes) and isinstance(scenes[i], dict) and parts[2] not in (scenes[i].get("ar") or {}):
                scenes[i].setdefault("ar", {})[parts[2]] = val
                n += 1
        elif parts[0] == "_legacy" and len(parts) == 2 and parts[1] in LEGACY_KEYS:
            lar = ar.setdefault("_legacy", {})
            if parts[1] not in lar:
                lar[parts[1]] = val
                n += 1
        elif parts[-1].isdigit() and ".".join(parts[:-1]) in LIST_PATHS:
            lists.setdefault(".".join(parts[:-1]), {})[int(parts[-1])] = val
        elif key in TEXT_PATHS and not pf.has_path(ar, key):
            pf.set_path(ar, key, val)
            n += 1
    for path, got in lists.items():
        items = pf.get_path(q, path)
        if pf.has_path(ar, path) or not isinstance(items, list):
            continue
        texts = [str(x) for x in items]
        need = [i for i, t in enumerate(texts) if t.strip()]
        if all(i in got for i in need):
            pf.set_path(ar, path, [got.get(i, texts[i]) if texts[i].strip() else texts[i] for i in range(len(texts))])
            n += len(need)
    if not ar:
        q.pop("ar", None)
    return q, n
