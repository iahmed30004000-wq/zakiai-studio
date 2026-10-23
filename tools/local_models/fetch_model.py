# -*- coding: utf-8 -*-
"""تنزيل أوزان النماذج المحلية من HuggingFace (سكربت مشترك لكل نماذج جهاز أحمد).

مشترك بين سكربتات tools/local_models/ — كل سكربت .ps1 (بمشغّل .bat بجنبه) بينادي عليه بـ
--repo و --dest و --allow. القواعد:
  · الأوزان دايماً تحت models/ (مجلد متجاهَل بالنسخ الاحتياطي و git).
  · مو ثقة للكود من النت: snapshot_download بس (ملفات أوزان وإعدادات، بلا كود).
  · ما منخزّن ولا توكن: التنزيل العام بس، والموديلات المقيّدة (مثل Stable Audio)
    بدها huggingface-cli login من المالك قبلها — والتوكن بيضل بجهاز ويندوز.
  · كل الرسائل عربي (شامي)، والتقدم بالبايتات للملاحظة.
استعمال:
  python fetch_model.py --repo <repo_id> --dest <models/اسم> --allow "*.safetensors" ...
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]          # جذر المشروع (tools/local_models/ → 项目)
MODELS_DIR = REPO_ROOT / "models"

HF_API = "https://huggingface.co/api/models/{repo}"


def msg(t: str) -> None:
    """طباعة برسالة عربية واضحة (ويندوز بالـ UTF-8 عبر PYTHONIOENCODING)."""
    print(t, flush=True)


def die(t: str) -> "None":
    msg(f"⚠ {t}")
    sys.exit(1)


def hf_info(repo: str) -> dict:
    """قراءة بطاقة الموديل من واجهة HuggingFace (بس للعرض: الرخصة والحجم)."""
    try:
        with urllib.request.urlopen(HF_API.format(repo=repo), timeout=30) as r:
            return r.json()
    except Exception:                                        # noqa: BLE001 — الشبكة مش مضمونة، بس معلومات
        return {}


def check_hf_cli() -> None:
    if shutil.which("huggingface-cli") is None:
        die("huggingface-cli مش موجود. ثبّته أول شي:  pip install -U \"huggingface_hub[cli]\"")


def check_disk(gb_needed: float) -> None:
    """فحص المساحة الفاضية قبل التنزيل (بالمغير المطلوب + هامش)."""
    try:
        free = shutil.disk_usage(MODELS_DIR).free / 1e9
    except OSError:
        free = 0.0
    if free < gb_needed:
        die(f"ماكو مساحة كافية: بدي {gb_needed:.0f} غيغا وما في غير {free:.0f}. فضّي شوي ومن ثاني شغّل السكربت.")


def check_gpu(required: bool, min_vram_gb: float) -> None:
    """فحص كرت الشاشة بـ nvidia-smi (بس تنبيه — الموديل بيشتغل بالمقلوب عالـCPU لو لازم)."""
    nvidia = shutil.which("nvidia-smi")
    if nvidia is None:
        if required:
            die("ما لقيت كرت شاشة NVIDIA (nvidia-smi مش موجود). هالموديل بدّه كرت.")
        msg("تنبيه: ما في nvidia-smi — بيشتغل عالـ CPU وبيكون أبطأ بكثير.")
        return
    try:
        out = subprocess.run([nvidia, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        total = max(int(x) for x in out.splitlines()) / 1024.0 if out else 0.0
    except Exception:                                        # noqa: BLE001
        total = 0.0
    if total and total < min_vram_gb:
        msg(f"تنبيه: كرتك {total:.1f} غيغا والموديل بيحب {min_vram_gb:.0f} غيغا على الأقل — غالباً رح ينحط شي بالـ CPU ويمشي أبطأ.")
    else:
        msg(f"كرت الشاشة تمام: {total:.1f} غيغا.")


def already_done(dest: Path, min_files: int = 1, min_bytes: int = 0) -> bool:
    """إذا الأوزان منزّلة قبل هيك، منوقف بدون تنزيل (السكربتات كلها idempotent)."""
    if not dest.exists():
        return False
    files = [f for f in dest.rglob("*") if f.is_file() and f.name not in (".gitattributes", "README.md")]
    size = sum(f.stat().st_size for f in files)
    return len(files) >= min_files and size >= min_bytes


def download(repo: str, dest: Path, allow: list[str]) -> None:
    """snapshot_download بـ allow_patterns — ملفات أوزان وإعدادات بس، بلا ملفات كود."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        die("مكتبة huggingface_hub مش منثبّتة. ثبّتها:  pip install -U huggingface_hub")
    msg(f"⬇ بنزّل {repo} … (أول مرة بس، بعدين بينط من هون عالطاير)")
    snapshot_download(
        repo_id=repo,
        local_dir=str(dest),
        allow_patterns=allow,
        trust_remote_code=False,          # ما مننفّذ كود من النت أبداً — أوزان وإعدادات بس
        token=None,                        # توكن مخزّن مسبقاً (huggingface-cli login) بيمشي لحاله، مش هون
        max_workers=4,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="تنزيل أوزان نموذج من HuggingFace")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dest", required=True, help="مجلد الوجهة (دائماً تحت models/)")
    ap.add_argument("--allow", nargs="+", required=True, help="أنماط الملفات المسموحة (allow_patterns)")
    ap.add_argument("--min-gb", type=float, default=1.0, help="المساحة الفاضية المطلوبة بالغيغا")
    ap.add_argument("--need-gpu", action="store_true")
    ap.add_argument("--min-vram-gb", type=float, default=0.0)
    ap.add_argument("--gated", action="store_true", help="موديل مقيّد — بده huggingface-cli login قبل التنزيل")
    ap.add_argument("--done-files", type=int, default=1)
    ap.add_argument("--done-bytes", type=float, default=0.0, help="لو موجودها أكتر من هيك بايت، خلاص منزّل")
    a = ap.parse_args()

    dest = (REPO_ROOT / a.dest).resolve()
    if MODELS_DIR.resolve() not in dest.parents and dest != MODELS_DIR.resolve():
        die(f"الوجهة لازم تكون تحت {MODELS_DIR} — ما بنكتب أوزان برّاها.")

    msg(f"◈ {a.repo}")
    info = hf_info(a.repo)
    if info:
        lic = (info.get("cardData") or {}).get("license") or "غير مذكورة"
        size = sum((s or {}).get("size") or 0 for s in info.get("siblings", []))
        msg(f"الترخيص: {lic} · الحجم التقريبي: {size / 1e9:.1f} غيغا")

    check_disk(a.min_gb)
    if a.need_gpu:
        check_gpu(required=True, min_vram_gb=a.min_vram_gb)
    if a.gated:
        check_hf_cli()
        try:
            from huggingface_hub import whoami
            whoami()
        except Exception:                                    # noqa: BLE001 — ما حدا مسجّل دخول
            die("هالموديل مقيّد وبدّه حساب HuggingFace وعِلم عليه. افتح CMD واكتب:\n"
                "    huggingface-cli login\n"
                "وادخل الموقع وقبول الترخيص، ومن ثاني شغّل السكربت من جديد.")

    if already_done(dest, min_files=a.done_files, min_bytes=int(a.done_bytes)):
        msg("✓ الأوزان منزّلة من قبل — ما في داعي ننزّل شي.")
        return

    download(a.repo, dest, a.allow)
    if not already_done(dest, min_files=a.done_files, min_bytes=int(a.done_bytes)):
        die("التنزيل خلص بس ما لقيت الملفات المتوقعة — شوف الرسائل فوق.")
    msg(f"✓ خلص التنزيل. الأوزان بـ {dest}")


if __name__ == "__main__":
    main()
