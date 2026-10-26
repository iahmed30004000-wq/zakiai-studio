"""ربط Google Drive — راجع gdrive.py (الربط بالرمز) وdrive_sync.py (الطابور والرفع). ولا مسار بيرجّع سر."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

import config

router = APIRouter(prefix="/api/drive")


async def _g(fn, *a, **k):
    import gdrive
    try:
        return await run_in_threadpool(fn, *a, **k)
    except gdrive.DriveTransient as e:
        raise HTTPException(503, str(e))
    except gdrive.DriveError as e:
        raise HTTPException(409 if e.code in ("not_configured", "not_connected", "auth") else 400, str(e))


def _stem(filename: str) -> str:
    p = Path(config.SCRIPTS_DIR) / Path(filename).name
    if p.suffix != ".json" or not p.exists():
        raise HTTPException(404, "السيناريو غير موجود")
    return p.stem


@router.get("/status")
def status() -> dict:
    import drive_sync
    return drive_sync.status()


@router.put("/app")
async def put_app(payload: dict) -> dict:
    """الرمزين من Google Cloud (Client secret بيروح لمخزن الأسرار)، و/أو خيار «ابعت تلقائي»."""
    import drive_sync
    import gdrive

    def go():
        if payload.get("client_id") is not None or payload.get("client_secret") is not None:
            gdrive.set_app(payload.get("client_id"), payload.get("client_secret"))
        if "auto" in payload:
            gdrive.write_cfg(lambda c: c.update(auto=bool(payload.get("auto"))))
        return drive_sync.status()
    return await _g(go)


@router.post("/connect")
async def connect() -> dict:
    """بيطلب رمز من Google: المالك بيفتح الرابط وبيكتب الرمز."""
    import gdrive
    return await _g(gdrive.device_start)


@router.post("/connect/check")
async def connect_check() -> dict:
    """الواجهة بتسأل كل كم ثانية: خلّص المالك؟ (لما يخلص بنبلّش الرفع)."""
    import drive_sync
    import gdrive
    r = await _g(gdrive.device_poll)
    if r.get("state") == "connected":
        drive_sync.start()
        drive_sync.wake()
    return {**r, "status": drive_sync.status()}


@router.post("/disconnect")
async def disconnect() -> dict:
    import drive_sync
    import gdrive

    def go():
        gdrive.disconnect()
        drive_sync.forget_all()
        return drive_sync.status()
    return await _g(go)


@router.post("/sync-all")
async def sync_all() -> dict:
    """«ابعت الإعلانات القديمة»: كل إعلان فيه شي معتمد + الأنماط + مكتبة الصوت."""
    import drive_sync
    import gdrive
    if not gdrive.connected():
        raise HTTPException(409, "اربط درايف أول")
    n = await run_in_threadpool(drive_sync.sync_all)
    return {"requested": n, "status": drive_sync.status()}


@router.post("/retry")
def retry() -> dict:
    import drive_sync
    drive_sync.retry_now()
    return drive_sync.status()


@router.post("/sync/{filename}")
def sync_ad(filename: str) -> dict:
    import drive_sync
    import gdrive
    stem = _stem(filename)
    if not gdrive.connected():
        raise HTTPException(409, "اربط درايف أول (الإعدادات ← النسخ والصرف)")
    drive_sync.request_ad(stem, manual=True)
    return drive_sync.ad_status(stem)


@router.get("/ad/{filename}")
def ad_status(filename: str) -> dict:
    import drive_sync
    return drive_sync.ad_status(_stem(filename))
