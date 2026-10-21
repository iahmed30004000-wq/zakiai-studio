#!/usr/bin/env python3
"""
النسخ الاحتياطي المشفّر (المرحلة 8).

المحتوى: library/ (بدون _backups وuploads وفيديوهات المصدر) + products/ + prompts/
+ settings.json بعد تجريد كل الأسرار. الأرشيف مشفّر Fernet بمفتاح عشوائي بمخزن
الأسرار (`backup_key`)، وفيه manifest: مسار → sha256 وعدد الملفات.

الاستعادة بتفك لمجلد جديد فقط — ما بتكتب فوق الشغّال أبداً.

    python backup.py run [--with-videos]
    python backup.py status
    python backup.py restore-test
    python backup.py restore الأرشيف المجلد_الجديد [--key ...]
    python backup.py export-key [--force]
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from cryptography.fernet import Fernet, InvalidToken

import config
import oplock
import secrets_store
import settings_io

KEY_SECRET_NAME = "backup_key"
MAGIC = b"VPBK1\n"
CHUNK = 4 * 1024 * 1024
FORMAT_VERSION = 1
SOURCE_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
TEXT_SCAN_EXTS = {".json", ".txt", ".md", ".srt", ".log", ".csv", ".html"}
TEXT_SCAN_MAX_BYTES = 8 * 1024 * 1024
SKIP_SUFFIXES = (".db-wal", ".db-shm", ".db-journal", ".tmp", ".part", ".lock")
NAME_RE = re.compile(r"^vidpattern_backup_(\d{8})(?:_(\d+))?\.vpbak$")


class BackupError(Exception):
    """فشل النسخ أو الاستعادة — الرسالة عربية."""


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _keep() -> int:
    return max(1, int(getattr(config, "BACKUP_KEEP", 30)))


def _alert_days() -> float:
    return float(getattr(config, "BACKUP_ALERT_DAYS", 2))


# ── الإعداد والحالة ──────────────────────────────────────────────────────


def _state_path() -> Path:
    return Path(config.LIBRARY_DIR) / "backup_state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_config() -> dict:
    raw = settings_io.load().get("BACKUP") or {}
    d = str(raw.get("dir") or "").strip()
    return {"dir": d, "include_source_videos": bool(raw.get("include_source_videos", False))}


def set_config(directory: str, include_source_videos: bool = False) -> dict:
    d = (directory or "").strip()
    if d:
        p = Path(d)
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".vidpattern_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            raise BackupError(f"المجلد ما بينكتب فيه ({e.strerror or type(e).__name__}) — تأكد من المسار والقرص") from None

    def mutate(s: dict) -> None:
        s["BACKUP"] = {"dir": d, "include_source_videos": bool(include_source_videos)}

    settings_io.update(mutate)
    return get_config()


def _backup_dir(directory: str | Path | None = None) -> Path:
    d = str(directory or get_config()["dir"] or "").strip()
    if not d:
        raise BackupError("مجلد النسخ الاحتياطي غير مضبوط — حدّده من الإعدادات (قرص خارجي أو OneDrive)")
    return Path(d)


# ── المفتاح ─────────────────────────────────────────────────────────────


def _get_key(create: bool = True) -> str | None:
    key = secrets_store.get_secret(KEY_SECRET_NAME)
    if not key and create:
        key = Fernet.generate_key().decode()
        secrets_store.set_secret(KEY_SECRET_NAME, key)
    return key


def export_key(force: bool = False) -> dict:
    """يعرض مفتاح التشفير مرة وحدة. لازم المالك يحفظه — بدونه ما بتنفتح النسخ على جهاز تاني."""
    state = _load_state()
    if state.get("key_exported_at") and not force:
        return {
            "ok": False, "already_exported": True, "exported_at": state["key_exported_at"],
            "message": "المفتاح انعرض قبل هيك ولا بينعرض مرة تانية من الواجهة. "
                       "إذا ضاع منك: python backup.py export-key --force من التيرمنال على هالجهاز.",
        }
    key = _get_key(create=True)
    state["key_exported_at"] = _now().isoformat(timespec="seconds")
    _save_state(state)
    return {
        "ok": True, "key": key,
        "message": "احفظ هالمفتاح بمكان آمن خارج هالجهاز (مدير كلمات مرور). "
                   "بدونه ما بتقدر تفك النسخ الاحتياطية على جهاز جديد.",
    }


# ── جمع الملفات ─────────────────────────────────────────────────────────


def _under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _sqlite_snapshot(src: Path, tmpdir: Path) -> Path | None:
    dest = tmpdir / f"{abs(hash(str(src)))}_{src.name}"
    try:
        s = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=20)
        d = sqlite3.connect(dest)
        try:
            s.backup(d)
        finally:
            d.close()
            s.close()
        return dest
    except sqlite3.Error:
        return None


def _list_sources(include_videos: bool, exclude_dir: Path | None, tmpdir: Path) -> list[tuple[str, Path]]:
    """[(اسم داخل الأرشيف، مسار الملف)] — settings.json بينضاف لحاله (مجرَّد)."""
    out: list[tuple[str, Path]] = []
    lib = Path(config.LIBRARY_DIR)

    def walk(root: Path, prefix: str, skip_top: set[str], is_library: bool) -> None:
        if not root.exists():
            return
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(root)
            parts = rel.parts
            if "__pycache__" in parts:
                continue
            if parts[0] in skip_top:
                continue
            if exclude_dir is not None and _under(f, exclude_dir):
                continue
            name = f.name.lower()
            if name.endswith(SKIP_SUFFIXES):
                continue
            if is_library and parts[0] == "raw" and f.suffix.lower() in SOURCE_VIDEO_EXTS and not include_videos:
                continue
            path = f
            if name.endswith(".db"):
                snap = _sqlite_snapshot(f, tmpdir)
                if snap is not None:
                    path = snap
            out.append((f"{prefix}/{rel.as_posix()}", path))

    walk(lib, "library", {"_backups", "uploads"}, True)
    walk(Path(config.PRODUCTS_DIR), "products", set(), False)
    walk(Path(config.PROMPTS_DIR), "prompts", set(), False)
    return out


def _settings_bytes() -> bytes:
    stripped = settings_io.strip_secrets(settings_io.load_raw())
    return json.dumps(stripped, ensure_ascii=False, indent=2).encode("utf-8")


def _redact_bytes(data: bytes) -> tuple[bytes, bool]:
    """خط دفاع أخير: أي شكل مفتاح بملف نصي بيتحجب قبل ما يدخل الأرشيف."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, False
    clean = settings_io.redact(text)
    if clean == text:
        return data, False
    return clean.encode("utf-8"), True


