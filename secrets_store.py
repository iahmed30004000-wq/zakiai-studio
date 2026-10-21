"""
مخزن الأسرار — Windows Credential Manager عبر keyring، خدمة `vidpattern`.

كل توكن ومفتاح بيعيش هون وبس: ما بيتكتب بملف نصي ولا بنسخة احتياطية ولا بتصدير.
الأسماء الثابتة: `settings.<مسار الحقل>` لمفاتيح settings.json (يديرها settings_io)،
و`crm_token` لتوكن الـ OMS، و`backup_key` لمفتاح تشفير النسخ.

بالاختبارات: use_memory_backend() بيبدّل الـ backend لنسخة بالذاكرة فما بنلمس
Credential Manager الحقيقي.
"""

from __future__ import annotations

import threading

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "vidpattern"
# حد Credential Manager: 2560 بايت للسر — منسبق بهامش أمان (UTF-16)
MAX_SECRET_CHARS = 1200

_version = 0
_version_lock = threading.Lock()


class SecretsError(Exception):
    """مخزن الأسرار غير متاح أو رفض العملية — الرسالة عربية وما فيها أي قيمة."""


def version() -> int:
    """عدّاد بيزيد مع كل كتابة/حذف — الكاش بـ settings_io بيعتمد عليه."""
    return _version


def _bump() -> None:
    global _version
    with _version_lock:
        _version += 1


def backend_name() -> str:
    kr = keyring.get_keyring()
    return f"{type(kr).__module__}.{type(kr).__name__}"


def _check_backend() -> None:
    name = type(keyring.get_keyring()).__name__.lower()
    if "fail" in name or "null" in name:
        raise SecretsError(
            "مخزن الأسرار غير متاح على هالجهاز (ما في Credential Manager شغّال). "
            "ما رح نكتب أي مفتاح بملف نصي — شغّل من حساب ويندوز عادي."
        )


def get_secret(name: str) -> str | None:
    if not name:
        return None
    _check_backend()
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError as e:
        raise SecretsError(f"تعذّرت قراءة السر '{name}' من مخزن ويندوز ({type(e).__name__})") from None


def set_secret(name: str, value: str) -> None:
    if not name:
        raise SecretsError("اسم السر فاضي")
    if value is None or value == "":
        delete_secret(name)
        return
    if len(value) > MAX_SECRET_CHARS:
        raise SecretsError(
            f"السر '{name}' أطول من الحد المسموح بمخزن ويندوز ({MAX_SECRET_CHARS} حرف)"
        )
    _check_backend()
    try:
        keyring.set_password(SERVICE, name, value)
    except KeyringError as e:
        raise SecretsError(f"تعذّر حفظ السر '{name}' بمخزن ويندوز ({type(e).__name__})") from None
    _bump()


def delete_secret(name: str) -> bool:
    """بيحذف السر. بيرجع True إذا كان موجود."""
    if not name:
        return False
    _check_backend()
    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        return False
    except KeyringError as e:
        raise SecretsError(f"تعذّر حذف السر '{name}' من مخزن ويندوز ({type(e).__name__})") from None
    _bump()
    return True


# ── طبقة الاختبار ────────────────────────────────────────────────────────


class InMemoryKeyring(KeyringBackend):
    """backend وهمي بالذاكرة — للاختبارات فقط."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


def use_memory_backend() -> tuple[InMemoryKeyring, KeyringBackend]:
    """يفعّل backend بالذاكرة. بيرجع (الجديد، القديم) عشان تقدر ترجّع."""
    previous = keyring.get_keyring()
    mem = InMemoryKeyring()
    keyring.set_keyring(mem)
    _bump()
    return mem, previous


def restore_backend(previous: KeyringBackend) -> None:
    keyring.set_keyring(previous)
    _bump()
