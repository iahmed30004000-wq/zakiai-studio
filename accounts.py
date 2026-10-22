#!/usr/bin/env python3
"""
حسابات الموظفين — بلا صلاحيات: كلكم متساويين، والغرض إنو كل واحد يدخل بحسابه وإنو نعرف مين عمل شو (activity.py).

  · أول مرة (ما في أي حساب) الصفحة بتفتح شاشة «أنشئ أول حساب»، وبس من نفس الجهاز. بعدها أي موظف بينضاف من الإعدادات ← «الموظفين»
    بكلمة سر مؤقتة بيغيّرها بأول دخول.
  · كلمات السر argon2id (ما بتنحفظ ولا بتنطبع ولا بتنكتب بأي سجل). جلسة الدخول توكن عشوائي، بالقاعدة منحفظ بصمته sha256 بس،
    وبالمتصفح كوكي HttpOnly+SameSite=Lax لمدة 30 يوم بتتجدّد مع الاستعمال.
  · قواعد الأمان: ما حدا بيعطّل حسابه ولا بيصفّر كلمة سره بنفسه، وآخر حساب فعّال ما بينعطّل. التعطيل أو التصفير بيطلّع الموظف من كل جلساته؛
    والتصفير بيفرض عليه كلمة سر جديدة بأول دخول. أي موظف بيقدر يصفّر حساب غيره (بلا صلاحيات متل ما طلب المالك) وكله بيظهر بـ«النشاط».
  · محاولات دخول غلط كتيرة (5 خلال 10 دقايق لنفس الاسم) بتقفل الاسم 10 دقايق.
  · نسيت كلمة السر ولا في حدا يصفّرها؟ من نفس الجهاز:  python accounts.py reset <اسم_المستخدم>   (بيسألك كلمة السر الجديدة مخفية)
  · ACTOR: «مين عم يشتغل هلّق» بمتغيّر سياق (contextvar) بيحطّه حارس الدخول (web/auth_gate.py) وبتقراه who() — بلا تعديل 40 موقع.
    المهام بالخلفية (subprocess) بتاخد VP_ACTOR من البيئة.
"""

from __future__ import annotations

import contextvars
import hashlib
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config

SESSION_DAYS = 30
SLIDE_EVERY_SEC = 300                       # بنجدّد الجلسة بالقاعدة كل 5 دقايق بالكتير (مش كل طلب)
MIN_PASSWORD = 8
MAX_PASSWORD = 200
LOGIN_FAILS = 5
LOGIN_WINDOW_SEC = 600
LOCK_SEC = 600
REMOTION_FREE_SEATS = 3                     # رخصة Remotion مجانية لـ 3 أشخاص أو أقل (المونتاج المتقدّم)
USERNAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
EXT_USER = {"id": 0, "username": "extension", "display_name": "الإضافة", "must_change": 0, "active": 1}

ACTOR: contextvars.ContextVar = contextvars.ContextVar("vp_actor", default=None)
_lock = threading.Lock()
_fails: dict[str, list[float]] = {}
_last_slide: dict[str, float] = {}
_hasher = None


class AccountError(Exception):
    """رسالة عربية جاهزة للعرض. code: setup_done · bad_input · exists · rules · locked · bad_login · disabled · not_found"""

    def __init__(self, msg: str, code: str = "bad_input", status: int = 400):
        super().__init__(msg)
        self.code, self.status = code, status


