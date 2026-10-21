"""
الجدولة بلا واجهة — خيط خلفي مع السيرفر، ونفس المنطق بيشتغل من `agent.py run`.

الجهاز ممكن يكون مطفي أو نايم: كل مهمة بتنحكم على الساعة الحقيقية (مش عدّاد)، فأول
ما يشتغل بيصير catch-up لكل مستحق من آخر نجاح. كل مهمة بمعزل: خطأ وحدة ما بيوقف الباقي،
ووحدة ناقصة (crm / fatigue / learn_patterns من وكيل B1) بتنتخطّى بدون انهيار.

الحالة: library/scheduler_state.json (آخر تشغيل/نجاح/خطأ لكل مهمة).
"""

from __future__ import annotations

import importlib
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import config
import oplock
import settings_io

CHECK_EVERY_SEC = 60          # فحص المستحق (بالساعة الحقيقية) — رخيص
STARTUP_DELAY_SEC = 15        # ما نزاحم إقلاع السيرفر
RETRY_AFTER_FAILURE_MIN = 15  # مهمة يومية فشلت: ما نعيد قبل هالمدة
SKIP_RECHECK_MIN = 60         # وحدة ناقصة: نفحص كل ساعة إذا انسلّمت
SELF_DECIDING_CHECK_MIN = 30  # مهام بتقرّر استحقاقها لحالها (نسخة/تعلّم/رفع)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class _Missing(Exception):
    """الوحدة أو الدالة مش موجودة بعد (وكيل تاني لسا ما سلّمها)."""


def _call(module: str, func: str, *args, **kw):
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name == module:
            raise _Missing(f"وحدة {module} مش موجودة") from None
        raise
    fn = getattr(mod, func, None)
    if fn is None:
        raise _Missing(f"{module}.{func} مش موجودة")
    return fn(*args, **kw)


# ── تعريف المهام ────────────────────────────────────────────────────────
# (اسم، تسمية، دالة، مؤهِّل الاستحقاق). المؤهِّل: (state_of_task, now) → bool.
# بعض المهام بتقرر استحقاقها لحالها (backup / learn_patterns) فبنناديها كل دورة.


def _every(minutes: float) -> Callable[[dict, datetime], bool]:
    """مستحقة إذا مضى الوقت من آخر تشغيلة (نجحت أو فشلت) — أو ما اشتغلت أبداً."""
    def due(st: dict, now: datetime) -> bool:
        last = st.get("last_run")
        return not last or now - datetime.fromisoformat(last) >= timedelta(minutes=minutes)
    return due


def _daily(st: dict, now: datetime) -> bool:
    """مرة باليوم على الأقل: مستحقة إذا آخر نجاح مش من اليوم، مع مهلة بعد الفشل/التخطّي."""
    last = st.get("last_success")
    if last and datetime.fromisoformat(last).astimezone().date() >= now.astimezone().date():
        return False
    return _every(SKIP_RECHECK_MIN if st.get("last_outcome") == "skipped"
                  else RETRY_AFTER_FAILURE_MIN)(st, now)


def _queue_interval(st: dict, now: datetime) -> bool:
    return _every(float(getattr(config, "CRM_QUEUE_POLL_MINUTES", 60)))(st, now)


def _t_queue():
    import queue_worker
    return queue_worker.poll_once()


def _t_crm_sync():
    return _call("crm", "sync_performance")


def _t_fatigue():
    return _call("fatigue", "scan_and_draft")


def _t_learn():
    return _call("learn_patterns", "run_weekly_if_due")


def _t_backup():
    import backup
    return backup.run_daily_if_due()


def _t_library_sync():
    import library_sync
    return library_sync.push_if_changed()


# الترتيب مهم: المزامنة قبل الكشف عن الإرهاق، والنسخة بعد ما تخلص التغييرات، والرفع آخر شي.
TASKS: list[tuple[str, str, Callable, Callable]] = [
    ("queue_poll", "التقاط طلبات الـ OMS", _t_queue, _queue_interval),
    ("crm_sync", "سحب أداء الإعلانات", _t_crm_sync, _daily),
    ("fatigue_scan", "كشف إرهاق الإعلانات", _t_fatigue, _daily),
    ("learn_weekly", "التعلّم الأسبوعي للأنماط", _t_learn, _every(60)),
    ("backup_daily", "النسخة الاحتياطية اليومية", _t_backup, _every(SELF_DECIDING_CHECK_MIN)),
    ("library_sync", "رفع المكتبة للـ OMS", _t_library_sync, _every(60)),
]
TASK_NAMES = [t[0] for t in TASKS]


# ── الحالة ──────────────────────────────────────────────────────────────

_state_lock = threading.Lock()


def _state_path() -> Path:
    return Path(config.LIBRARY_DIR) / "scheduler_state.json"


def load_state() -> dict:
    try:
        s = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        s = {}
    s.setdefault("tasks", {})
    return s


