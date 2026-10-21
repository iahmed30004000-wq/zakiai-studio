"""
مكتبة الشخصيات — المحطة ٣.

مكتبة ثابتة (هدفها ٥٠: ٢٠ رجل و٣٠ امرأة) بيعبّيها المالك. الوجوه ما بتتولّد من جديد:
كل توليد بيرفق ورقة الشخصية كمرجع. سيناريو جديد = اختيار جديد؛ الاختيار السابق ما بينتقل.

    library/characters/<id>/character.json
    library/characters/<id>/sheet/<view>.<ext>     أمام · جانب · ثلاثة أرباع · جسم كامل · يدين (٥ وضعيات ثابتة، لكل وضعية برومبت جاهز
                                                   بـ refprompts.py، وبتتثبّت (lock) بعد الاعتماد فما تنبدّل بالغلط)
    library/characters/<id>/consent/...            موافقة موقّعة (للشخصية المبنية على شخص حقيقي)
    library/character_usage.json                   عدّاد الاستخدام: شخصية ← منتج ← بلد
    library/studio/<stem>/character.json           اختيار هالسيناريو

ما بنتحقق قانونياً من محتوى الموافقة — بنمنع اعتماد شخصية حقيقية بلا ملف موافقة وبس.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config
import refprompts
import taxonomy

VIEWS = {
    "front": "أمام", "side": "جانب", "three_quarter": "ثلاثة أرباع",
    "full_body": "جسم كامل", "hands": "يدين",
}
GENDERS = {"m": "رجل", "f": "امرأة"}
TARGET = {"m": 20, "f": 30}
SOURCES = ("synthetic", "real_person")
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_PROMPT_CHARS = 4000
MAX_ACTIVE_ADS = 2                  # تنبيه لو نفس الشخصية بأكتر من إعلانين شغّالين لنفس المنتج
ACTIVE_WINDOW_DAYS = 7

EDITABLE = {"name_ar", "gender", "age", "market_look", "skin", "hair", "wardrobe", "persona",
            "categories", "voice", "source"}


class CharacterError(Exception):
    """رسالة عربية جاهزة للعرض."""


def root() -> Path:
    return Path(config.LIBRARY_DIR) / "characters"


def dir_of(cid: str) -> Path:
    if not re.fullmatch(r"ch_[mf]_\d{3}", cid or ""):
        raise CharacterError("معرّف شخصية غير صالح")
    return root() / cid


def _file(cid: str) -> Path:
    return dir_of(cid) / "character.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict:
    return {
        "name_ar": "", "gender": "f", "age": 0, "market_look": {}, "skin": "", "hair": "",
        "wardrobe": {"description": "", "palette": []}, "persona": "", "categories": [],
        "voice": {"provider": "", "voice_id": "", "model": ""},
        "sheet": {v: None for v in VIEWS}, "source": "synthetic", "consent": None,
        "prompts": {}, "locked": {},
    }


# ── التحقق ──────────────────────────────────────────────────────────────
def missing_for_ready(ch: dict) -> list[str]:
    """أسباب عدم الجاهزية — بالعربي. فاضي = جاهزة."""
    out = []
    if not str(ch.get("name_ar") or "").strip():
        out.append("الاسم العربي")
    if ch.get("gender") not in GENDERS:
        out.append("الجنس")
    if not isinstance(ch.get("age"), int) or not 18 <= ch["age"] <= 80:
        out.append("العمر (18–80)")
    for k, label in (("skin", "البشرة"), ("hair", "الشعر"), ("persona", "الطابع")):
        if not str(ch.get(k) or "").strip():
            out.append(label)
    if not str((ch.get("wardrobe") or {}).get("description") or "").strip():
        out.append("وصف اللبس")
    if not ch.get("categories"):
        out.append("الفئات المناسبة")
    v = ch.get("voice") or {}
    if not (v.get("provider") and v.get("voice_id")):
        out.append("صوت ثابت (المزوّد + المعرّف)")
    for view, label in VIEWS.items():
        if not ch.get("sheet", {}).get(view):
            out.append(f"ورقة مرجعية: {label}")
    if ch.get("source") == "real_person":
        c = ch.get("consent") or {}
        if not c.get("file"):
            out.append("ملف الموافقة الموقّعة (شخص حقيقي)")
    return out


def _refresh(ch: dict) -> dict:
    if ch.get("status") == "retired":
        return ch
    ch["status"] = "ready" if not missing_for_ready(ch) else "draft"
    return ch


def _clean(patch: dict) -> dict:
    out = {}
    for k, v in patch.items():
        if k not in EDITABLE:
            continue
        if k == "gender" and v not in GENDERS:
            raise CharacterError("الجنس: m أو f")
        if k == "age":
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise CharacterError("العمر لازم يكون رقم")
        if k == "source" and v not in SOURCES:
            raise CharacterError("المصدر: synthetic أو real_person")
        if k == "categories":
            v = [c for c in (v or []) if c in taxonomy.CATEGORIES]
        if k == "wardrobe":
            v = {"description": str((v or {}).get("description") or ""),
                 "palette": [str(c) for c in ((v or {}).get("palette") or [])][:8]}
        if k == "voice":
            v = {"provider": str((v or {}).get("provider") or ""),
                 "voice_id": str((v or {}).get("voice_id") or ""),
                 "model": str((v or {}).get("model") or "")}
        if k == "market_look":
            v = {c: str(t) for c, t in (v or {}).items() if c in taxonomy.COUNTRIES}
        out[k] = v
    return out


# ── CRUD ────────────────────────────────────────────────────────────────
def _next_id(gender: str) -> str:
    nums = [int(p.name.split("_")[2]) for p in root().glob(f"ch_{gender}_*") if p.is_dir()]
    return f"ch_{gender}_{(max(nums) + 1 if nums else 1):03d}"


def create(data: dict) -> dict:
    ch = _empty()
    ch.update(_clean(data))
    if not str(ch["name_ar"]).strip():
        raise CharacterError("لازم اسم عربي للشخصية")
    if not ch["age"]:
        raise CharacterError("لازم عمر")
    cid = _next_id(ch["gender"])
    ch.update(id=cid, created_at=_now(), updated_at=_now(), status="draft")
    _refresh(ch)
    _write(ch)
    return ch


def _write(ch: dict) -> None:
    p = _file(ch["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ch, ensure_ascii=False, indent=2), encoding="utf-8")


def get(cid: str) -> dict | None:
    p = _file(cid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _need(cid: str) -> dict:
    ch = get(cid)
    if not ch:
        raise CharacterError("الشخصية غير موجودة")
    return ch


def update(cid: str, patch: dict) -> dict:
    ch = _need(cid)
    clean = _clean(patch)
    if "gender" in clean and clean["gender"] != ch["gender"]:
        raise CharacterError("الجنس ما بيتغيّر بعد الإنشاء (المعرّف مبني عليه) — أنشئ شخصية جديدة")
    ch.update(clean)
    ch["updated_at"] = _now()
    _refresh(ch)
    _write(ch)
    return ch


def retire(cid: str) -> dict:
    ch = _need(cid)
    ch["status"] = "retired"
    ch["updated_at"] = _now()
    _write(ch)
    return ch


def list_all(include_retired: bool = False) -> list[dict]:
    out = []
    for p in sorted(root().glob("ch_*/character.json")):
        try:
            ch = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if include_retired or ch.get("status") != "retired":
            out.append(ch)
    return out


def summary() -> dict:
    chars = list_all()
    ready = {"m": 0, "f": 0}
    for c in chars:
        if c.get("status") == "ready":
            ready[c["gender"]] += 1
    return {"total": len(chars), "ready": ready, "target": dict(TARGET),
            "remaining": {g: max(0, TARGET[g] - ready[g]) for g in TARGET}}


# ── الأوراق المرجعية والموافقة ──────────────────────────────────────────
def set_sheet(cid: str, view: str, filename: str, data: bytes) -> dict:
    if view not in VIEWS:
        raise CharacterError("زاوية غير معروفة")
    if (_need(cid).get("locked") or {}).get(view):
        raise CharacterError(f"وضعية «{VIEWS[view]}» مثبّتة — فكّ التثبيت أول إذا بدك تبدّل صورتها")
    ext = Path(filename or "").suffix.lower()
    if ext not in IMG_EXT:
        raise CharacterError(f"صيغة غير مدعومة: {ext or 'بدون امتداد'}")
    if len(data) < 500:
        raise CharacterError("الصورة تالفة أو فاضية")
    ch = _need(cid)
    d = dir_of(cid) / "sheet"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{view}.*"):
        old.unlink()
    (d / f"{view}{ext}").write_bytes(data)
    ch["sheet"][view] = f"sheet/{view}{ext}"                  # نسبي لمجلد الشخصية
    ch["updated_at"] = _now()
    _refresh(ch)
    _write(ch)
    return ch


def sheet_path(cid: str, view: str) -> Path | None:
    ch = get(cid)
    rel = (ch or {}).get("sheet", {}).get(view)
    if not rel:
        return None
    p = (dir_of(cid) / rel).resolve()
    return p if p.exists() and dir_of(cid).resolve() in p.parents else None


def delete_sheet(cid: str, view: str) -> dict:
    """حذف صورة وضعية: بتنتقل لسلة library/_trash/characters/<id>/ (بترجع لو بدك) مش مسح نهائي. المثبّتة ما بتنحذف.
    حذف وضعية بيرجّع الشخصية «مسودة» لأنو أوراقها الخمس شرط الجاهزية."""
    if view not in VIEWS:
        raise CharacterError("زاوية غير معروفة")
    ch = _need(cid)
    if (ch.get("locked") or {}).get(view):
        raise CharacterError(f"وضعية «{VIEWS[view]}» مثبّتة — فكّ التثبيت أول إذا بدك تحذف صورتها")
    p = sheet_path(cid, view)
    if not p:
        raise CharacterError("ما في صورة بهالوضعية")
    trash = Path(config.LIBRARY_DIR) / "_trash" / "characters" / cid
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(trash / f"{view}_{datetime.now().strftime('%Y%m%d-%H%M%S')}{p.suffix}"))
    ch["sheet"][view] = None
    ch["updated_at"] = _now()
    _refresh(ch)
    _write(ch)
    return ch


def set_consent(cid: str, filename: str, data: bytes, signed_at: str, scope: str) -> dict:
    ch = _need(cid)
    if ch.get("source") != "real_person":
        raise CharacterError("الموافقة مطلوبة للشخصية المبنية على شخص حقيقي بس")
    if not (signed_at or "").strip() or not (scope or "").strip():
        raise CharacterError("تاريخ التوقيع ونطاق الاستخدام مطلوبين")
    ext = Path(filename or "").suffix.lower()
    if ext not in IMG_EXT | {".pdf"}:
        raise CharacterError("الموافقة: pdf أو صورة")
    if len(data) < 500:
        raise CharacterError("الملف تالف أو فاضي")
    d = dir_of(cid) / "consent"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"consent{ext}").write_bytes(data)
    ch["consent"] = {"file": f"consent/consent{ext}", "signed_at": signed_at.strip(), "scope": scope.strip()}
    ch["updated_at"] = _now()
    _refresh(ch)
    _write(ch)
    return ch


# ── الاستخدام ───────────────────────────────────────────────────────────
def _usage_path() -> Path:
    return Path(config.LIBRARY_DIR) / "character_usage.json"


def _usage() -> dict:
    p = _usage_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def record_use(cid: str, product_code: str, country: str, script_id: str) -> None:
    u = _usage()
    scripts = (u.setdefault(cid, {}).setdefault(product_code or "?", {})
               .setdefault(country or "?", {"scripts": []})["scripts"])
    if script_id and script_id not in scripts:
        scripts.append(script_id)
    p = _usage_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(u, ensure_ascii=False, indent=2), encoding="utf-8")


def _scripts_of(cid: str, product_code: str, country: str | None = None) -> list[str]:
    per = _usage().get(cid, {}).get(product_code or "?", {})
    out: list[str] = []
    for c, v in per.items():
        if country in (None, c):
            out += v.get("scripts", [])
    return out


def active_ads(cid: str, product_code: str, today: date | None = None) -> int:
    """كم إعلان شغّال (إنفاق آخر ٧ أيام) لنفس الشخصية والمنتج — من الأداء المسحوب."""
    ids = set(_scripts_of(cid, product_code))
    if not ids:
        return 0
    import sqlite3
    db = Path(config.LIBRARY_DIR) / "perf.db"
    if not db.exists():
        return 0
    since = ((today or date.today()) - timedelta(days=ACTIVE_WINDOW_DAYS)).isoformat()
    try:
        con = sqlite3.connect(db)
        marks = ",".join("?" * len(ids))
        rows = con.execute(
            f"SELECT DISTINCT script_id FROM ad_daily WHERE script_id IN ({marks}) "
            "AND date >= ? AND spend > 0", (*ids, since)).fetchall()
        con.close()
    except sqlite3.Error:
        return 0
    return len(rows)


def usage_report(cid: str, product_code: str, country: str | None = None) -> dict:
    n = active_ads(cid, product_code)
    return {"scripts": _scripts_of(cid, product_code, country), "active_ads": n,
            "warning": (f"نفس الشخصية بـ {n} إعلانات شغّالة لنفس المنتج (الحد {MAX_ACTIVE_ADS})"
                        if n > MAX_ACTIVE_ADS else "")}


# ── الترشيح: ٣ حسب المنتج والسوق والجمهور ───────────────────────────────
_WOMEN = re.compile(r"نساء|سيدات|امرأة|إمرأة|بنات|أمهات|women|female", re.I)
_MEN = re.compile(r"رجال|شباب|ذكور|\bmen\b|male", re.I)


def suggest(brief: dict, country: str = "", product_code: str = "", top: int = 3) -> list[dict]:
    cat = (brief or {}).get("category") or ""
    aud = str((brief or {}).get("target_audience") or "")
    want = "f" if _WOMEN.search(aud) and not _MEN.search(aud) else "m" if _MEN.search(aud) and not _WOMEN.search(aud) else None
    out = []
    for ch in list_all():
        if ch.get("status") != "ready":
            continue
        score, why = 0, []
        chcats = ch.get("categories") or []
        if cat and cat in chcats:
            score += 40; why.append("فئة المنتج ضمن فئاتها")
        elif cat and any(taxonomy.category_distance(cat, c) == "adjacent" for c in chcats):
            score += 15; why.append("فئة مجاورة")
        if country and country in (ch.get("market_look") or {}):
            score += 20; why.append("ملامح مضبوطة لسوق " + taxonomy.COUNTRIES.get(country, country))
        if want and ch["gender"] == want:
            score += 15; why.append("تطابق جنس الجمهور")
        rep = usage_report(ch["id"], product_code, country or None)
        score -= 15 * min(rep["active_ads"], 3)
        score -= 5 * min(len(rep["scripts"]), 4)
        if rep["scripts"]:
            why.append(f"استُخدمت {len(rep['scripts'])} مرة لهالمنتج")
        out.append({"character": ch, "score": score, "reasons": why,
                    "warning": rep["warning"], "active_ads": rep["active_ads"]})
    out.sort(key=lambda r: (-r["score"], r["character"]["id"]))
    return out[:top]


# ── اختيار سيناريو ──────────────────────────────────────────────────────
def choice_path(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "studio" / stem / "character.json"


def chosen(stem: str) -> dict | None:
    p = choice_path(stem)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def library_active() -> bool:
    """في شخصية جاهزة؟ لو لأ فالمحطة ٣ بتنعتبر «راوٍ بلا شخصية»."""
    return any(c.get("status") == "ready" for c in list_all())


def choose(stem: str, script: dict, character_id: str) -> dict:
    import studio_state
    ch = _need(character_id)
    if ch.get("status") != "ready":
        raise CharacterError("الشخصية مش جاهزة: " + "، ".join(missing_for_ready(ch)))
    meta = script.get("_meta") or {}
    prev = chosen(stem)
    if prev and prev.get("character_id") != character_id:
        studio_state.set_state(stem, 3, "awaiting_choice", "تغيّر اختيار الشخصية")   # بيعلّم اللاحقة stale
    code = meta.get("product_code") or meta.get("product") or ""
    try:
        import review_script
        country = (review_script.load_brief(script) or {}).get("country") or ""
    except Exception:
        country = ""
    rec = {"character_id": character_id, "chosen_at": _now(), "product_code": code,
           "script_id": meta.get("script_id")}
    p = choice_path(stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    record_use(character_id, code, country, meta.get("script_id") or stem)
    studio_state.set_state(stem, 3, "approved", f"اختار المالك: {ch['name_ar']}")
    return rec


def voice_overrides(stem: str) -> dict:
    """صوت الشخصية المختارة (بيتغلّب عليه اختيار المالك الصريح بالواجهة)."""
    c = chosen(stem)
    ch = get(c["character_id"]) if c else None
    v = (ch or {}).get("voice") or {}
    return {k: val for k, val in (("provider", v.get("provider")), ("voice", v.get("voice_id")),
                                  ("model", v.get("model"))) if val}


# ── برومبتات الوضعيات + التثبيت ─────────────────────────────────────────
def default_prompt(ch: dict, view: str, country: str = "") -> str:
    if view not in VIEWS:
        raise CharacterError("زاوية غير معروفة")
    return refprompts.character_prompt(view, ch, country)


def slots(cid: str, country: str = "") -> dict:
    """وضعيات الورقة المرجعية: لكل وضعية ثابتة صورتها + برومبتها (الفعلي والأصلي) + التثبيت."""
    ch = _need(cid)
    out = []
    for sp in refprompts.CHARACTER_SLOTS:
        v = sp["slot"]
        default = default_prompt(ch, v, country)
        over = (ch.get("prompts") or {}).get(v)
        out.append({"slot": v, "label": VIEWS[v], "label_en": sp["en"], "pose_ar": sp["pose_ar"], "required": True,
                    "has_image": bool((ch.get("sheet") or {}).get(v)), "locked": bool((ch.get("locked") or {}).get(v)),
                    "prompt": {"text": over or default, "default": default, "edited": bool(over)}, "needs_front": v != "front",
                    "use_note": refprompts.character_use_note(v)})
    return {"slots": out, "prompt_gaps": refprompts.character_gaps(ch), "source": ch.get("source"), "name": ch.get("name_ar") or cid,
            "countries": list((ch.get("market_look") or {}))}


def set_prompt(cid: str, view: str, text: str) -> dict:
    if view not in VIEWS:
        raise CharacterError("زاوية غير معروفة")
    t = str(text or "").strip()
    if not t:
        raise CharacterError("البرومبت فاضي — اضغط «رجّع الأصلي» بدل ما تفضّيه")
    if len(t) > MAX_PROMPT_CHARS:
        raise CharacterError(f"البرومبت أطول من {MAX_PROMPT_CHARS} حرف")
    ch = _need(cid)
    ch.setdefault("prompts", {})[view] = t
    ch["updated_at"] = _now()
    _write(ch)
    return ch


def reset_prompt(cid: str, view: str) -> dict:
    if view not in VIEWS:
        raise CharacterError("زاوية غير معروفة")
    ch = _need(cid)
    (ch.get("prompts") or {}).pop(view, None)
    ch["updated_at"] = _now()
    _write(ch)
    return ch


def set_lock(cid: str, view: str, locked: bool) -> dict:
    """تثبيت وضعية معتمدة: ما بتنبدّل صورتها لحد ما تنفكّ. بدها صورة أصلاً."""
    if view not in VIEWS:
        raise CharacterError("زاوية غير معروفة")
    ch = _need(cid)
    if locked and not (ch.get("sheet") or {}).get(view):
        raise CharacterError("ما في صورة للتثبيت — ارفع صورة الوضعية أول")
    lk = ch.setdefault("locked", {})
    if locked:
        lk[view] = True
    else:
        lk.pop(view, None)
    ch["updated_at"] = _now()
    _write(ch)
    return ch


def _docx_notes(sh: dict) -> list[str]:
    """ملاحظات الشخصية لـ Word: الشخص الحقيقي والناقص من التفاصيل (بس لو موجودين)."""
    notes = []
    if sh["source"] == "real_person":
        notes.append("شخصية مبنية على شخص حقيقي: صوره هي مصدر الهوية الوحيد (الموافقة الموقّعة لازم تكون مرفقة).")
    if sh["prompt_gaps"]:
        notes.append("ناقص بالبرومبتات (كمّله بالنظام قبل التوليد): " + "، ".join(sh["prompt_gaps"]))
    return notes


def prompts_docx(cid: str, country: str = "") -> tuple[str, bytes]:
    """ملف Word بكل برومبتات الشخصية (للصقها بـ ChatGPT/Flow). بيرجّع (اسم الملف، bytes)."""
    sh = slots(cid, country)
    intro = [f"الشخصية: {sh['name']} ({cid})",
             "ترتيب الشغل: ولّد وضعية «أمام» أول وراجعها. بعدها لكل وضعية تانية: ارفق صورة «أمام» مع برومبت الوضعية (قفل الهوية)، وولّد. نفس الوجه واللبس بكل الوضعيات.",
             "ارفع كل صورة بمكانها بالنظام. الوجوه ما بتتولّد من جديد بعد الاعتماد.", *_docx_notes(sh)]
    return f"{cid}_reference_prompts.docx", refprompts.build_docx(f"برومبتات الورقة المرجعية — {sh['name']}", intro,
                                                                   refprompts.slot_docx_items(sh["slots"]))


def docx_sections(cid: str, country: str = "") -> list[dict]:
    """قسم Word لشخصية وحدة (عنوان فاصل + وضعياتها) — ref_docx بيجمّع الأقسام بملف واحد لكل المراجع."""
    sh = slots(cid, country)
    return [{"heading": True, "title": f"الشخصية: {sh['name']}", "lines": [f"المعرّف: {cid}", *_docx_notes(sh)]},
            *refprompts.slot_docx_items(sh["slots"])]
