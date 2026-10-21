"""
نقطة تشغيل صندوق النموذج: uvicorn بإعدادات من متغيرات البيئة.

    ENGINE_BACKEND  fake | ltx | wan          (افتراضي fake)
    ENGINE_TOKEN    توكن الوصول (X-Engine-Token)
    WEIGHTS_DIR     مجلد الأوزان (للقراءة فقط)
    OUTPUT_DIR      مجلد الخرج المؤقت
    LOCK_DIR        مجلد القفل المشترك بين الصناديق
    IDLE_UNLOAD_MIN دقائق الخمول قبل تفريغ النموذج من الذاكرة
    MAX_SECONDS     أقصى مدة فيديو مسموحة
    ENGINE_HOST     عنوان الاستماع (افتراضي 127.0.0.1؛ صورة Docker بتضبطه 0.0.0.0 — والـ compose بيربطه بـ 127.0.0.1 للجهاز)
    ENGINE_PORT     المنفذ (افتراضي 8000)

الاستماع بغير loopback بدون توكن ممنوع (إلا بـ ENGINE_ALLOW_NO_TOKEN=1 للتجارب).
"""

from __future__ import annotations

import os
import sys

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def main() -> None:
    import uvicorn
    from services.engine.app import Settings, create_app

    try:
        settings = Settings.from_env()
        host = os.environ.get("ENGINE_HOST", "127.0.0.1")
        port = int(os.environ.get("ENGINE_PORT", "8000"))
    except ValueError as e:
        sys.exit(f"[!] {e}")
    if host not in LOOPBACK and not settings.token and os.environ.get("ENGINE_ALLOW_NO_TOKEN") != "1":
        sys.exit("[!] الصندوق مفتوح على الشبكة بدون ENGINE_TOKEN — حط توكن بملف .env قبل التشغيل")
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("ENGINE_LOG_LEVEL", "info"), access_log=False)


if __name__ == "__main__":
    main()
