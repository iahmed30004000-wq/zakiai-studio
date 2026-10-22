#!/usr/bin/env python3
"""
الحركات السينمائية — مكتبة «وصفات» حركة (كاميرا · منتج · شخصية) بأسماء عربية، بنيناها عنا بديل قسم Higgsfield.

كل وصفة = كلام لكل عائلة موديل (hailuo · kling · … وdefault للباقي)، المدة الأنسب، نوع اللقطات المناسب، وهل فيها حركة كاميرا
(حركة الكاميرا بتتعارض مع «صورة النهاية» اللي بنستعملها لتثبيت الوجه). الوصفات ملف بسيط بلا كود:

    presets/camera_presets.json          الوصفات الجاهزة (مرفوعة مع النظام) + جداول الكاميرا/العدسات (MIT، third_party/open-generative-ai/NOTICE)
    library/camera_presets.json          إضافات المالك وتعديلاته (نفس المعرّف = بيغلب الجاهزة؛ حذفه بيرجّع الجاهزة)
    library/presets/examples/<id>.mp4    فيديو مثال صغير من شغلنا (أول مرة بتتطبّق الوصفة) + examples.json

التطبيق على لقطة: shot["camera_preset"] = {id, look, at} + shot["motion_desc"] = وصف عربي (للموديلات المحلية)؛ وبوقت التشغيل
motion.build_prompt_en بياخد وصفة عائلة الموديل (Hailuo: أمر بين أقواس + جملة؛ Kling: جملة طبيعية). الجداول الجاهزة فيها الأوامر
الـ 15 لـ Hailuo Director — على Hailuo 02 مش مؤكَّدة رسمياً فبنحط معها جملة طبيعية دايماً.

    python motion_presets.py            (بيطبع الوصفات)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import timeline

BASE_PATH = Path(config.BASE) / "presets" / "camera_presets.json"
FAMILIES = {"default": "عام (الباقي)", "hailuo": "Hailuo", "kling": "Kling", "grok": "Grok", "local": "موديل محلي"}
SHOT_TYPES = ("close", "medium", "wide", "hand_product")
PREFER_BONUS = 6.0                         # نقاط ترتيب لموديل من العائلة المفضّلة للوصفة (نقطة القوة = 10)
MAX_RECIPE = 400
ID_RX = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_AR = re.compile(r"[؀-ۿ]")


class PresetError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── الملفات ──────────────────────────────────────────────────────────────
def user_path() -> Path:
    return Path(config.LIBRARY_DIR) / "camera_presets.json"


def examples_dir() -> Path:
    return Path(config.LIBRARY_DIR) / "presets" / "examples"


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_user(data: dict) -> None:
    p = user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def base() -> dict:
    return _read(BASE_PATH, {"categories": [], "presets": [], "looks": {}})


def categories() -> list[dict]:
    return base().get("categories", [])


def looks() -> dict:
    return base().get("looks", {})


def _user_presets() -> list[dict]:
    d = _read(user_path(), {})
    return [p for p in (d.get("presets") if isinstance(d, dict) else []) or [] if isinstance(p, dict) and p.get("id")]


def all_presets() -> list[dict]:
    """الجاهزة (مع تعديلات المالك بنفس المعرّف) ثم وصفات المالك الجديدة. كل واحدة: custom (جديدة من المالك) وoverridden (جاهزة معدّلة)."""
    mine = {p["id"]: p for p in _user_presets()}
    out, seen = [], set()
    for p in base().get("presets", []):
        seen.add(p["id"])
        if p["id"] in mine:
            out.append({**mine[p["id"]], "custom": False, "overridden": True})
        else:
            out.append({**p, "custom": False, "overridden": False})
    for pid, p in mine.items():
        if pid not in seen:
            out.append({**p, "custom": True, "overridden": False})
    return out


def get(pid: str | None) -> dict | None:
    return next((p for p in all_presets() if p["id"] == pid), None)


# ── العائلة والوصفة ──────────────────────────────────────────────────────
def family_of(model: dict | None) -> str:
    """hailuo | kling | grok | local | default — من اسم الموديل/عنوان fal."""
    if not model:
        return "default"
    kind = model.get("kind", "command")
    if kind in ("command", "http"):
        return "local"
    hay = f"{model.get('name', '')} {(model.get('api') or {}).get('endpoint', '')}".lower()
    for key, words in (("hailuo", ("hailuo", "minimax")), ("kling", ("kling",)), ("grok", ("grok", "xai"))):
        if any(w in hay for w in words):
            return key
    return "default"


def recipe_text(preset: dict, family: str = "default") -> str:
    r = preset.get("recipes") or {}
    return str(r.get(family) or r.get("default") or "").strip()


def look_text(look: dict | None) -> str:
    """«الكاميرا والعدسة» ← جملة إنجليزية: shot on a …, using a … at 35mm (…), aperture f/4 (…). كل جزء اختياري."""
    if not isinstance(look, dict):
        return ""
    t = looks()
    by = lambda key, val: next((x for x in t.get(key, []) if str(x["id"]) == str(val)), None)    # noqa: E731
    cam, lens, foc, ap = by("cameras", look.get("camera")), by("lenses", look.get("lens")), by("focals", look.get("focal")), by("apertures", look.get("aperture"))
    parts = []
    if cam:
        parts.append(f"shot on a {cam['en']}")
    if lens or foc:
        s = f"using a {lens['en']}" if lens else "at"
        if foc:
            s += f" at {foc['mm']}mm ({foc['en']})" if lens else f" {foc['mm']}mm ({foc['en']})"
        parts.append(s)
    if ap:
        parts.append(f"aperture {ap['f']} ({ap['en']})")
    return ", ".join(parts)


def clean_look(look) -> dict:
    """بيحتفظ بالخيارات الصالحة بس (معرّفات من الجداول)."""
    if not isinstance(look, dict):
        return {}
    t = looks()
    out = {}
    for field, key in (("camera", "cameras"), ("lens", "lenses"), ("focal", "focals"), ("aperture", "apertures")):
        v = str(look.get(field) or "").strip()
        if v and any(str(x["id"]) == v for x in t.get(key, [])):
            out[field] = v
    return out


# ── تحقق وإدارة وصفات المالك ─────────────────────────────────────────────
def _check(data: dict, pid: str) -> dict:
    if not isinstance(data, dict):
        raise PresetError("بيانات الوصفة غير صالحة")
    cats = {c["id"] for c in categories()}
    out = {"id": pid}
    name = str(data.get("name_ar") or "").strip()
    if not 2 <= len(name) <= 40:
        raise PresetError("اسم الوصفة (2–40 حرف) مطلوب")
    out["name_ar"] = name
    cat = str(data.get("category") or "camera")
    if cat not in cats:
        raise PresetError("القسم: " + " أو ".join(sorted(cats)))
    out["category"] = cat
    desc = str(data.get("desc_ar") or "").strip()
    if len(desc) > 200:
        raise PresetError("الوصف أطول من 200 حرف")
    out["desc_ar"] = desc
    motion = str(data.get("motion_desc_ar") or desc or name).strip()
    if len(motion) > 300:
        raise PresetError("وصف الحركة (للموديلات المحلية) أطول من 300 حرف")
    out["motion_desc_ar"] = motion
    out["camera_move"] = bool(data.get("camera_move"))
    rec = data.get("recipes") if isinstance(data.get("recipes"), dict) else {}
    clean = {}
    for fam, text in rec.items():
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            continue
        if fam not in FAMILIES:
            raise PresetError("عائلة موديل غير معروفة: " + str(fam))
        if _AR.search(text):
            raise PresetError("كلام الكاميرا لازم يكون بالإنجليزي (الموديلات بتفهمه أدق)")
        if len(text) > MAX_RECIPE:
            raise PresetError(f"كلام الكاميرا أطول من {MAX_RECIPE} حرف")
        clean[fam] = text
    if not clean.get("default"):
        raise PresetError("لازم كلام الكاميرا «العام» (default) بالإنجليزي")
    out["recipes"] = clean
    try:
        lo, hi = (float(x) for x in (data.get("duration_s") or [3, 5])[:2])
    except (TypeError, ValueError):
        raise PresetError("المدة الأنسب: رقمين بالثواني")
    if not 1 <= lo <= hi <= 15:
        raise PresetError("المدة الأنسب بين 1 و15 ثانية")
    out["duration_s"] = [lo, hi]
    out["best_for"] = [t for t in (data.get("best_for") or list(SHOT_TYPES)) if t in SHOT_TYPES] or list(SHOT_TYPES)
    out["prefer"] = [f for f in (data.get("prefer") or []) if f in FAMILIES and f != "default"]
    return out


def _save_user(presets: list[dict]) -> None:
    _write_user({"presets": presets})


def _slug_id(name: str) -> str:
    base_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    base_id = ("custom_" + base_id) if base_id else "custom"
    existing = {p["id"] for p in all_presets()}
    pid, n = base_id[:36], 1
    while pid in existing:
        n += 1
        pid = f"{base_id[:32]}_{n}"
    return pid


def create(data: dict) -> dict:
    """وصفة جديدة من المالك (معرّفها بيتولّد لحاله)."""
    pid = _slug_id(str(data.get("name_en") or "")) if data.get("name_en") else _slug_id("")
    mine = _user_presets()
    new = _check(data, pid)
    mine.append(new)
    _save_user(mine)
    return get(pid)


def update(pid: str, data: dict) -> dict:
    """تعديل وصفة: الجديدة بتنحدّث، والجاهزة بتنحفظ نسخة معدّلة (override) وبيرجع الأصل بحذفها."""
    if not get(pid):
        raise PresetError("الوصفة غير موجودة")
    new = _check(data, pid)
    mine = [p for p in _user_presets() if p["id"] != pid] + [new]
    _save_user(mine)
    return get(pid)


def delete(pid: str) -> dict | None:
    """وصفة المالك بتنحذف؛ تعديله على جاهزة بينشال فبترجع الأصلية. الجاهزة الأصلية ما بتنحذف."""
    cur = get(pid)
    if not cur:
        raise PresetError("الوصفة غير موجودة")
    if not cur["custom"] and not cur["overridden"]:
        raise PresetError("الوصفات الجاهزة ما بتنحذف (بتقدر تعدّلها، وبترجع الأصلية لو حذفت تعديلك)")
    _save_user([p for p in _user_presets() if p["id"] != pid])
    return get(pid)


# ── التطبيق على لقطة ─────────────────────────────────────────────────────
def _find(tl: dict, shot_id: str) -> dict:
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == shot_id:
                return sh
    raise PresetError("لقطة غير موجودة")


def apply(script_path, shot_id: str, preset_id: str, look: dict | None = None) -> dict:
    """بيحط الوصفة على اللقطة (التحريك الفعلي بيتشغّل بعدين: motion.run_shot). بيرجّع اللقطة."""
    stem = Path(script_path).stem
    tl = timeline.load(stem)
    if not tl:
        raise PresetError("ما في خط زمني")
    p = get(preset_id)
    if not p:
        raise PresetError("الوصفة غير موجودة")
    sh = _find(tl, shot_id)
    sh["camera_preset"] = {"id": p["id"], "look": clean_look(look), "at": _now()}
    sh["motion_desc"] = p["motion_desc_ar"]
    sh["motion_prompt"] = None
    timeline.save(stem, tl)
    return sh


def clear(script_path, shot_id: str) -> dict:
    stem = Path(script_path).stem
    tl = timeline.load(stem)
    if not tl:
        raise PresetError("ما في خط زمني")
    sh = _find(tl, shot_id)
    sh.pop("camera_preset", None)
    sh["motion_prompt"] = None
    timeline.save(stem, tl)
    return sh


def of_shot(shot: dict) -> dict | None:
    cp = (shot or {}).get("camera_preset")
    return get(cp.get("id")) if isinstance(cp, dict) else None


def camera_move_of(shot: dict) -> bool | None:
    """هل وصفة اللقطة فيها حركة كاميرا؟ None لو ما في وصفة (المستدعي بيرجع للتخمين من النص)."""
    p = of_shot(shot)
    return None if p is None else bool(p.get("camera_move"))


def preference(shot: dict, model: dict) -> float:
    """نقاط ترتيب إضافية لموديل من العائلة المفضّلة لوصفة اللقطة."""
    p = of_shot(shot)
    return PREFER_BONUS if p and family_of(model) in (p.get("prefer") or []) else 0.0


# ── فيديو المثال من شغلنا ────────────────────────────────────────────────
def examples() -> dict:
    return _read(examples_dir() / "examples.json", {})


def example_path(pid: str) -> Path | None:
    p = examples_dir() / f"{pid}.mp4"
    return p if p.exists() and re.fullmatch(r"[a-z0-9_]+", pid or "") else None


def remember_example(pid: str, clip: Path, meta: dict | None = None) -> bool:
    """أول فيديو بيطلع بوصفة بنحفظ منه نسخة صغيرة (عرض ≤ 360) كمثال. لو في مثال قبل ما بنبدّل. بيرجّع true لو انحفظ."""
    if example_path(pid) or not get(pid) or not Path(clip).exists():
        return False
    d = examples_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{pid}.mp4"
    ok = False
    try:
        r = subprocess.run(["ffmpeg", "-y", "-i", str(clip), "-vf", "scale=360:-2", "-an", "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)], capture_output=True, timeout=120)
        ok = r.returncode == 0 and dest.exists() and dest.stat().st_size > 500
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        dest.unlink(missing_ok=True)
        if Path(clip).stat().st_size <= 5 * 1024 * 1024:
            shutil.copyfile(clip, dest)
            ok = True
    if ok:
        ex = examples()
        ex[pid] = {**(meta or {}), "at": _now()}
        (d / "examples.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ok


def public(p: dict) -> dict:
    """نسخة للواجهة: + مثال الفيديو (إن وجد) + نص «الكاميرا والعدسة» ما فيه."""
    ex = examples().get(p["id"])
    return {**p, "example": ({"url": f"/api/presets/{p['id']}/example", **ex} if ex and example_path(p["id"]) else None)}


def main() -> None:
    for p in all_presets():
        print(f"{p['id']:16} {p['category']:10} {p['name_ar']}")


if __name__ == "__main__":
    main()
