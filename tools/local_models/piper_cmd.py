# -*- coding: utf-8 -*-
"""Piper — صوت عربي خفيف على المعالج (بلا كرت شاشة) — أمر تشغيل لمكتبة النماذج.

نموذج: rhasspy/piper-voices ← ar_JO/kareem/medium (صوت رجالي واحد، 22 كيلوهرتز). بيشتغل على المعالج بثواني قليلة للجملة.
الأوزان تحت models/piper-ar، والبيئة تحت third_party/piper/.venv (سكربت 5_piper.ps1 بيجهّزهم).
الرخصة: الصوت من مستودع piper-voices (MIT) بس بيانات التدريب (arabicttstrain) ما إلها رخصة معلنة ← الرخصة «غير معروفة»
وبتحتاج تأكيد المالك قبل ما تدخل مكتبة النماذج.

الربط بالاستوديو: المصنع ← النماذج ← «أمر تشغيل» ← الصوت: ["<venv>/python", "tools/local_models/piper_cmd.py", "--text-file", "{text_file}", "--out", "{out}"]
التشكيل (use_tashkeel) شغّال: بيحسّن النطق كتير لأن النص العربي العادي بلا تشكيل.
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE = REPO_ROOT / "models" / "piper-ar" / "ar" / "ar_JO" / "kareem" / "medium" / "ar_JO-kareem-medium.onnx"


def die(t: str) -> None:
    print(f"⚠ {t}", flush=True)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Piper — نص عربي لصوت")
    ap.add_argument("--text", default="")
    ap.add_argument("--text-file", default="")
    ap.add_argument("--out", required=True, help="ملف الناتج (wav)")
    ap.add_argument("--no-tashkeel", action="store_true", help="بلا تشكيل تلقائي (النص مشكّل أصلاً)")
    a = ap.parse_args()

    text = a.text
    if not text and a.text_file and Path(a.text_file).is_file():
        text = Path(a.text_file).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        die("ما في نص — بدي {text} أو {text_file} بالأمر.")
    if not VOICE.exists():
        die(f"الصوت مش موجود بـ {VOICE} — شغّل سكربت «5_piper.bat» أول شي.")

    import shutil                                             # noqa: PLC0415
    import piper                                              # noqa: PLC0415 — بعد فحص الملفات
    from piper import PiperVoice                              # noqa: PLC0415

    # مكتبة espeak-ng ما بتفتح ملفاتها من مسار فيه حروف عربية (اسم مجلد المشروع «المشروع») ← بننسخ بياناتها لمسار إنجليزي مرة وحدة
    src = Path(piper.__file__).parent / "espeak-ng-data"
    data = Path.home() / ".cache" / "zakiai-piper" / "espeak-ng-data"
    if not (data / "phontab").exists():
        shutil.copytree(src, data, dirs_exist_ok=True)
    voice = PiperVoice.load(str(VOICE), espeak_data_dir=str(data))
    voice.use_tashkeel = not a.no_tashkeel
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        voice.synthesize_wav(text, wf)
    print(f"✓ انكتب {out} ({out.stat().st_size // 1024} كيلوبايت)", flush=True)


if __name__ == "__main__":
    main()
