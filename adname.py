"""
اسم الإعلان على ميتا: `البلد|المنتج|الصفحة|النوع` + خانة خامسة اختيارية `VP-<script_id>`.

الخانة الخامسة هي الـ script_id كما هو (بيبدأ بـ VP- أصلاً): هي الرابط الوحيد بين
إعلان شغّال وسيناريو VidPattern. إعلان بأربع خانات (أو خامسة مش VP-) بيضل شغّال
بس `script_id=None` — بره التعلّم، وما بنخمّن سيناريوه أبداً.
"""

from __future__ import annotations

import re

SEP = "|"
AD_TYPE = "video"
SCRIPT_PREFIX = "VP-"
_SCRIPT_RX = re.compile(r"^VP-[^|\s]+-\d+-v\d+(?:-h\d+)?$")           # -hN اختياري: نسخة هوك بديل من نفس السيناريو


def _clean(part, label: str) -> str:
    text = re.sub(r"\s+", " ", str(part or "")).strip().replace(SEP, "-")
    if not text:
        raise ValueError(f"حقل «{label}» فاضي — ما بيصير نبني اسم الإعلان")
    return text


def build(country: str, product_code: str, landing_page: str, script_id: str) -> str:
    """يبني الاسم بخمس خانات. الفاصل | ممنوع داخل الحقول (بيتبدّل بـ -)."""
    sid = _clean(script_id, "script_id")
    if not sid.startswith(SCRIPT_PREFIX):
        raise ValueError(f"الـ script_id لازم يبدأ بـ {SCRIPT_PREFIX}")
    return SEP.join([_clean(country, "البلد"), _clean(product_code, "كود المنتج"),
                     _clean(landing_page, "الصفحة"), AD_TYPE, sid])


def is_script_id(value) -> bool:
    return bool(value) and bool(_SCRIPT_RX.match(str(value).strip()))


def parse(name: str) -> dict:
    """
    يقرأ 4 أو 5 خانات. ما بيرمي أبداً: اسم ناقص/غريب = حقول None.
    الخانة الخامسة بتُقبل كـ script_id فقط لو بصيغة VP-{code}-{n}-v{v} (أو VP-{code}-{n}-v{v}-h{k} لنسخة هوك).
    """
    parts = [p.strip() for p in str(name or "").split(SEP)]
    while len(parts) < 4:
        parts.append("")
    fifth = parts[4] if len(parts) > 4 else ""
    return {
        "country": parts[0] or None,
        "product": parts[1] or None,
        "landing_page": parts[2] or None,
        "type": parts[3] or None,
        "script_id": fifth if is_script_id(fifth) else None,
    }
