#!/usr/bin/env python3
"""
ترحيل مفاتيح settings.json لمخزن أسرار ويندوز (Credential Manager).

    python migrate_secrets.py --dry-run             # يعرض شو رح ينرحّل بدون ما يكتب
    python migrate_secrets.py                       # يرحّل فعلاً
    python migrate_secrets.py --rollback --yes      # يرجّع المفاتيح لـ settings.json كنص خام
    python migrate_secrets.py --settings مسار.json  # على ملف تاني (للتجربة على نسخة)

بلا نسخة احتياطية فيها مفاتيح: الترحيل بيضل عكسياً لأن المفاتيح موجودة بالمخزن،
و--rollback بيكتبها صراحةً لـ settings.json بأمرك.

ترتيب الأمان: المفاتيح بتنكتب للمخزن وبتنقرا وبتتقارن أولاً، وبعدين بس بيتبدّل
الملف. لو أي خطوة فشلت الملف الأصلي بيضل كما هو.
"""

import argparse
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config
import secrets_store
import settings_io

RAW_KEY_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}")


def _plaintext_fields(obj, path=()):
    """[(مسار، قيمة)] لكل حقل سرّي نصه خام (مش مرجع وغير فاضي)."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if settings_io.is_secret_field(k) and isinstance(v, str):
                if v.strip() and not settings_io.is_ref(v):
                    found.append((path + (k,), v))
            else:
                found += _plaintext_fields(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _plaintext_fields(v, path + (i,))
    return found


def _fmt(path) -> str:
    return ".".join(str(p) for p in path)


def migrate(path: Path, dry_run: bool) -> int:
    raw = settings_io.load_raw(path)
    if not raw and not path.exists():
        print(f"[!] الملف مش موجود: {path}")
        return 1
    fields = _plaintext_fields(raw)
    if not fields:
        print("[✓] ما في مفاتيح خام بالملف — ما في شي للترحيل.")
        return 0

    print(f"لقيت {len(fields)} مفتاح خام:")
    for p, v in fields:
        print(f"   - {_fmt(p)}  ({len(v)} حرف)")
    if dry_run:
        print("\n[dry-run] ما انكتب شي. شيل --dry-run لتنفيذ الترحيل.")
        return 0

    try:
        for p, v in fields:
            name = settings_io.secret_name(p)
            secrets_store.set_secret(name, v)
            if secrets_store.get_secret(name) != v:
                print(f"[!] فشل التحقق من قراءة السر '{name}' — أوقفنا الترحيل، الملف ما تغيّر.")
                return 1
    except secrets_store.SecretsError as e:
        print(f"[!] {e}\n    الملف ما تغيّر.")
        return 1

    settings_io.save(raw, path)

    text = path.read_text(encoding="utf-8")
    leaked = RAW_KEY_RE.findall(text) or [v for _, v in fields if v in text]
    if leaked:
        print("[!] لسا في مفتاح خام بالملف بعد الترحيل — راجع يدوياً.")
        return 1
    resolved = settings_io.load(path)
    for p, v in fields:
        cur = resolved
        for part in p:
            cur = cur[part]
        if cur != v:
            print(f"[!] بعد الترحيل قراءة '{_fmt(p)}' ما طابقت الأصل.")
            return 1

    print(f"\n[✓] انرحّل {len(fields)} مفتاح لمخزن ويندوز ({secrets_store.backend_name()}).")
    print("    settings.json صار فيه مراجع (secret:...) بدل المفاتيح، والنظام بيقراها عبر settings_io.")
    print("    لو بدك ترجّعها: python migrate_secrets.py --rollback --yes")
    return 0


def rollback(path: Path, yes: bool) -> int:
    raw = settings_io.load_raw(path)
    refs = []

    def walk(o, p=()):
        if isinstance(o, dict):
            for k, v in o.items():
                if settings_io.is_secret_field(k) and settings_io.is_ref(v):
                    refs.append(p + (k,))
                else:
                    walk(v, p + (k,))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, p + (i,))

    walk(raw)
    if not refs:
        print("[✓] ما في مراجع أسرار بالملف — ما في شي لإرجاعه.")
        return 0
    print(f"رح تنكتب {len(refs)} مفتاح كنص خام بـ {path} — هيك بتتحوّل لملف فيه أسرار.")
    if not yes:
        print("أكّد بإضافة --yes إذا هيك بدك.")
        return 1

    resolved = settings_io.load(path)
    missing = []
    for p in refs:
        cur = resolved
        for part in p:
            cur = cur[part]
        if not cur:
            missing.append(_fmt(p))
    if missing:
        print("[!] أسرار مفقودة من المخزن (ما رح ترجع): " + ", ".join(missing))
    import json
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"[✓] انكتبت المفاتيح لـ settings.json. (النسخ بمخزن ويندوز بعدها موجودة، وأي حفظ جاي بيرجّعها للمخزن.)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ترحيل أسرار settings.json لمخزن ويندوز")
    ap.add_argument("--settings", help="مسار settings.json (افتراضي: الحقيقي)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--yes", action="store_true", help="تأكيد الإرجاع")
    a = ap.parse_args(argv)
    path = Path(a.settings) if a.settings else Path(config.SETTINGS_PATH)
    if a.rollback:
        return rollback(path, a.yes)
    return migrate(path, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
