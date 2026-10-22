"""
سجل محاولات الإنتاج — SQLite بمجلد library (production_log.db).

كل محاولة إنتاج (تحريك، صورة، صوت، موسيقى، آهات) بتنسجّل: أي موديل، بأي طريقة، نجحت ولا فشلت، وكم أخدت.
الغرض: بعد أسبوعين الأرقام بتقلّك شو الأفضل لكل عنصر (خطة نظام الإنتاج، القسم 4).

القواعد:
  · التسجيل ما بيكسر الإنتاج أبداً: أي خطأ بالسجل بيتبلع (record بترجع None).
  · نص الخطأ بينقصّ على 300 حرف. ما بنسجّل توكنات ولا مفاتيح (المستدعي مسؤول، وبنشيل أي قيمة بتبدو كتوكن).
"""

from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import config

KINDS = ("motion", "image", "voice", "music", "ahat", "face_image", "face_video",   # face_*: نتيجة فحص ثبات الوجه لموديل الصور/التحريك
         "stt", "lipsync", "upscale", "bgremove", "sfx")                           # مكتبة النماذج: باقي مهامها التسع
PATHS = ("command", "http", "api", "extension",
         "app", "std", "builtin", "upload")        # app: برنامج Gradio · std: واجهة قياسية (OpenAI) · builtin: الطريقة المدمجة بالكود · upload: ملف رفعه المالك
