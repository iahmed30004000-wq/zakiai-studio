"""
قفل الكرت المشترك + تسليمه بين الصناديق — ملف صغير بلا FastAPI ولا torch.

الصناديق (services/engine/app.py) والاستوديو (gpu_lease.py) بيستوردوه: الكل بيمسك نفس ملف القفل (gpu.lock)
بنفس المجلد المشترك، فشغلة وحدة على الكرت بكل لحظة حتى لو صندوق وبرنامج نموذج (Gradio) وأمر محلي مع بعض.
filelock بيتستورد وقت الاستعمال بس (الاستوديو بدون كرت ما بيحتاجه).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_NAME_RX = re.compile(r"[^A-Za-z0-9_.-]")
SHARED_MODE = 0o666      # المجلد بتشاركه حاويات بمستخدمين مختلفين (الصناديق uid 10001، والاستوديو غيرو): الملفات لازم تنفتح للكل


def _share(path: Path) -> None:
    """يخلّي الملف مفتوح للقراءة والكتابة لكل مستخدم (ما بيأثر لو مش ملكنا: اللي أنشأه هو اللي ضبطه)."""
    try:
        os.chmod(path, SHARED_MODE)
    except OSError:
        pass


def _put(path: Path, text: str) -> None:
    """يكتب ملف صغير بالمجلد المشترك. لو الملف لمستخدم تاني ومش قابل للكتابة: بنحذفه (المجلد مفتوح للكل) ونعيد كتابته."""
    try:
        path.write_text(text, encoding="utf-8")
    except PermissionError:
        path.unlink()
        path.write_text(text, encoding="utf-8")
    _share(path)


class GpuLock:
    """قفل ملف مشترك بين كل الصناديق (نفس المجلد مربوط بكلهم)."""

    def __init__(self, lock_dir: Path):
        from filelock import FileLock
        lock_dir.mkdir(parents=True, exist_ok=True)
        self.path = lock_dir / "gpu.lock"
        try:
            os.close(os.open(self.path, os.O_RDWR | os.O_CREAT, SHARED_MODE))
        except OSError:
            pass
        _share(self.path)
        self._lock = FileLock(str(self.path), mode=SHARED_MODE)

    def acquire(self, timeout: float) -> bool:
        from filelock import Timeout
        try:
            self._lock.acquire(timeout=timeout)
            return True
        except Timeout:
            return False

    def release(self) -> None:
        if self._lock.is_locked:
            self._lock.release()

    @property
    def held(self) -> bool:
        return self._lock.is_locked

    def busy(self) -> bool:
        """هل في أي صندوق (حتى هاد) ماسك الكرت هلأ؟ بمحاولة قفل لحظية بنسخة منفصلة."""
        from filelock import FileLock, Timeout
        probe = FileLock(str(self.path), mode=SHARED_MODE, thread_local=False)
        try:
            probe.acquire(timeout=0)
        except Timeout:
            return True
        except OSError:
            return False
        probe.release()
        return False


class Handoff:
    """تسليم الكرت بين الصناديق: مين آخر واحد استعمله، وطلب «فرّغ نموذجك» بملفات صغيرة بالمجلد المشترك."""

    def __init__(self, lock_dir: Path, me: str):
        self.dir = lock_dir
        self.me = _NAME_RX.sub("_", me)

    def _req(self, name: str) -> Path:
        return self.dir / f"unload_{_NAME_RX.sub('_', name)}.req"

    @property
    def _last(self) -> Path:
        return self.dir / "last_user"

    def last_user(self) -> str | None:
        try:
            return self._last.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def mark_used(self) -> None:
        try:
            _put(self._last, self.me)
        except OSError:
            pass

    def clear_last_if_me(self) -> None:
        if self.last_user() == self.me:
            try:
                self._last.unlink()
            except OSError:
                pass

    def request_unload(self, other: str) -> None:
        try:
            _put(self._req(other), self.me)
        except OSError:
            pass

    def requested(self) -> bool:
        return self._req(self.me).exists()

    def done(self) -> None:
        try:
            self._req(self.me).unlink()
        except OSError:
            pass

    def pending_for(self, other: str) -> bool:
        return self._req(other).exists()

    def withdraw(self, other: str) -> None:
        """سحب طلب «فرّغ» ما انردّ عليه (الصندوق التاني واقف أو بطيء): منكمّل بدونه."""
        try:
            self._req(other).unlink()
        except OSError:
            pass
