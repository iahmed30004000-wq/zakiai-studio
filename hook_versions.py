"""
نسخ الهوك: كل هوك بديل بيصير نسخة فيديو لنفس الإعلان، بدون ما ننتج الإعلان كله من جديد.

النسخة = ملف سيناريو لحاله library/scripts/<الأساسي>__h2.json: نفس السيناريو الأساسي بس افتتاحية المشهد 1 هي الهوك البديل،
وهويته VP-<كود>-<رقم>-v<نسخة>-h2 (إعلان مستقل بميتا).

اللي بيتورّث من الفيديو الأساسي (مشاهد 2–7):
  · الصوت: ملفات المشاهد + مانيفست (voice.json فيه `inherited`) ← generate_voice بيولّد المشهد 1 بس.
  · اللقطات بعد بناء الخط الزمني (overlay_timeline): البرومبت والصورة المختارة والحركة + ملفاتها، وتتعلّم `inherited`
    فالتوليد ما بيعيدها (shot_prompts.build وطابور الإضافة بيتخطّوها).
اللي بينتج لحاله: المشهد 1 (صوت، صور، تحريك) ثم المونتاج. وكل محطة بتبقى بموافقة المالك كالعادة.

المراجعة مشتقة بلا نداء ذكاء: بتنسخ مراجعة الأساسي (اللي أصلاً نظيفة) بدون ملاحظات المشهد 1، لأن الهوك البديل انفحص
بالكود وراجعه المراجع كهوك بديل (hooks_review).
"""

from __future__ import annotations

import copy
import glob
import json
import shutil
from datetime import datetime
from pathlib import Path

import config
import script_hooks as sh
import script_versions

STRUCT_KEYS = ("id", "start_ms", "end_ms", "word_range")                       # حقول اللقطة اللي بتتحسب من الصوت وما بتتورّث
SCENE1_FIELDS = ("hook_line", "voiceover", "on_screen_text", "visual")


