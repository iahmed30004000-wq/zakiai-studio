"""
قراءة وكتابة settings.json مع مخزن الأسرار.

load(): بيقرأ الملف وبيحلّ مراجع الأسرار ("secret:<اسم>") لقيمها.
save(): أي حقل اسمه api_key / token / secret / password (بأي عمق) بينتقل لمخزن
        الأسرار، وبالملف بيتكتب مرجع بس. الترتيب: المخزن أولاً ثم الملف — فلو فشل
        المخزن ما بيتكتب شي (ما في تراجع لنص خام أبداً).

كل وحدة بتقرأ الإعدادات لازم تمرّ من load()، وكل كتابة من save()/update().
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import secrets_store

REF_PREFIX = "secret:"
NAME_PREFIX = "settings."

# api_key, ANTHROPIC_API_KEY, crm_token, client_secret… لكن مش MAX_OUTPUT_TOKENS
_SECRET_KEY_RE = re.compile(r"(^|_)(api_?key|token|secret|password|passwd)$", re.IGNORECASE)
_KEY_LIKE_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{12,}")

_lock = threading.RLock()
_CACHE_TTL_SEC = 30   # عمليات تانية (الوكيل/الترحيل) ممكن تغيّر المخزن
_cache: dict[str, Any] = {"sig": None, "data": None, "at": 0.0}
_known_values: set[str] = set()
_warned: set[str] = set()


def is_secret_field(key: Any) -> bool:
    return isinstance(key, str) and bool(_SECRET_KEY_RE.search(key))


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(REF_PREFIX)


def secret_name(path: tuple) -> str:
    return NAME_PREFIX + ".".join(str(p) for p in path)


def _path(path: str | Path | None) -> Path:
    import config   # متأخر: config نفسه بيستورد settings_io بآخره
    return Path(path) if path else Path(config.SETTINGS_PATH)


def _read_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_raw(path: str | Path | None = None) -> dict:
    """محتوى الملف كما هو (بالمراجع، بدون حلّها)."""
    return _read_raw(_path(path))


def _warn(msg: str) -> None:
    if msg not in _warned:
        _warned.add(msg)
        print(f"[!] {msg}", file=sys.stderr)


def _map(obj: Any, path: tuple, fn: Callable[[tuple, str], Any]) -> Any:
    """يبني نسخة جديدة؛ fn بيستدعى لكل قيمة نصية تحت حقل سرّي."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if is_secret_field(k) and isinstance(v, str):
                out[k] = fn(path + (k,), v)
            else:
                out[k] = _map(v, path + (k,), fn)
        return out
    if isinstance(obj, list):
        return [_map(v, path + (i,), fn) for i, v in enumerate(obj)]
    return obj


def _collect_refs(obj: Any) -> set[str]:
    found: set[str] = set()

    def grab(_p, v):
        if is_ref(v):
            found.add(v[len(REF_PREFIX):])
        return v

    _map(obj, (), grab)
    return found


def secret_fields(data: dict) -> list[tuple]:
    """مسارات كل الحقول السرّية غير الفاضية (بدون قيمها) — للتقارير والترحيل."""
    paths: list[tuple] = []

    def grab(p, v):
        if v.strip():
            paths.append(p)
        return v

    _map(data, (), grab)
    return paths


# ── القراءة ──────────────────────────────────────────────────────────────


def _resolve(path: tuple, value: str) -> str:
    if not is_ref(value):
        return value
    name = value[len(REF_PREFIX):]
    try:
        secret = secrets_store.get_secret(name)
    except secrets_store.SecretsError as e:
        _warn(str(e))
        return ""
    if not secret:
        _warn(f"السر '{name}' مش موجود بمخزن ويندوز — أعد إدخال المفتاح من الإعدادات")
        return ""
    _known_values.add(secret)
    return secret


