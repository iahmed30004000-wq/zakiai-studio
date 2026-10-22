#!/usr/bin/env python3
"""
سجل النشاط — «مين عمل شو ومتى»: كل حفظ أو رفع أو توليد أو حذف أو اعتماد بيتسجّل باسم الموظف ووقته (library/activity.db).

حارس الدخول (web/auth_gate.py) بيناديه بعد كل طلب كتابة (POST/PUT/PATCH/DELETE) نجح (< 400). الوصف بالعربي من جدول RULES
(طريقة + نمط المسار ← نوع + جملة فيها أسماء من المسار). كل مسار كتابة لازم إله قاعدة هون أو يكون بقائمة SILENT (طلبات الإضافة
التقنية، فحوصات…) — اختبار بيقارن الجدول بكل مسارات التطبيق عشان ما يفلت مسار جديد بلا وصف.
أحداث الحسابات (دخول/خروج/إضافة موظف/تعطيل/تصفير) بتنسجّل صراحةً من مساراتها (record_event) فبتحمل اسم الموظف المقصود.

مثال: «سارة — رفع صورة وضعية «أمام» لمنتج kama — 9:14 م».
"""

from __future__ import annotations

import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config

KINDS = {"create": "إضافة", "edit": "تعديل", "upload": "رفع", "generate": "توليد وتشغيل", "approve": "اعتماد وقرار",
         "delete": "حذف", "settings": "إعدادات ومفاتيح", "account": "حسابات"}
