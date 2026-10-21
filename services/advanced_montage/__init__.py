"""
المونتاج المتقدّم: طبقة التحضير والتحقق + محرّك الرندر Remotion (renderers/remotion_engine.py، مشروع remotion/).

  · adapter/build_job.py  الخط الزمني المعتمد ← job محايد (JSON)
  · adapter/stage_media.py تجهيز مجلد عمل مؤقت بأسماء آمنة (ASCII) ومنع الخروج من المكتبة
  · adapter/verify.py     فحص الناتج بـ ffprobe
  · adapter/audio_mix.py  الصوت المدموج (آهات + خفض تلقائي + loudnorm)
  · render.py             سجل محرّكات (remotion)
  · cli.py                python -m services.advanced_montage prepare|verify|doctor|render|still

ما في هون أي كود مأخوذ من مشاريع خارجية. الرندر بيحتاج Node وChrome الموجود على الجهاز (شوف README_AR.md).
"""

from .constants import JOB_VERSION
from .errors import JobError, RendererUnavailable, StageError

__all__ = ["JOB_VERSION", "JobError", "StageError", "RendererUnavailable"]
