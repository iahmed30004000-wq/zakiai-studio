"""
إلغاء المهمة = SIGTERM (web/jobs.py: proc.terminate()). بلينكس العملية بتموت فوراً بدون ما تشتغل كتل finally، فلو كانت
بتنتظر صندوق نموذج (محمّل على الكرت) الصندوق بيكمّل يولّد لحد المهلة. install() بتحوّل SIGTERM لـ SystemExit فتشتغل
كتل finally (مثلاً DELETE /jobs/{id} للصندوق) قبل الخروج.

ويندوز: ما في SIGTERM حقيقي (terminate هناك قتل فوري) — ما بنعمل شي، وطبعاً ما في صناديق عليه.
بتنادى أول سطر بـ main() لأوامر المهام اللي بتكلّم نموذجاً خارجياً (تحريك، صور، صوت، مكتبة النماذج).
"""

from __future__ import annotations

import signal
import threading

EXIT_CODE = 143          # 128 + SIGTERM: نفس رمز الخروج لو انقتلت مباشرة


def _on_term(signum, frame):
    raise SystemExit(EXIT_CODE)


def install() -> bool:
    """بترجع True لو ركّبت المعالج. بتتجاهل ويندوز والخيوط غير الرئيسية (signal.signal ممنوع فيها)."""
    sig = getattr(signal, "SIGTERM", None)
    if sig is None or threading.current_thread() is not threading.main_thread():
        return False
    try:
        import os
        if os.name == "nt":
            return False
        signal.signal(sig, _on_term)
        return True
    except (ValueError, OSError):
        return False
