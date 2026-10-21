"""
توليد الفويس أوفر — طبقة مزوّدين موحّدة.

بتاخد سيناريو وبتولّد ملف صوتي لكل مشهد + ملف كامل مدموج، وبتقيس المدة
الفعلية لكل مقطع وتقارنها بالمدة المخطّطة — لأن الفرق بينهم هو اللي بيكسر
المونتاج لاحقاً.

الأصوات بتنجلب من المزوّد نفسه لما يدعم ذلك، عشان القائمة تضل محدّثة.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import requests

import config

TTS_PRESETS = {
    "elevenlabs": {
        "label": "ElevenLabs", "kind": "elevenlabs",
        "base_url": "https://api.elevenlabs.io/v1", "env_key": "ELEVENLABS_API_KEY",
        "models": ["eleven_v3", "eleven_multilingual_v2", "eleven_turbo_v2_5"],
        "lists_voices": True,
        "note": "الأقوى باللهجات العربية. eleven_v3 بيدعم وسوم المشاعر بالنص.",
    },
    "openai": {
        "label": "OpenAI TTS", "kind": "openai",
        "base_url": "https://api.openai.com/v1", "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"],
        "lists_voices": False,
        "voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer", "ash", "sage", "coral"],
        "note": "gpt-4o-mini-tts بيقبل تعليمات نبرة بحقل instructions.",
    },
    "minimax": {
        "label": "MiniMax Speech", "kind": "minimax",
        "base_url": "https://api.minimax.chat/v1", "env_key": "MINIMAX_API_KEY",
        "models": ["speech-02-hd", "speech-02-turbo"],
        "lists_voices": False,
        "voices": ["male-qn-qingse", "female-shaonv", "audiobook_male_1"],
        "note": "بيحتاج GroupId مع المفتاح — حطّه بخانة Base URL هيك: ...?GroupId=xxx",
    },
    "google": {
        "label": "Google Cloud TTS", "kind": "google",
        "base_url": "https://texttospeech.googleapis.com/v1", "env_key": "GOOGLE_TTS_API_KEY",
        "models": ["Chirp3-HD", "Neural2", "Standard"],
        "lists_voices": True,
        "note": "بيدعم لهجات عربية متعددة (ar-XA وغيرها). الصوت بينحدد بالاسم الكامل.",
    },
    "gemini": {
        "label": "Google Gemini TTS", "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env_key": "GEMINI_API_KEY",
        "models": ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"],
        "lists_voices": False,
        "voices": ["Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"],
        "note": "بيقبل تعليمات نبرة بلغة طبيعية قبل النص — الأمرن بالتحكم بالأداء.",
    },
    "deepgram": {
        "label": "Deepgram Aura", "kind": "deepgram",
        "base_url": "https://api.deepgram.com/v1/speak", "env_key": "DEEPGRAM_API_KEY",
        "models": ["aura-2-thalia-en", "aura-asteria-en"],
        "lists_voices": False, "voices": [],
        "note": "سريع ورخيص، بس أصواته إنجليزية بالأساس — مش مناسب للعربي.",
    },
}

# خصائص الأداء — بتتحوّل لتعليمات نصية للمزوّدين اللي بيدعموها
GENDERS = {"": "أي", "female": "أنثى", "male": "ذكر"}
AGES = {"": "أي", "young": "شابة/شاب (18-25)", "adult": "بالغ (26-40)",
        "mature": "ناضج (40-55)", "senior": "كبير بالسن (55+)"}
DIALECTS = {"": "أي", "ar-SY": "شامي", "ar-EG": "مصري", "ar-SA": "خليجي",
            "ar-MA": "مغربي", "ar-XA": "فصحى"}
TONES = {"": "طبيعي", "warm": "دافئ ومطمئن", "energetic": "حماسي وسريع",
         "confident": "واثق وحازم", "intimate": "همس قريب وسرّي",
         "urgent": "مستعجل وضاغط", "empathetic": "متعاطف وهادي",
         "excited": "متحمّس ومنبهر", "authoritative": "خبير وموثوق"}


def performance_note(cfg: dict) -> str:
    """يحوّل الخصائص المختارة لتعليمة أداء نصية."""
    bits = []
    if cfg.get("tone"):
        bits.append(f"Speak in a {cfg['tone']} tone")
    if cfg.get("gender"):
        bits.append(f"{cfg['gender']} voice")
    if cfg.get("age"):
        bits.append(f"sounding {cfg['age'].replace('_', ' ')}")
    if cfg.get("dialect"):
        bits.append(f"in {DIALECTS.get(cfg['dialect'], cfg['dialect'])} Arabic dialect")
    if cfg.get("instructions"):
        bits.append(cfg["instructions"])
    return ". ".join(bits)


class TTSError(Exception):
    """فشل توليد الصوت — برسالة جاهزة للعرض."""


def _settings() -> dict:
    import settings_io
    return settings_io.load()


def tts_config(overrides: dict | None = None) -> dict:
    saved = _settings()
    entry = {**(saved.get("TTS") or {}), **{k: v for k, v in (overrides or {}).items() if v}}
    provider = entry.get("provider") or "elevenlabs"
    preset = TTS_PRESETS.get(provider, TTS_PRESETS["elevenlabs"])

    key = entry.get("api_key") or ""
    if not key and preset.get("env_key"):
        key = os.environ.get(preset["env_key"], "")

    return {
        "provider": provider,
        "kind": preset["kind"],
        "model": entry.get("model") or preset["models"][0],
        "voice": entry.get("voice") or (preset.get("voices") or [""])[0],
        "base_url": (entry.get("base_url") or preset["base_url"]).rstrip("/"),
        "api_key": key,
        "speed": float(entry.get("speed") or 1.0),
        "stability": float(entry.get("stability") or 0.5),
        "similarity": float(entry.get("similarity") or 0.75),
        "style": float(entry.get("style") or 0.0),
        "instructions": entry.get("instructions") or "",
        "gender": entry.get("gender") or "",
        "age": entry.get("age") or "",
        "dialect": entry.get("dialect") or "",
        "tone": entry.get("tone") or "",
    }


def list_voices(provider: str, api_key: str, base_url: str = "") -> list[dict]:
    """يجلب الأصوات من المزوّد لما يدعم ذلك، وإلا بيرجّع القائمة الثابتة."""
    preset = TTS_PRESETS.get(provider)
    if not preset:
        raise TTSError(f"مزوّد غير معروف: {provider}")

    if not preset.get("lists_voices"):
        return [{"id": v, "label": v} for v in preset.get("voices", [])]

    if preset["kind"] == "google":
        base = (base_url or preset["base_url"]).rstrip("/")
        try:
            r = requests.get(f"{base}/voices", params={"key": api_key, "languageCode": "ar"},
                             timeout=45)
        except requests.RequestException as e:
            raise TTSError(f"ما قدرت أوصل لـ Google: {e}")
        if r.status_code != 200:
            raise TTSError(f"Google رجّع {r.status_code}: {r.text[:150]}")
        return [{"id": v["name"],
                 "label": f"{v['name']} — {v.get('ssmlGender','')}"}
                for v in r.json().get("voices", [])]

    url = (base_url or preset["base_url"]).rstrip("/")
    try:
        r = requests.get(f"{url}/voices", headers={"xi-api-key": api_key}, timeout=45)
    except requests.RequestException as e:
        raise TTSError(f"ما قدرت أوصل للمزوّد: {e}")
    if r.status_code == 401:
        raise TTSError("المفتاح مرفوض")
    if r.status_code != 200:
        raise TTSError(f"المزوّد رجّع {r.status_code}: {r.text[:150]}")

    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        desc = " · ".join(filter(None, [labels.get("gender"), labels.get("accent"),
                                        labels.get("description")]))
        out.append({"id": v.get("voice_id"), "label": f"{v.get('name')} — {desc}" if desc else v.get("name")})
    return out


# ── المزوّدين ────────────────────────────────────────────────────────────


def _elevenlabs(cfg: dict, text: str, out: Path) -> dict | None:
    if not cfg["voice"]:
        raise TTSError("لازم تختار صوت")
    # eleven_v3 بيفهم وسم النبرة بين قوسين مربعين بأول النص
    payload = f"[{cfg['tone']}] {text}" if (cfg.get("tone") and "v3" in cfg["model"]) else text
    body = {
        "text": payload,
        "model_id": cfg["model"],
        "voice_settings": {
            "stability": cfg["stability"],
            "similarity_boost": cfg["similarity"],
            "style": cfg["style"],
        },
    }
    if cfg.get("want_timing"):
        # نقطة التوقيت بترجّع الصوت + توقيت كل حرف؛ منحوّله لكلمات
        r = requests.post(f"{cfg['base_url']}/text-to-speech/{cfg['voice']}/with-timestamps",
                          headers={"xi-api-key": cfg["api_key"]}, json=body, timeout=300)
        if r.status_code != 200:
            raise TTSError(f"ElevenLabs رجّع {r.status_code}: {r.text[:200]}")
        data = r.json()
        import base64
        out.write_bytes(base64.b64decode(data.get("audio_base64") or ""))
        al = data.get("normalized_alignment") or data.get("alignment") or {}
        if al.get("characters"):
            return {"payload": payload, "alignment": al}
        return None
    r = requests.post(f"{cfg['base_url']}/text-to-speech/{cfg['voice']}",
                      headers={"xi-api-key": cfg["api_key"]}, json=body, timeout=300)
    if r.status_code != 200:
        raise TTSError(f"ElevenLabs رجّع {r.status_code}: {r.text[:200]}")
    out.write_bytes(r.content)
    return None


def _google(cfg: dict, text: str, out: Path) -> None:
    """Google Cloud TTS — الصوت اسم كامل مثل ar-XA-Chirp3-HD-Aoede."""
    lang = cfg["dialect"] or "ar-XA"
    body = {
        "input": {"text": text},
        "voice": {"languageCode": lang[:5] if "-" in lang else "ar-XA",
                  "name": cfg["voice"] or ""},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": cfg["speed"]},
    }
    if not body["voice"]["name"]:
        body["voice"].pop("name")
        body["voice"]["ssmlGender"] = (cfg["gender"] or "NEUTRAL").upper()
    r = requests.post(f"{cfg['base_url']}/text:synthesize",
                      params={"key": cfg["api_key"]}, json=body, timeout=300)
    if r.status_code != 200:
        raise TTSError(f"Google رجّع {r.status_code}: {r.text[:200]}")
    audio = r.json().get("audioContent")
    if not audio:
        raise TTSError("Google ما رجّع صوت")
    import base64 as _b64
    out.write_bytes(_b64.b64decode(audio))


def _gemini(cfg: dict, text: str, out: Path) -> None:
    """Gemini TTS — بيقبل تعليمة أداء بلغة طبيعية قبل النص."""
    note = performance_note(cfg)
    payload = f"{note}: {text}" if note else text
    body = {
        "contents": [{"parts": [{"text": payload}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": cfg["voice"] or "Kore"}}},
        },
    }
    r = requests.post(f"{cfg['base_url']}/models/{cfg['model']}:generateContent",
                      params={"key": cfg["api_key"]}, json=body, timeout=300)
    if r.status_code != 200:
        raise TTSError(f"Gemini رجّع {r.status_code}: {r.text[:200]}")
    import base64 as _b64
    for cand in r.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
            if data:
                # Gemini بيرجّع PCM خام — منلفّه بـ WAV
                pcm = _b64.b64decode(data)
                _write_wav(pcm, out.with_suffix(".wav"))
                if out.suffix != ".wav":
                    _to_mp3(out.with_suffix(".wav"), out)
                return
    raise TTSError("Gemini ما رجّع صوت")


def _write_wav(pcm: bytes, path: Path, rate: int = 24000) -> None:
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _to_mp3(src: Path, dest: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-i", str(src), str(dest)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    src.unlink(missing_ok=True)


def _openai(cfg: dict, text: str, out: Path) -> None:
    body = {"model": cfg["model"], "input": text, "voice": cfg["voice"] or "alloy",
            "speed": cfg["speed"], "response_format": "mp3"}
    note = performance_note(cfg)
    if note and "gpt-4o" in cfg["model"]:
        body["instructions"] = note
    r = requests.post(f"{cfg['base_url']}/audio/speech",
                      headers={"Authorization": f"Bearer {cfg['api_key']}"},
                      json=body, timeout=300)
    if r.status_code != 200:
        raise TTSError(f"OpenAI رجّع {r.status_code}: {r.text[:200]}")
    out.write_bytes(r.content)


def _minimax(cfg: dict, text: str, out: Path) -> None:
    body = {"model": cfg["model"], "text": text, "stream": False,
            "voice_setting": {"voice_id": cfg["voice"], "speed": cfg["speed"]},
            "audio_setting": {"format": "mp3"}}
    r = requests.post(f"{cfg['base_url']}/t2a_v2",
                      headers={"Authorization": f"Bearer {cfg['api_key']}"},
                      json=body, timeout=300)
    if r.status_code != 200:
        raise TTSError(f"MiniMax رجّع {r.status_code}: {r.text[:200]}")
    d = r.json()
    hexaudio = (d.get("data") or {}).get("audio")
    if not hexaudio:
        raise TTSError(f"MiniMax ما رجّع صوت: {json.dumps(d)[:200]}")
    out.write_bytes(bytes.fromhex(hexaudio))


def _deepgram(cfg: dict, text: str, out: Path) -> None:
    r = requests.post(cfg["base_url"], params={"model": cfg["model"]},
                      headers={"Authorization": f"Token {cfg['api_key']}",
                               "Content-Type": "application/json"},
                      json={"text": text}, timeout=300)
    if r.status_code != 200:
        raise TTSError(f"Deepgram رجّع {r.status_code}: {r.text[:200]}")
    out.write_bytes(r.content)


_DISPATCH = {"elevenlabs": _elevenlabs, "openai": _openai, "google": _google,
             "gemini": _gemini, "minimax": _minimax, "deepgram": _deepgram}


def audio_duration(path: Path) -> float:
    """المدة الفعلية بالثواني — لازمة لمقارنتها بالمخطّط."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return round(float(out), 2)
    except (subprocess.CalledProcessError, ValueError):
        return 0.0


