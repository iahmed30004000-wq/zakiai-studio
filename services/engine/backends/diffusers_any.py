# ⚠ غير مجرَّب على كرت حقيقي — ينجرّب على السيرفر.
#   (مكتوب من التوثيق الرسمي لـ diffusers، ومفحوص بالاختبارات بـ diffusers مزيّف. أول تشغيل حقيقي لازم يكون بإشراف.)
"""
الصندوق العام: أي أوزان diffusers بمجلد WEIGHTS_DIR (صور، تعديل صور، فيديو، وصوت: Stable Audio) + ملفات التكبير بمجلد upscale/.

  · الاكتشاف والحماية والتلميحات بـ _introspect.py (بلا torch). هون التحميل والتشغيل بس.
  · نموذج وحدة محمّل بكل لحظة: طلب لنموذج تاني بيفرّغ الحالي أول (الذاكرة).
  · الأوزان من مجلد محلي بس: local_files_only، use_safetensors=True (أي pickle بيفشل)، وما بنمرّر trust_remote_code أبداً.
  · الإلغاء بين الخطوات (callback_on_step_end) وتقدّم الخطوات للصندوق.

الاستيراد الثقيل (torch / diffusers) كله داخل الدوال، فالملف بينقرأ بدونهم.
"""

from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path

from services.engine.backends import Backend
from services.engine.backends import _introspect as intro
from services.engine.backends._common import Cancelled, encode_mp4, fit_resolution, force_offline, free_memory, write_wav

SCAN_TTL_SEC = 30.0


