# models — أوزان النماذج المحلية (بتنزل مرة وحدة، بلا إنترنت بعدها)

| المجلد/الملف | المصدر | الحجم | الترخيص | شو بيعمل |
|---|---|---|---|---|
| BiRefNet/ | huggingface.co/ZhengPeng7/BiRefNet | 0.44 غيغا | MIT | تفريغ خلفية الصور (bgremove.py) |
| faster-whisper-large-v3/ | huggingface.co/Systran/faster-whisper-large-v3 | 3.1 غيغا | MIT | تفريغ الصوت وتوقيت كل كلمة (stt.py) |
| RealESRGAN_x4plus.pth | github.com/xinntao/Real-ESRGAN (v0.1.0) | 64 ميغا | BSD-3 | تكبير الصور (upscale.py) |

منزّلة بتاريخ 2026-10-21 وأحجامها متحقّق منها. هالمجلد برّا النسخ الاحتياطي الصغير (حجمه ~3.5 غيغا).
لإعادة التنزيل: huggingface_hub.snapshot_download(repo_id=..., local_dir="models/<الاسم>").
whisper على كرتك الحالي بيرجع للمعالج تلقائياً (مكتبات CUDA 12 ناقصة) — أبطأ بس شغّال. على السيرفر بيشتغل على الكرت.
