# ⚠ غير مجرَّب على كرت حقيقي — ينجرّب على السيرفر.
#   (مكتوب من التوثيق الرسمي لـ diffusers، ومفحوص بالاختبارات بخلفية وهمية بس. أول تشغيل حقيقي لازم يكون بإشراف.)
"""
قاعدة مشتركة لخلفيات diffusers (LTX وWan): تحميل كسول من مجلد أوزان محلي فقط، offload للذاكرة القليلة،
إلغاء بين الخطوات، تحويل الخرج mp4، وتفريغ الذاكرة.

الاستيراد الثقيل (torch / diffusers) كله داخل الدوال، فالملف بينقرأ بدونهم.
"""

from __future__ import annotations

from pathlib import Path

from services.engine.backends import Backend
from services.engine.backends._common import (Cancelled, encode_mp4, force_offline, frame_count, free_memory,
                                                load_image_fitted, target_size, weights_path)


class DiffusersVideoBackend(Backend):
    tasks = ("i2v", "t2v")
    weights_sub = ""                 # مجلد الأوزان تحت WEIGHTS_DIR
    multiple = 32                    # أبعاد الفيديو لازم من مضاعفاته
    frame_step = 8                   # عدد الإطارات = frame_step*k + 1
    default_fps = 24
    default_steps = 30
    default_guidance = 3.0
    default_max_pixels = 480 * 832
    default_negative = "worst quality, blurry, jittery, distorted, inconsistent motion, watermark, text"

    def __init__(self, settings):
        super().__init__(settings)
        self._pipe = None
        self._mode: str | None = None

    # ── للتخصيص بكل نموذج ──
    def _build(self, mode: str, path: Path, dtype):  # pragma: no cover - يحتاج diffusers وكرت
        raise NotImplementedError

    def _call_kwargs(self, mode: str, image, w: int, h: int, frames: int, fps: int) -> dict:
        return {}

    # ── التحميل والتفريغ ──
    def _offload_mode(self) -> str:
        m = (getattr(self.settings, "offload", "auto") or "auto").lower()
        if m in ("model", "none"):
            return m
        try:
            import torch
            total = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            return "model" if total < 30 else "none"
        except Exception:
            return "model"

    def load(self, mode: str = "i2v") -> None:  # pragma: no cover - يحتاج diffusers وكرت
        force_offline()
        import torch
        path = weights_path(self.settings.weights_dir, self.weights_sub)
        pipe = self._build(mode, path, torch.bfloat16)
        if self._offload_mode() == "model":
            pipe.enable_model_cpu_offload()          # يحرّك كل جزء للكرت وقت الحاجة بس
        else:
            pipe.to("cuda")
        try:
            pipe.vae.enable_tiling()                 # يقلّل ذروة الذاكرة وقت فك التشفير
        except Exception:
            pass
        self._pipe, self._mode, self.loaded = pipe, mode, True

    def unload(self) -> None:
        self._pipe = None
        self._mode = None
        self.loaded = False
        free_memory()

    # ── التوليد ──
    def generate(self, params, image, out, cancel) -> None:  # pragma: no cover - يحتاج diffusers وكرت
        import torch
        mode = params.get("mode", "i2v")
        if not self.loaded or self._mode != mode:
            self.unload()
            self.load(mode)
        max_px = int(getattr(self.settings, "max_pixels", 0) or self.default_max_pixels)
        w, h = target_size(params, image, max_px, self.multiple)
        fps = int(params.get("fps") or self.default_fps)
        frames = frame_count(float(params.get("seconds", 3)), fps, self.frame_step)
        steps = int(params.get("steps") or self.default_steps)
        guidance = float(params.get("guidance") if params.get("guidance") is not None else self.default_guidance)
        img = load_image_fitted(image, w, h) if (mode == "i2v" and image is not None) else None
        seed = params.get("seed")
        gen = torch.Generator(device="cpu").manual_seed(int(seed)) if seed is not None else None

        def on_step(_pipe, step, _timestep, kw):
            cancel.step, cancel.total = step + 1, steps
            if cancel.is_set():
                raise Cancelled()                     # بتوقف الاستدلال بين خطوتين
            return kw

        kwargs = dict(prompt=params.get("prompt") or "", negative_prompt=params.get("negative_prompt") or self.default_negative,
                      width=w, height=h, num_frames=frames, num_inference_steps=steps, guidance_scale=guidance,
                      generator=gen, callback_on_step_end=on_step, callback_on_step_end_tensor_inputs=["latents"],
                      output_type="pil")                # Wan بيرجّع numpy افتراضياً؛ بنثبّتها PIL (تحقّقت من تواقيع diffusers 0.36)
        kwargs.update(self._call_kwargs(mode, img, w, h, frames, fps))
        try:
            with torch.inference_mode():
                result = self._pipe(**kwargs)
        except Cancelled:
            free_memory()
            return
        if cancel.is_set():
            return
        encode_mp4(result.frames[0], fps, out)
        del result
        free_memory()
