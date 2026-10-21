# ⚠ غير مجرَّب على كرت حقيقي — ينجرّب على السيرفر.
"""
خلفية LTX-Video (نسخة 2B) عبر diffusers: LTXImageToVideoPipeline (صورة لفيديو) وLTXPipeline (نص لفيديو).

الأوزان: WEIGHTS_DIR/LTX-Video (نسخة Lightricks/LTX-Video بصيغة diffusers). ترخيص الأوزان «other» — راجعه قبل أي استخدام تجاري.
قيم افتراضية من توثيق LTX: توجيه 3–3.5، عدد الإطارات 8k+1، أبعاد من مضاعفات 32، 24 إطار بالثانية.
"""

from __future__ import annotations

from pathlib import Path

from services.engine.backends._diffusers import DiffusersVideoBackend


class LtxBackend(DiffusersVideoBackend):
    name = "ltx"
    weights_sub = "LTX-Video"
    multiple = 32
    frame_step = 8
    default_fps = 24
    default_steps = 40
    default_guidance = 3.0
    default_max_pixels = 480 * 864

    def _build(self, mode: str, path: Path, dtype):  # pragma: no cover - يحتاج diffusers وكرت
        from diffusers import LTXImageToVideoPipeline, LTXPipeline
        cls = LTXImageToVideoPipeline if mode == "i2v" else LTXPipeline
        return cls.from_pretrained(str(path), torch_dtype=dtype, local_files_only=True)

    def _call_kwargs(self, mode, image, w, h, frames, fps):
        kw = {"frame_rate": fps}
        if mode == "i2v":
            kw["image"] = image
        return kw
