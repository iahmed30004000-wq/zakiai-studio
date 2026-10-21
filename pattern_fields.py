"""
وصف كل حقل بالنمط — مصدر واحد للمحرّر والتحقق واستيراد Excel. دوال صافية (بلا قراءة ولا كتابة ملفات).

الشكل اللي بيتعامل معه المحرّر هو نفس شكل ملف النمط (متداخل): {"pattern_name": …, "hook": {"type": …}, "scene_blueprint": […]}.
القيم المغلقة (الإطار، الفئة، اللهجة…) بتنحفظ دايماً slug (إنجليزي)، والعرض بالعربي من taxonomy.
"""

from __future__ import annotations

import re

import taxonomy

COMPLEXITY = {"low": "بسيطة", "medium": "متوسطة", "high": "عالية"}
_COMPLEXITY_AR_IN = {"بسيط": "low", "بسيطة": "low", "متوسط": "medium", "متوسطة": "medium", "عالي": "high", "عالية": "high"}   # قيم المستورِد القديم

GROUPS = [
    {"key": "basic", "label": "الأساسيات"},
    {"key": "hook", "label": "الهوك (أول ثواني)"},
    {"key": "entry", "label": "دخول المنتج والإثبات"},
    {"key": "cta", "label": "الدعوة للشراء (CTA)"},
    {"key": "pacing", "label": "الإيقاع"},
    {"key": "visual", "label": "اللغة البصرية"},
    {"key": "arc", "label": "المشاعر والمشاهد"},
    {"key": "why", "label": "ليش بيشتغل وحدوده"},
]

# type: text | textarea | list | number | select | int
FIELDS = [
    {"path": "pattern_name", "label": "اسم النمط", "type": "text", "group": "basic", "required": True, "max": 160,
     "hint": "اسم قصير بيعبّر عن فكرة النمط."},
    {"path": "one_line_summary", "label": "ملخص بسطر", "type": "textarea", "group": "basic", "max": 600,
     "hint": "شو بيعمل النمط وليش بيقنع، بجملة أو جملتين."},
    {"path": "framework", "label": "الإطار", "type": "select", "group": "basic", "required": True, "options": "frameworks",
     "hint": "هيكل الإقناع الأساسي."},
    {"path": "framework_secondary", "label": "إطار ثانوي (اختياري)", "type": "select", "group": "basic", "options": "frameworks"},
    {"path": "product_category", "label": "فئة المنتج", "type": "select", "group": "basic", "required": True, "options": "categories"},
    {"path": "dialect_or_language", "label": "اللهجة", "type": "select", "group": "basic", "options": "dialects"},
    {"path": "dialect_sub", "label": "لهجة فرعية (اختياري)", "type": "select", "group": "basic", "options": "dialect_subs"},
    {"path": "target_audience", "label": "الجمهور المستهدف", "type": "textarea", "group": "basic", "max": 600},
    {"path": "reusability_score", "label": "قابلية الاستخدام (0–10)", "type": "int", "group": "basic", "min": 0, "max": 10,
     "hint": "قديش بيصلح النمط لمنتجات تانية. 7 وفوق = قوي."},
    {"path": "production_complexity", "label": "تعقيد الإنتاج", "type": "select", "group": "basic", "options": "complexity"},

    {"path": "hook.type", "label": "نوع الهوك", "type": "text", "group": "hook", "required": True, "max": 200,
     "hint": "مثال: سؤال صادم، ادعاء معاكس، رقم، موقف من الحياة."},
    {"path": "hook.duration_sec", "label": "مدة الهوك (ثانية)", "type": "number", "group": "hook", "min": 0, "max": 60},
    {"path": "hook.mechanism", "label": "كيف بيشتغل الهوك", "type": "textarea", "group": "hook", "max": 1200},
    {"path": "hook.transferable_template", "label": "قالب قابل للنقل", "type": "textarea", "group": "hook", "max": 800,
     "hint": "الهوك كقالب بفراغات بين [ ] بتتعبّى لكل منتج."},

    {"path": "product_entry_sec", "label": "ثانية دخول المنتج", "type": "number", "group": "entry", "min": 0, "max": 300},
    {"path": "product_entry_style", "label": "كيف بيدخل المنتج", "type": "textarea", "group": "entry", "max": 800},
    {"path": "proof_mechanism", "label": "آلية الإثبات", "type": "text", "group": "entry", "max": 300},
    {"path": "objection_handled", "label": "الاعتراضات اللي بيعالجها", "type": "list", "group": "entry"},

    {"path": "cta.type", "label": "نوع الـ CTA", "type": "text", "group": "cta", "max": 300},
    {"path": "cta.placement_sec", "label": "ثانية ظهور الـ CTA", "type": "number", "group": "cta", "min": 0, "max": 300},
    {"path": "cta.wording_style", "label": "صياغة الـ CTA", "type": "textarea", "group": "cta", "max": 800},

    {"path": "pacing.total_duration_sec", "label": "المدة الكلية (ثانية)", "type": "number", "group": "pacing", "min": 0, "max": 600},
    {"path": "pacing.cut_rhythm", "label": "إيقاع القطع", "type": "textarea", "group": "pacing", "max": 600},
    {"path": "pacing.words_per_second", "label": "كلمات بالثانية", "type": "number", "group": "pacing", "min": 0, "max": 10},

    {"path": "visual_language.shot_types", "label": "أنواع اللقطات", "type": "list", "group": "visual"},
    {"path": "visual_language.setting", "label": "المكان والأجواء", "type": "text", "group": "visual", "max": 400},
    {"path": "visual_language.production_style", "label": "أسلوب الإنتاج", "type": "text", "group": "visual", "max": 400},
    {"path": "visual_language.text_overlay_style", "label": "أسلوب النص عالشاشة", "type": "text", "group": "visual", "max": 400},
    {"path": "visual_language.talent", "label": "الأشخاص بالفيديو", "type": "text", "group": "visual", "max": 400},

    {"path": "emotional_arc", "label": "مسار المشاعر", "type": "list", "group": "arc", "hint": "كلمة لكل مرحلة، بالترتيب."},

    {"path": "why_it_works", "label": "ليش بيشتغل", "type": "list", "group": "why"},
    {"path": "weak_points", "label": "نقاط الضعف", "type": "list", "group": "why"},
    {"path": "best_for", "label": "بيناسب", "type": "list", "group": "why"},
    {"path": "avoid_for", "label": "ما بيناسب", "type": "list", "group": "why"},
]
FIELD_BY_PATH = {f["path"]: f for f in FIELDS}

