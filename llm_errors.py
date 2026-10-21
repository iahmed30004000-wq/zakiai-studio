"""
ترجمة أخطاء Anthropic API لرسائل مفهومة.

بدون هالطبقة، أي فشل بينتهي كجدار تتبّع بايثون بالسجل ورسالة
"انتهت العملية برمز 1" بالواجهة — ما بتقول للمستخدم شو صار ولا شو يعمل.
"""

from __future__ import annotations

import sys
from functools import wraps


def friendly(exc: Exception) -> str | None:
    """يرجع رسالة عربية واضحة، أو None إذا الاستثناء مش من نوع معروف."""
    try:
        import anthropic
    except ImportError:
        return None

    if isinstance(exc, anthropic.APIStatusError):
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = str(exc)
        low = detail.lower()

        if "credit balance" in low:
            return ("نفد رصيد الـ API.\n"
                    "    اشحن من console.anthropic.com ← Plans & Billing، وبعدين أعد التشغيل.")
        if exc.status_code == 429 or "rate limit" in low:
            return "تجاوزت حد الطلبات (rate limit) — استنى دقيقة وأعد المحاولة."
        if exc.status_code == 401:
            return "مفتاح الـ API مرفوض — تأكد من ANTHROPIC_API_KEY."
        if exc.status_code == 529 or "overloaded" in low:
            return "خوادم Anthropic مضغوطة حالياً — أعد المحاولة بعد شوي."
        return f"خطأ من الـ API ({exc.status_code}): {detail[:200]}"

    if isinstance(exc, anthropic.APIConnectionError):
        return "ما قدرت أوصل لـ Anthropic — تأكد من الاتصال بالإنترنت."

    return None


def exit_on_api_error(func):
    """يلفّ main(): يحوّل أخطاء الـ API لرسالة نظيفة بدل جدار تتبّع."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            msg = friendly(exc)
            if msg is None:
                raise
            sys.exit(f"[!] {msg}")
    return wrapper