# ── الأرشيف المشفّر ──────────────────────────────────────────────────────


def _encrypt_stream(src, dst, key: str) -> None:
    f = Fernet(key.encode())
    dst.write(MAGIC)
    index = 0
    chunk = src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK)
        last = 0 if nxt else 1
        token = f.encrypt(struct.pack(">QB", index, last) + chunk)
        dst.write(struct.pack(">I", len(token)) + token)
        if last:
            break
        chunk, index = nxt, index + 1


def _decrypt_stream(src, dst, key: str) -> None:
    try:
        f = Fernet(key.encode())
    except (ValueError, TypeError):
        raise BackupError("مفتاح التشفير غير صالح") from None
    if src.read(len(MAGIC)) != MAGIC:
        raise BackupError("هاد مش أرشيف Zakiai Systems صالح")
    expected, saw_last = 0, False
    while True:
        head = src.read(4)
        if not head:
            break
        if saw_last or len(head) < 4:
            raise BackupError("الأرشيف تالف")
        (n,) = struct.unpack(">I", head)
        token = src.read(n)
        if len(token) != n:
            raise BackupError("الأرشيف مقطوع أو ناقص")
        try:
            plain = f.decrypt(token)
        except InvalidToken:
            raise BackupError("مفتاح التشفير غلط أو الأرشيف تالف") from None
        idx, last = struct.unpack(">QB", plain[:9])
        if idx != expected:
            raise BackupError("ترتيب الأرشيف مضروب")
        dst.write(plain[9:])
        expected += 1
        saw_last = bool(last)
    if not saw_last:
        raise BackupError("الأرشيف مقطوع أو ناقص")


def _next_path(directory: Path, day: str) -> Path:
    p = directory / f"vidpattern_backup_{day}.vpbak"
    n = 2
    while p.exists():
        p = directory / f"vidpattern_backup_{day}_{n}.vpbak"
        n += 1
    return p


def list_archives(directory: str | Path | None = None) -> list[Path]:
    d = _backup_dir(directory)
    if not d.exists():
        return []
    found = []
    for f in d.iterdir():
        m = NAME_RE.match(f.name)
        if m and f.is_file():
            found.append(((m.group(1), int(m.group(2) or 1)), f))
    return [f for _, f in sorted(found)]


def _apply_retention(directory: Path) -> list[str]:
    archives = list_archives(directory)
    removed = []
    for old in archives[:-_keep()] if len(archives) > _keep() else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def run(include_source_videos: bool | None = None, directory: str | Path | None = None) -> dict:
    """ينفّذ نسخة مشفّرة الآن. الفشل بينحفظ بالحالة وبيرمي BackupError."""
    at = _now()
    try:
        return _run(at, include_source_videos, directory)
    except (BackupError, secrets_store.SecretsError, OSError) as e:
        msg = settings_io.redact(str(e))
        state = _load_state()
        state["last"] = {"at": at.isoformat(timespec="seconds"), "ok": False, "path": None,
                         "files": 0, "error": msg}
        _save_state(state)
        if isinstance(e, BackupError):
            raise
        raise BackupError(f"فشل النسخ الاحتياطي: {msg}") from None


