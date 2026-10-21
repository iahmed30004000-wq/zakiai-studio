"""
مكتبات CUDA 12 لـ Whisper على ويندوز (CTranslate2 بيطلب cublas64_12.dll وcudnn 9).

حزم pip الرسمية من NVIDIA (nvidia-cublas-cu12 وnvidia-cudnn-cu12) بتنزل بـ site-packages/nvidia/<اسم>/bin، لكن ويندوز ما بيلاقيها لحاله.
هون بنضيف هالمجلدات لـ PATH (وadd_dll_directory) قبل تحميل الموديل. ما بنحمّل ولا بننزّل شي: بس بنوجّه البحث لمكتبات منزّلة أصلاً.
جرّبناها بنفس العملية مع torch (BiRefNet وESRGAN) بالترتيبين بلا تعارض.
"""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_added: list[str] = []
_done = False


def _site_dirs() -> list[Path]:
    dirs = [Path(p) for p in site.getsitepackages()]
    try:
        dirs.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    dirs += [Path(p) for p in sys.path if p.endswith("site-packages")]
    seen, out = set(), []
    for d in dirs:
        if str(d) not in seen:
            seen.add(str(d))
            out.append(d)
    return out


def register() -> list[str]:
    """بيرجّع المجلدات اللي انضافت (فاضي على غير ويندوز أو لو الحزم مش منزّلة). آمن لو انندهى أكتر من مرة."""
    global _done
    if _done or os.name != "nt":
        return list(_added)
    _done = True
    for sp in _site_dirs():
        root = sp / "nvidia"
        if not root.is_dir():
            continue
        for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
            b = root / sub / "bin"
            if b.is_dir() and str(b) not in _added:
                try:
                    os.add_dll_directory(str(b))
                except (OSError, AttributeError):
                    pass
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
                _added.append(str(b))
    return list(_added)
