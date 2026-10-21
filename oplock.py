"""
قفل ملفات بسيط بين العمليات — عشان السيرفر والوكيل (agent.py) ما ينفّذوا نفس المهمة سوا.
القفل بيُعتبر ميّت إذا عمره فوق المدة المحدّدة (انهيار عملية).
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path | str, stale_seconds: float = 3 * 3600):
    """بيعطي True إذا أخدنا القفل، False إذا حدا تاني ماسكه. بيفكّه بالخروج."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - p.stat().st_mtime
            except OSError:
                continue
            if age > stale_seconds:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            break
        except OSError:
            break
    if fd is None:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield True
    finally:
        try:
            p.unlink()
        except OSError:
            pass
