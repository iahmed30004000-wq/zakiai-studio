"""
برومبتات اللقطات — المحطة ٦.

النظام بيكتب برومبت عربي لكل لقطة من: كلماتها · الوصف البصري · نوع اللقطة · مرجع الشخصية ·
مرجع المنتج. المالك بيعاين وبيعدّل قبل التوليد. الكتابة قاطعة بالكود (قالب)؛ وبطلب صريح
(`refine=True`) الموديل بيحسّنها ويترجم نسخة للموديل — وأي فشل بيرجع للقالب.

القواعد اللي بتنفرض بالكود مهما كتب الموديل أو المالك:
  · بلا أي كتابة/حروف/أرقام داخل الصورة (النص بينحط بالمونتاج).
  · كل لقطة بنوع مختلف عن اللي جنبها بنفس المشهد.
  · ما في برومبتين متطابقين بالسيناريو.

الموديل بياخد دايماً نسخة إنجليزية (prompt_model): بتنترجم من العربي (اللي بيعدّله المالك) بالذكاء، ومعها بطاقة هوية الشخصية
الإنجليزية (identity.py) — لأنو الموديلات الصينية بتميل لملامح شرق آسيا والوصف الثابت بيثبّت الهوية. لو الترجمة فشلت
(الذكاء مش متاح) بيروح للموديل بطاقة الهوية + البرومبت العربي، وبتنعاد المحاولة بالتوليد الجاي.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import config
import timeline

MAX_LEN = 1500
NO_TEXT = "بدون أي كتابة أو حروف أو أرقام أو شعارات داخل الصورة"
TYPE_LABEL = {"close": "لقطة قريبة", "medium": "لقطة متوسطة", "wide": "لقطة واسعة",
              "hand_product": "يد مع المنتج"}
# ترتيب التنويع: أول لقطة بتاخد نوع المشهد الأصلي، والباقي بتدور على هالقائمة
_CYCLE = ["close", "hand_product", "wide", "medium"]
_NO_TEXT_RX = re.compile(r"بدون\s+(?:أي|اي)?\s*كتاب")


class ShotPromptError(Exception):
    pass


def _ensure_no_text(p: str) -> str:
    p = re.sub(r"\s+", " ", p).strip()
    return p if _NO_TEXT_RX.search(p) else f"{p}. {NO_TEXT}."


def assign_types(tl: dict) -> None:
    """أنواع لقطات مختلفة جنب بعض بنفس المشهد (الأولى بتحافظ على نوع المشهد الأصلي)."""
    for sc in tl["scenes"]:
        prev = None
        used = []
        for k, sh in enumerate(sc["shots"]):
            t = sh.get("type") if sh.get("type") in timeline.SHOT_TYPES else "medium"
            if k > 0 and (t == prev or t in used):
                t = next((c for c in _CYCLE if c != prev and c not in used), None) or \
                    next(c for c in timeline.SHOT_TYPES if c != prev)
            sh["type"] = t
            used.append(t)
            prev = t


def _words_of(tl: dict, sh: dict) -> str:
    a, b = sh["word_range"]
    return " ".join(w["text"] for w in tl["words"][a:b + 1])


def _who(ch: dict | None, stype: str) -> str:
    if not ch:
        return ""
    look = f"{ch.get('skin', '')}، {ch.get('hair', '')}، لبس: {(ch.get('wardrobe') or {}).get('description', '')}"
    if stype == "hand_product":
        return f"يد {ch['name_ar']} فقط (نفس البشرة: {ch.get('skin', '')}) — بدون وجه"
    return f"الشخصية {ch['name_ar']}، {look} — نفس الوجه والملامح من الورقة المرجعية بالضبط"


def compose(tl: dict, scene: dict, sh: dict, script_scene: dict, product: str, ch: dict | None,
            first: bool) -> str:
    stype = sh["type"]
    words = _words_of(tl, sh)
    parts = [f"{TYPE_LABEL.get(stype, stype)}"]
    visual = (script_scene.get("visual") or "").strip()
    if first and visual:
        parts.append(visual)
    else:
        parts.append("لقطة دخيلة تخدم الكلام بزاوية وإطار مختلفين عن اللقطة السابقة")
    who = _who(ch, stype)
    if who:
        parts.append(who)
    if stype in ("hand_product", "close") and product:
        parts.append(f"المنتج «{product}» بمظهره الحقيقي من صورة المرجع — لا تغيّر العبوة ولا الألوان")
    parts.append(f"يغطّي الكلام: «{words}»")
    if scene.get("emotion"):
        parts.append(f"الشعور: {scene['emotion']}")
    parts.append("عمودي 9:16")
    return _ensure_no_text(". ".join(p for p in parts if p))[:MAX_LEN]


def build(tl: dict, script: dict, product: str = "", ch: dict | None = None,
          product_ref: str | None = None) -> dict:
    """يملأ prompt_ar لكل لقطة (وبيعيد كتابة الموجود). مسموح بس على خط زمني صالح."""
    if not timeline.validate(tl)["ok"]:
        raise ShotPromptError("الخط الزمني فيه أخطاء — صلّحها قبل البرومبتات")
    assign_types(tl)
    smap = {s.get("scene_number"): s for s in script.get("scenes", [])}
    for sc in tl["scenes"]:
        for k, sh in enumerate(sc["shots"]):
            if sh.get("inherited"):                      # نسخة هوك: اللقطة موروثة بصورتها وبرومبتها (ما بنعيد كتابتها)
                continue
            sh["prompt_ar"] = compose(tl, sc, sh, smap.get(sc["n"], {}), product, ch, k == 0)
            sh["prompt_model"] = ""
            sh["refs"] = {"character_id": (ch or {}).get("id"), "product_ref": product_ref}
            sh["prompt_edited"] = False
    return tl


def refine(tl: dict, log=print, ch: dict | None = None, country: str = "") -> dict:
    """تحسين اختياري بالموديل: بنداء واحد لكل الأفلام. أي خطأ ← القالب يبقى."""
    import llm
    shots = [{"id": sh["id"], "type": sh["type"], "prompt_ar": sh["prompt_ar"]}
             for sc in tl["scenes"] for sh in sc["shots"]]
    system = (Path(config.PROMPTS_DIR) / "shot_planner.txt").read_text(encoding="utf-8") if \
        (Path(config.PROMPTS_DIR) / "shot_planner.txt").exists() else ""
    task = ("حسّن كل برومبت عربي ليكون أوضح وقابل للتنفيذ لموديل صور، وأعطِ نسخة إنجليزية prompt_model. "
            "التزم بالمعرّفات والأنواع كما هي، وحافظ على «بدون أي كتابة داخل الصورة» وعلى ذكر مرجع الشخصية والمنتج. "
            'رجّع JSON فقط: {"shots":[{"id","prompt_ar","prompt_model"}]}')
    try:
        res = llm.complete_json("shotplan", system + "\n\n" + task,
                                [{"type": "text", "text": json.dumps(shots, ensure_ascii=False)}],
                                config.MAX_OUTPUT_TOKENS)
        by_id = {s.get("id"): s for s in (res.get("shots") or [])}
    except Exception as e:                          # فشل الموديل ما بيوقف — القالب كافي
        log(f"[!] تعذّر تحسين البرومبتات ({e}) — بنبقى على القالب")
        return tl
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            r = by_id.get(sh["id"])
            if not r:
                continue
            ar = str(r.get("prompt_ar") or "").strip()
            if ar:
                sh["prompt_ar"] = _ensure_no_text(ar)[:MAX_LEN]
            en = str(r.get("prompt_model") or "").strip()
            if en:
                sh["prompt_model"] = _finish_en(en, sh, ch, country)
    return tl


# ── النسخة الإنجليزية اللي بتروح للموديل (دايماً) ─────────────────────────
_NO_TEXT_EN = re.compile(r"\b(?:no|without)\s+(?:any\s+|visible\s+|on-screen\s+)?(?:text|writing|letters|captions)", re.I)
_AR_LETTER = re.compile(r"[\u0600-\u06FF]")
_EN_CHUNK = 25
_EN_SYSTEM = ("You translate image-generation prompts written in Arabic into natural, precise English for an image model. "
              "Keep every instruction and visual detail; keep names as written; never add details; never drop the rule that the "
              "image contains no text, letters, numbers or logos. The quoted Arabic voiceover words are only scene context: express "
              "their meaning in a few words and do NOT quote them. Reply with JSON only: {\"shots\": [{\"id\": \"...\", \"en\": \"...\"}]}.")


def character_of(sh: dict) -> dict | None:
    """شخصية اللقطة من مرجعها (بلا ذكاء، قراءة ملف بس)."""
    cid = (sh.get("refs") or {}).get("character_id")
    if not cid:
        return None
    try:
        import characters
        return characters.get(cid)
    except Exception:                                   # noqa: BLE001
        return None


def _identity_line(sh: dict, ch: dict | None, country: str = "") -> str:
    """بطاقة الهوية قبل كل برومبت فيه وجه. لقطات اليد بلا وجه فبلا بطاقة (بشرة اليد بتجي من الورقة المرجعية)."""
    if not ch or sh.get("type") == "hand_product":
        return ""
    import identity
    return (f"Subject (identical in every shot): {identity.text_of(ch, country)}. "
            "Keep exactly the same face as in the attached reference images. ")


def _finish_en(en: str, sh: dict, ch: dict | None, country: str = "") -> str:
    en = re.sub(r"\s+", " ", str(en or "")).strip()
    if not _NO_TEXT_EN.search(en):
        en = f"{en.rstrip('. ')}. No text, letters, numbers or logos in the image."
    return (_identity_line(sh, ch, country) + en)[:MAX_LEN]


def model_prompt(sh: dict, ch: dict | None = None, country: str = "") -> str:
    """البرومبت اللي بينبعت للموديل: النسخة الإنجليزية المخزّنة، وإلا بطاقة الهوية + البرومبت العربي (الترجمة لسا ما صارت)."""
    en = (sh.get("prompt_model") or "").strip()
    if en:
        return en
    ar = (sh.get("prompt_ar") or "").strip()
    if not ar:
        return ""
    return (_identity_line(sh, ch if ch is not None else character_of(sh), country) + ar)[:MAX_LEN]


def _llm_translate(items: list[dict]) -> dict[str, str]:
    import llm
    res = llm.complete_json("imgprompt", _EN_SYSTEM, [{"type": "text", "text": json.dumps(items, ensure_ascii=False)}],
                            config.MAX_OUTPUT_TOKENS)
    rows = res.get("shots") if isinstance(res, dict) else None
    return {str(r.get("id")): str(r.get("en") or "").strip() for r in (rows or []) if isinstance(r, dict)}


def _mostly_english(t: str) -> bool:
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and len(_AR_LETTER.findall(t)) / len(letters) < 0.3


def english_for(tl: dict, ch: dict | None = None, country: str = "", translate=None, only=None, log=print,
                force: bool = False) -> dict:
    """يضمن نسخة إنجليزية (prompt_model) للقطات اللي ما إلها: ترجمة برومبتها العربي بنداء واحد (دفعات ٢٥)
    + بطاقة هوية الشخصية. فشل الذكاء ما بيوقف شي: اللقطة بتضل بلا نسخة (model_prompt بيرجع للعربي) وبتنعاد المحاولة لاحقاً.
    only: معرّفات لقطات محدّدة. force: يعيد حتى لو في نسخة. بيرجّع {done, failed}."""
    todo = [sh for sc in tl["scenes"] for sh in sc["shots"]
            if (only is None or sh["id"] in only) and (sh.get("prompt_ar") or "").strip() and not sh.get("inherited")
            and (force or not (sh.get("prompt_model") or "").strip())]
    if not todo:
        return {"done": 0, "failed": 0}
    if ch:
        try:                                            # بطاقة الهوية أول (بتنترجم وبتنخزّن مرة وحدة)
            import characters
            import identity
            identity.ensure(ch["id"], country)
            ch = characters.get(ch["id"]) or ch
        except Exception as e:                          # noqa: BLE001
            log(f"[!] بطاقة الهوية: {type(e).__name__} — بنكمّل بنسختها الأساسية")
    got: dict[str, str] = {}
    items = [{"id": sh["id"], "ar": sh["prompt_ar"]} for sh in todo]
    for i in range(0, len(items), _EN_CHUNK):
        try:
            got.update((translate or _llm_translate)(items[i:i + _EN_CHUNK]))
        except Exception as e:                          # noqa: BLE001 — الذكاء مش متاح: بنكمّل بلا ترجمة
            log(f"[!] تعذّرت ترجمة البرومبتات للإنجليزي ({type(e).__name__}) — بتنعاد عند التوليد")
    done = 0
    for sh in todo:
        en = (got.get(sh["id"]) or "").strip()
        if en and _mostly_english(en):
            sh["prompt_model"] = _finish_en(en, sh, ch, country)
            done += 1
    return {"done": done, "failed": len(todo) - done}


def set_prompt(tl: dict, shot_id: str, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ShotPromptError("البرومبت فاضي")
    if len(text) > MAX_LEN:
        raise ShotPromptError(f"البرومبت أطول من {MAX_LEN} حرف")
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == shot_id:
                sh["prompt_ar"] = _ensure_no_text(text)
                sh["prompt_model"] = ""            # النسخة المترجمة قديمة بعد التعديل
                sh["prompt_edited"] = True
                return sh
    raise ShotPromptError("لقطة غير موجودة")


def validate(tl: dict) -> list[dict]:
    """مشاكل تمنع الاعتماد: {shot, message}."""
    out, seen = [], {}
    for sc in tl["scenes"]:
        prev = None
        for sh in sc["shots"]:
            p = (sh.get("prompt_ar") or "").strip()
            if not p:
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: بلا برومبت"})
                continue
            if len(p) > MAX_LEN:
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: البرومبت أطول من {MAX_LEN}"})
            if not _NO_TEXT_RX.search(p):
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: ما فيه «بدون كتابة»"})
            if p in seen:
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: برومبتها مطابق لـ {seen[p]}"})
            seen[p] = sh["id"]
            if prev is not None and sh.get("type") == prev:
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: نفس نوع اللقطة اللي قبلها"})
            prev = sh.get("type")
    return out
