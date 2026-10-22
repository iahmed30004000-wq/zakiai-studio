"""خلفية تجريبية: ffmpeg بيعمل تقريب بطيء على الصورة. للاختبار وللتأكد إن السلسلة كاملة شغّالة بلا كرت."""

from __future__ import annotations

import hashlib
import subprocess
import time

from services.engine.backends import Backend


class FakeBackend(Backend):
    name = "fake"
    tasks = ("i2v", "t2v")

    def _hooks(self, params, cancel) -> bool:
        """خطّافات الاختبار (انهيار/خطأ/بطء). False = انلغت المهمة وإحنا بنستنى."""
        self.loaded = True
        if params.get("simulate_oom"):
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        if params.get("simulate_error"):
            raise RuntimeError("خطأ تجريبي")
        end = time.time() + float(params.get("sleep", 0))
        while time.time() < end:                      # محاكاة وقت التوليد، مع احترام الإلغاء
            if cancel.is_set():
                return False
            time.sleep(0.05)
        return True

    def generate(self, params, image, out, cancel) -> None:
        if not self._hooks(params, cancel):
            return
        sec = float(params.get("seconds", 3))
        fps = int(params.get("fps", 24))
        w, h = int(params.get("width", 270)), int(params.get("height", 480))
        w, h = w - w % 2, h - h % 2
        if image is not None:
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-vf",
                   f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                   f"zoompan=z='min(zoom+0.0015,1.3)':d={int(sec * fps)}:s={w}x{h}:fps={fps},format=yuv420p",
                   "-t", f"{sec:.3f}", str(out)]
        else:
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={sec:.3f}:r={fps}", "-pix_fmt", "yuv420p", str(out)]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg فشل بالخلفية التجريبية")


class FakeImagesBackend(FakeBackend):
    """نسخة تجريبية من الصندوق العام (عقد v2): توليد صور، تعديل صور (مع مراجع)، تكبير، فيديو، وصوت (نغمة) — كله بلا كرت.
    للاختبار، ولتجربة السلسلة كاملة بجهازك: ENGINE_BACKEND=fake-images. النماذج وهمية (demo-*)."""

    name = "fake-images"
    tasks = ("t2i", "i2i", "upscale", "t2v", "i2v", "t2a")
    MODELS = {                                        # الاسم ← (النوع، الأنماط)
        "demo-image": ("image", ["t2i", "i2i"]),
        "demo-video": ("video", ["t2v", "i2v"]),
        "demo-audio": ("audio", ["t2a"]),
        "upscale-demo": ("image", ["upscale"]),
    }
    REJECTED = {"demo-unsafe": "فيه ملفات غير آمنة: model.bin — أوزان safetensors بس (pickle بيشغّل كود لما ينفتح)"}

    def __init__(self, settings):
        super().__init__(settings)
        self._model: str | None = None

    @property
    def loaded_model(self) -> str | None:
        return self._model

    def unload(self) -> None:
        self._model = None
        super().unload()

    def list_models(self, refresh: bool = False) -> list[dict]:
        ok = [{"name": n, "kind": kind, "pipeline": "FakePipeline", "family": "fake", "tasks": list(modes), "size_gb": 0.01,
               "licence": {"id": "apache-2.0", "commercial": "yes"}, "ok": True, "reason": "", "note": "نموذج وهمي للتجربة"}
              for n, (kind, modes) in self.MODELS.items()]
        bad = [{"name": n, "kind": "image", "pipeline": "FakePipeline", "family": "fake", "tasks": [], "size_gb": 0.01,
                "licence": {"id": "غير معروفة", "commercial": "unknown"}, "ok": False, "reason": why, "note": ""}
               for n, why in self.REJECTED.items()]
        return ok + bad

    def validate_params(self, p: dict) -> dict:
        name = p.get("model")
        if not name:
            raise ValueError("لازم تحدد النموذج (model) — شوف GET /models")
        if name in self.REJECTED:
            raise ValueError(f"النموذج «{name}» مرفوض: {self.REJECTED[name]}")
        if name not in self.MODELS:
            raise ValueError(f"النموذج «{name}» مش موجود بمجلد الأوزان")
        modes = self.MODELS[name][1]
        if p["mode"] not in modes:
            raise ValueError(f"النموذج «{name}» ما بيدعم النمط {p['mode']} (بيدعم: {'، '.join(modes)})")
        return p

    def _tone(self, params, out) -> None:
        """صوت وهمي: نغمة ستيريو بمدة الطلب، ونغمتها من وصفه (وصفين مختلفين = صوتين مختلفين)."""
        import numpy as np
        from services.engine.backends._common import write_wav
        rate = 8000
        t = np.arange(int(float(params.get("seconds", 3)) * rate)) / rate
        hz = 220 + hashlib.sha1(str(params.get("prompt") or "").encode("utf-8")).digest()[0]
        tone = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        write_wav(np.stack([tone, tone]), rate, out)

    def generate(self, params, image, out, cancel) -> None:
        mode = params["mode"]
        if mode in ("t2v", "i2v"):
            self._model = params["model"]
            return super().generate(params, image, out, cancel)
        if not self._hooks(params, cancel):
            return
        self._model = params["model"]
        if mode == "t2a":
            return self._tone(params, out)
        from PIL import Image, ImageDraw, PngImagePlugin
        info = PngImagePlugin.PngInfo()
        info.add_text("model", str(params["model"]))
        info.add_text("mode", mode)
        info.add_text("prompt", str(params.get("prompt") or ""))
        if mode == "upscale":
            scale = int(params.get("scale") or 4)
            with Image.open(image) as im:
                big = im.convert("RGB").resize((im.width * scale, im.height * scale), Image.LANCZOS)
            info.add_text("scale", str(scale))
            big.save(out, "PNG", pnginfo=info)
            return
        w, h = int(params.get("width") or 128), int(params.get("height") or 224)
        if mode == "i2i":
            with Image.open(image) as im:
                base = im.convert("RGB").resize((w, h)) if params.get("width") else im.convert("RGB")
            refs = 1 + sum(1 for k in ("_image2", "_image3") if params.get(k))
            info.add_text("refs", str(refs))
            info.add_text("strength", str(params.get("strength")))
            d = ImageDraw.Draw(base)
            d.rectangle([0, 0, max(2, base.width * refs // 3), 6], fill=(255, 0, 0))      # شريط بيبيّن كم صورة وصلت
            base.save(out, "PNG", pnginfo=info)
            return
        seed = hashlib.sha1(str(params.get("prompt") or "").encode("utf-8")).digest()
        im = Image.new("RGB", (w, h), (seed[0], seed[1], seed[2]))
        ImageDraw.Draw(im).rectangle([w // 4, h // 4, w * 3 // 4, h * 3 // 4], fill=(seed[3], seed[4], seed[5]))
        im.save(out, "PNG", pnginfo=info)
