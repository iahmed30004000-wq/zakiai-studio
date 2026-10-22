"""
اكتشاف أوزان diffusers وفهمها — بلا torch ولا diffusers (الملف بينقرأ وبينفحص بالاختبارات بدونهم).

الصندوق العام (diffusers_any) بيقرا أي أوزان بمجلد WEIGHTS_DIR: كل مجلد فيه model_index.json = نموذج. هون:
  · discover()   بيمسح المجلد وبيطلّع لكل نموذج: الاسم، الـ pipeline، الأنماط (t2i/i2i/t2v/i2v…)، الحجم، الرخصة، وصلاحيته + سبب الرفض.
  · plan_call()  بيبني معاملات نداء الـ pipeline من طلب المالك حسب «تلميحات العائلة» وتوقيع __call__ (أي معامل مش بالتوقيع ما بنبعتو).

حماية (قواعد ثابتة):
  · مكوّنات النموذج لازم من مكتبتي diffusers وtransformers بس (أي مكتبة تانية = مرفوض: ما بننفّذ كود غريب).
    استثناء واحد بالاسم: StableAudioProjectionModel — مكتبته stable_audio هي مجلد جوّا diffusers نفسها (هيك بيسجّله model_index.json)، مش كود خارجي.
  · أوزان safetensors بس. أي ملف .bin/.pt/.pth/.ckpt/.pkl… (pickle بيشغّل كود لما ينفتح) أو .py/.so/.sh داخل مجلد النموذج = مرفوض بسبب واضح.
    (الاستثناء الوحيد: ملفات التكبير بمجلد upscale/ — بتنفتح بـ spandrel بوضع tensors فقط.)
  · روابط رمزية (symlink) بتطلع برّا مجلد الأوزان بتنتجاهل.
  · الرخصة بتنقرا من README (front matter) كمساعدة بس — القرار للمالك بمكتبة النماذج.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from services.engine.backends._common import fit_resolution, frame_count

ALLOWED_LIBS = {"diffusers", "transformers"}
ALLOWED_BUNDLED = {("stable_audio", "StableAudioProjectionModel")}          # (المكتبة، الصنف): مكوّنات مكتبتها اسم مجلد pipeline جوّا diffusers
FORBIDDEN_EXT = {".bin", ".pt", ".pth", ".ckpt", ".pkl", ".pickle", ".joblib", ".npy", ".npz", ".py", ".pyc", ".so", ".dll", ".sh", ".exe", ".bat"}
UPSCALE_EXT = {".pth", ".safetensors"}
NAME_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")
MAX_FILES = 6000
MODES = ("t2i", "i2i", "upscale", "t2v", "i2v", "t2a")
IMAGE_MODES = ("t2i", "i2i", "upscale")
KIND_OF_MODE = {"t2i": "image", "i2i": "image", "upscale": "image", "t2v": "video", "i2v": "video", "t2a": "audio"}
EXT_OF_KIND = {"image": ".png", "video": ".mp4", "audio": ".wav"}

# تلميحات العائلات. modes: النمط ← صنف الـ pipeline اللي بنحمّله لهالنمط (من نفس مجلد الأوزان).
# multiple: أبعاد الصورة/الفيديو لازم من مضاعفاته. cfg: اسم معامل التوجيه. frame_step: الإطارات = step*k+1. neg: بيقبل negative_prompt.
PIPELINES: dict[str, dict] = {
    "QwenImagePipeline": dict(family="qwen-image", kind="image", modes={"t2i": "QwenImagePipeline"}, multiple=16, steps=50, guidance=4.0, cfg="true_cfg_scale", neg=True,
                              max_pixels=1328 * 1328, default_negative=" "),
    "QwenImageEditPipeline": dict(family="qwen-image-edit", kind="image", modes={"i2i": "QwenImageEditPipeline"}, multiple=16, steps=50, guidance=4.0, cfg="true_cfg_scale",
                                  neg=True, max_pixels=1328 * 1328, max_images=1, default_negative=" "),
    "QwenImageEditPlusPipeline": dict(family="qwen-image-edit", kind="image", modes={"i2i": "QwenImageEditPlusPipeline"}, multiple=16, steps=40, guidance=4.0,
                                      cfg="true_cfg_scale", neg=True, max_pixels=1328 * 1328, max_images=3, default_negative=" "),
    "FluxPipeline": dict(family="flux", kind="image", modes={"t2i": "FluxPipeline"}, multiple=16, steps=28, guidance=3.5, cfg="guidance_scale", neg=False, max_pixels=1024 * 1792),
    "FluxImg2ImgPipeline": dict(family="flux", kind="image", modes={"i2i": "FluxImg2ImgPipeline"}, multiple=16, steps=28, guidance=3.5, cfg="guidance_scale", neg=False,
                                max_pixels=1024 * 1792, strength=0.75, max_images=1),
    "FluxKontextPipeline": dict(family="flux-kontext", kind="image", modes={"i2i": "FluxKontextPipeline"}, multiple=16, steps=28, guidance=2.5, cfg="guidance_scale", neg=False,
                                max_pixels=1024 * 1792, max_images=1),
    "StableDiffusionXLPipeline": dict(family="sdxl", kind="image", modes={"t2i": "StableDiffusionXLPipeline"}, multiple=8, steps=30, guidance=6.0, cfg="guidance_scale",
                                      neg=True, max_pixels=1024 * 1280),
    "StableDiffusionXLImg2ImgPipeline": dict(family="sdxl", kind="image", modes={"i2i": "StableDiffusionXLImg2ImgPipeline"}, multiple=8, steps=30, guidance=6.0,
                                             cfg="guidance_scale", neg=True, max_pixels=1024 * 1280, strength=0.6, max_images=1),
    "StableDiffusion3Pipeline": dict(family="sd3", kind="image", modes={"t2i": "StableDiffusion3Pipeline"}, multiple=16, steps=28, guidance=7.0, cfg="guidance_scale",
                                     neg=True, max_pixels=1024 * 1280),
    # i2v بمجلد WanPipeline بس لـ TI2V (model_index فيه expand_timesteps=true)؛ T2V-14B وأخوته ما بيحرّكوا صورة (مجلداتهم بصنف WanImageToVideoPipeline لو كانوا I2V)
    "WanPipeline": dict(family="wan", kind="video", modes={"t2v": "WanPipeline", "i2v": "WanImageToVideoPipeline"}, mode_requires={"i2v": ("expand_timesteps", True)},
                        multiple=32, steps=30, guidance=5.0, cfg="guidance_scale", neg=True, max_pixels=480 * 832, frame_step=4, fps=16, max_images=1,
                        default_negative="worst quality, low quality, blurry, static, distorted hands, extra fingers, watermark, text, subtitles"),
    "WanImageToVideoPipeline": dict(family="wan", kind="video", modes={"i2v": "WanImageToVideoPipeline"}, multiple=32, steps=30, guidance=5.0, cfg="guidance_scale",
                                    neg=True, max_pixels=480 * 832, frame_step=4, fps=16, max_images=1,
                                    default_negative="worst quality, low quality, blurry, static, distorted hands, extra fingers, watermark, text, subtitles"),
    "LTXPipeline": dict(family="ltx", kind="video", modes={"t2v": "LTXPipeline", "i2v": "LTXImageToVideoPipeline"}, multiple=32, steps=40, guidance=3.0, cfg="guidance_scale",
                        neg=True, max_pixels=480 * 864, frame_step=8, fps=24, fps_arg="frame_rate", max_images=1,
                        default_negative="worst quality, blurry, jittery, distorted, inconsistent motion, watermark, text"),
    "LTXImageToVideoPipeline": dict(family="ltx", kind="video", modes={"i2v": "LTXImageToVideoPipeline"}, multiple=32, steps=40, guidance=3.0, cfg="guidance_scale", neg=True,
                                    max_pixels=480 * 864, frame_step=8, fps=24, fps_arg="frame_rate", max_images=1,
                                    default_negative="worst quality, blurry, jittery, distorted, inconsistent motion, watermark, text"),
    "CogVideoXPipeline": dict(family="cogvideox", kind="video", modes={"t2v": "CogVideoXPipeline"}, multiple=16, steps=50, guidance=6.0,       # أوزان I2V بمجلد تاني (CogVideoXImageToVideoPipeline)
                              cfg="guidance_scale", neg=True, max_pixels=480 * 720, frame_step=8, fps=8, max_images=1),
    "CogVideoXImageToVideoPipeline": dict(family="cogvideox", kind="video", modes={"i2v": "CogVideoXImageToVideoPipeline"}, multiple=16, steps=50, guidance=6.0,
                                          cfg="guidance_scale", neg=True, max_pixels=480 * 720, frame_step=8, fps=8, max_images=1),
    "HunyuanVideoPipeline": dict(family="hunyuan", kind="video", modes={"t2v": "HunyuanVideoPipeline"}, multiple=16, steps=30, guidance=6.0, cfg="guidance_scale", neg=False,
                                 max_pixels=480 * 848, frame_step=4, fps=15),
    # صوت (موسيقى/مؤثرات): ستيريو 44.1kHz، لحد ~47.5 ثانية. بلا أبعاد (multiple/max_pixels شكلية). fp16 حسب توثيق diffusers. callback قديم مش callback_on_step_end.
    "StableAudioPipeline": dict(family="stable-audio", kind="audio", modes={"t2a": "StableAudioPipeline"}, multiple=1, steps=100, guidance=7.0, cfg="guidance_scale", neg=True,
                                max_pixels=0, max_seconds=47.0, dtype="float16", default_negative="Low quality."),
}
SUPPORTED_NAMES = sorted({c for spec in PIPELINES.values() for c in spec["modes"].values()} | set(PIPELINES))

# معاملات للمحرّك نفسه — ما بتنمرّر من extra أبداً (حتى لو التوقيع بيقبلها)
DENY_EXTRA = {"prompt", "negative_prompt", "prompt_2", "negative_prompt_2", "image", "width", "height", "num_frames", "num_inference_steps", "guidance_scale",
              "true_cfg_scale", "generator", "callback", "callback_on_step_end", "callback_on_step_end_tensor_inputs", "output_type", "return_dict",
              "cross_attention_kwargs", "attention_kwargs", "latents", "prompt_embeds", "negative_prompt_embeds", "frame_rate", "fps", "strength", "device", "dtype",
              "torch_dtype", "cache_dir", "local_files_only", "trust_remote_code", "use_safetensors", "variant",
              "audio_end_in_s", "audio_start_in_s", "num_waveforms_per_prompt", "initial_audio_waveforms", "initial_audio_sampling_rate", "attention_mask",
              "negative_attention_mask", "callback_steps", "num_images_per_prompt", "num_videos_per_prompt"}      # مضاعفات الشغل: ممنوعة (الصندوق بيحفظ أول ناتج بس)
_EXTRA_KEY = re.compile(r"[a-z_][a-z0-9_]{0,40}")
EXTRA_NUM_MAX = 100_000_000                       # أي رقم بـ extra أكبر من هيك مرفوض (حماية: inf وأرقام ضخمة)
EXTRA_CAPS = {"max_sequence_length": 2048}        # المحلّل بيحشو لهالطول على المعالج: قيمة ضخمة = ذاكرة الجهاز كلها

# رخص معروفة (id بالأحرف الصغيرة كما بترويسة README) ← هل بتسمح بالاستعمال التجاري؟ yes | conditional | no
LICENCES = {
    "apache-2.0": "yes", "mit": "yes", "bsd-3-clause": "yes", "bsd-2-clause": "yes", "cc0-1.0": "yes", "unlicense": "yes", "cc-by-4.0": "yes", "cc-by-sa-4.0": "yes",
    "openrail": "conditional", "openrail++": "conditional", "creativeml-openrail-m": "conditional", "bigscience-openrail-m": "conditional",
    "gemma": "conditional", "llama3": "conditional", "llama3.1": "conditional", "llama3.2": "conditional", "other": "unknown",
    "cc-by-nc-4.0": "no", "cc-by-nc-sa-4.0": "no", "cc-by-nc-nd-4.0": "no", "cc-by-nc-3.0": "no", "agpl-3.0": "conditional", "gpl-3.0": "conditional",
}


@dataclass
class ModelInfo:
    name: str
    path: str
    pipeline: str = ""
    family: str = ""
    kind: str = ""                                    # image | video | audio
    modes: list[str] = field(default_factory=list)
    size_bytes: int = 0
    licence_id: str = ""
    commercial: str = "unknown"
    problems: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)
    note: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.modes)

    def public(self) -> dict:
        reason = "؛ ".join(self.problems) if self.problems else ("" if self.modes else "ما فهمنا أنماط النموذج")
        return {"name": self.name, "kind": self.kind, "pipeline": self.pipeline, "family": self.family, "tasks": list(self.modes), "size_gb": round(self.size_bytes / 1024 ** 3, 2),
                "licence": {"id": self.licence_id or "غير معروفة", "commercial": self.commercial}, "ok": self.ok, "reason": reason, "note": self.note}


def _read_json(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def licence_from_readme(text: str) -> tuple[str, str]:
    """(id الرخصة، تجاري؟) من ترويسة README (--- … ---). بسيط بلا YAML: سطور key: value بس."""
    m = re.match(r"\s*---\s*\n(.*?)\n---", text or "", re.S)
    if not m:
        return "", "unknown"
    vals = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() and not k.startswith((" ", "-", "\t")):
            vals[k.strip().lower()] = v.strip().strip("'\"").lower()
    lic = vals.get("license", "")
    name = vals.get("license_name", "")
    com = LICENCES.get(lic, "unknown")
    if com == "unknown" and (name or lic == "other"):
        label = name or lic
        com = "no" if re.search(r"non[- ]?commercial|research|noncommercial|\bnc\b", label) else "unknown"
    return (name or lic), com


def _scan_tree(root: Path, limit: int = MAX_FILES) -> tuple[list[Path], list[str]]:
    """(الملفات، المشاكل). ملفات برابط رمزي لبرّا المجلد بنتجاهلها. مشاكل بتمنع النموذج (diffusers بيتبع الروابط وإحنا لازم نشوف كل شي):
    أي مجلد برابط رمزي، أو عدد ملفات أكبر من الحد (ما بنفحصه كله)، أو حلقة روابط."""
    files: list[Path] = []
    problems: list[str] = []
    try:
        base = root.resolve()
    except (OSError, RuntimeError):
        return files, ["المجلد مش مقروء (رابط رمزي دائري؟)"]
    stack = [root]
    n = 0
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            n += 1
            if n > limit:
                problems.append(f"فيه أكتر من {limit} ملف/مجلد — ما بنفحصه كله (نموذج diffusers عادي فيه عشرات الملفات)")
                return files, problems
            p = Path(e.path)
            try:
                if e.is_symlink():
                    target = p.resolve()
                    if target.is_dir():                                    # أينما أشار (جوّا الأوزان أو برّا): diffusers بيتبعه وإحنا ما منقدر نفحص محتواه
                        problems.append(f"«{e.name}» مجلد برابط رمزي — انسخه فعلياً (ما منقدر نفحص محتواه بأمان)")
                    elif target.is_file() and (target == base or base in target.parents):
                        files.append(p)                                    # ملف برابط لجوّا نفس المجلد: بينحسب. الباقي (برّا المجلد أو مكسور) بنتجاهله
                elif e.is_dir(follow_symlinks=False):
                    stack.append(p)
                elif e.is_file(follow_symlinks=False):
                    files.append(p)
            except (OSError, RuntimeError):                                # RuntimeError: حلقة روابط رمزية (Python ≤ 3.12)
                problems.append(f"«{e.name}» رابط رمزي مش مقروء (حلقة؟)")
    return files, problems


def scan_model(path: Path) -> ModelInfo:
    """يفحص مجلد نموذج واحد (فيه model_index.json). ما بيرمي: الأخطاء بتنكتب بـ problems."""
    path = Path(path)
    info = ModelInfo(name=path.name, path=str(path))
    if not NAME_RX.fullmatch(path.name):
        info.problems.append("اسم المجلد فيه رموز غير مسموحة (حروف إنجليزية وأرقام و _ - . بس)")
        return info
    idx = _read_json(path / "model_index.json")
    if idx is None:
        info.problems.append("model_index.json مش مقروء")
        return info
    info.pipeline = str(idx.get("_class_name") or "")
    for k, v in idx.items():
        if k.startswith("_") or not isinstance(v, list) or len(v) != 2:
            continue
        lib, cls = v
        info.components[k] = [lib, cls]
        if lib is not None and str(lib) not in ALLOWED_LIBS and (str(lib), str(cls)) not in ALLOWED_BUNDLED:
            info.problems.append(f"المكوّن «{k}» من مكتبة غير مسموحة ({lib}) — بس diffusers وtransformers")
    spec = PIPELINES.get(info.pipeline)
    if spec is None:
        info.problems.append(f"نوع الـ pipeline ({info.pipeline or 'غير مذكور'}) مش مدعوم بعد")
    else:
        info.family, info.kind, info.modes = spec["family"], spec["kind"], list(spec["modes"])
        for mode, (key, want) in (spec.get("mode_requires") or {}).items():       # نمط بدّه علامة بـ model_index (متل i2v بـ Wan: TI2V بس)
            if mode in info.modes and idx.get(key) != want:
                info.modes.remove(mode)
                if info.modes == ["t2v"]:
                    info.note = "نص لفيديو بس (هالنموذج ما بيحرّك صورة)"
    total, bad = 0, []
    files, walk_problems = _scan_tree(path, MAX_FILES)
    info.problems.extend(walk_problems)
    for f in files:
        ext = f.suffix.lower()
        if ext in FORBIDDEN_EXT:
            bad.append(f.name)
        elif ext == ".safetensors":
            try:
                if len(f.relative_to(path).parts) >= 2:       # أوزان المكوّنات بمجلداتها بس: النسخ الأحادية بالجذر (flux1-schnell.safetensors، ltxv-*.safetensors) ما بيحمّلها diffusers
                    total += f.stat().st_size
            except (OSError, ValueError):
                pass
    info.size_bytes = total
    if bad:
        info.problems.append("فيه ملفات غير آمنة: " + "، ".join(sorted(set(bad))[:4]) + " — أوزان safetensors بس (pickle بيشغّل كود لما ينفتح)")
    elif total == 0:
        info.problems.append("ما في أوزان safetensors بمجلدات المكوّنات (transformer وvae…) — المجلد لازم بصيغة diffusers")
    for readme in ("README.md", "readme.md", "model_card.md"):
        r = path / readme
        if r.is_file():
            try:
                info.licence_id, info.commercial = licence_from_readme(r.read_text(encoding="utf-8", errors="replace")[:20000])
            except OSError:
                pass
            break
    if "schnell" in path.name.lower():
        info.note = "نسخة سريعة (4 خطوات)"
    return info


def scan_upscalers(root: Path) -> list[ModelInfo]:
    """ملفات التكبير بمجلد upscale/ (Real-ESRGAN وأمثاله): كل ملف .pth/.safetensors = نموذج باسم upscale-<اسم الملف>."""
    out = []
    d = Path(root) / "upscale"
    if not d.is_dir():
        return out
    for f in sorted(d.iterdir()):
        try:
            if not f.is_file() or f.suffix.lower() not in UPSCALE_EXT or (f.is_symlink() and d.resolve() not in f.resolve().parents):
                continue
        except (OSError, RuntimeError):
            continue
        name = f"upscale-{f.stem}"
        info = ModelInfo(name=name, path=str(f), pipeline="spandrel", family="upscale", kind="image", modes=["upscale"])
        if not NAME_RX.fullmatch(name):
            info.problems.append("اسم الملف فيه رموز غير مسموحة")
        try:
            info.size_bytes = f.stat().st_size
        except OSError:
            info.problems.append("الملف مش مقروء")
        info.note = "بيتحمّل بـ spandrel (tensors بس، بلا تنفيذ كود)"
        out.append(info)
    return out


def discover(weights_dir) -> list[ModelInfo]:
    """كل النماذج بمجلد الأوزان (مجلد فيه model_index.json) + ملفات التكبير. مرتّبة بالاسم."""
    root = Path(weights_dir)
    out: list[ModelInfo] = []
    if root.is_dir():
        for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            try:
                if d.is_dir() and not d.name.startswith(".") and d.name != "upscale" and (d / "model_index.json").is_file():
                    if d.is_symlink() and root.resolve() not in d.resolve().parents:
                        continue
                    out.append(scan_model(d))
            except (OSError, RuntimeError):                                  # رابط دائري بمجلد: ما بيطيّر القائمة كلها
                continue
    return out + scan_upscalers(root)


# ── بناء نداء الـ pipeline ────────────────────────────────────────────────
@dataclass
class CallPlan:
    kwargs: dict
    width: int = 0
    height: int = 0
    frames: int = 0
    fps: int = 0
    steps: int = 0
    kind: str = "image"
    ignored_extra: list[str] = field(default_factory=list)
    cls_name: str = ""
    seconds: float = 0.0                              # الصوت: المدة اللي انطلبت فعلاً (بعد سقف النموذج)


def clean_extra(raw) -> dict:
    """extra من الطلب: لحد 12 مفتاح، أسماؤها حروف صغيرة/أرقام/_، قيمها بسيطة (bool/رقم/نص ≤200). ValueError بسبب عربي."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("extra لازم كائن")
    if len(raw) > 12:
        raise ValueError("extra: لحد 12 معامل")
    out = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not _EXTRA_KEY.fullmatch(k):
            raise ValueError(f"extra: اسم معامل غير صالح ({k!r})")
        if k in DENY_EXTRA:
            raise ValueError(f"extra: المعامل «{k}» محجوز للصندوق")
        if isinstance(v, bool) or isinstance(v, (int, float)):
            if isinstance(v, float) and v != v:
                raise ValueError(f"extra.{k}: رقم غير صالح")
            if not isinstance(v, bool):
                cap = EXTRA_CAPS.get(k)
                if cap is not None and not 1 <= v <= cap:
                    raise ValueError(f"extra.{k}: لازم بين 1 و{cap}")
                if abs(v) > EXTRA_NUM_MAX:
                    raise ValueError(f"extra.{k}: رقم كبير كتير")
        elif isinstance(v, str):
            if len(v) > 200 or "\x00" in v:
                raise ValueError(f"extra.{k}: نص أطول من 200 حرف")
        else:
            raise ValueError(f"extra.{k}: القيمة لازم بسيطة (رقم أو نص أو صح/غلط)")
        out[k] = v
    return out


