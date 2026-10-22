"""
الخط الزمني المربوط بالصوت — المحطة ٥.

الصوت المعتمد هو الساعة الوحيدة: مدة كل مشهد ولقطة وحركة مشتقة منه، وكل حد لقطة
بيقع على بداية كلمة. مشهد ← لقطة ← مدى كلمات.

ملف واحد لكل سيناريو: library/timelines/<stem>/timeline.json (مسارات نسبية).
القيود بتنفرض بـ validate() عند كل حفظ — الواجهة ما بتقدر تخرقها.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import config

SCHEMA = 1
PUNCT_END = "،,.؟?!:;؛"
SHOT_TYPES = ("close", "medium", "wide", "hand_product")


class TimelineError(Exception):
    pass


def _ms(sec) -> int:
    return int(round(float(sec) * 1000))


def _max_shot_ms() -> int:
    return _ms(getattr(config, "STUDIO_MAX_SHOT_SEC", 3.0))


def _max_shots() -> int:
    return int(getattr(config, "STUDIO_MAX_SHOTS_PER_SCENE", 3))


def path_for(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "timelines" / stem / "timeline.json"


# ── التقسيم ─────────────────────────────────────────────────────────────
def split_scene(words: list[dict], start: int, end: int, max_shot_ms: int,
                max_shots: int) -> list[tuple[int, int, int, int]]:
    """
    يقسم مشهد للقطات. بيرجّع [(start_ms, end_ms, first_word_idx, last_word_idx)] بفهارس
    محلية (0..len(words)-1). الحدود على بدايات كلمات، وقرب التقسيم المتساوي مع تفضيل
    فاصل طبيعي (صمت قبل الكلمة أو علامة ترقيم قبلها).
    """
    dur = end - start
    n = min(max_shots, max(1, math.ceil(dur / max_shot_ms)), len(words))
    if n <= 1:
        return [(start, end, 0, len(words) - 1)]

    cuts: list[int] = []            # فهرس أول كلمة بكل لقطة بعد الأولى
    prev_idx, prev_ms = 0, start
    for k in range(1, n):
        target = start + dur * k / n
        best, best_cost = None, None
        for j in range(prev_idx + 1, len(words) - (n - k) + 1):
            ws = words[j]["start_ms"]
            if ws <= prev_ms:       # لقطة بمدة صفر ممنوعة
                continue
            gap = ws - words[j - 1]["end_ms"]
            bonus = min(max(gap, 0), 300) * 0.5
            if words[j - 1]["text"][-1:] in PUNCT_END:
                bonus += 200
            cost = abs(ws - target) - bonus
            if best_cost is None or cost < best_cost:
                best, best_cost = j, cost
        if best is None:            # ما في مكان صالح — بنقلّل عدد اللقطات
            break
        cuts.append(best)
        prev_idx, prev_ms = best, words[best]["start_ms"]

    bounds = [start] + [words[j]["start_ms"] for j in cuts] + [end]
    firsts = [0] + cuts
    out = []
    for i, f in enumerate(firsts):
        last = (firsts[i + 1] - 1) if i + 1 < len(firsts) else len(words) - 1
        out.append((bounds[i], bounds[i + 1], f, last))
    return out


# ── البناء ──────────────────────────────────────────────────────────────
def build(script: dict, voice: dict, *, script_hash: str = "", audio_rel: str = "",
          approved_at: str = "", audio_sha256: str = "") -> dict:
    """
    يبني الخط الزمني من مانيفست الصوت (voice.json). كل مشهد بلا كلام أو بلا توقيت كلمات
    = خطأ صريح، مش لقطة يتيمة.
    """
    vs = {s["scene"]: s for s in voice.get("scenes", [])}
    smeta = {s.get("scene_number"): s for s in script.get("scenes", [])}
    if not vs:
        raise TimelineError("ما في صوت مولّد")

    max_shot, max_shots = _max_shot_ms(), _max_shots()
    words: list[dict] = []
    scenes: list[dict] = []
    t = 0
    for n in sorted(vs):
        v = vs[n]
        dur = _ms(v["duration_sec"])
        s0, s1 = t, t + dur
        first = len(words)
        local: list[dict] = []
        last_start = s0
        for w in v.get("words") or []:
            ws = max(s0 + _ms(w["start"]), last_start)
            we = min(max(s0 + _ms(w["end"]), ws), s1)
            last_start = ws
            local.append({"i": len(words) + len(local), "text": w["text"],
                          "start_ms": min(ws, s1), "end_ms": we, "scene": n})
        if not local:
            raise TimelineError(f"مشهد {n}: ما في كلمات بتوقيتها — ما بنقدر نربط لقطات")
        words.extend(local)
        m = smeta.get(n, {})
        shots = []
        for k, (a, b, fi, la) in enumerate(split_scene(local, s0, s1, max_shot, max_shots), 1):
            shots.append({
                "id": f"s{n}c{k}", "start_ms": a, "end_ms": b,
                "word_range": [local[fi]["i"], local[la]["i"]],
                "type": (m.get("shot_type") if k == 1 and m.get("shot_type") in SHOT_TYPES else "medium"),
                "prompt_ar": "", "prompt_model": "",
                "refs": {"character_id": None, "product_ref": None},
                "image": {"candidates": [], "chosen": None, "upscaled": False, "path_used": None},
                "product_check": None, "face_check": None, "motion": None,
            })
        scenes.append({
            "n": n, "start_ms": s0, "end_ms": s1,
            "word_range": [first, len(words) - 1],
            "function": m.get("purpose"), "emotion": m.get("emotion"),
            "voiceover": m.get("voiceover") or v.get("text"), "shots": shots,
        })
        t = s1

    return {
        "schema": SCHEMA,
        "script_id": (script.get("_meta") or {}).get("script_id"),
        "script_hash": script_hash,
        "voice": {
            "provider": voice.get("provider"), "model": voice.get("model"),
            "voice_id": voice.get("voice"), "character_id": None,
            "audio": audio_rel or ((voice.get("combined") or {}).get("path")),
            "duration_ms": t, "approved_at": approved_at, "sha256": audio_sha256,
            "timing_source": ("estimated" if any(
                (s.get("timing_source") == "estimated") for s in voice["scenes"]) else "provider"),
        },
        "words": words,
        "scenes": scenes,
        "ambience": None,
        "captions": None,
        "checks_approved_by_owner": {},
    }


# ── التحقق ──────────────────────────────────────────────────────────────
# المشروع الحر (mode == "free"): بلا قيد 7 مشاهد ولا 45–50 ث ولا حدود كلمات — اللقطات هي الساعة.
FREE_MAX_SCENES = 40
FREE_MAX_SHOTS = 8
FREE_MIN_SHOT_MS = 500
FREE_MAX_SHOT_MS = 60_000
FREE_MAX_TOTAL_MS = 300_000


def is_free(tl: dict | None) -> bool:
    return bool(tl) and tl.get("mode") == "free"


def _validate_free(tl: dict) -> dict:
    """خط زمني حر: مشاهد 0–40، لقطات 1–8 بالمشهد، لقطة 0.5–60ث، المجموع ≤ 300ث، كل شي متصل بالـ ms ومعرّفات فريدة."""
    errors: list[dict] = []
    warnings: list[dict] = []

    def err(code, msg, scene=None, shot=None):
        errors.append({"code": code, "scene": scene, "shot": shot, "message": msg})

    def warn(code, msg, scene=None, shot=None):
        warnings.append({"code": code, "scene": scene, "shot": shot, "message": msg})

    scenes = tl.get("scenes") or []
    if not scenes:
        warn("no_scenes", "ما في مشاهد بعد — ضيف مشهد أو استورد نص")
    if len(scenes) > FREE_MAX_SCENES:
        err("scene_count", f"عدد المشاهد {len(scenes)} أكتر من الحد ({FREE_MAX_SCENES})")

    seen_keys: set = set()
    seen_ids: set = set()
    prev_end = 0
    shots_total = 0
    for sc in scenes:
        n = sc.get("n")
        key = sc.get("key")
        if not key or key in seen_keys:
            err("scene_key", f"مشهد {n}: معرّف المشهد ناقص أو مكرّر", n)
        seen_keys.add(key)
        if sc.get("start_ms") != prev_end:
            err("scene_gap", f"مشهد {n}: فجوة/تداخل مع المشهد السابق", n)
        prev_end = sc.get("end_ms", prev_end)

        shots = sc.get("shots") or []
        if not 1 <= len(shots) <= FREE_MAX_SHOTS:
            err("shot_count", f"مشهد {n}: {len(shots)} لقطات، المسموح 1–{FREE_MAX_SHOTS}", n)
            continue
        cursor = sc.get("start_ms")
        for sh in shots:
            sid = sh.get("id")
            if not sid or sid in seen_ids:
                err("shot_id", f"لقطة {sid}: معرّف ناقص أو مكرّر", n, sid)
            seen_ids.add(sid)
            a, b = sh.get("start_ms"), sh.get("end_ms")
            if a != cursor:
                err("shot_gap", f"لقطة {sid}: فجوة أو تداخل مع اللي قبلها", n, sid)
            if a is None or b is None or b <= a:
                err("shot_zero", f"لقطة {sid}: مدة صفر أو سالبة", n, sid)
                cursor = b if b is not None else cursor
                continue
            dur = b - a
            cursor = b
            shots_total += dur
            if dur < FREE_MIN_SHOT_MS:
                err("shot_short", f"لقطة {sid}: {dur / 1000:.1f}ث أقصر من الحد ({FREE_MIN_SHOT_MS / 1000:.1f}ث)", n, sid)
            if dur > FREE_MAX_SHOT_MS:
                err("shot_long", f"لقطة {sid}: {dur / 1000:.0f}ث أطول من الحد ({FREE_MAX_SHOT_MS // 1000}ث)", n, sid)
            im, mo = sh.get("image") or {}, sh.get("motion")
            if not (im.get("chosen") or (mo or {}).get("clip")):
                warn("shot_no_media", f"لقطة {sid}: بلا صورة أو فيديو", n, sid)
            if mo and mo.get("duration_ms") not in (None, dur):
                warn("motion_duration", f"لقطة {sid}: مدة الفيديو ≠ مدة اللقطة (بيتجمّد آخر كادر أو بيتقصّ)", n, sid)
        if cursor != sc.get("end_ms"):
            err("scene_end", f"مشهد {n}: لقطاته ما بتنتهي بنهاية المشهد", n)
        v = sc.get("voice") or {}
        if v.get("duration_ms") and v["duration_ms"] > (sc.get("end_ms", 0) - sc.get("start_ms", 0)) + 150:
            warn("voice_long", f"مشهد {n}: الصوت أطول من المشهد (بيتقصّ)", n)

    total = tl.get("length_ms") or 0
    if scenes and shots_total != total:
        err("sum_mismatch", f"مجموع مدد اللقطات {shots_total}ms ≠ طول الفيديو {total}ms")
    if total > FREE_MAX_TOTAL_MS:
        err("total_long", f"الفيديو {total / 1000:.0f}ث أطول من الحد ({FREE_MAX_TOTAL_MS // 1000}ث)")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def validate(tl: dict) -> dict:
    """{ok, errors:[{code, scene, shot, message}], warnings:[…]} — كل الرسائل عربي."""
    if is_free(tl):
        return _validate_free(tl)
    errors: list[dict] = []
    warnings: list[dict] = []

    def err(code, msg, scene=None, shot=None):
        errors.append({"code": code, "scene": scene, "shot": shot, "message": msg})

    def warn(code, msg, scene=None, shot=None):
        warnings.append({"code": code, "scene": scene, "shot": shot, "message": msg})

    words = tl.get("words") or []
    scenes = tl.get("scenes") or []
    total = (tl.get("voice") or {}).get("duration_ms") or 0
    lo, hi = _ms(config.SCRIPT_MIN_SEC), _ms(config.SCRIPT_MAX_SEC)

    if len(scenes) != config.SCRIPT_SCENES:
        err("scene_count", f"عدد المشاهد {len(scenes)} والمطلوب {config.SCRIPT_SCENES} بالضبط")
    if not lo <= total <= hi:
        err("voice_duration", f"مدة الصوت {total / 1000:.1f}ث خارج {config.SCRIPT_MIN_SEC}–{config.SCRIPT_MAX_SEC}ث")

    max_shot = _max_shot_ms()
    prev_end = 0
    shots_total = 0
    expected_word = 0
    for sc in scenes:
        n = sc.get("n")
        if sc.get("start_ms") != prev_end:
            err("scene_gap", f"مشهد {n}: فجوة/تداخل مع المشهد السابق", n)
        prev_end = sc.get("end_ms", prev_end)

        shots = sc.get("shots") or []
        if not 1 <= len(shots) <= _max_shots():
            err("shot_count", f"مشهد {n}: {len(shots)} لقطات، المسموح 1–{_max_shots()}", n)
            continue
        wr = sc.get("word_range") or [0, -1]
        if wr[0] != expected_word:
            err("word_gap", f"مشهد {n}: كلماته ما بتبدأ بعد كلمات السابق مباشرة", n)
        expected_word = wr[1] + 1

        cursor, word_cursor = sc["start_ms"], wr[0]
        for k, sh in enumerate(shots):
            sid = sh.get("id")
            a, b = sh.get("start_ms"), sh.get("end_ms")
            if a != cursor:
                err("shot_gap", f"لقطة {sid}: فجوة أو تداخل مع اللي قبلها", n, sid)
            if b is None or a is None or b <= a:
                err("shot_zero", f"لقطة {sid}: مدة صفر أو سالبة", n, sid)
            cursor = b if b is not None else cursor
            shots_total += (b - a) if (a is not None and b is not None) else 0

            r = sh.get("word_range") or [0, -1]
            if r[1] < r[0]:
                err("shot_no_words", f"لقطة {sid}: بلا كلمات تغطيها", n, sid)
                continue
            if r[0] != word_cursor:
                err("shot_words", f"لقطة {sid}: مدى الكلمات مش متصل بالسابق", n, sid)
            word_cursor = r[1] + 1
            if k > 0 and 0 <= r[0] < len(words) and a != words[r[0]]["start_ms"]:
                err("shot_boundary", f"لقطة {sid}: حدّها مش على بداية كلمة", n, sid)
            if b is not None and a is not None and (b - a) > max_shot + 1:
                warn("shot_long", f"لقطة {sid}: {(b - a) / 1000:.1f}ث فوق الحد {max_shot / 1000:.1f}ث", n, sid)
            mo = sh.get("motion")
            if mo and a is not None and b is not None and mo.get("duration_ms") != b - a:
                err("motion_duration", f"لقطة {sid}: مدة الحركة لازم تساوي مدة اللقطة بالضبط", n, sid)
        if shots and cursor != sc["end_ms"]:
            err("scene_end", f"مشهد {n}: لقطاته ما بتنتهي بنهاية المشهد", n)
        if word_cursor != wr[1] + 1:
            err("scene_words", f"مشهد {n}: كلمات لقطاته ما بتغطي كلمات المشهد", n)

    if scenes and shots_total != total:
        err("sum_mismatch", f"مجموع مدد اللقطات {shots_total}ms ≠ مدة الصوت {total}ms")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ── تعديل حد لقطة ───────────────────────────────────────────────────────
def move_boundary(tl: dict, scene_n: int, shot_index: int, to_ms: int) -> dict:
    """
    يحرّك الحد بين لقطة `shot_index` واللي بعدها (١-based) ويلصقه بأقرب بداية كلمة
    ضمن نفس المشهد، وبيحافظ على كلمة على الأقل بكل لقطة.
    """
    sc = next((s for s in tl["scenes"] if s["n"] == scene_n), None)
    if not sc:
        raise TimelineError(f"مشهد {scene_n} مش موجود")
    shots = sc["shots"]
    if not 1 <= shot_index < len(shots):
        raise TimelineError("ما في حد بهالموقع")
    left, right = shots[shot_index - 1], shots[shot_index]
    words = tl["words"]
    lo_i, hi_i = left["word_range"][0] + 1, right["word_range"][1]   # فهارس كلمات مسموح تبدأ اللقطة اليمنى
    cands = [i for i in range(lo_i, hi_i + 1)]
    if not cands:
        raise TimelineError("ما بيصير تحريك: لقطة لازم تضل فيها كلمة")
    j = min(cands, key=lambda i: abs(words[i]["start_ms"] - to_ms))
    b = words[j]["start_ms"]
    left["end_ms"], right["start_ms"] = b, b
    left["word_range"][1], right["word_range"][0] = j - 1, j
    for sh in (left, right):
        if sh.get("motion"):
            sh["motion"] = None         # مدة الحركة تغيّرت — لازم تنعاد
    return tl


# ── حفظ/تحميل ───────────────────────────────────────────────────────────
def save(stem: str, tl: dict, *, allow_invalid: bool = False) -> dict:
    res = validate(tl)
    if not res["ok"] and not allow_invalid:
        raise TimelineError("خط زمني غير صالح: " + " | ".join(e["message"] for e in res["errors"][:3]))
    p = path_for(stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def load(stem: str) -> dict | None:
    p = path_for(stem)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
