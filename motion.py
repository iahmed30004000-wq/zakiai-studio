#!/usr/bin/env python3
"""
المحطة ٩: التحريك بموديلات محلية.

    python motion.py run library/scripts/X.json --shot s2c1 [--model mm_x] [--n 2]

سجل الموديلات (library/motion_models.json) بيعبّيه المالك. كل موديل بيُشغَّل بأمر خارجي (قائمة وسائط)
فيه أماكن: {image} {prompt_file} {prompt} {seconds} {width} {height} {out} — فما في افتراض عن شكل أي موديل.

القواعد بالكود:
  · مدة الحركة = مدة اللقطة بالضبط (قص لو أطول، تمديد لو أقصر بحدود ١٥٪، وإلا فشل).
  · برومبت الحركة بهيكل ثابت من ٧ أقسام ≤ ٢٠٠٠ حرف.
  · الاختيار التلقائي بيراعي نوع اللقطة ووصف الحركة والمدة والذاكرة المتاحة — وبيقول ليش استبعد كل موديل.
  · لقطات الكلام على الكاميرا: مزامنة شفاه بموديل محلي يدعمها (أمر ثاني بالسجل).
  · نوعين موديل: «أمر محلي» (kind=command) و«صندوق نموذج» (kind=http: خدمة Docker على نفس الجهاز/السيرفر،
    services/engine). عنوان الصندوق بقائمة سماح صارمة: http، loopback أو اسم docker بلا نقاط، منفذ صريح، بلا تحويلات.
  · kind=api: تحريك عبر API مباشر (motion_api.py، fal.ai) بالدفع حسب الثانية — بيتقدّر سعره قبل التشغيل وبينفرض سقف إنفاق للسيناريو،
    وبيستخدم برومبت إنجليزي ثابت (النماذج الخارجية بتفهم الإنجليزي أحسن من العربي).
  · ثبات وجه الشخصية: لقطات الوجه بتاخد بطاقة الهوية الإنجليزية (identity.py) ببرومبتها الإنجليزي، وبرومبت سلبي ضد ملامح شرق آسيا
    وتغيّر الوجه (للموديلات اللي بتقبله)، ونفس صورة اللقطة كصورة نهاية (Kling/Hailuo؛ بتتخطّى لحركات الكاميرا)، وصور الشخصية كمرجع
    للموديل المرجعي. وبعد كل فيديو بنفحص وجهه محلياً (facecheck.py: 3 لقطات) وبنسجّل نتيجة كل موديل (production_log.face_rates):
    الترتيب التلقائي بيقدّم اللي بيحافظ على الوجه. الفحص بيعلّم بس («الوجه تغيّر») والمالك هو اللي بيقرر.
  · الحركات السينمائية (motion_presets.py): وصفة على اللقطة (camera_preset) بتحدّد كلام الكاميرا حسب عائلة الموديل (Hailuo بأوامره بين أقواس،
    Kling جملة طبيعية)، وبتفضّل عائلة موديل، وبتقرر إذا في حركة كاميرا (بتتعارض مع صورة النهاية). أول فيديو بوصفة بيتحفظ كمثال.
  · بديل تلقائي: لو موديل فشل لسبب تقني (مهلة/اتصال/نقص ذاكرة/خرج غير صالح) بنجرّب التالي بالترتيب (حتى 3 محاولات)،
    وكل محاولة بتنسجّل بسجل الإنتاج (production_log.py). أخطاء المالك/الحالة ما إلها بديل.
"""

from __future__ import annotations

import argparse
import io
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import facecheck
import motion_api
import motion_presets
import production_log
import studio_state
import timeline

STRENGTHS = {"faces": "وجوه", "product": "منتج", "camera_motion": "حركة كاميرا", "realism": "واقعية", "hand": "يد"}
MAX_PROMPT = 2000
MAX_DESC = 600
STRETCH_TOLERANCE = 0.15
# المشروع الحر بس (اقتراح البحث 3): مقطع أقصر لحد النص بيتمدّد بإطارات مخترعة بالنص (minterpolate)
# بدل الفشل وإعادة توليد مدفوعة. المهمة الموجّهة قواعدها ثابتة (١٥٪ وبس).
SMOOTH_STRETCH_MAX = 2.0
DURATION_EPS_MS = 60
SECTIONS = ["قفل المرجع", "الأجواء", "الواقعية الجسدية", "الكاميرا", "الفيزياء", "المزاج", "الممنوع"]
_CAMERA_RX = re.compile(r"كاميرا|تقريب|تبعيد|بانوراما|دفع|سحب|zoom|pan|dolly|tilt", re.I)
# حركة كاميرا فعلية (مش مجرد ذكر الكاميرا): صورة نهاية = نفس صورة البداية بتتعارض معها
_CAMERA_MOVE_RX = re.compile(r"تقريب|تبعيد|بانوراما|دفع|سحب|دوران|رافعة|تتبّع|تتبع|zoom|dolly|\bpan(?:s|ning)?\b|"
                             r"camera\s+(?:tilt|push|pull|move|moves|orbit|track)|push[- ]?in|pull[- ]?out|orbit|crane|tracking", re.I)
FACE_MIN_CHECKS = 3                    # أقل فحوص قبل ما نثق بنسبة موديل
FACE_WEIGHT = 10                       # نسبة الوجه 0..1 ← ±5 نقاط على الترتيب (نقطة القوة = 10)
HTTP_NEGATIVE = "worst quality, low quality, blurry, jittery, distorted, inconsistent motion, watermark, text, subtitles"
PLACEHOLDERS = ("{image}", "{prompt_file}", "{prompt}", "{seconds}", "{width}", "{height}", "{out}")


KINDS = {"command": "أمر محلي", "http": "صندوق نموذج (http)", "api": "API مباشر (fal.ai)"}
HTTP_MODES = ("i2v", "t2v")
HTTP_POLL_SEC = 2.0                    # كل كم ثانية نسأل الصندوق عن الحالة
HTTP_CALL_TIMEOUT = 30                 # مهلة نداء واحد للصندوق (مش مهلة الشغلة كلها)
MAX_ATTEMPTS = 3                       # أقصى عدد موديلات نجرّبها للقطة الواحدة
MAX_DOWNLOAD_MB = 1024
MAX_UPLOAD_MB = 18                     # أكبر من هيك الصورة بتنضغط JPEG قبل الإرسال (حد الصندوق 20)
ENGINE_MAX_SIDE = 2048                 # حد الصندوق لأبعاد الصورة المطلوبة
OOM_MARK = "الذاكرة ما كفّت"
_DOCKER_NAME_RX = re.compile(r"[a-z][a-z0-9_-]{0,62}")
_SECRET_NAME_RX = re.compile(r"[A-Za-z0-9_.-]{1,64}")
HTTP_KEYS = ("url", "mode", "steps", "guidance", "token_secret", "model")
_ENGINE_MODEL_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")        # اسم مجلد الأوزان بالصندوق العام (نفس قاعدة الصندوق)


class MotionError(Exception):
    """رسالة عربية جاهزة للعرض."""


class TechnicalError(MotionError):
    """فشل تقني بالموديل نفسه (مهلة، اتصال، نقص ذاكرة، خرج غير صالح…): مؤهل للبديل التلقائي.
    أي MotionError عادي = خطأ مالك/حالة (محطة مقفولة، ما في صورة…) وما إله بديل."""

    def __init__(self, msg: str, reason: str = "failed"):
        super().__init__(msg)
        self.reason = reason


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── السجل ───────────────────────────────────────────────────────────────
def registry_path() -> Path:
    return Path(config.LIBRARY_DIR) / "motion_models.json"


def load_models() -> list[dict]:
    p = registry_path()
    if p.exists():
        try:
            models = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        for m in models:
            m.setdefault("kind", "command")
        return models
    return []


