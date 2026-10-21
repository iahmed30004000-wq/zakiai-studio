"""
الهوكات: 3–5 افتتاحيات بديلة لكل سيناريو (دوال صافية، بلا قراءة ولا كتابة ملفات).

الفكرة: الهوك الأساسي دايماً = `hook_line` + بداية المشهد 1، فكل خط الإنتاج (صوت، صور، مونتاج، إطلاق) بيشتغل متل ما هو.
والبدائل بتتخزّن بجنبه بالسيناريو نفسه:

    hooks:      [{id, type, spoken, on_screen_text, visual, why}]      id = h1..h5
    hook_main:  id الهوك الأساسي (الافتراضي h1)
    _meta.hooks_requested: كم هوك انطلب وقت الكتابة

الهوك بيستبدل **افتتاحية المشهد 1 بس**: السطر المحكي الأول (hook_line) + نص الشاشة + الوصف البصري؛ وباقي كلام المشهد 1
(اللي بعد الهوك) وباقي المشاهد بتضل متل ما هي. لهيك نسخة الفيديو لهوك بديل = إنتاج مشهد 1 بس (مرحلة لاحقة).

السيناريوهات القديمة (بلا hooks) بتنقرأ كهوك واحد (hooks_of) وما بتنعاد كتابتها.
"""

from __future__ import annotations

import copy
import hashlib
import re

import config
import taxonomy

TYPES = taxonomy.HOOK_TYPES
MIN_HOOKS = 1
WPS_MIN, WPS_MAX = 2.0, 2.7          # نفس مدى النطق بالمراجع (review_script)
MAX_OSTEXT_WORDS = 5


def _words(text) -> int:
    return len([w for w in re.split(r"\s+", str(text or "").strip()) if w])


def clean_requested(n) -> int:
    """عدد الهوكات المطلوب: رقم صحيح بين 1 و HOOKS_MAX، وغير هيك الافتراضي."""
    top = int(getattr(config, "HOOKS_MAX", 5))
    try:
        v = int(n)
    except (TypeError, ValueError):
        return int(getattr(config, "HOOKS_DEFAULT", 3))
    return max(MIN_HOOKS, min(top, v))


def hook_id(i: int) -> str:
    return f"h{i}"


def _scene1(script: dict) -> dict:
    scenes = script.get("scenes") or []
    return scenes[0] if scenes and isinstance(scenes[0], dict) else {}


def _hook_row(hid, typ, spoken, on_screen_text="", visual="", why="") -> dict:
    return {"id": hid, "type": typ if typ in TYPES else "other", "spoken": str(spoken or "").strip(),
            "on_screen_text": str(on_screen_text or "").strip(), "visual": str(visual or "").strip(), "why": str(why or "").strip()}


# ═════════════════ القراءة ═════════════════
def hooks_of(script: dict) -> list[dict]:
    """كل هوكات السيناريو. القديم (بلا hooks) بيطلع هوك واحد مبني من hook_line والمشهد 1."""
    hooks = script.get("hooks")
    if isinstance(hooks, list) and hooks and all(isinstance(h, dict) and h.get("id") for h in hooks):
        return copy.deepcopy(hooks)
    s1 = _scene1(script)
    spoken = script.get("hook_line") or s1.get("voiceover") or ""
    return [_hook_row("h1", "other", spoken, s1.get("on_screen_text"), s1.get("visual"))]


def main_id(script: dict) -> str:
    ids = [h["id"] for h in hooks_of(script)]
    m = script.get("hook_main")
    return m if m in ids else ids[0]


def get(script: dict, hid: str) -> dict | None:
    return next((h for h in hooks_of(script) if h["id"] == hid), None)


def has_alternatives(script: dict) -> bool:
    return len(hooks_of(script)) > 1


