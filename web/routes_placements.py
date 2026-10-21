"""تسجيل الإعلان المنشور بالحساب الإعلاني (ميتا/تيك توك/سناب…): إدخال يدوي أو اختيار من حملات العمليات."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

import config

router = APIRouter(prefix="/api")


def _script(filename: str) -> Path:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p


def _vp_id(p: Path) -> str:
    import timeline
    tl = timeline.load(p.stem) or {}
    meta = (json.loads(p.read_text(encoding="utf-8")).get("_meta") or {})
    return tl.get("script_id") or meta.get("script_id") or ""


def _pe(fn, *a, **k):
    import placements
    try:
        return fn(*a, **k)
    except placements.PlacementError as e:
        raise HTTPException(400, str(e))


@router.get("/studio/{filename}/placements")
def get_placements(filename: str) -> dict:
    import placements
    p = _script(filename)
    vp = _vp_id(p)
    return {"vp_id": vp, "entries": placements.list_for(vp) if vp else [], "platforms": placements.PLATFORMS,
            "statuses": placements.STATUSES, "suggestion": placements.suggest_ad_name(p), "oms": placements.oms_options()}


@router.post("/studio/{filename}/placements")
def add_placement(filename: str, payload: dict) -> dict:
    import placements
    vp = _vp_id(_script(filename))
    return _pe(placements.add, vp, payload)


@router.put("/studio/{filename}/placements/{pid}")
def edit_placement(filename: str, pid: str, payload: dict) -> dict:
    import placements
    vp = _vp_id(_script(filename))
    return _pe(placements.update, vp, pid, payload)


@router.delete("/studio/{filename}/placements/{pid}")
def remove_placement(filename: str, pid: str) -> dict:
    import placements
    vp = _vp_id(_script(filename))
    _pe(placements.delete, vp, pid)
    return {"ok": True}
