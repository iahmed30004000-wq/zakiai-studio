"""اكتشاف أوزان diffusers وفهمها (services/engine/backends/_introspect.py) — بلا torch ولا diffusers: ملفات وهمية بمجلد مؤقت."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.engine.backends import _introspect as it  # noqa: E402

GOOD_COMPONENTS = {"scheduler": ["diffusers", "FlowMatchEulerDiscreteScheduler"], "vae": ["diffusers", "AutoencoderKL"],
                   "text_encoder": ["transformers", "T5EncoderModel"], "tokenizer": ["transformers", "T5Tokenizer"],
                   "transformer": ["diffusers", "SomeTransformer"]}


def make_model(root: Path, name: str, pipeline: str, *, components=None, files=("transformer/diffusion_pytorch_model.safetensors",), readme=None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    idx = {"_class_name": pipeline, "_diffusers_version": "0.35.0", **(GOOD_COMPONENTS if components is None else components)}
    (d / "model_index.json").write_text(json.dumps(idx), encoding="utf-8")
    for f in files:
        p = d / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * 1024)
    if readme is not None:
        (d / "README.md").write_text(readme, encoding="utf-8")
    return d


class Img:
    """بديل عن صورة PIL (الاختبار بلا PIL): بس الحجم."""

    def __init__(self, size=(540, 960)):
        self.size = size


def sig_of(*names) -> set:
    return set(names)


# ── الاكتشاف ─────────────────────────────────────────────────────────────
def test_discover_reads_models_sizes_modes_and_licence(tmp_path):
    make_model(tmp_path, "Qwen-Image", "QwenImagePipeline", readme="---\nlicense: apache-2.0\n---\n# Qwen")
    make_model(tmp_path, "Wan2.2-TI2V-5B-Diffusers", "WanPipeline", files=("transformer/a.safetensors", "transformer/b.safetensors"),
               components={**GOOD_COMPONENTS, "expand_timesteps": True})                                   # TI2V: العلامة اللي بتفتح i2v
    (tmp_path / "notes").mkdir()                                       # مجلد بلا model_index.json: يتجاهل
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "model_index.json").write_text("{}")
    found = {m.name: m for m in it.discover(tmp_path)}
    assert set(found) == {"Qwen-Image", "Wan2.2-TI2V-5B-Diffusers"}
    q = found["Qwen-Image"]
    assert q.ok and q.modes == ["t2i"] and q.kind == "image" and q.family == "qwen-image" and q.size_bytes == 1024
    assert (q.licence_id, q.commercial) == ("apache-2.0", "yes")
    w = found["Wan2.2-TI2V-5B-Diffusers"]
    assert w.ok and w.modes == ["t2v", "i2v"] and w.kind == "video" and w.size_bytes == 2048 and w.commercial == "unknown"
    pub = q.public()
    assert pub["tasks"] == ["t2i"] and pub["ok"] is True and pub["reason"] == "" and pub["licence"] == {"id": "apache-2.0", "commercial": "yes"}


def test_unknown_libraries_pickles_and_unsupported_pipelines_are_refused_with_a_reason(tmp_path):
    make_model(tmp_path, "EvilLib", "QwenImagePipeline", components={**GOOD_COMPONENTS, "extra": ["evil_pkg", "Backdoor"]})
    make_model(tmp_path, "Pickled", "FluxPipeline", files=("transformer/model.safetensors", "transformer/weights.bin"))
    make_model(tmp_path, "HasPy", "FluxPipeline", files=("transformer/model.safetensors", "pipeline.py"))
    make_model(tmp_path, "NoWeights", "FluxPipeline", files=())
    make_model(tmp_path, "Strange", "SomethingNewPipeline")
    by = {m.name: m for m in it.discover(tmp_path)}
    assert not by["EvilLib"].ok and "evil_pkg" in by["EvilLib"].public()["reason"] and "غير مسموحة" in by["EvilLib"].public()["reason"]
    assert not by["Pickled"].ok and "weights.bin" in by["Pickled"].public()["reason"] and "safetensors" in by["Pickled"].public()["reason"]
    assert not by["HasPy"].ok and "pipeline.py" in by["HasPy"].public()["reason"]
    assert not by["NoWeights"].ok and "safetensors" in by["NoWeights"].public()["reason"]
    assert not by["Strange"].ok and "مش مدعوم" in by["Strange"].public()["reason"] and by["Strange"].public()["tasks"] == []


def test_bad_names_and_broken_index_are_reported_not_raised(tmp_path):
    (tmp_path / "فيه عربي").mkdir()
    (tmp_path / "فيه عربي" / "model_index.json").write_text("{}")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "model_index.json").write_text("{nope", encoding="utf-8")
    (tmp_path / "list").mkdir()
    (tmp_path / "list" / "model_index.json").write_text("[1]", encoding="utf-8")
    by = {m.name: m for m in it.discover(tmp_path)}
    assert "رموز غير مسموحة" in by["فيه عربي"].public()["reason"]
    assert "مش مقروء" in by["broken"].public()["reason"] and "مش مقروء" in by["list"].public()["reason"]
    assert it.discover(tmp_path / "does-not-exist") == []


def test_symlinks_leaving_the_weights_dir_are_ignored(tmp_path):
    outside = tmp_path / "outside"
    make_model(outside, "Leak", "FluxPipeline")
    root = tmp_path / "weights"
    root.mkdir()
    try:
        (root / "Leak").symlink_to(outside / "Leak", target_is_directory=True)
        make_model(root, "Safe", "FluxPipeline")
        (root / "Safe" / "link.safetensors").symlink_to(outside / "Leak" / "transformer" / "diffusion_pytorch_model.safetensors")
    except OSError:
        pytest.skip("الجهاز ما بيسمح بإنشاء روابط رمزية (ويندوز بلا وضع المطوّر)")
    names = [m.name for m in it.discover(root)]
    assert names == ["Safe"]
    assert it.discover(root)[0].size_bytes == 1024                    # الرابط اللي بيطلع برّا ما بينحسب


def test_upscalers_are_files_under_upscale_and_pickle_dirs_stay_forbidden(tmp_path):
    up = tmp_path / "upscale"
    up.mkdir()
    (up / "RealESRGAN_x4plus.pth").write_bytes(b"\0" * 2048)
    (up / "other.safetensors").write_bytes(b"\0" * 10)
    (up / "readme.txt").write_text("x")
    (up / "bad name.pth").write_bytes(b"\0")
    make_model(tmp_path, "Flux", "FluxPipeline")
    by = {m.name: m for m in it.discover(tmp_path)}
    assert set(by) == {"Flux", "upscale-RealESRGAN_x4plus", "upscale-other", "upscale-bad name"}
    u = by["upscale-RealESRGAN_x4plus"]
    assert u.ok and u.modes == ["upscale"] and u.size_bytes == 2048 and u.pipeline == "spandrel" and Path(u.path).name == "RealESRGAN_x4plus.pth"
    assert not by["upscale-bad name"].ok                                   # الاسم لازم يمرّ على نفس قاعدة الأسماء
    assert "upscale" not in [m.name for m in it.discover(tmp_path) if m.pipeline == "FluxPipeline"]


def test_only_component_folders_count_as_weights_not_single_file_checkpoints_at_the_root(tmp_path):
    """مستودعات متل FLUX.1-schnell وLTX-Video فيها نسخ أحادية الملف بالجذر (22GB وأكتر): diffusers ما بيحمّلها، فما بتنحسب بالحجم ولا بتكفي لوحدها."""
    make_model(tmp_path, "Flux", "FluxPipeline", files=("flux1-schnell.safetensors", "ae.safetensors", "transformer/a.safetensors", "vae/b.safetensors"))
    make_model(tmp_path, "OnlyRoot", "FluxPipeline", files=("model.safetensors",))
    by = {m.name: m for m in it.discover(tmp_path)}
    assert by["Flux"].ok and by["Flux"].size_bytes == 2048
    assert not by["OnlyRoot"].ok and by["OnlyRoot"].size_bytes == 0 and "مجلدات المكوّنات" in by["OnlyRoot"].public()["reason"]


@pytest.mark.parametrize("text,expect", [
    ("---\nlicense: apache-2.0\n---\nbody", ("apache-2.0", "yes")),
    ("---\nlicense: mit\n---", ("mit", "yes")),
    ("---\nlicense: cc-by-nc-4.0\n---", ("cc-by-nc-4.0", "no")),
    ("---\nlicense: creativeml-openrail-m\n---", ("creativeml-openrail-m", "conditional")),
    ("---\nlicense: other\nlicense_name: flux-1-dev-non-commercial-license\n---", ("flux-1-dev-non-commercial-license", "no")),
    ("---\nlicense: other\nlicense_name: ltx-video-open-weights\n---", ("ltx-video-open-weights", "unknown")),
    ("---\nlicense: 'Apache-2.0'\ntags:\n  - a\n---", ("apache-2.0", "yes")),
    ("# no front matter", ("", "unknown")),
    ("", ("", "unknown")),
    ("---\nlicense: made-up-licence\n---", ("made-up-licence", "unknown")),
])
def test_licence_from_readme_is_a_helper_that_never_over_promises(text, expect):
    assert it.licence_from_readme(text) == expect


# ── extra ────────────────────────────────────────────────────────────────
def test_extra_rules():
    assert it.clean_extra(None) == {} and it.clean_extra({}) == {}
    assert it.clean_extra({"max_sequence_length": 128, "flag": True, "style": "x"}) == {"max_sequence_length": 128, "flag": True, "style": "x"}
    for bad, msg in (([1], "كائن"), ({f"k{i}": 1 for i in range(13)}, "12"), ({"Bad Key": 1}, "اسم معامل غير صالح"), ({"prompt": "x"}, "محجوز"),
                     ({"callback_on_step_end": 1}, "محجوز"), ({"output_type": "np"}, "محجوز"), ({"a": [1]}, "بسيطة"), ({"a": "x" * 201}, "200"),
                     ({"a": float("nan")}, "غير صالح"), ({"a": {"b": 1}}, "بسيطة")):
        with pytest.raises(ValueError, match=msg):
            it.clean_extra(bad)


# ── تخطيط النداء ─────────────────────────────────────────────────────────
QWEN_SIG = sig_of("prompt", "negative_prompt", "true_cfg_scale", "height", "width", "num_inference_steps", "generator", "output_type",
                  "callback_on_step_end", "callback_on_step_end_tensor_inputs", "max_sequence_length")


def test_qwen_t2i_uses_true_cfg_a_blank_negative_and_the_vertical_default_size():
    spec = it.PIPELINES["QwenImagePipeline"]
    p = it.plan_call(spec, "t2i", QWEN_SIG, {"prompt": "عطر"}, [], model_name="Qwen-Image")
    kw = p.kwargs
    assert kw["prompt"] == "عطر" and kw["negative_prompt"] == " " and kw["true_cfg_scale"] == 4.0 and kw["num_inference_steps"] == 50
    assert kw["output_type"] == "pil"
    assert kw["width"] % 16 == 0 and kw["height"] % 16 == 0 and kw["height"] > kw["width"] and kw["width"] * kw["height"] <= 1328 * 1328
    assert p.kind == "image" and p.frames == 0 and p.steps == 50 and p.cls_name == "QwenImagePipeline"
    custom = it.plan_call(spec, "t2i", QWEN_SIG, {"prompt": "x", "negative_prompt": "bad", "steps": 20, "guidance": 3, "width": 768, "height": 1344}, [], model_name="Qwen-Image")
    assert (custom.kwargs["negative_prompt"], custom.kwargs["num_inference_steps"], custom.kwargs["true_cfg_scale"]) == ("bad", 20, 3.0)
    assert (custom.kwargs["width"], custom.kwargs["height"]) == (768, 1344)


def test_flux_schnell_is_four_steps_without_guidance_and_never_gets_a_negative():
    spec = it.PIPELINES["FluxPipeline"]
    sig = sig_of("prompt", "negative_prompt", "height", "width", "num_inference_steps", "guidance_scale", "max_sequence_length", "output_type")
    p = it.plan_call(spec, "t2i", sig, {"prompt": "x", "negative_prompt": "ignored?"}, [], model_name="FLUX.1-schnell")
    assert p.kwargs["num_inference_steps"] == 4 and p.kwargs["guidance_scale"] == 0.0 and "negative_prompt" not in p.kwargs
    assert p.kwargs["max_sequence_length"] == 256
    dev = it.plan_call(spec, "t2i", sig, {"prompt": "x"}, [], model_name="FLUX.1-dev")
    assert dev.kwargs["num_inference_steps"] == 28 and dev.kwargs["guidance_scale"] == 3.5 and "max_sequence_length" not in dev.kwargs


def test_wan_video_frames_fps_and_image_size_follow_the_model_and_the_picture():
    spec = it.PIPELINES["WanPipeline"]
    sig = sig_of("prompt", "negative_prompt", "image", "height", "width", "num_frames", "num_inference_steps", "guidance_scale", "output_type")
    i2v = it.plan_call(spec, "i2v", sig, {"prompt": "حرّك", "seconds": 3}, [Img((540, 960))], model_name="Wan2.2-TI2V-5B-Diffusers")
    kw = i2v.kwargs
    assert i2v.fps == 24 and kw["num_frames"] == 73 and (kw["num_frames"] - 1) % 4 == 0 and kw["image"].size == (540, 960)
    assert (kw["width"], kw["height"]) == (448, 832) and kw["width"] % 32 == 0 and kw["height"] % 32 == 0 and kw["width"] * kw["height"] <= 480 * 832
    assert "worst quality" in kw["negative_prompt"] and kw["guidance_scale"] == 5.0 and i2v.kind == "video"
    t2v = it.plan_call(spec, "t2v", sig, {"prompt": "x", "seconds": 2, "fps": 16}, [], model_name="Wan2.2-T2V-A14B-Diffusers")
    assert "image" not in t2v.kwargs and t2v.kwargs["num_frames"] == 33 and t2v.fps == 16
    a14 = it.plan_call(spec, "t2v", sig, {"prompt": "x"}, [], model_name="Wan2.2-T2V-A14B-Diffusers")
    assert a14.fps == 16                                                # A14B بـ 16 إطار بالثانية، وTI2V-5B بـ 24


def test_ltx_gets_frame_rate_and_cog_and_hunyuan_follow_their_tables():
    ltx = it.plan_call(it.PIPELINES["LTXPipeline"], "i2v", sig_of("prompt", "negative_prompt", "image", "width", "height", "num_frames", "frame_rate", "num_inference_steps",
                                                                   "guidance_scale"), {"prompt": "x", "seconds": 3}, [Img((1080, 1920))], model_name="LTX-Video")
    assert ltx.kwargs["frame_rate"] == 24 and ltx.kwargs["num_frames"] == 73 and ltx.kwargs["width"] % 32 == 0 and ltx.cls_name == "LTXImageToVideoPipeline"
    cog = it.plan_call(it.PIPELINES["CogVideoXPipeline"], "t2v", sig_of("prompt", "negative_prompt", "num_frames", "num_inference_steps", "guidance_scale", "height", "width"),
                       {"prompt": "x", "seconds": 6}, [], model_name="CogVideoX-5b")
    assert cog.fps == 8 and cog.kwargs["num_frames"] == 49 and "frame_rate" not in cog.kwargs
    hy = it.plan_call(it.PIPELINES["HunyuanVideoPipeline"], "t2v", sig_of("prompt", "negative_prompt", "num_frames", "num_inference_steps", "guidance_scale", "height", "width"),
                      {"prompt": "x", "seconds": 2}, [], model_name="HunyuanVideo")
    assert "negative_prompt" not in hy.kwargs and hy.fps == 15 and (hy.kwargs["num_frames"] - 1) % 4 == 0


def test_image_edit_modes_take_images_strength_and_cap_the_reference_count():
    sig = sig_of("prompt", "negative_prompt", "image", "strength", "num_inference_steps", "guidance_scale", "true_cfg_scale", "width", "height")
    sdxl = it.plan_call(it.PIPELINES["StableDiffusionXLImg2ImgPipeline"], "i2i", sig, {"prompt": "x", "strength": 0.4}, [Img((512, 768))], model_name="sdxl")
    assert sdxl.kwargs["strength"] == 0.4 and sdxl.kwargs["image"].size == (512, 768) and "width" not in sdxl.kwargs         # بلا مقاس: مقاس الصورة نفسها
    assert it.plan_call(it.PIPELINES["StableDiffusionXLImg2ImgPipeline"], "i2i", sig, {"prompt": "x"}, [Img()], model_name="sdxl").kwargs["strength"] == 0.6
    plus = it.PIPELINES["QwenImageEditPlusPipeline"]
    three = it.plan_call(plus, "i2i", sig, {"prompt": "x"}, [Img(), Img(), Img(), Img(), Img()], model_name="Qwen-Image-Edit-2509")
    assert isinstance(three.kwargs["image"], list) and len(three.kwargs["image"]) == 3
    one = it.plan_call(plus, "i2i", sig, {"prompt": "x"}, [Img()], model_name="Qwen-Image-Edit-2509")
    assert not isinstance(one.kwargs["image"], list)
    single = it.plan_call(it.PIPELINES["QwenImageEditPipeline"], "i2i", sig, {"prompt": "x"}, [Img(), Img()], model_name="Qwen-Image-Edit")
    assert not isinstance(single.kwargs["image"], list)                    # النسخة القديمة بتاخد صورة وحدة


def test_plan_refuses_missing_images_and_unsupported_modes():
    with pytest.raises(ValueError, match="بدّه صورة"):
        it.plan_call(it.PIPELINES["StableDiffusionXLImg2ImgPipeline"], "i2i", None, {"prompt": "x"}, [])
    with pytest.raises(ValueError, match="بدّه صورة"):
        it.plan_call(it.PIPELINES["WanPipeline"], "i2v", None, {"prompt": "x"}, [])
    with pytest.raises(ValueError, match="ما بيدعم النمط"):
        it.plan_call(it.PIPELINES["FluxPipeline"], "t2v", None, {"prompt": "x"}, [])


def test_arguments_not_in_the_pipeline_signature_are_never_sent_and_extras_are_filtered():
    spec = it.PIPELINES["FluxPipeline"]
    tiny = sig_of("prompt", "num_inference_steps")
    p = it.plan_call(spec, "t2i", tiny, {"prompt": "x", "width": 512, "height": 512, "guidance": 2, "seed": 3}, [], model_name="flux")
    assert set(p.kwargs) == {"prompt", "num_inference_steps"}              # بلا guidance_scale/width/height/output_type لأنها مش بالتوقيع
    full = sig_of("prompt", "num_inference_steps", "max_sequence_length", "guidance_scale", "width", "height")
    q = it.plan_call(spec, "t2i", full, {"prompt": "x", "extra": {"max_sequence_length": 128, "unknown_knob": 1}}, [], model_name="flux")
    assert q.kwargs["max_sequence_length"] == 128 and "unknown_knob" not in q.kwargs and q.ignored_extra == ["unknown_knob"]
    unknown = it.plan_call(spec, "t2i", None, {"prompt": "x", "extra": {"anything": 1}}, [], model_name="flux")          # التوقيع مجهول: ما بنفلتر
    assert unknown.kwargs["anything"] == 1 and unknown.kwargs["output_type"] == "pil"


def test_default_size_is_vertical_nine_sixteen_within_the_pixel_budget():
    for mp, mult in ((1328 * 1328, 16), (480 * 832, 32), (1024 * 1280, 8)):
        w, h = it.default_size(mp, mult)
        assert w % mult == 0 and h % mult == 0 and w * h <= mp and abs(w / h - 9 / 16) < 0.06, (mp, mult, w, h)


def test_the_hints_table_is_complete_and_consistent():
    assert set(it.KIND_OF_MODE) == set(it.MODES) and set(it.EXT_OF_KIND) == {"image", "video", "audio"}
    for name, spec in it.PIPELINES.items():
        assert {"family", "kind", "modes", "multiple", "steps", "guidance", "cfg", "neg", "max_pixels"} <= set(spec), name
        assert spec["kind"] in it.EXT_OF_KIND and spec["cfg"] in ("guidance_scale", "true_cfg_scale"), name
        for mode, cls in spec["modes"].items():
            assert it.KIND_OF_MODE[mode] == spec["kind"] and cls in it.SUPPORTED_NAMES, (name, mode)
        if spec["kind"] == "video":
            assert spec["frame_step"] > 0 and spec["fps"] > 0, name
        if spec["kind"] == "audio":
            assert spec["max_seconds"] > 0 and spec["dtype"] == "float16", name
    assert "WanImageToVideoPipeline" in it.SUPPORTED_NAMES and "QwenImageEditPlusPipeline" in it.SUPPORTED_NAMES and "StableAudioPipeline" in it.SUPPORTED_NAMES


def test_hints_table_matches_the_real_diffusers_signatures_when_diffusers_is_installed():
    """عقد حقيقي: على جهاز فيه diffusers بيتأكد إن كل صف بالجدول متوافق مع توقيع __call__ الفعلي (بيتخطّى هون: diffusers مش منزّل)."""
    diffusers = pytest.importorskip("diffusers")
    import inspect
    for key, spec in it.PIPELINES.items():
        for mode, cls_name in spec["modes"].items():
            cls = getattr(diffusers, cls_name, None)
            assert cls is not None, f"{cls_name} مش بـ diffusers {diffusers.__version__}"
            params = set(inspect.signature(cls.__call__).parameters)
            cb = ("callback", "callback_steps", "audio_end_in_s") if spec["kind"] == "audio" else ("callback_on_step_end", "callback_on_step_end_tensor_inputs")      # Stable Audio بـ callback قديم
            for needed in ("prompt", "num_inference_steps", spec["cfg"], *cb):
                assert needed in params, (key, mode, needed)
            if spec["kind"] == "video":
                assert "num_frames" in params, (key, mode)
            if mode in ("i2i", "i2v"):
                assert "image" in params, (key, mode)


# ── Stable Audio (t2a) ───────────────────────────────────────────────────
STABLE_AUDIO = {"scheduler": ["diffusers", "EDMDPMSolverMultistepScheduler"], "vae": ["diffusers", "AutoencoderOobleck"], "text_encoder": ["transformers", "T5EncoderModel"],
                "tokenizer": ["transformers", "T5TokenizerFast"], "transformer": ["diffusers", "StableAudioDiTModel"],
                "projection_model": ["stable_audio", "StableAudioProjectionModel"]}      # هيك بيسجّله model_index.json الحقيقي (مكتبة stable_audio = مجلد جوّا diffusers)
SA_FILES = ("transformer/diffusion_pytorch_model.safetensors", "vae/diffusion_pytorch_model.safetensors", "text_encoder/model.safetensors",
            "projection_model/diffusion_pytorch_model.safetensors", "tokenizer/spiece.model", "model.safetensors")
AUDIO_SIG = sig_of("prompt", "audio_end_in_s", "audio_start_in_s", "num_inference_steps", "guidance_scale", "negative_prompt", "num_waveforms_per_prompt", "eta",
                   "generator", "output_type", "callback", "callback_steps")


def test_stable_audio_folder_is_found_as_an_audio_model_with_its_bundled_projection_component(tmp_path):
    make_model(tmp_path, "stable-audio-open-1.0", "StableAudioPipeline", components=STABLE_AUDIO, files=SA_FILES,
               readme="---\nlicense: other\nlicense_name: stable-audio-community\n---")
    m = {x.name: x for x in it.discover(tmp_path)}["stable-audio-open-1.0"]
    assert m.ok and m.kind == "audio" and m.modes == ["t2a"] and m.family == "stable-audio" and m.size_bytes == 4 * 1024        # النسخة الأحادية بالجذر ما بتنحسب
    assert (m.licence_id, m.commercial) == ("stable-audio-community", "unknown")
    pub = m.public()
    assert pub["tasks"] == ["t2a"] and pub["kind"] == "audio" and pub["ok"] is True


def test_only_the_exact_bundled_pair_is_allowed_and_ckpt_files_are_still_refused(tmp_path):
    make_model(tmp_path, "BadClass", "StableAudioPipeline", components={**STABLE_AUDIO, "projection_model": ["stable_audio", "EvilModel"]}, files=SA_FILES)
    make_model(tmp_path, "OtherPipelineLib", "StableAudioPipeline", components={**STABLE_AUDIO, "extra": ["kandinsky", "KandinskyPriorPipeline"]}, files=SA_FILES)
    make_model(tmp_path, "RealRepoLayout", "StableAudioPipeline", components=STABLE_AUDIO, files=SA_FILES + ("model.ckpt", "vae_model.ckpt"))
    by = {m.name: m for m in it.discover(tmp_path)}
    assert not by["BadClass"].ok and "stable_audio" in by["BadClass"].public()["reason"] and "غير مسموحة" in by["BadClass"].public()["reason"]
    assert not by["OtherPipelineLib"].ok and "kandinsky" in by["OtherPipelineLib"].public()["reason"]
    reason = by["RealRepoLayout"].public()["reason"]
    assert not by["RealRepoLayout"].ok and "model.ckpt" in reason and "vae_model.ckpt" in reason and "safetensors" in reason     # المستودع الأصلي لازم ينزل بـ --exclude "*.ckpt"


def test_stable_audio_plan_sets_the_length_numpy_output_and_a_default_negative():
    spec = it.PIPELINES["StableAudioPipeline"]
    p = it.plan_call(spec, "t2a", AUDIO_SIG, {"prompt": "hammer", "seconds": 12.5}, [], model_name="stable-audio-open-1.0")
    kw = p.kwargs
    assert kw["prompt"] == "hammer" and kw["audio_end_in_s"] == 12.5 and kw["negative_prompt"] == "Low quality." and kw["guidance_scale"] == 7.0 and kw["num_inference_steps"] == 100
    assert kw["output_type"] == "np" and not ({"width", "height", "num_frames", "image", "audio_start_in_s"} & set(kw))
    assert (p.kind, p.seconds, p.frames, p.fps, p.cls_name, p.steps) == ("audio", 12.5, 0, 0, "StableAudioPipeline", 100)
    long = it.plan_call(spec, "t2a", AUDIO_SIG, {"prompt": "x", "seconds": 300, "steps": 20, "guidance": 5, "negative_prompt": "noise"}, [], model_name="s")
    assert long.kwargs["audio_end_in_s"] == 47.0 and long.kwargs["num_inference_steps"] == 20 and long.kwargs["guidance_scale"] == 5.0 and long.kwargs["negative_prompt"] == "noise"
    assert it.plan_call(spec, "t2a", AUDIO_SIG, {"prompt": "x"}, [], model_name="s").kwargs["audio_end_in_s"] == 10.0
    assert it.plan_call(spec, "t2a", None, {"prompt": "x", "seconds": 4}, [], model_name="s").kwargs["output_type"] == "np"                 # التوقيع مجهول: ما بنفلتر
    for key in ("audio_end_in_s", "audio_start_in_s", "num_waveforms_per_prompt", "callback_steps", "initial_audio_waveforms"):
        with pytest.raises(ValueError, match="محجوز"):
            it.clean_extra({key: 1})
    with pytest.raises(ValueError, match="ما بيدعم النمط"):
        it.plan_call(spec, "t2i", AUDIO_SIG, {"prompt": "x"}, [])
    with pytest.raises(ValueError, match="ما بيدعم النمط"):
        it.plan_call(it.PIPELINES["FluxPipeline"], "t2a", None, {"prompt": "x"}, [])


# ── مراجعة مستقلة: قدرات الأنماط، حماية الفحص، حدود extra ─────────────────
def test_wan_image_to_video_needs_the_ti2v_marker_and_cogvideox_t2v_folders_are_text_only(tmp_path):
    make_model(tmp_path, "Wan-T2V-14B", "WanPipeline")                                                    # T2V: بلا expand_timesteps
    make_model(tmp_path, "Wan-TI2V-5B", "WanPipeline", components={**GOOD_COMPONENTS, "expand_timesteps": True})
    make_model(tmp_path, "CogVideoX-5b", "CogVideoXPipeline")
    make_model(tmp_path, "CogVideoX-5b-I2V", "CogVideoXImageToVideoPipeline")
    by = {m.name: m for m in it.discover(tmp_path)}
    assert by["Wan-T2V-14B"].modes == ["t2v"] and "نص لفيديو" in by["Wan-T2V-14B"].note and by["Wan-T2V-14B"].ok
    assert by["Wan-TI2V-5B"].modes == ["t2v", "i2v"] and by["Wan-TI2V-5B"].note == ""
    assert by["CogVideoX-5b"].modes == ["t2v"] and by["CogVideoX-5b-I2V"].modes == ["i2v"]


def _symlink(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("الجهاز ما بيسمح بإنشاء روابط رمزية (ويندوز بلا وضع المطوّر)")


def test_a_symlinked_component_folder_is_refused_instead_of_hiding_unsafe_files(tmp_path):
    root = tmp_path / "weights"
    root.mkdir()
    make_model(root, "Other", "FluxPipeline", files=("transformer/a.safetensors", "text_encoder/evil.bin"))
    make_model(root, "Linked", "FluxPipeline")
    _symlink(root / "Linked" / "text_encoder", root / "Other" / "text_encoder", directory=True)           # diffusers بيتبعه، rglob ما كان يدخله
    by = {m.name: m for m in it.discover(root)}
    assert not by["Linked"].ok and "text_encoder" in by["Linked"].public()["reason"] and "رابط رمزي" in by["Linked"].public()["reason"]
    assert not by["Other"].ok and "evil.bin" in by["Other"].public()["reason"]


def test_too_many_files_refuse_the_model_and_symlink_loops_never_break_the_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(it, "MAX_FILES", 5)
    make_model(tmp_path, "Big", "FluxPipeline", files=tuple(f"transformer/w{i}.safetensors" for i in range(8)))
    by = {m.name: m for m in it.discover(tmp_path)}
    assert not by["Big"].ok and "أكتر من 5" in by["Big"].public()["reason"]
    monkeypatch.setattr(it, "MAX_FILES", 6000)
    loop = make_model(tmp_path, "Loop", "FluxPipeline")
    _symlink(loop / "a", loop / "b", directory=True)
    _symlink(loop / "b", loop / "a", directory=True)                                                       # حلقة: resolve() بيرمي RuntimeError على Python ≤ 3.12
    make_model(tmp_path, "Fine", "FluxPipeline")
    by = {m.name: m for m in it.discover(tmp_path)}
    assert by["Fine"].ok and "Loop" in by                                                                  # القائمة كلها ما وقعت بسبب المجلد الدائري
    if sys.version_info < (3, 13):
        assert not by["Loop"].ok and "حلقة" in by["Loop"].public()["reason"]


def test_extra_numbers_are_bounded_and_work_multipliers_are_reserved():
    for bad, msg in (({"max_sequence_length": 10 ** 9}, "لازم بين"), ({"max_sequence_length": 0}, "لازم بين"), ({"max_sequence_length": 2049}, "لازم بين"),
                     ({"a": float("inf")}, "كبير كتير"), ({"a": -10 ** 12}, "كبير كتير"), ({"num_images_per_prompt": 4}, "محجوز"), ({"num_videos_per_prompt": 2}, "محجوز")):
        with pytest.raises(ValueError, match=msg):
            it.clean_extra(bad)
    assert it.clean_extra({"max_sequence_length": 2048, "max_area": 1048576, "flag": True}) == {"max_sequence_length": 2048, "max_area": 1048576, "flag": True}
