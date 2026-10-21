"""
ملف المنتج المرجعي — لتثبيت هوية المنتج باللقطات. لكل منتج ملفه المستقل (بكوده).

    library/product_refs/<code>/ref.json
    library/product_refs/<code>/angles/<angle>.png     مفرَّغة (خلفية شفافة): ٦ زوايا إلزامية + وضعيتين اختياريتين (بيد، الملصق)
    الأبعاد الحقيقية بالسنتيمتر · نص الملصق الحرفي · الألوان · وصف الشكل

كل وضعية إلها برومبت جاهز (refprompts.py) بنفس الإطار والنِّسب والإضاءة، وبتنرفع صورتها جنب برومبتها. البرومبت ممكن
يتعدّل (بنحفظ التعديل) ويرجع للأصلي. الوضعية بتتثبّت (lock) بعد ما تتعتمد صورتها فما تنبدّل بالغلط. بنفحص نسبة الصورة
المفرَّغة مقابل أبعاد المنتج الحقيقية ونحذّر لو مش متطابقة.

لقطات المنتج القريبة بتركّب فيها صورة المنتج الحقيقية (زاوية «أمام») بالحجم المحسوب — هوية ١٠٠٪.
باقي اللقطات بتتولّد بالمرجع وبتنفحص (نص الملصق).
"""

from __future__ import annotations

import io
import json
import shutil
from datetime import datetime
from pathlib import Path

import config

import refprompts
from brief import slug_code

ANGLES ={"front": "أمام", "back": "خلف", "left": "يسار", "right": "يمين", "top": "فوق", "bottom": "تحت"}      # إلزامية
EXTRA_SLOTS = {"in_hand": "بيد (للحجم)", "label": "الملصق قريب",
               "box_front": "العلبة من قدّام", "with_box": "المنتج مع علبته"}                                 # اختيارية
SLOTS = {**ANGLES, **EXTRA_SLOTS}
MAX_BYTES = 15 * 1024 * 1024
MAX_PROMPT_CHARS = 4000
RATIO_TOLERANCE = 0.15                  # فرق نسبة الصورة عن نسبة الأبعاد الحقيقية المقبول (15%)


class ProductRefError(Exception):
    pass


def _norm(code) -> str:
    """نفس تنظيف الاستوديو لكود المنتج (brief.slug_code: حروف وأرقام، حتى 24) بحروف صغيرة —
    فالورقة والتوليد (image_studio.product_code) دايماً بيلاقوا نفس المجلد."""
    return slug_code(code).lower()


def _code(code: str) -> str:
    c = _norm(code)
    if not c:
        raise ProductRefError("كود المنتج غير صالح")
    return c


def dir_of(code: str) -> Path:
    return Path(config.LIBRARY_DIR) / "product_refs" / _code(code)


def _empty(code: str) -> dict:
    return {"code": _code(code), "angles": {a: None for a in SLOTS},
            "dims_cm": {"h": None, "w": None, "d": None}, "label_text": "", "colors": [],
            "visual": "", "box_text": "", "prompts": {}, "locked": {}, "meta": {}}


def load(code: str) -> dict:
    p = dir_of(code) / "ref.json"
    d = _empty(code)
    if p.exists():
        saved = json.loads(p.read_text(encoding="utf-8"))
        angles = {**d["angles"], **(saved.get("angles") or {})}                 # ملفات قديمة بدون الوضعيات الاختيارية
        d.update(saved)
        d["angles"] = angles
    return d


