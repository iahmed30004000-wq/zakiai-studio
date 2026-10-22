"""
توقيت الكلمات لصوت جاهز — للترجمة الكلمة بكلمة وحدود اللقطات.

المزوّدات المدمجة (ElevenLabs…) بترجّع التوقيت مع الصوت، بس الصوت اللي بييجي من الإضافة أو من نموذج بمكتبة النماذج غالباً لأ.
فبنفرّغ الصوت (stt.transcribe — ممكن يكون Whisper المدمج أو نموذج تفريغ مربوط بالمكتبة) ونربط كلمات التفريغ بكلمات النص الأصلي
(اللي بتظهر بالترجمة). إذا فشل التفريغ أو ما في مفتاح: تقدير بنسبة طول الكلمة، ومعلّم «estimated» بالمانيفست.

كان هالمنطق بـ ext_tasks (بيضل فيه اسمين قديمين بيشيروا لهون، لأن اختبارات بتبدّل ext_tasks._words).
"""

from __future__ import annotations

from pathlib import Path


def align_to_script(asr: list[dict], text: str, duration: float) -> list[dict]:
    """كلمات النص الأصلي (اللي بتظهر بالترجمة) بتوقيت التفريغ الصوتي.
    التفريغ ممكن يكتب الكلمة غير شكل (تشكيل/همزة/دمج كلمتين)، فبنربط بالترتيب: كل كلمة من النص بتاخد
    مجال الكلمات المقابلة إلها من التفريغ بالنسبة (أكتر من واحدة إذا التفريغ فيه كلمات أكتر)."""
    toks = text.split()
    m, n = len(asr), len(toks)
    if not toks or not m:
        return []
    out = []
    for i, tok in enumerate(toks):
        lo = i * m // n
        hi = max(lo, -(-(i + 1) * m // n) - 1)              # سقف القسمة
        st = float(asr[lo]["start"])
        en = float(asr[min(hi, m - 1)]["end"])
        st = min(max(st, 0.0), duration)
        en = min(max(en, st), duration)
        out.append({"text": tok, "start": round(st, 3), "end": round(en, 3)})
    for a, b in zip(out, out[1:]):                           # ما يتداخلوا: نهاية الكلمة ≤ بداية اللي بعدها
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    return out


def words_for(audio: Path, text: str, duration: float) -> tuple[list[dict], str]:
    """كلمات بتوقيتها: التفريغ الصوتي أولاً، وإذا فشل أو ما في مفتاح ← تقدير بنسبة طول الكلمة. بيرجّع (الكلمات، المصدر: stt|estimated)."""
    import tts
    try:
        import stt
        res = stt.transcribe(audio)
        if res.get("words"):                                  # توقيت كل كلمة (Whisper المحلي أو نموذج تفريغ مربوط)
            aligned = align_to_script(res["words"], text, duration)
            if aligned:
                return aligned, "stt"
        words = []
        for seg in res.get("segments", []):
            s, e = float(seg["start"]), float(seg["end"])
            toks = " ".join(str(seg.get("text", "")).split())
            for w in tts.estimate_words(toks, max(e - s, 0.01)):
                st = min(s + w["start"], duration)
                words.append({"text": w["text"], "start": round(st, 3), "end": round(min(max(s + w["end"], st), duration), 3)})
        if words:
            return words, "stt"
    except Exception:                                         # noqa: BLE001 — أي خلل بالتفريغ: منقدّر
        pass
    return tts.estimate_words(text, duration), "estimated"
