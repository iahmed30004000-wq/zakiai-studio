"""
Zakiai Systems — طبقة الويب.

بتتعامل مع سكربتات المراحل كمحرّك خارجي (subprocess) مش كاستيراد،
فبتضل المراحل تشتغل من التيرمنال بدون الويب، والعكس.

التشغيل:
    python -m uvicorn web.app:app --reload --port 8000
أو:
    python run_web.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import settings_io  # noqa: E402
from web import jobs  # noqa: E402

app = FastAPI(title="Zakiai Systems")
from web.guard import LocalGuard  # noqa: E402
from web.auth_gate import AuthGate  # noqa: E402
app.add_middleware(AuthGate)          # حسابات الموظفين: كل /api/* بدها دخول (راجع web/auth_gate.py) — بتشتغل بعد LocalGuard
app.add_middleware(LocalGuard)        # Host/Origin: يسكّر النفق ومواقع غريبة (راجع web/guard.py) — الأخير المضاف بيشتغل أول

from web import routes_pipeline, routes_crm, routes_ops, routes_studio, routes_characters, routes_motion, routes_montage, routes_ext, routes_claims, routes_hooks, routes_hooks_bank, routes_patterns, routes_placements, routes_presets, routes_auth, routes_ads, routes_free, routes_model_library, routes_drive  # noqa: E402
STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = ROOT / "library" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


@app.on_event("startup")
def _startup() -> None:
    jobs.init_db()
    jobs.requeue_pending()
    try:                     # الجدولة: catch-up للمستحق + دورة الطابور/المزامنة/النسخ
        import scheduler
        scheduler.start()
    except Exception as e:   # ما بنوقف السيرفر لو الجدولة فشلت
        print(f"[!] الجدولة ما اشتغلت: {e}")
    try:                     # عامل درايف: بيرفع نواتج المحطات المعتمدة (بلا ربط ما بيعمل شي)
        import drive_sync
        drive_sync.start()
    except Exception as e:
        print(f"[!] عامل درايف ما اشتغل: {e}")
    try:                     # أي نمط نصه لسا إنجليزي بينترجم لحاله بالخلفية (بعد لحظات من الإقلاع)
        import pattern_i18n
        pattern_i18n.schedule_startup()
    except Exception as e:
        print(f"[!] الترجمة التلقائية ما بدأت: {e}")


def safe_stem(name: str) -> str:
    """اسم ملف آمن — المستخدم بيتحكم فيه فما منثق فيه كمسار."""
    stem = Path(name).stem
    stem = re.sub(r"[^\w؀-ۿ-]+", "_", stem).strip("_")
    return stem[:60] or "video"


# ────────────────────────────── المكتبة ──────────────────────────────


def _load_patterns() -> list[dict]:
    out = []
    for f in sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        p["_pattern_id"] = f.name.replace(".pattern.json", "")
        out.append(p)
    return out


@app.get("/api/stats")
def stats() -> dict:
    patterns = _load_patterns()
    extracts = list(Path(config.RAW_DIR).glob("*/extract.json"))
    scripts = list(Path(config.SCRIPTS_DIR).glob("*.json"))
    scores = [p.get("reusability_score") for p in patterns if isinstance(p.get("reusability_score"), (int, float))]
    import taxonomy
    categories: dict[str, int] = {}
    for p in patterns:
        cat = taxonomy.CATEGORY_LABELS.get(p.get("product_category"), "غير مصنّف")
        categories[cat] = categories.get(cat, 0) + 1
    return {
        "extracts": len(extracts),
        "patterns": len(patterns),
        "scripts": len(scripts),
        "products": len([p for p in Path(config.PRODUCTS_DIR).glob("*.json") if not p.name.startswith("_")]),
        "avg_reusability": round(sum(scores) / len(scores), 1) if scores else None,
        "strong_patterns": sum(1 for s in scores if s >= 7),
        "frameworks": len({p.get("framework") for p in patterns if p.get("framework")}),
        "categories": sorted(categories.items(), key=lambda kv: -kv[1]),
        "active_jobs": jobs.active_count(),
    }


@app.get("/api/patterns")
def api_patterns(category: str | None = None) -> list[dict]:
    import pattern_text as pt
    import taxonomy
    patterns = _load_patterns()
    try:
        import evidence
        ev = evidence.pattern_evidence()
    except Exception:
        ev = {}
    names = {q["_pattern_id"]: pt.display_name(q) for q in patterns}       # كل المكتبة (قبل الفلترة) لاسم «مكرّر من»
    if category:      # slug مغلق أو جزء من التسمية العربية
        patterns = [p for p in patterns if p.get("product_category") == category
                    or category in taxonomy.CATEGORY_LABELS.get(p.get("product_category"), "")]
    return [_pattern_row(p, ev, names) for p in patterns]


def _pattern_row(p: dict, ev: dict, names: dict) -> dict:
    """صف الكرت بالعربي: النصوص من طبقة العربي (pattern_text)، والقيم المغلقة بتسمياتها العربية."""
    import pattern_text as pt
    import taxonomy
    pid = p["_pattern_id"]
    lp = pt.localized(p)
    e = ev.get(pid) or {}
    dup = next((m for m in (p.get("_similar_to") or []) if m.get("is_duplicate")), None)
    return {
        "id": pid,
        "name": pt.display_name(p),
        "framework": taxonomy.FRAMEWORKS.get(p.get("framework"), "غير مصنّف"),
        "framework_slug": p.get("framework"),
        "framework_secondary": taxonomy.FRAMEWORKS.get(p.get("framework_secondary")),
        "dialect": taxonomy.DIALECTS.get(p.get("dialect_or_language"), "غير مصنّف"),
        "dialect_slug": p.get("dialect_or_language"),
        "category_slug": p.get("product_category"),
        "cluster_id": p.get("cluster_id"),
        "cluster_role": p.get("cluster_role"),
        "needs_review": not (p.get("_taxonomy") or {}).get("complete", False),
        "summary": lp.get("one_line_summary"),
        "category": taxonomy.CATEGORY_LABELS.get(p.get("product_category"), "غير مصنّف"),
        "hook_type": (lp.get("hook") or {}).get("type"),
        "product_entry_sec": p.get("product_entry_sec"),
        "proof": lp.get("proof_mechanism"),
        "reusability": p.get("reusability_score"),
        "reusability_opinion": p.get("reusability_score"),
        "evidence_level": e.get("evidence_level", "unproven"),
        "evidence_score": e.get("evidence_score", 0),
        "delivered": e.get("delivered", 0),
        "cost_per_delivered": e.get("cost_per_delivered"),
        "blueprint_len": len(p.get("scene_blueprint", [])),
        "duplicate_of": (names.get(dup.get("pattern_id")) or dup.get("pattern_name")) if dup else None,
        "authored": (p.get("_source") or {}).get("type") == "authored",
        "origin": (p.get("_source") or {}).get("type")
                  or ("proven" if pid.startswith("proven_") else "mined"),
    }


@app.get("/api/duplicates")
def api_duplicates() -> list[dict]:
    """أزواج الأنماط المتشابهة بنيوياً — بدون أي نداء API."""
    import pattern_dedupe
    import pattern_text as pt
    lib = pattern_dedupe.load_library(config.PATTERNS_DIR)
    pairs = []
    for i, a in enumerate(lib):
        for b in lib[i + 1:]:
            score, parts = pattern_dedupe.similarity(a, b)
            if score >= pattern_dedupe.SIMILAR_THRESHOLD:
                pairs.append({
                    "score": round(score, 3),
                    "is_duplicate": score >= pattern_dedupe.DUPLICATE_THRESHOLD,
                    "a": {"id": a["_pattern_id"], "name": pt.display_name(a)},
                    "b": {"id": b["_pattern_id"], "name": pt.display_name(b)},
                    "parts": {k: round(v, 2) for k, v in parts.items()},
                })
    pairs.sort(key=lambda x: -x["score"])
    return pairs


@app.get("/api/taxonomy")
def api_taxonomy() -> dict:
    import taxonomy
    return {"dialects": taxonomy.DIALECTS, "dialect_subs": {k: v[0] for k, v in taxonomy.DIALECT_SUBS.items()},
            "frameworks": taxonomy.FRAMEWORKS, "categories": taxonomy.CATEGORY_LABELS,
            "category_groups": {k: v[1] for k, v in taxonomy.CATEGORIES.items()},
            "countries": taxonomy.COUNTRIES}


@app.get("/api/review-queue")
def api_review_queue(status: str = "open") -> dict:
    """بنود المراجعة، ومعها اسم النمط بالعربي والقيمة الأصلية مترجمة (إذا الترجمة موجودة)."""
    import pattern_store
    import pattern_text as pt
    import review_queue
    legacy_key = {"dialect": "dialect_or_language", "framework": "framework",
                  "framework_order": "framework", "category": "product_category"}
    out = []
    for it in review_queue.list_items(None if status == "all" else status):
        row = dict(it)
        key = legacy_key.get(it.get("kind"))
        p = pattern_store.load_any(str(it.get("pattern_id") or "")) if key else None
        if p:
            row["pattern_name"] = pt.display_name(p)
            ar = ((p.get("ar") or {}).get("_legacy") or {}).get(key)
            if ar:
                row["raw_ar"] = ar
        out.append(row)
    return {"items": out}


@app.post("/api/review-queue/{item_id}/resolve")
async def api_review_resolve(item_id: str, payload: dict) -> dict:
    import review_queue
    try:
        it = review_queue.resolve(item_id, str(payload.get("value", "")), payload.get("secondary"))
    except KeyError:
        raise HTTPException(404, "عنصر غير موجود")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "item": it}


@app.get("/api/clusters")
def api_clusters() -> dict:
    import clusters
    return {"clusters": clusters.load()}


@app.get("/api/patterns/{pattern_id}")
def api_pattern(pattern_id: str) -> dict:
    """النمط بالعربي (طبقة العربي مدموجة)، من المكتبة أو الأرشيف (سيناريو قديم ممكن يكون مبني على نمط مؤرشف)."""
    import pattern_store
    import pattern_text as pt
    p = pattern_store.load_any(pattern_id)
    if p is None:
        raise HTTPException(404, "النمط غير موجود")
    p["_pattern_id"] = pattern_id
    out = pt.localized(p)
    out["_archived"] = pattern_store.is_archived(pattern_id)
    return out


# ────────────────────────────── المنتجات ──────────────────────────────


@app.get("/api/products")
def api_products() -> list[dict]:
    out = []
    for f in sorted(Path(config.PRODUCTS_DIR).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "file": f.name,
            "is_template": f.name.startswith("_"),
            "product_name": d.get("product_name", f.stem),
            "category": d.get("category"),
            "market": d.get("market"),
            "dialect": d.get("dialect"),
        })
    return out


@app.get("/api/products/{filename}")
def api_product(filename: str) -> dict:
    path = Path(config.PRODUCTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "ملف المنتج غير موجود")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/products/parse")
def parse_product(text: str = Form(...)) -> dict:
    """نص حر عن منتج -> حقول منظّمة. المستخدم بيراجعها قبل الحفظ."""
    import llm
    if len(text.strip()) < 30:
        raise HTTPException(400, "النص قصير كتير — الصق تفاصيل المنتج")

    prompt = (Path(config.PROMPTS_DIR) / "product_parser.txt").read_text(encoding="utf-8")
    try:
        return llm.complete_json("parser", prompt, [{"type": "text", "text": text[:120_000]}])
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


@app.put("/api/products/{filename}")
async def save_product(filename: str, payload: dict) -> dict:
    name = Path(filename).name
    if not name.endswith(".json") or name.startswith("_"):
        raise HTTPException(400, "اسم ملف غير صالح")
    path = Path(config.PRODUCTS_DIR) / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "file": name}


@app.delete("/api/products/{filename}")
def delete_product(filename: str) -> dict:
    name = Path(filename).name
    if name.startswith("_"):
        raise HTTPException(400, "ما بينحذف النموذج")
    path = Path(config.PRODUCTS_DIR) / name
    if not path.exists():
        raise HTTPException(404, "ملف المنتج غير موجود")
    path.unlink()
    # نظّف نتيجة المطابقة المرتبطة فيه
    (Path(config.LIBRARY_DIR) / "matches" / f"{path.stem}.json").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/matches/{filename}")
def api_matches(filename: str) -> dict:
    """آخر نتيجة مطابقة محفوظة لهذا المنتج."""
    stem = Path(filename).stem
    path = Path(config.LIBRARY_DIR) / "matches" / f"{stem}.json"
    if not path.exists():
        raise HTTPException(404, "ما في مطابقة محفوظة — شغّل التحليل أول")
    return json.loads(path.read_text(encoding="utf-8"))


# ────────────────────────────── السيناريوهات ──────────────────────────────


@app.get("/api/scripts")
def api_scripts() -> list[dict]:
    out = []
    for f in sorted(Path(config.SCRIPTS_DIR).glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        meta = d.get("_meta", {})
        product = meta.get("product") or ""
        number = meta.get("number")
        out.append({
            "file": f.name,
            "title": d.get("title"),
            "product": product,
            "number": number,
            # السيناريوهات القديمة ما فيها رقم — بينعرضوا باسم المنتج بس
            "display_name": meta.get("display_name")
                            or (f"#{number} - {product}" if number else product or f.stem),
            "pattern_id": meta.get("pattern_id"),
            "duration": d.get("total_duration_sec"),
            "scenes": len(d.get("scenes", [])),
            "generated_at": meta.get("generated_at"),
            "status": meta.get("status"),
            "script_id": meta.get("script_id"),
            "version": meta.get("version"),
            "mode": "free" if meta.get("mode") == "free" else "guided",      # مشروع حر (يدوي) أو مهمة موجّهة
        })
    # الأحدث أولاً ضمن كل منتج
    return sorted(out, key=lambda s: (s["product"], -(s["number"] or 0)))


@app.get("/api/scripts/{filename}")
def api_script(filename: str) -> dict:
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return json.loads(path.read_text(encoding="utf-8"))


REVIEW_DIR = Path(config.LIBRARY_DIR) / "reviews"


@app.put("/api/scripts/{filename}")
async def save_script(filename: str, payload: dict) -> dict:
    """حفظ تعديلات يدوية على السيناريو، مع إعادة حساب المدة والكلمات."""
    import review_script
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")

    script = json.loads(path.read_text(encoding="utf-8"))
    if (script.get("_meta") or {}).get("mode") == "free":
        raise HTTPException(409, "المشروع الحر بيتعدّل من شاشته (المشاهد واللقطات) مش من محرّر السيناريو")
    before = json.loads(json.dumps(script))
    for key in ("title", "hook_line", "cta_line"):
        if key in payload:
            script[key] = payload[key]

    if "scenes" in payload:
        for edit in payload["scenes"]:
            n = edit.get("scene_number")
            target = next((s for s in script.get("scenes", []) if s.get("scene_number") == n), None)
            if not target:
                continue
            for field in ("voiceover", "visual", "on_screen_text", "shot_type",
                          "purpose", "emotion", "duration_sec"):
                if field in edit:
                    target[field] = edit[field]
            target["word_count"] = review_script.word_count(target.get("voiceover"))

    import script_hooks
    script = script_hooks.sync_after_edit(before, script)            # hook_line ↔ بداية المشهد 1 ↔ الهوك الأساسي
    script["total_duration_sec"] = round(
        sum(float(s.get("duration_sec") or 0) for s in script.get("scenes", [])), 1
    )
    import script_versions
    meta = script.setdefault("_meta", {})
    meta["edited_at"] = datetime.now().isoformat(timespec="seconds")
    meta["content_hash"] = script_versions.content_hash(script)
    if meta.get("status") == "approved":
        meta["status"] = "draft"      # التعديل بعد الموافقة = لازم مراجعة جديدة

    path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    md = path.with_suffix(".md")
    if md.exists():
        md.unlink()      # نسخة الماركداون صارت قديمة
    return {"ok": True, "total_duration_sec": script["total_duration_sec"]}


@app.post("/api/review/{filename}")
def start_review(filename: str) -> dict:
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return {"job_id": jobs.create_job("review", f"تدقيق: {path.stem}",
                                      ["review_script.py", str(path)])}


@app.get("/api/review/{filename}")
def get_review(filename: str) -> dict:
    stem = Path(filename).stem
    path = REVIEW_DIR / f"{stem}.review.json"
    if not path.exists():
        raise HTTPException(404, "ما في تدقيق محفوظ")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/review/{filename}/local")
def local_review(filename: str) -> dict:
    """الفحوصات الحسابية فقط — فورية ومجانية، بدون أي نداء API."""
    import review_script
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    script = json.loads(path.read_text(encoding="utf-8"))
    findings = review_script.local_checks(script)
    return {
        "findings": findings,
        "blockers": review_script.count_main(findings, "blocker"),
        "hook_blockers": sum(1 for f in findings if review_script.is_hook_finding(f) and f["severity"] == "blocker"),
        "total_duration_sec": round(
            sum(float(s.get("duration_sec") or 0) for s in script.get("scenes", [])), 1),
    }


VOICE_DIR = Path(config.LIBRARY_DIR) / "voice"


@app.get("/api/tts")
def get_tts() -> dict:
    import tts
    cfg = tts.tts_config(library=False)               # صفحة الإعدادات = الطريقة الحالية؛ نماذج المكتبة من «مكتبة النماذج»
    key = cfg["api_key"]
    return {
        "current": {**{k: v for k, v in cfg.items() if k != "api_key"},
                    "key_set": bool(key),
                    "key_masked": f"{key[:8]}…{key[-4:]}" if len(key) > 14 else ("مضبوط" if key else "")},
        "providers": {
            pid: {"label": p["label"], "models": p["models"],
                  "voices": p.get("voices", []), "lists_voices": p.get("lists_voices", False),
                  "note": p.get("note", ""), "env_key": p.get("env_key", "")}
            for pid, p in tts.TTS_PRESETS.items()
        },
        "attributes": {"genders": tts.GENDERS, "ages": tts.AGES,
                       "dialects": tts.DIALECTS, "tones": tts.TONES},
    }


@app.put("/api/tts")
async def save_tts(payload: dict) -> dict:
    import tts
    provider = payload.get("provider", "elevenlabs")
    if provider not in tts.TTS_PRESETS:
        raise HTTPException(400, "مزوّد صوت غير معروف")
    saved = _read_settings()
    entry = saved.setdefault("TTS", {})
    for k in ("provider", "model", "voice", "base_url", "instructions",
              "gender", "age", "dialect", "tone"):
        if k in payload:
            entry[k] = str(payload[k]).strip()
    for k in ("speed", "stability", "similarity", "style"):
        if payload.get(k) not in (None, ""):
            entry[k] = float(payload[k])
    if str(payload.get("api_key", "")).strip():
        entry["api_key"] = str(payload["api_key"]).strip()
    settings_io.save(saved)
    return {"ok": True}


@app.get("/api/tts/voices")
def tts_voices(provider: str, base_url: str = "") -> dict:
    """يجلب الأصوات من المزوّد بالمفتاح المحفوظ."""
    import tts
    cfg = tts.tts_config({"provider": provider})
    try:
        return {"voices": tts.list_voices(provider, cfg["api_key"], base_url)}
    except tts.TTSError as e:
        raise HTTPException(400, str(e))


def _require_voice_approved(path: Path) -> None:
    """الصوت هو الساعة: ولا صورة قبل فويس أوفر معتمد (محطة ٤)."""
    import voice_studio
    ok, reason = voice_studio.voice_is_approved(path)
    if not ok:
        raise HTTPException(409, "ما في صورة قبل فويس أوفر معتمد — " + reason)


def _require_cleared(path: Path) -> None:
    """بوابة المرحلة ٤: ما في صوت/صور لسيناريو عوائقه مش صفر أو مراجعته قديمة."""
    import review_loop
    ok, reason = review_loop.is_cleared(path)
    if not ok:
        raise HTTPException(409, reason)


@app.post("/api/voice/{filename}")
def make_voice(filename: str, provider: str | None = Form(None), model: str | None = Form(None),
               voice: str | None = Form(None), scene: int | None = Form(None),
               gender: str | None = Form(None), age: str | None = Form(None),
               dialect: str | None = Form(None), tone: str | None = Form(None),
               instructions: str | None = Form(None)) -> dict:
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    _require_cleared(path)
    cmd = ["generate_voice.py", str(path)]
    for flag, val in (("--provider", provider), ("--model", model), ("--voice", voice),
                      ("--gender", gender), ("--age", age), ("--dialect", dialect),
                      ("--tone", tone), ("--instructions", instructions)):
        if val:
            cmd += [flag, val]
    if scene:
        cmd += ["--scene", str(scene)]
    scope = f" مشهد {scene}" if scene else ""
    return {"job_id": jobs.create_job("voice", f"فويس أوفر{scope}: {path.stem}", cmd)}


@app.get("/api/voice/{filename}")
def get_voice(filename: str) -> dict:
    mf = VOICE_DIR / Path(filename).stem / "voice.json"
    if not mf.exists():
        raise HTTPException(404, "ما في صوت مولّد بعد")
    return json.loads(mf.read_text(encoding="utf-8"))


@app.get("/api/voice/{filename}/audio/{name}")
def get_audio(filename: str, name: str):
    path = VOICE_DIR / Path(filename).stem / Path(name).name
    if not path.exists() or path.suffix.lower() != ".mp3":
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(path, media_type="audio/mpeg")


IMAGE_DIR = Path(config.LIBRARY_DIR) / "images"


@app.get("/api/imagegen")
def get_imagegen() -> dict:
    import imagegen
    cfg = imagegen.image_config()
    key = cfg["api_key"]
    return {
        "current": {**{k: v for k, v in cfg.items() if k != "api_key"},
                    "key_set": bool(key),
                    "key_masked": f"{key[:8]}…{key[-4:]}" if len(key) > 14 else ("مضبوط" if key else "")},
        "providers": {
            pid: {"label": p["label"], "models": p["models"], "sizes": p["sizes"],
                  "note": p.get("note", ""), "env_key": p.get("env_key", "")}
            for pid, p in imagegen.IMAGE_PRESETS.items()
        },
        "no_text_rule": imagegen.NO_TEXT_RULE,
    }


@app.put("/api/imagegen")
async def save_imagegen(payload: dict) -> dict:
    import imagegen
    provider = payload.get("provider", "openai")
    if provider not in imagegen.IMAGE_PRESETS:
        raise HTTPException(400, "مزوّد صور غير معروف")
    saved = _read_settings()
    entry = saved.setdefault("IMAGE", {})
    for k in ("provider", "model", "size", "base_url", "style"):
        if k in payload:
            entry[k] = str(payload[k]).strip()
    if str(payload.get("api_key", "")).strip():
        entry["api_key"] = str(payload["api_key"]).strip()
    settings_io.save(saved)
    return {"ok": True}


@app.post("/api/images/{filename}")
def make_images(filename: str, provider: str | None = Form(None), model: str | None = Form(None),
                size: str | None = Form(None), scene: int | None = Form(None),
                shot: int | None = Form(None), plan_only: bool = Form(False),
                character: str | None = Form(None), product_ref: str | None = Form(None),
                no_refs: bool = Form(False), keep_plan: bool = Form(False)) -> dict:
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    _require_cleared(path)
    _require_voice_approved(path)
    cmd = ["generate_images.py", str(path)]
    for flag, val in (("--provider", provider), ("--model", model), ("--size", size),
                      ("--character", character), ("--product-ref", product_ref)):
        if val:
            cmd += [flag, val]
    if scene:
        cmd += ["--scene", str(scene)]
    if shot:
        cmd += ["--shot", str(shot)]
    if plan_only:
        cmd.append("--plan-only")
    if no_refs:
        cmd.append("--no-refs")
    if keep_plan:
        cmd.append("--keep-plan")

    verb = "تخطيط لقطات" if plan_only else "توليد صور"
    scope = f" مشهد {scene}" + (f"/لقطة {shot}" if shot else "") if scene else ""
    return {"job_id": jobs.create_job("images", f"{verb}{scope}: {path.stem}", cmd)}


@app.put("/api/images/{filename}/shot")
async def edit_shot_prompt(filename: str, payload: dict) -> dict:
    """تعديل برومبت لقطة وحدة بالخطة المحفوظة."""
    mf = IMAGE_DIR / Path(filename).stem / "images.json"
    if not mf.exists():
        raise HTTPException(404, "ما في خطة محفوظة")
    data = json.loads(mf.read_text(encoding="utf-8"))

    scene_n, shot_i = payload.get("scene"), payload.get("shot")
    new_prompt = str(payload.get("prompt", "")).strip()
    if not new_prompt:
        raise HTTPException(400, "البرومبت ما بينفع يكون فاضي")

    for s in data.get("scenes", []):
        if s["scene"] != scene_n:
            continue
        for sh in s.get("shots", []):
            if sh.get("index") == shot_i:
                sh["prompt"] = new_prompt
                sh["prompt_edited"] = True
                mf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return {"ok": True}
    raise HTTPException(404, "اللقطة غير موجودة")


@app.post("/api/images/{filename}/regenerate")
def regenerate_shot(filename: str, scene: int = Form(...), shot: int = Form(...),
                    provider: str | None = Form(None), model: str | None = Form(None),
                    size: str | None = Form(None), character: str | None = Form(None),
                    product_ref: str | None = Form(None)) -> dict:
    """إعادة توليد لقطة وحدة — بنفس برومبتها المحفوظ (أو المعدّل) وبموديل تختاره."""
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    cmd = ["generate_images.py", str(path), "--scene", str(scene), "--shot", str(shot),
           "--keep-plan"]
    for flag, val in (("--provider", provider), ("--model", model), ("--size", size),
                      ("--character", character), ("--product-ref", product_ref)):
        if val:
            cmd += [flag, val]
    label = f"إعادة لقطة {scene}/{shot}: {path.stem}" + (f" ({model})" if model else "")
    return {"job_id": jobs.create_job("images", label, cmd)}


@app.get("/api/images/{filename}")
def get_images(filename: str) -> dict:
    mf = IMAGE_DIR / Path(filename).stem / "images.json"
    if not mf.exists():
        raise HTTPException(404, "ما في صور مولّدة بعد")
    return json.loads(mf.read_text(encoding="utf-8"))


@app.get("/api/images/{filename}/file/{name}")
def get_image_file(filename: str, name: str):
    path = IMAGE_DIR / Path(filename).stem / Path(name).name
    if not path.exists() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(path)


@app.get("/api/performance")
def api_performance() -> dict:
    import performance
    return {
        "entries": performance.load(),
        "results": performance.RESULTS,
        "metrics": performance.METRICS,
        "scoreboard": performance.pattern_scoreboard(),
    }


@app.put("/api/performance/{filename}")
async def set_performance(filename: str, payload: dict) -> dict:
    import performance
    name = Path(filename).name
    if not (Path(config.SCRIPTS_DIR) / name).exists():
        raise HTTPException(404, "السيناريو غير موجود")
    try:
        entry = performance.mark(
            name,
            payload.get("result", "untested"),
            payload.get("metrics") or {},
            str(payload.get("notes", "")),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "entry": entry}


@app.post("/api/learn")
def learn_patterns(product: str | None = None) -> dict:
    """يستخرج أنماط جديدة من أحكام الأداء الفعلي (تكلفة الطلب المُسلَّم من الـ OMS)."""
    cmd = ["learn_patterns.py"]
    if product:
        cmd += ["--product", product]
    return {"job_id": jobs.create_job("learn", "تعلّم أنماط من النتايج", cmd)}


@app.get("/api/scripts/{filename}/download")
def download_script(filename: str):
    path = Path(config.SCRIPTS_DIR) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return FileResponse(path, filename=path.name, media_type="application/json")


# ────────────────────────────── المهام ──────────────────────────────


@app.post("/api/extract/upload")
async def extract_upload(file: UploadFile = File(...)) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(400, f"صيغة غير مدعومة: {ext or 'بدون امتداد'}")

    stem = safe_stem(file.filename or "video")
    dest = UPLOAD_DIR / f"{stem}{ext}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "الملف أكبر من 500 ميجا")
            out.write(chunk)

    job_id = jobs.create_job(
        "extract", f"استخراج: {dest.name}",
        ["stage1_extract.py", str(dest), "--id", stem],
    )
    return {"job_id": job_id, "video_id": stem}


@app.post("/api/extract/link")
def extract_link(url: str = Form(...)) -> dict:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "رابط غير صالح")
    job_id = jobs.create_job("extract", f"استخراج من رابط", ["stage1_extract.py", url])
    return {"job_id": job_id}


@app.post("/api/mine")
def mine(limit: int | None = None) -> dict:
    cmd = ["stage2_pattern.py", "--all"]
    if limit:
        cmd += ["--limit", str(limit)]
    job_id = jobs.create_job("mine", "تشريح الأنماط", cmd)
    return {"job_id": job_id}


@app.post("/api/generate")
def generate(product_file: str = Form(...), category: str | None = Form(None),
             pattern: str | None = Form(None), match_only: bool = Form(False),
             connection: str | None = Form(None), model: str | None = Form(None),
             tag: str | None = Form(None), hooks: int | None = Form(None)) -> dict:
    path = Path(config.PRODUCTS_DIR) / Path(product_file).name
    if not path.exists():
        raise HTTPException(404, "ملف المنتج غير موجود")
    cmd = ["stage3_generate.py", str(path)]
    if hooks:
        import script_hooks
        cmd += ["--hooks", str(script_hooks.clean_requested(hooks))]
    if category:
        cmd += ["--category", category]
    if pattern:
        cmd += ["--pattern", pattern]
    if match_only:
        cmd.append("--match-only")
    if connection:
        cmd += ["--connection", connection]
    if model:
        cmd += ["--model", model]
    if tag:
        cmd += ["--label", re.sub(r"[^\w-]+", "", tag)[:20]]
    label = f"{'مطابقة' if match_only else 'توليد'}: {path.stem}"
    if model:
        label += f" ({model})"
    return {"job_id": jobs.create_job("generate", label, cmd)}


@app.post("/api/compare")
def compare(product_file: str = Form(...), models: str = Form(...),
            pattern: str | None = Form(None)) -> dict:
    """
    يولّد نفس السيناريو بأكتر من موديل عشان تقارن.
    models: "conn_id:model_id" مفصولين بفاصلة.
    """
    path = Path(config.PRODUCTS_DIR) / Path(product_file).name
    if not path.exists():
        raise HTTPException(404, "ملف المنتج غير موجود")

    specs = [s.strip() for s in models.split(",") if s.strip()]
    if len(specs) < 2:
        raise HTTPException(400, "اختر موديلين ع الأقل للمقارنة")

    job_ids = []
    for i, spec in enumerate(specs, 1):
        conn_id, _, model_id = spec.partition(":")
        cmd = ["stage3_generate.py", str(path), "--connection", conn_id,
               "--model", model_id, "--label", f"cmp{i}"]
        if pattern:
            cmd += ["--pattern", pattern]
        job_ids.append(jobs.create_job("generate", f"مقارنة {i}: {model_id}", cmd))
    return {"job_ids": job_ids, "count": len(job_ids)}


@app.get("/api/jobs")
def api_jobs() -> list[dict]:
    return jobs.list_jobs()


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    result = jobs.cancel_job(job_id)
    if result == "not_found":
        raise HTTPException(404, "المهمة غير موجودة")
    if result == "not_active":
        raise HTTPException(400, "المهمة خلصت — ما في شي يتوقف")
    return {"ok": True, "result": result}


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str) -> dict:
    result = jobs.pause_job(job_id)
    errors = {
        "not_found": (404, "المهمة غير موجودة"),
        "not_running": (400, "المهمة مش شغالة"),
        "no_psutil": (500, "ثبّت psutil عشان التوقيف المؤقت: pip install psutil"),
    }
    if result in errors:
        raise HTTPException(*errors[result])
    return {"ok": True, "result": result}


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    result = jobs.resume_job(job_id)
    errors = {
        "not_found": (404, "المهمة غير موجودة"),
        "not_paused": (400, "المهمة مش موقوفة مؤقتاً"),
        "lost": (410, "ضاعت العملية — لازم تعيد تشغيل المهمة"),
    }
    if result in errors:
        raise HTTPException(*errors[result])
    return {"ok": True, "result": result}


# الموديلات المتاحة لكل مهمة — تُعرض بالواجهة كقوائم
CLAUDE_MODELS = [
    {"id": "claude-opus-5", "label": "Opus 5 — الأقوى (الأغلى)"},
    {"id": "claude-sonnet-5", "label": "Sonnet 5 — متوازن (موصى للتحليل)"},
    {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5 — الأسرع والأرخص"},
]
WHISPER_MODELS = ["large-v3", "medium", "small", "base", "tiny"]


def _read_settings() -> dict:
    path = Path(config.SETTINGS_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


# البرومبتات: وصف كل واحد + المتغيّرات اللي لازم تضل موجودة فيه
PROMPT_INFO = {
    "pattern_miner.txt": {
        "label": "تشريح الفيديو", "task": "analysis",
        "desc": "بيحوّل الفيديو المستخرج لبصمة نمط. أي تعديل بيغيّر شكل كل الأنماط الجديدة.",
        "required": [],
    },
    "pattern_matcher.txt": {
        "label": "مطابقة المنتج بالأنماط", "task": "match",
        "desc": "بيرتّب أفضل 3 أنماط لمنتجك ويشرح سبب كل اختيار.",
        "required": [],
    },
    "script_writer.txt": {
        "label": "كتابة السيناريو", "task": "writer",
        "desc": "قلب التوليد — القيود واللهجة وإيقاع الكلام وبوابات الجودة.",
        "required": ["{{SCENES}}", "{{MIN_SEC}}", "{{MAX_SEC}}"],
    },
    "product_parser.txt": {
        "label": "قراءة بيانات المنتج من نص", "task": "parser",
        "desc": "بيحوّل النص الحر لحقول منتج منظّمة.",
        "required": [],
    },
    "pattern_importer.txt": {
        "label": "استيراد أنماط من مستند", "task": "importer",
        "desc": "بيستخرج الأطر القابلة لإعادة الاستخدام من أي مستند نصي.",
        "required": [],
    },
    "hook_writer.txt": {
        "label": "كتابة هوك بديل", "task": "writer",
        "desc": "بيكتب هوك واحد جديد (أو بدل موجود) لسيناريو جاهز، بنفس قواعد البريف.",
        "required": [],
    },
    "pattern_translator.txt": {
        "label": "ترجمة الأنماط للعربي", "task": "translate",
        "desc": "بيترجم نصوص الأنماط (الاسم، الهوك، المشاهد…) للعربي مرة وحدة لكل نمط. الأصل الإنجليزي بيضل محفوظ.",
        "required": [],
    },
    "pattern_learner.txt": {
        "label": "التعلّم من نتايجك", "task": "analysis",
        "desc": "بيقارن السيناريوهات الناجحة بالفاشلة ويستخرج الآلية اللي فسّرت الفرق.",
        "required": [],
    },
}

DEFAULTS_DIR = Path(config.PROMPTS_DIR) / ".defaults"


def _prompt_path(name: str) -> Path:
    safe = Path(name).name
    if safe not in PROMPT_INFO:
        raise HTTPException(404, "برومبت غير معروف")
    return Path(config.PROMPTS_DIR) / safe


@app.get("/api/prompts")
def list_prompts() -> list[dict]:
    out = []
    for name, info in PROMPT_INFO.items():
        path = Path(config.PROMPTS_DIR) / name
        default = DEFAULTS_DIR / name
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        original = default.read_text(encoding="utf-8") if default.exists() else ""
        out.append({
            "file": name, "label": info["label"], "task": info["task"],
            "desc": info["desc"], "required": info["required"],
            "chars": len(current), "lines": current.count("\n") + 1 if current else 0,
            "modified": bool(original) and current != original,
            "has_default": bool(original),
        })
    return out


@app.get("/api/prompts/{name}")
def read_prompt(name: str) -> dict:
    path = _prompt_path(name)
    if not path.exists():
        raise HTTPException(404, "الملف غير موجود")
    default = DEFAULTS_DIR / Path(name).name
    return {
        "file": path.name,
        "content": path.read_text(encoding="utf-8"),
        "default": default.read_text(encoding="utf-8") if default.exists() else "",
        **PROMPT_INFO[path.name],
    }


@app.put("/api/prompts/{name}")
async def write_prompt(name: str, payload: dict) -> dict:
    path = _prompt_path(name)
    content = payload.get("content", "")
    if not content.strip():
        raise HTTPException(400, "البرومبت ما بينفع يكون فاضي")

    # المتغيّرات بينحقنوا من الإعدادات وقت التشغيل — بدونها التوليد بيكسر بصمت
    missing = [v for v in PROMPT_INFO[path.name]["required"] if v not in content]
    if missing:
        raise HTTPException(
            400,
            f"ناقص متغيّرات إلزامية: {'، '.join(missing)} — "
            "بدونها القيم من الإعدادات ما رح توصل للموديل"
        )

    path.write_text(content, encoding="utf-8")
    return {"ok": True, "chars": len(content)}


@app.post("/api/prompts/{name}/restore")
def restore_prompt(name: str) -> dict:
    path = _prompt_path(name)
    default = DEFAULTS_DIR / path.name
    if not default.exists():
        raise HTTPException(404, "ما في نسخة افتراضية محفوظة")
    path.write_text(default.read_text(encoding="utf-8"), encoding="utf-8")
    return {"ok": True}


@app.get("/api/usage")
def api_usage(days: int | None = None, balances: bool = True) -> dict:
    """الاستهلاك والتكلفة المقدّرة، مع رصيد المزوّدين اللي بيدعموا الاستعلام.

    balances=False بيتخطّى كل نداءات الشبكة لرصيد المزوّدين (بيستعملها شريحة الصرف
    بالهيدر كل 10 دقايق، بلا ما تبطّئ الصفحة).
    """
    import usage as usage_mod
    import llm

    data = usage_mod.summary(days)

    # اسأل كل مزوّد مستخدم فعلاً عن رصيده (اللي بيدعم) — إلا إذا طلبوا بلا أرصدة
    if balances:
        provider_balances = {}
        seen = set()
        for task in llm.TASK_LABELS:
            cfg = llm.task_config(task)
            if cfg["provider"] in seen:
                continue
            seen.add(cfg["provider"])
            provider_balances[cfg["provider"]] = usage_mod.provider_balance(cfg["provider"], cfg["api_key"])
        data["balances"] = provider_balances

    return data


@app.get("/api/connections")
def list_connections() -> dict:
    import connections, llm
    return {
        "connections": connections.public_view(),
        "providers": {
            pid: {"label": p["label"], "region": p.get("region", "أخرى"),
                  "base_url": p["base_url"], "vision": p["vision"],
                  "env_key": p.get("env_key", ""), "note": p.get("note", "")}
            for pid, p in llm.PROVIDER_PRESETS.items()
        },
    }


@app.post("/api/connections")
async def create_connection(payload: dict) -> dict:
    """ينشئ اتصال ويجلب موديلاته الحيّة من المزوّد. المفتاح الغلط بيفشل هون فوراً."""
    import connections
    try:
        conn = connections.create(
            payload.get("provider", ""), payload.get("api_key", ""),
            payload.get("label", ""), payload.get("base_url", ""),
        )
    except connections.ConnectionError_ as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": conn["id"], "models": len(conn["models"])}


@app.post("/api/connections/{conn_id}/refresh")
def refresh_connection(conn_id: str) -> dict:
    import connections
    try:
        conn = connections.refresh(conn_id)
    except connections.ConnectionError_ as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "models": len(conn["models"]), "fetched_at": conn["fetched_at"]}


@app.delete("/api/connections/{conn_id}")
def delete_connection(conn_id: str) -> dict:
    import connections
    connections.delete(conn_id)
    return {"ok": True}


@app.get("/api/auto-picks")
def auto_picks() -> dict:
    """شو رح يختار النظام تلقائياً لكل مهمة — عشان تشوف قبل ما تشغّل."""
    import connections, llm
    out = {}
    for task, label in llm.TASK_LABELS.items():
        pick = connections.auto_pick(task)
        out[task] = {
            "label": label,
            "tier": connections.TASK_PROFILE.get(task, {}).get("tier"),
            "needs_vision": connections.TASK_PROFILE.get(task, {}).get("vision", False),
            "pick": pick,
        }
    return out


@app.get("/api/tasks")
def get_tasks() -> dict:
    """إعداد المزوّد/الموديل/المفتاح لكل مهمة — المفاتيح مقنّعة."""
    import llm
    saved = _read_settings()
    tasks = {}
    for task, label in llm.TASK_LABELS.items():
        cfg = llm.task_config(task)
        entry = (saved.get("TASKS") or {}).get(task) or {}
        key = cfg["api_key"]
        tasks[task] = {
            "label": label,
            "needs_vision": task == "analysis",
            "provider": cfg["provider"],
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "key_set": bool(key),
            "key_masked": f"{key[:10]}…{key[-4:]}" if len(key) > 18 else ("مضبوط" if key else ""),
            "key_from_task": bool(entry.get("api_key")),
        }
    return {
        "tasks": tasks,
        "providers": {
            pid: {
                "label": p["label"], "base_url": p["base_url"], "vision": p["vision"],
                "models": p["models"], "env_key": p["env_key"],
                "region": p.get("region", "أخرى"), "note": p.get("note", ""),
            }
            for pid, p in llm.PROVIDER_PRESETS.items()
        },
    }


@app.put("/api/tasks/{task}")
async def save_task(task: str, payload: dict) -> dict:
    import llm
    if task not in llm.TASK_LABELS:
        raise HTTPException(404, "مهمة غير معروفة")

    saved = _read_settings()
    tasks = saved.setdefault("TASKS", {})
    conn_id = str(payload.get("connection", "")).strip()

    if not conn_id:
        tasks[task] = {}          # فاضي = ارجع للاختيار التلقائي
    else:
        conns = saved.get("CONNECTIONS") or {}
        conn = conns.get(conn_id)
        if not conn:
            raise HTTPException(404, "اتصال غير موجود")
        preset = llm.PROVIDER_PRESETS.get(conn["provider"], {})
        if task == "analysis" and not preset.get("vision", True):
            raise HTTPException(400, "تشريح الفيديو بدّه مزوّد بيدعم الصور")
        tasks[task] = {"connection": conn_id, "model": str(payload.get("model", "")).strip()}

    settings_io.save(saved)
    return {"ok": True}


@app.delete("/api/tasks/{task}/key")
def clear_task_key(task: str) -> dict:
    saved = _read_settings()
    (saved.get("TASKS") or {}).get(task, {}).pop("api_key", None)
    settings_io.save(saved)
    return {"ok": True}


@app.post("/api/providers/{provider}/models")
async def add_provider_model(provider: str, payload: dict) -> dict:
    import llm
    if provider not in llm.PROVIDER_PRESETS:
        raise HTTPException(404, "مزوّد غير معروف")
    try:
        return {"ok": True, "models": llm.add_model(provider, payload.get("model", ""))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/providers/{provider}/models/{model:path}")
def delete_provider_model(provider: str, model: str) -> dict:
    import llm
    return {"ok": True, "models": llm.remove_model(provider, model)}


@app.get("/api/stt")
def get_stt() -> dict:
    """إعداد التفريغ الصوتي — المزوّد والموديل واللغة."""
    import stt
    cfg = stt.stt_config()
    key = cfg["api_key"]
    return {
        "current": {
            "provider": cfg["provider"], "model": cfg["model"],
            "language": cfg["language"] or "", "base_url": cfg["base_url"],
            "key_set": bool(key),
            "key_masked": f"{key[:8]}…{key[-4:]}" if len(key) > 14 else ("مضبوط" if key else ""),
        },
        "providers": {
            pid: {
                "label": p["label"], "models": p["models"], "cost": p.get("cost", ""),
                "note": p.get("note", ""), "env_key": p.get("env_key", ""),
                "local": p["kind"] == "local",
            }
            for pid, p in stt.STT_PRESETS.items()
        },
    }


@app.put("/api/stt")
async def save_stt(payload: dict) -> dict:
    import stt
    provider = payload.get("provider", "local_whisper")
    if provider not in stt.STT_PRESETS:
        raise HTTPException(400, "مزوّد تفريغ غير معروف")

    saved = _read_settings()
    entry = saved.setdefault("STT", {})
    entry["provider"] = provider
    entry["model"] = str(payload.get("model", "")).strip()
    entry["language"] = str(payload.get("language", "")).strip()
    entry["base_url"] = str(payload.get("base_url", "")).strip()
    new_key = str(payload.get("api_key", "")).strip()
    if new_key:
        entry["api_key"] = new_key

    settings_io.save(saved)
    return {"ok": True}


@app.get("/api/settings")
def get_settings() -> dict:
    """القيم الفعّالة الحالية. المفتاح بينرجع مقنّع فقط — أبداً كامل."""
    import os
    import importlib
    # المهام الفرعية بتستورد config من جديد كل مرة، فبتشوف آخر settings.json.
    # السيرفر استورده مرة وحدة عند الإقلاع، فلازم نعيد تحميله عشان نعرض
    # نفس اللي رح ينفّذ فعلاً — مش نسخة قديمة بالذاكرة.
    importlib.reload(config)
    saved = _read_settings()
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return {
        "values": {k: getattr(config, k, None) for k in sorted(config.OVERRIDABLE)},
        "overridden": sorted(k for k in saved if k in config.OVERRIDABLE),
        "api_key": {
            "set": bool(key),
            "masked": f"{key[:12]}…{key[-4:]}" if len(key) > 20 else ("مضبوط" if key else ""),
            "from_settings": bool(saved.get("ANTHROPIC_API_KEY")),
        },
        "choices": {
            "models": CLAUDE_MODELS,
            "whisper_models": WHISPER_MODELS,
            "whisper_devices": ["cuda", "cpu"],
            "whisper_computes": ["int8_float16", "float16", "int8", "float32"],
        },
    }


@app.put("/api/settings")
async def save_settings(payload: dict) -> dict:
    saved = _read_settings()

    for k, v in payload.items():
        if k == "ANTHROPIC_API_KEY":
            v = str(v).strip()
            if v:                      # فاضي = ما تلمس المحفوظ
                saved[k] = v
            continue
        if k in config.OVERRIDABLE:
            saved[k] = v

    settings_io.save(saved)
    return {"ok": True, "note": "التعديلات بتسري على المهام الجديدة"}


@app.delete("/api/settings/api-key")
def clear_api_key() -> dict:
    saved = _read_settings()
    saved.pop("ANTHROPIC_API_KEY", None)
    settings_io.save(saved)
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    import os
    return {
        "ok": True,
        "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "whisper_device": config.WHISPER_DEVICE,
        "ocr_gpu": config.OCR_USE_GPU,
    }


@app.middleware("http")
async def no_cache_static(request, call_next):
    """
    المتصفح بيخزّن style.css و app.js بعناد، فبتضل تشوف نسخة قديمة بعد كل تعديل.
    أداة محلية بتتطوّر باستمرار — الصحة أهم من سرعة التحميل.
    """
    response = await call_next(request)
    if request.url.path.endswith((".css", ".js", ".html")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        # ETag بيخلي المتصفح يسأل "تغيّر؟" ويقبل 304 — لازم نشيله كمان
        for h in ("etag", "last-modified"):
            if h in response.headers:
                del response.headers[h]
    return response


for _r in (routes_pipeline.router, routes_crm.router, routes_ops.router, routes_studio.router, routes_characters.router, routes_motion.router, routes_montage.router, routes_ext.router, routes_claims.router, routes_hooks.router, routes_hooks_bank.router, routes_patterns.router, routes_placements.router, routes_presets.router, routes_auth.router, routes_ads.router, routes_free.router, routes_model_library.router, routes_drive.router):
    app.include_router(_r)

@app.get("/icons.svg", include_in_schema=False)
def _icons_alias():
    """قشرة zaki-ui (vendor) بتطلب icons.svg نسبياً من الجذر ← نفس ملف الأيقونات المنسوخ بـ vendor/zaki-ui."""
    return FileResponse(STATIC_DIR / "vendor" / "zaki-ui" / "icons.svg", media_type="image/svg+xml")


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