def _save_state(s: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _summarize(result) -> object:
    """ملخّص صغير وآمن للنتيجة (بدون حمولات كبيرة)."""
    if isinstance(result, dict):
        keep = {k: v for k, v in result.items()
                if isinstance(v, (str, int, float, bool, type(None))) or k in ("counts",)}
        return keep
    if isinstance(result, (list, tuple)):
        return {"count": len(result)}
    return result if isinstance(result, (str, int, float, bool, type(None))) else str(result)[:200]


def _failed(result) -> str | None:
    if isinstance(result, dict) and result.get("ok") is False:
        return str(result.get("error") or "فشل")
    return None


def run_task(name: str, *, force: bool = False) -> dict:
    """ينفّذ مهمة وحدة إذا مستحقة (أو force). ما بيرمي أبداً."""
    spec = next((t for t in TASKS if t[0] == name), None)
    if spec is None:
        return {"task": name, "ran": False, "error": "مهمة غير معروفة"}
    _, label, fn, due = spec

    with _state_lock:
        st = load_state()["tasks"].get(name, {})
    now = _now()
    if not force:
        try:
            if not due(st, now):
                return {"task": name, "ran": False, "reason": "مش مستحقة"}
        except ValueError:
            pass

    with oplock.file_lock(Path(config.LIBRARY_DIR) / f".sched_{name}.lock", stale_seconds=2 * 3600) as got:
        if not got:
            return {"task": name, "ran": False, "reason": "شغّالة بعملية تانية"}
        started = _now()
        outcome: dict
        try:
            result = fn()
            err = _failed(result)
            if err and isinstance(result, dict) and result.get("offline"):
                # الـ OMS/الإنترنت مش متاح: مش عطل عندنا، بنعيد لاحقاً بدون ما نعدّه فشل
                outcome = {"offline": err}
            else:
                outcome = {"error": err} if err else {"ok": True}
            outcome["result"] = _summarize(result)
        except _Missing as e:
            outcome = {"skipped": str(e)}
        except Exception as e:                                          # noqa: BLE001
            outcome = {"error": settings_io.redact(f"{type(e).__name__}: {e}")[:300]}

    with _state_lock:
        s = load_state()
        t = s["tasks"].setdefault(name, {})
        t["label"] = label
        t["last_run"] = _iso(started)
        t["runs"] = int(t.get("runs", 0)) + 1
        t["last_outcome"] = ("skipped" if outcome.get("skipped") else "offline" if outcome.get("offline")
                             else "error" if outcome.get("error") else "ok")
        if outcome.get("offline"):
            t["last_offline"] = outcome["offline"]
            t["last_error"] = None
        elif outcome.get("skipped"):
            t["last_skipped"] = outcome["skipped"]
            t["last_error"] = None
        elif outcome.get("error"):
            t["last_error"] = outcome["error"]
            t["last_error_at"] = _iso(started)
            t["failures"] = int(t.get("failures", 0)) + 1
        else:
            t["last_success"] = _iso(started)
            t["last_error"] = None
            t["last_skipped"] = None
            t["last_offline"] = None
            t["last_result"] = outcome.get("result")
        _save_state(s)
    return {"task": name, "ran": True, **outcome}


def run_due(only: list[str] | None = None, *, force: bool = False) -> list[dict]:
    """يمرّ على كل المهام بالترتيب وينفّذ المستحق. خطأ وحدة ما بيوقف الباقي."""
    results = []
    for name in TASK_NAMES:
        if only and name not in only:
            continue
        results.append(run_task(name, force=force))
    return results


# ── الخيط الخلفي ─────────────────────────────────────────────────────────

_thread: threading.Thread | None = None
_stop = threading.Event()


def _loop(initial_delay: float, check_every: float) -> None:
    if _stop.wait(initial_delay):
        return
    while not _stop.is_set():
        try:
            run_due()
        except Exception:                                               # noqa: BLE001
            pass
        if _stop.wait(check_every):
            return


def start(initial_delay: float = STARTUP_DELAY_SEC, check_every: float = CHECK_EVERY_SEC) -> bool:
    """يشغّل الخيط (idempotent). VIDPATTERN_NO_SCHEDULER=1 بيعطّله."""
    global _thread
    if os.environ.get("VIDPATTERN_NO_SCHEDULER") == "1":
        return False
    if _thread is not None and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(initial_delay, check_every),
                               name="vidpattern-scheduler", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()


def status() -> dict:
    s = load_state()["tasks"]
    tasks = []
    for name, label, _fn, _due in TASKS:
        st = s.get(name, {})
        tasks.append({
            "task": name, "label": label,
            "last_run": st.get("last_run"), "last_success": st.get("last_success"),
            "last_error": st.get("last_error"), "last_skipped": st.get("last_skipped"),
            "last_offline": st.get("last_offline"),
            "runs": st.get("runs", 0), "failures": st.get("failures", 0),
        })
    return {"running": bool(_thread and _thread.is_alive()), "tasks": tasks,
            "check_every_sec": CHECK_EVERY_SEC}
