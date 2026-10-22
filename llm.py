"""
طبقة مزوّدين موحّدة — كل مهمة تقدر تستخدم مزوّد وموديل ومفتاح مختلف.

ليش موجودة: Anthropic له صيغة طلب خاصة، وأغلب المزوّدين التانيين (كيمي/Moonshot،
DeepSeek، OpenRouter، Groq…) بيتبعوا صيغة OpenAI chat/completions. بدل ما كل
سكربت يعرف الفرق، بيستدعوا complete() وهي بتترجم.

المهام: analysis (تشريح الفيديو — بدها رؤية) · match · writer · parser · importer
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

import config

# مزوّدين جاهزين. كل شي هون مجرد قيمة ابتدائية — الـ base_url واسم الموديل
# قابلين للتعديل من الواجهة، لأن المزوّدين بيغيّروا نطاقاتهم وأسماء موديلاتهم باستمرار.
PROVIDER_PRESETS = {
    # ── أمريكية ──────────────────────────────────────────────────────────
    "anthropic": {
        "label": "Anthropic — Claude", "region": "أمريكية",
        "kind": "anthropic", "base_url": "", "env_key": "ANTHROPIC_API_KEY",
        "vision": True,
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
    },
    "openai": {
        "label": "OpenAI — GPT", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY", "vision": True,
        "models": ["gpt-5", "gpt-5-mini", "o4-mini"],
    },
    "google": {
        "label": "Google — Gemini", "region": "أمريكية",
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GEMINI_API_KEY", "vision": True,
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
    },
    "xai": {
        "label": "xAI — Grok", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.x.ai/v1",
        "env_key": "XAI_API_KEY", "vision": True,
        "models": ["grok-4", "grok-4-fast"],
    },
    "groq": {
        "label": "Groq — استضافة سريعة جداً", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY", "vision": False,
        "models": ["llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct"],
    },
    "together": {
        "label": "Together AI — استضافة مفتوحة المصدر", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.together.xyz/v1",
        "env_key": "TOGETHER_API_KEY", "vision": True,
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-VL-72B-Instruct"],
    },
    "fireworks": {
        "label": "Fireworks AI", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.fireworks.ai/inference/v1",
        "env_key": "FIREWORKS_API_KEY", "vision": True,
        "models": ["accounts/fireworks/models/deepseek-v3"],
    },
    "cerebras": {
        "label": "Cerebras — الأسرع بالتوليد", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.cerebras.ai/v1",
        "env_key": "CEREBRAS_API_KEY", "vision": False,
        "models": ["llama-3.3-70b", "qwen-3-235b-a22b"],
    },
    "perplexity": {
        "label": "Perplexity — مربوط بالبحث", "region": "أمريكية",
        "kind": "openai", "base_url": "https://api.perplexity.ai",
        "env_key": "PERPLEXITY_API_KEY", "vision": False,
        "models": ["sonar-pro", "sonar-reasoning-pro"],
    },
    "mistral": {
        "label": "Mistral (فرنسية)", "region": "أوروبية",
        "kind": "openai", "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY", "vision": True,
        "models": ["mistral-large-latest", "pixtral-large-latest"],
    },

    # ── صينية ────────────────────────────────────────────────────────────
    "moonshot": {
        "label": "Moonshot — Kimi", "region": "صينية",
        "kind": "openai", "base_url": "https://api.moonshot.ai/v1",
        "env_key": "MOONSHOT_API_KEY", "vision": True,
        "models": ["kimi-k2-0905-preview", "kimi-k2-turbo-preview",
                   "moonshot-v1-32k-vision-preview"],
        "note": "للصين بدّل النطاق لـ api.moonshot.cn",
    },
    "deepseek": {
        "label": "DeepSeek", "region": "صينية",
        "kind": "openai", "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY", "vision": False,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "qwen": {
        "label": "Alibaba — Qwen (DashScope)", "region": "صينية",
        "kind": "openai",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY", "vision": True,
        "models": ["qwen-max", "qwen-plus", "qwen-vl-max"],
        "note": "دي النسخة الدولية. لبكين: dashscope.aliyuncs.com",
    },
    "zhipu": {
        "label": "Zhipu — GLM (Z.ai)", "region": "صينية",
        "kind": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY", "vision": True,
        "models": ["glm-4.6", "glm-4v-plus"],
        "note": "للنسخة الدولية جرّب api.z.ai/api/paas/v4",
    },
    "doubao": {
        "label": "ByteDance — Doubao (Volcengine)", "region": "صينية",
        "kind": "openai", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "env_key": "ARK_API_KEY", "vision": True,
        "models": ["doubao-seed-1-6", "doubao-1.5-vision-pro"],
        "note": "الموديل بينحدّد كـ endpoint id من لوحة Volcengine",
    },
    "minimax": {
        "label": "MiniMax", "region": "صينية",
        "kind": "openai", "base_url": "https://api.minimax.chat/v1",
        "env_key": "MINIMAX_API_KEY", "vision": True,
        "models": ["MiniMax-Text-01", "abab6.5s-chat"],
    },
    "stepfun": {
        "label": "StepFun — 阶跃星辰", "region": "صينية",
        "kind": "openai", "base_url": "https://api.stepfun.com/v1",
        "env_key": "STEPFUN_API_KEY", "vision": True,
        "models": ["step-2-16k", "step-1v-8k"],
    },
    "yi": {
        "label": "01.AI — Yi (零一万物)", "region": "صينية",
        "kind": "openai", "base_url": "https://api.lingyiwanwu.com/v1",
        "env_key": "YI_API_KEY", "vision": True,
        "models": ["yi-large", "yi-vision"],
    },
    "hunyuan": {
        "label": "Tencent — Hunyuan", "region": "صينية",
        "kind": "openai", "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "env_key": "HUNYUAN_API_KEY", "vision": True,
        "models": ["hunyuan-turbos-latest", "hunyuan-vision"],
    },
    "baichuan": {
        "label": "Baichuan — 百川", "region": "صينية",
        "kind": "openai", "base_url": "https://api.baichuan-ai.com/v1",
        "env_key": "BAICHUAN_API_KEY", "vision": False,
        "models": ["Baichuan4-Turbo"],
    },
    "siliconflow": {
        "label": "SiliconFlow — بوابة صينية", "region": "صينية",
        "kind": "openai", "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "SILICONFLOW_API_KEY", "vision": True,
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-VL-72B-Instruct"],
    },

    # ── بوابات ومحلي ─────────────────────────────────────────────────────
    "unorouter": {
        "label": "UnoRouter — بوابة (فيها موديلات مجانية)", "region": "بوابات",
        "kind": "openai", "base_url": "https://api.unorouter.com/v1",
        "env_key": "UNOROUTER_API_KEY", "vision": True,
        "models": ["gpt-oss-120b:free"],
        "note": "الموديلات اللي بتنتهي بـ :free مجانية تماماً. 300+ موديل بمفتاح واحد.",
    },
    "openrouter": {
        "label": "OpenRouter — بوابة لكل الموديلات", "region": "بوابات",
        "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY", "vision": True,
        "models": ["anthropic/claude-sonnet-5", "moonshotai/kimi-k2",
                   "google/gemini-2.5-pro", "deepseek/deepseek-chat"],
    },
    "ollama": {
        "label": "Ollama — محلي على جهازك", "region": "بوابات",
        "kind": "openai", "base_url": "http://localhost:11434/v1",
        "env_key": "", "vision": True,
        "models": ["qwen2.5vl", "llama3.2-vision"],
        "note": "بدون مفتاح — بس لازم Ollama شغال محلياً",
    },
    "custom": {
        "label": "مخصّص — أي مزوّد متوافق مع OpenAI", "region": "بوابات",
        "kind": "openai", "base_url": "", "env_key": "", "vision": True,
        "models": [],
    },
}

# الإعداد القديم (موديل واحد لكل مهمة على Anthropic) — يُستخدم لو ما في إعداد مهام
LEGACY_MODEL_KEYS = {
    "analysis": "MODEL_ANALYSIS",
    "match": "MODEL_MATCH",
    "writer": "MODEL_WRITER",
    "reviewer": "MODEL_WRITER",     # التدقيق بدّه موديل قوي متل الكتابة
    "parser": "MODEL_MATCH",
    "importer": "MODEL_ANALYSIS",
    "shotplan": "MODEL_MATCH",
    "translate": "MODEL_MATCH",
    "imgprompt": "MODEL_MATCH",
}

TASK_LABELS = {
    "analysis": "تشريح الفيديو (بدّه رؤية)",
    "match": "مطابقة المنتج بالأنماط",
    "writer": "كتابة السيناريو",
    "reviewer": "تدقيق السيناريو",
    "parser": "قراءة بيانات المنتج من نص",
    "importer": "استيراد أنماط من مستند",
    "shotplan": "تقسيم المشهد للقطات",
    "translate": "ترجمة الأنماط للعربي",
    "imgprompt": "ترجمة برومبتات اللقطات وبطاقة الشخصية للإنجليزي",
}


class LLMError(Exception):
    """خطأ من المزوّد — برسالة جاهزة للعرض."""


def _record(cfg: dict, input_tokens: int, output_tokens: int) -> None:
    """تسجيل الاستهلاك — ما بيوقف النداء إذا فشل."""
    try:
        import usage
        usage.record(cfg["task"], cfg["provider"], cfg["model"],
                     int(input_tokens or 0), int(output_tokens or 0))
    except Exception:
        pass


def _settings() -> dict:
    import settings_io
    return settings_io.load()


def provider_models(provider: str) -> list[str]:
    """موديلات المزوّد: الجاهزة + اللي ضفتها إنت (CUSTOM_MODELS بالإعدادات)."""
    preset = PROVIDER_PRESETS.get(provider, {})
    base = list(preset.get("models", []))
    extra = (_settings().get("CUSTOM_MODELS") or {}).get(provider, [])
    for m in extra:
        if m and m not in base:
            base.append(m)
    return base


def add_model(provider: str, model: str) -> list[str]:
    """يضيف موديل لقائمة مزوّد ويحفظه."""
    import settings_io
    model = (model or "").strip()
    if not model:
        raise ValueError("اسم الموديل فاضي")

    def mutate(saved: dict) -> None:
        lst = saved.setdefault("CUSTOM_MODELS", {}).setdefault(provider, [])
        if model not in lst and model not in PROVIDER_PRESETS.get(provider, {}).get("models", []):
            lst.append(model)

    settings_io.update(mutate)
    return provider_models(provider)


def remove_model(provider: str, model: str) -> list[str]:
    """يشيل موديل مضاف يدوياً — الجاهزة ما بتنشال."""
    import settings_io

    def mutate(saved: dict) -> None:
        lst = (saved.get("CUSTOM_MODELS") or {}).get(provider, [])
        if model in lst:
            lst.remove(model)

    settings_io.update(mutate)
    return provider_models(provider)


# تجاوز لتشغيلة وحدة — بينحط من سطر الأوامر، بيغلب المحفوظ بدون ما يعدّله.
# لازم عشان تقدر تولّد بموديل معيّن مرة وحدة وتقارن، بدون ما تغيّر إعدادك.
_OVERRIDES: dict[str, dict] = {}


def set_override(task: str, connection: str = "", model: str = "") -> None:
    if connection or model:
        _OVERRIDES[task] = {"connection": connection, "model": model}


def task_config(task: str) -> dict:
    """
    يحلّ إعداد المهمة بالترتيب:
      0. تجاوز مؤقت لهالتشغيلة (من سطر الأوامر)
      1. اتصال + موديل محدّدين يدوياً لهالمهمة
      2. اختيار تلقائي من الاتصالات المحفوظة حسب طبيعة المهمة
      3. الإعداد القديم (مزوّد+مفتاح مباشر بالمهمة) — للتوافق
    """
    saved = _settings()
    entry = (saved.get("TASKS") or {}).get(task) or {}

    ov = _OVERRIDES.get(task)
    if ov:
        entry = {**entry, **{k: v for k, v in ov.items() if v}}

    # (1) و(2): الاتصالات
    conn_id, model = entry.get("connection"), entry.get("model")
    picked_auto = False
    if not conn_id and not entry.get("provider"):
        try:
            import connections
            auto = connections.auto_pick(task)
        except Exception:
            auto = None
        if auto:
            conn_id, model, picked_auto = auto["connection"], auto["model"], True

    if conn_id:
        conns = saved.get("CONNECTIONS") or {}
        conn = conns.get(conn_id)
        if conn:
            preset = PROVIDER_PRESETS.get(conn["provider"], PROVIDER_PRESETS["custom"])
            return {
                "task": task,
                "provider": conn["provider"],
                "kind": preset["kind"],
                "model": model or "",
                "base_url": (conn.get("base_url") or preset["base_url"] or "").rstrip("/"),
                "api_key": conn.get("api_key", ""),
                "vision": preset.get("vision", True),
                "connection": conn_id,
                "connection_label": conn.get("label", ""),
                "auto": picked_auto,
            }

    # (3) المسار القديم
    provider = entry.get("provider") or "anthropic"
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])

    model = entry.get("model") or getattr(config, LEGACY_MODEL_KEYS.get(task, "MODEL_MATCH"), "")
    base_url = (entry.get("base_url") or preset["base_url"] or "").rstrip("/")

    # المفتاح بالترتيب: إعداد المهمة ← متغيّر بيئة المزوّد ← المفتاح العام المحفوظ
    key = entry.get("api_key") or ""
    if not key and preset["env_key"]:
        key = os.environ.get(preset["env_key"], "")
    if not key and provider == "anthropic":
        key = saved.get("ANTHROPIC_API_KEY", "")
    # متغيّر البيئة ممكن يكون مرجع سر (config.py بينسخه من settings.json)
    import settings_io
    key = settings_io.resolve_ref(key or "")

    return {
        "task": task,
        "provider": provider,
        "kind": preset["kind"],
        "model": model,
        "base_url": base_url,
        "api_key": key or "",
        "vision": preset.get("vision", True),
    }


# ── ترجمة المحتوى ────────────────────────────────────────────────────────
# الشكل الموحّد: [{"type":"text","text":...}, {"type":"image","data":b64,"media_type":...}]


def _to_anthropic(blocks: list[dict]) -> list[dict]:
    out = []
    for b in blocks:
        if b["type"] == "text":
            out.append({"type": "text", "text": b["text"]})
        else:
            out.append({
                "type": "image",
                "source": {"type": "base64",
                           "media_type": b.get("media_type", "image/jpeg"),
                           "data": b["data"]},
            })
    return out


def _to_openai(blocks: list[dict]) -> list[dict]:
    out = []
    for b in blocks:
        if b["type"] == "text":
            out.append({"type": "text", "text": b["text"]})
        else:
            mt = b.get("media_type", "image/jpeg")
            out.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mt};base64,{b['data']}"},
            })
    return out


# ── التنفيذ ──────────────────────────────────────────────────────────────


def _call_anthropic(cfg: dict, system: str, blocks: list[dict], max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        raise LLMError("مكتبة anthropic غير مثبّتة — pip install anthropic")
    if not cfg["api_key"]:
        raise LLMError("ما في مفتاح لمزوّد Anthropic — حطّه من تبويب الإعدادات")

    kwargs: dict[str, Any] = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]

    try:
        resp = anthropic.Anthropic(**kwargs).messages.create(
            model=cfg["model"],
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": _to_anthropic(blocks)}],
        )
    except Exception as exc:
        from llm_errors import friendly
        raise LLMError(friendly(exc) or str(exc)) from exc

    _record(cfg, getattr(resp.usage, "input_tokens", 0), getattr(resp.usage, "output_tokens", 0))

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        kinds = [b.type for b in resp.content]
        raise LLMError(
            f"الرد إجا بدون نص (كتل: {kinds}, سبب التوقف: {resp.stop_reason}). "
            "غالباً التفكير استهلك كل السقف — ارفع MAX_OUTPUT_TOKENS."
        )
    return text


def _call_openai(cfg: dict, system: str, blocks: list[dict], max_tokens: int) -> str:
    if not cfg["base_url"]:
        raise LLMError(f"ما في base_url لمزوّد {cfg['provider']} — حدّده بالإعدادات")
    # المزوّد المحلي (Ollama) ما بدّه مفتاح
    is_local = cfg["base_url"].startswith(("http://localhost", "http://127.0.0.1"))
    if not cfg["api_key"] and not is_local:
        raise LLMError(f"ما في مفتاح لمزوّد {cfg['provider']} — حطّه من تبويب الإعدادات")

    payload = {
        "model": cfg["model"],
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": _to_openai(blocks)},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    try:
        r = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=600,
        )
    except requests.RequestException as exc:
        raise LLMError(f"ما قدرت أوصل لـ {cfg['provider']}: {exc}") from exc

    if r.status_code != 200:
        detail = r.text[:300]
        try:
            detail = r.json().get("error", {}).get("message", detail)
        except ValueError:
            pass
        if r.status_code == 401:
            raise LLMError(f"مفتاح {cfg['provider']} مرفوض")
        if r.status_code == 429:
            raise LLMError(f"تجاوزت حد الطلبات عند {cfg['provider']} — استنى شوي")
        raise LLMError(f"خطأ من {cfg['provider']} ({r.status_code}): {detail}")

    data = r.json()
    u = data.get("usage") or {}
    _record(cfg, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise LLMError(f"رد غير متوقّع من {cfg['provider']}: {json.dumps(data)[:250]}")
    if not (text or "").strip():
        raise LLMError(f"{cfg['provider']} رجّع رد فاضي")
    return text.strip()


def _enforce_spend_limit() -> None:
    """حد الإنفاق اليومي/الشهري — بيمنع النداء قبل ما يطلع من الجهاز."""
    import usage
    try:
        usage.check_spend_limits()
    except usage.SpendLimitReached as e:
        raise LLMError(str(e)) from None
    except Exception:
        # عطل بقراءة الإحصاءات ما لازم يوقف الشغل، بس ما نخفيه بالصمت
        import sys
        print("[!] تعذّر فحص حد الإنفاق — النداء رح يكمل", file=sys.stderr)


def complete(task: str, system: str, blocks: list[dict], max_tokens: int | None = None) -> str:
    """ينفّذ المهمة على المزوّد المضبوط إلها ويرجّع النص."""
    cfg = task_config(task)
    if not cfg["model"]:
        raise LLMError(f"ما في موديل محدّد لمهمة '{task}' — ظبّطه من الإعدادات")

    has_image = any(b["type"] == "image" for b in blocks)
    if has_image and not cfg["vision"]:
        raise LLMError(
            f"مهمة '{TASK_LABELS.get(task, task)}' بدها رؤية، "
            f"و{cfg['provider']} ما بيدعم الصور. غيّر المزوّد لهالمهمة."
        )

    _enforce_spend_limit()

    max_tokens = max_tokens or getattr(config, "MAX_OUTPUT_TOKENS", 8000)
    if cfg["kind"] == "anthropic":
        return _call_anthropic(cfg, system, blocks, max_tokens)
    return _call_openai(cfg, system, blocks, max_tokens)


def strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.removeprefix("json").strip()
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def complete_json(task: str, system: str, blocks: list[dict], max_tokens: int | None = None):
    raw = strip_json_fence(complete(task, system, blocks, max_tokens))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        from pathlib import Path
        Path("last_raw_response.txt").write_text(raw, encoding="utf-8")
        raise LLMError(
            f"الرد مش JSON صالح (المزوّد: {task_config(task)['provider']}). "
            "الخام محفوظ في last_raw_response.txt"
        ) from exc
