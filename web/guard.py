"""
حارس الاستوديو المحلي (ASGI): بيسكّر طريقين بتخلّي موقع غريب أو نفق يتحكم بالاستوديو.

1. فحص عنوان الطلب (Host): مسموح فقط localhost و127.0.0.1 و[::1] و testserver، وما نضيفه بالمتغيّر VP_ALLOWED_HOSTS
   (أسماء أو عناوين مفصولة بفاصلة؛ run_web.py --lan بيضيف عنوان الجهاز لحاله). النفق (ngrok…) بيجيب Host غريب ← مرفوض،
   وهاد كمان بيمنع «DNS rebinding» (موقع خبيث بيوجّه اسمه لـ 127.0.0.1 ويقرا بيانات الاستوديو).
2. فحص مصدر الطلب (Origin) للطلبات اللي بتغيّر شي (POST/PUT/PATCH/DELETE):
   · مسموح: نفس مصدر الصفحة (Origin = Host الطلب)، أو chrome-extension:// (إضافتنا؛ مساراتها بتوكن أصلاً)،
     أو مصدر مكتوب بالمتغيّر VP_ALLOWED_ORIGINS (للمحوّلات العكسية).
   · أي مصدر تاني، أو Origin: null، أو Sec-Fetch-Site: cross-site بلا Origin ← 403.
   · بلا Origin وبلا Sec-Fetch-Site (curl، الاختبارات، سكربتات الجهاز) ← مسموح.
مثال: موقع غريب فيه فورم مخفي بيعمل POST على /api/ahat/ah_001/revoke ← المتصفح بيبعت Origin بتاع الموقع الغريب ← 403.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

BASE_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
MSG_HOST = "عنوان الطلب مش مسموح — الاستوديو بيشتغل على localhost بس (لا تستعمل نفق ولا اسم تاني)"
MSG_ORIGIN = "مصدر الطلب مش مسموح — الطلب لازم يجي من صفحات الاستوديو نفسه"


def _env_list(name: str) -> set[str]:
    return {x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()}


def allowed_hosts() -> set[str]:
    return BASE_HOSTS | _env_list("VP_ALLOWED_HOSTS")


def host_of(value: str) -> str:
    """اسم المضيف بدون المنفذ (يدعم [::1])، أو فاضي لو الصيغة غريبة."""
    try:
        return (urlsplit("//" + value.strip()).hostname or "").lower()
    except ValueError:
        return ""


def host_ok(host_header: str) -> bool:
    return host_of(host_header) in allowed_hosts()


def origin_ok(origin: str, host_header: str) -> bool:
    o = origin.strip().lower()
    if o.startswith("chrome-extension://"):
        return True
    if o in _env_list("VP_ALLOWED_ORIGINS"):
        return True
    try:
        parts = urlsplit(o)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False                                          # "null" وغيره
    return parts.netloc == host_header.strip().lower()        # نفس المصدر بالضبط (اسم + منفذ)


class LocalGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        bad = None
        if not host_ok(h.get("host", "")):
            bad = (400, MSG_HOST)
        elif scope["type"] == "http" and scope.get("method") in UNSAFE:
            origin = h.get("origin")
            if origin is not None:
                if not origin_ok(origin, h.get("host", "")):
                    bad = (403, MSG_ORIGIN)
            elif h.get("sec-fetch-site", "").lower() == "cross-site":
                bad = (403, MSG_ORIGIN)
        if bad is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        body = json.dumps({"detail": bad[1]}, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": bad[0],
                    "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
