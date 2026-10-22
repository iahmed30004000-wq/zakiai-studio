"""الصندوق العام (services/engine/backends/diffusers_any.py + _upscale.py) بـ diffusers مزيّف: كلاسات pipeline بنفس تواقيع __call__ الحقيقية.
torch الحقيقي (مولّد seed وinference_mode) لكن بلا كرت ولا أوزان. تحميل حقيقي على كرت = تجربة السيرفر."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import types
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.dirname(__file__))

torch = pytest.importorskip("torch")
from PIL import Image  # noqa: E402
from test_introspect import GOOD_COMPONENTS, SA_FILES, STABLE_AUDIO, make_model  # noqa: E402

from services.engine.app import CancelEvent, Settings  # noqa: E402
from services.engine.backends import _upscale, get_backend  # noqa: E402
from services.engine.backends.diffusers_any import DiffusersAnyBackend  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def install_fake_diffusers(monkeypatch, calls: list, *, wan_numpy=False):
    mod = types.ModuleType("diffusers")

    class Base:
        def __init__(self, path, kw):
            self.path, self.kw, self.offloaded, self.device = path, kw, False, None
            self.vae = types.SimpleNamespace(enable_tiling=lambda: calls.append(("tiling", type(self).__name__)))

        @classmethod
        def from_pretrained(cls, path, **kw):
            calls.append(("load", cls.__name__, Path(path).name, kw))
            return cls(path, kw)

        def to(self, dev):
            self.device = dev
            return self

        def enable_model_cpu_offload(self):
            self.offloaded = True

        def _steps(self, n, cb, tensors):
            for i in range(n):
                if cb is not None:
                    cb(self, i, 0, {k: None for k in (tensors or [])})

    class QwenImagePipeline(Base):
        def __call__(self, prompt=None, negative_prompt=None, true_cfg_scale=4.0, height=None, width=None, num_inference_steps=50, generator=None,
                     output_type="pil", callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, max_sequence_length=512):
            calls.append(("call", "QwenImagePipeline", dict(prompt=prompt, negative_prompt=negative_prompt, true_cfg_scale=true_cfg_scale, height=height, width=width,
                                                           num_inference_steps=num_inference_steps, generator=generator, output_type=output_type,
                                                           max_sequence_length=max_sequence_length)))
            self._steps(num_inference_steps, callback_on_step_end, callback_on_step_end_tensor_inputs)
            return types.SimpleNamespace(images=[Image.new("RGB", (width or 64, height or 64), (9, 99, 199))])

    class QwenImageEditPlusPipeline(Base):
        def __call__(self, image=None, prompt=None, negative_prompt=None, true_cfg_scale=4.0, height=None, width=None, num_inference_steps=40,
                     generator=None, output_type="pil", callback_on_step_end=None, callback_on_step_end_tensor_inputs=None):
            n = len(image) if isinstance(image, list) else 1
            calls.append(("call", "QwenImageEditPlusPipeline", dict(refs=n, size=(width, height), prompt=prompt)))
            self._steps(num_inference_steps, callback_on_step_end, callback_on_step_end_tensor_inputs)
            first = image[0] if isinstance(image, list) else image
            return types.SimpleNamespace(images=[first.copy()])

    class WanPipeline(Base):
        def __call__(self, prompt=None, negative_prompt=None, height=480, width=832, num_frames=81, num_inference_steps=50, guidance_scale=5.0, generator=None,
                     output_type="np", callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, max_sequence_length=512):
            calls.append(("call", type(self).__name__, dict(width=width, height=height, num_frames=num_frames, output_type=output_type, steps=num_inference_steps)))
            self._steps(num_inference_steps, callback_on_step_end, callback_on_step_end_tensor_inputs)
            if output_type == "pil" and not wan_numpy:
                frames = [Image.new("RGB", (width, height), (i * 3 % 255, 50, 80)) for i in range(num_frames)]
            else:
                import numpy as np
                frames = np.full((num_frames, height, width, 3), 0.4, dtype=np.float32)
            return types.SimpleNamespace(frames=[frames])

    class WanImageToVideoPipeline(WanPipeline):
        def __call__(self, image=None, prompt=None, negative_prompt=None, height=480, width=832, num_frames=81, num_inference_steps=50, guidance_scale=5.0,
                     generator=None, output_type="np", callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, max_sequence_length=512):
            calls.append(("image", type(image).__name__, image.size))
            return WanPipeline.__call__(self, prompt=prompt, negative_prompt=negative_prompt, height=height, width=width, num_frames=num_frames,
                                        num_inference_steps=num_inference_steps, generator=generator, output_type=output_type,
                                        callback_on_step_end=callback_on_step_end, callback_on_step_end_tensor_inputs=callback_on_step_end_tensor_inputs)

    class FluxPipeline(Base):
        def __call__(self, prompt=None, height=None, width=None, num_inference_steps=28, guidance_scale=3.5, generator=None, output_type="pil",
                     callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, max_sequence_length=512):
            calls.append(("call", "FluxPipeline", dict(steps=num_inference_steps, guidance=guidance_scale, max_sequence_length=max_sequence_length)))
            self._steps(num_inference_steps, callback_on_step_end, callback_on_step_end_tensor_inputs)
            return types.SimpleNamespace(images=[Image.new("RGB", (width or 32, height or 32), (200, 10, 10))])

    class StableAudioPipeline(Base):
        def __init__(self, path, kw):
            super().__init__(path, kw)
            self.vae = types.SimpleNamespace(config=types.SimpleNamespace(sampling_rate=16000))          # AutoencoderOobleck: بلا enable_tiling

        def __call__(self, prompt=None, audio_end_in_s=None, audio_start_in_s=0.0, num_inference_steps=100, guidance_scale=7.0, negative_prompt=None,
                     num_waveforms_per_prompt=1, eta=0.0, generator=None, output_type="pt", callback=None, callback_steps=1):
            calls.append(("call", "StableAudioPipeline", dict(prompt=prompt, seconds=audio_end_in_s, steps=num_inference_steps, guidance=guidance_scale, negative=negative_prompt,
                                                              output_type=output_type, generator=generator, callback_steps=callback_steps)))
            for i in range(num_inference_steps):
                if callback is not None and i % callback_steps == 0:
                    callback(i, 0, None)                                  # نفس تحقيق diffusers القديم: callback(step, timestep, latents)
            import numpy as np
            return types.SimpleNamespace(audios=[np.full((2, int(audio_end_in_s * 16000)), 0.25, dtype=np.float32)])

    class AutoencoderKLWan:
        @classmethod
        def from_pretrained(cls, path, **kw):
            calls.append(("vae", Path(path).name, kw.get("subfolder"), str(kw.get("torch_dtype"))))
            return object()

    for c in (QwenImagePipeline, QwenImageEditPlusPipeline, WanPipeline, WanImageToVideoPipeline, FluxPipeline, StableAudioPipeline, AutoencoderKLWan):
        setattr(mod, c.__name__, c)
    monkeypatch.setitem(sys.modules, "diffusers", mod)
    return mod


@pytest.fixture
def box(tmp_path, monkeypatch):
    calls: list = []
    install_fake_diffusers(monkeypatch, calls)
    weights = tmp_path / "weights"
    make_model(weights, "Qwen-Image", "QwenImagePipeline")
    make_model(weights, "Qwen-Image-Edit-2509", "QwenImageEditPlusPipeline")
    make_model(weights, "Wan2.2-TI2V-5B-Diffusers", "WanPipeline", components={**GOOD_COMPONENTS, "expand_timesteps": True})
    make_model(weights, "FLUX.1-schnell", "FluxPipeline")
    make_model(weights, "Pickled", "FluxPipeline", files=("a.safetensors", "b.bin"))
    make_model(weights, "stable-audio-open-1.0", "StableAudioPipeline", components=STABLE_AUDIO, files=SA_FILES)
    s = Settings(backend="diffusers", name="e", outputs=tmp_path / "o", lock_dir=tmp_path / "l", weights_dir=weights, offload="none")
    be = DiffusersAnyBackend(s)
    return types.SimpleNamespace(be=be, calls=calls, weights=weights, tmp=tmp_path, settings=s)


def save_png(path: Path, size=(40, 60), color=(5, 5, 5)) -> Path:
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def last_call(calls, cls):
    return [c for c in calls if c[0] == "call" and c[1] == cls][-1][2]


# ── الاكتشاف والتحقق ──────────────────────────────────────────────────────
def test_registered_as_the_diffusers_backend_and_lists_models_with_reasons(box):
    assert get_backend("diffusers", box.settings).name == "diffusers"
    names = {m["name"]: m for m in box.be.list_models()}
    assert set(names) == {"Qwen-Image", "Qwen-Image-Edit-2509", "Wan2.2-TI2V-5B-Diffusers", "FLUX.1-schnell", "Pickled", "stable-audio-open-1.0"}
    assert names["stable-audio-open-1.0"]["ok"] and names["stable-audio-open-1.0"]["kind"] == "audio" and names["stable-audio-open-1.0"]["tasks"] == ["t2a"]
    assert names["Pickled"]["ok"] is False and "b.bin" in names["Pickled"]["reason"]
    assert names["Qwen-Image-Edit-2509"]["tasks"] == ["i2i"] and names["Wan2.2-TI2V-5B-Diffusers"]["tasks"] == ["t2v", "i2v"]


def test_validation_checks_model_state_and_mode_before_a_job_is_accepted(box):
    v = box.be.validate_params
    assert v({"mode": "t2i", "model": "Qwen-Image"})["model"] == "Qwen-Image"
    assert v({"mode": "t2a", "model": "stable-audio-open-1.0"})["model"] == "stable-audio-open-1.0"
    for params, needle in (({"mode": "t2i"}, "لازم تحدد"), ({"mode": "t2i", "model": "Nope"}, "مش موجود"), ({"mode": "t2i", "model": "Pickled"}, "مرفوض"),
                           ({"mode": "i2v", "model": "Qwen-Image"}, "ما بيدعم النمط"), ({"mode": "t2i", "model": "stable-audio-open-1.0"}, "ما بيدعم النمط"), ({"mode": "t2i", "model": "Qwen-Image", "extra": {"prompt": "x"}}, "محجوز")):
        with pytest.raises(ValueError, match=needle):
            v(params)


def test_a_model_downloaded_after_startup_is_found_without_restart(box):
    assert "Late" not in [m["name"] for m in box.be.list_models()]
    make_model(box.weights, "Late", "FluxPipeline")
    assert box.be.validate_params({"mode": "t2i", "model": "Late"})["model"] == "Late"        # الاسم مش بالكاش: مسح تاني تلقائي
    assert "Late" in [m["name"] for m in box.be.list_models(refresh=True)]


# ── التوليد ──────────────────────────────────────────────────────────────
def test_text_to_image_loads_offline_safetensors_only_calls_with_hints_and_saves_png(box):
    out = box.tmp / "r.png"
    cancel = CancelEvent()
    box.be.generate({"mode": "t2i", "model": "Qwen-Image", "prompt": "عطر", "width": 768, "height": 1344, "seed": 7, "steps": 3}, None, out, cancel)
    assert Image.open(out).size == (768, 1344) and box.be.loaded and box.be.loaded_model == "Qwen-Image"
    load = next(c for c in box.calls if c[0] == "load")
    assert load[1] == "QwenImagePipeline" and load[2] == "Qwen-Image"
    kw = load[3]
    assert kw["local_files_only"] is True and kw["use_safetensors"] is True and "trust_remote_code" not in kw
    assert os.environ.get("HF_HUB_OFFLINE") == "1" and os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    call = last_call(box.calls, "QwenImagePipeline")
    assert call["num_inference_steps"] == 3 and call["true_cfg_scale"] == 4.0 and call["negative_prompt"] == " " and call["output_type"] == "pil"
    assert call["generator"].initial_seed() == 7 and (call["width"], call["height"]) == (768, 1344)
    assert (cancel.step, cancel.total) == (3, 3)                              # تقدّم الخطوات بيوصل للخدمة
    assert any(c[0] == "tiling" for c in box.calls)


def test_schnell_defaults_and_one_loaded_model_at_a_time(box):
    box.be.generate({"mode": "t2i", "model": "Qwen-Image", "prompt": "x", "steps": 1}, None, box.tmp / "a.png", CancelEvent())
    first = box.be._pipe
    box.be.generate({"mode": "t2i", "model": "FLUX.1-schnell", "prompt": "x"}, None, box.tmp / "b.png", CancelEvent())
    assert box.be._pipe is not first and box.be.loaded_model == "FLUX.1-schnell"
    call = last_call(box.calls, "FluxPipeline")
    assert (call["steps"], call["guidance"], call["max_sequence_length"]) == (4, 0.0, 256)
    loads = [c for c in box.calls if c[0] == "load"]
    box.be.generate({"mode": "t2i", "model": "FLUX.1-schnell", "prompt": "y"}, None, box.tmp / "c.png", CancelEvent())
    assert len([c for c in box.calls if c[0] == "load"]) == len(loads)       # نفس النموذج ونفس النمط: ما بيعيد التحميل
    box.be.unload()
    assert not box.be.loaded and box.be.loaded_model is None and box.be._pipe is None


def test_edit_with_references_passes_a_list_and_keeps_the_picture_size(box):
    a, b, c3 = (save_png(box.tmp / f"{n}.png", (64, 96), col) for n, col in (("a", (1, 1, 1)), ("b", (2, 2, 2)), ("c", (3, 3, 3))))
    out = box.tmp / "e.png"
    box.be.generate({"mode": "i2i", "model": "Qwen-Image-Edit-2509", "prompt": "غيّر", "_image2": str(b), "_image3": str(c3), "steps": 2}, a, out, CancelEvent())
    call = last_call(box.calls, "QwenImageEditPlusPipeline")
    assert call["refs"] == 3 and call["size"] == (None, None) and Image.open(out).size == (64, 96)


def test_video_runs_through_pil_output_even_though_wan_defaults_to_numpy(box):
    src = save_png(box.tmp / "s.png", (540, 960))
    out = box.tmp / "v.mp4"
    box.be.generate({"mode": "i2v", "model": "Wan2.2-TI2V-5B-Diffusers", "prompt": "حرّك", "seconds": 1, "steps": 2}, src, out, CancelEvent())
    call = last_call(box.calls, "WanImageToVideoPipeline")
    assert call["output_type"] == "pil" and call["num_frames"] == 25 and (call["width"], call["height"]) == (448, 832)
    assert out.exists() and out.stat().st_size > 1000
    assert [c for c in box.calls if c[0] == "vae"][0][1:3] == ("Wan2.2-TI2V-5B-Diffusers", "vae")           # VAE بـ float32 لـ Wan
    assert "float32" in [c for c in box.calls if c[0] == "vae"][0][3]
    before = len([c for c in box.calls if c[0] == "load"])
    box.be.generate({"mode": "t2v", "model": "Wan2.2-TI2V-5B-Diffusers", "prompt": "x", "seconds": 1, "steps": 1}, None, box.tmp / "t.mp4", CancelEvent())
    assert len([c for c in box.calls if c[0] == "load"]) == before + 1 and (box.tmp / "t.mp4").exists()      # نمط تاني = صنف pipeline تاني


def test_numpy_frames_are_encoded_too(box, monkeypatch):
    calls: list = []
    install_fake_diffusers(monkeypatch, calls, wan_numpy=True)
    out = box.tmp / "n.mp4"
    box.be.generate({"mode": "t2v", "model": "Wan2.2-TI2V-5B-Diffusers", "prompt": "x", "seconds": 1, "steps": 1}, None, out, CancelEvent())
    assert out.exists() and out.stat().st_size > 500


def test_cancel_between_steps_stops_without_writing_and_keeps_the_service_usable(box):
    cancel = CancelEvent()

    class Flip(CancelEvent):
        def __setattr__(self, k, v):
            super().__setattr__(k, v)
            if k == "step" and v == 2:
                self.set()
    cancel = Flip()
    out = box.tmp / "c.png"
    box.be.generate({"mode": "t2i", "model": "Qwen-Image", "prompt": "x", "steps": 10}, None, out, cancel)
    assert not out.exists() and cancel.step == 2
    box.be.generate({"mode": "t2i", "model": "Qwen-Image", "prompt": "y", "steps": 1}, None, out, CancelEvent())
    assert out.exists()


def test_generate_refuses_missing_or_rejected_models_and_unsupported_requests(box):
    with pytest.raises(RuntimeError, match="مش جاهز"):
        box.be.generate({"mode": "t2i", "model": "Pickled", "prompt": "x"}, None, box.tmp / "x.png", CancelEvent())
    with pytest.raises(RuntimeError, match="مش جاهز"):
        box.be.generate({"mode": "t2i", "model": "Ghost", "prompt": "x"}, None, box.tmp / "x.png", CancelEvent())
    with pytest.raises(ValueError, match="بدّه صورة"):
        box.be.generate({"mode": "i2i", "model": "Qwen-Image-Edit-2509", "prompt": "x"}, None, box.tmp / "x.png", CancelEvent())


def test_a_diffusers_without_the_class_says_so_in_arabic(box, monkeypatch):
    mod = sys.modules["diffusers"]
    monkeypatch.delattr(mod, "FluxPipeline")
    with pytest.raises(RuntimeError, match="حدّث الصورة"):
        box.be.generate({"mode": "t2i", "model": "FLUX.1-schnell", "prompt": "x"}, None, box.tmp / "x.png", CancelEvent())


def test_offload_mode_follows_the_setting_and_the_card_size(box, monkeypatch):
    be = box.be
    be.settings.offload = "model"
    assert be._offload_mode() == "model"
    be.settings.offload = "none"
    assert be._offload_mode() == "none"
    be.settings.offload = "auto"
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda i: types.SimpleNamespace(total_memory=48 * 1024 ** 3))
    assert be._offload_mode() == "none"
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda i: types.SimpleNamespace(total_memory=16 * 1024 ** 3))
    assert be._offload_mode() == "model"
    box.be.settings.offload = "model"
    box.be.generate({"mode": "t2i", "model": "Qwen-Image", "prompt": "x", "steps": 1}, None, box.tmp / "o.png", CancelEvent())
    assert box.be._pipe.offloaded is True and box.be._pipe.device is None


# ── الصوت (Stable Audio) ─────────────────────────────────────────────────
def test_text_to_audio_loads_fp16_uses_the_legacy_callback_and_writes_a_wav(box):
    out = box.tmp / "a.wav"
    cancel = CancelEvent()
    box.be.generate({"mode": "t2a", "model": "stable-audio-open-1.0", "prompt": "hammer", "seconds": 12.5, "seed": 3, "steps": 4}, None, out, cancel)
    load = next(c for c in box.calls if c[0] == "load")
    assert load[1] == "StableAudioPipeline" and load[3]["torch_dtype"] == torch.float16 and load[3]["local_files_only"] is True and load[3]["use_safetensors"] is True
    call = last_call(box.calls, "StableAudioPipeline")
    assert (call["seconds"], call["steps"], call["guidance"], call["negative"], call["output_type"]) == (12.5, 4, 7.0, "Low quality.", "np")
    assert call["callback_steps"] == 1 and call["generator"].initial_seed() == 3 and (cancel.step, cancel.total) == (4, 4)
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (2, 16000, 200000)
    assert not any(c[0] == "tiling" for c in box.calls)                      # مشفّر الصوت (Oobleck) ما فيه tiling: الصندوق ما بيطيّر
    assert box.be.loaded_model == "stable-audio-open-1.0"


def test_audio_length_is_capped_at_the_model_maximum_and_cancel_works_with_the_legacy_callback(box):
    box.be.generate({"mode": "t2a", "model": "stable-audio-open-1.0", "prompt": "x", "seconds": 90, "steps": 1}, None, box.tmp / "long.wav", CancelEvent())
    assert last_call(box.calls, "StableAudioPipeline")["seconds"] == 47.0

    class Flip(CancelEvent):
        def __setattr__(self, k, v):
            super().__setattr__(k, v)
            if k == "step" and v == 3:
                self.set()
    cancel = Flip()
    out = box.tmp / "c.wav"
    box.be.generate({"mode": "t2a", "model": "stable-audio-open-1.0", "prompt": "x", "seconds": 5, "steps": 10}, None, out, cancel)
    assert not out.exists() and cancel.step == 3
    box.be.generate({"mode": "t2a", "model": "stable-audio-open-1.0", "prompt": "y", "seconds": 1, "steps": 1}, None, out, CancelEvent())
    assert out.exists()                                                         # الخدمة بتضل شغّالة بعد الإلغاء


def test_write_wav_handles_shapes_clipping_tensors_and_bad_input(tmp_path):
    import array

    import numpy as np

    from services.engine.backends._common import write_wav

    def info(p):
        with wave.open(str(p)) as w:
            return w.getnchannels(), w.getframerate(), w.getnframes(), w.readframes(w.getnframes())
    write_wav(np.zeros((2, 100), dtype=np.float32), 8000, tmp_path / "a.wav")                  # (قنوات، عينات)
    assert info(tmp_path / "a.wav")[:3] == (2, 8000, 100)
    write_wav(np.zeros((100, 2), dtype=np.float32), 8000, tmp_path / "b.wav")                  # (عينات، قنوات)
    assert info(tmp_path / "b.wav")[:3] == (2, 8000, 100)
    write_wav(np.zeros(50, dtype=np.float32), 8000, tmp_path / "c.wav")                        # أحادي
    assert info(tmp_path / "c.wav")[:3] == (1, 8000, 50)
    write_wav(np.zeros((6, 40), dtype=np.float32), 8000, tmp_path / "d.wav")                   # أكتر من قناتين: أول اتنتين
    assert info(tmp_path / "d.wav")[:3] == (2, 8000, 40)
    write_wav(np.array([[0.5, 2.0, -4.0, 1.0]], dtype=np.float32), 8000, tmp_path / "e.wav")    # الذروة 4: الصوت كله بيتصغّر بنفس النسبة (بدل ما تنقص الذروة وتتشوّه)
    pcm = array.array("h")
    pcm.frombytes(info(tmp_path / "e.wav")[3])
    assert max(abs(x) for x in pcm) == 32767 and pcm[1] > 0 and pcm[2] < 0 and abs(pcm[0] - round(0.5 / 4 * 32767)) <= 1
    write_wav(torch.full((2, 10), 0.25), 8000, tmp_path / "f.wav")                             # tensor
    assert info(tmp_path / "f.wav")[:3] == (2, 8000, 10)
    write_wav(np.array([[np.nan, np.inf, -np.inf]], dtype=np.float32), 8000, tmp_path / "g.wav")   # قيم تالفة = صمت مش ضجيج
    assert set(array.array("h", info(tmp_path / "g.wav")[3])) == {0}
    for bad in (np.zeros((2, 0), dtype=np.float32), np.zeros((2, 3, 4), dtype=np.float32)):
        with pytest.raises(RuntimeError, match="شكل الصوت"):
            write_wav(bad, 8000, tmp_path / "x.wav")


# ── التكبير ──────────────────────────────────────────────────────────────
class Up(torch.nn.Module):
    def __init__(self, scale=4):
        super().__init__()
        self.scale = scale

    def forward(self, x):
        return torch.nn.functional.interpolate(x, scale_factor=self.scale, mode="nearest")


@pytest.fixture
def upscaler(box, monkeypatch):
    (box.weights / "upscale").mkdir()
    (box.weights / "upscale" / "RealESRGAN_x4plus.pth").write_bytes(b"\0" * 64)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)              # على المعالج: الاختبار ما بيعتمد على كرت الجهاز
    monkeypatch.setattr(_upscale, "load_model", lambda path, device: Up(4))
    return box


def test_upscale_tiles_the_picture_and_returns_exactly_the_requested_factor(upscaler):
    src = save_png(upscaler.tmp / "s.png", (50, 70), (10, 200, 30))
    out = upscaler.tmp / "big.png"
    upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 4}, src, out, CancelEvent())
    assert Image.open(out).size == (200, 280) and Image.open(out).convert("RGB").getpixel((100, 100)) == (10, 200, 30)
    assert upscaler.be.loaded_model == "upscale-RealESRGAN_x4plus"
    half = upscaler.tmp / "half.png"
    upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 2}, src, half, CancelEvent())
    assert Image.open(half).size == (100, 140)                                  # النموذج ×4 والمطلوب ×2: بنصغّر لحجم المطلوب


def test_upscale_unloads_the_diffusion_model_and_guards_size_cancel_and_missing_image(upscaler):
    upscaler.be.generate({"mode": "t2i", "model": "Qwen-Image", "prompt": "x", "steps": 1}, None, upscaler.tmp / "i.png", CancelEvent())
    assert upscaler.be._pipe is not None
    src = save_png(upscaler.tmp / "s.png", (20, 20))
    upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 4}, src, upscaler.tmp / "u.png", CancelEvent())
    assert upscaler.be._pipe is None and upscaler.be.loaded_model == "upscale-RealESRGAN_x4plus"             # نموذج وحيد بالذاكرة
    upscaler.settings.upscale_max_pixels = 5000              # 20×20 ×4 ×4 = 6400 بكسل بالخرج: أكبر من الحد
    with pytest.raises(RuntimeError, match="الصورة كبيرة"):
        upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 4}, src, upscaler.tmp / "z.png", CancelEvent())
    upscaler.settings.upscale_max_pixels = 0                  # 0 = الافتراضي (64 ميغابكسل)
    upscaler.settings.max_pixels = 100                        # سقف دقة التوليد مش لهالتكبير: ما بيأثر
    stop = CancelEvent()
    stop.set()
    cancelled = upscaler.tmp / "cx.png"
    upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 4}, src, cancelled, stop)
    assert not cancelled.exists()
    with pytest.raises(RuntimeError, match="بدّه صورة"):
        upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 4}, None, cancelled, CancelEvent())


def test_load_model_uses_spandrel_once_per_file_and_refuses_non_image_models(tmp_path, monkeypatch):
    loads = []

    class Desc:
        scale = 4

        def eval(self):
            return self

        def to(self, dev):
            return self

        def half(self):
            return self

    class Other:
        pass

    mod = types.ModuleType("spandrel")
    mod.ImageModelDescriptor = Desc
    mod.ModelLoader = lambda: types.SimpleNamespace(load_from_file=lambda p: loads.append(p) or (Other() if "audio" in p else Desc()))
    monkeypatch.setitem(sys.modules, "spandrel", mod)
    _upscale.clear()
    f = tmp_path / "m.pth"
    a = _upscale.load_model(f, "cpu")
    assert _upscale.load_model(f, "cpu") is a and len(loads) == 1
    with pytest.raises(RuntimeError, match="مش نموذج تكبير"):
        _upscale.load_model(tmp_path / "audio.pth", "cpu")
    _upscale.clear()


def test_upscale_guard_uses_the_models_native_scale_and_cancel_stops_between_tiles(upscaler):
    import numpy as np
    src = save_png(upscaler.tmp / "s.png", (50, 70))
    upscaler.settings.upscale_max_pixels = 50 * 70 * 4 * 4 - 1                        # ×2 مطلوب بس النموذج ×4 داخلياً: المصفوفة بتتحجز ×4 قبل التصغير
    with pytest.raises(RuntimeError, match="بيكبّر ×4 داخلياً"):
        upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 2}, src, upscaler.tmp / "g.png", CancelEvent())
    assert not (upscaler.tmp / "g.png").exists()
    upscaler.settings.upscale_max_pixels = 50 * 70 * 4 * 4
    upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 2}, src, upscaler.tmp / "ok.png", CancelEvent())
    assert Image.open(upscaler.tmp / "ok.png").size == (100, 140)

    class AfterN:
        def __init__(self, n):
            self.n, self.calls = n, 0

        def is_set(self):
            self.calls += 1
            return self.calls > self.n
    arr = np.zeros((600, 600, 3), dtype=np.float32)                                    # 4×4 قطع
    stopper = AfterN(2)
    assert _upscale.tile_upscale(arr, Up(4), "cpu", cancel=stopper) is None and stopper.calls == 3              # وقفت بعد قطعتين، بلا ما تكمّل الباقي
    assert _upscale.tile_upscale(arr, Up(4), "cpu").shape == (2400, 2400, 3)
    upscaler.settings.upscale_max_pixels = 64_000_000
    big = save_png(upscaler.tmp / "b.png", (600, 600))
    cancelled = upscaler.tmp / "c.png"
    upscaler.be.generate({"mode": "upscale", "model": "upscale-RealESRGAN_x4plus", "scale": 4}, big, cancelled, AfterN(3))
    assert not cancelled.exists()


def test_edit_images_bigger_than_the_pixel_cap_are_shrunk_before_the_pipeline_sees_them(box):
    box.settings.max_pixels = 90000
    big = save_png(box.tmp / "big.png", (640, 960))
    out = box.tmp / "e.png"
    box.be.generate({"mode": "i2i", "model": "Qwen-Image-Edit-2509", "prompt": "x", "steps": 1}, big, out, CancelEvent())
    w, h = Image.open(out).size                                                       # الـ pipeline المزيّف بيرجّع نسخة من الصورة اللي وصلته
    assert w * h <= 90000 and 0.55 <= w / h <= 0.8 and w % 16 == 0 and h % 16 == 0
    small = save_png(box.tmp / "small.png", (64, 96))
    box.be.generate({"mode": "i2i", "model": "Qwen-Image-Edit-2509", "prompt": "x", "steps": 1}, small, box.tmp / "e2.png", CancelEvent())
    assert Image.open(box.tmp / "e2.png").size == (64, 96)                           # الصغيرة ما بتتغيّر


def test_concurrent_listing_is_safe(box):
    out = []
    ts = [threading.Thread(target=lambda: out.append(len(box.be.list_models(refresh=True)))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [6] * 6
