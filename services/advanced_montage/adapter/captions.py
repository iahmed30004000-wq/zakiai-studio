"""الترجمة: كلمات بتوقيتها ← أسطر (صفحات) بحد أقصى حرف/سطر، بدون تقطيع أي كلمة."""

from __future__ import annotations

from .. import constants as C
from .text import latin_digits


def frame_of(ms: int, fps: int = C.FPS) -> int:
    """ملي ثانية ← رقم إطار (تقريب لأقرب إطار، نصف لفوق) بحساب صحيح بدون كسور عشرية."""
    return (int(ms) * fps + 500) // 1000


def build_captions(words: list[dict], total_ms: int, *, max_chars: int = C.CAPTION_MAX_CHARS,
                   max_words: int = C.CAPTION_MAX_WORDS, gap_ms: int = C.CAPTION_GAP_MS) -> list[dict]:
    """
    كل سطر: {id, text, start_ms, end_ms, start_frame, end_frame, words[{text,start_ms,end_ms}]}.
      · الكلمة ما بتنقسم أبداً: كلمة أطول من الحد بتاخد سطر لوحدها.
      · بنقطع عند علامة ترقيم أو وقفة أو تجاوز الحد.
      · الأسطر ما بتتداخل بالزمن، وكل الأرقام لاتينية.
    """
    clean: list[dict] = []
    for w in sorted(words or [], key=lambda x: (x.get("start_ms", 0), x.get("i", 0))):
        t = latin_digits(w.get("text", "")).strip()
        if not t:
            continue
        s = min(max(int(w["start_ms"]), 0), total_ms)
        e = min(max(int(w["end_ms"]), s), total_ms)
        clean.append({"text": t, "start_ms": s, "end_ms": e})

    groups: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(clean):
        if cur and len(" ".join(x["text"] for x in cur + [w])) > max_chars:
            groups.append(cur)
            cur = []
        cur.append(w)
        nxt = clean[i + 1] if i + 1 < len(clean) else None
        if (len(cur) >= max_words or w["text"][-1:] in C.CAPTION_PUNCT
                or (nxt and nxt["start_ms"] - w["end_ms"] > gap_ms)):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    lines: list[dict] = []
    for k, g in enumerate(groups):
        start, end = g[0]["start_ms"], g[-1]["end_ms"]
        nxt_start = groups[k + 1][0]["start_ms"] if k + 1 < len(groups) else total_ms
        end = max(end, min(nxt_start, end + C.CAPTION_EXTEND_MS))            # نمدّد النهاية شوي
        if end - start < C.CAPTION_MIN_MS:
            end = min(nxt_start, start + C.CAPTION_MIN_MS)
        end = max(end, g[-1]["end_ms"])
        if k + 1 < len(groups) and groups[k + 1][0]["start_ms"] > start:       # ما بنسمح بتداخل أسطر
            end = min(end, groups[k + 1][0]["start_ms"])
        lines.append({
            "id": f"c{k + 1:03d}", "text": " ".join(x["text"] for x in g),
            "start_ms": start, "end_ms": end,
            "start_frame": frame_of(start), "end_frame": frame_of(end),
            "words": [dict(x, end_ms=min(x["end_ms"], end)) for x in g],
        })
    return lines
