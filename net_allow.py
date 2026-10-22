"""
قواعد الروابط الداخلية للنماذج (صناديق التحريك، الواجهة القياسية، برامج النماذج): قائمة سماح صارمة بدل «أي رابط».

  · http بس (الصناديق بتحكي داخلياً، https وغيره ممنوع).
  · المضيف: localhost، أو IP loopback (127.x و::1)، أو اسم docker بلا نقاط (ltx، engine).
  · منفذ صريح، وبلا اسم مستخدم/كلمة سر، وبلا ? ولا #، وبلا مسار — إلا لو المسار مسموح لهالنوع (الواجهة القياسية: /v1).
  · التوكن بحقل مستقل (مش بالرابط).

motion.validate_engine_url بيفوّض إلها بنفس رسائلها. بلا شبكة: فحص نصي صافي (ما بنحلّ DNS هون).
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

DOCKER_NAME_RX = re.compile(r"[a-z][a-z0-9_-]{0,62}")
SAFE_PATH_RX = re.compile(r"(/[A-Za-z0-9._~-]{1,40}){0,3}/?")
BAD_CHARS_RX = re.compile(r"[\s\x00-\x1f\x7f\\]")


class NetAllowError(ValueError):
    """رسالة عربية جاهزة للعرض."""


def host_allowed(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback            # 127.x.x.x و ::1 بس
    except ValueError:
        pass
    return bool(DOCKER_NAME_RX.fullmatch(host))                  # اسم docker بلا نقاط (ltx، wan)


def validate(url, *, subject: str = "عنوان الصندوق", example: str = "http://127.0.0.1:8101", allow_path: bool = False) -> str:
    """العنوان المنظَّف (http://host:port أو مع مسار آمن لو allow_path) أو NetAllowError برسالة عربية."""
    if not isinstance(url, str) or not url.strip():
        raise NetAllowError(f"{subject} مطلوب (مثال: {example})")
    u = url.strip()
    if BAD_CHARS_RX.search(u):
        raise NetAllowError(f"{subject} فيه رموز غير مسموحة")
    try:
        p = urlsplit(u)
        port = p.port
    except ValueError:
        raise NetAllowError(f"{subject} غير صالح") from None
    if p.scheme != "http":
        raise NetAllowError(f"{subject} لازم يبدأ بـ http:// (الصناديق بتحكي داخلياً، https وغيره ممنوع)")
    if "@" in p.netloc or p.username or p.password:
        raise NetAllowError(f"ممنوع اسم مستخدم أو كلمة سر داخل {subject}")
    if p.query or p.fragment or "?" in u or "#" in u:
        raise NetAllowError(f"{subject} بدون ? أو # (التوكن بحقل مستقل)")
    if allow_path:
        if not SAFE_PATH_RX.fullmatch(p.path or "") or any(seg and set(seg) <= {"."} for seg in (p.path or "").split("/")):       # بلا . ولا ..
            raise NetAllowError(f"مسار {subject} غير آمن (حروف وأرقام ونقطة وشرطة بس، لحد 3 أجزاء — مثال: /v1)")
    elif p.path not in ("", "/"):
        raise NetAllowError(f"{subject} بدون مسار (مثال: {example})")
    host = (p.hostname or "").lower()
    if not host or not host_allowed(host):
        raise NetAllowError("المضيف مش مسموح: بس 127.0.0.1 أو localhost أو اسم صندوق docker بدون نقاط (مثل ltx أو wan)")
    if port is None:
        raise NetAllowError("لازم تكتب رقم المنفذ بالعنوان (مثال: :8101)")
    if not 1 <= port <= 65535:
        raise NetAllowError("رقم المنفذ خارج المعقول")
    base = f"http://{'[' + host + ']' if ':' in host else host}:{port}"
    path = (p.path or "").rstrip("/") if allow_path else ""
    return base + path


def join(base: str, path: str) -> str:
    """base (بعد validate) + مسار نداء. المسار لازم يبدأ بـ / وبلا .. ولا // ولا ? — عشان ما يهرب النداء من القاعدة."""
    if not isinstance(path, str) or not path.startswith("/") or ".." in path or "//" in path or "?" in path or "#" in path or BAD_CHARS_RX.search(path):
        raise NetAllowError("مسار النداء غير آمن")
    return base.rstrip("/") + path


def same_host(base: str, other: str) -> bool:
    """هل other (رابط ملف بنزّله من رد برنامج) على نفس مضيف ومنفذ base؟ (ما منسمح لبرنامج يحوّلنا لمكان تاني)."""
    try:
        a, b = urlsplit(base), urlsplit(other)
    except ValueError:
        return False
    return a.scheme == b.scheme == "http" and (a.hostname or "").lower() == (b.hostname or "").lower() and a.port == b.port