def _save(ref: dict) -> dict:
    d = dir_of(ref["code"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "ref.json").write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
    return ref


def set_details(code: str, dims_cm: dict | None = None, label_text: str | None = None,
                colors: list | None = None, visual: str | None = None, box_text: str | None = None) -> dict:
    ref = load(code)
    if box_text is not None:
        b = str(box_text).strip()
        if len(b) > 600:
            raise ProductRefError("نص العلبة طويل (الحد 600 حرف)")
        ref["box_text"] = b
    if visual is not None:
        v = str(visual).strip()
        if len(v) > 600:
            raise ProductRefError("وصف الشكل طويل (الحد 600 حرف)")
        ref["visual"] = v
    if dims_cm is not None:
        out = {}
        for k in ("h", "w", "d"):
            v = dims_cm.get(k)
            if v in (None, ""):
                out[k] = None
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                raise ProductRefError("الأبعاد أرقام بالسنتيمتر")
            if not 0.5 <= out[k] <= 200:
                raise ProductRefError("الأبعاد خارج المعقول (0.5–200 سم)")
        ref["dims_cm"] = out
    if label_text is not None:
        ref["label_text"] = str(label_text).strip()
    if colors is not None:
        ref["colors"] = [str(c).strip() for c in colors if str(c).strip()][:8]
    return _save(ref)


def _auto_remove_background(im):
    """تفريغ الخلفية بـ BiRefNet محلياً (بلا إنترنت). بيرجّع صورة RGBA."""
    import tempfile
    from PIL import Image
    import bgremove
    if not bgremove.available():
        raise ProductRefError("نموذج تفريغ الخلفية غير منزّل (models/BiRefNet) — ارفع PNG مفرَّغ جاهز")
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.png", Path(td) / "out.png"
        im.convert("RGB").save(src, "PNG")
        try:
            bgremove.remove_background(src, dst)
        except bgremove.BgRemoveError as e:
            raise ProductRefError(str(e))
        with Image.open(dst) as out:
            out.load()
            return out.convert("RGBA")


def set_angle(code: str, angle: str, data: bytes, auto_remove: bool = False) -> dict:
    """PNG مفرَّغ بقناة شفافية (alpha). بنرفض اللي بلا شفافية لأن التركيب بيعتمد عليها —
    إلا لو طُلب التفريغ التلقائي (auto_remove): بيقبل أي صورة (JPG/PNG/WebP) وبيفرّغ خلفيتها محلياً."""
    from PIL import Image
    if angle not in SLOTS:
        raise ProductRefError("زاوية غير معروفة")
    if (load(code).get("locked") or {}).get(angle):
        raise ProductRefError(f"وضعية «{SLOTS[angle]}» مثبّتة — فكّ التثبيت أول إذا بدك تبدّل صورتها")
    if len(data) > MAX_BYTES:
        raise ProductRefError("الملف كبير (الحد 15MB)")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ProductRefError("الملف مش صورة صالحة")
    has_alpha = im.format == "PNG" and "A" in im.getbands() and im.convert("RGBA").getchannel("A").getextrema()[0] < 255
    if auto_remove and not has_alpha:
        im = _auto_remove_background(im)
    elif im.format != "PNG":
        raise ProductRefError("لازم PNG مفرَّغ (خلفية شفافة) — أو فعّل «فرّغ الخلفية تلقائياً»")
    im = im.convert("RGBA")
    lo, hi = im.getchannel("A").getextrema()
    if lo == 255:
        raise ProductRefError("الصورة بلا شفافية — فرّغ الخلفية أولاً، أو فعّل «فرّغ الخلفية تلقائياً»")
    d = dir_of(code) / "angles"
    d.mkdir(parents=True, exist_ok=True)
    im.save(d / f"{angle}.png")
    ref = load(code)
    ref["angles"][angle] = f"angles/{angle}.png"
    box = im.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()        # إطار المنتج الفعلي (بدون الشفاف)
    ref.setdefault("meta", {})[angle] = {"w": box[2] - box[0], "h": box[3] - box[1]} if box else {}
    return _save(ref)


def angle_path(code: str, angle: str) -> Path | None:
    rel = load(code)["angles"].get(angle)
    if not rel:
        return None
    p = (dir_of(code) / rel).resolve()
    return p if p.exists() and dir_of(code).resolve() in p.parents else None


def delete_angle(code: str, angle: str) -> dict:
    """حذف صورة وضعية: بتنتقل لسلة library/_trash/product_refs/<code>/ (بترجع لو بدك) مش مسح نهائي. المثبّتة ما بتنحذف."""
    if angle not in SLOTS:
        raise ProductRefError("زاوية غير معروفة")
    ref = load(code)
    if (ref.get("locked") or {}).get(angle):
        raise ProductRefError(f"وضعية «{SLOTS[angle]}» مثبّتة — فكّ التثبيت أول إذا بدك تحذف صورتها")
    p = angle_path(code, angle)
    if not p:
        raise ProductRefError("ما في صورة بهالوضعية")
    trash = Path(config.LIBRARY_DIR) / "_trash" / "product_refs" / _code(code)
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(trash / f"{angle}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"))
    ref["angles"][angle] = None
    (ref.get("meta") or {}).pop(angle, None)
    return _save(ref)


