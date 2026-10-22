#!/usr/bin/env python3
"""
بطاقة الهوية الإنجليزية للشخصية — جملة وحدة ثابتة بتنحط بكل برومبت صورة وتحريك فيه الشخصية.

ليش: موديلات الفيديو الصينية بتميل لملامح شرق آسيا، والصورة المرجعية وحدها ما بتكفي. وصف إنجليزي ثابت (العمر، الجنسية،
الملامح، البشرة، الشعر، اللبس) بيثبّت الهوية، ومعه «برومبت سلبي» ضد الملامح الشرق آسيوية للموديلات اللي بتقبله (NEGATIVE).

  · بتنبني لحالها من بيانات الشخصية: العمر والجنس والبلد من الكود، والبشرة والشعر واللبس والملامح العربية بتنترجم بالذكاء
    مرة وحدة وبتنحفظ بملف الشخصية (identity_en). لو الذكاء مش متاح بتنبني نسخة ناقصة (الأساس بس) وبتنعاد المحاولة لاحقاً.
  · المالك بيقدر يعدّلها بإيده (auto=False)؛ وبعدها ما بتنكتب فوقها أبداً، وبيرجّعها تلقائية لما يمسح النص.
  · بطاقة وحدة لكل شخصية: بلد التوليد (market_look) جزء من بصمة المصدر، فتغيّر البلد بيعيد بناءها.
دوال build/current صافية (بلا ذكاء ولا ملفات)؛ ensure/set_manual/reset هي اللي بتكتب بملف الشخصية.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

GENDER = {"m": "man", "f": "woman"}
# بلد (ISO) ← (الجنسية، المنطقة). الباقي بيطلع «Arab» عام لأنو سوقنا عربي.
COUNTRIES = {
    "SY": ("Syrian", "Levantine Arab"), "LB": ("Lebanese", "Levantine Arab"), "JO": ("Jordanian", "Levantine Arab"),
    "PS": ("Palestinian", "Levantine Arab"), "IQ": ("Iraqi", "Mesopotamian Arab"),
    "SA": ("Saudi", "Gulf Arab"), "AE": ("Emirati", "Gulf Arab"), "KW": ("Kuwaiti", "Gulf Arab"),
    "QA": ("Qatari", "Gulf Arab"), "BH": ("Bahraini", "Gulf Arab"), "OM": ("Omani", "Gulf Arab"),
    "YE": ("Yemeni", "Arab"), "EG": ("Egyptian", "Egyptian Arab"), "SD": ("Sudanese", "Arab"),
    "LY": ("Libyan", "North African Arab"), "TN": ("Tunisian", "North African Arab"),
    "DZ": ("Algerian", "North African Arab"), "MA": ("Moroccan", "North African Arab"),
}
# ممنوع بالموديلات اللي بتقبل برومبت سلبي (Kling, Wan…): الانحراف المعروف للنماذج الصينية + تغيّر الوجه
NEGATIVE = ("East Asian facial features, Chinese or Japanese or Korean appearance, different person, face change, "
            "face morphing, identity drift, distorted face, deformed hands, extra fingers")
FALLBACK_TAIL = "same skin tone, hair and outfit as the reference images"
MAX_TEXT = 600

_SYSTEM = ("You turn short Arabic character-description fragments into concise English noun phrases for image and video "
           "generation prompts. Keep every concrete detail (colors, materials, lengths, styles) exactly as given; never invent "
           "details and never add flattering adjectives. skin → '<tone> skin'; hair → '<length/texture/color> hair' (plus a covering "
           "or style if mentioned); outfit → '<garments with colors>' without the word 'wearing'; look → a short phrase about the "
           "facial/regional look. Reply with JSON only: {\"skin\": \"...\", \"hair\": \"...\", \"outfit\": \"...\", \"look\": \"...\"} "
           "and leave out any key that was not provided.")
_AR = re.compile(r"[؀-ۿ]")
_TASHKEEL = re.compile(r"[ً-ْـ]")


class IdentityError(Exception):
    """رسالة عربية جاهزة للعرض."""


def has_arabic(text: str) -> bool:
    return bool(_AR.search(text or ""))


def _norm(t) -> str:
    t = _TASHKEEL.sub("", str(t or ""))
    return re.sub(r"\s+", " ", t).strip()


# ── المصدر والبصمة ───────────────────────────────────────────────────────
def pick_country(ch: dict, country: str = "") -> str:
    """بلد الشخصية للبطاقة: المطلوب إن كان معروف، وإلا الوحيد بملامح السوق، وإلا فاضي (عربي عام)."""
    c = (country or "").strip().upper()
    if c in COUNTRIES:
        return c
    looks = [k.upper() for k in (ch.get("market_look") or {}) if k.upper() in COUNTRIES]
    return looks[0] if len(looks) == 1 else ""


def source_fields(ch: dict, country: str = "") -> dict[str, str]:
    """الحقول الحرّة (عربي) اللي بتنترجم. الفاضي بينشال."""
    looks = ch.get("market_look") or {}
    c = pick_country(ch, country)
    look = next((v for k, v in looks.items() if k.upper() == c), "") if c else (next(iter(looks.values()), "") if len(looks) == 1 else "")
    out = {"skin": ch.get("skin"), "hair": ch.get("hair"), "outfit": (ch.get("wardrobe") or {}).get("description"), "look": look}
    return {k: _norm(v) for k, v in out.items() if _norm(v)}


def src_hash(ch: dict, country: str = "") -> str:
    blob = json.dumps({"g": ch.get("gender"), "a": ch.get("age"), "c": pick_country(ch, country), "f": source_fields(ch, country)},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ── التجميع (صافي) ───────────────────────────────────────────────────────
def _clean_phrase(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip(" .,;،")


def build(ch: dict, country: str = "", translations: dict | None = None) -> str:
    """الجملة الإنجليزية. translations: {skin, hair, outfit, look} بالإنجليزي (ناقصة = بنكتب «نفس المرجع»)."""
    tr = {k: _clean_phrase(v) for k, v in (translations or {}).items() if _clean_phrase(v) and not has_arabic(str(v))}
    who = GENDER.get(ch.get("gender"), "person")
    age = ch.get("age")
    c = pick_country(ch, country)
    nat, region = COUNTRIES.get(c, ("Arab", "Middle Eastern"))
    head = f"a {age}-year-old " if isinstance(age, int) and age else "a "
    head += f"{nat} ({region}) {who}" if c else f"Middle Eastern Arab {who}"
    parts = [head + " with natural Middle Eastern facial features"]
    for k in ("look", "skin", "hair"):
        if tr.get(k):
            parts.append(tr[k])
    if tr.get("outfit"):
        outfit = re.sub(r"^(?:wearing|dressed in)\s+", "", tr["outfit"], flags=re.I)
        parts.append(f"wearing {outfit}")
    if not any(tr.get(k) for k in ("skin", "hair", "outfit")):
        parts.append(FALLBACK_TAIL)
    return ", ".join(parts)[:MAX_TEXT]


def current(ch: dict, country: str = "") -> dict:
    """البطاقة المعتمدة الآن (بلا ذكاء ولا كتابة): {text, auto, complete, stale}.
    المعدّلة يدوياً دايماً بتنرجع كما هي. التلقائية المبنية من نفس البيانات الحالية بتنرجع (الناقصة كمان، بس stale=True يعني لسا
    بدها ترجمة). اللي بياناتها تغيّرت بعدها بنرجّع الأساس (build بلا ترجمة) وبنعلّمها stale."""
    st = ch.get("identity_en") or {}
    text = str(st.get("text") or "").strip()
    if st.get("auto") is False and text:
        return {"text": text, "auto": False, "complete": True, "stale": False}
    if text and st.get("src") == src_hash(ch, country):
        done = bool(st.get("complete"))
        return {"text": text, "auto": True, "complete": done, "stale": not done}
    return {"text": build(ch, country), "auto": True, "complete": not source_fields(ch, country), "stale": True}


def text_of(ch: dict | None, country: str = "") -> str:
    """الجملة الجاهزة للبرومبتات (فاضية لو ما في شخصية)."""
    return current(ch, country)["text"] if ch else ""


# ── الترجمة بالذكاء ──────────────────────────────────────────────────────
def llm_translate(fields: dict[str, str]) -> dict[str, str]:
    """نداء واحد لكل الحقول. بيرمي أي استثناء من المزوّد — المستدعي بيقرر (ensure بيبلع وبيعلّم «ناقصة»)."""
    import llm
    res = llm.complete_json("imgprompt", _SYSTEM, [{"type": "text", "text": json.dumps(fields, ensure_ascii=False)}], 600)
    if not isinstance(res, dict):
        raise IdentityError("رد الترجمة مش بالشكل المتوقع")
    return {k: str(res[k]) for k in fields if isinstance(res.get(k), str) and res[k].strip()}


def ensure(cid: str, country: str = "", translate=None, force: bool = False) -> dict:
    """يضمن بطاقة حديثة مخزّنة بملف الشخصية (بترجم لو لازم). المعدّلة يدوياً ما بتنلمس. بيرجّع current()."""
    import characters
    ch = characters.get(cid)
    if not ch:
        raise IdentityError("الشخصية غير موجودة")
    st = ch.get("identity_en") or {}
    if st.get("auto") is False and str(st.get("text") or "").strip():
        return current(ch, country)
    src = src_hash(ch, country)
    if not force and st.get("src") == src and st.get("complete") and str(st.get("text") or "").strip():
        return current(ch, country)
    fields = source_fields(ch, country)
    tr = {}
    complete = True
    if fields:
        try:
            tr = (translate or llm_translate)(fields)
        except Exception:                                  # noqa: BLE001 — الذكاء مش متاح: نسخة ناقصة وبنعيد لاحقاً
            tr, complete = {}, False
        else:
            complete = all(k in tr and not has_arabic(tr[k]) for k in fields)
    text = build(ch, country, tr)
    characters.set_identity(cid, {"text": text, "auto": True, "complete": complete, "src": src, "country": pick_country(ch, country),
                                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return current(characters.get(cid), country)


def set_manual(cid: str, text: str) -> dict:
    """المالك كتب البطاقة بإيده (إنجليزي). نص فاضي = رجوع للتلقائية."""
    import characters
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return reset(cid)
    if has_arabic(t):
        raise IdentityError("البطاقة لازم تكون بالإنجليزي (الموديلات بتفهمها أدق)")
    if len(t) > MAX_TEXT:
        raise IdentityError(f"البطاقة أطول من {MAX_TEXT} حرف")
    characters.set_identity(cid, {"text": t, "auto": False, "complete": True, "src": "", "country": "",
                                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return current(characters.get(cid))


def reset(cid: str) -> dict:
    import characters
    characters.set_identity(cid, None)
    return current(characters.get(cid))


def negative(ch: dict | None = None) -> str:
    """البرومبت السلبي الثابت (للموديلات اللي بتقبله)."""
    return NEGATIVE


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="بطاقة الهوية الإنجليزية للشخصية")
    ap.add_argument("character_id")
    ap.add_argument("--country", default="")
    ap.add_argument("--rebuild", action="store_true", help="أعد الترجمة بالذكاء")
    a = ap.parse_args()
    try:
        r = ensure(a.character_id, a.country, force=a.rebuild)
    except IdentityError as e:
        sys.exit(f"[!] {e}")
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
