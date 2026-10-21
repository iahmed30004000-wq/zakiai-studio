"""خلفية تجريبية: ffmpeg بيعمل تقريب بطيء على الصورة. للاختبار وللتأكد إن السلسلة كاملة شغّالة بلا كرت."""

from __future__ import annotations

import subprocess
import time

from services.engine.backends import Backend


class FakeBackend(Backend):
    name = "fake"
    tasks = ("i2v", "t2v")

    def generate(self, params, image, out, cancel) -> None:
        self.loaded = True
        if params.get("simulate_oom"):
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        if params.get("simulate_error"):
            raise RuntimeError("خطأ تجريبي")
        end = time.time() + float(params.get("sleep", 0))
        while time.time() < end:                      # محاكاة وقت التوليد، مع احترام الإلغاء
            if cancel.is_set():
                return
            time.sleep(0.05)
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
