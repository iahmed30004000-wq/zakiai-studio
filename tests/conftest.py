"""إعدادات مشتركة للاختبارات."""

import os

import pytest

# الترجمة التلقائية للأنماط ما بتشتغل لحالها بالاختبارات (الاختبارات اللي بتفحصها بتشغّلها صراحة بـ monkeypatch.setenv)
os.environ["VP_AUTO_TRANSLATE"] = "0"
# درايف (drive_sync) ما بيسجّل ولا بيرفع شي بالاختبارات — اختبارات درايف بتشيل هالمتغيّر صراحة (tests/fake_drive.py)
os.environ["VIDPATTERN_NO_DRIVE"] = "1"


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
def _model_library_isolated(monkeypatch, tmp_path_factory):
    """مكتبة النماذج (library/model_library.json) ملف المالك الحقيقي — الاختبارات ما بتلمسه ولا بتتأثر فيه: كل اختبار بملف مؤقت فاضي.
    اختبارات المكتبة نفسها بتشير لملفها بنفس المتغيّر (VP_MODEL_LIBRARY) أو بتحذفه لتفحص المسار الافتراضي."""
    monkeypatch.setenv("VP_MODEL_LIBRARY", str(tmp_path_factory.mktemp("modellib") / "model_library.json"))


@pytest.fixture(autouse=True)
def _auth_gate_off(monkeypatch):
    """حارس الدخول (web/auth_gate.py) بيطفا بالاختبارات: كلها بتنادي مسارات بلا حسابات. اختبارات الحارس والحسابات بتشغّله صراحة."""
    try:
        from web import auth_gate
    except Exception:
        return
    monkeypatch.setattr(auth_gate, "ACTIVE", False)
