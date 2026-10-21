"""
هوكات السيناريو: عرض، اختيار الأساسي، تعديل، حذف، وتوليد هوك بديل (جديد أو بدل موجود) بالذكاء.

الأساسي = hook_line + بداية المشهد 1 (فتعديله أو تبديله بيغيّر محتوى السيناريو ← بصمة المحتوى بتتحدّث والموافقة بترجع مسودة).
البدائل بتتخزّن بجنب: تعديلها ما بيلمس المحتوى المعتمد. كل ردّ = العرض الكامل (script_hooks.public) عشان الواجهة ترسم من جديد.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/scripts/{file}/hooks")

MAX_SPOKEN, MAX_OST, MAX_VISUAL, MAX_WHY = 300, 80, 600, 300


def _load(file: str):
    import config
    path = Path(config.SCRIPTS_DIR) / Path(file).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(400, "ملف السيناريو تالف")


def _brief(script: dict):
    import review_script
    return review_script.load_brief(script)


def _ensure(script: dict) -> dict:
    """السيناريو القديم (بلا hooks) بيتحوّل لشكل الهوكات قبل أي تعديل عليه."""
    import script_hooks as sh
    if not (isinstance(script.get("hooks"), list) and script["hooks"]):
        script["hooks"] = sh.hooks_of(script)
        script["hook_main"] = sh.main_id(script)
    return script


def _save(path: Path, script: dict, *, main_changed: bool) -> None:
    import script_versions
    meta = script.setdefault("_meta", {})
    meta["edited_at"] = datetime.now().isoformat(timespec="seconds")
    if main_changed:
        meta["content_hash"] = script_versions.content_hash(script)
        if meta.get("status") == "approved":
            meta["status"] = "draft"                      # تغيّر الأساسي = لازم مراجعة جديدة
        md = path.with_suffix(".md")
        if md.exists():
            md.unlink()                                   # نسخة الماركداون صارت قديمة
    path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")


def _view(path: Path, script: dict) -> dict:
    """العرض الكامل: الهوكات + نسخ الفيديو الموجودة لكل هوك بديل + هل بتنفع نعمل نسخة (وليش لا)."""
    import hook_versions
    import script_hooks as sh
    brief = _brief(script)
    view = sh.public(script, brief)
    is_version = hook_versions.is_version(script)
    by = {} if is_version else {v["hook_id"]: v for v in hook_versions.list_versions(path)}
    for h in view["hooks"]:
        h["version"] = by.get(h["id"])
        if not h["main"] and not is_version and not h["version"]:
            ok, why, _ = hook_versions.can_create(path, h["id"])
            h["can_version"] = {"ok": ok, "reason": why}
    view["version_of"] = (hook_versions.info(script) or {}).get("base")
    return {"ok": True, **view}


def _text(body: dict, key: str, limit: int, label: str):
    if key not in body:
        return None
    v = str(body.get(key) or "").strip()
    if len(v) > limit:
        raise HTTPException(400, f"«{label}» أطول من {limit} حرف")
    return v


def _forget_review(script: dict, hid: str) -> None:
    hr = script.get("hooks_review")
    if isinstance(hr, dict):
        hr.pop(hid, None)


@router.get("")
def list_hooks(file: str) -> dict:
    path, script = _load(file)
    return _view(path, script)


@router.post("/select")
def select_main(file: str, payload: dict) -> dict:
    """يخلّي هوك بديل هو الأساسي: بتتبدّل بداية المشهد 1 وhook_line، والأساسي القديم بيضل بديل."""
    import script_hooks as sh
    path, script = _load(file)
    hid = str(payload.get("id") or "")
    if sh.get(script, hid) is None:
        raise HTTPException(404, "الهوك غير موجود")
    if hid == sh.main_id(script):
        return _view(path, script)
    out = sh.select_main(_ensure(script), hid)
    _forget_review(out, hid)
    _save(path, out, main_changed=True)
    return _view(path, out)


@router.put("/{hid}")
def edit_hook(file: str, hid: str, payload: dict) -> dict:
    import script_hooks as sh
    import review_script
    path, script = _load(file)
    if sh.get(script, hid) is None:
        raise HTTPException(404, "الهوك غير موجود")
    spoken = _text(payload, "spoken", MAX_SPOKEN, "السطر المحكي")
    ost = _text(payload, "on_screen_text", MAX_OST, "نص الشاشة")
    visual = _text(payload, "visual", MAX_VISUAL, "الوصف البصري")
    why = _text(payload, "why", MAX_WHY, "ليش بيشتغل")
    typ = payload.get("type")
    if spoken == "":
        raise HTTPException(400, "السطر المحكي مطلوب")
    if typ is not None and typ not in sh.TYPES:
        raise HTTPException(400, "نوع الهوك مش من القائمة")
    new = _ensure(copy.deepcopy(script))
    main = hid == sh.main_id(new)
    row = next(h for h in new["hooks"] if h["id"] == hid)
    if typ is not None:
        row["type"] = typ
    if why is not None:
        row["why"] = why
    if main:                                              # الأساسي: التعديل بيروح للسيناريو نفسه (hook_line + المشهد 1)
        if spoken is not None:
            new["hook_line"] = spoken
        s1 = new["scenes"][0]
        if ost is not None:
            s1["on_screen_text"] = ost
        if visual is not None:
            s1["visual"] = visual
        new = sh.sync_after_edit(script, new)
        new["scenes"][0]["word_count"] = review_script.word_count(new["scenes"][0].get("voiceover"))
    else:
        for k, v in (("spoken", spoken), ("on_screen_text", ost), ("visual", visual)):
            if v is not None:
                row[k] = v
        _forget_review(new, hid)                          # النص اتغيّر ← حكم المراجع القديم ما بيصلح
    _save(path, new, main_changed=main)
    return _view(path, new)


@router.delete("/{hid}")
def delete_hook(file: str, hid: str) -> dict:
    import script_hooks as sh
    path, script = _load(file)
    if sh.get(script, hid) is None:
        raise HTTPException(404, "الهوك غير موجود")
    if hid == sh.main_id(script):
        raise HTTPException(400, "الهوك الأساسي ما بينحذف — اختر هوك تاني كأساسي أول")
    new = _ensure(copy.deepcopy(script))
    new["hooks"] = [h for h in new["hooks"] if h["id"] != hid]
    _forget_review(new, hid)
    _save(path, new, main_changed=False)
    return _view(path, new)


def _generate(file: str, payload: dict, replace_id: str | None) -> dict:
    import hook_writer
    import llm
    import script_hooks as sh
    path, script = _load(file)
    want = payload.get("type") or None
    try:
        res = hook_writer.propose(script, _brief(script), replace_id=replace_id, want_type=want)
    except hook_writer.HookWriterError as e:
        raise HTTPException(400, str(e))
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    new = _ensure(copy.deepcopy(script))
    row = res["hook"]
    if replace_id is None:
        new["hooks"].append(row)
    else:
        new["hooks"] = [row if h["id"] == replace_id else h for h in new["hooks"]]
        _forget_review(new, replace_id)
    _save(path, new, main_changed=False)
    return {**_view(path, new), "new_id": row["id"], "attempts": res["attempts"]}


@router.post("")
def add_hook(file: str, payload: dict) -> dict:
    """هوك بديل جديد بالذكاء (لحد الحد الأقصى)."""
    return _generate(file, payload, None)


@router.post("/{hid}/regenerate")
def regenerate_hook(file: str, hid: str, payload: dict) -> dict:
    """بدّل هوك بديل بواحد جديد (الأساسي ما بينبدّل هيك)."""
    return _generate(file, payload, hid)


@router.post("/{hid}/version")
def create_version(file: str, hid: str) -> dict:
    """نسخة فيديو لهوك بديل: سيناريو لحاله بهويته -hN، بصوت ولقطات مشاهد 2–7 موروثة من الفيديو الأساسي (المشهد 1 بس بينتج)."""
    import hook_versions
    path, _script = _load(file)
    try:
        res = hook_versions.create(path, hid)
    except hook_versions.HookVersionError as e:
        raise HTTPException(e.status, str(e))
    path, script = _load(file)
    return {**_view(path, script), "created": res}