def _run(at: datetime, include_source_videos: bool | None, directory) -> dict:
    cfg = get_config()
    include_videos = cfg["include_source_videos"] if include_source_videos is None else include_source_videos
    dest_dir = _backup_dir(directory)
    dest_dir.mkdir(parents=True, exist_ok=True)
    key = _get_key(create=True)

    with oplock.file_lock(Path(config.LIBRARY_DIR) / ".backup.lock") as got:
        if not got:
            raise BackupError("في نسخة احتياطية شغّالة حالياً — استنى تخلص")

        files: dict[str, str] = {}
        redacted: list[str] = []
        skipped: list[str] = []

        with tempfile.TemporaryDirectory(prefix="vp_bk_") as tmp, tempfile.TemporaryFile() as zbuf:
            tmpdir = Path(tmp)
            sources = _list_sources(include_videos, dest_dir, tmpdir)
            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                def add_bytes(arc: str, data: bytes) -> None:
                    zf.writestr(arc, data)
                    files[arc] = hashlib.sha256(data).hexdigest()

                add_bytes("settings.json", _settings_bytes())

                for arc, path in sources:
                    try:
                        if path.suffix.lower() in TEXT_SCAN_EXTS and path.stat().st_size <= TEXT_SCAN_MAX_BYTES:
                            data, changed = _redact_bytes(path.read_bytes())
                            if changed:
                                redacted.append(arc)
                            add_bytes(arc, data)
                            continue
                        h = hashlib.sha256()
                        zi = zipfile.ZipInfo(arc, date_time=datetime.fromtimestamp(path.stat().st_mtime).timetuple()[:6])
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        with path.open("rb") as src, zf.open(zi, "w", force_zip64=True) as out:
                            while blk := src.read(1 << 20):
                                h.update(blk)
                                out.write(blk)
                        files[arc] = h.hexdigest()
                    except OSError:
                        skipped.append(arc)

                manifest = {
                    "format": FORMAT_VERSION,
                    "created_at": at.isoformat(timespec="seconds"),
                    "include_source_videos": include_videos,
                    "count": len(files),
                    "files": files,
                    "redacted": redacted,
                    "skipped": skipped,
                }
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

            zbuf.seek(0)
            final = _next_path(dest_dir, at.strftime("%Y%m%d"))
            part = final.with_name(final.name + ".part")
            try:
                with part.open("wb") as out:
                    _encrypt_stream(zbuf, out, key)
                part.replace(final)
            finally:
                part.unlink(missing_ok=True)

    removed = _apply_retention(dest_dir)
    state = _load_state()
    last = {"at": at.isoformat(timespec="seconds"), "ok": True, "path": str(final), "files": len(files)}
    state["last"] = last
    state["last_success"] = last
    _save_state(state)
    return {"ok": True, "path": str(final), "files": len(files), "bytes": final.stat().st_size,
            "at": last["at"], "include_source_videos": include_videos,
            "redacted": redacted, "skipped": skipped, "removed_old": removed}


def run_daily_if_due() -> dict:
    """نسخة واحدة لكل يوم (بتوقيت الجهاز). بدون مجلد مضبوط: بيتخطّى بدون خطأ."""
    if not get_config()["dir"]:
        return {"ok": True, "skipped": True, "reason": "مجلد النسخ الاحتياطي غير مضبوط"}
    ok = (_load_state().get("last_success") or {}).get("at")
    if ok:
        try:
            if datetime.fromisoformat(ok).astimezone().date() == _now().date():
                return {"ok": True, "skipped": True, "reason": "في نسخة لليوم"}
        except ValueError:
            pass
    try:
        return run()
    except BackupError as e:
        return {"ok": False, "error": str(e)}


# ── الاستعادة ───────────────────────────────────────────────────────────


def _safe_arc(name: str) -> bool:
    p = Path(name)
    return not (p.is_absolute() or ".." in p.parts or name.startswith(("/", "\\")) or ":" in name)