def spec_for(pipeline: str) -> dict | None:
    return PIPELINES.get(pipeline)


def default_size(max_pixels: int, multiple: int, ratio: tuple[int, int] = (9, 16)) -> tuple[int, int]:
    """أكبر مقاس بنسبة 9:16 (عمودي، متل إعلاناتنا) بحدود max_pixels ومن مضاعفات multiple."""
    rw, rh = ratio
    h = int((max_pixels * rh / rw) ** 0.5)
    return fit_resolution(max(1, h * rw // rh), h, max_pixels, multiple)


def plan_call(spec: dict, mode: str, sig: set[str] | None, req: dict, images: list, *, max_pixels: int = 0, model_name: str = "") -> CallPlan:
    """معاملات نداء الـ pipeline.
    spec: صف من PIPELINES · sig: أسماء معاملات __call__ (None = ما منعرف: ما بنفلتر) · req: الطلب بعد التحقق · images: صور جاهزة للنداء (PIL).
    بيرمي ValueError (رسالة عربية) لو الطلب ما بيناسب النمط (مثلاً صورة ناقصة)."""
    kind = spec["kind"]
    if mode not in spec["modes"]:
        raise ValueError(f"النموذج ما بيدعم النمط {mode}")
    has = (lambda n: True) if sig is None else (lambda n: n in sig)
    need_img = mode in ("i2v", "i2i")
    if need_img and not images:
        raise ValueError("هالنمط بدّه صورة")
    if images and len(images) > spec.get("max_images", 1):
        images = images[: spec.get("max_images", 1)]
    steps = int(req.get("steps") or spec["steps"])
    guidance = req.get("guidance")
    slow_fast = "schnell" in model_name.lower()
    if slow_fast:
        steps = int(req.get("steps") or 4)
        guidance = 0.0 if guidance is None else guidance
    guidance = float(spec["guidance"] if guidance is None else guidance)
    kw: dict = {"prompt": req.get("prompt") or ""}
    neg = req.get("negative_prompt") or spec.get("default_negative")
    if spec.get("neg") and has("negative_prompt") and neg:
        kw["negative_prompt"] = neg
    if has("num_inference_steps"):
        kw["num_inference_steps"] = steps
    cfg = spec["cfg"]
    if has(cfg):
        kw[cfg] = guidance
    elif cfg == "true_cfg_scale" and has("guidance_scale"):
        kw["guidance_scale"] = guidance
    w = h = 0
    mp = int(max_pixels or spec["max_pixels"])
    if kind in ("image", "video") and has("width") and has("height"):
        if req.get("width") and req.get("height"):
            w, h = fit_resolution(int(req["width"]), int(req["height"]), mp, spec["multiple"])
        elif mode == "i2v":
            iw, ih = images[0].size
            w, h = fit_resolution(iw, ih, mp, spec["multiple"])
        elif mode in ("t2i", "t2v"):
            w, h = default_size(mp, spec["multiple"])
        if w and h:                                   # تعديل صورة (i2i) بلا مقاس: الـ pipeline بياخد مقاس الصورة نفسها
            kw["width"], kw["height"] = w, h
    if need_img:
        key = "image"
        kw[key] = images if spec.get("max_images", 1) > 1 and len(images) > 1 else images[0]
        if mode == "i2i" and has("strength") and spec.get("strength") is not None:
            kw["strength"] = float(req["strength"] if req.get("strength") is not None else spec["strength"])
    frames = fps = 0
    if kind == "video":
        base_fps = spec.get("fps", 24)
        if spec["family"] == "wan" and ("ti2v" in model_name.lower() or "5b" in model_name.lower()):
            base_fps = 24                                  # Wan2.2-TI2V-5B بـ 24 إطار بالثانية، وكل إخوته (A14B) بـ 16
        fps = int(req.get("fps") or base_fps)
        frames = frame_count(float(req.get("seconds", 3)), fps, spec["frame_step"])
        if has("num_frames"):
            kw["num_frames"] = frames
        if spec.get("fps_arg") and has(spec["fps_arg"]):
            kw[spec["fps_arg"]] = fps
    audio_sec = 0.0
    if kind == "audio":                               # Stable Audio: المدة بالثواني (≤ سقف النموذج ~47.5)، من الصفر
        audio_sec = min(float(req.get("seconds") or 10), float(spec.get("max_seconds") or 47.0))
        if has("audio_end_in_s"):
            kw["audio_end_in_s"] = audio_sec
    if slow_fast and has("max_sequence_length"):
        kw["max_sequence_length"] = 256
    if has("output_type"):                            # Wan بيرجّع numpy افتراضياً؛ الباقي PIL — بنثبّتها PIL للكل. الصوت numpy (الافتراضي tensor) ونكتب WAV بأنفسنا
        kw["output_type"] = "np" if kind == "audio" else "pil"
    ignored = []
    for k, v in clean_extra(req.get("extra")).items():
        if (sig is None or k in sig) and k not in kw:
            kw[k] = v
        else:
            ignored.append(k)
    return CallPlan(kwargs=kw, width=w, height=h, frames=frames, fps=fps, steps=steps, kind=kind, ignored_extra=ignored, cls_name=spec["modes"][mode], seconds=audio_sec)
