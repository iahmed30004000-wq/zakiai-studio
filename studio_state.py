"""
حالات محطات الاستوديو الإحدى عشر لكل سيناريو.

الحالات: not_started · running · awaiting_choice · approved · failed · stale
القواعد (بتنفرض بالخادم مش بالواجهة):
  ١. ما محطة بتصير running قبل ما تكون اللي قبلها approved — خصوصاً ما في صورة قبل صوت معتمد.
  ٢. الرجوع لمحطة سابقة مسموح دايماً؛ بيعلّم اللاحقة stale بدون حذف شي.
  ٣. كل انتقال بيتسجّل بسجل أحداث.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config

STATIONS = {
    1: ("brief", "البريف"),
    2: ("script", "السيناريو"),
    3: ("character", "الشخصية"),
    4: ("voice", "الفويس أوفر"),
    5: ("timeline", "الخط الزمني"),
    6: ("shot_prompts", "برومبتات اللقطات"),
    7: ("images", "الصور"),
    8: ("match_check", "فحص التطابق"),
    9: ("motion", "التحريك"),
    10: ("edit", "الآهات والمونتاج"),
    11: ("launch", "الإطلاق"),
}
STATES = ("not_started", "running", "awaiting_choice", "approved", "failed", "stale")
_ACTIVE = ("running", "awaiting_choice", "failed")     # الرجوع لمحطة معتمدة بيدخل واحدة منها


class StationBlocked(Exception):
    """محاولة تشغيل محطة قبل اعتماد اللي قبلها."""


def path_for(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "studio" / stem / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fresh() -> dict:
    return {"stations": {str(n): {"state": "not_started", "updated_at": None, "note": ""}
                         for n in STATIONS}, "events": []}


def load(stem: str) -> dict:
    p = path_for(stem)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            base = _fresh()
            base["stations"].update(data.get("stations") or {})
            base["events"] = data.get("events") or []
            return base
        except json.JSONDecodeError:
            pass
    return _fresh()


def _save(stem: str, st: dict) -> None:
    p = path_for(stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def state_of(stem: str, n: int) -> str:
    return load(stem)["stations"][str(n)]["state"]


def can_start(stem: str, n: int) -> tuple[bool, str]:
    if n not in STATIONS:
        return False, "محطة غير معروفة"
    if n == 1:
        return True, ""
    prev = load(stem)["stations"][str(n - 1)]["state"]
    if prev != "approved":
        return False, (f"محطة «{STATIONS[n][1]}» ما بتبدأ قبل اعتماد «{STATIONS[n - 1][1]}» "
                       f"(حالتها الآن: {prev})")
    return True, ""


def set_state(stem: str, n: int, state: str, note: str = "", by: str = "system") -> dict:
    if state not in STATES:
        raise ValueError(f"حالة غير معروفة: {state}")
    if n not in STATIONS:
        raise ValueError("محطة غير معروفة")
    st = load(stem)
    cur = st["stations"][str(n)]["state"]

    if state == "running":
        ok, why = can_start(stem, n)
        if not ok:
            raise StationBlocked(why)

    # الرجوع لمحطة كانت معتمدة: اللاحقة (غير الفاضية) بتصير stale — بدون حذف
    if cur == "approved" and state in _ACTIVE:
        for m in range(n + 1, len(STATIONS) + 1):
            if st["stations"][str(m)]["state"] not in ("not_started", "stale"):
                st["stations"][str(m)].update(state="stale", updated_at=_now(),
                                              note=f"تغيّرت «{STATIONS[n][1]}» بعد اعتمادها")
                st["events"].append({"at": _now(), "station": m, "from": "…", "to": "stale", "by": by})

    st["stations"][str(n)] = {"state": state, "updated_at": _now(), "note": note}
    st["events"].append({"at": _now(), "station": n, "from": cur, "to": state, "by": by, "note": note})
    _save(stem, st)
    return st


def summary(stem: str) -> list[dict]:
    st = load(stem)
    return [{"n": n, "key": key, "label": label, **st["stations"][str(n)]}
            for n, (key, label) in STATIONS.items()]


def derive_early(stem: str, script_path) -> dict:
    """
    يشتق المحطات ١–٣ من الواقع بدل ما نطلب اعتماداً يدوياً مكرراً:
      ١ البريف: اكتماله   ٢ السيناريو: مراجعة نظيفة   ٣ الشخصية: راوٍ بلا شخصية طالما
      مكتبة الشخصيات ما انبنت بعد (أول ما تنبني لازم اختيار صريح — بيتعلّم كذا بالملاحظة).
    """
    import brief
    import review_loop
    import review_script

    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    st = load(stem)

    def put(n, state, note):
        if st["stations"][str(n)]["state"] != state:
            set_state(stem, n, state, note)

    b = review_script.load_brief(script)
    if b is not None and brief.completeness(b)["ready"]:
        put(1, "approved", "البريف مكتمل")
    else:
        put(1, "failed", "البريف ناقص أو غير موجود")

    ok, why = review_loop.is_cleared(script_path)
    put(2, "approved" if ok else "failed", "مراجعة نظيفة" if ok else why)

    import characters
    if not characters.library_active():
        put(3, "approved", "راوٍ بلا شخصية — مكتبة الشخصيات لسا ما فيها شخصية جاهزة")
    elif characters.chosen(stem):
        put(3, "approved", "شخصية مختارة")
    else:
        cur = st["stations"]["3"]["state"]
        if cur in ("not_started", "approved", "stale"):     # كانت «راوٍ» أو ما اختار — لازم يختار
            put(3, "awaiting_choice", "اختر شخصية من ٣ مرشّحين")
    return summary(stem)
