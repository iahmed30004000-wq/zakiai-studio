"""إعدادات المنظومة — القيم الافتراضية هون، وتعديلاتك من الواجهة بـ settings.json."""

import os
from pathlib import Path

BASE = Path(__file__).parent

# ── المسارات ─────────────────────────────────────────────────────────────
LIBRARY_DIR = BASE / "library"
CANDIDATES_DIR = LIBRARY_DIR / "candidates"  # مخرجات المرحلة 0
RAW_DIR = LIBRARY_DIR / "raw"            # مخرجات المرحلة 1
PATTERNS_DIR = LIBRARY_DIR / "patterns"  # مكتبة الأنماط (المرحلة 2)
SCRIPTS_DIR = LIBRARY_DIR / "scripts"    # السيناريوهات (المرحلة 3)
REGISTRY_PATH = LIBRARY_DIR / "used_registry.json"
PROMPTS_DIR = BASE / "prompts"
PRODUCTS_DIR = BASE / "products"

# ── الحصاد (المرحلة 0 — Apify) ───────────────────────────────────────────
# تأكد من معرّفات الأكترز من متجر Apify — بتتغيّر أحياناً.
APIFY_ACTORS = {
    "tiktok": "clockworks/tiktok-scraper",
    "adlibrary": "curious_coder/facebook-ads-library-scraper",
    "reels": "apify/instagram-scraper",
}
APIFY_TIMEOUT_SEC = 600

# عتبات قبول الفيديو كـ"ناجح" — عدّلها حسب حجم السوق
MIN_VIEWS = 100_000
MIN_LIKES = 2_000
MIN_ENGAGEMENT_RATE = 0.02   # لايكات ÷ مشاهدات
MAX_AGE_DAYS = 180           # 0 = بدون حد
HARVEST_TOP_N = 40           # أعلى كم مرشّح ينحفظ من كل حصاد

# ── التفريغ الصوتي (Whisper) ─────────────────────────────────────────────
WHISPER_MODEL = "large-v3"   # بدائل أخف: medium / small
WHISPER_DEVICE = "cuda"      # "cpu" إذا ما في كرت شاشة
WHISPER_COMPUTE = "int8_float16"  # أخف على ذاكرة الكرت (6 غيغا) وبنفس الدقة تقريباً | "float16" لكرت أكبر | "int8" مع cpu
WHISPER_LANGUAGE = None      # None = كشف تلقائي | "ar" لتثبيت العربية

# ── كشف المشاهد ──────────────────────────────────────────────────────────
SCENE_THRESHOLD = 27.0       # أقل رقم = حساسية أعلى = مشاهد أكثر
MIN_SCENE_SEC = 0.6          # أقصر مشهد مقبول

# ── OCR ──────────────────────────────────────────────────────────────────
OCR_LANGS = ["ar", "en"]
OCR_MIN_CONFIDENCE = 0.45
OCR_USE_GPU = True           # False إذا ما في كرت شاشة

# ── الموديلات ────────────────────────────────────────────────────────────
MODEL_ANALYSIS = "claude-sonnet-5"   # تشريح الفيديو (رؤية)
MODEL_MATCH = "claude-sonnet-5"      # مطابقة المنتج بالأنماط
MODEL_WRITER = "claude-opus-5"       # كتابة السيناريو
MAX_FRAMES_PER_VIDEO = 14            # سقف اللقطات المرسلة للتحليل
MAX_OUTPUT_TOKENS = 16000            # سقف مخرجات الموديل — ارفعه إذا انقطع الرد بالنص

# ── قواعد السيناريو ──────────────────────────────────────────────────────
SCRIPT_SCENES = 7
SCRIPT_MIN_SEC = 45
SCRIPT_MAX_SEC = 50
HOOKS_DEFAULT = 3                 # افتتاحيات (هوكات) لكل سيناريو: الأساسي + بدائل لاختبارها بإعلانات
HOOKS_MAX = 5
AUTO_TRANSLATE_PATTERNS = True   # أي نمط نصه مش عربي بينترجم لحاله بالخلفية (المالك ما بيعمل شي)