def _save_models(models: list[dict]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8")


def _host_allowed(host: str) -> bool:
    import net_allow
    return net_allow.host_allowed(host)


def validate_engine_url(url) -> str:
    """قائمة سماح صارمة لعنوان صندوق النموذج (net_allow). بترجّع العنوان المنظَّف (http://host:port) أو بترمي MotionError."""
    import net_allow
    try:
        return net_allow.validate(url, subject="عنوان الصندوق", example="http://127.0.0.1:8101")
    except net_allow.NetAllowError as e:
        raise MotionError(str(e)) from None


def _clean_http(raw, existing: dict | None) -> dict:
    if not isinstance(raw, dict):
        raise MotionError("إعدادات الصندوق (http) مطلوبة: العنوان والوضع")
    bad = [k for k in raw if k not in HTTP_KEYS]
    if bad:
        raise MotionError(f"حقول غير معروفة بإعدادات الصندوق: {bad}")
    h = {**(existing or {}), **raw}
    out = {"url": validate_engine_url(h.get("url"))}
    mode = h.get("mode") or "i2v"
    if mode not in HTTP_MODES:
        raise MotionError("وضع الصندوق لازم i2v (صورة لفيديو) أو t2v (نص لفيديو)")
    out["mode"] = mode
    for k, lo, hi, integer in (("steps", 1, 200, True), ("guidance", 0, 30, False)):
        v = h.get(k)
        if v in (None, ""):
            out[k] = None
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise MotionError(f"{k}: لازم رقم") from None
        if not lo <= v <= hi:
            raise MotionError(f"{k}: خارج المعقول ({lo}–{hi})")
        out[k] = int(v) if integer else v
    ts = h.get("token_secret")
    if ts in (None, ""):
        out["token_secret"] = None
    elif isinstance(ts, str) and _SECRET_NAME_RX.fullmatch(ts.strip()):
        out["token_secret"] = ts.strip()
    else:
        raise MotionError("اسم مفتاح التوكن: حروف إنجليزية وأرقام و _ - . بس (حتى 64)")
    mdl = h.get("model")                                 # الصندوق العام (ENGINE_BACKEND=diffusers): أي مجلد أوزان بيشغّله؛ فاضي = صندوق بنموذج ثابت (ltx/wan)
    if mdl in (None, ""):
        out["model"] = None
    elif isinstance(mdl, str) and _ENGINE_MODEL_RX.fullmatch(mdl.strip()) and ".." not in mdl:
        out["model"] = mdl.strip()
    else:
        raise MotionError("اسم نموذج الصندوق: حروف إنجليزية وأرقام و _ - . بس (اسم مجلد الأوزان)")
    return out


def _clean_model(d: dict, existing: dict | None = None) -> dict:
    m = dict(existing or {})
    if (d.get("kind") or m.get("kind")) == "api" and "max_sec" not in d and "max_sec" not in m:
        a = d.get("api")
        durs = a.get("durations") if isinstance(a, dict) else None
        if isinstance(durs, list) and durs and all(isinstance(x, (int, float)) for x in durs):
            d = {**d, "max_sec": max(durs)}
    for k in ("name", "limits", "resolution"):
        if k in d:
            m[k] = str(d[k] or "").strip()
    if not m.get("name"):
        raise MotionError("اسم الموديل مطلوب")
    for k, lo, hi in (("max_sec", 0.5, 60), ("vram_gb", 0, 200), ("speed_sec_per_sec", 0, 3600)):
        if k in d:
            try:
                v = float(d[k])
            except (TypeError, ValueError):
                raise MotionError(f"{k}: لازم رقم")
            if not lo <= v <= hi:
                raise MotionError(f"{k}: خارج المعقول ({lo}–{hi})")
            m[k] = v
    if "max_sec" not in m:
        raise MotionError("أقصى مدة (max_sec) مطلوبة")
    m.setdefault("vram_gb", 0)
    m.setdefault("speed_sec_per_sec", 60)
    if "strengths" in d:
        bad = [s for s in (d["strengths"] or []) if s not in STRENGTHS]
        if bad:
            raise MotionError(f"نقاط قوة غير معروفة: {bad}")
        m["strengths"] = list(dict.fromkeys(d["strengths"] or []))
    m.setdefault("strengths", [])
    for k in ("command", "lipsync_command"):
        if k in d:
            cmd = d[k]
            if cmd in (None, "", []):
                m[k] = None
                continue
            if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
                raise MotionError(f"{k}: قائمة وسائط نصية (مو سطر واحد)")
            m[k] = cmd
    m.setdefault("command", None)
    m.setdefault("lipsync_command", None)
    kind = d.get("kind") or m.get("kind") or "command"
    if kind not in KINDS:
        raise MotionError("نوع التشغيل لازم «command» (أمر محلي) أو «http» (صندوق نموذج) أو «api» (API مباشر)")
    m["kind"] = kind
    if kind == "http":
        m["http"] = _clean_http(d["http"] if "http" in d else m.get("http"), m.get("http"))
    else:
        m["http"] = None
    if kind == "api":
        m["api"] = _clean_api(d["api"] if "api" in d else m.get("api"))
        if "speed_sec_per_sec" not in d and "speed_sec_per_sec" not in (existing or {}):
            m["speed_sec_per_sec"] = 15
    else:
        m["api"] = None
    if "enabled" in d:
        m["enabled"] = bool(d["enabled"])
    m.setdefault("enabled", True)
    m["lipsync"] = bool(m.get("lipsync_command")) or bool(d.get("lipsync", m.get("lipsync", False)))
    return m


def upsert_model(d: dict, model_id: str | None = None) -> dict:
    models = load_models()
    if model_id:
        cur = next((x for x in models if x["id"] == model_id), None)
        if not cur:
            raise MotionError("الموديل غير موجود")
        new = _clean_model(d, cur)
        models[models.index(cur)] = new
    else:
        new = _clean_model(d)
        nums = [int(x["id"].split("_")[1]) for x in models if re.fullmatch(r"mm_\d+", x["id"])]
        new["id"] = f"mm_{(max(nums) + 1 if nums else 1):03d}"
        models.append(new)
    _save_models(models)
    return new


def delete_model(model_id: str) -> None:
    models = load_models()
    if not any(x["id"] == model_id for x in models):
        raise MotionError("الموديل غير موجود")
    _save_models([x for x in models if x["id"] != model_id])


# ── الذاكرة المتاحة ─────────────────────────────────────────────────────
def available_vram_gb() -> float:
    """الذاكرة الحرة بكرت الشاشة (GB): كرت هالجهاز (torch)، وإلا كرت صندوق الأوزان على السيرفر (الكرت كله: الصندوق بيفرّغ نموذجه قبل
    ما غيره يشتغل، فالنموذج المحمّل هلأ ما بيستبعد غيره)، وإلا القيمة المضبوطة GPU_VRAM_GB (افتراضي ٦)."""
    try:
        import torch
        if torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            return round(free / 1024 ** 3, 1)
    except Exception:
        pass
    box = _box_vram_gb()
    if box is not None:
        return box
    return float(getattr(config, "GPU_VRAM_GB", 6))


def _box_vram_gb() -> float | None:
    """كرت صندوق الأوزان على السيرفر (الكرت كله، GB) أو None لو ما في صندوق مضبوط/ما ردّ."""
    try:
        import link_engine
        g = link_engine.gpu_info()
        return round(g["total_gb"], 1) if g else None
    except Exception:                                    # noqa: BLE001 — الصندوق مش مربوط/واقف: نكمّل بالقيمة المضبوطة
        return None


# ── الاختيار التلقائي ───────────────────────────────────────────────────
def needs_for(shot: dict, talking: bool = False) -> list[str]:
    typ = shot.get("type")
    need = {"close": ["product", "realism"], "hand_product": ["hand", "product"],
            "medium": ["faces", "realism"], "wide": ["camera_motion", "realism"]}.get(typ, ["realism"])
    if (shot.get("refs") or {}).get("character_id") and typ in ("medium", "close") and "faces" not in need:
        need.append("faces")
    if _CAMERA_RX.search(shot.get("motion_desc") or "") and "camera_motion" not in need:
        need.append("camera_motion")
    return need


def _not_runnable(m: dict) -> str | None:
    """سبب إن الموديل ما بينشغّل، أو None لو جاهز."""
    if m.get("kind", "command") == "api":
        if not m.get("api"):
            return "إعدادات الـ API ناقصة"
        if not motion_api.has_key():
            return "ما في مفتاح fal — حطّه من «المصنع» ثم «API»"
        return None
    if m.get("kind", "command") == "http":
        h = m.get("http") or {}
        if not h.get("url"):
            return "عنوان الصندوق ناقص بالسجل"
        try:
            validate_engine_url(h["url"])
        except MotionError as e:
            return f"عنوان الصندوق غير مسموح: {e}"
        return None
    return None if m.get("command") else "ما إله أمر تشغيل بالسجل"


def rank_models(shot: dict, models: list[dict] | None = None, vram_gb: float | None = None,
                talking: bool = False) -> dict:
    """{ranked:[{model,score,matched,eta_sec}], excluded:[{model,reason}]} — الاستبعاد بسبب مكتوب."""
    models = load_models() if models is None else models
    vram = available_vram_gb() if vram_gb is None else vram_gb
    dur = (shot["end_ms"] - shot["start_ms"]) / 1000
    need = needs_for(shot, talking)
    face_rates: dict = {}
    if "faces" in need and (shot.get("refs") or {}).get("character_id") and shot.get("type") != "hand_product":
        try:                                           # نسبة نجاح فحص الوجه لكل موديل (بتتجمّع من الفحوص السابقة)
            face_rates = production_log.face_rates("face_video")
        except Exception:                              # noqa: BLE001 — التعلّم تحسين مش شرط
            face_rates = {}
    ranked, excluded = [], []
    lib_lip = bool(talking and _library_lipsync())      # مزامنة من المكتبة: بتخلّي كل الموديلات مناسبة للقطات الكلام
    for m in models:
        if not m.get("enabled", True):
            excluded.append({"model": m, "reason": "معطّل"})
        elif _not_runnable(m):
            excluded.append({"model": m, "reason": _not_runnable(m)})
        elif m["max_sec"] + 1e-9 < dur:
            excluded.append({"model": m, "reason": f"أقصى مدة {m['max_sec']:g}ث أقصر من اللقطة ({dur:.1f}ث)"})
        elif m.get("vram_gb", 0) > vram:
            excluded.append({"model": m, "reason": f"بيحتاج {m['vram_gb']:g}GB وعندك {vram:g}GB حرة"})
        elif talking and not (m.get("lipsync") or lib_lip):
            excluded.append({"model": m, "reason": "لقطة كلام على الكاميرا وما بيدعم مزامنة شفاه"})
        else:
            matched = [s for s in need if s in m.get("strengths", [])]
            cost = est_cost(m, dur)
            # الملاءمة أهم (10 لكل نقطة قوة)، وبعدها الأرخص: المحلي مجاني، والـ API بيخصم ضعف سعره بالدولار
            score = 10 * len(matched) - round(m.get("speed_sec_per_sec", 0) / 60, 2) - 2 * (cost or 0)
            fr = face_rates.get(m["id"])
            bonus = round(FACE_WEIGHT * (fr["rate"] - 0.5), 2) if fr and fr["checks"] >= FACE_MIN_CHECKS else 0.0
            pref = motion_presets.preference(shot, m)             # وصفة سينمائية على اللقطة: العائلة المفضّلة للوصفة
            ranked.append({"model": m, "score": round(score + bonus + pref, 2), "matched": matched,
                           "eta_sec": round(m.get("speed_sec_per_sec", 0) * dur), "est_cost_usd": cost,
                           "face_rate": fr, "face_bonus": bonus, "preset_bonus": pref})
    ranked.sort(key=lambda r: (-r["score"], r["model"]["id"]))
    return {"ranked": ranked, "excluded": excluded, "needs": need, "vram_gb": vram}


# ── وصف الحركة وبرومبتها ────────────────────────────────────────────────
_DEFAULT_DESC = {
    "close": "تقريب بطيء على المنتج مع حركة ضوء خفيفة على سطحه",
    "hand_product": "اليد ترفع المنتج ببطء وتديره قليلاً أمام الكاميرا",
    "medium": "حركة طبيعية خفيفة للشخصية (تنفّس، تحريك رأس بسيط) والكاميرا شبه ثابتة",
    "wide": "دفع بطيء للكاميرا للأمام مع حركة محيط هادئة",
}


def default_motion_desc(shot: dict) -> str:
    return _DEFAULT_DESC.get(shot.get("type"), "حركة هادئة طبيعية")


def build_prompt(shot: dict, scene: dict, character: dict | None, duration_ms: int) -> str:
    """سبعة أقسام بترتيب ثابت. بنقصّ الأجواء ووصف الحركة لو تجاوزنا ٢٠٠٠ حرف، وبنرفض لو ما كفى."""
    desc = (shot.get("motion_desc") or default_motion_desc(shot)).strip()
    if len(desc) > MAX_DESC:
        raise MotionError(f"وصف الحركة طويل ({len(desc)} حرف) — الحد {MAX_DESC}")
    who = ""
    if character and shot.get("type") != "hand_product":
        who = f" الشخصية {character.get('name_ar', '')} بنفس الوجه واللبس تماماً."
    parts = {
        "قفل المرجع": "التزم بالصورة المرجعية بالضبط: نفس التكوين والوجه والمنتج والألوان والإضاءة، ولا تغيّر عبوة المنتج ولا الملصق." + who,
        "الأجواء": (f"الشعور العام: {scene['emotion']}. " if scene.get("emotion") else "") + "إضاءة ثابتة كما بالمرجع.",
        "الواقعية الجسدية": f"{desc}. حركة بشرية طبيعية، بدون تشوّه بالأصابع أو الوجه أو الأطراف.",
        "الكاميرا": "حركة كاميرا سينمائية هادئة ومتّسقة، بدون قفزات.",
        "الفيزياء": "الأجسام والسوائل والأقمشة بتتحرك بوزن وقصور ذاتي واقعي.",
        "المزاج": "هادئ وموثوق، بإيقاع بطيء.",
        "الممنوع": "ممنوع: أي كتابة أو نص أو شعار على الشاشة، وميض، تشوّه، تغيّر بالمنتج، تبديل الشخصية، قطع بالمشهد.",
    }
    body = "\n".join(f"{i + 1}. {k}: {parts[k]}" for i, k in enumerate(SECTIONS))
    head = f"مدة الحركة {duration_ms / 1000:.1f} ثانية بالضبط.\n"
    text = head + body
    if len(text) > MAX_PROMPT:                       # تقصير الأقسام المرنة قبل الرفض
        parts["الأجواء"] = "إضاءة ثابتة كما بالمرجع."
        text = head + "\n".join(f"{i + 1}. {k}: {parts[k]}" for i, k in enumerate(SECTIONS))
    if len(text) > MAX_PROMPT:
        raise MotionError(f"وصف الحركة طويل: برومبت الحركة {len(text)} حرف والحد {MAX_PROMPT}")
    return text


def validate_prompt(text: str) -> list[str]:
    out = []
    if len(text) > MAX_PROMPT:
        out.append(f"أطول من {MAX_PROMPT} حرف")
    for i, k in enumerate(SECTIONS, 1):
        if f"{i}. {k}:" not in text:
            out.append(f"ناقص القسم {i}: {k}")
    return out


# ── ffmpeg ──────────────────────────────────────────────────────────────
def probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                             capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def fit_duration(src: Path, dest: Path, target_ms: int, smooth: bool = False) -> dict:
    """مدة الحركة = مدة اللقطة بالضبط: قص لو أطول، تمديد لو أقصر بحدود ١٥٪، وإلا فشل.
    smooth=True (المشروع الحر): الأقصر لحد النص بيتمدّد بإطارات مخترعة (how=interpolated) بدل الفشل."""
    d = probe_duration(src)
    if d <= 0:
        raise TechnicalError("الموديل ما رجّع فيديو صالح", "bad_output")
    t = target_ms / 1000
    dest.parent.mkdir(parents=True, exist_ok=True)
    if d + 0.001 >= t:
        cmd = ["ffmpeg", "-y", "-i", str(src), "-t", f"{t:.3f}", "-an", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
        how = "trimmed" if d > t + 0.02 else "exact"
    elif d >= t * (1 - STRETCH_TOLERANCE):
        cmd = ["ffmpeg", "-y", "-i", str(src), "-filter:v", f"setpts={t / d:.6f}*PTS", "-t", f"{t:.3f}", "-an",
               "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
        how = "stretched"
    elif smooth and d >= t / SMOOTH_STRETCH_MAX:
        cmd = ["ffmpeg", "-y", "-i", str(src), "-filter:v",
               # إطارات مخترعة أول (60/ث)، بعدين إبطاء، وتثبيت آخر إطار لنص ثانية عشان -t يقص على المدة بالضبط
               f"minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,setpts={t / d:.6f}*PTS,fps=30,"
               "tpad=stop_mode=clone:stop_duration=0.5",
               "-t", f"{t:.3f}", "-an", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
        how = "interpolated"
    else:
        raise TechnicalError(f"الموديل أنتج {d:.1f}ث والمطلوب {t:.1f}ث — أقصر من الحد المسموح للتمديد ({round(STRETCH_TOLERANCE * 100)}٪)", "bad_output")
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not dest.exists():
        raise TechnicalError("فشل ffmpeg وقت ضبط المدة", "bad_output")
    got = probe_duration(dest)
    if abs(got * 1000 - target_ms) > DURATION_EPS_MS:
        raise TechnicalError(f"المدة بعد الضبط {got:.2f}ث ≠ {t:.2f}ث", "bad_output")
    return {"how": how, "source_sec": round(d, 2), "final_ms": target_ms}


# ── وصول للخط الزمني ────────────────────────────────────────────────────
def clips_dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "timelines" / stem / "clips"


def _rel(stem: str, p: Path) -> str:
    return p.resolve().relative_to((Path(config.LIBRARY_DIR) / "timelines" / stem).resolve()).as_posix()


def abs_of(stem: str, rel: str) -> Path | None:
    base = (Path(config.LIBRARY_DIR) / "timelines" / stem).resolve()
    p = (base / rel).resolve()
    return p if base in p.parents and p.exists() else None


def _is_free(stem: str) -> bool:
    return (timeline.load(stem) or {}).get("mode") == "free"


def _load(stem: str) -> dict:
    tl = timeline.load(stem)
    if not tl:
        raise MotionError("ما في خط زمني")
    return tl


def _shot(tl: dict, shot_id: str) -> tuple[dict, dict]:
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == shot_id:
                return sc, sh
    raise MotionError("لقطة غير موجودة")


def _final_image(sh: dict) -> str | None:
    im = sh.get("image") or {}
    return im.get("composite") or im.get("chosen")


def set_desc(script_path, shot_id: str, desc: str, talking: bool | None = None) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    desc = (desc or "").strip()
    if not desc:
        raise MotionError("وصف الحركة فاضي")
    sh["motion_desc"] = desc
    if talking is not None:
        sh["talking"] = bool(talking)
    sh["motion_prompt"] = None                       # بيتبنى من جديد عند التشغيل
    timeline.save(stem, tl)
    return sh


# ── التشغيل ─────────────────────────────────────────────────────────────
def _fill(cmd: list[str], values: dict) -> list[str]:
    out = []
    for a in cmd:
        for k, v in values.items():
            a = a.replace("{" + k + "}", str(v))
        out.append(a)
    return out


def _run_cmd(cmd: list[str], timeout: int, log) -> None:
    log("    $ " + " ".join(cmd[:3]) + (" …" if len(cmd) > 3 else ""))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise TechnicalError(f"أمر الموديل غير موجود: {cmd[0]}", "model_failed") from None
    except subprocess.TimeoutExpired:
        raise TechnicalError(f"الموديل تجاوز المهلة ({timeout}ث)", "timeout") from None
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-300:]
        raise TechnicalError(f"الموديل فشل ({r.returncode}): {tail}", "oom" if "out of memory" in tail.lower() else "model_failed")


# ── صندوق النموذج (http) ────────────────────────────────────────────────
def _engine_token(h: dict) -> str | None:
    """توكن الصندوق: من مخزن الأسرار باسم token_secret، وإلا من متغير البيئة ENGINE_TOKEN (سيرفر لينكس بلا Credential Manager).
    ما بيتسجّل ولا بيتعرض أبداً."""
    name = h.get("token_secret")
    if not name:
        return None
    try:
        import secrets_store
        v = secrets_store.get_secret(name)
    except Exception:                      # SecretsError أو مخزن غير متاح
        v = None
    return v or os.environ.get("ENGINE_TOKEN") or None


def _engine_session(token: str | None):
    import requests
    s = requests.Session()
    s.trust_env = False                    # ما نمرّر طلبات الصندوق عبر أي proxy من البيئة
    if token:
        s.headers["X-Engine-Token"] = token
    return s


def _engine_detail(resp) -> str:
    try:
        d = resp.json().get("detail")
        if isinstance(d, str):
            return d
        if d:
            return json.dumps(d, ensure_ascii=False)[:200]
    except Exception:
        pass
    return f"رد {resp.status_code}"


def _engine_call(sess, method: str, base: str, path: str, *, timeout=None, **kw):
    """نداء واحد للصندوق. بدون تحويلات أبداً، وأي فشل بيتحوّل لرسالة عربية تقنية."""
    import requests
    try:
        r = sess.request(method, base + path, timeout=timeout or HTTP_CALL_TIMEOUT, allow_redirects=False, **kw)
    except requests.exceptions.ConnectTimeout:
        raise TechnicalError(f"الصندوق ({base}) ما ردّ بوقت الاتصال", "connection") from None
    except requests.exceptions.ReadTimeout:
        raise TechnicalError(f"الصندوق ({base}) تأخر بالرد", "timeout") from None
    except requests.exceptions.RequestException:
        raise TechnicalError(f"ما قدرنا نتصل بالصندوق ({base}) — واقف أو مش شغّال", "connection") from None
    if 300 <= r.status_code < 400:
        r.close()
        raise TechnicalError("الصندوق حاول يحوّلنا لعنوان ثاني — التحويلات ممنوعة", "connection")
    if r.status_code == 401:
        r.close()
        raise TechnicalError("توكن الصندوق غلط أو ناقص — راجع اسم مفتاح التوكن بإعدادات الموديل", "auth")
    if r.status_code >= 400:
        msg = _engine_detail(r)
        code = r.status_code
        r.close()
        raise TechnicalError(f"الصندوق رفض الطلب: {msg}", "oom" if OOM_MARK in msg else ("missing" if code == 404 else "rejected"))
    return r


def _image_payload(img: Path) -> tuple[bytes, str]:
    """بايتات الصورة ونوعها. لو أكبر من الحد أو بصيغة غريبة بتتحوّل JPEG."""
    data = img.read_bytes()
    kind = ("image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if data.startswith(b"\xff\xd8\xff")
            else "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None)
    if kind and len(data) <= MAX_UPLOAD_MB * 1024 * 1024:
        return data, kind
    from PIL import Image
    with Image.open(img) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue(), "image/jpeg"


def _run_http(m: dict, img: Path | None, prompt: str, seconds: float, w: int, h: int, raw: Path, timeout: int, log,
              negative: str = "") -> None:
    """POST /jobs ← استطلاع GET /jobs/{id} ← تنزيل /result. DELETE بالنهاية دائماً (إلغاء لو لسا شغّالة، تنظيف لو خلصت)."""
    cfg = m.get("http") or {}
    base = validate_engine_url(cfg.get("url"))
    mode = cfg.get("mode") or "i2v"
    sess = _engine_session(_engine_token(cfg))
    scale = min(1.0, ENGINE_MAX_SIDE / max(w, h, 1))
    params = {"mode": mode, "prompt": prompt, "seconds": round(seconds, 3),
              "width": max(64, int(w * scale)), "height": max(64, int(h * scale))}
    for k in ("steps", "guidance"):
        if cfg.get(k) is not None:
            params[k] = cfg[k]
    if cfg.get("model"):                               # الصندوق العام: أي نموذج بيشغّل (مجلد أوزانه)
        params["model"] = cfg["model"]
    if negative:                                       # الصندوق بيقبله (ALLOWED_PARAMS)؛ بدونه بياخد سلبي الباكند الافتراضي
        params["negative_prompt"] = negative[:1900]
    files = None
    if mode == "i2v":
        if img is None:
            raise MotionError("وضع صورة لفيديو بدّه صورة معتمدة")
        data, mime = _image_payload(img)
        files = {"image": ("frame" + (".png" if mime == "image/png" else ".webp" if mime == "image/webp" else ".jpg"), data, mime)}
    log(f"    [http] {base} ({mode})")
    jid = None
    try:
        r = _engine_call(sess, "POST", base, "/jobs", data={"params": json.dumps(params, ensure_ascii=False)}, files=files)
        try:
            jid = r.json()["id"]
        except Exception:
            raise TechnicalError("رد الصندوق غير مفهوم (ما في رقم مهمة)", "bad_output") from None
        deadline = time.time() + timeout
        last = None
        while True:
            st = _engine_call(sess, "GET", base, f"/jobs/{jid}").json()
            status = st.get("status")
            pr = st.get("progress") or {}
            tag = (status, pr.get("step"))
            if tag != last:
                last = tag
                log(f"    [http] {status}" + (f" {pr.get('step')}/{pr.get('total')}" if pr.get("total") else ""))
            if status == "done":
                break
            if status == "failed":
                err = str(st.get("error") or "فشل بدون سبب")
                raise TechnicalError(f"الصندوق فشل: {err}", "oom" if OOM_MARK in err else "model_failed")
            if status == "cancelled":
                raise TechnicalError("الصندوق ألغى المهمة", "model_failed")
            left = deadline - time.time()
            if left <= 0:
                raise TechnicalError(f"الصندوق تجاوز المهلة ({timeout}ث)", "timeout")
            time.sleep(max(0.0, min(HTTP_POLL_SEC, left)))
        resp = _engine_call(sess, "GET", base, f"/jobs/{jid}/result", stream=True)
        got, cap = 0, MAX_DOWNLOAD_MB * 1024 * 1024
        try:
            with open(raw, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    got += len(chunk)
                    if got > cap:
                        raise TechnicalError("فيديو الصندوق أكبر من الحد المسموح", "bad_output")
                    f.write(chunk)
        except TechnicalError:
            raise
        except Exception:
            raise TechnicalError("انقطع تنزيل الفيديو من الصندوق", "connection") from None
        finally:
            resp.close()
        if got == 0:
            raise TechnicalError("الصندوق رجّع فيديو فاضي", "bad_output")
    finally:
        if jid:
            try:
                _engine_call(sess, "DELETE", base, f"/jobs/{jid}", timeout=5)
            except Exception:
                pass                               # تنظيف بقدر الإمكان
        sess.close()


def _clean_api(raw) -> dict:
    try:
        return motion_api.validate_spec(raw)
    except motion_api.ApiMotionError as e:
        raise MotionError(str(e)) from None


def est_cost(m: dict, seconds: float) -> float | None:
    """تقدير سعر لقطة بالدولار: المحلي (أمر/صندوق) = 0، والـ API = المدة المحسوبة × سعر الثانية (None لو السعر مجهول)."""
    if m.get("kind", "command") != "api":
        return 0.0
    try:
        return motion_api.estimate_cost(m["api"], seconds)
    except Exception:
        return None


def _over_budget(stem: str, m: dict, dur_ms: int) -> str | None:
    """رسالة لو هالمحاولة بتتجاوز سقف إنفاق التحريك بالـ API لهالسيناريو، وإلا None."""
    if m.get("kind", "command") != "api":
        return None
    est = est_cost(m, dur_ms / 1000) or 0.0
    cap = float(getattr(config, "MOTION_API_CAP_USD", 15.0))
    spent = production_log.spent(stem, "motion")
    if spent + est > cap + 1e-9:
        return f"وصلت سقف إنفاق التحريك بالـ API (${cap:g}) لهالسيناريو — صرفت ${spent:.2f} وهالمحاولة ${est:.2f}"
    return None


def _run_api(m: dict, img: Path | None, prompt: str, seconds: float, raw: Path, timeout: int, log, **extra) -> dict:
    """extra: end_image / refs / negative (ثبات الشخصية) — motion_api.run_job بيبعت بس اللي النموذج بياخده."""
    if img is None:
        raise MotionError("تحريك الـ API بدّه صورة معتمدة")
    try:
        return motion_api.run_job(m["api"], img, prompt, seconds, raw, timeout_sec=min(timeout, 1200), log=log, **extra)
    except motion_api.ApiMotionError as e:
        raise TechnicalError(str(e), "api") from None


_EN_DESC = {
    "close": "Slow push-in on the product while soft light drifts across its surface",
    "hand_product": "A hand slowly lifts the product and turns it slightly toward the camera",
    "medium": "Subtle natural motion of the person (breathing, slight head movement) with a nearly static camera",
    "wide": "Slow forward camera push with calm ambient motion",
}


def _preset_desc(shot: dict, model: dict | None) -> str:
    """كلام الكاميرا لوصفة اللقطة حسب عائلة الموديل (+ جملة «الكاميرا والعدسة» لو المالك اختارها). فاضي لو ما في وصفة."""
    p = motion_presets.of_shot(shot)
    if not p:
        return ""
    text = motion_presets.recipe_text(p, motion_presets.family_of(model))
    look = motion_presets.look_text((shot.get("camera_preset") or {}).get("look"))
    return f"{text}. {look}" if text and look else text


def build_prompt_en(shot: dict, character: dict | None, duration_ms: int, country: str = "", model: dict | None = None) -> str:
    """برومبت إنجليزي ثابت للـ API والصناديق (النماذج أفهم للإنجليزي). وصف الحركة: لو المالك كتبه بحروف لاتينية بناخده،
    وإلا بنستخدم الوصف الإنجليزي الافتراضي لنوع اللقطة. بدون أي نص عربي (ما بيتفهم) ولا بيانات حساسة.
    لقطات الوجه: بطاقة هوية الشخصية الإنجليزية (identity.py) عشان الوجه ما يميل لملامح شرق آسيا."""
    custom = _preset_desc(shot, model) or (shot.get("api_desc_en") or "").strip()
    if not custom:
        d = (shot.get("motion_desc") or "").strip()
        letters = [c for c in d if c.isalpha()]
        if letters and sum(c.isascii() for c in letters) / len(letters) >= 0.8:
            custom = d
    desc = custom or _EN_DESC.get(shot.get("type"), "Calm natural motion")
    if not custom and _CAMERA_RX.search(shot.get("motion_desc") or "") and "camera" not in desc.lower():
        desc += ", with a smooth camera move"
    who = ""
    if character and shot.get("type") != "hand_product":
        import identity
        who = (f" Keep the same person in every frame: {identity.text_of(character, country)}. "
               "Identical face, hair and clothing; the face must not change.")
    text = (f"Animate the reference image for {duration_ms / 1000:.1f} seconds. {desc.rstrip('.')}.{who} "
            "Keep the exact composition, product, label and colors of the image; never change the product packaging or its text. "
            "Realistic natural motion, steady cinematic camera, soft consistent lighting. "
            "No on-screen text, no logos, no flicker, no distortion, no extra fingers, no scene cuts.")
    return text[:1500]


def estimate_script(script_path, model_id: str | None = None) -> dict:
    """تقدير تكلفة تحريك كل اللقطات الباقية قبل ما ننفّق: لكل لقطة الموديل الأول بالترتيب (أو الموديل المحدّد)."""
    stem = Path(script_path).stem
    tl = _load(stem)
    models = load_models()
    shots, total, unknown = [], 0.0, 0
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if sh.get("motion_candidates") or not (sh.get("image") or {}).get("chosen"):
                continue
            dur = (sh["end_ms"] - sh["start_ms"]) / 1000
            rk = rank_models(sh, models, talking=bool(sh.get("talking")))
            pick = next((r for r in rk["ranked"] if not model_id or r["model"]["id"] == model_id), None)
            if not pick:
                shots.append({"id": sh["id"], "model": None, "cost_usd": None, "note": "ما في موديل مناسب"})
                continue
            c = pick["est_cost_usd"]
            if c is None:
                unknown += 1
            else:
                total += c
            shots.append({"id": sh["id"], "model": pick["model"]["name"], "duration_s": round(dur, 1), "cost_usd": c,
                          "path": _path_of(pick["model"])})
    cap = float(getattr(config, "MOTION_API_CAP_USD", 15.0))
    spent = production_log.spent(stem, "motion")
    return {"shots": shots, "total_usd": round(total, 2), "unknown_prices": unknown, "cap_usd": cap,
            "spent_usd": round(spent, 2), "over_cap": spent + total > cap + 1e-9}


def probe(model_id: str) -> dict:
    """فحص صندوق نموذج: شغّال؟ محمّل؟ في طابور؟ الكرت مشغول؟ بيرجّع {ok, backend, loaded, queued, running, gpu_busy}
    أو {ok: False, reason} بسبب عربي. ما بيرمي على خطأ اتصال."""
    m = next((x for x in load_models() if x["id"] == model_id), None)
    if not m:
        raise MotionError("الموديل غير موجود")
    if m.get("kind", "command") != "http":
        raise MotionError("هاد الموديل بأمر محلي — الفحص للصناديق (http) بس")
    cfg = m.get("http") or {}
    try:
        base = validate_engine_url(cfg.get("url"))
    except MotionError as e:
        return {"ok": False, "reason": str(e)}
    sess = _engine_session(_engine_token(cfg))
    try:
        try:
            h = _engine_call(sess, "GET", base, "/health", timeout=5).json()
        except TechnicalError as e:
            return {"ok": False, "reason": str(e)}
        except Exception:
            return {"ok": False, "reason": "رد الصندوق غير مفهوم"}
        try:
            _engine_call(sess, "GET", base, "/jobs/probe-token", timeout=5)      # 401 لو التوكن غلط؛ 404 يعني التوكن سليم
        except TechnicalError as e:
            if e.reason != "missing":
                return {"ok": False, "reason": str(e)}
        if not isinstance(h, dict) or not h.get("ok"):
            return {"ok": False, "reason": "الصندوق رد لكن مش بحالة سليمة"}
        mode = cfg.get("mode") or "i2v"
        if h.get("tasks") and mode not in h["tasks"]:
            return {"ok": False, "reason": f"الصندوق ما بيدعم الوضع {mode} (بيدعم: {', '.join(h['tasks'])})"}
        want = cfg.get("model")
        if want:                                       # الصندوق العام: النموذج لازم يكون موجود وسليم وبيدعم الوضع
            if not h.get("api"):
                return {"ok": False, "reason": "هاد صندوق بنموذج ثابت (ltx/wan) — اسم النموذج بيشتغل مع الصندوق العام بس"}
            try:
                listing = _engine_call(sess, "GET", base, "/models", timeout=8).json()
            except TechnicalError as e:
                return {"ok": False, "reason": str(e)}
            except Exception:
                return {"ok": False, "reason": "رد قائمة نماذج الصندوق غير مفهوم"}
            found = next((x for x in (listing.get("models") or []) if isinstance(x, dict) and x.get("name") == want), None)
            if not found:
                return {"ok": False, "reason": f"النموذج «{want}» مش موجود بمجلد أوزان الصندوق"}
            if not found.get("ok"):
                return {"ok": False, "reason": f"النموذج «{want}» مرفوض: {found.get('reason') or 'غير صالح'}"}
            if mode not in (found.get("tasks") or []):
                return {"ok": False, "reason": f"النموذج «{want}» ما بيدعم الوضع {mode} (بيدعم: {'، '.join(found.get('tasks') or [])})"}
        return {"ok": True, "backend": h.get("backend"), "loaded": bool(h.get("loaded")), "queued": int(h.get("queued") or 0),
                "running": int(h.get("running") or 0), "gpu_busy": bool(h.get("gpu_busy")), "url": base,
                "loaded_model": h.get("loaded_model"), "gpu": h.get("gpu") if isinstance(h.get("gpu"), dict) else None}
    finally:
        sess.close()


def _path_of(m: dict) -> str:
    return {"http": "http", "api": "api"}.get(m.get("kind", "command"), "command")


def _log_attempt(stem: str, shot_id: str, m: dict, ok: bool, seconds: float, error=None, cost_usd=None) -> None:
    production_log.record("motion", "ok" if ok else "failed", script_stem=stem, shot_id=shot_id, model_id=m["id"],
                          model_name=m.get("name"), path=_path_of(m), seconds=seconds, error=error, cost_usd=cost_usd)


def _produce(m: dict, *, img: Path, prompt: str, pf: Path, dur_ms: int, w: int, h: int, raw: Path, stem: str, sh: dict,
             out_dir: Path, talking: bool, log, prompt_en: str = "", negative: str = "", end_image: Path | None = None,
             refs: dict | None = None) -> tuple[Path, dict, bool]:
    """موديل واحد، محاولة واحدة: تشغيل ← ضبط المدة ← (مزامنة شفاه). أي فشل تقني بيطلع TechnicalError.
    negative/end_image/refs: ثبات الشخصية للقطات الوجه بس (فاضيين لغيرها). الأوامر المحلية بتضل بالبرومبت العربي (المالك ضابطها)."""
    timeout = int(getattr(config, "MOTION_TIMEOUT_SEC", 3600))
    api_info: dict = {}
    if m.get("kind", "command") == "api":
        api_info = _run_api(m, img, prompt_en or prompt, dur_ms / 1000, raw, timeout, log, negative=negative,
                            end_image=end_image, refs=refs)
    elif m.get("kind", "command") == "http":
        _run_http(m, img, prompt_en or prompt, dur_ms / 1000, w, h, raw, timeout, log,
                  negative=f"{HTTP_NEGATIVE}, {negative}" if negative else "")
    else:
        cmd = _fill(m["command"], {"image": img, "prompt_file": pf, "prompt": prompt, "seconds": f"{dur_ms / 1000:.3f}",
                                   "width": w, "height": h, "out": raw})
        _run_cmd(cmd, timeout, log)
    if not raw.exists():
        raise TechnicalError("الموديل ما كتب ملف الخرج", "bad_output")
    final = raw.with_name(raw.name.replace("_raw", ""))
    fit = fit_duration(raw, final, dur_ms, smooth=_is_free(stem))
    if api_info:
        fit["cost_usd"] = api_info.get("cost_usd")
        fit["billed_sec"] = api_info.get("billed_sec")
    lip = False
    if talking:
        final, lip = _lipsync(stem, sh, m, final, out_dir, log)
    return final, fit, lip


def _cleanup_attempt(raw: Path) -> None:
    base = raw.name[:-len("_raw.mp4")] if raw.name.endswith("_raw.mp4") else raw.stem
    for suffix in ("_raw.mp4", ".mp4", "_lip.mp4", "_lip_fit.mp4"):
        (raw.parent / f"{base}{suffix}").unlink(missing_ok=True)


def _end_frame_ok(sh: dict) -> bool:
    """صورة النهاية = صورة البداية: بتنفع لحركة خفيفة بمكانها، وبتتعارض مع حركة كاميرا (تقريب/دفع/دوران…)."""
    if not getattr(config, "MOTION_END_FRAME", True):
        return False
    mv = motion_presets.camera_move_of(sh)                    # وصفة سينمائية: هي اللي بتقرر
    return not (_CAMERA_MOVE_RX.search(sh.get("motion_desc") or "") if mv is None else mv)


def _identity_inputs(sh: dict, ch: dict | None, img: Path, face_shot: bool) -> dict:
    """مدخلات ثبات الشخصية للقطة وجه: ممنوعات الهوية، صورة النهاية، وصور الشخصية (للموديل المرجعي). فاضية لغير لقطات الوجه."""
    if not face_shot or not ch:
        return {"negative": "", "end_image": None, "refs": None}
    import characters
    import identity
    refs = {}
    for view in motion_api.REF_VIEWS:
        p = characters.sheet_path(ch["id"], view)
        if p:
            refs[view] = p
    return {"negative": identity.negative(ch), "end_image": img if _end_frame_ok(sh) else None, "refs": refs}


def _check_face(ch: dict, video: Path, stem: str, shot_id: str, cand: dict, check=None) -> dict:
    """فحص وجه الفيديو (3 لقطات) + تسجيل النتيجة الحاسمة لموديل التحريك. أي عطل تقني = «غير مقاس» (ما بيوقف الإنتاج)."""
    try:
        r = (check or facecheck.check_video)(facecheck.character_refs(ch["id"]), video)
    except facecheck.FaceCheckError as e:
        return {"status": "unchecked", "similarity": None, "note": str(e)}
    except Exception as e:                                       # noqa: BLE001 — فحص تحسيني: ما بنكسر الإنتاج لأي سبب
        return {"status": "unchecked", "similarity": None, "note": f"تعذّر فحص الوجه ({type(e).__name__})"}
    if r.get("status") in ("pass", "fail"):
        production_log.record("face_video", "ok" if r["status"] == "pass" else "failed", script_stem=stem, shot_id=shot_id,
                              model_id=cand["id"], model_name=cand.get("name"), path=_path_of(cand), score=r.get("similarity"))
    return {**r, "at": _now()}


def _library_lipsync() -> dict | None:
    """نموذج مزامنة الشفاه الافتراضي من مكتبة النماذج (مفعّل ورخصته تسمح)، أو None. بيخدم أي موديل تحريك ما إله أمر مزامنة بسجله."""
    try:
        import model_library
        return model_library.pick("lipsync").model
    except Exception:                                # noqa: BLE001 — مكتبة تالفة ما بتوقف الترتيب: بنكمّل بدونها
        return None


def _pinned_default() -> str | None:
    try:
        import model_library
        return model_library.task_config("motion")["default"]
    except Exception:                                    # noqa: BLE001 — مكتبة تالفة: الترتيب التلقائي المعتاد
        return None


def _primary(ranked: list[dict], pin: str | None) -> dict:
    """الموديل الأساسي: المثبّت لو هو بالمرتّبين (يعني مناسب للقطة وجاهز)، وإلا الأعلى ترتيباً."""
    return next((r["model"] for r in ranked if r["model"]["id"] == pin), None) or ranked[0]["model"]


def run_shot(script_path, shot_id: str, model_id: str | None = None, n: int = 1, log=print, fallback: bool = True,
             face_check=None) -> dict:
    path = Path(script_path)
    stem = path.stem
    ok, why = studio_state.can_start(stem, 9)
    if not ok:
        raise MotionError(why)
    tl = _load(stem)
    sc, sh = _shot(tl, shot_id)
    rel = _final_image(sh)
    img = None
    if rel:
        from image_studio import abs_of as img_abs
        img = img_abs(stem, rel)
    if not img:
        raise MotionError(f"لقطة {shot_id}: ما في صورة معتمدة")
    dur_ms = sh["end_ms"] - sh["start_ms"]
    talking = bool(sh.get("talking"))
    models = load_models()
    rk = rank_models(sh, models, talking=talking)
    if model_id:
        m = next((x for x in models if x["id"] == model_id), None)
        if not m:
            raise MotionError("الموديل غير موجود")
        if any(e["model"]["id"] == model_id for e in rk["excluded"]):
            reason = next(e["reason"] for e in rk["excluded"] if e["model"]["id"] == model_id)
            raise MotionError(f"الموديل «{m['name']}» ما بيناسب اللقطة: {reason}")
    elif rk["ranked"]:
        m = _primary(rk["ranked"], _pinned_default())      # الموديل المثبّت بمكتبة النماذج أول، لو مناسب للقطة وجاهز
    else:
        raise MotionError("ما في موديل مناسب: " + "؛ ".join(f"{e['model']['name']}: {e['reason']}" for e in rk["excluded"]) if rk["excluded"] else "سجل الموديلات فاضي")
    # سلسلة البدائل: الأساسي أول، وبعده المرتّبين حسب الأفضلية (كلهم مناسبين للقطة أصلاً)
    chain = [m] + [r["model"] for r in rk["ranked"] if r["model"]["id"] != m["id"]]

    import characters
    cur = characters.chosen(stem)
    ch = characters.get(cur["character_id"]) if cur else None
    country = (cur or {}).get("country") or ""
    if not sh.get("motion_desc"):
        sh["motion_desc"] = default_motion_desc(sh)
    face_shot = bool(ch) and sh.get("type") != "hand_product"
    if face_shot:                                    # بطاقة الهوية الإنجليزية (بتنترجم وبتنخزّن مرة وحدة؛ فشلها ما بيوقف)
        try:
            import identity
            identity.ensure(ch["id"], country)
            ch = characters.get(ch["id"]) or ch
        except Exception:                            # noqa: BLE001
            pass
    prompt = build_prompt(sh, sc, ch, dur_ms)
    sh["motion_prompt"] = prompt
    prompt_en = build_prompt_en(sh, ch, dur_ms, country)
    ident = _identity_inputs(sh, ch, img, face_shot)
    timeline.save(stem, tl)

    studio_state.set_state(stem, 9, "running", f"تحريك {shot_id} بـ {m['name']}")
    out_dir = clips_dir(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    pf = out_dir / f"{shot_id}_prompt.txt"
    pf.write_text(prompt, encoding="utf-8")
    from PIL import Image
    with Image.open(img) as im:
        w, h = im.size
    made, used, fallbacks = [], m, 0
    dead: set[str] = set()                           # موديلات فشلت تقنياً بهالتشغيلة: ما بنعيد عليها لباقي الخيارات
    max_attempts = MAX_ATTEMPTS if fallback else 1
    for k in range(n):
        stamp = int(time.time() * 1000)
        failures: list[tuple[dict, TechnicalError]] = []
        done = None
        attempt = 0
        for cand in chain:
            if cand["id"] in dead:
                continue
            if attempt >= max_attempts:
                break
            attempt += 1
            if attempt > 1 or failures:
                studio_state.set_state(stem, 9, "running", f"تحريك {shot_id} بـ {cand['name']} (بديل)")
                log(f"  [↻] {shot_id}: بجرّب البديل «{cand['name']}»")
            raw = out_dir / f"{shot_id}_{stamp}_{k}{'' if attempt == 1 else f'_b{attempt}'}_raw.mp4"
            over = _over_budget(stem, cand, dur_ms)
            if over:                                         # سقف الإنفاق: ما بنصرف، وبننزل للتالي (غالباً المحلي المجاني)
                dead.add(cand["id"])
                failures.append((cand, TechnicalError(over, "budget")))
                log(f"  [$] {shot_id}: «{cand['name']}» — {over}")
                continue
            t0 = time.time()
            try:
                final, fit, lip = _produce(cand, img=img, prompt=prompt, pf=pf, dur_ms=dur_ms, w=w, h=h, raw=raw, stem=stem,
                                           sh=sh, out_dir=out_dir, talking=talking, log=log,
                                           prompt_en=build_prompt_en(sh, ch, dur_ms, country, model=cand), **ident)
            except TechnicalError as e:
                _log_attempt(stem, shot_id, cand, False, time.time() - t0, str(e))
                dead.add(cand["id"])
                failures.append((cand, e))
                _cleanup_attempt(raw)
                log(f"  [!] {shot_id}: «{cand['name']}» فشل: {e}")
                continue
            except MotionError as e:                 # خطأ مالك/حالة: ما في بديل
                _log_attempt(stem, shot_id, cand, False, time.time() - t0, str(e))
                _cleanup_attempt(raw)
                studio_state.set_state(stem, 9, "failed", f"{shot_id}: {e}")
                raise
            finally:
                raw.unlink(missing_ok=True)
            took = time.time() - t0
            _log_attempt(stem, shot_id, cand, True, took, cost_usd=fit.get("cost_usd"))
            done = (cand, final, fit, lip, took)
            break
        if done is None:
            if len(failures) == 1:
                msg = str(failures[0][1])
                err: MotionError = failures[0][1]
            else:
                msg = "كل المحاولات فشلت — " + "؛ ".join(f"«{c['name']}»: {e}" for c, e in failures)
                err = MotionError(msg)
            studio_state.set_state(stem, 9, "failed", f"{shot_id}: {msg}")
            raise err
        cand, final, fit, lip, took = done
        used = cand
        tl = _load(stem)
        _sc2, sh2 = _shot(tl, shot_id)
        rec = {"clip": _rel(stem, final), "model_id": cand["id"], "model_name": cand["name"], "path": _path_of(cand),
               "duration_ms": dur_ms, "fit": fit["how"], "source_sec": fit["source_sec"], "lipsync": lip,
               "took_sec": round(took, 1), "at": _now()}
        if fit.get("cost_usd") is not None:
            rec["cost_usd"] = fit["cost_usd"]
        if face_shot:
            rec["face"] = _check_face(ch, final, stem, shot_id, cand, face_check)
            if rec["face"]["status"] == "fail":
                log(f"  [!] {shot_id}: الوجه تغيّر بفيديو «{cand['name']}» — {rec['face'].get('note', '')}")
        skipped = [c for c in chain if c["id"] in dead and c["id"] != cand["id"]]      # موديلات فشلت (هلأ أو بخيار سابق) فنزلنا عنها
        if skipped:
            rec["fallback_from"] = skipped[0]["id"]
            fallbacks += 1
        sh2.setdefault("motion_candidates", []).append(rec)
        timeline.save(stem, tl)
        if sh2.get("camera_preset"):                                  # أول فيديو بهالوصفة = مثالها بمكتبة الحركات (من شغلنا)
            try:
                motion_presets.remember_example(sh2["camera_preset"]["id"], final, {"model": cand["name"], "shot": shot_id, "stem": stem})
            except Exception:                                         # noqa: BLE001 — المثال تحسين مش شرط
                pass
        made.append(final.name)
        log(f"  [✓] {shot_id} خيار {k + 1}/{n} ({fit['how']})" + (f" — بديل عن «{skipped[0]['name']}»" if skipped else ""))
    studio_state.set_state(stem, 9, "awaiting_choice", "بانتظار اختيارك لحركة كل لقطة")
    return {"shot": shot_id, "model": used["id"], "made": made, "fallbacks": fallbacks}


def _run_library_lipsync(lib: dict, video: Path, audio: Path, out: Path, stem: str, sh: dict, log) -> None:
    """مزامنة بنموذج المكتبة. أي فشل = MotionError بسببه (بلا بديل: تغيير نموذج المزامنة بنص الشغلة بيخرّب الناتج، والقرار للمالك)."""
    import model_run
    req = model_run.RunRequest(task="lipsync", out=out, video=video, audio=audio, script_stem=stem, shot_id=sh["id"], log=log)
    try:
        model_run.run(lib, req)
    except model_run.RunError as e:
        raise MotionError(f"مزامنة الشفاه بنموذج «{lib['name']}» فشلت: {e}") from None


def _lipsync(stem: str, sh: dict, m: dict, video: Path, out_dir: Path, log) -> tuple[Path, bool]:
    lib = None
    if not m.get("lipsync_command"):
        lib = _library_lipsync()                    # الأمر الخاص بالموديل أولى؛ وإلا الافتراضي من مكتبة النماذج
        if lib is None:
            raise MotionError(f"الموديل «{m['name']}» ما إله أمر مزامنة شفاه، وما في نموذج مزامنة افتراضي بمكتبة النماذج")
    import voice_studio
    man = voice_studio.load_manifest(stem)
    aud = ((man or {}).get("combined") or {}).get("path")
    src = (Path(config.LIBRARY_DIR) / aud) if aud else None
    if not src or not src.exists():
        raise MotionError("ما في صوت مدموج للمزامنة")
    seg = out_dir / f"{sh['id']}_voice.wav"
    r = subprocess.run(["ffmpeg", "-y", "-ss", f"{sh['start_ms'] / 1000:.3f}", "-t", f"{(sh['end_ms'] - sh['start_ms']) / 1000:.3f}",
                        "-i", str(src), str(seg)], capture_output=True)
    if r.returncode != 0:
        raise MotionError("فشل استخراج مقطع الصوت للمزامنة")
    out = video.with_name(video.stem + "_lip.mp4")
    if lib is not None:
        _run_library_lipsync(lib, video, seg, out, stem, sh, log)
    else:
        _run_cmd(_fill(m["lipsync_command"], {"video": video, "audio": seg, "out": out}),
                 int(getattr(config, "MOTION_TIMEOUT_SEC", 3600)), log)
    if not out.exists():
        raise TechnicalError("موديل المزامنة ما كتب الخرج", "bad_output")
    fit_duration(out, out.with_name(out.stem + "_fit.mp4"), sh["end_ms"] - sh["start_ms"])
    return out.with_name(out.stem + "_fit.mp4"), True


def run_all(script_path, model_id: str | None = None, n: int = 1, log=print, fallback: bool = True) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    todo = [s["id"] for sc in tl["scenes"] for s in sc["shots"] if not s.get("motion_candidates")]
    done, failed = [], []
    for sid in todo:
        try:
            run_shot(script_path, sid, model_id, n, log, fallback)
            done.append(sid)
        except MotionError as e:
            failed.append({"shot": sid, "error": str(e)})
            log(f"  [!] {sid}: {e}")
    return {"done": done, "failed": failed}


# ── فيديو من المالك (بدل التوليد) ────────────────────────────────────────
def add_upload(script_path, shot_id: str, raw: Path) -> dict:
    """فيديو من المالك للقطة كمرشّح model_id=upload — بنفس شرط التحريك (المحطة 9 مسموح تبدأ). مدته بتتظبط على مدة اللقطة بالضبط:
    قص لو أطول، تمديد لو أقصر بحدود 15%، وإلا رفض برسالة عربية. الاختيار بعدها بـ choose(clip). بيرجّع اللقطة."""
    path = Path(script_path)
    stem = path.stem
    ok, why = studio_state.can_start(stem, 9)
    if not ok:
        raise MotionError(why)
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    dur_ms = sh["end_ms"] - sh["start_ms"]
    out_dir = clips_dir(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{shot_id}_{int(time.time() * 1000)}_up.mp4"
    try:
        fit = fit_duration(Path(raw), final, dur_ms, smooth=tl.get("mode") == "free")
    except MotionError as e:
        final.unlink(missing_ok=True)
        raise MotionError(str(e).replace("الموديل أنتج", "الفيديو اللي رفعته مدته").replace("الموديل ما رجّع فيديو صالح", "الملف مش فيديو صالح"))
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    sh.setdefault("motion_candidates", []).append({
        "clip": _rel(stem, final), "model_id": "upload", "model_name": "رفع يدوي", "path": "upload", "duration_ms": dur_ms,
        "fit": fit["how"], "source_sec": fit["source_sec"], "lipsync": False, "took_sec": 0.0, "at": _now()})
    timeline.save(stem, tl)
    try:
        studio_state.set_state(stem, 9, "awaiting_choice", "بانتظار اختيارك لحركة كل لقطة")
    except studio_state.StationBlocked as e:
        raise MotionError(str(e))
    return sh


# ── الاختيار والاعتماد ──────────────────────────────────────────────────
def choose(script_path, shot_id: str, clip: str) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    cand = next((c for c in sh.get("motion_candidates", []) if c["clip"] == clip), None)
    if not cand:
        raise MotionError("الخيار مش من مرشّحات هاللقطة")
    dur = sh["end_ms"] - sh["start_ms"]
    sh["motion"] = {"model_id": cand["model_id"], "prompt": sh.get("motion_prompt") or "", "duration_ms": dur,
                    "clip": clip, "lipsync": cand.get("lipsync", False)}
    timeline.save(stem, tl)                      # validate بيرفض لو مدة الحركة ≠ مدة اللقطة
    if studio_state.state_of(stem, 9) == "approved":
        studio_state.set_state(stem, 9, "awaiting_choice", "تغيّرت حركة لقطة")
    return sh


def problems(tl: dict) -> list[dict]:
    out = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            mo = sh.get("motion")
            dur = sh["end_ms"] - sh["start_ms"]
            if not mo or not mo.get("clip"):
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: ما في حركة مختارة"})
            elif mo.get("duration_ms") != dur:
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: مدة الحركة ≠ مدة اللقطة"})
            elif sh.get("talking") and not mo.get("lipsync"):
                out.append({"shot": sh["id"], "message": f"لقطة {sh['id']}: كلام على الكاميرا بلا مزامنة شفاه"})
    return out


def approve(script_path) -> dict:
    stem = Path(script_path).stem
    ok, why = studio_state.can_start(stem, 9)
    if not ok:
        raise MotionError(why)
    tl = _load(stem)
    probs = problems(tl)
    if probs:
        raise MotionError("؛ ".join(p["message"] for p in probs[:4]))
    studio_state.set_state(stem, 9, "approved", "حركة كل لقطة معتمدة بمدتها الدقيقة")
    return {"approved": True, "shots": sum(len(s["shots"]) for s in tl["scenes"])}


def main() -> None:
    import job_signals
    job_signals.install()                       # إلغاء المهمة على لينكس = SystemExit فيشتغل finally وبنبعت DELETE للصندوق
    ap = argparse.ArgumentParser(description="تحريك اللقطات بموديل محلي")
    ap.add_argument("action", choices=["run"])
    ap.add_argument("script")
    ap.add_argument("--shot")
    ap.add_argument("--model")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--no-fallback", action="store_true", help="بدون بديل تلقائي لو الموديل فشل")
    a = ap.parse_args()
    try:
        r = (run_shot(a.script, a.shot, a.model, a.n, fallback=not a.no_fallback) if a.shot
             else run_all(a.script, a.model, a.n, fallback=not a.no_fallback))
    except MotionError as e:
        sys.exit(f"[!] {e}")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if isinstance(r, dict) and r.get("failed"):
        sys.exit("[!] بعض اللقطات فشلت — شوف السجل")


if __name__ == "__main__":
    main()
