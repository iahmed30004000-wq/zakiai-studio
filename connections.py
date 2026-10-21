"""
الاتصالات: مزوّد + مفتاح واحد، والموديلات بتنجلب من المزوّد نفسه.

ليش هيك: المفتاح بينحفظ مرة وحدة لا مرة بكل مهمة، وقائمة الموديلات بتضل
محدّثة لأنها جاية من الـ API مش محفورة بالكود. كل مهمة بس بتشير لاتصال
وموديل منه — أو بتتركه "تلقائي" فالنظام بيختار الأنسب.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

import config
import settings_io
from llm import PROVIDER_PRESETS


class ConnectionError_(Exception):
    """فشل بالاتصال أو بجلب الموديلات — برسالة جاهزة للعرض."""


def _load() -> dict:
    return settings_io.load()


def _save(data: dict) -> None:
    settings_io.save(data)


def all_connections() -> dict:
    return _load().get("CONNECTIONS") or {}


def get(conn_id: str) -> dict | None:
    return all_connections().get(conn_id)


# ── جلب الموديلات من المزوّد ─────────────────────────────────────────────


def fetch_models(provider: str, api_key: str, base_url: str = "") -> list[dict]:
    """يسأل المزوّد شو الموديلات المتاحة لهالمفتاح. بيرجع [{id, label}]."""
    preset = PROVIDER_PRESETS.get(provider)
    if not preset:
        raise ConnectionError_(f"مزوّد غير معروف: {provider}")

    url = (base_url or preset.get("base_url") or "").rstrip("/")

    try:
        if preset["kind"] == "anthropic":
            r = requests.get(
                f"{url or 'https://api.anthropic.com'}/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                params={"limit": 100}, timeout=45,
            )
        else:
            if not url:
                raise ConnectionError_("لازم base_url لهالمزوّد")
            r = requests.get(f"{url}/models",
                             headers={"Authorization": f"Bearer {api_key}"}, timeout=45)
    except requests.RequestException as e:
        raise ConnectionError_(f"ما قدرت أوصل للمزوّد: {e}")

    if r.status_code == 401:
        raise ConnectionError_("المفتاح مرفوض — تأكد منه")
    if r.status_code == 404:
        raise ConnectionError_(
            "المزوّد ما بيدعم عرض الموديلات — اكتب اسم الموديل يدوياً"
        )
    if r.status_code != 200:
        raise ConnectionError_(f"المزوّد رجّع {r.status_code}: {r.text[:180]}")

    try:
        # بعض المزوّدين (Ollama لما يكون فاضي) بيرجّعوا data: null مش []
        raw = r.json().get("data") or []
    except ValueError:
        # غالباً الـ base_url غلط فالطلب راح لصفحة ويب بدل الـ API
        body = r.text.lstrip()[:80].lower()
        if body.startswith(("<!doctype", "<html", "<?xml")):
            expected = preset.get("base_url") or "…/v1"
            raise ConnectionError_(
                f"العنوان رجّع صفحة ويب مش بيانات — غالباً base_url غلط.\n"
                f"    المستخدم: {url or '(فاضي)'}\n"
                f"    الصحيح لهالمزوّد: {expected}"
            )
        raise ConnectionError_(f"رد غير مفهوم من المزوّد: {r.text[:120]}")

    models = []
    for m in raw:
        mid = m.get("id") or m.get("name")
        if not mid:
            continue
        models.append({"id": mid, "label": m.get("display_name") or mid})
    if not models:
        raise ConnectionError_("المزوّد ما رجّع ولا موديل")
    return sorted(models, key=lambda m: m["id"])


def create(provider: str, api_key: str, label: str = "", base_url: str = "") -> dict:
    """ينشئ اتصال ويجلب موديلاته فوراً — الفشل بيمنع الحفظ."""
    if not api_key.strip():
        raise ConnectionError_("لازم مفتاح")

    models = fetch_models(provider, api_key.strip(), base_url)

    data = _load()
    conns = data.setdefault("CONNECTIONS", {})
    conn_id = f"c_{uuid.uuid4().hex[:8]}"
    conns[conn_id] = {
        "provider": provider,
        "label": label.strip() or PROVIDER_PRESETS[provider]["label"],
        "api_key": api_key.strip(),
        "base_url": (base_url or PROVIDER_PRESETS[provider].get("base_url", "")).rstrip("/"),
        "models": models,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(data)
    return {"id": conn_id, **conns[conn_id]}


def refresh(conn_id: str) -> dict:
    data = _load()
    conn = (data.get("CONNECTIONS") or {}).get(conn_id)
    if not conn:
        raise ConnectionError_("اتصال غير موجود")
    conn["models"] = fetch_models(conn["provider"], conn["api_key"], conn.get("base_url", ""))
    conn["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(data)
    return {"id": conn_id, **conn}


def delete(conn_id: str) -> None:
    data = _load()
    conns = data.get("CONNECTIONS") or {}
    conns.pop(conn_id, None)
    # فكّ أي مهمة كانت مربوطة فيه عشان ما تضل تشير لاتصال محذوف
    for task, entry in (data.get("TASKS") or {}).items():
        if entry.get("connection") == conn_id:
            entry.pop("connection", None)
            entry.pop("model", None)
    _save(data)


def public_view() -> list[dict]:
    """للواجهة — بدون المفاتيح."""
    out = []
    for cid, c in all_connections().items():
        key = c.get("api_key", "")
        out.append({
            "id": cid,
            "provider": c["provider"],
            "label": c["label"],
            "base_url": c.get("base_url", ""),
            "key_masked": f"{key[:10]}…{key[-4:]}" if len(key) > 18 else "مضبوط",
            "models": c.get("models", []),
            "model_count": len(c.get("models", [])),
            "fetched_at": c.get("fetched_at"),
            "vision": PROVIDER_PRESETS.get(c["provider"], {}).get("vision", True),
        })
    return sorted(out, key=lambda c: c["label"])


# ── الاختيار التلقائي ────────────────────────────────────────────────────

# إشارات بأسماء الموديلات: الأقوى للمهام الإبداعية، الأرخص للمهام الآلية.
# الترتيب مهم — أول نمط بينطبق بيفوز.
STRONG_HINTS = ["opus", "gpt-5", "grok-4", "gemini-2.5-pro", "deepseek-reasoner",
                "qwen-max", "kimi-k2", "glm-4.6", "mistral-large", "-405b", "-70b"]
BALANCED_HINTS = ["sonnet", "gpt-5-mini", "gemini-2.5-flash", "deepseek-chat",
                  "qwen-plus", "grok-4-fast"]
CHEAP_HINTS = ["haiku", "mini", "flash", "turbo", "nano", "small", "-8b"]

# شو بتحتاج كل مهمة
TASK_PROFILE = {
    "analysis": {"tier": "balanced", "vision": True},
    "match":    {"tier": "balanced", "vision": False},
    "writer":   {"tier": "strong",   "vision": False},
    "reviewer": {"tier": "strong",   "vision": False},
    "parser":   {"tier": "cheap",    "vision": False},
    "importer": {"tier": "balanced", "vision": False},
    "shotplan": {"tier": "balanced", "vision": False},
    "translate": {"tier": "balanced", "vision": False},
}

# موديلات ما بتنفع للمهام هون مهما كان اسمها
EXCLUDE = ["embed", "whisper", "tts", "audio", "image", "vision-only",
           "moderation", "rerank", "guard"]


def _version_score(model_id: str) -> float:
    """
    رقم أكبر = نسخة أحدث. لازم لأن المزوّد بيرجّع كل الأجيال سوا،
    وبدون هالترجيح بيفوز الأقدم أبجدياً (sonnet-4-5 قبل sonnet-5).
    """
    import re
    mid = model_id.lower()
    # شيل ختم التاريخ (20250929) عشان ما ينقرأ كنسخة
    stripped = re.sub(r"[-_]\d{8}\b", "", mid)
    nums = re.findall(r"(?<![a-z0-9])(\d+)(?:[.-](\d+))?(?![a-z])", stripped)
    version = 0.0
    for major, minor in nums:
        try:
            v = float(f"{int(major)}.{int(minor)}") if minor else float(major)
        except ValueError:
            continue
        version = max(version, v)
    # الاسم بدون ختم تاريخ = مؤشّر متجدّد، بيفضّل على اللقطة المثبّتة
    if not re.search(r"[-_]\d{8}\b", mid):
        version += 0.05
    return version


def _rank(model_id: str, tier: str) -> tuple[int, float]:
    """
    (درجة المستوى، سالب النسخة) — الأقل بيفوز، فالنسخة الأحدث بتتقدّم
    ضمن نفس المستوى.
    """
    mid = model_id.lower()
    tiers = {"strong": STRONG_HINTS, "balanced": BALANCED_HINTS, "cheap": CHEAP_HINTS}
    ver = -_version_score(model_id)

    for i, h in enumerate(tiers[tier]):
        if h in mid:
            return (i, ver)
    # ما طابق المستوى المطلوب — جرّب المستويات التانية بعقوبة
    for other, pen in (("strong", 100), ("balanced", 200), ("cheap", 300)):
        if other == tier:
            continue
        for i, h in enumerate(tiers[other]):
            if h in mid:
                return (pen + i, ver)
    return (900, ver)


def auto_pick(task: str) -> dict | None:
    """يختار أنسب (اتصال، موديل) للمهمة من المحفوظ. None لو ما في شي صالح."""
    profile = TASK_PROFILE.get(task, {"tier": "balanced", "vision": False})
    best = None

    for cid, conn in all_connections().items():
        preset = PROVIDER_PRESETS.get(conn["provider"], {})
        if profile["vision"] and not preset.get("vision", True):
            continue                      # المهمة بدها رؤية والمزوّد ما بيدعمها
        for m in conn.get("models", []):
            mid = m["id"]
            if any(x in mid.lower() for x in EXCLUDE):
                continue
            score = _rank(mid, profile["tier"])
            if best is None or score < best["score"]:
                best = {"connection": cid, "model": mid, "score": score,
                        "provider": conn["provider"], "label": conn["label"]}
    return best