def fingerprint(hook: dict) -> str:
    """بصمة نص الهوك: لو انغيّر بيصير فحصه المخزّن قديم."""
    raw = "|".join(" ".join(str(hook.get(k) or "").split()) for k in ("spoken", "on_screen_text", "visual"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def hook_values(script: dict) -> list[str]:
    """سطور الهوكات المحكية كلها (للسجل المانع للتكرار: حتى البدائل ما بتنعاد)."""
    out = [h["spoken"] for h in hooks_of(script) if h.get("spoken")]
    line = str(script.get("hook_line") or "").strip()
    if line and line not in out:
        out.insert(0, line)
    return out


# ═════════════════ التركيب ═════════════════
def split_scene1(script: dict) -> tuple[str, str]:
    """(سطر الهوك، باقي كلام المشهد 1). لو hook_line مش بداية كلام المشهد 1 بيرجع (كلام المشهد كامل، "")."""
    vo = str(_scene1(script).get("voiceover") or "").strip()
    line = str(script.get("hook_line") or "").strip()
    if line and vo.startswith(line):
        return line, vo[len(line):].strip()
    return vo, ""


def compose_scene1(script: dict, hid: str) -> dict:
    """المشهد 1 كما بيصير مع الهوك hid (الأساسي = المشهد الحالي بدون تغيير)."""
    h = get(script, hid)
    if h is None:
        raise KeyError(hid)
    s1 = copy.deepcopy(_scene1(script))
    if hid == main_id(script):
        return s1
    _, rest = split_scene1(script)
    s1["voiceover"] = f"{h['spoken']} {rest}".strip()
    s1["on_screen_text"] = h.get("on_screen_text") or ""
    if h.get("visual"):
        s1["visual"] = h["visual"]
    return s1


def as_script(script: dict, hid: str) -> dict:
    """نسخة من السيناريو كأنو الهوك hid هو الأساسي (مشهد 1 + hook_line مركّبين). بدون ما نلمس الأصل."""
    out = copy.deepcopy(script)
    h = get(script, hid)
    if h is None:
        raise KeyError(hid)
    if out.get("scenes"):
        out["scenes"][0] = compose_scene1(script, hid)
    out["hook_line"] = h["spoken"]
    out["hook_main"] = hid
    return out


def select_main(script: dict, hid: str) -> dict:
    """يجعل hid هو الهوك الأساسي: hook_line + المشهد 1 بيتبدّلوا، والأساسي القديم بيضل بديل (نصه محفوظ)."""
    old_id, hooks = main_id(script), hooks_of(script)
    if get(script, hid) is None:
        raise KeyError(hid)
    if hid == old_id:
        return copy.deepcopy(script)
    out = as_script(script, hid)
    old = next(h for h in hooks if h["id"] == old_id)
    s1 = _scene1(script)
    old.update({"spoken": split_scene1(script)[0] or old["spoken"],
                "on_screen_text": s1.get("on_screen_text") or old.get("on_screen_text", ""),
                "visual": s1.get("visual") or old.get("visual", "")})
    out["hooks"] = hooks
    return out


def sync_after_edit(old: dict, new: dict) -> dict:
    """
    بعد تعديل يدوي (hook_line أو المشهد 1): بيخلّي الهوك الأساسي والمشهد 1 متّسقين. بيرجّع نسخة معدّلة من new.
      · hook_line اتغيّر والمشهد 1 لسا بيبدأ بالقديم وما اتلمس ← بداية المشهد 1 بتصير الجديد (بنفس الباقي).
      · بعدها hooks[الأساسي] = السطر الحالي + نص الشاشة والوصف من المشهد 1 (المشهد 1 هو مصدر الأساسي).
    السيناريو بلا hooks (قديم) ما بيتلمس.
    """
    out = copy.deepcopy(new)
    s1 = _scene1(out)
    old_line, new_line = str(old.get("hook_line") or "").strip(), str(out.get("hook_line") or "").strip()
    old_vo, new_vo = str(_scene1(old).get("voiceover") or "").strip(), str(s1.get("voiceover") or "").strip()
    if s1 and new_line and new_line != old_line and old_line and new_vo == old_vo and old_vo.startswith(old_line):
        s1["voiceover"] = f"{new_line} {old_vo[len(old_line):].strip()}".strip()
    if isinstance(out.get("hooks"), list) and out["hooks"]:
        mid = main_id(out)
        for h in out["hooks"]:
            if h.get("id") == mid:
                h["spoken"] = new_line or h.get("spoken", "")
                h["on_screen_text"] = str(s1.get("on_screen_text") or "").strip()
                h["visual"] = str(s1.get("visual") or "").strip()
    return out


# ═════════════════ المعايرة بعد الكتابة ═════════════════
def normalize(script: dict, requested=None) -> dict:
    """
    رد الكاتب ← الشكل المعتمد: ids مرتّبة (h1..)، أنواع من القائمة المغلقة، حذف الفاضي والمكرر، قص الزيادة عن المطلوب،
    وh1 = الهوك الأساسي دايماً (سطره = hook_line، ونص الشاشة والوصف = من المشهد 1 لأنو المصدر للأساسي).
    رد بلا hooks (برومبت قديم) بيضل متل ما هو بهوك واحد.
    """
    out = copy.deepcopy(script)
    want = clean_requested(requested if requested is not None else (out.get("_meta") or {}).get("hooks_requested"))
    raw = out.get("hooks") if isinstance(out.get("hooks"), list) else []
    rows = [_hook_row("", str(h.get("type") or "").strip(), h.get("spoken") or h.get("hook_line"),
                      h.get("on_screen_text"), h.get("visual"), h.get("why"))
            for h in raw if isinstance(h, dict) and str(h.get("spoken") or h.get("hook_line") or "").strip()]
    if not rows:
        out.pop("hooks", None)
        out.pop("hook_main", None)
        return out
    line = str(out.get("hook_line") or "").strip() or rows[0]["spoken"]
    rows[0]["spoken"] = line                                       # الأساسي = hook_line (السجل والإطلاق بيقرأوه)
    uniq, seen = [], set()
    for r in rows:
        key = " ".join(r["spoken"].split())
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    rows = uniq[:want]
    for i, r in enumerate(rows, 1):
        r["id"] = hook_id(i)
    s1 = _scene1(out)
    if s1:                                                         # المشهد 1 هو مصدر الأساسي
        rows[0]["on_screen_text"] = str(s1.get("on_screen_text") or rows[0]["on_screen_text"] or "").strip()
        rows[0]["visual"] = str(s1.get("visual") or rows[0]["visual"] or "").strip()
    out["hooks"], out["hook_main"], out["hook_line"] = rows, "h1", line
    out.setdefault("_meta", {})["hooks_requested"] = want
    return out


# ═════════════════ الفحص ═════════════════
def check(script: dict, brief: dict | None = None) -> dict[str, list[dict]]:
    """
    فحص فوري بالكود لكل هوك (الأساسي والبدائل): {hook_id: [ملاحظات]}.
      · مدى النطق للمشهد 1 بعد التركيب · حد نص الشاشة · الادعاءات الممنوعة (claims.scan_script) · تكرار نص بين الهوكات.
    ملاحظات الأساسي بيفحصها المراجع العادي، فهون بنضيف بس اللي خاص بالهوكات (hook_id بكل ملاحظة).
    """
    import claims
    hooks = hooks_of(script)
    s1 = _scene1(script)
    dur = float(s1.get("duration_sec") or 0)
    out: dict[str, list[dict]] = {h["id"]: [] for h in hooks}
    main = main_id(script)
    seen: dict[str, str] = {}
    for h in hooks:
        hid, rows = h["id"], out[h["id"]]

        def add(sev, field, issue, evidence, fix, rule=False):
            rows.append({"severity": sev, "scene": 1, "field": field, "issue": issue, "evidence": evidence, "fix": fix,
                         "hook_id": hid, **({"rule": True} if rule else {})})

        if hid != main and not h.get("spoken"):
            add("blocker", "voiceover", "الهوك بلا سطر محكي", "", "اكتب السطر أو شيل الهوك")
            continue
        key = " ".join(h["spoken"].split())
        if key in seen:
            add("major", "voiceover", "نفس سطر هوك تاني", h["spoken"], "غيّر الصياغة أو شيل المكرر")
        seen.setdefault(key, hid)
        composed = compose_scene1(script, hid)
        if dur > 0 and hid != main:
            n = _words(composed.get("voiceover"))
            wps = n / dur
            if wps > WPS_MAX:
                add("blocker", "voiceover", f"المشهد 1 مع هالهوك أسرع من الممكن نطقه ({wps:.1f} كلمة/ث)",
                    f"{n} كلمة بـ{dur:g}ث", f"اختصر الهوك لـ{max(1, int(dur * WPS_MAX) - _words(split_scene1(script)[1]))} كلمة أو مدّد المشهد 1")
            elif wps < WPS_MIN and n:
                add("minor", "voiceover", f"المشهد 1 مع هالهوك أبطأ من الطبيعي ({wps:.1f} كلمة/ث)", f"{n} كلمة بـ{dur:g}ث", "زيد كلمات الهوك")
        ost = _words(h.get("on_screen_text"))
        if ost > MAX_OSTEXT_WORDS:
            add("major", "on_screen_text", f"نص الشاشة {ost} كلمات والحد {MAX_OSTEXT_WORDS}", h.get("on_screen_text") or "", "اختصره")
        if brief is not None and hid != main:
            for f in claims.scan_script(as_script(script, hid), brief):
                if f.get("field") == "hook_line" or (f.get("scene") == 1 and f.get("field") in ("voiceover", "on_screen_text")):
                    rows.append({**f, "scene": 1, "hook_id": hid})
    return out


def blockers(script: dict, brief: dict | None = None) -> dict[str, list[dict]]:
    """{hook_id: موانع} للهوكات اللي فيها مانع بس."""
    return {hid: [f for f in rows if f.get("severity") == "blocker"] for hid, rows in check(script, brief).items()
            if any(f.get("severity") == "blocker" for f in rows)}


# ═════════════════ للواجهة ═════════════════
def public(script: dict, brief: dict | None = None) -> dict:
    """الهوكات + أسماء الأنواع بالعربي + ملاحظات الفحص + حالة المراجعة المخزّنة (hooks_review) لكل هوك."""
    findings = check(script, brief)
    review = script.get("hooks_review") if isinstance(script.get("hooks_review"), dict) else {}
    main = main_id(script)
    rows = []
    for h in hooks_of(script):
        rv = review.get(h["id"]) or {}
        fresh = bool(rv) and rv.get("fp") == fingerprint(h)
        rows.append({**h, "type_label": TYPES.get(h["type"], "غير محدد"), "main": h["id"] == main,
                     "findings": findings.get(h["id"], []),
                     "blockers": sum(1 for f in findings.get(h["id"], []) if f.get("severity") == "blocker"),
                     "ai": {"verdict": rv.get("verdict"), "note": rv.get("note") or "", "fresh": fresh} if rv else None})
    return {"hooks": rows, "main": main, "requested": (script.get("_meta") or {}).get("hooks_requested") or len(rows),
            "types": dict(TYPES), "max": int(getattr(config, "HOOKS_MAX", 5)), "legacy": not (isinstance(script.get("hooks"), list) and script.get("hooks"))}
