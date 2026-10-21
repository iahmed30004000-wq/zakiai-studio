"""تسجيل الدخول بفيسبوك (ميتا) وسحب الحسابات والإعلانات — راجع ads_meta.py. كل المسارات من نفس الجهاز بس."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/ads/meta")
BACK = "/#/factory/api/keys"


def _local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "بس من نفس الجهاز")


async def _m(fn, *a, **k):
    import ads_meta
    try:
        return await run_in_threadpool(fn, *a, **k)
    except ads_meta.MetaError as e:
        raise HTTPException(409 if e.code in ("token_expired", "not_connected", "not_configured") else 400, str(e))


@router.get("/status")
def status(request: Request) -> dict:
    _local(request)
    import ads_meta
    return ads_meta.status()


@router.put("/app")
async def put_app(request: Request, payload: dict) -> dict:
    _local(request)
    import ads_meta
    cid = payload.get("config_id")
    return await _m(lambda: (ads_meta.set_app(payload.get("app_id"), payload.get("app_secret"), None if cid is None else str(cid)), ads_meta.status())[1])


@router.put("/token")
async def put_token(request: Request, payload: dict) -> dict:
    """طريق بديل: لصق توكن جاهز. بنفس فحوصات الدخول (تطبيقنا + ads_read). التوكن ما بيرجع بأي ردّ."""
    _local(request)
    import ads_meta
    return await _m(ads_meta.set_token, payload.get("token"))


@router.delete("/app")
async def delete_app(request: Request) -> dict:
    _local(request)
    import ads_meta
    await _m(ads_meta.clear_app)
    return ads_meta.status()


@router.get("/start")
async def start(request: Request) -> dict:
    _local(request)
    import ads_meta
    return {"url": await _m(ads_meta.authorize_url)}


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "", error_reason: str = ""):
    """ميتا بترجّع المتصفح لهون. بنرجّعو للواجهة برمز قصير بس (لا توكن ولا رسائل ميتا بالرابط)."""
    _local(request)
    import ads_meta
    if error:
        return RedirectResponse(f"{BACK}?meta=denied", status_code=303)
    try:
        await run_in_threadpool(ads_meta.complete_login, code, state)
    except ads_meta.MetaError as e:
        return RedirectResponse(f"{BACK}?meta=error_{quote(e.code, safe='')}", status_code=303)
    return RedirectResponse(f"{BACK}?meta=connected", status_code=303)


@router.get("/accounts")
async def get_accounts(request: Request) -> dict:
    _local(request)
    import ads_meta
    return {"accounts": await _m(ads_meta.accounts)}


@router.get("/ads")
async def get_ads(request: Request, account: str, days: int = 30) -> dict:
    _local(request)
    import ads_meta
    return await _m(ads_meta.preview, account, days)


@router.post("/sync")
async def post_sync(request: Request, payload: dict) -> dict:
    _local(request)
    import ads_meta
    try:
        days = int(payload.get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    return await _m(ads_meta.sync, str(payload.get("account") or ""), days)


@router.delete("/connection")
async def delete_connection(request: Request) -> dict:
    _local(request)
    import ads_meta
    await _m(ads_meta.disconnect)
    return ads_meta.status()
