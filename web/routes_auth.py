"""الدخول والموظفين والنشاط: /api/auth/* (عامة جزئياً — راجع auth_gate) + /api/accounts + /api/activity."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import accounts
import activity

router = APIRouter(prefix="/api")
COOKIE = "vp_session"
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def _err(e: accounts.AccountError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _token(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def _set_cookie(resp: JSONResponse, token: str, request: Request) -> None:
    resp.set_cookie(COOKIE, token, max_age=accounts.SESSION_DAYS * 86400, httponly=True, samesite="lax", path="/",
                    secure=request.url.scheme == "https")


def _me() -> dict:
    a = accounts.actor()
    if not a or a.get("id") == 0:
        raise HTTPException(401, "لازم تسجّل دخولك")
    return a


# ── الدخول (عامة) ────────────────────────────────────────────────────────
@router.get("/auth/me")
def auth_me(request: Request) -> dict:
    """مين أنا؟ + هل لازم أنشئ أول حساب. عامة (صفحة الدخول بتسألها)."""
    user = accounts.session_user(_token(request))
    return {"user": user, "needs_setup": accounts.needs_setup(), "seats_note": accounts.seats_note() if user else ""}


@router.post("/auth/setup")
def auth_setup(payload: dict, request: Request) -> JSONResponse:
    """الحساب الأول (المالك): بس لو ما في أي حساب، وبس من نفس الجهاز (إلا VP_ALLOW_REMOTE_SETUP=1، مثلاً Docker)."""
    host = request.client.host if request.client else ""
    if host not in LOOPBACK and os.environ.get("VP_ALLOW_REMOTE_SETUP") != "1":
        raise HTTPException(403, "أنشئ الحساب الأول من نفس الجهاز اللي شغّال عليه الاستوديو")
    try:
        u = accounts.create_first(payload.get("display_name"), payload.get("username"), payload.get("password"))
    except accounts.AccountError as e:
        raise _err(e)
    resp = JSONResponse({"user": u})
    _set_cookie(resp, accounts.create_session(u["id"], request.headers.get("user-agent", "")), request)
    activity.record_event(u, "account", "أنشأ الحساب الأول (صاحب الاستوديو)")
    return resp


@router.post("/auth/login")
def auth_login(payload: dict, request: Request) -> JSONResponse:
    try:
        u = accounts.authenticate(payload.get("username"), payload.get("password"))
    except accounts.AccountError as e:
        raise _err(e)
    resp = JSONResponse({"user": u})
    _set_cookie(resp, accounts.create_session(u["id"], request.headers.get("user-agent", "")), request)
    activity.record_event(u, "account", "سجّل دخوله")
    return resp


@router.post("/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    tok = _token(request)
    u = accounts.session_user(tok)
    accounts.end_session(tok)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    if u:
        activity.record_event(u, "account", "سجّل خروجه")
    return resp


@router.post("/auth/password")
def auth_password(payload: dict, request: Request) -> dict:
    """الموظف بيغيّر كلمة سره (بيطلب القديمة). بيطلّع باقي جلساته."""
    me = _me()
    try:
        u = accounts.change_password(me["id"], payload.get("old"), payload.get("new"), keep_token=_token(request))
    except accounts.AccountError as e:
        raise _err(e)
    return {"user": u}


# ── الموظفين (بلا صلاحيات: أي موظف بيدير) ─────────────────────────────────
@router.get("/accounts")
def accounts_list() -> dict:
    me = _me()
    return {"users": accounts.list_users(), "me": me["id"], "seats_note": accounts.seats_note(), "free_seats": accounts.REMOTION_FREE_SEATS}


@router.post("/accounts")
def accounts_add(payload: dict) -> dict:
    me = _me()
    try:
        u = accounts.add_user(payload.get("display_name"), payload.get("username"), payload.get("password"), by=me["display_name"])
    except accounts.AccountError as e:
        raise _err(e)
    activity.record_event(me, "account", f"أضاف الموظف «{u['display_name']}» ({u['username']})")
    return {"user": u, "seats_note": accounts.seats_note()}


@router.put("/accounts/{uid}/active")
def accounts_active(uid: int, payload: dict) -> dict:
    me = _me()
    try:
        u = accounts.set_active(me["id"], uid, bool(payload.get("active")))
    except accounts.AccountError as e:
        raise _err(e)
    activity.record_event(me, "account", f"{'فعّل' if u['active'] else 'عطّل'} حساب «{u['display_name']}»")
    return {"user": u, "seats_note": accounts.seats_note()}


@router.post("/accounts/{uid}/reset")
def accounts_reset(uid: int, payload: dict) -> dict:
    me = _me()
    try:
        u = accounts.reset_password(me["id"], uid, payload.get("password"))
    except accounts.AccountError as e:
        raise _err(e)
    activity.record_event(me, "account", f"صفّر كلمة سر «{u['display_name']}» (بيغيّرها بأول دخول)")
    return {"user": u}


# ── النشاط ───────────────────────────────────────────────────────────────
@router.get("/activity")
def activity_list(user: int | None = None, kind: str | None = None, since: str | None = None, until: str | None = None,
                  limit: int = 100, offset: int = 0) -> dict:
    """مين عمل شو ومتى (الأحدث أول). since/until: وقت ISO UTC (الواجهة بتحوّل بداية/نهاية اليوم المحلي)."""
    _me()
    if kind and kind not in activity.KINDS:
        raise HTTPException(400, "نوع غير معروف — المتاح: " + "، ".join(activity.KINDS))
    out = activity.list_events(user, kind, since, until, limit, offset)
    out["kinds"] = activity.KINDS
    out["users"] = [{"id": u["id"], "name": u["display_name"]} for u in accounts.list_users()] + [{"id": 0, "name": "الإضافة"}]
    return out