class DiffusersAnyBackend(Backend):
    name = "diffusers"
    tasks = ("t2i", "i2i", "upscale", "t2v", "i2v", "t2a")

    def __init__(self, settings):
        super().__init__(settings)
        self._pipe = None
        self._loaded_model: str | None = None
        self._loaded_mode: str | None = None
        self._sig: set[str] | None = None
        self._scan: list[intro.ModelInfo] = []
        self._scan_at = 0.0
        self._lock = threading.Lock()

    # ── الاكتشاف ──
    @property
    def loaded_model(self) -> str | None:
        return self._loaded_model

    def models(self, refresh: bool = False) -> list[intro.ModelInfo]:
        with self._lock:
            if refresh or not self._scan_at or time.monotonic() - self._scan_at > SCAN_TTL_SEC:
                self._scan, self._scan_at = intro.discover(self.settings.weights_dir), time.monotonic()
            return list(self._scan)

    def list_models(self, refresh: bool = False) -> list[dict]:
        return [m.public() for m in self.models(refresh)]

    def info_for(self, name: str) -> intro.ModelInfo | None:
        found = next((m for m in self.models() if m.name == name), None)
        return found or next((m for m in self.models(True) if m.name == name), None)

    def validate_params(self, p: dict) -> dict:
        """يتأكد قبل ما المهمة تنقبل: النموذج موجود وصالح وبيدعم النمط، وextra سليم. ValueError بسبب عربي (الخدمة بتحوّله 400)."""
        name = p.get("model")
        if not name:
            raise ValueError("لازم تحدد النموذج (model) — شوف GET /models")
        info = self.info_for(name)
        if info is None:
            raise ValueError(f"النموذج «{name}» مش موجود بمجلد الأوزان")
        if not info.ok:
            raise ValueError(f"النموذج «{name}» مرفوض: " + ("؛ ".join(info.problems) or "ما فهمنا أنماطه"))
        if p["mode"] not in info.modes:
            raise ValueError(f"النموذج «{name}» ما بيدعم النمط {p['mode']} (بيدعم: {'، '.join(info.modes)})")
        intro.clean_extra(p.get("extra"))
        return p

    # ── الذاكرة ──
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

    def unload(self) -> None:
        self._pipe, self._loaded_model, self._loaded_mode, self._sig = None, None, None, None
        self.loaded = False
        try:
            from services.engine.backends import _upscale
            _upscale.clear()
        except Exception:
            pass
        free_memory()

    def _build(self, info: intro.ModelInfo, mode: str):  # pragma: no cover - يحتاج diffusers وكرت
        import diffusers
        import torch
        spec = intro.spec_for(info.pipeline)
        cls_name = spec["modes"][mode]
        cls = getattr(diffusers, cls_name, None)
        if cls is None:
            raise RuntimeError(f"نسخة diffusers بالصندوق ما فيها {cls_name} — حدّث الصورة")
        kw = dict(torch_dtype=getattr(torch, spec.get("dtype") or "bfloat16"), local_files_only=True, use_safetensors=True)
        if spec["family"] == "wan":                   # VAE بـ float32 (توصية التوثيق)
            vae = diffusers.AutoencoderKLWan.from_pretrained(info.path, subfolder="vae", torch_dtype=torch.float32, local_files_only=True, use_safetensors=True)
            kw["vae"] = vae
        pipe = cls.from_pretrained(info.path, **kw)
        if self._offload_mode() == "model":
            pipe.enable_model_cpu_offload()           # يحرّك كل جزء للكرت وقت الحاجة بس
        else:
            pipe.to("cuda")
        try:
            pipe.vae.enable_tiling()                  # يقلّل ذروة الذاكرة وقت فك التشفير
        except Exception:
            pass
        return pipe

    def load(self, info: intro.ModelInfo, mode: str) -> None:
        force_offline()
        self.unload()
        self._pipe = self._build(info, mode)
        self._loaded_model, self._loaded_mode, self.loaded = info.name, mode, True
        try:                                           # أسماء معاملات __call__ الصريحة: اللي مش فيها ما بنبعتو
            params = inspect.signature(type(self._pipe).__call__).parameters.values()
            self._sig = {q.name for q in params if q.kind not in (q.VAR_POSITIONAL, q.VAR_KEYWORD)} or None
        except (TypeError, ValueError):
            self._sig = None

    # ── التوليد ──
    def generate(self, params, image, out, cancel) -> None:
        info = self.info_for(params["model"])
        if info is None or not info.ok:
            raise RuntimeError("النموذج مش جاهز")
        mode = params["mode"]
        if mode == "upscale":
            return self._upscale(info, params, image, out, cancel)
        if not self.loaded or self._loaded_model != info.name or self._loaded_mode != mode:
            self.load(info, mode)
        import torch
        spec = intro.spec_for(info.pipeline)
        imgs = self._images(mode, spec, params, image)
        plan = intro.plan_call(spec, mode, self._sig, params, imgs, max_pixels=int(getattr(self.settings, "max_pixels", 0) or 0), model_name=info.name)
        kwargs = dict(plan.kwargs)
        seed = params.get("seed")
        if seed is not None:
            kwargs["generator"] = torch.Generator(device="cpu").manual_seed(int(seed))
        if self._sig is None or "callback_on_step_end" in self._sig:
            def on_step(_pipe, step, _timestep, kw):
                cancel.step, cancel.total = step + 1, plan.steps
                if cancel.is_set():
                    raise Cancelled()                 # بتوقف الاستدلال بين خطوتين
                return kw
            kwargs["callback_on_step_end"] = on_step
            if self._sig is None or "callback_on_step_end_tensor_inputs" in self._sig:
                kwargs["callback_on_step_end_tensor_inputs"] = ["latents"]
        elif "callback" in self._sig:                 # pipelines أقدم (Stable Audio): callback(step, timestep, latents) بعد كل خطوة
            def on_step_legacy(step, _timestep, _latents):
                cancel.step, cancel.total = step + 1, plan.steps
                if cancel.is_set():
                    raise Cancelled()
            kwargs["callback"] = on_step_legacy
            if "callback_steps" in self._sig:
                kwargs["callback_steps"] = 1
        try:
            with torch.inference_mode():
                result = self._pipe(**kwargs)
        except Cancelled:
            free_memory()
            return
        if cancel.is_set():
            return
        if plan.kind == "video":
            encode_mp4(result.frames[0], plan.fps, out)
        elif plan.kind == "audio":
            vae = self._pipe.vae
            rate = getattr(getattr(vae, "config", None), "sampling_rate", None) or getattr(vae, "sampling_rate", None) or 44100
            write_wav(result.audios[0], int(rate), out)
        else:
            result.images[0].save(out, "PNG")
        del result
        free_memory()

    def _images(self, mode: str, spec: dict, params: dict, image) -> list:
        """صور الطلب (الأولى + image2/image3 الداخلية) كصور PIL جاهزة للنموذج."""
        paths = [p for p in [image, params.get("_image2"), params.get("_image3")] if p]
        if mode not in ("i2v", "i2i") or not paths:
            return []
        from PIL import Image, ImageOps
        out = []
        mp = int(getattr(self.settings, "max_pixels", 0) or spec["max_pixels"])
        for p in paths[: spec.get("max_images", 1)]:
            with Image.open(p) as im:
                img = ImageOps.exif_transpose(im).convert("RGB")
            if mode == "i2i" and img.width * img.height > mp:                   # pipelines التعديل بلا width/height ما بتصغّر: صورة 64 ميغابكسل = ذاكرة الكرت تخلص
                w, h = fit_resolution(img.width, img.height, mp, spec["multiple"])
                img = img.resize((w, h), Image.LANCZOS)
            out.append(img)
        if mode == "i2v":                              # الفيديو بياخد الصورة بمقاس الهدف (قص من النص) — plan_call بيحسب المقاس من الصورة نفسها
            return out[:1]
        return out

    def _upscale(self, info: intro.ModelInfo, params: dict, image, out, cancel) -> None:
        from services.engine.backends import _upscale
        if image is None:
            raise RuntimeError("التكبير بدّه صورة")
        if self._pipe is not None:                     # نموذج وحدة محمّل بكل لحظة
            self.unload()
        self.loaded, self._loaded_model, self._loaded_mode = True, info.name, "upscale"
        _upscale.upscale_file(Path(info.path), Path(image), Path(out), int(params.get("scale") or 4),
                              int(getattr(self.settings, "upscale_max_pixels", 0) or 64_000_000), cancel)
