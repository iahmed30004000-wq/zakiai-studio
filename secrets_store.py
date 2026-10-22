"""
مخزن الأسرار — Windows Credential Manager عبر keyring، خدمة `vidpattern`.

كل توكن ومفتاح بيعيش هون وبس: ما بيتكتب بملف نصي ولا بنسخة احتياطية ولا بتصدير.
الأسماء الثابتة: `settings.<مسار الحقل>` لمفاتيح settings.json (يديرها settings_io)،
و`crm_token` لتوكن الـ OMS، و`backup_key` لمفتاح تشفير النسخ، و`modellib.<ml_id>.token` لتوكن سيرفر نموذج مربوط.

على السيرفر (لينكس/docker) ما في Credential Manager ولا keyring بالنظام: لو المتغيّر VP_SECRETS_KEY مضبوط
(بملف .env، الاستوديو ما بيشوفه ولا بيطبعه) بنركّب خزنة مشفّرة بملف `secrets/vault.enc` (Fernet) بدل الـ backend الفاشل.
بدون المفتاح الوضع القديم: رفض صريح — ما رح نكتب أي سر بملف نصي.

بالاختبارات: use_memory_backend() بيبدّل الـ backend لنسخة بالذاكرة فما بنلمس
Credential Manager الحقيقي.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "vidpattern"
# حد Credential Manager: 2560 بايت للسر — منسبق بهامش أمان (UTF-16)
MAX_SECRET_CHARS = 1200

VAULT_KEY_ENV = "VP_SECRETS_KEY"          # عبارة سر الخزنة (بيحطها المالك بملف .env — ما بتنكتب بأي ملف تاني)
VAULT_DIR_ENV = "VP_SECRETS_DIR"          # مجلد الخزنة (الافتراضي: secrets/ جنب الكود، برّا library/ فما بتدخل النسخ الاحتياطي)
MIN_VAULT_KEY_CHARS = 16
_VAULT_ROUNDS = 200_000
_VAULT_ROUNDS_RANGE = (100_000, 2_000_000)  # ملف مزوّر ما بيقدر يعلّق الاستوديو بعدد دورات خيالي
_VAULT_MAX_BYTES = 4 * 1024 * 1024

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


def vault_path() -> Path:
    base = os.environ.get(VAULT_DIR_ENV, "").strip()
    return (Path(base) if base else Path(__file__).resolve().parent / "secrets") / "vault.enc"


class EncryptedFileKeyring(KeyringBackend):
    """خزنة مشفّرة بملف — للسيرفر بس، لما ما في keyring بالنظام. ما بتنختار لحالها: بتحتاج مسار وعبارة سر بالبناء،
    فاكتشاف keyring التلقائي (اللي بينادي المنشئ بلا معاملات) بيتجاهلها، وبتتركّب فقط بـ _activate_vault().

    الملف: JSON فيه نسخة الصيغة والملح وعدد دورات الاشتقاق (PBKDF2-SHA256) والمحتوى مشفّر Fernet.
    القراءة والكتابة تحت قفل، والكتابة ذرّية (ملف مؤقت ثم استبدال). ملف ما قدرنا نفكّه (مفتاح غلط/تالف) = SecretsError
    وما بنكتب فوقه أبداً. الاستوديو العملية الوحيدة اللي بتكتب الأسرار، فما في قفل بين العمليات (القراءة آمنة بسبب الاستبدال الذرّي).
    """

    priority = 0.5

    def __init__(self, path, passphrase: str) -> None:
        super().__init__()
        self._path = Path(path)
        self._pass = passphrase.encode("utf-8")
        self._lock = threading.RLock()
        self._ciphers: dict[tuple[bytes, int], object] = {}
        self._salt: bytes | None = None
        self._rounds = _VAULT_ROUNDS

    def _cipher(self, salt: bytes, rounds: int):
        got = self._ciphers.get((salt, rounds))
        if got is None:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            raw = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=rounds).derive(self._pass)
            got = self._ciphers[(salt, rounds)] = Fernet(base64.urlsafe_b64encode(raw))
        return got

    def _load(self) -> dict:
        from cryptography.fernet import InvalidToken
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError:
            raise SecretsError("تعذّرت قراءة ملف الخزنة (صلاحيات الملف؟)") from None
        if len(raw) > _VAULT_MAX_BYTES:
            raise SecretsError("ملف الخزنة أكبر من المعقول — مش ملفنا؟ ما رح نكتب فوقه")
        try:
            head = json.loads(raw.decode("utf-8"))
            if head["v"] != 1:
                raise SecretsError("ملف الخزنة بصيغة أحدث من اللي بنفهمها — حدّث الاستوديو")
            salt = base64.b64decode(head["salt"], validate=True)
            rounds = int(head["rounds"])
            token = head["data"].encode("ascii")
        except SecretsError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SecretsError("ملف الخزنة تالف (صيغته مش مفهومة) — ما رح نكتب فوقه") from None
        if not _VAULT_ROUNDS_RANGE[0] <= rounds <= _VAULT_ROUNDS_RANGE[1] or not 8 <= len(salt) <= 64:
            raise SecretsError("ملف الخزنة تالف (إعدادات التشفير غير معقولة) — ما رح نكتب فوقه")
        try:
            data = json.loads(self._cipher(salt, rounds).decrypt(token).decode("utf-8"))
        except InvalidToken:
            raise SecretsError(f"مفتاح الخزنة ({VAULT_KEY_ENV}) غلط أو الملف تالف — ما رح نكتب فوقه") from None
        except ValueError:
            raise SecretsError("محتوى الخزنة تالف — ما رح نكتب فوقه") from None
        if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
            raise SecretsError("محتوى الخزنة تالف — ما رح نكتب فوقه")
        self._salt, self._rounds = salt, rounds
        return data

    def _save(self, data: dict) -> None:
        salt = self._salt or os.urandom(16)
        token = self._cipher(salt, self._rounds).encrypt(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
        body = json.dumps({"v": 1, "kdf": "pbkdf2-sha256", "rounds": self._rounds, "salt": base64.b64encode(salt).decode("ascii"),
                           "data": token}).encode("utf-8")
        tmp = self._path.parent / f".{self._path.name}.{os.getpid()}.tmp"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise SecretsError("تعذّرت كتابة ملف الخزنة (المجلد مقفول أو ممتلي؟)") from None
        self._salt = salt

    def get_password(self, service, username):
        with self._lock:
            return self._load().get(service, {}).get(username)

    def set_password(self, service, username, password):
        with self._lock:
            data = self._load()
            data.setdefault(service, {})[username] = password
            self._save(data)

    def delete_password(self, service, username):
        with self._lock:
            data = self._load()
            bucket = data.get(service, {})
            if username not in bucket:
                raise PasswordDeleteError("not found")
            del bucket[username]
            if not bucket:
                data.pop(service, None)
            self._save(data)


def _unavailable(kr) -> bool:
    """backend الفشل/الفراغ بمكتبة keyring اسم صنفه `Keyring` بالحالتين — بنميّزه من مسار وحدته (keyring.backends.fail / .null)."""
    t = type(kr)
    ident = f"{t.__module__}.{t.__name__}".lower()
    return "fail" in ident or "null" in ident


def _activate_vault() -> bool:
    """جهاز بلا keyring بالنظام + VP_SECRETS_KEY مضبوط → نركّب الخزنة المشفّرة. غير هيك False (الرفض القديم)."""
    phrase = os.environ.get(VAULT_KEY_ENV, "")
    if not phrase.strip():
        return False
    if len(phrase) < MIN_VAULT_KEY_CHARS:
        raise SecretsError(f"مفتاح الخزنة ({VAULT_KEY_ENV}) قصير — لازم {MIN_VAULT_KEY_CHARS} حرف على الأقل")
    keyring.set_keyring(EncryptedFileKeyring(vault_path(), phrase))
    _bump()
    return True


def _check_backend() -> None:
    if not _unavailable(keyring.get_keyring()) or _activate_vault():
        return
    raise SecretsError(
        "مخزن الأسرار غير متاح على هالجهاز (ما في Credential Manager شغّال). "
        "ما رح نكتب أي مفتاح بملف نصي — شغّل من حساب ويندوز عادي، أو على السيرفر حط "
        f"{VAULT_KEY_ENV} (عبارة سر من {MIN_VAULT_KEY_CHARS} حرف على الأقل) بملف .env."
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
