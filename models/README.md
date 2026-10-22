# models — أوزان النماذج المحلية (بتنزل مرة وحدة، بلا إنترنت بعدها)

| المجلد/الملف | المصدر | الحجم | الترخيص | شو بيعمل |
|---|---|---|---|---|
| BiRefNet/ | huggingface.co/ZhengPeng7/BiRefNet | 0.44 غيغا | MIT | تفريغ خلفية الصور (bgremove.py) |
| faster-whisper-large-v3/ | huggingface.co/Systran/faster-whisper-large-v3 | 3.1 غيغا | MIT | تفريغ الصوت وتوقيت كل كلمة (stt.py) |
| RealESRGAN_x4plus.pth | github.com/xinntao/Real-ESRGAN (v0.1.0) | 64 ميغا | BSD-3 | تكبير الصور (upscale.py) |
| face/face_detection_yunet_2023mar.onnx | github.com/opencv/opencv_zoo (face_detection_yunet) | 0.23 ميغا | MIT | كشف الوجوه (facecheck.py) |
| face/face_recognition_sface_2021dec.onnx | github.com/opencv/opencv_zoo (face_recognition_sface) | 38.7 ميغا | Apache-2.0 | مطابقة الوجوه — فحص ثبات الشخصية (facecheck.py) |

منزّلة بتاريخ 2026-10-21 (نماذج الوجه 2026-10-22) وأحجامها متحقّق منها. بصمة SHA-256 لنموذجي الوجه مكتوبة بـ facecheck.py وبتنفحص عند التحميل (تنزيل ناقص = رسالة واضحة). هالمجلد برّا النسخ الاحتياطي الصغير (حجمه ~3.5 غيغا).
لإعادة التنزيل: huggingface_hub.snapshot_download(repo_id=..., local_dir="models/<الاسم>").
whisper على كرتك الحالي بيرجع للمعالج تلقائياً (مكتبات CUDA 12 ناقصة) — أبطأ بس شغّال. على السيرفر بيشتغل على الكرت.

نماذج الوجه (face/): بتشتغل على المعالج وبتحتاج ثواني قليلة لكل صورة. ممنوع نبدّلها بموديلات InsightFace/ArcFace الجاهزة: رخصتها للأبحاث فقط مش للاستعمال التجاري.
لإعادة التنزيل: raw.githubusercontent.com/opencv/opencv_zoo/main/models/<اسم المجلد>/<اسم الملف> (نفس الأسماء بالجدول).
