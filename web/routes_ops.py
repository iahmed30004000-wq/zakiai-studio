"""
مسارات التشغيل والأمان — الطابور، النسخ الاحتياطي، حدود الإنفاق، الجدولة.
الأخطاء: {"detail": "رسالة عربية"}.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _require_local(request: Request) -> None:
    """المفتاح ما بينعرض إلا من نفس الجهاز — حتى لو السيرفر مفتوح على الشبكة (--lan)."""
    host = request.client.host if request.client else ""
    if host not in _LOCAL_HOSTS:
        raise HTTPException(403, "هاد الإجراء متاح من نفس الجهاز بس")


# ── الطابور ────────────────────────────────────────────────────────────


@router.get("/queue")
def get_queue() -> dict:
    import queue_worker
    return queue_worker.local_view()


@router.post("/queue/poll")
def poll_queue() -> dict:
    import queue_worker
    return queue_worker.poll_once()


# ── النسخ الاحتياطي ─────────────────────────────────────────────────────


@router.get("/backup/status")
def backup_status() -> dict:
    import backup
    return backup.status()


@router.get("/backup/config")
def backup_config() -> dict:
    import backup
    return backup.get_config()


@router.put("/backup/config")
def set_backup_config(payload: dict) -> dict:
    import backup
    try:
        return backup.set_config(str(payload.get("dir") or ""),
                                 bool(payload.get("include_source_videos", False)))
    except backup.BackupError as e:
        raise HTTPException(400, str(e))


@router.post("/backup/run")
def backup_run(payload: dict | None = None) -> dict:
    import backup
    videos = (payload or {}).get("include_source_videos")
    try:
        return backup.run(include_source_videos=None if videos is None else bool(videos))
    except backup.BackupError as e:
        raise HTTPException(400, str(e))


@router.post("/backup/restore-test")
def backup_restore_test() -> dict:
    import backup
    try:
        return backup.restore_test()
    except backup.BackupError as e:
        raise HTTPException(400, str(e))


@router.post("/backup/export-key")
def backup_export_key(request: Request) -> dict:
    import backup
    import secrets_store
    _require_local(request)
    try:
        return backup.export_key()
    except secrets_store.SecretsError as e:
        raise HTTPException(500, str(e))


# ── حدود الإنفاق ────────────────────────────────────────────────────────


@router.get("/settings/spend-limits")
def get_spend_limits() -> dict:
    import usage
    st = usage.limit_status()
    return {"daily_usd": st["limits"]["daily_usd"], "monthly_usd": st["limits"]["monthly_usd"],
            "spent_today_usd": st["spent"]["daily_usd"], "spent_month_usd": st["spent"]["monthly_usd"],
            "blocked": st["blocked"], "reason": st["reason"],
            "note": "الإنفاق تقديري (توكنز × جدول الأسعار) لنداءات الموديلات فقط. فاضي أو صفر = بلا حد."}


@router.put("/settings/spend-limits")
def put_spend_limits(payload: dict) -> dict:
    import usage
    try:
        usage.set_limits(payload.get("daily_usd"), payload.get("monthly_usd"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_spend_limits()


# ── الجدولة ────────────────────────────────────────────────────────────


@router.get("/scheduler/status")
def scheduler_status() -> dict:
    import scheduler
    return scheduler.status()
