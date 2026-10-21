# ⚠ غير مجرَّب على كرت حقيقي — ينجرّب على السيرفر.
"""
خلفية Wan2.2-TI2V-5B عبر diffusers: WanImageToVideoPipeline (صورة لفيديو) وWanPipeline (نص لفيديو).

الأوزان: WEIGHTS_DIR/Wan2.2-TI2V-5B-Diffusers (صيغة diffusers، مش الصيغة الأصلية اللي بدها generate.py).
قيم افتراضية من إعداد Wan2.2-TI2V-5B: 24 إطار بالثانية، توجيه 5، عدد الإطارات 4k+1، أبعاد من مضاعفات 32 (VAE ×16 مع patch ×2).
الـ VAE بيتحمّل float32 (توصية التوثيق)، والباقي bfloat16.
"""

from __future__ import annotations

from pathlib import Path

from services.engine.backends._diffusers import DiffusersVideoBackend


class WanBackend(DiffusersVideoBackend):
    name = "wan"
    weights_sub = "Wan2.2-TI2V-5B-Diffusers"
    multiple = 32
    frame_step = 4
    default_fps = 24
    default_steps = 30
    default_guidance = 5.0
    default_max_pixels = 480 * 832
    default_negative = "worst quality, low quality, blurry, static, distorted hands, extra fingers, watermark, text, subtitles"

    def _build(self, mode: str, path: Path, dtype):  # pragma: no cover - يحتاج diffusers وكرت
        import torch
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, WanPipeline
        vae = AutoencoderKLWan.from_pretrained(str(path), subfolder="vae", torch_dtype=torch.float32, local_files_only=True)
        cls = WanImageToVideoPipeline if mode == "i2v" else WanPipeline
        return cls.from_pretrained(str(path), vae=vae, torch_dtype=dtype, local_files_only=True)

    def _call_kwargs(self, mode, image, w, h, frames, fps):
        return {"image": image} if mode == "i2v" else {}