class HookVersionError(Exception):
    """سبب عربي جاهز للعرض. status: 400 شرط ناقص، 404 مش موجود، 409 موجودة."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _scripts_dir() -> Path:
    return Path(config.SCRIPTS_DIR)


def _read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def version_stem(base_stem: str, hid: str) -> str:
    return f"{base_stem}__{hid}"


def info(script: dict) -> dict | None:
    """بيانات الربط بالسيناريو الأساسي لو هاد نسخة هوك، وإلا None."""
    hi = (script.get("_meta") or {}).get("hook_of")
    return hi if isinstance(hi, dict) and hi.get("base") else None


def is_version(script: dict) -> bool:
    return info(script) is not None


# ═════════════════ القائمة ═════════════════
def list_versions(base_path) -> list[dict]:
    """نسخ الهوك المنشأة لسيناريو أساسي، مع تقدّم محطات الإنتاج لكل وحدة."""
    import studio_state
    base_stem = Path(base_path).stem
    out = []
    for f in sorted(_scripts_dir().glob(glob.escape(base_stem) + "__h*.json")):
        try:
            s = _read(f)
        except json.JSONDecodeError:
            continue
        hi = info(s)
        if not hi or hi.get("base") != base_stem:
            continue
        meta = s.get("_meta") or {}
        stations = studio_state.summary(f.stem)
        approved = sum(1 for x in stations if x["state"] == "approved")
        current = next((x for x in stations if x["state"] != "approved"), None)
        out.append({"hook_id": hi.get("hook_id"), "file": f.name, "stem": f.stem, "script_id": meta.get("script_id"),
                    "status": meta.get("status"), "type": hi.get("type"), "created_at": hi.get("created_at"),
                    "inherited_scenes": hi.get("inherited_scenes") or [],
                    "progress": {"approved": approved, "total": len(stations), "current": current["label"] if current else None}})
    return sorted(out, key=lambda v: (v["hook_id"] or ""))


def version_file(base_path, hid: str) -> Path:
    return _scripts_dir() / f"{version_stem(Path(base_path).stem, hid)}.json"


# ═════════════════ الشروط ═════════════════
def can_create(base_path, hid: str) -> tuple[bool, str, int]:
    """(نعم/لا، السبب بالعربي، كود الحالة لو لا)."""
    import review_loop
    import review_script
    import voice_studio
    path = Path(base_path)
    if not path.exists():
        return False, "السيناريو غير موجود", 404
    script = _read(path)
    if is_version(script):
        return False, "هاد نسخة هوك أصلاً — اعمل النسخ من السيناريو الأساسي", 400
    hook = sh.get(script, hid)
    if hook is None:
        return False, "الهوك غير موجود", 404
    if hid == sh.main_id(script):
        return False, "هذا الهوك الأساسي — الفيديو الأساسي هو نسخته", 400
    if version_file(path, hid).exists():
        return False, "في نسخة فيديو لهالهوك أصلاً", 409
    ok, why = review_loop.is_cleared(path)
    if not ok:
        return False, f"السيناريو الأساسي لازم يكون مراجَع ومعتمد أول: {why}", 400
    blockers = sh.blockers(script, review_script.load_brief(script)).get(hid)
    if blockers:
        return False, f"الهوك فيه {len(blockers)} مانع بالفحص — عدّله أو ولّد غيره", 400
    rv = (script.get("hooks_review") or {}).get(hid)
    if not rv or rv.get("fp") != sh.fingerprint(hook):
        return False, "الهوك ما انراجع بالذكاء (أو انعدّل بعد المراجعة) — شغّل تدقيق السيناريو أول، بيراجع الهوكات كمان", 400
    if rv.get("verdict") == "reject":
        return False, "رفضه المراجع" + (f": {rv['note']}" if rv.get("note") else ""), 400
    ok, why = voice_studio.voice_is_approved(path)
    if not ok:
        return False, "اعتمد صوت الفيديو الأساسي أول (محطة الفويس أوفر) — النسخة بتاخد صوت مشاهده 2–7 منه", 400
    return True, "", 200


# ═════════════════ الإنشاء ═════════════════
def _derived_review(base_path: Path, new_path: Path, new_script: dict, hid: str, hook: dict) -> None:
    """مراجعة النسخة = مراجعة الأساسي بدون ملاحظات افتتاحية المشهد 1 (الهوك انفحص لحاله)، ببصمة محتوى النسخة."""
    import review_loop
    import review_script
    base = review_loop.load_review(base_path) or {}
    findings = [f for f in (base.get("findings") or [])
                if isinstance(f, dict) and not f.get("hook_id") and not (f.get("scene") == 1 and f.get("field") in SCENE1_FIELDS)]
    now = datetime.now().isoformat(timespec="seconds")
    review = {
        **{k: v for k, v in base.items() if k not in ("findings", "script_hash", "_meta", "hooks_review", "corrected_script")},
        "verdict": "approve", "findings": findings,
        "summary": "مراجعة مشتقة من السيناريو الأساسي: نفس المحتوى ما عدا افتتاحية المشهد 1 (فُحصت بالكود وراجعها المراجع كهوك بديل).",
        "blockers": review_script.count_main(findings, "blocker"), "major": review_script.count_main(findings, "major"),
        "minor": review_script.count_main(findings, "minor"), "hook_blockers": 0, "rounds": 0,
        "script_hash": script_versions.content_hash(new_script),
        "derived_from": {"stem": base_path.stem, "hook_id": hid, "base_script_hash": base.get("script_hash"), "hook_fp": sh.fingerprint(hook)},
        "_meta": {"script": new_path.name, "reviewed_at": now, "provider": "derived", "model": "derived"},
    }
    out = review_loop.review_path(new_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")


def inherit_voice(base_stem: str, new_stem: str) -> list[int]:
    """ينسخ صوت مشاهد 2+ من الفيديو الأساسي (ملفات + مانيفست فيه inherited). بيرجّع أرقام المشاهد الموروثة."""
    import generate_voice
    import voice_studio
    m = voice_studio.load_manifest(base_stem)
    if not m:
        return []
    lib = Path(config.LIBRARY_DIR)
    out_dir = lib / "voice" / new_stem
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = []
    for s in m.get("scenes", []):
        if s.get("scene") == 1:
            continue                                         # المشهد 1 هو اللي بيتغيّر
        src = lib / str(s.get("path", ""))
        if not src.is_file():
            continue
        dst = out_dir / src.name
        shutil.copy2(src, dst)
        scenes.append({**copy.deepcopy(s), "path": generate_voice._rel(dst)})
    if not scenes:
        return []
    total = round(sum(s["duration_sec"] for s in scenes), 2)
    planned = round(sum(s.get("planned_sec", 0) for s in scenes), 2)
    manifest = {"script": f"{new_stem}.json", "generated_at": datetime.now().isoformat(timespec="seconds"),
                "provider": m.get("provider"), "model": m.get("model"), "voice": m.get("voice"), "scenes": scenes,
                "total_actual_sec": total, "total_planned_sec": planned, "total_drift_sec": round(total - planned, 2),
                "scenes_off": [s["scene"] for s in scenes if abs(s.get("drift_sec", 0)) > generate_voice.DRIFT_WARN],
                "combined": None, "inherited": [s["scene"] for s in scenes]}
    (out_dir / "voice.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest["inherited"]


def create(base_path, hid: str, *, by: str = "owner") -> dict:
    """ينشئ سيناريو نسخة الهوك + مراجعته المشتقة + صوته الموروث + نفس الشخصية. بيرجّع {file, stem, script_id, inherited_scenes}."""
    path = Path(base_path)
    ok, why, status = can_create(path, hid)
    if not ok:
        raise HookVersionError(why, status)
    base = _read(path)
    hook = sh.get(base, hid)
    bmeta = base.get("_meta") or {}
    code, number, version = bmeta.get("product_code"), bmeta.get("number"), script_versions.version_of(base)
    new = sh.as_script(base, hid)
    for k in ("hooks", "hook_main", "hooks_review"):          # النسخة سيناريو بهوك واحد (هوكها هو الأساسي فيها)
        new.pop(k, None)
    new_stem = version_stem(path.stem, hid)
    sid = script_versions.make_script_id(code, number, version, hid)
    meta = copy.deepcopy(bmeta)
    for k in ("edited_at", "rewritten_at", "snapshot_at"):
        meta.pop(k, None)
    label = sh.TYPES.get(hook.get("type"), "")
    meta.update({
        "script_id": sid, "status": "approved", "hooks_requested": 1,
        "display_name": f"{bmeta.get('display_name') or path.stem} · هوك {hid[1:]}" + (f" ({label})" if label else ""),
        "hook_of": {"base": path.stem, "base_script_id": bmeta.get("script_id"), "hook_id": hid, "type": hook.get("type"),
                    "created_at": datetime.now().isoformat(timespec="seconds"), "by": by},
    })
    new["_meta"] = meta
    meta["content_hash"] = script_versions.content_hash(new)
    out = _scripts_dir() / f"{new_stem}.json"
    out.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    script_versions.save_version(new_stem, new)
    _derived_review(path, out, new, hid, hook)

    inherited = inherit_voice(path.stem, new_stem)
    meta["hook_of"]["inherited_scenes"] = inherited
    out.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    _copy_character(path.stem, new_stem)
    try:                                                     # المحطات 1–3 بتنشتق (البريف، السيناريو، الشخصية)
        import studio_state
        studio_state.derive_early(new_stem, out)
    except Exception:                                        # noqa: BLE001 — اشتقاق المحطات تحسين، مش شرط للإنشاء
        pass
    return {"file": out.name, "stem": new_stem, "script_id": sid, "inherited_scenes": inherited}


def _copy_character(base_stem: str, new_stem: str) -> None:
    """نفس الشخصية المختارة بالفيديو الأساسي (الوجه والصوت ثابتين بين النسخ)."""
    src = Path(config.LIBRARY_DIR) / "studio" / base_stem / "character.json"
    if src.is_file():
        dst = Path(config.LIBRARY_DIR) / "studio" / new_stem / "character.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


# ═════════════════ توريث اللقطات ═════════════════
def _shot_words(tl: dict, shot: dict) -> list[str]:
    a, b = shot["word_range"]
    return [w["text"] for w in tl["words"][a:b + 1]]


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def overlay_timeline(new_stem: str, tl: dict, script: dict) -> int:
    """
    بعد بناء الخط الزمني للنسخة: لقطات المشاهد 2+ بتورّث من خط الفيديو الأساسي (برومبت، صورة، حركة، فحوص) إذا هي نفس
    اللقطة فعلاً (نفس المعرّف، نفس المدة، نفس الكلمات). ملفاتها (صور/مقاطع) بتنتسخ لمجلد النسخة بنفس المسار النسبي.
    اللقطة اللي ورثت صورة معتمدة بتتعلّم inherited فالتوليد التلقائي ما بيعيدها. بيرجّع عدد اللقطات اللي ورثت.
    """
    import timeline as tlmod
    hi = info(script)
    if not hi:
        return 0
    base_tl = tlmod.load(hi["base"])
    if not base_tl:
        return 0
    base_dir = (Path(config.LIBRARY_DIR) / "timelines" / hi["base"]).resolve()
    new_dir = Path(config.LIBRARY_DIR) / "timelines" / new_stem
    base_shots = {s["id"]: s for sc in base_tl["scenes"] if sc["n"] != 1 for s in sc["shots"]}
    count = 0
    for sc in tl["scenes"]:
        if sc["n"] == 1:
            continue
        for shot in sc["shots"]:
            b = base_shots.get(shot["id"])
            if b is None or (b["end_ms"] - b["start_ms"]) != (shot["end_ms"] - shot["start_ms"]) \
                    or _shot_words(base_tl, b) != _shot_words(tl, shot):
                continue
            fields = {k: copy.deepcopy(v) for k, v in b.items() if k not in STRUCT_KEYS and k != "inherited"}
            for rel in {s for s in _strings(fields) if s and not s.startswith(("/", "\\")) and "://" not in s}:
                src = (base_dir / rel).resolve()
                if base_dir in src.parents and src.is_file():
                    dst = new_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            shot.update(fields)
            if (shot.get("image") or {}).get("chosen"):
                shot["inherited"] = True
                count += 1
    return count
