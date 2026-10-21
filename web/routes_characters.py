"""مكتبة الشخصيات + اختيار شخصية السيناريو (المحطة ٣)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

import config

router = APIRouter(prefix="/api")


def _err(e: Exception) -> HTTPException:
    return HTTPException(409, str(e))


def _view(ch: dict) -> dict:
    import characters
    return {**ch, "missing": characters.missing_for_ready(ch) if ch.get("status") != "retired" else []}


@router.get("/characters")
def list_characters(retired: bool = False) -> dict:
    import characters
    return {"characters": [_view(c) for c in characters.list_all(retired)],
            "summary": characters.summary(), "views": characters.VIEWS,
            "genders": characters.GENDERS}


@router.post("/characters")
def create_character(payload: dict) -> dict:
    import characters
    try:
        return _view(characters.create(payload))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.get("/characters/{cid}")
def get_character(cid: str) -> dict:
    import characters
    try:
        ch = characters.get(cid)
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))
    if not ch:
        raise HTTPException(404, "الشخصية غير موجودة")
    return _view(ch)


@router.put("/characters/{cid}")
def update_character(cid: str, payload: dict) -> dict:
    import characters
    try:
        return _view(characters.update(cid, payload))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.post("/characters/{cid}/retire")
def retire_character(cid: str) -> dict:
    import characters
    try:
        return _view(characters.retire(cid))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.post("/characters/{cid}/sheet/{view}")
async def upload_sheet(cid: str, view: str, file: UploadFile = File(...)) -> dict:
    import characters
    try:
        return _view(characters.set_sheet(cid, view, file.filename or "", await file.read()))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.delete("/characters/{cid}/sheet/{view}")
def delete_sheet(cid: str, view: str) -> dict:
    """حذف صورة وضعية للشخصية (بتنتقل للسلة library/_trash، مش مسح نهائي). المثبّتة ما بتنحذف، والشخصية بترجع مسودة."""
    import characters
    try:
        return _view(characters.delete_sheet(cid, view))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.get("/characters/{cid}/sheet/{view}")
def get_sheet(cid: str, view: str):
    import characters
    try:
        p = characters.sheet_path(cid, view)
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))
    if not p:
        raise HTTPException(404, "ما في صورة")
    return FileResponse(p)


@router.get("/characters/{cid}/slots")
def character_slots(cid: str, country: str = "") -> dict:
    """الوضعيات الثابتة للورقة المرجعية: صورة كل وضعية + برومبتها (الفعلي والأصلي) + التثبيت."""
    import characters
    try:
        return characters.slots(cid, country)
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.put("/characters/{cid}/prompt/{view}")
def put_character_prompt(cid: str, view: str, payload: dict) -> dict:
    import characters
    try:
        characters.set_prompt(cid, view, payload.get("text"))
        return characters.slots(cid, str(payload.get("country") or ""))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.delete("/characters/{cid}/prompt/{view}")
def reset_character_prompt(cid: str, view: str) -> dict:
    import characters
    try:
        characters.reset_prompt(cid, view)
        return characters.slots(cid)
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.post("/characters/{cid}/lock/{view}")
def lock_character_view(cid: str, view: str, payload: dict) -> dict:
    import characters
    try:
        characters.set_lock(cid, view, bool(payload.get("locked")))
        return characters.slots(cid)
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.get("/characters/{cid}/prompts.docx")
def character_prompts_docx(cid: str, country: str = "") -> Response:
    import characters
    import refprompts
    try:
        name, data = characters.prompts_docx(cid, country)
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))
    return Response(content=data, media_type=refprompts.DOCX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/characters/{cid}/consent")
async def upload_consent(cid: str, file: UploadFile = File(...), signed_at: str = Form(""),
                         scope: str = Form("")) -> dict:
    import characters
    try:
        return _view(characters.set_consent(cid, file.filename or "", await file.read(), signed_at, scope))
    except characters.CharacterError as e:
        raise HTTPException(400, str(e))


@router.get("/characters/{cid}/consent")
def get_consent(cid: str):
    import characters
    ch = characters.get(cid)
    rel = ((ch or {}).get("consent") or {}).get("file")
    p = (characters.dir_of(cid) / rel) if rel else None
    if not p or not p.exists():
        raise HTTPException(404, "ما في ملف موافقة")
    return FileResponse(p)


# ── محطة ٣ للسيناريو ────────────────────────────────────────────────────
def _script(filename: str) -> tuple[Path, dict]:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p, json.loads(p.read_text(encoding="utf-8"))


@router.get("/studio/{filename}/characters")
def suggestions(filename: str) -> dict:
    import characters
    import review_script
    p, script = _script(filename)
    b = review_script.load_brief(script) or {}
    meta = script.get("_meta") or {}
    code = meta.get("product_code") or b.get("product_code") or ""
    sug = characters.suggest(b, b.get("country") or "", code)
    cur = characters.chosen(p.stem)
    return {"library_active": characters.library_active(), "chosen": cur,
            "suggestions": [{**s, "character": _view(s["character"])} for s in sug],
            "summary": characters.summary()}


@router.post("/studio/{filename}/character")
def choose_character(filename: str, payload: dict) -> dict:
    import characters
    p, script = _script(filename)
    try:
        return characters.choose(p.stem, script, str(payload.get("character_id") or ""))
    except characters.CharacterError as e:
        raise _err(e)


# ── ملف المنتج المرجعي (تثبيت هوية المنتج) ─────────────────────────────
@router.get("/product-refs")
def list_product_refs() -> dict:
    """كل المنتجات، كل واحد بملفه المرجعي المستقل وتقدّمه."""
    import product_ref
    return {"products": product_ref.list_products()}


@router.get("/ref-sheets/prompts.docx")
def all_ref_prompts_docx() -> Response:
    """برومبتات كل المنتجات وكل الشخصيات بملف Word واحد (قسم لكل وحدة)."""
    import ref_docx
    import refprompts
    name, data = ref_docx.all_prompts_docx()
    return Response(content=data, media_type=refprompts.DOCX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/product-refs/{code}")
def get_product_ref(code: str) -> dict:
    import product_ref
    try:
        ref = product_ref.load(code)
        sheet = product_ref.sheet(code)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))
    return {**ref, **sheet, "missing": product_ref.missing(ref), "angle_labels": product_ref.ANGLES, "slot_labels": product_ref.SLOTS,
            "can_composite": product_ref.can_composite(code)}


@router.put("/product-refs/{code}")
def put_product_ref(code: str, payload: dict) -> dict:
    import product_ref
    try:
        ref = product_ref.set_details(code, payload.get("dims_cm"), payload.get("label_text"), payload.get("colors"), payload.get("visual"),
                                      payload.get("box_text"))
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))
    return {**ref, "missing": product_ref.missing(ref)}


@router.post("/product-refs/{code}/angle/{angle}")
async def upload_product_angle(code: str, angle: str, file: UploadFile = File(...), auto: bool = False) -> dict:
    import product_ref
    from starlette.concurrency import run_in_threadpool
    try:
        # auto=1: تفريغ الخلفية بالذكاء محلياً (ثقيل شوي، فبنشغّله بخيط منفصل عشان ما نعلّق الخادم)
        ref = await run_in_threadpool(product_ref.set_angle, code, angle, await file.read(), auto)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))
    return {**ref, "missing": product_ref.missing(ref)}


@router.delete("/product-refs/{code}/angle/{angle}")
def delete_product_angle(code: str, angle: str) -> dict:
    """حذف صورة وضعية (بتنتقل للسلة library/_trash، مش مسح نهائي). المثبّتة ما بتنحذف."""
    import product_ref
    try:
        ref = product_ref.delete_angle(code, angle)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))
    return {**ref, **product_ref.sheet(code), "missing": product_ref.missing(ref)}


@router.get("/product-refs/{code}/angle/{angle}")
def get_product_angle(code: str, angle: str):
    import product_ref
    try:
        p = product_ref.angle_path(code, angle)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))
    if not p:
        raise HTTPException(404, "ما في صورة")
    return FileResponse(p)


@router.put("/product-refs/{code}/prompt/{slot}")
def put_product_prompt(code: str, slot: str, payload: dict) -> dict:
    import product_ref
    try:
        product_ref.set_prompt(code, slot, payload.get("text"))
        return product_ref.sheet(code)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))


@router.delete("/product-refs/{code}/prompt/{slot}")
def reset_product_prompt(code: str, slot: str) -> dict:
    import product_ref
    try:
        product_ref.reset_prompt(code, slot)
        return product_ref.sheet(code)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))


@router.post("/product-refs/{code}/lock/{slot}")
def lock_product_slot(code: str, slot: str, payload: dict) -> dict:
    import product_ref
    try:
        product_ref.set_lock(code, slot, bool(payload.get("locked")))
        return product_ref.sheet(code)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))


@router.get("/product-refs/{code}/prompts.docx")
def product_prompts_docx(code: str) -> Response:
    import product_ref
    import refprompts
    try:
        name, data = product_ref.prompts_docx(code)
    except product_ref.ProductRefError as e:
        raise HTTPException(400, str(e))
    return Response(content=data, media_type=refprompts.DOCX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})