def missing(ref: dict) -> list[str]:
    out = [f"زاوية: {lbl}" for a, lbl in ANGLES.items() if not ref["angles"].get(a)]
    if not all(ref["dims_cm"].get(k) for k in ("h", "w", "d")):
        out.append("الأبعاد بالسنتيمتر")
    if not ref["label_text"]:
        out.append("نص الملصق الحرفي")
    if not ref["colors"]:
        out.append("الألوان")
    return out


def can_composite(code: str) -> bool:
    """التركيب بيحتاج زاوية «أمام» بس."""
    return bool(angle_path(code, "front"))


# ═════════════════ الوضعيات والبرومبتات (ورقة المنتج) ═════════════════
def product_info(code: str) -> dict:
    """اسم المنتج وفئته ووصف شكله من ملف المنتج (products/*.json) — كل منتج مستقل بكوده. فاضي لو ما انلقى."""
    want = _code(code)
    for f in sorted(Path(config.PRODUCTS_DIR).glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _norm(d.get("product_code") or f.stem) == want or _norm(f.stem) == want:
            return {"file": f.name, "name": str(d.get("product_name") or ""), "category": str(d.get("category") or ""),
                    "visual": str(d.get("product_visual") or "")}
    return {"file": "", "name": "", "category": "", "visual": ""}


def _inputs(ref: dict, info: dict) -> dict:
    return dict(name=info.get("name") or ref["code"], category=info.get("category") or "",
                visual=ref.get("visual") or info.get("visual") or "", dims=ref.get("dims_cm") or {},
                label=ref.get("label_text") or "", colors=ref.get("colors") or [], box_text=ref.get("box_text") or "")


def default_prompt(ref: dict, slot: str, info: dict | None = None) -> str:
    if slot not in SLOTS:
        raise ProductRefError("زاوية غير معروفة")
    return refprompts.product_prompt(slot, **_inputs(ref, info if info is not None else product_info(ref["code"])))


def ratio_check(ref: dict, slot: str) -> dict | None:
    """نسبة الصورة المفرَّغة مقابل نسبة الأبعاد الحقيقية. None = ما في صورة/ما في توقّع لهالوضعية. ok=None = الأبعاد ناقصة."""
    spec = next((s["ratio"] for s in refprompts.PRODUCT_SLOTS if s["slot"] == slot), None)
    m = (ref.get("meta") or {}).get(slot) or {}
    if not spec or not m.get("w") or not m.get("h"):
        return None
    a, b = (ref.get("dims_cm") or {}).get(spec[0]), (ref.get("dims_cm") or {}).get(spec[1])
    actual = m["w"] / m["h"]
    if not a or not b:
        return {"ok": None, "actual": round(actual, 3), "expected": None, "diff_pct": None}
    expected = a / b
    diff = abs(actual - expected) / expected
    return {"ok": diff <= RATIO_TOLERANCE, "expected": round(expected, 3), "actual": round(actual, 3), "diff_pct": round(diff * 100)}


def sheet(code: str) -> dict:
    """ورقة المنتج: لكل وضعية ثابتة صورتها + برومبتها (الفعلي والأصلي) + التثبيت + فحص النسبة."""
    ref = load(code)
    info = product_info(code)
    slots = []
    for s in refprompts.PRODUCT_SLOTS:
        k = s["slot"]
        default = default_prompt(ref, k, info)
        over = (ref.get("prompts") or {}).get(k)
        slots.append({"slot": k, "label": SLOTS[k], "label_en": s["en"], "pose_ar": s["pose_ar"], "required": s["required"],
                      "has_image": bool(ref["angles"].get(k)), "locked": bool((ref.get("locked") or {}).get(k)),
                      "prompt": {"text": over or default, "default": default, "edited": bool(over)},
                      "check": ratio_check(ref, k), "needs_front": k != "front", "use_note": refprompts.product_use_note(k)})
    return {"slots": slots, "product": {"name": info.get("name") or ref["code"], "category": info.get("category"), "file": info.get("file")},
            "prompt_gaps": refprompts.product_gaps(dims=ref["dims_cm"], label=ref["label_text"], colors=ref["colors"],
                                                   visual=ref.get("visual") or info.get("visual") or ""),
            "visual_from_brief": (not ref.get("visual")) and bool(info.get("visual")), "brief_visual": info.get("visual") or ""}


def set_prompt(code: str, slot: str, text: str) -> dict:
    if slot not in SLOTS:
        raise ProductRefError("زاوية غير معروفة")
    t = str(text or "").strip()
    if not t:
        raise ProductRefError("البرومبت فاضي — اضغط «رجّع الأصلي» بدل ما تفضّيه")
    if len(t) > MAX_PROMPT_CHARS:
        raise ProductRefError(f"البرومبت أطول من {MAX_PROMPT_CHARS} حرف")
    ref = load(code)
    ref.setdefault("prompts", {})[slot] = t
    return _save(ref)


def reset_prompt(code: str, slot: str) -> dict:
    if slot not in SLOTS:
        raise ProductRefError("زاوية غير معروفة")
    ref = load(code)
    (ref.get("prompts") or {}).pop(slot, None)
    return _save(ref)


def set_lock(code: str, slot: str, locked: bool) -> dict:
    """تثبيت وضعية معتمدة: ما بتنبدّل صورتها لحد ما تنفكّ. بدها صورة أصلاً."""
    if slot not in SLOTS:
        raise ProductRefError("زاوية غير معروفة")
    ref = load(code)
    if locked and not ref["angles"].get(slot):
        raise ProductRefError("ما في صورة للتثبيت — ارفع صورة الوضعية أول")
    lk = ref.setdefault("locked", {})
    if locked:
        lk[slot] = True
    else:
        lk.pop(slot, None)
    return _save(ref)


def list_products() -> list[dict]:
    """كل المنتجات (من products/ + أي ملف مرجعي موجود) — كل واحد بتقدّمه: كم وضعية إلزامية جاهزة."""
    rows: dict[str, dict] = {}
    for f in sorted(Path(config.PRODUCTS_DIR).glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        code = _norm(d.get("product_code") or f.stem)
        if code:
            rows[code] = {"code": code, "name": str(d.get("product_name") or code), "category": str(d.get("category") or ""), "file": f.name}
    base = Path(config.LIBRARY_DIR) / "product_refs"
    if base.exists():
        for p in sorted(base.iterdir()):
            if p.is_dir() and (p / "ref.json").exists():
                rows.setdefault(p.name, {"code": p.name, "name": p.name, "category": "", "file": ""})
    out = []
    for code, row in rows.items():
        try:
            ref = load(code)
        except ProductRefError:
            continue
        out.append({**row, "done": sum(1 for a in ANGLES if ref["angles"].get(a)), "required": len(ANGLES),
                    "extra_done": sum(1 for a in EXTRA_SLOTS if ref["angles"].get(a)),
                    "locked": sum(1 for a in SLOTS if (ref.get("locked") or {}).get(a)), "complete": not missing(ref)})
    return out


def prompts_docx(code: str) -> tuple[str, bytes]:
    """ملف Word بكل برومبتات المنتج (للصقها بـ ChatGPT/Flow). بيرجّع (اسم الملف، bytes)."""
    sh = sheet(code)
    name = sh["product"]["name"]
    intro = [f"المنتج: {name} ({_code(code)})",
             "ترتيب الشغل: ولّد وضعية «أمام» أول وراجعها. بعدها لكل وضعية تانية: ارفق صورة «أمام» مع برومبت الوضعية (قفل الهوية)، وولّد. ارفع كل صورة بمكانها بالنظام.",
             "كل البرومبتات بنفس الإطار والإضاءة والخلفية عشان الحجم والزوايا تطلع ثابتة. لا تغيّر غير وضعية الكاميرا."]
    if sh["prompt_gaps"]:
        intro.append("ناقص بالبرومبتات (كمّله بالنظام قبل التوليد): " + "، ".join(sh["prompt_gaps"]))
    return f"{_code(code)}_reference_prompts.docx", refprompts.build_docx(f"برومبتات الصور المرجعية — {name}", intro, refprompts.slot_docx_items(sh["slots"]))


def docx_sections(code: str) -> list[dict]:
    """قسم Word لمنتج واحد (عنوان فاصل + وضعياته) — ref_docx بيجمّع الأقسام بملف واحد لكل المراجع."""
    sh = sheet(code)
    ref = load(code)
    lines = [f"الكود: {_code(code)} · الوضعيات الأساسية الجاهزة: {sum(1 for a in ANGLES if ref['angles'].get(a))} من {len(ANGLES)}"]
    if sh["prompt_gaps"]:
        lines.append("ناقص بالبرومبتات (كمّله بالنظام قبل التوليد): " + "، ".join(sh["prompt_gaps"]))
    return [{"heading": True, "title": f"المنتج: {sh['product']['name']}", "lines": lines}, *refprompts.slot_docx_items(sh["slots"])]