STATUSES = ("ok", "failed")
MAX_ERROR = 300
_lock = threading.Lock()
_SECRET_RX = re.compile(r"(?i)(token|secret|api[_-]?key|authorization|password|passwd)\s*[:=]\s*(?:(?:bearer|basic)\s+)?\S+")
_BEARER_RX = re.compile(r"(?i)(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    script_stem TEXT,
    shot_id TEXT,
    model_id TEXT,
    model_name TEXT,
    path TEXT,
    status TEXT NOT NULL,
    seconds REAL,
    error TEXT,
    cost_usd REAL,
    score REAL
);
CREATE INDEX IF NOT EXISTS attempts_kind_id ON attempts(kind, id);
"""


def db_path() -> Path:
    return Path(config.LIBRARY_DIR) / "production_log.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(attempts)")}
    for col in ("cost_usd", "score"):                # ترحيل قاعدة قديمة بدون عمود التكلفة/الرقم
        if col not in cols:
            con.execute(f"ALTER TABLE attempts ADD COLUMN {col} REAL")
            con.commit()
    return con


def _clean_error(error) -> str | None:
    if not error:
        return None
    t = _SECRET_RX.sub(lambda m: m.group(1) + "=***", str(error))
    t = _BEARER_RX.sub(lambda m: m.group(1) + " ***", t).strip()
    return t[:MAX_ERROR] or None


def record(kind: str, status: str, *, script_stem: str | None = None, shot_id: str | None = None,
           model_id: str | None = None, model_name: str | None = None, path: str | None = None,
           seconds: float | None = None, error=None, cost_usd: float | None = None, score: float | None = None) -> int | None:
    """يسجّل محاولة. بيرجّع رقمها، أو None لو التسجيل نفسه فشل (الإنتاج بيكمل). score: رقم الفحص (تطابق الوجه) لأنواع face_*."""
    if kind not in KINDS:
        raise ValueError(f"نوع غير معروف: {kind}")
    if status not in STATUSES:
        raise ValueError(f"حالة غير معروفة: {status}")
    if path is not None and path not in PATHS:
        raise ValueError(f"طريقة غير معروفة: {path}")
    try:
        with _lock:
            con = _connect()
            try:
                cur = con.execute(
                    "INSERT INTO attempts(at,kind,script_stem,shot_id,model_id,model_name,path,status,seconds,error,cost_usd,score) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), kind, script_stem, shot_id, model_id,
                     model_name, path, status, None if seconds is None else round(float(seconds), 2), _clean_error(error),
                     None if cost_usd is None else round(float(cost_usd), 4), None if score is None else round(float(score), 3)))
                con.commit()
                return cur.lastrowid
            finally:
                con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return None


def recent(n: int = 50, kind: str | None = None) -> list[dict]:
    """آخر n محاولة (الأحدث أول)، مع فلتر نوع اختياري."""
    n = max(1, min(int(n), 500))
    if kind is not None and kind not in KINDS:
        raise ValueError(f"نوع غير معروف: {kind}")
    if not db_path().exists():
        return []
    try:
        con = _connect()
        try:
            if kind:
                rows = con.execute("SELECT * FROM attempts WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, n)).fetchall()
            else:
                rows = con.execute("SELECT * FROM attempts ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def stats(kind: str | None = None) -> dict:
    """أرقام إجمالية: نجاح/فشل، وتفصيل لكل موديل وكل طريقة (متوسط الزمن للناجح بس)."""
    out = {"total": 0, "ok": 0, "failed": 0, "by_kind": {}, "by_path": {}, "by_model": [], "cost_by_path": {}, "cost_total": 0.0}
    if not db_path().exists():
        return out
    where, args = ("WHERE kind=?", (kind,)) if kind else ("", ())
    try:
        con = _connect()
        try:
            for r in con.execute(f"SELECT status, COUNT(*) c FROM attempts {where} GROUP BY status", args):
                out[r["status"]] = r["c"]
            out["total"] = out["ok"] + out["failed"]
            for r in con.execute(f"SELECT kind, status, COUNT(*) c FROM attempts {where} GROUP BY kind, status", args):
                d = out["by_kind"].setdefault(r["kind"], {"ok": 0, "failed": 0})
                d[r["status"]] = r["c"]
            for r in con.execute(f"SELECT COALESCE(path,'?') p, status, COUNT(*) c FROM attempts {where} GROUP BY p, status", args):
                d = out["by_path"].setdefault(r["p"], {"ok": 0, "failed": 0})
                d[r["status"]] = r["c"]
            for r in con.execute(f"SELECT COALESCE(path,'?') p, COALESCE(SUM(cost_usd),0) c FROM attempts {where} "
                                 f"{'AND' if where else 'WHERE'} status='ok' GROUP BY p", args):
                out["cost_by_path"][r["p"]] = round(r["c"], 4)
            out["cost_total"] = round(sum(out["cost_by_path"].values()), 4)
            q = (f"SELECT kind, model_id, MAX(model_name) model_name, COALESCE(MAX(path),'?') path, COUNT(*) attempts, "
                 f"SUM(status='ok') ok, SUM(status='failed') failed, "
                 f"ROUND(AVG(CASE WHEN status='ok' THEN seconds END),1) avg_seconds "
                 f"FROM attempts {where} GROUP BY kind, model_id ORDER BY attempts DESC, model_id")
            out["by_model"] = [dict(r) for r in con.execute(q, args)]
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out



def face_rates(kind: str = "face_video") -> dict[str, dict]:
    """نسبة نجاح فحص الوجه لكل موديل: {model_id: {name, checks, passed, rate, avg_score}}.
    بتحسب الفحوص الحاسمة بس (ناجح/ساقط)؛ «ما انكشف وجه» ما بينسجّل أصلاً. بتغذّي ترتيب الموديلات للقطات الوجه."""
    if kind not in ("face_image", "face_video"):
        raise ValueError(f"نوع غير معروف: {kind}")
    if not db_path().exists():
        return {}
    try:
        con = _connect()
        try:
            rows = con.execute("SELECT model_id, MAX(model_name) name, COUNT(*) n, SUM(status='ok') ok, ROUND(AVG(score), 3) s "
                               "FROM attempts WHERE kind=? AND model_id IS NOT NULL AND model_id != '' GROUP BY model_id", (kind,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return {r["model_id"]: {"name": r["name"], "checks": r["n"], "passed": r["ok"] or 0,
                            "rate": round((r["ok"] or 0) / r["n"], 3), "avg_score": r["s"]} for r in rows if r["n"]}


def spent(script_stem: str, kind: str = "motion") -> float:
    """مجموع ما انصرف بالدولار على محاولات ناجحة لسيناريو (لسقف الإنفاق). 0 لو ما في سجل."""
    if not db_path().exists():
        return 0.0
    try:
        con = _connect()
        try:
            r = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM attempts WHERE script_stem=? AND kind=? AND status='ok'",
                            (script_stem, kind)).fetchone()
        finally:
            con.close()
        return float(r[0] or 0.0)
    except sqlite3.Error:
        return 0.0