def resolve_ref(value: str) -> str:
    """يحلّ قيمة مفردة لو كانت مرجع (للمفاتيح اللي بتجي من متغيّرات البيئة)."""
    return _resolve((), value) if is_ref(value) else value


def load(path: str | Path | None = None) -> dict:
    p = _path(path)
    try:
        st = p.stat()
        sig = (str(p), st.st_mtime_ns, st.st_size, secrets_store.version())
    except OSError:
        return {}
    with _lock:
        if _cache["sig"] == sig and time.monotonic() - _cache["at"] < _CACHE_TTL_SEC:
            return copy.deepcopy(_cache["data"])
        data = _map(_read_raw(p), (), _resolve)
        _cache["sig"], _cache["data"], _cache["at"] = sig, data, time.monotonic()
        return copy.deepcopy(data)


# ── الكتابة ──────────────────────────────────────────────────────────────


def _atomic_write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    last: Exception | None = None
    for _ in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError as e:       # قارئ تاني فاتح الملف لحظياً
            last = e
            threading.Event().wait(0.1)
    raise last  # type: ignore[misc]


def save(data: dict, path: str | Path | None = None) -> dict:
    """
    يحفظ الإعدادات. بيرجع نسخة الملف المكتوبة (بالمراجع) — مفيدة للتحقق.
    الحقول السرّية الفاضية بتضل فاضية؛ اللي مرجعها موجود بيضل مرجع.
    """
    p = _path(path)
    with _lock:
        old_refs = _collect_refs(_read_raw(p))
        new_refs: set[str] = set()

        def to_ref(fpath: tuple, value: str) -> str:
            if is_ref(value):
                new_refs.add(value[len(REF_PREFIX):])
                return value
            if not value.strip():
                return value
            name = secret_name(fpath)
            if secrets_store.get_secret(name) != value:
                secrets_store.set_secret(name, value)
            _known_values.add(value)
            new_refs.add(name)
            return REF_PREFIX + name

        out = _map(data, (), to_ref)
        _atomic_write(p, out)

        # أسرار انشالت من الإعدادات (اتصال انحذف، مفتاح انمسح) — ننضّف المخزن
        for name in old_refs - new_refs:
            if name.startswith(NAME_PREFIX):
                try:
                    secrets_store.delete_secret(name)
                except secrets_store.SecretsError:
                    pass
        _cache["sig"] = None
        return out


def update(mutator: Callable[[dict], Any], path: str | Path | None = None) -> dict:
    """قراءة-تعديل-كتابة تحت قفل — على النسخة الخام فالمراجع ما بتنلمس."""
    p = _path(path)
    with _lock:
        raw = _read_raw(p)
        res = mutator(raw)
        save(res if isinstance(res, dict) else raw, p)
        return raw


# ── التقنيع والتنظيف ────────────────────────────────────────────────────


def mask(value: str) -> str:
    if not value:
        return ""
    return f"{value[:6]}…{value[-4:]}" if len(value) > 18 else "مضبوط"


def masked_view(data: dict) -> dict:
    """نسخة آمنة للعرض: كل سر مقنّع (أو محذوف لو مرجع)."""
    return _map(data, (), lambda _p, v: "مضبوط" if is_ref(v) else mask(v))


def strip_secrets(data: dict) -> dict:
    """يشيل كل حقل سرّي بالكامل (للنسخ الاحتياطي والتصدير) وأي قيمة مرجع."""

    def clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()
                    if not (is_secret_field(k) and isinstance(v, str))}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        if is_ref(obj):
            return None
        return obj

    return clean(data)


def redact(text: str) -> str:
    """للرسائل والسجلات: يخفي أي شكل مفتاح معروف وأي قيمة سر حلّيناها."""
    if not text:
        return text
    text = _KEY_LIKE_RE.sub("[محجوب]", text)
    for v in sorted(_known_values, key=len, reverse=True):
        if len(v) >= 8 and v in text:
            text = text.replace(v, "[محجوب]")
    return text