def restore(archive: str | Path, dest: str | Path, key: str | None = None) -> dict:
    """يفك الأرشيف لمجلد جديد (أو فاضي) ويتحقق من sha256 لكل ملف. ما بيكتب فوق شي."""
    archive, dest = Path(archive), Path(dest)
    if not archive.is_file():
        raise BackupError("ملف الأرشيف مش موجود")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise BackupError("مجلد الاستعادة لازم يكون جديد أو فاضي — ما بنكتب فوق مجلد فيه ملفات")
    for live in (Path(config.LIBRARY_DIR), Path(config.PRODUCTS_DIR), Path(config.PROMPTS_DIR)):
        if dest.resolve() == live.resolve() or _under(dest, live):
            raise BackupError("ما بنستعيد جوّا مجلدات النظام الشغّال — اختار مجلد جديد برّا")
    key = key or _get_key(create=False)
    if not key:
        raise BackupError("ما في مفتاح تشفير — أعطِ المفتاح المحفوظ عندك (--key)")

    with tempfile.TemporaryFile() as zbuf:
        with archive.open("rb") as src:
            _decrypt_stream(src, zbuf, key)
        zbuf.seek(0)
        try:
            zf = zipfile.ZipFile(zbuf)
        except zipfile.BadZipFile:
            raise BackupError("الأرشيف تالف") from None
        with zf:
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (KeyError, json.JSONDecodeError):
                raise BackupError("الأرشيف ما فيه manifest صالح") from None
            expected: dict[str, str] = manifest.get("files") or {}
            dest.mkdir(parents=True, exist_ok=True)
            restored, mismatched, missing = 0, [], []
            names = set(zf.namelist())
            for arc, want in expected.items():
                if arc not in names:
                    missing.append(arc)
                    continue
                if not _safe_arc(arc):
                    mismatched.append(arc)
                    continue
                target = dest / arc
                target.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with zf.open(arc) as src, target.open("wb") as out:
                    while blk := src.read(1 << 20):
                        h.update(blk)
                        out.write(blk)
                restored += 1
                if h.hexdigest() != want:
                    mismatched.append(arc)
    ok = not mismatched and not missing and restored == len(expected)
    return {"ok": ok, "dest": str(dest), "files_manifest": len(expected), "files_restored": restored,
            "mismatched": mismatched, "missing": missing, "created_at": manifest.get("created_at")}


def restore_test(directory: str | Path | None = None) -> dict:
    """نسخة حقيقية ← استعادة بمجلد مؤقت جديد ← مقارنة العدد وsha256. بيتنظّف بعدها."""
    result = run(directory=directory)
    tmp = Path(tempfile.mkdtemp(prefix="vp_restore_"))
    dest = tmp / "restored"
    try:
        r = restore(result["path"], dest)
        actual = sum(1 for f in dest.rglob("*") if f.is_file())
        match = bool(r["ok"]) and actual == result["files"] == r["files_restored"]
        return {"ok": match, "files_backup": result["files"], "files_restored": actual,
                "match": match, "path": result["path"]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── الحالة ──────────────────────────────────────────────────────────────


def status() -> dict:
    state = _load_state()
    cfg = get_config()
    last = state.get("last") or {"at": None, "ok": None, "path": None, "files": 0}
    ok_at = (state.get("last_success") or {}).get("at")
    days_since = None
    if ok_at:
        try:
            days_since = round((_now() - datetime.fromisoformat(ok_at)).total_seconds() / 86400, 2)
        except ValueError:
            days_since = None
    never = days_since is None
    alert = never or days_since > _alert_days()
    reasons = []
    if not cfg["dir"]:
        reasons.append("مجلد النسخ الاحتياطي غير مضبوط")
    if never:
        reasons.append("ما في ولا نسخة احتياطية ناجحة")
    elif days_since > _alert_days():
        reasons.append(f"آخر نسخة ناجحة من {days_since:g} يوم")
    return {
        "last": {k: last.get(k) for k in ("at", "ok", "path", "files")} | (
            {"error": last["error"]} if last.get("error") else {}),
        "days_since": days_since,
        "alert": alert,
        "alert_reasons": reasons,
        "configured": bool(cfg["dir"]),
        "dir": cfg["dir"],
        "include_source_videos": cfg["include_source_videos"],
        "key_exported": bool(state.get("key_exported_at")),
        "keep": _keep(),
    }


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="النسخ الاحتياطي المشفّر لـ Zakiai Systems")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="نسخة الآن")
    r.add_argument("--with-videos", action="store_true", help="ضمّن فيديوهات المصدر (كبيرة)")
    sub.add_parser("status")
    sub.add_parser("restore-test")
    rs = sub.add_parser("restore")
    rs.add_argument("archive")
    rs.add_argument("dest")
    rs.add_argument("--key")
    ek = sub.add_parser("export-key")
    ek.add_argument("--force", action="store_true", help="اعرضه حتى لو انعرض قبل")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "run":
            out = run(include_source_videos=True if a.with_videos else None)
        elif a.cmd == "status":
            out = status()
        elif a.cmd == "restore-test":
            out = restore_test()
        elif a.cmd == "restore":
            out = restore(a.archive, a.dest, a.key)
        else:
            out = export_key(force=a.force)
    except BackupError as e:
        print(f"[!] {e}")
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) is not False else 1


if __name__ == "__main__":
    sys.exit(_main())
