"""
بوابة وضع المشروع — موجّه (guided: المهمة المتسلسلة المعتادة) أو حر (free: مشروع يدوي بلا ترتيب إجباري).

الوضع مخزّن بالسيناريو نفسه: `_meta.mode == "free"`. أي قيمة تانية أو ملف ناقص أو تالف = موجّه، فالبيانات القديمة
والمهمات الحالية ما بتتغيّر ولا بحرف.

بوابة الخط الزمني بتتشارك فيها كل مسارات الاستوديو (الصور، التحريك، المونتاج):
  · موجّه: صوت معتمد لنفس نص السيناريو ثم خط زمني — بنفس الرسائل والأكواد اللي كانت (409/404).
  · حر: بس الخط الزمني (ما في صوت معتمد ولا ترتيب محطات).
"""

from __future__ import annotations

import json
from pathlib import Path

import config

FREE = "free"
GUIDED = "guided"


class GateError(Exception):
    """رفض بوابة: status (HTTP) + رسالة عربية جاهزة للعرض."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def mode_of(script) -> str:
    """وضع سيناريو محمّل (dict). كل شي غير «free» صريح = موجّه."""
    if isinstance(script, dict) and (script.get("_meta") or {}).get("mode") == FREE:
        return FREE
    return GUIDED


def _stem_of(value) -> str:
    s = str(value or "")
    name = Path(s).name
    return name[:-5] if name.endswith(".json") else name


def is_free(stem_or_path) -> bool:
    """هل هالسيناريو (اسم ملف أو stem أو مسار) مشروع حر؟ ملف ناقص أو تالف = لا."""
    stem = _stem_of(stem_or_path)
    if not stem:
        return False
    p = Path(config.SCRIPTS_DIR) / f"{stem}.json"
    try:
        return mode_of(json.loads(p.read_text(encoding="utf-8"))) == FREE
    except (OSError, ValueError):
        return False


def timeline_for(path, missing_msg: str = "ما في خط زمني") -> dict:
    """الخط الزمني لسيناريو بعد بوابة الوضع. بيرمي GateError (409 صوت غير معتمد، 404 ما في خط زمني)."""
    import timeline
    p = Path(path)
    if is_free(p):
        tl = timeline.load(p.stem)
        if not tl:
            raise GateError(404, "ما في مشاهد بعد")
        return tl
    import voice_studio                      # بالاسم وقت النداء: الاختبارات بتبدّل voice_studio.voice_is_approved
    ok, why = voice_studio.voice_is_approved(p)
    if not ok:
        raise GateError(409, why)
    tl = timeline.load(p.stem)
    if not tl:
        raise GateError(404, missing_msg)
    return tl


def require_free(path) -> None:
    """للمسارات اللي بتخص المشروع الحر بس: المهمة الموجّهة بتاخد 409 واضح."""
    if not is_free(path):
        raise GateError(409, "هاد مش مشروع حر — هالأداة للمشاريع الحرة بس")


def require_guided(path, message: str = "المشروع الحر ما بينطلق للعمليات — نزّل الفيديو") -> None:
    """للمسارات اللي ما بتنفع للمشروع الحر (الإطلاق مثلاً)."""
    if is_free(path):
        raise GateError(409, message)