SCENE_FIELDS = [
    {"key": "function", "label": "وظيفة المشهد", "type": "text", "required": True, "max": 400},
    {"key": "duration_sec", "label": "المدة (ثانية)", "type": "number", "min": 0, "max": 300},
    {"key": "shot_type", "label": "نوع اللقطة", "type": "text", "max": 300},
    {"key": "vo_intent", "label": "الهدف من الصوت", "type": "text", "max": 500},
    {"key": "on_screen_text_role", "label": "دور النص عالشاشة", "type": "text", "max": 400},
    {"key": "emotion", "label": "الإحساس", "type": "text", "max": 120},
]
SCENE_TEXT_KEYS = [f["key"] for f in SCENE_FIELDS if f["type"] == "text"]
MAX_SCENES = 30
MIN_SCENES_NEW = 3
MAX_LIST_ITEMS = 30
MAX_LIST_ITEM_CHARS = 500
MAX_TEXTAREA = 2000

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫،", "01234567890123456789.,")


def latin_digits(s) -> str:
    return str(s).translate(_DIGITS)


def options() -> dict:
    return {
        "frameworks": dict(taxonomy.FRAMEWORKS),
        "categories": dict(taxonomy.CATEGORY_LABELS),
        "dialects": dict(taxonomy.DIALECTS),
        "dialect_subs": {k: v[0] for k, v in taxonomy.DIALECT_SUBS.items()},
        "complexity": dict(COMPLEXITY),
    }


