"""
توليد الصور — طبقة مزوّدين موحّدة.

قاعدة ثابتة بهالمنظومة: **ممنوع أي كتابة داخل الصورة**. النص بينحط بالمونتاج،
والموديلات بتكتب حروف عربية مشوّهة لو تركناها. فكل برومبت بينضاف عليه منع صريح.

كل مزوّد بيرجّع صورة بشكل مختلف (بايتات مباشرة / base64 / رابط مؤقت) —
الطبقة بتوحّدهم لملف على القرص.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests

import config

IMAGE_PRESETS = {
    "openai": {
        "label": "OpenAI — GPT Image", "kind": "openai",
        "base_url": "https://api.openai.com/v1", "env_key": "OPENAI_API_KEY",
        "models": ["gpt-image-1", "dall-e-3"],
        "sizes": ["1024x1536", "1024x1024", "1536x1024"],
        "supports_refs": True,
        "note": "1024x1536 هو الأقرب للعمودي 9:16.",
    },
    "google": {
        "label": "Google — Imagen / Nano Banana", "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env_key": "GEMINI_API_KEY",
        "models": ["gemini-2.5-flash-image", "imagen-4.0-generate-001"],
        "sizes": ["9:16", "1:1", "16:9"],
        "supports_refs": True,
        "note": "Nano Banana = gemini-2.5-flash-image. بياخد نسبة مش أبعاد.",
    },
    "bfl": {
        "label": "Black Forest Labs — FLUX", "kind": "bfl",
        "base_url": "https://api.bfl.ai/v1", "env_key": "BFL_API_KEY",
        "models": ["flux-pro-1.1", "flux-dev"],
        "sizes": ["768x1344", "1024x1024"],
        "supports_refs": True,
        "note": "واقعية عالية. بيشتغل بنظام انتظار (polling).",
    },
    "replicate": {
        "label": "Replicate — بوابة موديلات", "kind": "replicate",
        "base_url": "https://api.replicate.com/v1", "env_key": "REPLICATE_API_TOKEN",
        "models": ["black-forest-labs/flux-1.1-pro", "stability-ai/sdxl"],
        "sizes": ["768x1344", "1024x1024"],
        "supports_refs": True,
        "note": "بيوصلك لأغلب الموديلات المفتوحة بمفتاح واحد.",
    },
    "unorouter": {
        "label": "UnoRouter — بوابة", "kind": "openai",
        "base_url": "https://api.unorouter.com/v1", "env_key": "UNOROUTER_API_KEY",
        "models": ["gpt-image-2", "gpt-image-1", "flux-pro-1.1", "gemini-2.5-flash-image"],
        "sizes": ["1024x1536", "1024x1024", "1536x1024"],
        # مُتحقَّق منه: بوابتهم بتدعم /images/generations بس مش /images/edits
        "supports_refs": False,
        "note": "توليد بس — ما بيدعم صور مرجعية. للشخصية الثابتة استخدم Google أو OpenAI مباشرة.",
    },
    "siliconflow": {
        "label": "SiliconFlow (صينية)", "kind": "openai",
        "base_url": "https://api.siliconflow.cn/v1", "env_key": "SILICONFLOW_API_KEY",
        "models": ["Kwai-Kolors/Kolors", "black-forest-labs/FLUX.1-schnell"],
        "sizes": ["768x1344", "1024x1024"],
        "supports_refs": True,
        "note": "رخيصة. Kolors قوي بالمشاهد الآسيوية والمنتجات.",
    },
}

# بينضاف لكل برومبت — بلا استثناء
NO_TEXT_RULE = (
    "ABSOLUTELY NO text, no letters, no words, no numbers, no captions, no subtitles, "
    "no watermarks, no logos with text, no signage, no product labels with readable text "
    "anywhere in the image. The frame must be completely free of any written characters."
)

STYLE_BASE = (
    "Vertical 9:16 mobile advertising photography, photorealistic, natural lighting, "
    "shallow depth of field, authentic unstaged feel, high detail."
)


class ImageError(Exception):
    """فشل توليد الصورة — برسالة جاهزة للعرض."""


def _settings() -> dict:
    import settings_io
    return settings_io.load()


def image_config(overrides: dict | None = None) -> dict:
    saved = _settings()
    entry = {**(saved.get("IMAGE") or {}), **{k: v for k, v in (overrides or {}).items() if v}}
    provider = entry.get("provider") or "openai"
    preset = IMAGE_PRESETS.get(provider, IMAGE_PRESETS["openai"])

    key = entry.get("api_key") or ""
    if not key and preset.get("env_key"):
        key = os.environ.get(preset["env_key"], "")

    return {
        "provider": provider,
        "kind": preset["kind"],
        "model": entry.get("model") or preset["models"][0],
        "size": entry.get("size") or preset["sizes"][0],
        "base_url": (entry.get("base_url") or preset["base_url"]).rstrip("/"),
        "api_key": key,
        "style": entry.get("style") or STYLE_BASE,
        "supports_refs": preset.get("supports_refs", True),
    }


def build_prompt(visual: str, cfg: dict, extra: str = "") -> str:
    """يركّب البرومبت النهائي: الوصف + الستايل + منع الكتابة."""
    parts = [visual.strip(), extra.strip(), cfg["style"].strip(), NO_TEXT_RULE]
    return " ".join(p for p in parts if p)


# ── المزوّدين ────────────────────────────────────────────────────────────


def _openai(cfg: dict, prompt: str, out: Path, refs: list[Path] | None = None) -> None:
    if refs:
        # مع مرجع: images/edits بيقبل صور أساس ويحافظ على شكلها
        files = []
        opened = []
        try:
            for i, rp in enumerate(refs):
                fh = rp.open("rb")
                opened.append(fh)
                files.append(("image[]", (rp.name, fh, f"image/{rp.suffix.lstrip('.')}")))
            r = requests.post(
                f"{cfg['base_url']}/images/edits",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                data={"model": cfg["model"], "prompt": prompt, "n": 1, "size": cfg["size"]},
                files=files, timeout=600,
            )
        finally:
            for fh in opened:
                fh.close()
    else:
        r = requests.post(f"{cfg['base_url']}/images/generations",
                          headers={"Authorization": f"Bearer {cfg['api_key']}"},
                          json={"model": cfg["model"], "prompt": prompt,
                                "n": 1, "size": cfg["size"]}, timeout=600)

    if r.status_code != 200:
        raise ImageError(f"{cfg['provider']} رجّع {r.status_code}: {r.text[:200]}")
    item = (r.json().get("data") or [{}])[0]
    if item.get("b64_json"):
        out.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        out.write_bytes(requests.get(item["url"], timeout=300).content)
    else:
        raise ImageError("المزوّد ما رجّع صورة")


def _gemini(cfg: dict, prompt: str, out: Path, refs: list[Path] | None = None) -> None:
    parts: list[dict] = []
    for rp in (refs or []):
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "jpeg": "image/jpeg", "webp": "image/webp"}[rp.suffix.lower().lstrip(".")]
        parts.append({"inline_data": {"mime_type": mime,
                                      "data": base64.b64encode(rp.read_bytes()).decode()}})
    parts.append({"text": prompt})

    url = f"{cfg['base_url']}/models/{cfg['model']}:generateContent"
    r = requests.post(url, params={"key": cfg["api_key"]},
                      json={"contents": [{"parts": parts}]}, timeout=600)
    if r.status_code != 200:
        raise ImageError(f"Google رجّع {r.status_code}: {r.text[:200]}")
    for cand in r.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
            if data:
                out.write_bytes(base64.b64decode(data))
                return
    raise ImageError("Google ما رجّع صورة — غالباً الموديل مش موديل صور")


def _bfl(cfg: dict, prompt: str, out: Path, refs: list[Path] | None = None) -> None:
    import time
    w, _, h = cfg["size"].partition("x")
    body = {"prompt": prompt, "width": int(w), "height": int(h or w)}
    if refs:
        # FLUX بياخد مرجع واحد بـ image_prompt
        body["image_prompt"] = base64.b64encode(refs[0].read_bytes()).decode()
    r = requests.post(f"{cfg['base_url']}/{cfg['model']}",
                      headers={"x-key": cfg["api_key"]}, json=body, timeout=120)
    if r.status_code not in (200, 202):
        raise ImageError(f"BFL رجّع {r.status_code}: {r.text[:200]}")
    poll_url = r.json().get("polling_url")
    if not poll_url:
        raise ImageError("BFL ما رجّع رابط متابعة")

    for _ in range(120):
        time.sleep(2)
        s = requests.get(poll_url, headers={"x-key": cfg["api_key"]}, timeout=60).json()
        status = s.get("status")
        if status == "Ready":
            img_url = (s.get("result") or {}).get("sample")
            out.write_bytes(requests.get(img_url, timeout=300).content)
            return
        if status in ("Error", "Failed", "Content Moderated"):
            raise ImageError(f"BFL: {status}")
    raise ImageError("BFL: انتهت المهلة")


def _replicate(cfg: dict, prompt: str, out: Path, refs: list[Path] | None = None) -> None:
    import time
    inp = {"prompt": prompt, "aspect_ratio": "9:16"}
    if refs:
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "jpeg": "image/jpeg", "webp": "image/webp"}[refs[0].suffix.lower().lstrip(".")]
        inp["image_prompt"] = (
            f"data:{mime};base64,{base64.b64encode(refs[0].read_bytes()).decode()}"
        )
    r = requests.post(f"{cfg['base_url']}/models/{cfg['model']}/predictions",
                      headers={"Authorization": f"Bearer {cfg['api_key']}",
                               "Prefer": "wait"},
                      json={"input": inp}, timeout=600)
    if r.status_code not in (200, 201):
        raise ImageError(f"Replicate رجّع {r.status_code}: {r.text[:200]}")
    d = r.json()
    for _ in range(120):
        if d.get("status") == "succeeded":
            output = d.get("output")
            url = output[0] if isinstance(output, list) else output
            out.write_bytes(requests.get(url, timeout=300).content)
            return
        if d.get("status") in ("failed", "canceled"):
            raise ImageError(f"Replicate: {d.get('error') or d.get('status')}")
        time.sleep(2)
        d = requests.get(d["urls"]["get"],
                         headers={"Authorization": f"Bearer {cfg['api_key']}"},
                         timeout=60).json()
    raise ImageError("Replicate: انتهت المهلة")


_DISPATCH = {"openai": _openai, "gemini": _gemini, "bfl": _bfl, "replicate": _replicate}


REF_RULE = (
    "Use the attached reference image(s) as the exact visual source of truth. "
    "The FIRST reference is the person: keep the same face, hair, body type, age and "
    "skin tone in every shot — this identity must not drift. "
    "Any product shown must match its reference exactly: same bottle shape, cap, colour "
    "and proportions. Do not redesign, restyle or relabel it."
)


def ref_rule(roles: list[str | None] | None = None) -> str:
    """تعليمة الصور المرجعية. بلا أدوار (الاستدعاءات القديمة): الصيغة الأصلية REF_RULE. بالأدوار: كل صورة بتنوصف
    بدورها (person/product) — فما بنقول «أول صورة هي الشخص» وهي بالحقيقة صورة المنتج (سيناريو بلا شخصية)."""
    if not roles:
        return REF_RULE

    def at(role: str) -> str:
        return ", ".join(str(i) for i, r in enumerate(roles, 1) if r == role)

    parts = ["Use the attached reference image(s) as the exact visual source of truth."]
    if at("person"):
        parts.append(f"Reference image(s) {at('person')}: the person. Keep the same face, hair, body type, age and skin tone in every shot; "
                     "this identity must not drift.")
    if at("product"):
        parts.append(f"Reference image(s) {at('product')}: the product. It must match its reference exactly: same shape, cap, colour and "
                     "proportions. Do not redesign, restyle or relabel it.")
    return " ".join(parts)


def generate(visual: str, out_path: Path, overrides: dict | None = None,
             extra: str = "", refs: list[Path] | None = None, ref_roles: list[str | None] | None = None) -> dict:
    cfg = image_config(overrides)
    if not cfg["api_key"]:
        raise ImageError(f"ما في مفتاح لمزوّد {cfg['provider']} — حطّه من الإعدادات")
    fn = _DISPATCH.get(cfg["kind"])
    if not fn:
        raise ImageError(f"مزوّد غير مدعوم: {cfg['provider']}")

    pairs = [(Path(r), ref_roles[i] if ref_roles and i < len(ref_roles) else None) for i, r in enumerate(refs or []) if Path(r).exists()]
    refs = [p for p, _role in pairs]                              # الأدوار بتتفلتر مع الصور (صورة مفقودة ما بتزحزح الباقي)
    roles = [role for _p, role in pairs] if ref_roles else None
    if refs and not cfg["supports_refs"]:
        raise ImageError(
            f"{cfg['provider']} ما بيدعم الصور المرجعية — بيولّد من النص بس.\n"
            "    للشخصية والمنتج الثابتين استخدم: Google أو OpenAI أو BFL أو Replicate.\n"
            "    أو شيل المراجع (الورقة المرجعية للمنتج/الشخصية) وولّد بدونها."
        )
    prompt = build_prompt(visual, cfg, " ".join(filter(None, [extra, ref_rule(roles) if refs else ""])))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fn(cfg, prompt, out_path, refs)
    except requests.RequestException as e:
        raise ImageError(f"فشل الاتصال بـ {cfg['provider']}: {e}")

    if not out_path.exists() or out_path.stat().st_size < 1000:
        raise ImageError("الصورة طلعت فاضية أو تالفة")
    return {"path": str(out_path), "prompt": prompt,
            "provider": cfg["provider"], "model": cfg["model"],
            "refs_used": [r.name for r in refs],
            "size": out_path.stat().st_size}