# ── وسوم المشاعر (eleven_v3) ──────────────────────────────────────────────
# شعور المشهد بالسيناريو نص حر؛ بنطابقه بكلمات مفتاحية. ما في تطابق = بلا وسم (ما بنخمّن).
_EMOTION_TAGS = [
    ("curious", r"curio|intrig|فضول|تساؤل|غموض"),
    ("excited", r"excit|joy|happy|thrill|حماس|فرح|انبهار|سعادة"),
    ("empathetic", r"empath|frustrat|pain|tired|sad|تعب|ألم|إحباط|تعاطف|قلق|ضيق"),
    ("confident", r"confid|trust|authorit|proud|ثقة|واثق|اطمئنان"),
    ("urgent", r"urgen|pressure|عاجل|استعجال"),
    ("warm", r"warm|relief|calm|comfort|ارتياح|راحة|دفء|هدوء"),
]


def emotion_tag(emotion: str | None) -> str:
    import re
    text = str(emotion or "")
    for tag, rx in _EMOTION_TAGS:
        if re.search(rx, text, re.I):
            return tag
    return ""


_PUNCT_END = "،,.؟?!:;؛"


def words_from_alignment(chars: list[str], starts: list[float], ends: list[float]) -> list[dict]:
    """توقيت حروف ← كلمات. الوسوم [بين قوسين] ما بتنعدّ كلام."""
    words, cur, depth = [], None, 0
    for ch, s, e in zip(chars, starts, ends):
        if ch == "[":
            depth += 1
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            continue
        if depth:
            continue
        if ch.isspace():
            if cur:
                words.append(cur)
                cur = None
            continue
        if cur is None:
            cur = {"text": ch, "start": float(s), "end": float(e)}
        else:
            cur["text"] += ch
            cur["end"] = float(e)
    if cur:
        words.append(cur)
    for w in words:
        w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)
    return words