# ── قاعدة البيانات ───────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    must_change INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by TEXT,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ua TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
"""


def db_path() -> Path:
    return Path(config.LIBRARY_DIR) / "accounts.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(_SCHEMA)
    return con


@contextmanager
def _db():
    """اتصال بقاعدة الحسابات: commit لو تمّ، rollback لو فشل، وبيتسكّر دايماً (ما بنسرّب اتصالات)."""
    con = _connect()
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ph():
    global _hasher
    if _hasher is None:
        try:
            from argon2 import PasswordHasher
        except ImportError as e:                                  # noqa: BLE001
            raise AccountError("مكتبة تشفير كلمات السر ناقصة — pip install argon2-cffi", "bad_input", 500) from e
        _hasher = PasswordHasher()
    return _hasher


# ── التحقق من المدخلات ───────────────────────────────────────────────────
def check_username(u) -> str:
    u = str(u or "").strip().lower()
    if not USERNAME_RX.match(u):
        raise AccountError("اسم المستخدم: 3–32 حرف إنجليزي صغير أو رقم أو . _ - (يبدأ بحرف أو رقم)")
    return u


def check_display(n) -> str:
    n = re.sub(r"\s+", " ", str(n or "")).strip()
    if not 2 <= len(n) <= 40:
        raise AccountError("الاسم الظاهر (2–40 حرف) مطلوب")
    return n


def check_password(p, username: str = "") -> str:
    p = str(p or "")
    if len(p) < MIN_PASSWORD:
        raise AccountError(f"كلمة السر لازم تكون {MIN_PASSWORD} أحرف على الأقل")
    if len(p) > MAX_PASSWORD:
        raise AccountError("كلمة السر طويلة كتير")
    if username and p.lower() == username.lower():
        raise AccountError("كلمة السر ما بتكون نفس اسم المستخدم")
    return p


# ── المستخدمين ───────────────────────────────────────────────────────────
def public(row) -> dict:
    """الحقول الآمنة للعرض (بلا بصمة كلمة السر أبداً)."""
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"], "active": bool(row["active"]),
            "must_change": bool(row["must_change"]), "created_at": row["created_at"], "created_by": row["created_by"],
            "last_login": row["last_login"]}


def count_users() -> int:
    with _db() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def needs_setup() -> bool:
    return count_users() == 0


def active_count() -> int:
    with _db() as con:
        return con.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]


def seats_note() -> str:
    """تذكير رخصة Remotion لما الموظفين الفعّالين يتجاوزوا 3 (بس تذكير — ما في منع)."""
    n = active_count()
    if n > REMOTION_FREE_SEATS:
        return (f"عندك {n} موظفين فعّالين. رخصة Remotion (المونتاج المتقدّم) مجانية لحد {REMOTION_FREE_SEATS} أشخاص؛ "
                "من الرابع بيلزمك رخصة شركة منهم. ما بنمنعك — بس نذكّرك.")
    return ""


def _insert(con, username: str, display: str, password: str, must_change: int, by: str) -> int:
    try:
        cur = con.execute("INSERT INTO users(username, display_name, pw_hash, must_change, active, created_at, created_by) VALUES(?,?,?,?,1,?,?)",
                          (username, display, _ph().hash(password), must_change, _iso(_now()), by))
    except sqlite3.IntegrityError:
        raise AccountError("اسم المستخدم مستعمل — اختار غيره", "exists", 409) from None
    return cur.lastrowid


def create_first(display_name, username, password) -> dict:
    """الحساب الأول (المالك). بس لو ما في أي حساب — غير هيك بيرفض."""
    u, d = check_username(username), check_display(display_name)
    p = check_password(password, u)
    with _lock, _db() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise AccountError("الحساب الأول انعمل أصلاً — سجّل دخولك", "setup_done", 409)
        uid = _insert(con, u, d, p, 0, "setup")
        return public(con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def add_user(display_name, username, temp_password, by: str = "") -> dict:
    """موظف جديد بكلمة سر مؤقتة (بيغيّرها بأول دخول)."""
    u, d = check_username(username), check_display(display_name)
    p = check_password(temp_password, u)
    with _lock, _db() as con:
        uid = _insert(con, u, d, p, 1, by or "")
        return public(con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def get(uid: int) -> dict | None:
    with _db() as con:
        r = con.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
    return public(r) if r else None


def list_users() -> list[dict]:
    with _db() as con:
        return [public(r) for r in con.execute("SELECT * FROM users ORDER BY id")]


def _need(con, uid: int):
    r = con.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
    if not r:
        raise AccountError("الموظف غير موجود", "not_found", 404)
    return r


def set_active(actor_id: int, uid: int, active: bool) -> dict:
    """تعطيل/تفعيل موظف. ما بتعطّل حسابك ولا آخر حساب فعّال. التعطيل بيطلّعه من كل جلساته."""
    with _lock, _db() as con:
        r = _need(con, uid)
        if not active:
            if int(uid) == int(actor_id):
                raise AccountError("ما بتقدر تعطّل حسابك بنفسك", "rules", 409)
            others = con.execute("SELECT COUNT(*) FROM users WHERE active=1 AND id!=?", (int(uid),)).fetchone()[0]
            if r["active"] and not others:
                raise AccountError("هاد آخر حساب فعّال — ما بينعطّل", "rules", 409)
        con.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, int(uid)))
        if not active:
            con.execute("DELETE FROM sessions WHERE user_id=?", (int(uid),))
        return public(_need(con, uid))


def reset_password(actor_id: int, uid: int, temp_password) -> dict:
    """تصفير كلمة سر موظف (غيرك) بكلمة مؤقتة: بيطلّعه من كل جلساته وبيفرض عليه كلمة جديدة بأول دخول."""
    with _lock, _db() as con:
        r = _need(con, uid)
        if int(uid) == int(actor_id):
            raise AccountError("ما بتصفّر كلمة سرك بنفسك — استعمل «غيّر كلمة السر»", "rules", 409)
        p = check_password(temp_password, r["username"])
        con.execute("UPDATE users SET pw_hash=?, must_change=1 WHERE id=?", (_ph().hash(p), int(uid)))
        con.execute("DELETE FROM sessions WHERE user_id=?", (int(uid),))
        _fails.pop(r["username"].lower(), None)
        return public(_need(con, uid))


def reset_by_cli(username: str, new_password: str) -> dict:
    """للاسترجاع من نفس الجهاز (python accounts.py reset): بلا قاعدة «ما بتصفّر حسابك». بيفرض تغيير كلمة السر ويفتح الاسم."""
    u = check_username(username)
    with _lock, _db() as con:
        r = con.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if not r:
            raise AccountError("ما في موظف بهالاسم", "not_found", 404)
        p = check_password(new_password, u)
        con.execute("UPDATE users SET pw_hash=?, must_change=1, active=1 WHERE id=?", (_ph().hash(p), r["id"]))
        con.execute("DELETE FROM sessions WHERE user_id=?", (r["id"],))
        _fails.pop(u, None)
        return public(_need(con, r["id"]))


def change_password(uid: int, old, new, keep_token: str | None = None) -> dict:
    """الموظف بيغيّر كلمة سره (بيطلب القديمة). بيطلّع باقي جلساته (الحالية بتضل)."""
    with _lock, _db() as con:
        r = _need(con, uid)
        try:
            _ph().verify(r["pw_hash"], str(old or ""))
        except Exception:                                         # noqa: BLE001 — أي فشل تحقق = كلمة غلط
            raise AccountError("كلمة السر الحالية غلط", "bad_login", 403) from None
        p = check_password(new, r["username"])
        if p == str(old):
            raise AccountError("اختار كلمة سر مختلفة عن الحالية")
        con.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE id=?", (_ph().hash(p), int(uid)))
        if keep_token:
            con.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (int(uid), _hash_token(keep_token)))
        else:
            con.execute("DELETE FROM sessions WHERE user_id=?", (int(uid),))
        return public(_need(con, uid))


# ── الدخول والجلسات ──────────────────────────────────────────────────────
def _throttled(key: str) -> int:
    """ثواني الانتظار المتبقية لو الاسم مقفول، وإلا 0."""
    now = time.time()
    hits = [t for t in _fails.get(key, []) if now - t < LOGIN_WINDOW_SEC]
    _fails[key] = hits
    if len(hits) >= LOGIN_FAILS:
        return max(1, int(LOCK_SEC - (now - hits[-1])))
    return 0


def authenticate(username, password) -> dict:
    """يتحقق من الاسم وكلمة السر. بيرمي AccountError (code: locked · bad_login · disabled). بيرجّع الموظف العام + must_change."""
    key = str(username or "").strip().lower()
    wait = _throttled(key)
    if wait:
        raise AccountError(f"محاولات دخول غلط كتير — جرّب بعد {max(1, wait // 60)} دقيقة", "locked", 429)
    with _lock, _db() as con:
        r = con.execute("SELECT * FROM users WHERE username=?", (key,)).fetchone()
        ok = False
        try:
            if r:
                _ph().verify(r["pw_hash"], str(password or ""))
                ok = True
            else:
                _ph().hash(str(password or "x"))                  # نفس الكلفة تقريباً: ما نكشف إذا الاسم موجود
        except AccountError:
            raise
        except Exception:                                         # noqa: BLE001
            ok = False
        if not ok:
            _fails.setdefault(key, []).append(time.time())
            raise AccountError("الاسم أو كلمة السر غلط", "bad_login", 401)
        if not r["active"]:
            raise AccountError("هالحساب معطّل — كلّم اللي بيدير الحسابات", "disabled", 403)
        try:                                                      # تحديث بصمة قديمة لمعاملات أقوى
            if _ph().check_needs_rehash(r["pw_hash"]):
                con.execute("UPDATE users SET pw_hash=? WHERE id=?", (_ph().hash(str(password)), r["id"]))
        except Exception:                                         # noqa: BLE001
            pass
        con.execute("UPDATE users SET last_login=? WHERE id=?", (_iso(_now()), r["id"]))
        _fails.pop(key, None)
        return public(_need(con, r["id"]))


def create_session(uid: int, ua: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with _db() as con:
        con.execute("INSERT INTO sessions(token_hash, user_id, created_at, last_seen, expires_at, ua) VALUES(?,?,?,?,?,?)",
                    (_hash_token(token), int(uid), _iso(now), _iso(now), _iso(now + timedelta(days=SESSION_DAYS)), (ua or "")[:200]))
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))             # تنظيف المنتهية
    return token


def session_user(token: str | None) -> dict | None:
    """الموظف الفعّال صاحب الجلسة، وإلا None. بيجدّد صلاحيتها (انزلاقياً) مرة كل 5 دقايق بالكتير."""
    if not token or len(token) > 200:
        return None
    th = _hash_token(token)
    with _db() as con:
        r = con.execute("SELECT u.*, s.expires_at AS s_exp FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (th,)).fetchone()
        if not r or not r["active"] or r["s_exp"] < _iso(_now()):
            return None
        now = time.time()
        if now - _last_slide.get(th, 0) > SLIDE_EVERY_SEC:
            _last_slide[th] = now
            con.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE token_hash=?",
                        (_iso(_now()), _iso(_now() + timedelta(days=SESSION_DAYS)), th))
        return public(r)


def end_session(token: str | None) -> None:
    if token:
        with _db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))
        _last_slide.pop(_hash_token(token), None)


# ── مين عم يشتغل ─────────────────────────────────────────────────────────
def actor() -> dict | None:
    return ACTOR.get()


def who(fallback: str = "") -> str:
    """الاسم الظاهر للموظف الحالي (حارس الدخول)، أو VP_ACTOR (مهام الخلفية)، وإلا fallback."""
    a = ACTOR.get()
    if a:
        return a.get("display_name") or fallback
    return os.environ.get("VP_ACTOR") or fallback


def actor_name(by: str) -> str:
    """اسم «مين عمل» للسجلات: القيم الافتراضية العامة (system/owner/فاضي) بتصير اسم الموظف لو في موظف، وغير هيك بتضل متل ما هي."""
    return who(by) if by in ("", "system", "owner") else by


# ── سطر الأوامر ──────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    import getpass
    ap = argparse.ArgumentParser(description="حسابات الموظفين (استرجاع من نفس الجهاز)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="اعرض الموظفين")
    rp = sub.add_parser("reset", help="صفّر كلمة سر موظف (وافتح حسابه) — بيسألك كلمة السر الجديدة")
    rp.add_argument("username")
    cp = sub.add_parser("create", help="أنشئ حساب: الأول (صاحب الاستوديو) أو موظف جديد — بيسألك كلمة السر")
    cp.add_argument("username")
    cp.add_argument("display_name", nargs="+")
    a = ap.parse_args()
    try:
        if a.cmd == "list":
            for u in list_users():
                print(f"{u['id']:>3}  {u['username']:<20} {u['display_name']:<24} {'فعّال' if u['active'] else 'معطّل'}"
                      f"{'  (بدّه كلمة سر جديدة)' if u['must_change'] else ''}")
            return
        pw = getpass.getpass("كلمة السر الجديدة: ")
        if pw != getpass.getpass("أعدها: "):
            sys.exit("[!] كلمتي السر مش متطابقتين")
        if a.cmd == "create":
            name = " ".join(a.display_name)
            if needs_setup():
                u, note = create_first(name, a.username, pw), ""
            else:
                u, note = add_user(name, a.username, pw, by="سطر الأوامر"), " — لازم يغيّر كلمة السر بأول دخول."
            print(f"تمّ: «{u['display_name']}» ({u['username']})" + note)
            return
        u = reset_by_cli(a.username, pw)
        print(f"تمّ: «{u['display_name']}» لازم يغيّر كلمة السر بأول دخول.")
    except AccountError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
