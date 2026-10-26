"""
مكتبة الأنماط: تعديل أي جزئية، نمط جديد، أرشفة، ترجمة، واستيراد Excel.

المسارات تحت /api/pattern-lib/* مش /api/patterns/*: لأنو GET /api/patterns/{id} بيلقط كل شي.
الأخطاء: 400 فيها detail قائمة [{field, msg}]، 404 مش موجود، 409 تعارض نسخة، 423 المكتبة مشغولة.
الأسئلة (نمط مشابه، نمط مستعمل بسيناريوهات) بترجع 200 {ok:false, confirm, message} مش خطأ: الواجهة بتسأل المالك
وبتعيد نفس الطلب مع confirm=true (ولازم تكون 200 لأنو api() بالواجهة بيحوّل detail الكائن لنص «[object Object]»).
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

router = APIRouter(prefix="/api/pattern-lib")


def _actor() -> str:
    """مين عمل الشغلة: اسم الموظف اللي داخل (حسابات الموظفين)، وإلا «owner»."""
    import accounts
    return accounts.who("owner")


def _guard(fn, *a, **k):
    import pattern_store
    try:
        return fn(*a, **k)
    except pattern_store.PatternError as e:
        raise HTTPException(e.status, e.detail)


@router.get("/schema")
def get_schema() -> dict:
    import pattern_fields
    return pattern_fields.schema()


@router.get("/translation")
def translation_status() -> dict:
    """حالة الترجمة التلقائية للعربي (للشريط اللي فوق المكتبة): كم ناقص، شغّالة؟ التقدّم، آخر خطأ، وقت الانتظار."""
    import pattern_i18n
    return pattern_i18n.status()


@router.post("/translate")
def start_translation(payload: dict) -> dict:
    """بيبدأ الترجمة بالخلفية إذا في ناقص ومش شغّالة (الواجهة بتناديه لحالها). retry=true بيتخطّى الانتظار بعد الفشل."""
    import pattern_i18n
    try:
        limit = int(payload.get("limit") or 0) or None
    except (TypeError, ValueError):
        raise HTTPException(400, "العدد لازم يكون رقم")
    return {"ok": True, **pattern_i18n.ensure_running(force=bool(payload.get("retry")), limit=limit)}


@router.get("/archived")
def list_archived() -> dict:
    import pattern_store
    return {"items": pattern_store.list_archived()}


@router.get("/template.xlsx")
def excel_template() -> Response:
    """نموذج Excel: «اقرأني» + «الأنماط» (قوائم منسدلة) + «المشاهد»."""
    import pattern_excel
    return Response(pattern_excel.template(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="zakiai-patterns-template.xlsx"'})


@router.get("/bundle.zip")
def bundle_export() -> Response:
    """كل الأنماط النشطة بملف مضغوط واحد — لنقل المكتبة من جهاز لجهاز (مثلاً لموقع السيرفر)."""
    import pattern_store
    return Response(pattern_store.export_bundle(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="zakiai-patterns.zip"'})


@router.post("/bundle")
async def bundle_import(file: UploadFile = File(...)) -> dict:
    """بيضيف الأنماط اللي مش موجودة من ملف مضغوط صدّره استوديو تاني. الموجود ما بينلمس."""
    import pattern_store
    data = await file.read(pattern_store.BUNDLE_MAX_BYTES + 1)
    return _guard(pattern_store.import_bundle, data, by=_actor())


@router.post("/import")
async def excel_preview(file: UploadFile = File(...)) -> dict:
    """يقرأ ملف Excel ويرجّع معاينة لكل سطر (صح/غلط وليش/مشابه). ما بيكتب شي بالمكتبة."""
    import pattern_excel
    data = await file.read(pattern_excel.MAX_BYTES + 1)
    try:
        return pattern_excel.preview(data, file.filename or "")
    except pattern_excel.ExcelError as e:
        raise HTTPException(400, str(e))


@router.post("/import/commit")
def excel_commit(payload: dict) -> dict:
    """بيحفظ الأنماط الصح من المعاينة (والمشابهة كمان إذا include_warnings)."""
    import pattern_excel
    rows = payload.get("rows")
    try:
        return pattern_excel.commit(str(payload.get("token") or ""), include_warnings=bool(payload.get("include_warnings")),
                                    rows=[int(x) for x in rows] if isinstance(rows, list) else None, by=_actor())
    except (pattern_excel.ExcelError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.post("/similar")
def similar(payload: dict) -> dict:
    """أنماط بالمكتبة بتشبه الحقول المكتوبة (تحذير بس). بيتعامل مع حقول ناقصة بدون خطأ."""
    import pattern_store
    return {"matches": pattern_store.similar(payload.get("fields") or {})}


@router.post("")
def create_pattern(payload: dict) -> dict:
    import pattern_fields
    import pattern_store
    fields = payload.get("fields") or {}
    _, errs = pattern_fields.validate(fields, "create")
    if errs:
        raise HTTPException(400, errs)
    if not payload.get("confirm"):
        near = [m for m in pattern_store.similar(fields) if m.get("is_duplicate") or m.get("same_name")]
        if near:
            top = near[0]
            why = "بنفس الاسم" if top.get("same_name") else f"بيشبهه {round(top['score'] * 100)}%"
            return {"ok": False, "confirm": "similar", "similar": near,
                    "message": f"في نمط بالمكتبة {why}: «{top['pattern_name']}». بتحفظ النمط الجديد برضو؟"}
    pid = _guard(pattern_store.create, fields, via="manual", by=_actor())
    return {"ok": True, "id": pid}


@router.get("/{pid}")
def get_pattern(pid: str) -> dict:
    import pattern_store
    return _guard(pattern_store.view, pid)


@router.put("/{pid}")
def edit_pattern(pid: str, payload: dict) -> dict:
    import pattern_store
    out = _guard(pattern_store.save_edit, pid, payload.get("fields") or {}, base_rev=payload.get("rev"), by=_actor())
    return {"ok": True, **out}


@router.post("/{pid}/archive")
def archive_pattern(pid: str, payload: dict) -> dict:
    """الحذف = أرشفة: النمط بيطلع من المكتبة وبيضل محفوظ (السيناريوهات المبنية عليه ما بتتأثر)."""
    import pattern_store
    refs = pattern_store.script_refs(pid)
    if refs["count"] and not payload.get("confirm"):
        names = "، ".join(f"«{n}»" for n in refs["names"])
        return {"ok": False, "confirm": "used", "refs": refs,
                "message": f"النمط مستعمل بـ {refs['count']} سيناريو ({names}). بيضلوا شغّالين، بس النمط بيطلع من المكتبة وبتقدر ترجّعه. كمّل؟"}
    out = _guard(pattern_store.archive, pid, by=_actor())
    return {"ok": True, **out}


@router.post("/{pid}/restore")
def restore_pattern(pid: str) -> dict:
    import pattern_store
    return {"ok": True, **_guard(pattern_store.restore, pid, by=_actor())}