def estimate_words(text: str, duration: float) -> list[dict]:
    """احتياط لمزوّد بلا توقيت: توزيع المدة بنسبة طول الكلمة. **تقديري** — بيتعلّم بالمانيفست."""
    toks = str(text).split()
    if not toks or duration <= 0:
        return []
    weights = [len(t) + 1 for t in toks]
    total, t, out = float(sum(weights)), 0.0, []
    for tok, w in zip(toks, weights):
        d = duration * w / total
        out.append({"text": tok, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def speak(text: str, out_path: Path, overrides: dict | None = None,
          want_timing: bool = False) -> dict:
    cfg = tts_config(overrides)
    cfg["want_timing"] = bool(want_timing)
    if not cfg["api_key"]:
        raise TTSError(f"ما في مفتاح لمزوّد {cfg['provider']} — حطّه من الإعدادات")
    fn = _DISPATCH.get(cfg["kind"])
    if not fn:
        raise TTSError(f"مزوّد غير مدعوم: {cfg['provider']}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        timing = fn(cfg, text, out_path)
    except requests.RequestException as e:
        raise TTSError(f"فشل الاتصال بـ {cfg['provider']}: {e}")

    if not out_path.exists() or out_path.stat().st_size < 500:
        raise TTSError("الملف الصوتي طلع فاضي أو تالف")
    duration = audio_duration(out_path)
    result = {"path": str(out_path), "duration_sec": duration,
              "provider": cfg["provider"], "model": cfg["model"], "voice": cfg["voice"]}
    if want_timing:
        al = (timing or {}).get("alignment") or {}
        words = []
        if al.get("characters"):
            words = words_from_alignment(al["characters"],
                                         al.get("character_start_times_seconds") or [],
                                         al.get("character_end_times_seconds") or [])
        if words:
            result["words"], result["timing_source"] = words, "provider"
        else:
            result["words"], result["timing_source"] = estimate_words(text, duration), "estimated"
    return result
