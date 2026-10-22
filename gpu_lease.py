"""
حجز الكرت للاستوديو — نفس القفل اللي بتستعمله صناديق الأوزان (services/engine/gpu.py).

برنامج نموذج (Gradio) أو أمر محلي أو سيرفر بواجهة قياسية بيستعمل الكرت لازم يمسك القفل قبل ما يشتغل، وإلا ممكن ينهار
هو أو الصندوق لأنو ذاكرة الكرت ما بتكفي للتنين مع بعض. وقبل ما نشتغل بنطلب من آخر صندوق استعمل الكرت يفرّغ نموذجه
(نفس بروتوكول الصناديق: ملف طلب بالمجلد المشترك).

    with gpu_lease.hold(uses_gpu=model["uses_gpu"], cancelled=cancel_event.is_set):
        ...  # نادي البرنامج

بيشتغل بس لما المتغيّر VP_GPU_LOCK_DIR مضبوط (على السيرفر: نفس حجم الأقفال المربوط بالصناديق — شوف docker-compose.yml).
بجهازك العادي، أو لنموذج ما بيستعمل الكرت = ما بيعمل أي شي.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

ENV = "VP_GPU_LOCK_DIR"
WHO = "studio"                      # اسم الاستوديو بملفات التسليم (unload_*.req / last_user)
POLL_SEC = 0.25
HANDOFF_WAIT_SEC = 30.0             # كم ننتظر صندوق يفرّغ نموذجه قبل ما نكمّل بدونه


class GpuBusy(RuntimeError):
    """الكرت مشغول أطول من الانتظار المسموح. الرسالة عربية جاهزة للعرض."""


class GpuCancelled(RuntimeError):
    """انلغت المهمة وهي بتنتظر دورها بالكرت."""


def lock_dir() -> Path | None:
    raw = os.environ.get(ENV, "").strip()
    return Path(raw) if raw else None


def enabled() -> bool:
    return lock_dir() is not None


def busy() -> bool | None:
    """هل في أي مهمة ماسكة الكرت هلأ؟ None لو الحجز مش مفعّل (ما بنعرف)."""
    d = lock_dir()
    if d is None:
        return None
    try:
        from services.engine.gpu import GpuLock
        return GpuLock(d).busy()
    except Exception:                                    # filelock ناقص أو المجلد مش قابل للكتابة: ما منعرف
        return None


def _free_previous(d: Path, cancelled) -> None:
    """آخر صندوق استعمل الكرت لسا نموذجه بالذاكرة: نطلب منه يفرّغ، ونستنى شوي (أو نكمّل لو ما ردّ)."""
    from services.engine.gpu import Handoff
    h = Handoff(d, WHO)
    prev = h.last_user()
    if not prev or prev == h.me:
        return
    h.request_unload(prev)
    end = time.monotonic() + HANDOFF_WAIT_SEC
    while h.pending_for(prev) and time.monotonic() < end and not (cancelled and cancelled()):
        time.sleep(0.05)
    if h.pending_for(prev):
        h.withdraw(prev)


@contextmanager
def hold(*, uses_gpu: bool = True, wait_sec: float = 900.0, cancelled=None):
    """يمسك قفل الكرت طول الـ with. يرمي GpuBusy لو انتظرنا أكثر من wait_sec، وGpuCancelled لو cancelled() رجعت True."""
    d = lock_dir()
    if not uses_gpu or d is None:
        yield False
        return
    try:
        from services.engine.gpu import GpuLock
        lock = GpuLock(d)
    except (ImportError, OSError):
        raise GpuBusy("قفل الكرت مش متاح (مجلد الأقفال مش قابل للكتابة أو مكتبة filelock ناقصة) — راجع إعداد VP_GPU_LOCK_DIR") from None
    end = time.monotonic() + max(0.0, wait_sec)
    while True:
        if cancelled and cancelled():
            raise GpuCancelled("انلغت قبل ما ييجي دورها بالكرت")
        if lock.acquire(timeout=POLL_SEC):
            break
        if time.monotonic() >= end:
            raise GpuBusy("الكرت مشغول بشغلة تانية (صندوق أو برنامج نموذج) — جرّب بعد شوي")
    try:
        _free_previous(d, cancelled)
        yield True
    finally:
        lock.release()
