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


@pytest.fixture(autouse=True)
def _image_provider_takes_refs(monkeypatch):
    """مزوّد الصور المضبوط عند المالك (UnoRouter) ما بياخد صور مرجعية، والاختبارات ما بتعتمد على إعداداته الحقيقية (settings.json).
    اختبارات التحويل للإضافة بتغيّر هالقيمة صراحة."""
    try:
        import image_studio
    except Exception:
        return
    monkeypatch.setattr(image_studio, "refs_supported",
                        lambda overrides=None: {"provider": "test", "model": "test", "supports_refs": True})


@pytest.fixture(autouse=True)
def _auth_gate_off(monkeypatch):
    """حارس الدخول (web/auth_gate.py) بيطفا بالاختبارات: كلها بتنادي مسارات بلا حسابات. اختبارات الحارس والحسابات بتشغّله صراحة."""
    try:
        from web import auth_gate
    except Exception:
        return
    monkeypatch.setattr(auth_gate, "ACTIVE", False)
