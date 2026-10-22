"""
حارس الدخول (ASGI صافي): كل /api/* بدها جلسة موظف (كوكي vp_session)، إلا لائحة صغيرة عامة، أو توكن الإضافة على مسارات الإضافة بس.

  · الصفحات والملفات الثابتة عامة (لازم تنعرض صفحة الدخول). وصفحة التطبيق «/» بلا جلسة ← تحويل لـ /login.html (إلا وضع التجربة ?mock=1).
  · مسارات عامة: /api/auth/me|login|setup|logout، ورد فيسبوك /api/ads/meta/callback، وتنزيل الإضافة /api/ext/download.
  · الإضافة: X-VP-Ext-Token صالح + مسار من مساراتها (/api/ext/* و/api/studio/<f>/ext/* وقائمة /api/scripts) ← بتمرّ باسم «الإضافة».
    التوكن لوحده ما بيفتح باقي الاستوديو.
  · موظف عليه تغيير كلمة السر (must_change) ما بيفتح إلا مسارات تغييرها.
  · الموظف الحالي بيتحط بمتغيّر السياق accounts.ACTOR قبل ما يوصل الطلب للمسار (المسارات العادية بتشتغل بخيط منسوخ السياق)،
    وبعد كل طلب كتابة نجح بيتسجّل بسجل النشاط (activity.py).
  · ACTIVE=False بيطفّي الحارس كله (الاختبارات بتطفيه افتراضياً — conftest).
ترتيب الطبقات (من برّا لجوّا): LocalGuard (Host/Origin) ← AuthGate ← المسارات.
"""

from __future__ import annotations

import json
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

import accounts
import activity

ACTIVE = True
COOKIE = "vp_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC = {("GET", "/api/auth/me"), ("POST", "/api/auth/login"), ("POST", "/api/auth/setup"), ("POST", "/api/auth/logout"),
          ("GET", "/api/ads/meta/callback"), ("GET", "/api/ext/download")}
MUST_CHANGE_OK = {("GET", "/api/auth/me"), ("POST", "/api/auth/password"), ("POST", "/api/auth/logout")}
EXT_PATHS = (re.compile(r"^/api/ext/"), re.compile(r"^/api/studio/[^/]+/ext/"))
EXT_GETS = {"/api/scripts"}
DOCS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}     # توثيق FastAPI التلقائي: بيكشف قائمة كل المسارات، فبدّو جلسة متل الـ API
MSG_LOGIN = "لازم تسجّل دخولك"
MSG_CHANGE = "لازم تغيّر كلمة السر أول شي"


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def session_token(headers: dict) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw)
        m = c.get(COOKIE)
        return m.value if m else None
    except Exception:                                          # noqa: BLE001 — كوكي تالف = بلا جلسة
        return None


def _ext_user(headers: dict, method: str, path: str):
    tok = headers.get("x-vp-ext-token")
    if not tok or not (any(rx.match(path) for rx in EXT_PATHS) or (method == "GET" and path in EXT_GETS)):
        return None
    try:
        import ext_bridge
        return accounts.EXT_USER if ext_bridge.verify(tok) else None
    except Exception:                                          # noqa: BLE001 — مخزن الأسرار غير متاح = بلا توكن
        return None


async def _json(send, status: int, body: dict, extra: list | None = None) -> None:
    raw = json.dumps(body, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(raw)).encode()), *(extra or [])]})
    await send({"type": "http.response.body", "body": raw})


class AuthGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not ACTIVE or scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        method = (scope.get("method") or "GET").upper() if scope["type"] == "http" else "GET"
        h = _headers(scope)

        if not path.startswith("/api/") and path not in DOCS:  # صفحات وملفات ثابتة
            if scope["type"] == "http" and path in ("/", "/index.html") and not self._page_allowed(scope, h):
                return await self._redirect(send)
            return await self.app(scope, receive, send)
        if (method, path) in PUBLIC:
            return await self.app(scope, receive, send)

        user = None
        try:
            user = accounts.session_user(session_token(h))
        except Exception:                                      # noqa: BLE001 — القاعدة معطّلة: رفض آمن
            user = None
        if user is None:
            user = _ext_user(h, method, path)
        if user is None:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await _json(send, 401, {"detail": MSG_LOGIN, "code": "auth_required"})
        if user.get("must_change") and (method, path) not in MUST_CHANGE_OK:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await _json(send, 403, {"detail": MSG_CHANGE, "code": "must_change_password"})

        status = {"code": 0}

        async def send2(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        tok = accounts.ACTOR.set(user)
        try:
            await self.app(scope, receive, send2)
        finally:
            accounts.ACTOR.reset(tok)
        if scope["type"] == "http" and method in UNSAFE and 0 < status["code"] < 400:
            activity.record(user, method, path, status["code"])

    @staticmethod
    def _page_allowed(scope, headers: dict) -> bool:
        if parse_qs((scope.get("query_string") or b"").decode("latin-1")).get("mock") == ["1"]:
            return True                                         # وضع التجربة: كود عام وبيانات وهمية
        try:
            return accounts.session_user(session_token(headers)) is not None
        except Exception:                                       # noqa: BLE001
            return False

    @staticmethod
    async def _redirect(send):
        await send({"type": "http.response.start", "status": 303,
                    "headers": [(b"location", b"/login.html"), (b"content-length", b"0"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})
