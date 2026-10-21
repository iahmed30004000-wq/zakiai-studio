"""إعدادات مشتركة للاختبارات."""

import os

import pytest

# الترجمة التلقائية للأنماط ما بتشتغل لحالها بالاختبارات (الاختبارات اللي بتفحصها بتشغّلها صراحة بـ monkeypatch.setenv)
os.environ["VP_AUTO_TRANSLATE"] = "0"


@pytest.fixture(autouse=True)
def _stable_gpu_memory(monkeypatch):
    """ذاكرة الكرت الحرة بتتغيّر حسب اللي شغّال بالجهاز (مثلاً السيرفر محمّل نماذج)، فبنثبّتها على القيمة المضبوطة
    (GPU_VRAM_GB) عشان نتيجة الاختبارات ما تعتمد على حالة الكرت وقت التشغيل. الاختبارات اللي بتفحص اختيار الموديل
    بتمرّر vram_gb صراحة."""
    try:
        import motion
    except Exception:
        return
    monkeypatch.setattr(motion, "available_vram_gb", lambda: float(getattr(motion.config, "GPU_VRAM_GB", 6)))