# ── إعادة الضبط: العتبات ─────────────────────────────────────────────────
SCRIPT_MAX_REVIEW_ROUNDS = 2      # دورات إعادة الكتابة قبل ما يوقف ويرفع للمالك
MIN_DELIVERED = 20                # أقل طلبات مُسلَّمة قبل أي حكم على سيناريو/نمط
LIBRARY_QUOTA = 10                # أنماط لكل فئة نشطة قبل ما تعتبر المطابقة موثوقة
FAR_CATEGORY_PENALTY = 25         # خصم نقاط الملاءمة لنمط من فئة بعيدة
ADJACENT_CATEGORY_PENALTY = 5
FATIGUE_DAYS = 7                  # أيام ارتفاع تكلفة الطلب المُسلَّم المتتالية
BACKUP_KEEP = 30
BACKUP_ALERT_DAYS = 2
CRM_QUEUE_POLL_MINUTES = 60
PERF_MATURITY_DAYS = 3            # التسليم بالدفع عند الاستلام بيتأخر — أحدث أيام بتنشال من الأحكام
CRM_RESYNC_LOOKBACK_DAYS = 14     # كل مزامنة بتعيد سحب آخر N يوم (المُسلَّم للأيام القديمة بيتغيّر)
CRM_INITIAL_BACKFILL_DAYS = 60
STUDIO_MAX_SHOT_SEC = 3.0        # أقصى مدة للقطة (قابلة للضبط)
STUDIO_MAX_SHOTS_PER_SCENE = 3
STUDIO_IMAGE_CANDIDATES = 2         # خيارات لكل لقطة
STUDIO_MAX_IMAGE_CALLS = 80         # حد نداءات الصور لكل فيديو (السعر مش معروف — الحد بالعدد)
GPU_VRAM_GB = 6                     # لو ما انقرت الذاكرة الحرة من الكرت
MOTION_TIMEOUT_SEC = 3600           # مهلة تشغيل موديل تحريك للقطة
MOTION_API_CAP_USD = 15.0           # سقف إنفاق التحريك بالـ API (دولار) لكل سيناريو — بعده بننزل للمحلي أو بنفشل
MONTAGE_FINAL_ENGINE = "ffmpeg"     # التصدير النهائي: "ffmpeg" (سريع) | "remotion" (متقدّم: ترجمة بالكلمة + بطاقات؛ بيرجع للعادي لو فشل)
LAUNCH_MAX_MB = 500                 # أقصى حجم فيديو للإطلاق (حماية محلية)
STUDIO_VOICE_MAX_ROUNDS = 2       # دورات تعديل النص لضبط مدة الصوت قبل ما يرفع للمالك
MIN_BASELINE_SCRIPTS = 3          # أقل سيناريوهات مؤهّلة لحساب خط الأساس

# ── تعديلات المستخدم من الواجهة ───────────────────────────────────────────
# settings.json بيكتبه تبويب الإعدادات وبيغلب القيم فوق.
# منقرأه بالآخر عشان يقدر يعدّل أي شي انكتب قبله.
SETTINGS_PATH = BASE / "settings.json"

# القيم المسموح تعديلها من الواجهة — أي مفتاح غيرها بينتجاهل
OVERRIDABLE = {
    "SCRIPT_MAX_REVIEW_ROUNDS", "MIN_DELIVERED", "LIBRARY_QUOTA", "FAR_CATEGORY_PENALTY", "ADJACENT_CATEGORY_PENALTY",
    "FATIGUE_DAYS", "BACKUP_KEEP", "BACKUP_ALERT_DAYS", "CRM_QUEUE_POLL_MINUTES", "PERF_MATURITY_DAYS", "CRM_RESYNC_LOOKBACK_DAYS", "CRM_INITIAL_BACKFILL_DAYS", "MIN_BASELINE_SCRIPTS", "STUDIO_MAX_SHOT_SEC", "STUDIO_MAX_SHOTS_PER_SCENE", "STUDIO_VOICE_MAX_ROUNDS", "LAUNCH_MAX_MB", "MONTAGE_FINAL_ENGINE", "GPU_VRAM_GB", "MOTION_TIMEOUT_SEC", "MOTION_API_CAP_USD", "STUDIO_IMAGE_CANDIDATES", "STUDIO_MAX_IMAGE_CALLS",
    "MODEL_ANALYSIS", "MODEL_MATCH", "MODEL_WRITER", "MAX_OUTPUT_TOKENS",
    "MAX_FRAMES_PER_VIDEO", "WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE",
    "WHISPER_LANGUAGE", "SCENE_THRESHOLD", "MIN_SCENE_SEC", "OCR_LANGS",
    "OCR_MIN_CONFIDENCE", "OCR_USE_GPU", "SCRIPT_SCENES", "SCRIPT_MIN_SEC",
    "SCRIPT_MAX_SEC", "HOOKS_DEFAULT", "AUTO_TRANSLATE_PATTERNS", "MIN_VIEWS", "MIN_LIKES", "MIN_ENGAGEMENT_RATE",
    "MAX_AGE_DAYS", "HARVEST_TOP_N",
}

# settings_io بيحلّ مراجع الأسرار (secret:...) من مخزن ويندوز — مفاتيح API ما بتنقرا من ملف نصي
import settings_io as _settings_io  # noqa: E402

_user = _settings_io.load()
for _k, _v in _user.items():
    if _k in OVERRIDABLE:
        globals()[_k] = _v
# المفتاح بينحط بالبيئة عشان العمليات الفرعية ترثه
if _user.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = _user["ANTHROPIC_API_KEY"]
