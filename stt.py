"""
طبقة تفريغ صوتي موحّدة — محلي أو سحابي.

المرحلة 1 كانت مربوطة بـ faster-whisper محلياً. هون منفصلها عن المزوّد
عشان تقدر تستخدم أي خدمة، مع الحفاظ على نفس شكل المخرج:

    {"language": "ar", "full_text": "...", "segments": [{"start","end","text"}]}

الطوابع الزمنية **إلزامية** — عليها بينبني ربط الكلام بالمشاهد. أي مزوّد
ما بيرجّع توقيتات ما بينفع هون.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

import config

STT_PRESETS = {
    "local_whisper": {
        "label": "Whisper محلي (على كرتك)", "kind": "local",
        "env_key": "", "cost": "مجاني — بس بياخد وقت ورام",
        "models": ["large-v3", "medium", "small", "base", "tiny"],
        "note": "ما بيحتاج إنترنت ولا مفتاح. الأدق للهجات العربية بموديل large-v3.",
    },
    "openai": {
        "label": "OpenAI — Whisper / GPT-4o Transcribe", "kind": "openai_audio",
        "base_url": "https://api.openai.com/v1", "env_key": "OPENAI_API_KEY",
        "cost": "بالدقيقة",
        "models": ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
        "note": "whisper-1 بس بيرجّع توقيتات مفصّلة (verbose_json).",
    },
    "groq": {
        "label": "Groq — Whisper سريع جداً", "kind": "openai_audio",
        "base_url": "https://api.groq.com/openai/v1", "env_key": "GROQ_API_KEY",
        "cost": "رخيص جداً بالدقيقة",
        "models": ["whisper-large-v3", "whisper-large-v3-turbo"],
        "note": "نفس موديل Whisper بس على عتاد Groq — أسرع بكتير من المحلي.",
    },
    "deepgram": {
        "label": "Deepgram — Nova", "kind": "deepgram",
        "base_url": "https://api.deepgram.com/v1/listen", "env_key": "DEEPGRAM_API_KEY",
        "cost": "بالدقيقة",
        "models": ["nova-3", "nova-2"],
        "note": "دقة عالية وسريع. حدّد اللغة بالإعدادات لنتيجة أفضل بالعربي.",
    },
    "assemblyai": {
        "label": "AssemblyAI", "kind": "assemblyai",
        "base_url": "https://api.assemblyai.com/v2", "env_key": "ASSEMBLYAI_API_KEY",
        "cost": "بالساعة",
        "models": ["best", "nano"],
        "note": "بيرفع الملف أول بعدين بيفرّغ — أبطأ شوي بس دقيق.",
    },
    "elevenlabs": {
        "label": "ElevenLabs — Scribe", "kind": "elevenlabs",
        "base_url": "https://api.elevenlabs.io/v1/speech-to-text",
        "env_key": "ELEVENLABS_API_KEY", "cost": "بالساعة",
        "models": ["scribe_v1"],
        "note": "قوي باللهجات. بيرجّع توقيتات على مستوى الكلمة.",
    },
}


class STTError(Exception):
    """فشل التفريغ — برسالة جاهزة للعرض."""


def _settings() -> dict:
    import settings_io
    return settings_io.load()


def stt_config() -> dict:
    saved = _settings()
    entry = saved.get("STT") or {}
    provider = entry.get("provider") or "local_whisper"
    preset = STT_PRESETS.get(provider, STT_PRESETS["local_whisper"])

    key = entry.get("api_key") or ""
    if not key and preset.get("env_key"):
        key = os.environ.get(preset["env_key"], "")

    return {
        "provider": provider,
        "kind": preset["kind"],
        "model": entry.get("model") or (preset["models"][0] if preset["models"] else ""),
        "base_url": (entry.get("base_url") or preset.get("base_url", "")).rstrip("/"),
        "api_key": key,
        "language": entry.get("language") or getattr(config, "WHISPER_LANGUAGE", None),
    }


def _words_to_segments(words: list[dict], max_gap: float = 0.8) -> list[dict]:
    """
    المزوّدين اللي بيرجّعوا كلمات مفردة لازم نجمّعهم لمقاطع.
    منقطع عند سكتة أطول من max_gap — هيك بتطلع جمل طبيعية.
    """
    segments, cur = [], None
    for w in words:
        text = (w.get("word") or w.get("text") or "").strip()
        if not text:
            continue
        start, end = float(w.get("start", 0)), float(w.get("end", 0))
        if cur and start - cur["end"] <= max_gap:
            cur["end"] = end
            cur["text"] += " " + text
        else:
            if cur:
                segments.append(cur)
            cur = {"start": round(start, 2), "end": round(end, 2), "text": text}
    if cur:
        segments.append(cur)
    for s in segments:
        s["start"], s["end"] = round(s["start"], 2), round(s["end"], 2)
        s["text"] = s["text"].strip()
    return segments


# ── المزوّدين ────────────────────────────────────────────────────────────


_whisper_cache: dict[str, object] = {}


def _local_model(name: str, force_cpu: bool = False):
    """يُحمَّل مرة وحدة لكل حجم — مهم جداً بوضع الدفعة (الموديل ~3 جيجا)."""
    key = name + ("|cpu" if force_cpu else "")
    if key not in _whisper_cache:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise STTError("faster-whisper غير مثبّت — pip install faster-whisper")
        # نسخة محلية منزّلة مسبقاً (models/faster-whisper-<الاسم>) = بلا إنترنت وبلا انتظار تنزيل
        # (وأوزان «turbo-ar» العراقي بـ models/whisper-turbo-ar-ct2 — بتختارها باسم turbo-ar من إعداد التفريغ)
        local = next((d for d in (Path(config.BASE) / "models" / f"faster-whisper-{name}", Path(config.BASE) / "models" / f"whisper-{name}-ct2")
                      if (d / "model.bin").exists()), None)
        src = str(local) if local else name
        device, compute = ("cpu", "int8") if force_cpu else (config.WHISPER_DEVICE, config.WHISPER_COMPUTE)
        if device == "cuda":
            import cuda_dlls
            cuda_dlls.register()                     # cublas/cudnn من حزم nvidia (ويندوز ما بيلاقيها لحاله)
        print(f"[…] تحميل Whisper ({name} على {device}{' — محلي' if src != name else ''})…", flush=True)
        _whisper_cache[key] = WhisperModel(src, device=device, compute_type=compute)
    return _whisper_cache[key]


def _local_whisper(cfg: dict, audio: Path) -> dict:
    name = cfg["model"] or config.WHISPER_MODEL

    def run(force_cpu: bool):
        model = _local_model(name, force_cpu=force_cpu)
        segs, info = model.transcribe(str(audio), language=cfg["language"],
                                      vad_filter=True, beam_size=5, word_timestamps=True)
        return list(segs), info                      # الأخطاء بتطلع هون (التنفيذ كسول)

    try:
        segs, info = run(False)
    except RuntimeError as e:
        # مكتبات CUDA ناقصة (cublas/cudnn) ← بنكمّل على المعالج بدل ما نفشل
        if config.WHISPER_DEVICE == "cpu" or not any(k in str(e).lower() for k in ("cublas", "cudnn", "cuda")):
            raise
        print(f"[!] كرت الشاشة ما اشتغل مع Whisper ({str(e)[:80]}) — بكمّل على المعالج", flush=True)
        segs, info = run(True)
    segments = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segs]
    # توقيت كل كلمة (بالثواني) — أدق بكتير من توزيع الكلمات على المقطع
    words = [{"text": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)}
             for s in segs for w in (s.words or []) if w.word.strip()]
    return {
        "words": words,
        "language": info.language,
        "language_confidence": round(getattr(info, "language_probability", 0) or 0, 3),
        "segments": segments,
        "full_text": " ".join(s["text"] for s in segments).strip(),
    }


def _openai_audio(cfg: dict, audio: Path) -> dict:
    """صيغة OpenAI audio/transcriptions — بتشتغل مع OpenAI وGroq."""
    if not cfg["api_key"]:
        raise STTError(f"ما في مفتاح لمزوّد {cfg['provider']}")
    data = {"model": cfg["model"], "response_format": "verbose_json"}
    if cfg["language"]:
        data["language"] = cfg["language"]
    try:
        with audio.open("rb") as fh:
            r = requests.post(
                f"{cfg['base_url']}/audio/transcriptions",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                files={"file": (audio.name, fh, "audio/wav")},
                data=data, timeout=900,
            )
    except requests.RequestException as e:
        raise STTError(f"فشل الاتصال بـ {cfg['provider']}: {e}")
    if r.status_code != 200:
        raise STTError(f"{cfg['provider']} رجّع {r.status_code}: {r.text[:200]}")

    d = r.json()
    segments = [
        {"start": round(s.get("start", 0), 2), "end": round(s.get("end", 0), 2),
         "text": (s.get("text") or "").strip()}
        for s in d.get("segments", [])
    ]
    if not segments and d.get("text"):
        raise STTError(
            f"موديل {cfg['model']} رجّع نص بدون توقيتات. "
            "استخدم whisper-1 أو whisper-large-v3 — التوقيتات إلزامية لربط المشاهد."
        )
    return {
        "language": d.get("language", cfg["language"] or "unknown"),
        "language_confidence": 0,
        "segments": segments,
        "full_text": (d.get("text") or " ".join(s["text"] for s in segments)).strip(),
    }


def _deepgram(cfg: dict, audio: Path) -> dict:
    if not cfg["api_key"]:
        raise STTError("ما في مفتاح Deepgram")
    params = {"model": cfg["model"], "punctuate": "true", "smart_format": "true"}
    params["language"] = cfg["language"] or "ar"
    try:
        with audio.open("rb") as fh:
            r = requests.post(
                cfg["base_url"], params=params,
                headers={"Authorization": f"Token {cfg['api_key']}",
                         "Content-Type": "audio/wav"},
                data=fh, timeout=900,
            )
    except requests.RequestException as e:
        raise STTError(f"فشل الاتصال بـ Deepgram: {e}")
    if r.status_code != 200:
        raise STTError(f"Deepgram رجّع {r.status_code}: {r.text[:200]}")

    d = r.json()
    try:
        alt = d["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError):
        raise STTError(f"رد غير متوقّع من Deepgram: {json.dumps(d)[:200]}")

    segments = (
        [{"start": round(u["start"], 2), "end": round(u["end"], 2), "text": u["transcript"].strip()}
         for u in d["results"].get("utterances", [])]
        or _words_to_segments(alt.get("words", []))
    )
    return {
        "language": cfg["language"] or "ar",
        "language_confidence": round(alt.get("confidence", 0), 3),
        "segments": segments,
        "full_text": alt.get("transcript", "").strip(),
    }


def _assemblyai(cfg: dict, audio: Path) -> dict:
    if not cfg["api_key"]:
        raise STTError("ما في مفتاح AssemblyAI")
    headers = {"authorization": cfg["api_key"]}
    base = cfg["base_url"]
    try:
        with audio.open("rb") as fh:
            up = requests.post(f"{base}/upload", headers=headers, data=fh, timeout=900)
        if up.status_code != 200:
            raise STTError(f"فشل رفع الملف: {up.status_code} {up.text[:150]}")

        body = {"audio_url": up.json()["upload_url"], "speech_model": cfg["model"]}
        if cfg["language"]:
            body["language_code"] = cfg["language"]
        job = requests.post(f"{base}/transcript", headers=headers, json=body, timeout=120)
        if job.status_code not in (200, 201):
            raise STTError(f"فشل بدء التفريغ: {job.status_code} {job.text[:150]}")

        tid = job.json()["id"]
        import time
        for _ in range(300):                      # سقف ~10 دقايق
            time.sleep(2)
            st = requests.get(f"{base}/transcript/{tid}", headers=headers, timeout=60).json()
            if st.get("status") == "completed":
                break
            if st.get("status") == "error":
                raise STTError(f"AssemblyAI: {st.get('error')}")
        else:
            raise STTError("AssemblyAI: انتهت المهلة")
    except requests.RequestException as e:
        raise STTError(f"فشل الاتصال بـ AssemblyAI: {e}")

    words = [{"start": w["start"] / 1000, "end": w["end"] / 1000, "text": w["text"]}
             for w in st.get("words", [])]
    return {
        "language": st.get("language_code", cfg["language"] or "ar"),
        "language_confidence": round(st.get("confidence", 0) or 0, 3),
        "segments": _words_to_segments(words),
        "full_text": (st.get("text") or "").strip(),
    }


def _elevenlabs(cfg: dict, audio: Path) -> dict:
    if not cfg["api_key"]:
        raise STTError("ما في مفتاح ElevenLabs")
    data = {"model_id": cfg["model"], "timestamps_granularity": "word"}
    if cfg["language"]:
        data["language_code"] = cfg["language"]
    try:
        with audio.open("rb") as fh:
            r = requests.post(
                cfg["base_url"], headers={"xi-api-key": cfg["api_key"]},
                files={"file": (audio.name, fh, "audio/wav")}, data=data, timeout=900,
            )
    except requests.RequestException as e:
        raise STTError(f"فشل الاتصال بـ ElevenLabs: {e}")
    if r.status_code != 200:
        raise STTError(f"ElevenLabs رجّع {r.status_code}: {r.text[:200]}")

    d = r.json()
    words = [{"start": w.get("start", 0), "end": w.get("end", 0), "text": w.get("text", "")}
             for w in d.get("words", []) if w.get("type", "word") == "word"]
    return {
        "language": d.get("language_code", cfg["language"] or "ar"),
        "language_confidence": round(d.get("language_probability", 0) or 0, 3),
        "segments": _words_to_segments(words),
        "full_text": (d.get("text") or "").strip(),
    }


_DISPATCH = {
    "local": _local_whisper,
    "openai_audio": _openai_audio,
    "deepgram": _deepgram,
    "assemblyai": _assemblyai,
    "elevenlabs": _elevenlabs,
}


def _via_library(audio: Path, language: str | None, via: str | None) -> dict | None:
    """نموذج تفريغ من مكتبة النماذج (الافتراضي أو lib:ml_x). None = كمّل بالطريقة الحالية."""
    import model_library
    import model_run
    sel = via or ""
    if not sel:
        saved = str((_settings().get("STT") or {}).get("provider") or "")
        sel = saved if saved.startswith(model_library.LIB_PREFIX) else ""

    def accept(res):
        d = res.data or {}
        return None if (d.get("segments") or d.get("words")) else "ما رجّع توقيتات (التوقيتات إلزامية لربط الكلام بالمشاهد)"

    res, note = model_run.run_via_library("stt", model_run.RunRequest(task="stt", audio=audio, language=language), sel or None,
                                          error_cls=STTError, accept=accept)
    if res is None:
        if note:
            print(f"[i] {note}", flush=True)
        return None
    d = res.data
    words = d.get("words") or []
    return {"language": d.get("language") or language or "ar", "language_confidence": 0, "words": words,
            "segments": d.get("segments") or _words_to_segments(words), "full_text": d.get("text") or "",
            "provider": f"lib:{res.model_id}", "model": res.model_name, "logged": True}


def transcribe(audio_path: Path, language: str | None = None, via: str | None = None) -> dict:
    """language (اختياري): بيغلب لغة الإعدادات لهالمرة بس (مثلاً «ar» لتسجيل المالك). النداءات القديمة ما بتتغيّر.
    via (اختياري): lib:ml_x لنموذج تفريغ من مكتبة النماذج، أو اسم مزوّد حالي. بلا via: افتراضي المكتبة (لو في) وإلا الطريقة الحالية."""
    lib = _via_library(Path(audio_path), language, via)
    if lib is not None:
        return lib
    cfg = stt_config()
    if language:
        cfg["language"] = language
    fn = _DISPATCH.get(cfg["kind"])
    if not fn:
        raise STTError(f"مزوّد تفريغ غير مدعوم: {cfg['provider']}")
    result = fn(cfg, Path(audio_path))
    if not result.get("segments"):
        raise STTError(
            f"{cfg['provider']} ما رجّع أي مقاطع بتوقيتات — "
            "التوقيتات إلزامية لربط الكلام بالمشاهد."
        )
    result["provider"] = cfg["provider"]
    result["model"] = cfg["model"]
    return result
