"""
مسارات خط الكتابة (الوكيل A): البريف والحقائق، توازن المكتبة والحصاد، المطابقة،
حلقة المراجعة والنسخ. بتنضم لـ app.py بـ `app.include_router(routes_pipeline.router)`.

كل المسارات تحت /api، والأخطاء {"detail": "رسالة عربية"}.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import brief as brief_mod  # noqa: E402
import claims  # noqa: E402
import config  # noqa: E402
import taxonomy  # noqa: E402

router = APIRouter(prefix="/api")

# حقول الحقائق التجارية اللي بتنسحب من الـ OMS
FACT_FIELDS = ("price", "price_positioning", "offer", "no_offer", "guarantee", "no_guarantee",
               "country", "dialect", "scarcity_deadline", "stock_units", "landing_page")


# ─────────────────────────── مساعدات ───────────────────────────


def _product_path(file: str) -> Path:
    name = Path(file).name
    if not name.endswith(".json"):
        name += ".json"
    path = Path(config.PRODUCTS_DIR) / name
    if name.startswith("_") or not path.exists():
        raise HTTPException(404, "ملف المنتج غير موجود")
    return path


def _script_path(file: str) -> Path:
    path = Path(config.SCRIPTS_DIR) / Path(file).name
    if not path.exists() or path.suffix != ".json":
        raise HTTPException(404, "السيناريو غير موجود")
    return path


def _load_brief(path: Path) -> dict:
    try:
        return brief_mod.load(path)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(422, "ملف المنتج تالف")


# ─────────────────────────── البريف ───────────────────────────


@router.get("/brief/schema")
def brief_schema() -> dict:
    return {
        "fields": [{"key": k, "label": l, "type": t, "group": g} for k, l, t, g in brief_mod.FIELDS],
        "required": list(brief_mod.REQUIRED),
        "publish_required": list(brief_mod.PUBLISH_REQUIRED),
    }


@router.get("/products/{file}/completeness")
def product_completeness(file: str) -> dict:
    b = _load_brief(_product_path(file))
    c = brief_mod.completeness(b)
    ok, basis = claims.scarcity_allowed(b)
    rules = claims.writer_rules(b)
    return {
        **c,
        "forbidden_effective": claims.effective_forbidden(b),
        "scarcity": {"allowed": ok, "basis": basis},
        "offer_policy": "allowed" if rules["offer_allowed_in_cta"] else "none",
    }


def _cache_path(product_code: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", product_code) or "unknown"
    return Path(config.LIBRARY_DIR) / "crm_cache" / "products" / f"{safe}.json"


def _read_cache(product_code: str) -> dict | None:
    p = _cache_path(product_code)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_cache(product_code: str, country: str, facts: dict) -> str:
    p = _cache_path(product_code)
    p.parent.mkdir(parents=True, exist_ok=True)
    at = datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps({"product_code": product_code, "country": country, "cached_at": at,
                             "facts": facts}, ensure_ascii=False, indent=2), encoding="utf-8")
    return at


def apply_facts(raw: dict, facts: dict) -> tuple[list[str], list[dict]]:
    """
    يطبّق حقائق الـ OMS على بريف (dict خام) بـ set_field(source="crm").
    بيرجّع (المفاتيح المطبّقة، المتخطّاة مع السبب). القيم الفاضية ما بتمسح شي.
    """
    facts = dict(facts or {})
    if "offer" not in facts and isinstance(facts.get("offers"), list):
        offers = [str(o).strip() for o in facts["offers"] if str(o).strip()]
        if offers:
            facts["offer"] = "؛ ".join(offers)

    applied: list[str] = []
    skipped: list[dict] = []

    def put(key, value):
        brief_mod.set_field(raw, key, value, source="crm")
        if key not in applied:
            applied.append(key)

    for key in FACT_FIELDS:
        if key not in facts:
            continue
        val = facts[key]
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        if key == "country":
            n = taxonomy.normalize_country(val)
            if n.status != "ok":
                skipped.append({"key": key, "reason": f"بلد غير معروف: {val}"})
                continue
            val = n.value
        elif key == "dialect":
            n = taxonomy.normalize_dialect(val)
            if n.status != "ok":
                skipped.append({"key": key, "reason": f"لهجة غير معروفة: {val}"})
                continue
            val = n.value
        elif isinstance(val, str):
            val = val.strip()
        put(key, val)
        # عرض/ضمان مسحوب = بطل «لا يوجد» لأنو بيناقضه
        if key == "offer" and raw.get("no_offer"):
            put("no_offer", False)
        if key == "guarantee" and raw.get("no_guarantee"):
            put("no_guarantee", False)
    return applied, skipped


@router.post("/products/{file}/facts/sync")
def sync_facts(file: str) -> dict:
    path = _product_path(file)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(422, "ملف المنتج تالف")
    b = _load_brief(path)
    code, country = b.get("product_code") or "", b.get("country") or ""
    if not code:
        raise HTTPException(400, "كود المنتج فاضي — عبّيه بالبريف قبل مزامنة الحقائق")

    facts, stale, cached_at, offline_reason = None, False, None, None
    try:
        import crm
    except ImportError:
        crm = None
    fetch = getattr(crm, "fetch_product_facts", None) if crm else None
    if fetch is None:
        offline_reason = "وحدة الـ OMS غير متاحة حالياً"
    else:
        offline_exc = getattr(crm, "CRMOffline", None)
        try:
            facts = fetch(code, country)
        except Exception as e:                       # noqa: BLE001 — تصنيف الفشل أدناه
            if offline_exc and isinstance(e, offline_exc):
                offline_reason = "الـ OMS أوفلاين"
            else:
                raise HTTPException(502, f"الـ OMS رجّع خطأ: {e}")
        else:
            cached_at = _write_cache(code, country, facts or {}) if facts else None

    if facts is None:
        cached = _read_cache(code)
        if not cached:
            raise HTTPException(503, f"{offline_reason} ولا في نسخة مخزّنة من الحقائق لهالمنتج")
        facts, stale, cached_at = cached.get("facts") or {}, True, cached.get("cached_at")

    applied, skipped = apply_facts(raw, facts)
    if applied:
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"applied": applied, "skipped": skipped, "stale": stale, "cached_at": cached_at}


# ─────────────────────────── توازن المكتبة والحصاد ───────────────────────────


@router.get("/library/coverage")
def library_coverage() -> dict:
    import library_stats
    return library_stats.coverage()


def _queue_call(fn, *args, **kwargs):
    import harvest_plan
    try:
        return fn(*args, **kwargs)
    except harvest_plan.QueueError as e:
        code = 404 if "غير موجود" in str(e) else 409 if ("موجود مسبقاً" in str(e) or "الحالة" in str(e)
                                                          or "انستخرج" in str(e) or "شغّال" in str(e)) else 400
        raise HTTPException(code, str(e))


@router.get("/harvest/candidates")
def harvest_candidates(status: str | None = None, category: str | None = None) -> dict:
    import harvest_plan
    return {"items": _queue_call(harvest_plan.list_items, status or None, category or None)}


@router.post("/harvest/candidates")
def harvest_add(payload: dict) -> dict:
    import harvest_plan
    url = str(payload.get("url") or "").strip()
    category = str(payload.get("category") or "").strip()
    if not url or not category:
        raise HTTPException(400, "لازم رابط وفئة")
    item = _queue_call(harvest_plan.add_candidate, url, category, "manual",
                       str(payload.get("note") or ""))
    return {"ok": True, "item": item}


@router.post("/harvest/candidates/{item_id}/approve")
def harvest_approve(item_id: str) -> dict:
    import harvest_plan
    item = _queue_call(harvest_plan.approve, item_id)
    return {"ok": True, "item": item, "job_id": item.get("job_id")}


@router.post("/harvest/candidates/{item_id}/reject")
def harvest_reject(item_id: str) -> dict:
    import harvest_plan
    return {"ok": True, "item": _queue_call(harvest_plan.reject, item_id)}


@router.post("/harvest/plan")
def harvest_plan_endpoint(category: str | None = None, run: bool = False) -> dict:
    """خطة حصاد للفئة (أو لكل الفئات الناقصة). run=true بيشغّل الحصاد الآلي إذا APIFY_TOKEN موجود."""
    import harvest_plan
    if category:
        slug = taxonomy.normalize_category(category).value
        if not slug:
            raise HTTPException(400, "الفئة لازم تكون slug صحيح")
        import library_stats
        cov = library_stats.coverage()
        row = next((r for r in cov["per_category"] if r["category"] == slug), None)
        plan = _queue_call(harvest_plan.plan_for_category, slug,
                           row["gap"] if row else None, row["count"] if row else None)
        if run:
            plan["job_ids"] = _queue_call(harvest_plan.run_plan, slug)
        return plan
    if run:
        raise HTTPException(400, "حدّد الفئة لتشغيل الحصاد الآلي")
    return {"plans": harvest_plan.plans_for_gaps(), "apify_configured": harvest_plan.apify_configured()}


# ─────────────────────────── المطابقة ───────────────────────────


@router.post("/match")
def match_product(payload: dict) -> dict:
    """مطابقة منتج مع المكتبة (نداء موديل واحد). النتيجة بعد قواعد الفئة + warnings."""
    import llm
    import stage3_generate
    path = _product_path(str(payload.get("product_file") or ""))
    try:
        return stage3_generate.match_for_product(path, category=payload.get("category") or None)
    except stage3_generate.PipelineError as e:
        raise HTTPException(422, str(e))
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


# ─────────────────────────── المراجعة والنسخ ───────────────────────────


@router.post("/scripts/{file}/review-loop")
def start_review_loop(file: str) -> dict:
    from web import jobs
    path = _script_path(file)
    return {"job_id": jobs.create_job("review", f"حلقة مراجعة: {path.stem}",
                                      ["review_loop.py", str(path)])}


@router.get("/scripts/{file}/status")
def script_status(file: str) -> dict:
    import review_loop
    return review_loop.status(_script_path(file))


@router.get("/scripts/{file}/versions")
def script_versions_endpoint(file: str) -> dict:
    import script_versions
    path = _script_path(file)
    return {"versions": script_versions.list_versions(path), "diffs": script_versions.diffs(path)}


def _ms(fn, *a, **k):
    """بينفّذ ويحوّل أخطاء السيناريو اليدوي لرسائل HTTP عربية."""
    import manual_script
    import voice_upload
    try:
        return fn(*a, **k)
    except manual_script.ManualScriptError as e:
        raise HTTPException(e.status, str(e))
    except voice_upload.VoiceUploadError as e:
        raise HTTPException(e.status, str(e))


@router.post("/scripts/manual")
async def create_manual_script(product_file: str = Form(...), pattern_id: str = Form(...), title: str = Form(""), text: str = Form(""),
                               split_sentences: bool = Form(False), file: UploadFile | None = File(None)) -> dict:
    """سيناريو بإيدك للمهمة الموجّهة: نص (كل فقرة مشهد) أو Excel (سطر لكل مشهد) — 7 مشاهد بالضبط. بيرجّع {file, warnings, …حالة المراجعة}."""
    import manual_script
    import review_loop
    import scene_import
    import accounts
    has_file = bool(file is not None and (file.filename or ""))
    if has_file and (text or "").strip():
        raise HTTPException(400, "اختار نص أو ملف Excel، مش الاتنين مع بعض")
    xlsx = None
    if has_file:
        xlsx = await file.read(scene_import.MAX_BYTES + 1)
        if len(xlsx) > scene_import.MAX_BYTES:
            raise HTTPException(413, f"الملف أكبر من {scene_import.MAX_BYTES // (1024 * 1024)} ميغا")
    rows, warnings = _ms(manual_script.rows_from, text, xlsx, split_sentences)
    path = _ms(manual_script.create, product_file, pattern_id, rows, title=title, by=accounts.who("owner"))
    return {"file": path.name, "warnings": warnings, **review_loop.status(path)}


@router.post("/scripts/manual/from-voice")
async def create_manual_script_from_voice(product_file: str = Form(...), pattern_id: str = Form(...), file: UploadFile = File(...),
                                          language: str = Form("")) -> dict:
    """ابدأ من تسجيل صوتك: بيتفرّغ وبيصير سيناريو 7 مشاهد وبيتوافق عليه حسابياً وصوتك بينقصّ على المشاهد — كمهمة خلفية.
    بيرجّع {job_id, token}؛ بعد ما تخلص المهمة GET /api/scripts/manual/result/<token> بيعطي اسم السيناريو."""
    import accounts
    import manual_script
    import media_io
    import uuid
    import voice_upload
    from fastapi.concurrency import run_in_threadpool
    from web import jobs
    _ms(manual_script._product, product_file)
    _ms(manual_script._pattern, pattern_id)
    kind = media_io.kind_of(file.filename)
    if kind not in ("audio", "video"):
        raise HTTPException(400, "لازم ملف صوت (mp3, wav, m4a, ogg…) أو فيديو فيه صوتك")
    token = uuid.uuid4().hex
    d = manual_script.jobs_dir() / token
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"upload{Path(file.filename or '').suffix.lower()}"
    try:
        await media_io.stream_to(file, dest, media_io.MAX_AUDIO_BYTES if kind == "audio" else media_io.MAX_VIDEO_BYTES)
        info = await run_in_threadpool(media_io.probe_av, dest)
    except media_io.MediaError as e:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(e.status, str(e))
    if not info["has_audio"] or info["duration_sec"] > voice_upload.MAX_SOURCE_SEC:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "الملف ما فيه صوت" if not info["has_audio"] else f"التسجيل أطول من {int(voice_upload.MAX_SOURCE_SEC // 60)} دقايق — قسّمه")
    cmd = ["manual_script.py", "from-voice", "--product", product_file, "--pattern", pattern_id, "--audio", str(dest), "--token", token]
    if language.strip():
        cmd += ["--language", language.strip()]
    return {"job_id": jobs.create_job("voice", "سيناريو من تسجيل صوتك", cmd), "token": token, "by": accounts.who("owner")}


@router.get("/scripts/manual/result/{token}")
def manual_voice_result(token: str) -> dict:
    """نتيجة «ابدأ من تسجيلك» بعد ما تخلص المهمة: {file, ok, reason, voice}."""
    import manual_script
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        raise HTTPException(400, "رمز غير صالح")
    f = manual_script.jobs_dir().parent / f"manual_voice_{token}.json"
    if not f.exists():
        raise HTTPException(404, "لسا ما في نتيجة")
    return json.loads(f.read_text(encoding="utf-8"))


@router.post("/scripts/{file}/approve-local")
def approve_script_local(file: str, payload: dict | None = None) -> dict:
    """موافقتك بالفحص الحسابي والادعاءات بس (لما مراجعة الذكاء مش متاحة): أي مانع بيوقف. لو في مراجعة ذكاء فيها موانع بيطلب تأكيد."""
    import review_loop
    import studio_gate
    path = _script_path(file)
    if studio_gate.is_free(path):
        raise HTTPException(409, "المشروع الحر ما بيحتاج موافقة — هاد للمهمة الموجّهة")
    try:
        st = review_loop.approve_local(path, by=__import__("accounts").who("owner"), confirm=bool((payload or {}).get("confirm")))
    except review_loop.ConfirmNeeded as e:
        raise HTTPException(409, {"code": "needs_confirm", "message": str(e)})
    except review_loop.ApprovalError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, **st}


@router.post("/scripts/{file}/approve")
def approve_script(file: str) -> dict:
    import review_loop
    path = _script_path(file)
    try:
        st = review_loop.approve(path, by=__import__("accounts").who("owner"))
    except review_loop.ApprovalError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, **st}
