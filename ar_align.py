"""
مطابقة عربية: تفريغ صوتي (كلمات بتوقيتها) مع نص مكتوب، وتقسيم تسجيل لجمل — لتوزيع تسجيل صوت المالك على المشاهد.

  · norm: بنطبّع الكلمة قبل المقارنة (تشكيل، تطويل، أ/إ/آ←ا، ى←ي، ة←ه، ؤ←و، ئ←ي، الأرقام، علامات الترقيم).
  · align: كل كلمة مكتوبة بتاخد توقيتها من الكلمة المسموعة المطابقة: تامة، ثم بلا السوابق (و/ف/ب/ل/ك/ال)، ثم تقريبية.
    اللي ما تطابق بيتوزّع بين جيرانه حسب طول الكلمة. coverage = نسبة الكلمات اللي طابقت فعلاً (مش الموزّعة).
  · spans / cut_points: مدى كل مشهد بالثواني، وحدود القص (بلا صمت طويل بين المشاهد).
  · sentences: جمل من التفريغ حسب الوقفات وعلامات الترقيم (دمج القصير، وتقسيم الطويل).
  · assign_by_time: توزيع الجمل على مشاهد حسب مدد المشاهد.

الأزمنة كلها بالثواني (متل stt.transcribe)، والكلمات {"text","start","end"}. بلا أي شبكة ولا ffmpeg: دوال صافية.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_DIAC = re.compile("[ً-ٰٟۖ-ۭـ]")                  # تشكيل + ألف خنجرية + علامات قرآنية + تطويل
_TR = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ی": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ڤ": "ف", "پ": "ب", "چ": "ج", "گ": "ك", "ک": "ك",
    **{c: str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}, **{c: str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")},
})
_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال", "و", "ف", "ب", "ل", "ك", "س")
STRONG_END = ".!؟?؛…۔"
FUZZY_MIN = 0.75
FUZZY_WINDOW = 6


def norm(token) -> str:
    """كلمة مطبّعة للمقارنة (فاضية لو كانت علامة ترقيم بس)."""
    t = _DIAC.sub("", str(token or "").lower()).translate(_TR)
    return re.sub(r"[^\w]|_", "", t)


def stem(n: str) -> str:
    """بلا سابقة واحدة: «والدنيا» و«الدنيا» و«دنيا» ← «دنيا». سابقة الحرف الواحد (و/ف/ب/ل/ك/س) بشرط يبقى 3 أحرف على الأقل
    (عشان «ولد» ما تصير «لد»)، و«ال» وأخواتها حرفين."""
    for p in _PREFIXES:
        if n.startswith(p) and len(n) - len(p) >= (3 if len(p) == 1 else 2):
            return n[len(p):]
    return n


def words_of(text: str) -> list[str]:
    """كلمات النص كما هي (بعلامات الترقيم الملصوقة): هي نفسها اللي بتنعرض بالترجمة."""
    return str(text or "").split()


# ── المطابقة ────────────────────────────────────────────────────────────
def _matcher_keys(keys: list[str], tag: str) -> list[str]:
    return [k or f"\x00{tag}{i}" for i, k in enumerate(keys)]            # الفاضي ما بيتطابق مع فاضي


def _fill(s: list[str], a: list[str], match: list, how: list, s_lo: int, s_hi: int, a_lo: int, a_hi: int) -> None:
    """مطابقة مرنة جوّا فجوة بين مرساتين: أول بلا السوابق، وبعدين تقريبية بالترتيب."""
    if s_lo >= s_hi or a_lo >= a_hi:
        return
    ss, aa = [stem(x) if x else "" for x in s[s_lo:s_hi]], [stem(x) if x else "" for x in a[a_lo:a_hi]]
    sm = SequenceMatcher(None, _matcher_keys(ss, "s"), _matcher_keys(aa, "a"), autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            i, j = s_lo + blk.a + k, a_lo + blk.b + k
            if s[i] and match[i] is None:
                match[i], how[i] = j, "flex"
    # تقريبية (إملاء مختلف شوي) بين اللي طابق، بنفس الترتيب
    anchors = [(-1, a_lo - 1)] + [(i, match[i]) for i in range(s_lo, s_hi) if match[i] is not None] + [(s_hi, a_hi)]
    for (i0, j0), (i1, j1) in zip(anchors, anchors[1:]):
        cursor = j0 + 1
        for i in range(i0 + 1, i1):
            if match[i] is not None or len(s[i]) < 3:
                continue
            best, bj = FUZZY_MIN, None
            for j in range(cursor, min(j1, cursor + FUZZY_WINDOW)):
                if len(a[j]) < 3:
                    continue
                r = SequenceMatcher(None, s[i], a[j]).ratio()
                if r >= best:
                    best, bj = r, j
            if bj is not None:
                match[i], how[i] = bj, "fuzzy"
                cursor = bj + 1


def align(script_words: list[str], asr_words: list[dict], duration: float | None = None) -> dict:
    """بيرجّع {"words": [{i, word, start, end, how}], "coverage": 0..1, "matched": n, "total": n}.
    how: exact | flex | fuzzy | interp (موزّعة بين جيرانها). start/end بالثواني."""
    n, m = len(script_words), len(asr_words)
    if not n:
        return {"words": [], "coverage": 0.0, "matched": 0, "total": 0}
    s = [norm(w) for w in script_words]
    a = [norm(w.get("text")) for w in asr_words]
    match: list = [None] * n
    how = ["interp"] * n
    if m:
        sm = SequenceMatcher(None, _matcher_keys(s, "s"), _matcher_keys(a, "a"), autojunk=False)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                if s[blk.a + k]:
                    match[blk.a + k], how[blk.a + k] = blk.b + k, "exact"
        anchors = [(-1, -1)] + [(i, match[i]) for i in range(n) if match[i] is not None] + [(n, m)]
        for (i0, j0), (i1, j1) in zip(anchors, anchors[1:]):
            _fill(s, a, match, how, i0 + 1, i1, j0 + 1, j1)
    # أزمنة: المطابق ياخد زمن كلمته، والباقي بيتوزّع بين جيرانه
    first = float(asr_words[0]["start"]) if m else 0.0
    last = max(float(asr_words[-1]["end"]) if m else 0.0, float(duration or 0.0))
    out: list[dict | None] = [None] * n
    for i in range(n):
        if match[i] is not None:
            w = asr_words[match[i]]
            out[i] = {"i": i, "word": script_words[i], "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3), "how": how[i]}
    i = 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        lo = out[i - 1]["end"] if i > 0 else first
        hi = out[j]["start"] if j < n else last
        hi = max(hi, lo)
        weights = [len(script_words[k]) + 1 for k in range(i, j)]
        tot, t = float(sum(weights)), lo
        for k, wt in zip(range(i, j), weights):
            d = (hi - lo) * wt / tot
            out[k] = {"i": k, "word": script_words[k], "start": round(t, 3), "end": round(t + d, 3), "how": "interp"}
            t += d
        i = j
    real = [i for i in range(n) if s[i]]
    matched = sum(1 for i in real if match[i] is not None)
    return {"words": out, "coverage": round(matched / len(real), 3) if real else 0.0, "matched": matched, "total": len(real)}


# ── مدى المشاهد وحدود القص ──────────────────────────────────────────────
def spans(timing: list[dict], counts: list[int]) -> list[tuple[float, float] | None]:
    """مدى كل مشهد (بداية أول كلمة، نهاية آخر كلمة) من توقيت الكلمات المرتبة. counts[k] = عدد كلمات المشهد k (0 = بلا كلام ← None)."""
    out, pos = [], 0
    for c in counts:
        if c <= 0:
            out.append(None)
            continue
        part = timing[pos:pos + c]
        pos += c
        out.append((min(w["start"] for w in part), max(w["end"] for w in part)) if part else None)
    return out


def cut_points(sp: list[tuple[float, float] | None], total: float, lead: float = 0.2, tail: float = 0.35) -> list[tuple[float, float] | None]:
    """حدود قص كل مشهد: بنزيد شوي قبل أول كلمة (lead) وبعد آخر كلمة (tail) بحدود نص الفجوة، فالصمت الطويل بين المشاهد بينشال
    وما بيتداخل مشهدين. مشهد بلا كلام ← None."""
    voiced = [k for k, x in enumerate(sp) if x is not None]
    out: list[tuple[float, float] | None] = [None] * len(sp)
    if not voiced:
        return out
    total = float(total or max(sp[k][1] for k in voiced))
    prev_end = 0.0
    for pos, k in enumerate(voiced):
        st, en = sp[k]
        first, last = pos == 0, pos == len(voiced) - 1
        before = max(0.0, st - (0.0 if first else sp[voiced[pos - 1]][1]))
        after = max(0.0, (total if last else sp[voiced[pos + 1]][0]) - en)
        a = st - min(lead, before if first else before / 2)
        b = en + min(tail, after if last else after / 2)
        a = min(max(a, prev_end), st)                          # ما يتداخل مع المقطع اللي قبله
        b = max(min(b, total), en)
        out[k] = (round(a, 3), round(b, 3))
        prev_end = out[k][1]
    return out


# ── جمل من التفريغ ──────────────────────────────────────────────────────
def _sentence(ws: list[dict]) -> dict:
    return {"start": ws[0]["start"], "end": ws[-1]["end"], "text": " ".join(str(w["text"]).strip() for w in ws).strip(), "words": ws}


def _split_long(s: dict, max_len: float, min_part: float) -> list[dict]:
    ws = s["words"]
    if s["end"] - s["start"] <= max_len or len(ws) < 2:
        return [s]
    best, bk = -1.0, None
    for k in range(1, len(ws)):
        if ws[k - 1]["end"] - s["start"] < min_part or s["end"] - ws[k]["start"] < min_part:
            continue
        gap = ws[k]["start"] - ws[k - 1]["end"]
        if gap > best:
            best, bk = gap, k
    if bk is None:                                         # بلا وقفة صالحة: عند أقرب كلمة للنص
        mid = (s["start"] + s["end"]) / 2
        bk = min(range(1, len(ws)), key=lambda k: abs(ws[k]["start"] - mid))
    return _split_long(_sentence(ws[:bk]), max_len, min_part) + _split_long(_sentence(ws[bk:]), max_len, min_part)


def sentences(words: list[dict], pause: float = 0.6, min_len: float = 1.5, max_len: float = 8.0) -> list[dict]:
    """جمل [{start, end, text, words}] من كلمات مفرّغة: بتنقطع عند علامة نهاية (. ! ؟ ؛) أو وقفة ≥ pause؛ القصير (< min_len) بينضم
    لجارته، والطويل (> max_len) بينقسم عند أكبر وقفة داخله."""
    ws = [w for w in words if str(w.get("text", "")).strip()]
    if not ws:
        return []
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for k, w in enumerate(ws):
        cur.append(w)
        nxt = ws[k + 1] if k + 1 < len(ws) else None
        if nxt is None or str(w["text"]).rstrip()[-1:] in STRONG_END or float(nxt["start"]) - float(w["end"]) >= pause:
            groups.append(cur)
            cur = []
    out = [_sentence(g) for g in groups]
    merged: list[dict] = []
    for s in out:                                          # دمج القصير مع اللي بعده
        if merged and merged[-1]["end"] - merged[-1]["start"] < min_len:
            merged[-1] = _sentence(merged[-1]["words"] + s["words"])
        else:
            merged.append(s)
    if len(merged) > 1 and merged[-1]["end"] - merged[-1]["start"] < min_len:
        merged[-2:] = [_sentence(merged[-2]["words"] + merged[-1]["words"])]
    final: list[dict] = []
    for s in merged:
        final.extend(_split_long(s, max_len, min(1.0, min_len)))
    return final


def assign_by_time(sents: list[dict], durations: list[float], total: float | None = None) -> list[list[int]]:
    """بيوزّع الجمل على المشاهد حسب مددها: كل جملة بتروح للمشهد اللي بيغطي منتصفها بعد ما نمدّ مدد المشاهد على طول التسجيل.
    بيرجّع قائمة فهارس الجمل لكل مشهد (ممكن فاضية)."""
    n = len(durations)
    out: list[list[int]] = [[] for _ in range(n)]
    if not n or not sents:
        return out
    T = float(total or sents[-1]["end"])
    tot = float(sum(max(d, 0.0) for d in durations)) or float(n)
    bounds, acc = [], 0.0
    for d in durations:
        acc += (max(d, 0.0) if sum(durations) > 0 else 1.0)
        bounds.append(acc / tot * T)
    for i, s in enumerate(sents):
        c = (s["start"] + s["end"]) / 2
        k = next((k for k, b in enumerate(bounds) if c <= b), n - 1)
        out[k].append(i)
    return out


def balanced(sents: list[dict], n: int) -> list[list[int]]:
    """جمل التسجيل موزّعة على n مجموعات متقاربة المدة وبترتيبها: كل حدّ بين مجموعتين بيروح لأقرب نهاية جملة للحدّ المثالي
    (كل مجموعة جملة على الأقل لو في جمل ≥ n)."""
    if n <= 0:
        return []
    if not sents:
        return [[] for _ in range(n)]
    if len(sents) <= n:
        return [[i] for i in range(len(sents))] + [[] for _ in range(n - len(sents))]
    t0 = sents[0]["start"]
    total = sents[-1]["end"] - t0
    cuts: list[int] = []
    lo = 0
    for k in range(n - 1):
        hi = len(sents) - (n - 1 - k) - 1                    # آخر فهرس بيخلّي جملة لكل مجموعة جاية
        b = t0 + total * (k + 1) / n
        i = min(range(lo, hi + 1), key=lambda j: abs(sents[j]["end"] - b))
        cuts.append(i)
        lo = i + 1
    out, start = [], 0
    for c in cuts + [len(sents) - 1]:
        out.append(list(range(start, c + 1)))
        start = c + 1
    return out
