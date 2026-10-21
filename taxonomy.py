"""
التصنيفات المغلقة: اللهجة · الإطار · الفئة · البلد.

القاعدة: قيمة الحقل دايماً من قائمة ثابتة (slug). النص الحر ممنوع.
والتحويل من النص الحر **ما بيخمّن** — إما تطابق قاطع أو الحالة بتنرفع لطابور
المراجعة (review_queue.py) مع المرشّحين الممكنين.

الأسماء العربية للعرض بس؛ المخزَّن دايماً الـ slug الإنجليزي.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── اللهجة ──────────────────────────────────────────────────────────────
DIALECTS = {
    "shami": "شامي",
    "egyptian": "مصري",
    "gulf": "خليجي",
    "iraqi": "عراقي",
    "maghrebi": "مغاربي",
    "hassani": "حساني",
    "msa_simple": "فصحى مبسطة",
    "none": "بلا كلام",
}

# لهجة فرعية اختيارية — لكل واحدة اللهجة الأم اللي بتنتمي إلها
DIALECT_SUBS = {
    "jordanian": ("أردني", "shami"), "syrian": ("سوري", "shami"),
    "lebanese": ("لبناني", "shami"), "palestinian": ("فلسطيني", "shami"),
    "saudi": ("سعودي", "gulf"), "emirati": ("إماراتي", "gulf"),
    "kuwaiti": ("كويتي", "gulf"), "qatari": ("قطري", "gulf"),
    "tunisian": ("تونسي", "maghrebi"), "moroccan": ("مغربي", "maghrebi"),
    "algerian": ("جزائري", "maghrebi"), "libyan": ("ليبي", "maghrebi"),
}

_DIALECT_RX = [
    ("shami", r"shami|levant|jordan|syria|palestin|leban|شام|أردن|سور"),
    ("gulf", r"gulf|khaleej|khaleeji|saudi|emirat|kuwait|qatar|bahrain|omani|خليج|سعود"),
    ("egyptian", r"egypt|مصر"),
    ("iraqi", r"iraq|عراق"),
    ("maghrebi", r"tunis|morocc|algeri|maghreb|libya|مغرب|مغارب|تونس|جزائر"),
    ("hassani", r"hassani|mauritan|حساني"),
    ("msa_simple", r"fusha|fus'ha|classical|\bmsa\b|modern standard|standard arabic|فصح"),
]
_DIALECT_SUB_RX = {
    "jordanian": r"jordan|أردن|\bjd\b", "syrian": r"syria|سور", "lebanese": r"leban|لبنان",
    "palestinian": r"palestin|فلسطين", "saudi": r"saudi|سعود", "emirati": r"emirat|إمارات",
    "kuwaiti": r"kuwait|كويت", "qatari": r"qatar|قطر", "tunisian": r"tunis|تونس",
    "moroccan": r"morocc|مغرب", "algerian": r"algeri|جزائر", "libyan": r"libya|ليب",
}
_DIALECT_NONE_RX = r"^\s*none\b|no dialogue|no speech|silent|wordless|no voice|بلا كلام"

# ── الإطار ──────────────────────────────────────────────────────────────
FRAMEWORKS = {
    "pas": "مشكلة ← تضخيم ← حل",
    "us_vs_them": "نحن مقابل هم",
    "authority_reveal": "كشف السلطة",
    "ugc_testimonial": "شهادة مستخدم",
    "the_hack": "الحيلة",
    "demo_proof": "إثبات بالعرض",
    "ingredient_reveal": "كشف المكوّنات",
    "story": "قصة",
    "countdown_ranked": "ترتيب تنازلي",
    "offer_bundle": "حزمة العرض",
}

def _fw_key(s: str) -> str:
    return re.sub(r"[^a-z0-9؀-ۿ]", "", str(s).casefold())

# أسماء معروفة لنفس الإطار. المفتاح منمّط (حروف وأرقام بس).
_FW_ALIASES: dict[str, str] = {}
for _slug, _names in {
    "pas": ["problem-agitate-solve", "problem agitate solve", "pas", "problem agitate resolve"],
    "us_vs_them": ["us vs them", "us versus them", "us-vs-them", "competitor comparison"],
    "authority_reveal": ["authority reveal", "authority", "expert reveal"],
    "ugc_testimonial": ["ugc testimonial", "ugc review", "testimonial", "ugc"],
    "the_hack": ["the hack", "hack", "life hack"],
    "demo_proof": ["demo-proof", "demo proof", "demonstration", "product demo"],
    "ingredient_reveal": ["ingredient reveal", "ingredients reveal"],
    "story": ["story loop", "story", "storytelling", "narrative"],
    "countdown_ranked": ["ranked list / countdown reveal", "ranked list", "countdown reveal",
                         "countdown", "top 3 countdown"],
    "offer_bundle": ["offer bundle", "bundle offer", "bundle reveal", "bundle"],
}.items():
    for _n in _names:
        _FW_ALIASES[_fw_key(_n)] = _slug
for _slug, _label in FRAMEWORKS.items():
    _FW_ALIASES[_fw_key(_slug)] = _slug
    _FW_ALIASES[_fw_key(_label)] = _slug

# كلمات مفتاحية بس لاقتراح مرشّحين على المراجع البشري — ما بتُطبَّق تلقائياً
_FW_HINTS = {
    "pas": r"problem|agitate|solve|pain", "us_vs_them": r"\bvs\b|versus|them|comparison",
    "authority_reveal": r"authority|expert", "ugc_testimonial": r"ugc|testimonial|review",
    "the_hack": r"hack|trick", "demo_proof": r"demo|proof|demonstrat",
    "ingredient_reveal": r"ingredient", "story": r"story|narrative",
    "countdown_ranked": r"countdown|ranked|top", "offer_bundle": r"bundle|offer|deal",
}

# ── الفئة ───────────────────────────────────────────────────────────────
# (اسم عربي، مجموعة). المجموعة هي أساس «الجوار»: نفس المجموعة = فئة مجاورة.
CATEGORIES = {
    "fragrance": ("عطور", "beauty"),
    "skincare": ("عناية بالبشرة", "beauty"),
    "hair_removal": ("إزالة الشعر", "beauty"),
    "hair_care": ("عناية بالشعر", "beauty"),
    "makeup": ("مكياج", "beauty"),
    "eye_care": ("عناية بالعين", "health"),
    "ear_care": ("عناية بالأذن", "health"),
    "oral_care": ("عناية بالفم والأسنان", "health"),
    "supplements": ("مكمّلات غذائية", "health"),
    "joint_pain": ("مفاصل وآلام", "health"),
    "wellness_device": ("أجهزة صحية", "health"),
    "home_kitchen": ("أدوات منزلية ومطبخ", "home"),
    "cleaning": ("تنظيف", "home"),
    "gadgets": ("أدوات وإلكترونيات", "home"),
    "apparel": ("ملابس", "fashion"),
    "accessories": ("إكسسوارات", "fashion"),
    "other": ("أخرى", "other"),
}
CATEGORY_LABELS = {k: v[0] for k, v in CATEGORIES.items()}

# ── أنواع الهوك (افتتاحية الإعلان) ─────────────────────────────────────────
# قائمة مغلقة: الكاتب بيطلّع هوكات من أنواع مختلفة، والمالك بيشوف الاسم العربي.
HOOK_TYPES = {
    "question": "سؤال",
    "number": "رقم",
    "life_moment": "موقف من الحياة",
    "contrarian": "ادعاء معاكس",
    "visual_shock": "صدمة بصرية",
}

# الترتيب مهم: الأخص قبل الأعم (إزالة الشعر قبل البشرة)
_CATEGORY_RX = [
    ("hair_removal", r"hair[\s-]*removal|depilat|إزالة\s*الشعر|ازالة\s*الشعر"),
    ("fragrance", r"fragran|perfum|cologne|عطر|\bscent"),
    ("eye_care", r"\beye|عين"),
    ("ear_care", r"\bear[\s-]*(care|drops?|wax)|\bear\b|أذن|اذن"),
    ("oral_care", r"oral|dental|tooth|teeth|أسنان|فم"),
    ("hair_care", r"hair[\s-]*(care|growth|oil|serum|loss)|شعر"),
    ("skincare", r"skin|serum|moistur|بشرة"),
    ("makeup", r"makeup|cosmetic|مكياج"),
    ("supplements", r"supplement|vitamin|مكمل|فيتامين"),
    ("joint_pain", r"joint|pain|arthr|مفاصل|ألم"),
    ("wellness_device", r"massager|wellness device|جهاز"),
    ("home_kitchen", r"kitchen|cookware|home\b|مطبخ"),
    ("cleaning", r"clean|detergent|تنظيف"),
    ("gadgets", r"gadget|electronic|إلكترون"),
    ("apparel", r"apparel|clothing|fashion|dress|ملابس"),
    ("accessories", r"accessor|jewel|watch|إكسسوار"),
]

# فئة أخص بتغلب فئات أعم بتطابق نفس النص (إزالة الشعر تغلب عناية بالشعر والبشرة)
_SUPERSEDES = {"hair_removal": {"hair_care", "skincare"}}


def category_group(slug: str | None) -> str | None:
    return CATEGORIES.get(slug or "", (None, None))[1]

def category_distance(product_cat: str | None, pattern_cat: str | None) -> str:
    """same | adjacent | far | unknown — أساس مبرر النقل بالمطابقة."""
    if not product_cat or not pattern_cat:
        return "unknown"
    if product_cat == pattern_cat:
        return "same"
    ga, gb = category_group(product_cat), category_group(pattern_cat)
    if ga in (None, "other") or gb in (None, "other"):
        return "unknown"
    return "adjacent" if ga == gb else "far"

# ── البلد ───────────────────────────────────────────────────────────────
COUNTRIES = {
    "SY": "سوريا", "SA": "السعودية", "AE": "الإمارات", "EG": "مصر", "IQ": "العراق",
    "JO": "الأردن", "KW": "الكويت", "QA": "قطر", "BH": "البحرين", "OM": "عُمان",
    "LB": "لبنان", "PS": "فلسطين", "MA": "المغرب", "DZ": "الجزائر", "TN": "تونس",
    "LY": "ليبيا", "SD": "السودان", "YE": "اليمن", "MR": "موريتانيا",
}
_COUNTRY_RX = {
    "SY": r"syria|سوريا|سورية", "SA": r"saudi|السعودية|المملكة", "AE": r"emirates|uae|الإمارات",
    "EG": r"egypt|مصر", "IQ": r"iraq|العراق", "JO": r"jordan|الأردن", "KW": r"kuwait|الكويت",
    "QA": r"qatar|قطر", "BH": r"bahrain|البحرين", "OM": r"oman|عمان|عُمان", "LB": r"leban|لبنان",
    "PS": r"palestin|فلسطين", "MA": r"morocc|المغرب", "DZ": r"algeri|الجزائر", "TN": r"tunis|تونس",
    "LY": r"libya|ليبيا", "SD": r"sudan|السودان", "YE": r"yemen|اليمن", "MR": r"mauritan|موريتانيا",
}

# ── نتيجة التحويل ───────────────────────────────────────────────────────
@dataclass
class Norm:
    value: str | None            # الـ slug المعتمد، أو None
    status: str                  # ok | review | empty
    candidates: list[str] = field(default_factory=list)
    sub: str | None = None       # لهجة فرعية
    secondary: str | None = None # إطار ثانوي
    needs_confirm: bool = False  # طُبّق فعلاً بس ترتيبه بيستاهل تأكيد بشري
    note: str = ""


def normalize_dialect(raw) -> Norm:
    text = str(raw or "").strip()
    if not text:
        return Norm(None, "empty")
    if text in DIALECTS:
        return Norm(text, "ok")
    if re.search(_DIALECT_NONE_RX, text, re.I):
        return Norm("none", "ok")

    hits = [slug for slug, rx in _DIALECT_RX if re.search(rx, text, re.I)]
    if len(hits) == 1:
        slug = hits[0]
        sub = next((s for s, rx in _DIALECT_SUB_RX.items()
                    if DIALECT_SUBS[s][1] == slug and re.search(rx, text, re.I)), None)
        return Norm(slug, "ok", sub=sub)
    if len(hits) > 1:
        return Norm(None, "review", candidates=hits, note="أكتر من لهجة مذكورة")
    return Norm(None, "review", note="ما انعرفت اللهجة")


def normalize_framework(raw) -> Norm:
    text = str(raw or "").strip()
    if not text:
        return Norm(None, "empty")

    whole = _FW_ALIASES.get(_fw_key(text))
    if whole:                                  # اسم إطار واحد معروف (حتى لو فيه "/")
        return Norm(whole, "ok")

    # دمج صريح بفاصل: "A | B" أو "A / B" — كل جزء لازم يكون معروف
    parts = [p.strip() for p in re.split(r"\s*[|/]\s*", text) if p.strip()]
    if len(parts) >= 2:
        slugs = [_FW_ALIASES.get(_fw_key(p)) for p in parts]
        if all(slugs):
            uniq = list(dict.fromkeys(slugs))
            return Norm(uniq[0], "ok", secondary=uniq[1] if len(uniq) > 1 else None,
                        needs_confirm=len(uniq) > 1,
                        note="مدموج بالأصل — الترتيب حسب الكتابة وبيستاهل تأكيد")

    hints = [s for s, rx in _FW_HINTS.items() if re.search(rx, text, re.I)]
    return Norm(None, "review", candidates=hints, note="اسم إطار غير معروف")


def normalize_category(raw) -> Norm:
    text = str(raw or "").strip()
    if not text:
        return Norm(None, "empty")
    if text in CATEGORIES:
        return Norm(text, "ok")
    for slug, (label, _g) in CATEGORIES.items():
        if text == label:
            return Norm(slug, "ok")

    hits = []
    for slug, rx in _CATEGORY_RX:
        if re.search(rx, text, re.I):
            hits.append(slug)
    dominated = set().union(*[_SUPERSEDES.get(h, set()) for h in hits]) if hits else set()
    hits = [h for h in hits if h not in dominated]
    if len(hits) == 1:
        return Norm(hits[0], "ok")
    if len(hits) > 1:
        return Norm(None, "review", candidates=hits, note="أكتر من فئة مطابقة")
    return Norm(None, "review", note="فئة غير معروفة")


def normalize_country(raw) -> Norm:
    text = str(raw or "").strip()
    if not text:
        return Norm(None, "empty")
    if text.upper() in COUNTRIES:
        return Norm(text.upper(), "ok")
    hits = [c for c, rx in _COUNTRY_RX.items() if re.search(rx, text, re.I)]
    if len(hits) == 1:
        return Norm(hits[0], "ok")
    if len(hits) > 1:
        return Norm(None, "review", candidates=hits, note="أكتر من بلد")
    return Norm(None, "review", note="بلد غير محدد — «السوق العربي» مثلاً مش بلد")


def vocab_block() -> str:
    """نص المفردات المغلقة اللي بينحقن ببرومبتات التشريح والاستيراد والتعلّم."""
    fw = "\n".join(f"  - {k}: {v}" for k, v in FRAMEWORKS.items())
    dl = "\n".join(f"  - {k}: {v}" for k, v in DIALECTS.items())
    ct = "\n".join(f"  - {k}: {v[0]}" for k, v in CATEGORIES.items())
    return (
        "=== CLOSED VOCABULARIES (use these exact slugs — never free text) ===\n"
        "`dialect_or_language` — one value:\n" + dl + "\n"
        "`framework` — the ONE primary framework. Never join two with | or /.\n"
        "  If a secondary mechanism is clearly present, put it in `framework_secondary`\n"
        "  (same list, or null):\n" + fw + "\n"
        "`product_category` — one value:\n" + ct + "\n"
        "If nothing fits, use `other` for category and choose the closest framework —\n"
        "do not invent new values."
    )


def inject_vocab(prompt: str) -> str:
    """يحقن المفردات مكان {{VOCAB}}، وإذا المستخدم شالها بيلصقها بآخر البرومبت."""
    block = vocab_block()
    return prompt.replace("{{VOCAB}}", block) if "{{VOCAB}}" in prompt else prompt.rstrip() + "\n\n" + block + "\n"


def apply_to_pattern(p: dict) -> tuple[dict, list[dict]]:
    """
    يطبّق التصنيف على نمط. بيرجّع (النمط، مشاكل للمراجعة).
    القيم الأصلية بتنحفظ بـ `_legacy` وما بتنمسح.
    """
    issues: list[dict] = []
    legacy = dict(p.get("_legacy") or {})
    for k in ("dialect_or_language", "framework", "product_category"):
        if k in p and k not in legacy:
            legacy[k] = p[k]

    def raw_of(k):  # الأصل دايماً، مش القيمة المعدّلة
        return legacy.get(k, p.get(k))

    # حقول قرّرها المالك (من المحرّر أو طابور المراجعة): ما بتنعاد حسابتها من الأصل، وما بتنرفع إلها بنود مراجعة
    locked = set((p.get("_taxonomy") or {}).get("locked") or [])

    d = normalize_dialect(raw_of("dialect_or_language"))
    f = normalize_framework(raw_of("framework"))
    c = normalize_category(raw_of("product_category"))

    if "dialect_or_language" not in locked:
        p["dialect_or_language"] = d.value
        p["dialect_sub"] = d.sub
    if "framework" not in locked:
        p["framework"] = f.value
        p["framework_secondary"] = f.secondary
    if "product_category" not in locked:
        p["product_category"] = c.value

    for kind, n, key in (("dialect", d, "dialect_or_language"), ("framework", f, "framework"),
                         ("category", c, "product_category")):
        if key in locked:
            continue
        if n.status in ("review", "empty"):
            issues.append({"kind": kind, "raw": raw_of(key), "candidates": n.candidates,
                           "note": n.note, "applied": False})
        elif n.needs_confirm:
            issues.append({"kind": "framework_order", "raw": raw_of(key),
                           "candidates": [n.value, n.secondary], "note": n.note, "applied": True})

    p["_legacy"] = legacy
    p["_taxonomy"] = {"version": 1, "complete": not any(not i["applied"] for i in issues)}
    if locked:
        p["_taxonomy"]["locked"] = sorted(locked)
    return p, issues
