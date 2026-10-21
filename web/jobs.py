"""
طابور المهام — الحالة محفوظة بـ SQLite مش بالذاكرة.

المعالجة (تفريغ + OCR + تحليل) بتاخد دقايق، فما بتنفع تنحبس بطلب HTTP.
كل مهمة بتنحفظ بقاعدة البيانات، فبتضل موجودة حتى لو السيرفر وقف وانفتح،
ولما نرحّل لسيرفر حقيقي منبدّل SQLite بـ Postgres والـ thread بـ worker منفصل
بدون ما نلمس طبقة الويب.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "library" / "jobs.db"

# المعالجة بتستهلك الكرت، فمهمة وحدة بكل لحظة — تشغيل متوازي بيفحّم الرام
_queue: Queue = Queue()
_worker_started = False
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                kind        TEXT NOT NULL,
                label       TEXT NOT NULL,
                status      TEXT NOT NULL,
                cmd         TEXT NOT NULL,
                log         TEXT NOT NULL DEFAULT '',
                error       TEXT,
                created_at  TEXT NOT NULL,
                started_at  TEXT,
                finished_at TEXT
            )
            """
        )
        # أي مهمة كانت شغالة وقت إغلاق السيرفر ما رح تكمل لحالها
        conn.execute(
            "UPDATE jobs SET status='failed', error='توقف السيرفر أثناء التنفيذ' "
            "WHERE status IN ('running','queued')"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(kind: str, label: str, cmd: list[str]) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, label, status, cmd, created_at) VALUES (?,?,?,?,?,?)",
            (job_id, kind, label, "queued", json.dumps(cmd), _now()),
        )
    _queue.put(job_id)
    _ensure_worker()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 30) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, kind, label, status, error, created_at, started_at, finished_at "
            "FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def active_count() -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()
    return row["n"]


def _append_log(job_id: str, text: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE jobs SET log = log || ? WHERE id=?", (text, job_id))


# المهام الشغالة: job_id -> Popen، عشان نقدر نوقفها
_running: dict[str, subprocess.Popen] = {}
# الإلغاء بيوسم المهمة قبل ما يقتل العملية — منميّز الإيقاف عن الفشل الحقيقي
_cancelled: set[str] = set()


def pause_job(job_id: str) -> str:
    """يعلّق العملية وكل أولادها (ffmpeg مثلاً) بدون ما يفقد التقدّم."""
    job = get_job(job_id)
    if not job:
        return "not_found"
    if job["status"] != "running":
        return "not_running"

    proc = _running.get(job_id)
    if not proc or proc.poll() is not None:
        return "not_running"

    try:
        import psutil
    except ImportError:
        return "no_psutil"

    try:
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.suspend()
        parent.suspend()
    except psutil.Error:
        return "not_running"

    with _connect() as conn:
        conn.execute("UPDATE jobs SET status='paused' WHERE id=?", (job_id,))
    return "paused"


def resume_job(job_id: str) -> str:
    job = get_job(job_id)
    if not job:
        return "not_found"
    if job["status"] != "paused":
        return "not_paused"

    proc = _running.get(job_id)
    if not proc or proc.poll() is not None:
        with _connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error='ضاعت العملية أثناء التعليق' WHERE id=?",
                (job_id,),
            )
        return "lost"

    try:
        import psutil
        parent = psutil.Process(proc.pid)
        parent.resume()
        for child in parent.children(recursive=True):
            child.resume()
    except Exception:
        return "lost"

    with _connect() as conn:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    return "resumed"


def cancel_job(job_id: str) -> str:
    """يوقف مهمة شغالة أو يشيل وحدة من الطابور. بيرجع وصف النتيجة."""
    job = get_job(job_id)
    if not job:
        return "not_found"

    if job["status"] == "queued":
        with _connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='cancelled', error='أُلغيت قبل ما تبدأ', finished_at=? "
                "WHERE id=? AND status='queued'",
                (_now(), job_id),
            )
        return "cancelled"

    if job["status"] in ("running", "paused"):
        proc = _running.get(job_id)
        if proc and proc.poll() is None:
            _cancelled.add(job_id)
            # عملية معلّقة ما بتستقبل terminate — لازم نفكّ التعليق أول
            if job["status"] == "paused":
                resume_job(job_id)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            return "cancelled"
        return "already_finished"

    return "not_active"


def _run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    # ممكن تكون انلغت وهي بالطابور
    if job["status"] != "queued":
        return
    cmd = json.loads(job["cmd"])

    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=?", (_now(), job_id)
        )

    try:
        proc = subprocess.Popen(
            [sys.executable, *cmd],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        _running[job_id] = proc
        buffer: list[str] = []
        for line in proc.stdout:
            buffer.append(line)
            # كتابة مجمّعة — كل سطر لحاله بيقفل القاعدة كتير
            if len(buffer) >= 5:
                _append_log(job_id, "".join(buffer))
                buffer.clear()
        if buffer:
            _append_log(job_id, "".join(buffer))
        code = proc.wait()

        if code == 0:
            status, error = "done", None
        elif _was_cancelled(job_id):
            status, error = "cancelled", "أوقفها المستخدم"
        else:
            status, error = "failed", _reason_from_log(job_id, code)
    except Exception as exc:
        status, error = "failed", str(exc)
    finally:
        _running.pop(job_id, None)

    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?",
            (status, error, _now(), job_id),
        )


def _was_cancelled(job_id: str) -> bool:
    return job_id in _cancelled


def _reason_from_log(job_id: str, code: int) -> str:
    """
    السكربتات بتطبع سبب الفشل بسطر يبدأ بـ [!] قبل ما تخرج.
    عرض هالسطر أنفع بكتير من "انتهت العملية برمز 1".
    """
    job = get_job(job_id) or {}
    lines = [ln.strip() for ln in (job.get("log") or "").splitlines() if ln.strip()]
    for line in reversed(lines[-40:]):
        if line.startswith("[!]"):
            return line.removeprefix("[!]").strip()
    # آخر سطر غير تتبّع بايثون
    for line in reversed(lines[-10:]):
        if not line.startswith(("File ", "  ", "Traceback", "^")):
            return line[:300]
    return f"انتهت العملية برمز {code}"


def _worker_loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run_job(job_id)
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, daemon=True).start()
        _worker_started = True


def requeue_pending() -> None:
    """يرجّع مهام كانت بالطابور وقت إقلاع السيرفر (بعد فشل سابق)."""
    _ensure_worker()
