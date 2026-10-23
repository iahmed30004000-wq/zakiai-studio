# -*- coding: utf-8 -*-
"""Stable Audio Open 1.0 — أمر تشغيل (موسيقى ومؤثرات صوتية) بالكرت المحلي.

نموذج: stabilityai/stable-audio-open-1.0 — Stability AI Community License
(الأوزان تحت models/stable-audio-open-1.0، مش مقيّدة هنا لأنها منزّلة من قبل).

الربط بالاستوديو: المصنع ← نماذج محلية ← «أمر تشغيل»، بأماكن الملفات القياسية
({prompt} {seconds} {out}) — من model_library.PLACEHOLDERS.

بتشتغل fp16 + CPU offload (enable_model_cpu_offload) لكرت 6 غيغا.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEIGHTS = REPO_ROOT / "models" / "stable-audio-open-1.0"


def die(t: str) -> None:
    print(f"⚠ {t}", flush=True)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Stable Audio Open 1.0 — توليد صوت")
    ap.add_argument("--prompt", default="", help="نص الوصف (بدّه عالأقل شي مرة — لازم بـ {prompt})")
    ap.add_argument("--prompt-file", default="", help="ملف فيه نص الوصف (بديل --prompt)")
    ap.add_argument("--negative", default="Low quality, noisy, distorted")
    ap.add_argument("--seconds", type=float, default=30.0, help="طول الناتج بالثواني")
    ap.add_argument("--out", required=True, help="ملف الناتج (wav)")
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0, help="0 = عشوائي")
    a = ap.parse_args()

    prompt = a.prompt
    if not prompt and a.prompt_file and Path(a.prompt_file).is_file():
        prompt = Path(a.prompt_file).read_text(encoding="utf-8", errors="replace").strip()
    if not prompt:
        die("ما في نص وصف — بدي {prompt} بالأمر.")
    if not WEIGHTS.exists():
        die(f"الأوزان مش موجودة بـ {WEIGHTS} — شغّل سكربت «4_stable_audio.bat» أول شي.")

    import torch                                              # noqa: PLC0415 — بعد فحص الأوزان
    from diffusers import StableAudioPipeline                 # noqa: PLC0415

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    print("◈ شغّال Stable Audio Open 1.0 (fp16 + CPU offload)…", flush=True)

    pipe = StableAudioPipeline.from_pretrained(str(WEIGHTS), torch_dtype=torch.float16)
    pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")
    pipe.enable_model_cpu_offload()                           # كرت 6 غيغا — ننقل الأجزاء هادئة عالـ CPU
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)

    generator = None
    if a.seed:
        generator = torch.Generator(device=pipe.device).manual_seed(a.seed)

    audio = pipe(
        prompt=prompt,
        negative_prompt=a.negative,
        num_inference_steps=a.steps,
        audio_end_in_s=float(a.seconds),
        generator=generator,
    ).audios

    # الناتج tensor (batch, قنوات، عينات) ستيريو — soundfile بدّه (عينات، قنوات) فبنقلب المحاور، وبمعدّل عينات النموذج نفسه
    import soundfile as sf                                    # noqa: PLC0415
    wav = audio[0].T.float().cpu().numpy()
    sf.write(str(out), wav, int(pipe.vae.sampling_rate))
    print(f"✓ خلص. الناتج: {out}", flush=True)


if __name__ == "__main__":
    main()
