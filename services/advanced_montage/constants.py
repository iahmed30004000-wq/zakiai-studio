"""
ثوابت المونتاج المتقدّم. القيم نفس ثوابت montage.py (الأرقام هون كلها لاتينية 0-9).
اختبار بيتأكد إنها ما تنحرف عن montage.py.
"""

JOB_VERSION = 1
JOB_KIND = "vidpattern.advanced_montage.job"

WIDTH, HEIGHT, FPS = 1080, 1920, 30            # عمودي 1080x1920 بـ 30 إطار
SAFE_BOTTOM = 0.22                              # منطقة آمنة سفلية (واجهات ميتا/تيك توك)
SAFE_SIDE = 0.06
SAFE_BOTTOM_PX = round(HEIGHT * SAFE_BOTTOM)    # 422
SAFE_SIDE_PX = round(WIDTH * SAFE_SIDE)         # 65
CAPTION_BAND_PX = 300                           # ارتفاع شريط الترجمة فوق المنطقة الآمنة
CAPTION_BAND_TOP_PX = HEIGHT - SAFE_BOTTOM_PX - CAPTION_BAND_PX   # 1198
CARD_TOP_PX = 200                               # البطاقات بتنتهي قبل شريط الترجمة بفاصل
CARD_BOTTOM_PX = CAPTION_BAND_TOP_PX - 48       # 1150

# الصوت (نفس قيم montage.py)
DUCK_DB = -14.0
DUCK_THRESHOLD = 0.02
DUCK_RATIO = 12
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 400
AHAT_FADE_IN_S = 1.0
AHAT_FADE_OUT_S = 1.5
LOUDNORM = {"I": -16, "TP": -1.5, "LRA": 11}
AUDIO_RATE = 48000

# الترجمة
CAPTION_MAX_CHARS = 24
CAPTION_MAX_WORDS = 5
CAPTION_GAP_MS = 350
CAPTION_MIN_MS = 300
CAPTION_EXTEND_MS = 250
CAPTION_PUNCT = "،,.؟?!؛;:"

# توقيت البطاقات (ملي ثانية)
CTA_MS = 3000
PRODUCT_MS = 3500
OFFER_MIN_MS = 2000
MIN_VISIBLE_MS = 1000

# التحقق
DURATION_TOLERANCE_MS = 40
MIN_FILE_BYTES = 100_000

STYLE = {"font": "IBM Plex Sans Arabic", "highlight": "#FFD54A", "direction": "rtl", "numerals": "latin"}
CTA_TEXT = "اطلب هلأ"

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
