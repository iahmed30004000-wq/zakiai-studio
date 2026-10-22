"""الحركات السينمائية: مكتبة الوصفات (جاهزة + إضافات المالك + أمثلة من شغلنا) وتطبيقها على لقطات السيناريو."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api")


def _p(fn, *a, **k):
    import motion_presets
    try:
        return fn(*a, **k)
    except motion_presets.PresetError as e:
        raise HTTPException(400, str(e))


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


@router.get("/presets")
def list_presets(category: str | None = None) -> dict:
    """الوصفات (الجاهزة مع تعديلات المالك + وصفاته) + الأقسام + جداول الكاميرا والعدسات + العائلات."""
    import motion_presets as mp
    rows = [mp.public(p) for p in mp.all_presets() if not category or p["category"] == category]
    return {"categories": mp.categories(), "presets": rows, "families": mp.FAMILIES, "looks": mp.looks(),
            "shot_types": list(mp.SHOT_TYPES),
            "counts": {"total": len(rows), "custom": sum(1 for p in rows if p["custom"]), "with_example": sum(1 for p in rows if p["example"])}}


@router.get("/presets/{pid}/example")
def preset_example(pid: str):
    import motion_presets as mp
    f = mp.example_path(pid)
    if not f:
        raise HTTPException(404, "ما في مثال لهالوصفة بعد")
    return FileResponse(f, media_type="video/mp4")


@router.post("/presets")
def create_preset(payload: dict) -> dict:
    import motion_presets as mp
    return mp.public(_p(mp.create, payload))


@router.put("/presets/{pid}")
def update_preset(pid: str, payload: dict) -> dict:
    import motion_presets as mp
    return mp.public(_p(mp.update, pid, payload))


@router.delete("/presets/{pid}")
def delete_preset(pid: str) -> dict:
    """وصفة المالك بتنحذف؛ تعديله على جاهزة بينشال (بترجع الأصلية). الجاهزة الأصلية ما بتنحذف."""
    import motion_presets as mp
    back = _p(mp.delete, pid)
    return {"ok": True, "restored": mp.public(back) if back else None}


@router.post("/studio/{filename}/shots/{shot_id}/preset")
def apply_preset(filename: str, shot_id: str, payload: dict) -> dict:
    """بيحط وصفة (وشكل الكاميرا/العدسة الاختياري) على لقطة. التحريك نفسه بيتشغّل من «حرّك» بنفس اللقطة."""
    import motion_presets as mp
    p = _script(filename)
    return {"shot": _p(mp.apply, p, shot_id, str(payload.get("preset_id") or ""), payload.get("look"))}


@router.delete("/studio/{filename}/shots/{shot_id}/preset")
def clear_preset(filename: str, shot_id: str) -> dict:
    import motion_presets as mp
    return {"shot": _p(mp.clear, _script(filename), shot_id)}