MAX_LIMIT = 500
SLOT_AR = {"front": "أمام", "back": "خلف", "left": "يسار", "right": "يمين", "top": "فوق", "bottom": "تحت", "in_hand": "بيد",
           "label": "الملصق", "box_front": "العلبة من قدّام", "with_box": "المنتج مع علبته", "side": "جانب",
           "three_quarter": "ثلاثة أرباع", "full_body": "جسم كامل", "hands": "يدين"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user_id INTEGER,
    user_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    method TEXT,
    path TEXT
);
CREATE INDEX IF NOT EXISTS events_at ON events(at);
CREATE INDEX IF NOT EXISTS events_user ON events(user_id, at);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, at);
"""

# (طريقة، نمط المسار بأسماء مجموعات، النوع، الجملة). الأسماء {file} {shot} {code} {view} … من المسار نفسه.
_R = [
    # ── فيسبوك/الإعلانات
    ("PUT", r"/api/ads/meta/app", "settings", "حفظ إعدادات تطبيق فيسبوك للإعلانات"),
    ("DELETE", r"/api/ads/meta/app", "settings", "فصل تطبيق فيسبوك للإعلانات"),
    ("DELETE", r"/api/ads/meta/connection", "settings", "فصل حساب فيسبوك للإعلانات"),
    ("POST", r"/api/ads/meta/sync", "generate", "مزامنة أرقام الإعلانات من فيسبوك"),
    ("PUT", r"/api/ads/meta/token", "settings", "حفظ مفتاح فيسبوك للإعلانات"),
    # ── الآهات والموسيقى
    ("POST", r"/api/ahat", "upload", "رفع آهة أو موسيقى للمكتبة"),
    ("DELETE", r"/api/ahat/(?P<tid>[^/]+)", "delete", "حذف آهة من المكتبة ({tid})"),
    ("POST", r"/api/ahat/(?P<tid>[^/]+)/approve", "approve", "اعتماد آهة ({tid})"),
    ("POST", r"/api/ahat/(?P<tid>[^/]+)/revoke", "approve", "سحب اعتماد آهة ({tid})"),
    # ── النسخ الاحتياطي
    ("PUT", r"/api/backup/config", "settings", "حفظ إعدادات النسخ الاحتياطي"),
    ("POST", r"/api/backup/export-key", "settings", "تصدير مفتاح النسخ الاحتياطي"),
    ("POST", r"/api/backup/restore-test", "generate", "تجربة استرجاع نسخة احتياطية"),
    ("POST", r"/api/backup/run", "generate", "تشغيل نسخة احتياطية"),
    # ── الشخصيات
    ("POST", r"/api/characters", "create", "إضافة شخصية جديدة"),
    ("PUT", r"/api/characters/(?P<cid>[^/]+)", "edit", "تعديل بيانات الشخصية {cid}"),
    ("POST", r"/api/characters/(?P<cid>[^/]+)/consent", "upload", "رفع موافقة موقّعة للشخصية {cid}"),
    ("PUT", r"/api/characters/(?P<cid>[^/]+)/identity", "edit", "تعديل بطاقة الهوية الإنجليزية للشخصية {cid}"),
    ("POST", r"/api/characters/(?P<cid>[^/]+)/identity/rebuild", "generate", "إعادة بناء بطاقة الهوية للشخصية {cid}"),
    ("POST", r"/api/characters/(?P<cid>[^/]+)/lock/(?P<view>[^/]+)", "edit", "تثبيت أو فك تثبيت وضعية «{view}» للشخصية {cid}"),
    ("PUT", r"/api/characters/(?P<cid>[^/]+)/prompt/(?P<view>[^/]+)", "edit", "تعديل برومبت وضعية «{view}» للشخصية {cid}"),
    ("DELETE", r"/api/characters/(?P<cid>[^/]+)/prompt/(?P<view>[^/]+)", "edit", "إرجاع البرومبت الأصلي لوضعية «{view}» للشخصية {cid}"),
    ("POST", r"/api/characters/(?P<cid>[^/]+)/retire", "delete", "أرشفة الشخصية {cid}"),
    ("POST", r"/api/characters/(?P<cid>[^/]+)/sheet/(?P<view>[^/]+)", "upload", "رفع صورة وضعية «{view}» للشخصية {cid}"),
    ("DELETE", r"/api/characters/(?P<cid>[^/]+)/sheet/(?P<view>[^/]+)", "delete", "حذف صورة وضعية «{view}» للشخصية {cid}"),
    # ── الادعاءات الممنوعة
    ("POST", r"/api/claims/reset/(?P<group>[^/]+)", "edit", "إرجاع قواعد الادعاءات الأصلية ({group})"),
    ("POST", r"/api/claims/rules/(?P<group>[^/]+)", "create", "إضافة قاعدة ادعاءات ({group})"),
    ("PUT", r"/api/claims/rules/(?P<group>[^/]+)/(?P<rule>[^/]+)", "edit", "تعديل قاعدة ادعاءات ({group})"),
    ("DELETE", r"/api/claims/rules/(?P<group>[^/]+)/(?P<rule>[^/]+)", "delete", "حذف قاعدة ادعاءات ({group})"),
    ("POST", r"/api/compare", "generate", "مقارنة نمطين"),
    # ── الاتصالات والإعدادات والمفاتيح
    ("POST", r"/api/connections", "settings", "حفظ اتصال مزوّد ذكاء اصطناعي"),
    ("DELETE", r"/api/connections/(?P<conn>[^/]+)", "settings", "حذف اتصال مزوّد ذكاء اصطناعي"),
    ("POST", r"/api/connections/(?P<conn>[^/]+)/refresh", "settings", "تحديث قائمة موديلات اتصال"),
    ("PUT", r"/api/crm/config", "settings", "حفظ إعدادات الربط بالـ OMS"),
    ("DELETE", r"/api/crm/launch-token", "settings", "حذف توكن إطلاق الإعلانات (OMS)"),
    ("DELETE", r"/api/crm/token", "settings", "حذف توكن الـ OMS"),
    ("POST", r"/api/crm/sync", "generate", "مزامنة بيانات الـ OMS"),
    ("PUT", r"/api/ext/config", "settings", "حفظ إعدادات الإضافة"),
    ("POST", r"/api/ext/token/rotate", "settings", "تجديد توكن الإضافة"),
    ("PUT", r"/api/imagegen", "settings", "حفظ إعدادات توليد الصور"),
    ("PUT", r"/api/stt", "settings", "حفظ إعدادات التفريغ الصوتي"),
    ("PUT", r"/api/tts", "settings", "حفظ إعدادات الصوت"),
    ("PUT", r"/api/settings", "settings", "حفظ الإعدادات"),
    ("DELETE", r"/api/settings/api-key", "settings", "حذف مفتاح Claude"),
    ("PUT", r"/api/settings/spend-limits", "settings", "حفظ حدود الإنفاق"),
    ("PUT", r"/api/tasks/(?P<task>[^/]+)", "settings", "ضبط مزوّد وموديل مهمة «{task}»"),
    ("DELETE", r"/api/tasks/(?P<task>[^/]+)/key", "settings", "حذف مفتاح مهمة «{task}»"),
    ("POST", r"/api/providers/(?P<provider>[^/]+)/models", "settings", "إضافة موديل لمزوّد {provider}"),
    ("DELETE", r"/api/providers/(?P<provider>[^/]+)/models/(?P<model>.+)", "settings", "حذف موديل {model} من مزوّد {provider}"),
    ("PUT", r"/api/prompts/(?P<name>[^/]+)", "edit", "تعديل برومبت النظام «{name}»"),
    ("POST", r"/api/prompts/(?P<name>[^/]+)/restore", "edit", "إرجاع برومبت النظام «{name}» للأصلي"),
    # ── مسودات المنتجات
    ("POST", r"/api/drafts/scan", "generate", "فحص مسودات المنتجات"),
    ("POST", r"/api/drafts/(?P<draft>[^/]+)/approve", "approve", "اعتماد مسودة منتج"),
    ("POST", r"/api/drafts/(?P<draft>[^/]+)/dismiss", "delete", "استبعاد مسودة منتج"),
    # ── التحليل والتعلّم والمطابقة والكتابة
    ("POST", r"/api/extract/link", "generate", "تحليل فيديو من رابط"),
    ("POST", r"/api/extract/upload", "upload", "رفع فيديو للتحليل"),
    ("POST", r"/api/generate", "generate", "كتابة سيناريو جديد"),
    ("POST", r"/api/learn", "generate", "التعلّم من فيديو"),
    ("POST", r"/api/learning/run", "generate", "تشغيل التعلّم من الأداء"),
    ("POST", r"/api/match", "generate", "مطابقة منتج بالأنماط"),
    ("POST", r"/api/mine", "generate", "استخراج أنماط من فيديوهات"),
    ("POST", r"/api/harvest/candidates", "generate", "جلب فيديوهات مرشّحة"),
    ("POST", r"/api/harvest/plan", "generate", "خطة جلب فيديوهات"),
    ("POST", r"/api/harvest/candidates/(?P<item>[^/]+)/approve", "approve", "اعتماد فيديو مرشّح للتحليل"),
    ("POST", r"/api/harvest/candidates/(?P<item>[^/]+)/reject", "delete", "رفض فيديو مرشّح للتحليل"),
    ("POST", r"/api/queue/poll", "generate", "سحب طابور الـ OMS الآن"),
    # ── بنك الهوكات
    ("POST", r"/api/hooks-bank", "create", "إضافة هوك يدوي لبنك الهوكات"),
    ("PUT", r"/api/hooks-bank/(?P<key>[^/]+)", "edit", "تعديل هوك ببنك الهوكات"),
    ("DELETE", r"/api/hooks-bank/(?P<key>[^/]+)", "delete", "حذف هوك من بنك الهوكات"),
    ("POST", r"/api/hooks-bank/(?P<key>[^/]+)/archive", "edit", "أرشفة أو استرجاع هوك ببنك الهوكات"),
    ("POST", r"/api/hooks-bank/(?P<key>[^/]+)/star", "edit", "تنجيم هوك ببنك الهوكات"),
    # ── الصور (الخط القديم) والصوت
    ("POST", r"/api/images/(?P<file>[^/]+)", "generate", "توليد صور للسيناريو {file}"),
    ("POST", r"/api/images/(?P<file>[^/]+)/regenerate", "generate", "إعادة توليد صور للسيناريو {file}"),
    ("PUT", r"/api/images/(?P<file>[^/]+)/shot", "edit", "تعديل لقطة بصور السيناريو {file}"),
    ("POST", r"/api/voice/(?P<file>[^/]+)", "generate", "توليد صوت السيناريو {file}"),
    # ── المهام
    ("POST", r"/api/jobs/(?P<job>[^/]+)/cancel", "generate", "إلغاء مهمة {job}"),
    ("POST", r"/api/jobs/(?P<job>[^/]+)/pause", "generate", "إيقاف مؤقت لمهمة {job}"),
    ("POST", r"/api/jobs/(?P<job>[^/]+)/resume", "generate", "استئناف مهمة {job}"),
    # ── موديلات التحريك والحركات السينمائية
    ("POST", r"/api/motion-models", "create", "إضافة موديل تحريك"),
    ("PUT", r"/api/motion-models/(?P<mid>[^/]+)", "edit", "تعديل موديل تحريك {mid}"),
    ("DELETE", r"/api/motion-models/(?P<mid>[^/]+)", "delete", "حذف موديل تحريك {mid}"),
    ("PUT", r"/api/motion/api/cap", "settings", "ضبط سقف إنفاق التحريك بالـ API"),
    ("PUT", r"/api/motion/api/key", "settings", "حفظ مفتاح fal للتحريك"),
    ("DELETE", r"/api/motion/api/key", "settings", "حذف مفتاح fal للتحريك"),
    ("POST", r"/api/motion/api/preset/(?P<key>[^/]+)", "create", "إضافة موديل تحريك API جاهز ({key})"),
    ("PUT", r"/api/motion/models/(?P<mid>[^/]+)/token", "settings", "حفظ توكن صندوق موديل {mid}"),
    ("POST", r"/api/presets", "create", "إضافة حركة سينمائية جديدة"),
    ("PUT", r"/api/presets/(?P<pid>[^/]+)", "edit", "تعديل حركة سينمائية ({pid})"),
    ("DELETE", r"/api/presets/(?P<pid>[^/]+)", "delete", "حذف أو إرجاع حركة سينمائية ({pid})"),
    # ── الأنماط
    ("POST", r"/api/pattern-lib", "create", "إضافة نمط جديد"),
    ("POST", r"/api/pattern-lib/import", "upload", "رفع ملف Excel لاستيراد أنماط (معاينة)"),
    ("POST", r"/api/pattern-lib/import/commit", "create", "استيراد أنماط من Excel"),
    ("POST", r"/api/pattern-lib/translate", "generate", "ترجمة الأنماط للعربي"),
    ("PUT", r"/api/pattern-lib/(?P<pid>[^/]+)", "edit", "تعديل النمط {pid}"),
    ("POST", r"/api/pattern-lib/(?P<pid>[^/]+)/archive", "delete", "أرشفة النمط {pid}"),
    ("POST", r"/api/pattern-lib/(?P<pid>[^/]+)/restore", "edit", "استرجاع النمط {pid}"),
    # ── الأداء
    ("PUT", r"/api/performance/(?P<file>[^/]+)", "edit", "تسجيل أداء السيناريو {file}"),
    # ── المنتجات وملف المنتج المرجعي
    ("POST", r"/api/products/parse", "generate", "قراءة بيانات منتج من نص"),
    ("PUT", r"/api/products/(?P<file>[^/]+)", "edit", "حفظ ملف المنتج {file}"),
    ("DELETE", r"/api/products/(?P<file>[^/]+)", "delete", "حذف ملف المنتج {file}"),
    ("POST", r"/api/products/(?P<file>[^/]+)/facts/sync", "generate", "مزامنة حقائق المنتج {file} من الـ OMS"),
    ("PUT", r"/api/product-refs/(?P<code>[^/]+)", "edit", "تعديل بيانات المراجع البصرية لمنتج {code}"),
    ("POST", r"/api/product-refs/(?P<code>[^/]+)/angle/(?P<angle>[^/]+)", "upload", "رفع صورة وضعية «{angle}» لمنتج {code}"),
    ("DELETE", r"/api/product-refs/(?P<code>[^/]+)/angle/(?P<angle>[^/]+)", "delete", "حذف صورة وضعية «{angle}» لمنتج {code}"),
    ("POST", r"/api/product-refs/(?P<code>[^/]+)/lock/(?P<slot>[^/]+)", "edit", "تثبيت أو فك تثبيت وضعية «{slot}» لمنتج {code}"),
    ("PUT", r"/api/product-refs/(?P<code>[^/]+)/prompt/(?P<slot>[^/]+)", "edit", "تعديل برومبت وضعية «{slot}» لمنتج {code}"),
    ("DELETE", r"/api/product-refs/(?P<code>[^/]+)/prompt/(?P<slot>[^/]+)", "edit", "إرجاع البرومبت الأصلي لوضعية «{slot}» لمنتج {code}"),
    # ── المراجعة والسيناريوهات والهوكات
    ("POST", r"/api/review-queue/(?P<item>[^/]+)/resolve", "approve", "قرار على بند مراجعة تصنيف"),
    ("POST", r"/api/review/(?P<file>[^/]+)", "generate", "مراجعة السيناريو {file} بالذكاء"),
    ("POST", r"/api/review/(?P<file>[^/]+)/local", "generate", "فحص السيناريو {file} محلياً"),
    ("PUT", r"/api/scripts/(?P<file>[^/]+)", "edit", "حفظ تعديل السيناريو {file}"),
    ("POST", r"/api/scripts/(?P<file>[^/]+)/approve", "approve", "اعتماد السيناريو {file}"),
    ("POST", r"/api/scripts/(?P<file>[^/]+)/review-loop", "generate", "مراجعة وإعادة كتابة السيناريو {file}"),
    ("POST", r"/api/scripts/(?P<file>[^/]+)/hooks", "create", "توليد أو إضافة هوك للسيناريو {file}"),
    ("POST", r"/api/scripts/(?P<file>[^/]+)/hooks/select", "approve", "اختيار الهوك الأساسي للسيناريو {file}"),
    ("PUT", r"/api/scripts/(?P<file>[^/]+)/hooks/(?P<hid>[^/]+)", "edit", "تعديل هوك ({hid}) بالسيناريو {file}"),
    ("DELETE", r"/api/scripts/(?P<file>[^/]+)/hooks/(?P<hid>[^/]+)", "delete", "حذف هوك ({hid}) من السيناريو {file}"),
    ("POST", r"/api/scripts/(?P<file>[^/]+)/hooks/(?P<hid>[^/]+)/regenerate", "generate", "توليد هوك بديل ({hid}) للسيناريو {file}"),
    ("POST", r"/api/scripts/(?P<file>[^/]+)/hooks/(?P<hid>[^/]+)/version", "create", "عمل نسخة فيديو للهوك ({hid}) من السيناريو {file}"),
    # ── استوديو الإنتاج (لكل سيناريو)
    ("POST", r"/api/studio/(?P<file>[^/]+)/character", "approve", "اختيار شخصية للسيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/voice", "generate", "توليد صوت السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/voice/approve", "approve", "اعتماد صوت السيناريو {file}"),
    ("PUT", r"/api/studio/(?P<file>[^/]+)/timeline/boundary", "edit", "تعديل حد لقطة بالخط الزمني ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/build", "generate", "بناء برومبتات لقطات السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/approve", "approve", "اعتماد برومبتات لقطات السيناريو {file}"),
    ("PUT", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/prompt", "edit", "تعديل برومبت اللقطة {shot} ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/images/generate", "generate", "توليد صور لقطات السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/images/approve", "approve", "اعتماد صور السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/choose", "approve", "اختيار صورة للقطة {shot} ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/upscale", "generate", "تكبير صورة اللقطة {shot} بالذكاء ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/composite", "edit", "تركيب المنتج الحقيقي على اللقطة {shot} ({file})"),
    ("DELETE", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/composite", "edit", "شيل تركيب المنتج عن اللقطة {shot} ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/check", "generate", "فحص اللقطة {shot} (الملصق والوجه) ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/match/check", "generate", "فحص لقطات السيناريو {file} (الملصق والوجه)"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/verdict", "approve", "حكم على اللقطة {shot} ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/match/approve", "approve", "اعتماد تطابق لقطات السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/motion/run", "generate", "تحريك لقطات السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/motion/choose", "approve", "اختيار حركة للقطة {shot} ({file})"),
    ("PUT", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/motion-desc", "edit", "تعديل وصف حركة اللقطة {shot} ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/preset", "edit", "حركة سينمائية على اللقطة {shot} ({file})"),
    ("DELETE", r"/api/studio/(?P<file>[^/]+)/shots/(?P<shot>[^/]+)/preset", "edit", "شيل الحركة السينمائية عن اللقطة {shot} ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/motion/approve", "approve", "اعتماد تحريك السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/ambience", "generate", "ضبط أجواء السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/montage/render", "generate", "تصدير مونتاج السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/launch", "approve", "إطلاق إعلان من السيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/launch/cancel", "approve", "إلغاء إطلاق إعلان ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/launch/refresh", "generate", "تحديث حالة إطلاق إعلان ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/placements", "create", "ربط إعلان بمكان ({file})"),
    ("PUT", r"/api/studio/(?P<file>[^/]+)/placements/(?P<pid>[^/]+)", "edit", "تعديل مكان إعلان ({file})"),
    ("DELETE", r"/api/studio/(?P<file>[^/]+)/placements/(?P<pid>[^/]+)", "delete", "حذف مكان إعلان ({file})"),
    # ── الإضافة (من الواجهة أو من الإضافة نفسها)
    ("POST", r"/api/studio/(?P<file>[^/]+)/ext/control", "generate", "ضبط تشغيل الإضافة للسيناريو {file}"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/ext/retry", "generate", "إعادة مهمة بالإضافة ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/ext/result", "upload", "تسليم نتيجة من الإضافة ({file})"),
    ("POST", r"/api/studio/(?P<file>[^/]+)/ext/requests", "create", "طلب آهة أو موسيقى بالإضافة ({file})"),
    ("DELETE", r"/api/studio/(?P<file>[^/]+)/ext/requests/(?P<rid>[^/]+)", "delete", "حذف طلب آهة أو موسيقى ({file})"),
    # ── الحسابات نفسها (الأحداث الخاصة بتنسجّل صراحة من مساراتها؛ تغيير كلمة السر هون)
    ("POST", r"/api/auth/password", "account", "غيّر كلمة سره"),
]

# مسارات كتابة ما إلها قيمة بسجل النشاط: تقنية (الإضافة)، فحوصات، أو حسابات بتنسجّل صراحة
SILENT = [
    ("POST", r"/api/claims/try"), ("POST", r"/api/ext/diag"), ("POST", r"/api/ext/selftest"),
    ("POST", r"/api/studio/[^/]+/ext/log"), ("POST", r"/api/studio/[^/]+/ext/stop"),
    ("POST", r"/api/pattern-lib/similar"), ("POST", r"/api/motion/models/[^/]+/probe"),
    ("POST", r"/api/auth/(login|logout|setup)"), ("POST", r"/api/accounts"), ("PUT", r"/api/accounts/[^/]+/active"),
    ("POST", r"/api/accounts/[^/]+/reset"),
]

RULES = [(m, re.compile(f"^{p}$"), k, t) for m, p, k, t in _R]
SILENT_RX = [(m, re.compile(f"^{p}$")) for m, p in SILENT]


def _clean(name: str, v: str) -> str:
    v = re.sub(r"\.json$", "", v or "")
    if name in ("view", "slot", "angle"):
        return SLOT_AR.get(v, v)
    return v if len(v) <= 48 else v[:45] + "…"


def describe(method: str, path: str) -> tuple[str, str] | None:
    """(نوع، جملة) لمسار كتابة، أو None لو ما إله قاعدة (صامت أو غير معروف)."""
    from urllib.parse import unquote
    method, path = method.upper(), unquote(path)
    for m, rx, kind, text in RULES:
        if m == method:
            hit = rx.match(path)
            if hit:
                vals = {k: _clean(k, v) for k, v in hit.groupdict().items()}
                return kind, text.format(**vals)
    return None


def is_silent(method: str, path: str) -> bool:
    return any(m == method.upper() and rx.match(path) for m, rx in SILENT_RX)


def covered(method: str, path_template: str) -> bool:
    """للاختبار: هل مسار OpenAPI (مثلاً /api/ahat/{tid}) إله قاعدة أو هو صامت؟ بنعوّض {x} بقيمة تجريبية."""
    concrete = re.sub(r"\{[^}]+\}", "x1", path_template)
    return describe(method, concrete) is not None or is_silent(method, concrete)


# ── القاعدة ──────────────────────────────────────────────────────────────
def db_path() -> Path:
    return Path(config.LIBRARY_DIR) / "activity.db"


@contextmanager
def _db():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_event(user: dict | None, kind: str, label: str, method: str = "", path: str = "") -> bool:
    """حدث صريح (الحسابات…). ما بيكسر الطلب لو فشل التسجيل."""
    try:
        with _db() as con:
            con.execute("INSERT INTO events(at, user_id, user_name, kind, label, method, path) VALUES(?,?,?,?,?,?,?)",
                        (_now(), (user or {}).get("id"), (user or {}).get("display_name") or "—", kind if kind in KINDS else "edit", label[:300],
                         method, path[:300]))
        return True
    except (sqlite3.Error, OSError):
        return False


def record(user: dict | None, method: str, path: str, status: int) -> bool:
    """يسجّل طلب كتابة نجح (< 400) إلو قاعدة. بيرجّع true لو انسجّل."""
    if status >= 400 or method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    d = describe(method, path)
    if not d:
        return False
    return record_event(user, d[0], d[1], method.upper(), path)


def list_events(user_id: int | None = None, kind: str | None = None, since: str | None = None, until: str | None = None,
                limit: int = 100, offset: int = 0) -> dict:
    """since/until: تاريخ-وقت ISO UTC (الواجهة بتحوّل بداية/نهاية اليوم المحلي). الأحدث أول."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    where, args = [], []
    if user_id is not None:
        where.append("user_id=?")
        args.append(int(user_id))
    if kind:
        where.append("kind=?")
        args.append(kind)
    if since:
        where.append("at >= ?")
        args.append(since)
    if until:
        where.append("at < ?")
        args.append(until)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        with _db() as con:
            total = con.execute(f"SELECT COUNT(*) FROM events{w}", args).fetchone()[0]
            rows = con.execute(f"SELECT id, at, user_id, user_name, kind, label FROM events{w} ORDER BY id DESC LIMIT ? OFFSET ?",
                               [*args, limit, max(0, int(offset))]).fetchall()
    except sqlite3.Error:
        return {"items": [], "total": 0}
    return {"items": [{**dict(r), "kind_label": KINDS.get(r["kind"], r["kind"])} for r in rows], "total": total}


if __name__ == "__main__":
    for e in list_events(limit=30)["items"]:
        print(e["at"], e["user_name"], "—", e["label"])