def schema() -> dict:
    return {"groups": GROUPS, "fields": FIELDS, "scene_fields": SCENE_FIELDS, "options": options(),
            "dialect_sub_parent": {k: v[1] for k, v in taxonomy.DIALECT_SUBS.items()},
            "limits": {"max_scenes": MAX_SCENES, "min_scenes_new": MIN_SCENES_NEW, "max_list_items": MAX_LIST_ITEMS},
            "category_groups": {k: v[1] for k, v in taxonomy.CATEGORIES.items()}}


# ═════════════════ مساعدات الوصول للمسارات المتداخلة ═════════════════
def get_path(d: dict, path: str, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def has_path(d: dict, path: str) -> bool:
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return False
        cur = cur[k]
    return True


def set_path(d: dict, path: str, value) -> None:
    cur = d
    keys = path.split(".")
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


# ═════════════════ تنظيف القيم ═════════════════
def _text(raw, spec) -> tuple[str, str | None]:
    s = "" if raw is None else str(raw).strip()
    cap = spec.get("max") or MAX_TEXTAREA
    if len(s) > cap:
        return s[:cap], f"أطول من {cap} حرف"
    return s, None


def _list(raw) -> tuple[list[str], str | None]:
    if raw is None:
        return [], None
    items = raw if isinstance(raw, list) else str(raw).splitlines()
    out = []
    for it in items:
        s = str(it).strip()
        if s:
            out.append(s)
    if len(out) > MAX_LIST_ITEMS:
        return out[:MAX_LIST_ITEMS], f"أكتر من {MAX_LIST_ITEMS} بند"
    if any(len(x) > MAX_LIST_ITEM_CHARS for x in out):
        return out, f"بند أطول من {MAX_LIST_ITEM_CHARS} حرف"
    return out, None


def _number(raw, spec) -> tuple[float | None, str | None]:
    if raw is None or str(raw).strip() == "":
        return None, None
    s = latin_digits(raw).strip().replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None, "لازم رقم"
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and v < lo:
        return None, f"الرقم أقل من {lo}"
    if hi is not None and v > hi:
        return None, f"الرقم أكبر من {hi}"
    return round(v, 3), None


def _opt_set(name: str) -> set[str]:
    return set(options()[name])


def normalize_complexity(raw) -> str | None:
    """بيقبل slug أو الاسم العربي (بما فيها قيم المستورِد القديم: بسيط/متوسط/عالي)."""
    s = str(raw or "").strip()
    if s in COMPLEXITY:
        return s
    return _COMPLEXITY_AR_IN.get(s) or next((k for k, v in COMPLEXITY.items() if v == s), None)


def validate(fields: dict, mode: str = "create", existing: dict | None = None) -> tuple[dict, list[dict]]:
    """
    fields: القيم المرسَلة (متداخلة). mode: create | edit. existing: النمط الحالي (للتعديل).
    بيرجّع (clean, errors): clean فيها بس الحقول المرسَلة بعد التنظيف؛ errors = [{field, msg}] بالعربي.
    """
    clean: dict = {}
    errors: list[dict] = []

    def err(field, msg):
        errors.append({"field": field, "msg": msg})

    for spec in FIELDS:
        path, kind = spec["path"], spec["type"]
        if not has_path(fields, path):
            if mode == "create" and spec.get("required"):
                err(path, f"«{spec['label']}» مطلوب")
            continue
        raw = get_path(fields, path)
        if kind in ("text", "textarea"):
            val, e = _text(raw, spec)
            if e:
                err(path, e)
            elif spec.get("required") and not val:
                err(path, f"«{spec['label']}» مطلوب")
                continue
        elif kind == "list":
            val, e = _list(raw)
            if e:
                err(path, e)
        elif kind in ("number", "int"):
            val, e = _number(raw, spec)
            if e:
                err(path, e)
                continue
            if val is not None and kind == "int":
                if abs(val - round(val)) > 1e-9:
                    err(path, "لازم رقم صحيح")
                    continue
                val = int(round(val))
        else:                                                   # select
            s = str(raw or "").strip()
            if path == "production_complexity" and s:
                v = normalize_complexity(s)
                if v is None:
                    err(path, "قيمة غير معروفة")
                    continue
                val = v
            elif not s:
                val = None
                if spec.get("required"):
                    err(path, f"«{spec['label']}» مطلوب")
                    continue
            else:
                if s not in _opt_set(spec["options"]):
                    err(path, "القيمة مش من القائمة")
                    continue
                val = s
        set_path(clean, path, val)

    # اتساق القيم المغلقة
    fw, fw2 = get_path(clean, "framework"), get_path(clean, "framework_secondary")
    if fw2 and (fw2 == fw or (fw is None and existing and fw2 == existing.get("framework"))):
        err("framework_secondary", "الإطار الثانوي لازم يختلف عن الأساسي")
    sub, dia = get_path(clean, "dialect_sub"), get_path(clean, "dialect_or_language")
    if sub:
        dia = dia if has_path(clean, "dialect_or_language") else (existing or {}).get("dialect_or_language")
        if taxonomy.DIALECT_SUBS[sub][1] != dia:
            err("dialect_sub", "اللهجة الفرعية مش تابعة للهجة المختارة")
    # ما بيصير تفضّي إطار أو فئة كانوا معبّيين
    if mode == "edit" and existing:
        for key in ("framework", "product_category", "pattern_name"):
            if has_path(clean, key) and not get_path(clean, key) and existing.get(key):
                err(key, "ما بيصير تفضّي هالحقل")

    # المشاهد
    if "scene_blueprint" in fields:
        scenes, serrs = _validate_scenes(fields.get("scene_blueprint"), mode)
        errors.extend(serrs)
        if not serrs:
            clean["scene_blueprint"] = scenes
    elif mode == "create":
        err("scene_blueprint", f"لازم {MIN_SCENES_NEW} مشاهد على الأقل")
    return clean, errors


def _validate_scenes(raw, mode) -> tuple[list[dict], list[dict]]:
    errs: list[dict] = []
    if not isinstance(raw, list):
        return [], [{"field": "scene_blueprint", "msg": "المشاهد لازم تكون قائمة"}]
    if len(raw) > MAX_SCENES:
        errs.append({"field": "scene_blueprint", "msg": f"أكتر من {MAX_SCENES} مشهد"})
    if mode == "create" and len(raw) < MIN_SCENES_NEW:
        errs.append({"field": "scene_blueprint", "msg": f"لازم {MIN_SCENES_NEW} مشاهد على الأقل"})
    elif mode == "edit" and not raw:                           # نمط بلا مشاهد بيكسر الكاتب
        errs.append({"field": "scene_blueprint", "msg": "لازم يضل مشهد واحد على الأقل"})
    out = []
    for i, sc in enumerate(raw[:MAX_SCENES], 1):
        if not isinstance(sc, dict):
            errs.append({"field": f"scene_blueprint.{i}", "msg": "مشهد غير صالح"})
            continue
        row: dict = {}
        for spec in SCENE_FIELDS:
            k = spec["key"]
            v = sc.get(k)
            if spec["type"] == "number":
                val, e = _number(v, spec)
                if e:
                    errs.append({"field": f"scene_blueprint.{i}.{k}", "msg": e})
                    continue
                row[k] = val
            else:
                val, e = _text(v, spec)
                if e:
                    errs.append({"field": f"scene_blueprint.{i}.{k}", "msg": e})
                row[k] = val
                if spec.get("required") and not val:
                    errs.append({"field": f"scene_blueprint.{i}.{k}", "msg": f"مشهد {i}: «{spec['label']}» مطلوب"})
        row["slot"] = i
        k_orig = sc.get("_k")
        row["_k"] = int(k_orig) if isinstance(k_orig, (int, float, str)) and str(k_orig).lstrip("-").isdigit() else None
        out.append(row)
    return out, errs


def clean_slug_for_id(text: str, limit: int = 40) -> str:
    """مقطع آمن لاسم ملف النمط: حروف عربية/لاتينية وأرقام وشرطة."""
    s = re.sub(r"[^\w؀-ۿ-]+", "_", str(text or "").strip(), flags=re.UNICODE).strip("_-")
    return s[:limit] or "pattern"
