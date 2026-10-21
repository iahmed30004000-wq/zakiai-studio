"""
مسارات حلقة الأداء (CRM + الدليل + الإرهاق + التعلّم).

الـ router بيتضم لـ web/app.py من المنسّق. كل مسار تحت /api، والأخطاء `{"detail": "عربي"}`.
التوكن ما بيرجع بأي استجابة ولا بينكتب بأي ملف — بيروح لمخزن الأسرار بس.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import crm  # noqa: E402

router = APIRouter(prefix="/api")


def _create_job(kind: str, label: str, cmd: list[str]) -> str:
    from web import jobs                                    # استيراد متأخر
    return jobs.create_job(kind, label, cmd)


# ───────────────────────────── الـ OMS ─────────────────────────────


@router.get("/crm/status")
def crm_status() -> dict:
    st = crm.sync_state()
    pending = None
    try:
        import queue_worker
        pending = queue_worker.pending_count()
    except Exception:
        pending = None

    last_backup = days_since = alert = None
    try:
        import backup
        b = backup.status() or {}
        last_backup = b.get("last_backup")
        days_since = b.get("days_since_backup")
        alert = b.get("backup_alert")
    except Exception:
        pass

    configured = crm.is_configured()
    return {
        "configured": configured,
        "token_set": bool(crm.get_token()),
        "launch_token_set": _launch_token_set(),
        "base_url": crm.base_url(),
        "connected": bool(configured and st["last_success"] and not st["last_error"]),
        "last_sync": {"at": st["last_success"] or st["last_attempt"], "ok": bool(st["last_success"]) and not st["last_error"],
                      "error": st["last_error"], "rows": st["rows"]},
        "pending_queue": pending,
        "last_backup": last_backup, "days_since_backup": days_since, "backup_alert": alert,
    }


def _launch_token_set() -> bool:
    try:
        import launch
        return bool(launch.launch_token())
    except Exception:
        return False


def _save_base_url(url: str) -> None:
    try:
        import settings_io
    except ImportError:
        settings_io = None
    if settings_io is not None:
        data = settings_io.load()
        data.setdefault("CRM", {})["base_url"] = url
        settings_io.save(data)
        return
    path = Path(config.SETTINGS_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("CRM", {})["base_url"] = url
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@router.put("/crm/config")
def crm_config(payload: dict) -> dict:
    try:
        url = crm.validate_base_url(payload.get("base_url"))
    except crm.CRMError as e:
        raise HTTPException(400, str(e))

    token = payload.get("token")
    if token is not None and not isinstance(token, str):
        raise HTTPException(400, "التوكن لازم يكون نص")
    if token and token.strip():
        try:
            import secrets_store
        except ImportError:
            raise HTTPException(503, "مخزن الأسرار غير متاح — ما بنحفظ التوكن بأي ملف")
        try:
            secrets_store.set_secret("crm_token", token.strip())
        except Exception:
            raise HTTPException(500, "تعذّر حفظ التوكن بمخزن الأسرار")
    lt = payload.get("launch_token")
    if lt is not None and not isinstance(lt, str):
        raise HTTPException(400, "توكن الإطلاق لازم يكون نص")
    if lt and lt.strip():
        try:
            import secrets_store
            secrets_store.set_secret("crm_token_launch", lt.strip())
        except ImportError:
            raise HTTPException(503, "مخزن الأسرار غير متاح — ما بنحفظ التوكن بأي ملف")
        except Exception:
            raise HTTPException(500, "تعذّر حفظ توكن الإطلاق بمخزن الأسرار")
    _save_base_url(url)
    return {"ok": True, "base_url": url, "token_set": bool(crm.get_token()), "launch_token_set": _launch_token_set()}


@router.delete("/crm/token")
def crm_delete_token() -> dict:
    try:
        import secrets_store
        secrets_store.delete_secret("crm_token")
    except ImportError:
        raise HTTPException(503, "مخزن الأسرار غير متاح")
    except Exception:
        raise HTTPException(500, "تعذّر حذف التوكن من مخزن الأسرار")
    return {"ok": True, "token_set": bool(crm.get_token())}


@router.delete("/crm/launch-token")
def crm_delete_launch_token() -> dict:
    try:
        import secrets_store
        secrets_store.delete_secret("crm_token_launch")
    except ImportError:
        raise HTTPException(503, "مخزن الأسرار غير متاح")
    except Exception:
        raise HTTPException(500, "تعذّر حذف التوكن من مخزن الأسرار")
    return {"ok": True, "launch_token_set": _launch_token_set()}


@router.post("/crm/sync")
def crm_sync() -> dict:
    if not crm.is_configured():
        raise HTTPException(400, "الـ OMS غير مضبوط — أدخل العنوان والتوكن أولاً")
    return {"job_id": _create_job("crm_sync", "مزامنة أداء الإعلانات من الـ OMS", ["crm.py", "sync"])}


# ───────────────────────────── اسم الإعلان ─────────────────────────────


@router.get("/scripts/{file}/ad-name")
def script_ad_name(file: str) -> dict:
    import adname
    import brief

    name = Path(file).name
    if not name.endswith(".json"):
        name += ".json"
    path = Path(config.SCRIPTS_DIR) / name
    if not path.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    try:
        meta = json.loads(path.read_text(encoding="utf-8")).get("_meta") or {}
    except ValueError:
        raise HTTPException(500, "ملف السيناريو تالف")

    script_id = meta.get("script_id")
    ppath = Path(config.PRODUCTS_DIR) / Path(meta.get("product_file") or "").name if meta.get("product_file") else None
    b = brief.load(ppath) if ppath and ppath.exists() else None

    missing: list[str] = []
    if b is None:
        missing.append("product_file")
    else:
        missing += list(brief.completeness(b)["publish_missing"])
    if not adname.is_script_id(script_id):
        missing.append("script_id")

    parts = {"country": (b or {}).get("country") or None, "product": (b or {}).get("product_code") or None,
             "landing_page": (b or {}).get("landing_page") or None, "type": adname.AD_TYPE,
             "script_id": script_id if adname.is_script_id(script_id) else None}
    ready = not missing
    return {"ad_name": adname.build(parts["country"], parts["product"], parts["landing_page"], parts["script_id"])
            if ready else None, "ready": ready, "missing": missing, "parts": parts}


# ───────────────────────────── الأداء والدليل ─────────────────────────────


@router.get("/performance/patterns")
def performance_patterns() -> list[dict]:
    import evidence
    keep = ("pattern_id", "name", "evidence_level", "evidence_score", "delivered", "spend",
            "cost_per_delivered", "scripts", "reusability_opinion",
            "reason", "cost_vs_baseline", "baseline_available", "scripts_total", "as_of")
    return [{k: e[k] for k in keep} for e in evidence.ranked_patterns()]


@router.get("/performance/scripts")
def performance_scripts() -> list[dict]:
    import evidence
    keep = ("script_file", "script_id", "delivered", "spend", "cost_per_delivered", "delivery_rate",
            "verdict", "reason", "pattern_id", "baseline_cpd", "cost_vs_baseline", "as_of")
    order = {"winner": 0, "ok": 1, "loser": 2, "insufficient": 3}
    rows = [{k: v[k] for k in keep} for v in evidence.script_verdicts().values()]
    return sorted(rows, key=lambda r: (order[r["verdict"]], -r["delivered"], r["script_file"]))


@router.get("/performance/alerts")
def performance_alerts() -> list[dict]:
    import fatigue
    return fatigue.current_alerts()


# ───────────────────────────── المسودات ─────────────────────────────


@router.get("/drafts")
def drafts_list(status: str | None = None) -> list[dict]:
    import drafts
    return drafts.list_drafts(status)


@router.post("/drafts/scan")
def drafts_scan() -> dict:
    import fatigue
    created = fatigue.scan_and_draft()
    return {"created": created, "errors": list(fatigue.last_errors)}


@router.post("/drafts/{draft_id}/approve")
def drafts_approve(draft_id: str) -> dict:
    """بيبدأ كتابة السيناريو كمهمة (بتاخد دقايق) — الحالة بتصير approving فوراً."""
    import drafts
    try:
        drafts.begin_approve(draft_id)
    except drafts.DraftError as e:
        raise HTTPException(404 if "غير موجودة" in str(e) else 409, str(e))
    job_id = _create_job("draft_approve", f"كتابة سيناريو بديل: {draft_id}",
                         ["drafts.py", "approve", draft_id, "--started"])
    return {"ok": True, "job_id": job_id, "draft_id": draft_id, "status": "approving"}


@router.post("/drafts/{draft_id}/dismiss")
def drafts_dismiss(draft_id: str) -> dict:
    import drafts
    try:
        d = drafts.dismiss(draft_id)
    except drafts.DraftError as e:
        raise HTTPException(404 if "غير موجودة" in str(e) else 409, str(e))
    return {"ok": True, "draft_id": d["id"], "status": d["status"]}


# ───────────────────────────── التعلّم ─────────────────────────────


@router.post("/learning/run")
def learning_run() -> dict:
    return {"job_id": _create_job("learn", "تعلّم أنماط من الأداء الفعلي", ["learn_patterns.py"])}


@router.get("/learning/last")
def learning_last() -> dict:
    import learn_patterns
    return learn_patterns.last_run()
