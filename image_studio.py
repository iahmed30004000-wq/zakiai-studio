#!/usr/bin/env python3
"""
المحطات ٧ و٨: الصور (٢–٣ خيارات لكل لقطة) وفحص التطابق.

    python image_studio.py gen library/scripts/X.json [--shot s2c1] [--n 2]

كل لقطة معتمدة بالبرومبتات (محطة ٦) بتتولّد بمرجع الشخصية والمنتج، والمالك بيختار.
  · أي صورة أقل من 1080×1920 (أو بنسبة غير 9:16) بتنقص/تنكبّر — تكبير Lanczos (مش موديل ذكاء اصطناعي).
  · لقطات المنتج القريبة (قريبة، يد مع المنتج): صورة المنتج الحقيقية بتنركّب فوق المشهد بالحجم المحسوب.
  · باقي اللقطات: فحص آلي لنص الملصق (OCR) ولوجه الشخصية (facecheck.py: YuNet + SFace على الجهاز، بلا إنترنت).
    حجم المنتج والتشابه البصري **ما بينقاسوا** آلياً — بتنعلّم «غير مقاسة» والمالك بيحكم بمحطة فحص التطابق.
    الفحص بيعلّم بس («الوجه تغيّر»)؛ حكم المالك هو النهائي، ونتيجة كل فحص حاسم بتنسجّل لنموذج الصور (تعلّم أي نموذج بيحافظ على الوجه).
  · حد عدد نداءات الصور لكل فيديو (STUDIO_MAX_IMAGE_CALLS) — بيوقف لما يوصل.
  · لقطة فيها مراجع (شخصية/منتج) ومزوّد الصور المضبوط ما بياخد صور مرجعية (UnoRouter مثلاً): ما بنفشل ولا بنولّد بلا الوجه المرجعي —
    بتتحوّل لطابور الإضافة (ChatGPT/Flow/Gemini بالمراجع) والنظام بيقول ليش بوضوح (RoutedToExtension).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import config
import production_log
import studio_state
import timeline

FRAME = (1080, 1920)
# عرض المنتج ÷ عرض الإطار، حسب نوع اللقطة
RATIO = {"close": 0.55, "hand_product": 0.34, "medium": 0.22, "wide": 0.12}
TOLERANCE = 0.10
PRODUCT_SHOTS = ("close", "hand_product")
LABEL_PASS = 0.6
VERDICTS = ("pass", "fail", "override")


class ImageStudioError(Exception):
    """رسالة عربية جاهزة للعرض."""


class RoutedToExtension(ImageStudioError):
    """مش فشل: اللقطة فيها مراجع ومزوّد الصور ما بياخدها فبتنعمل بالإضافة. الرسالة بتشرح ليش وشو يعمل المالك."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def img_dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "timelines" / stem / "img"


def _rel(stem: str, p: Path) -> str:
    return p.resolve().relative_to((Path(config.LIBRARY_DIR) / "timelines" / stem).resolve()).as_posix()


def abs_of(stem: str, rel: str) -> Path | None:
    base = (Path(config.LIBRARY_DIR) / "timelines" / stem).resolve()
    p = (base / rel).resolve()
    return p if base in p.parents and p.exists() else None


# ── الميزانية (عدد النداءات لكل فيديو) ───────────────────────────────────
def _budget_path(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "studio" / stem / "image_budget.json"


def calls_used(stem: str) -> int:
    p = _budget_path(stem)
    return json.loads(p.read_text(encoding="utf-8")).get("calls", 0) if p.exists() else 0


def cap() -> int:
    return int(getattr(config, "STUDIO_MAX_IMAGE_CALLS", 80))


def _bump(stem: str) -> None:
    p = _budget_path(stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"calls": calls_used(stem) + 1, "cap": cap(), "at": _now()}), encoding="utf-8")


def budget(stem: str) -> dict:
    return {"used": calls_used(stem), "cap": cap(), "left": max(0, cap() - calls_used(stem))}


# ── وصول للخط الزمني ────────────────────────────────────────────────────
def _load(stem: str) -> dict:
    tl = timeline.load(stem)
    if not tl:
        raise ImageStudioError("ما في خط زمني — اعتمد الصوت أولاً")
    return tl


def _shot(tl: dict, shot_id: str) -> tuple[dict, dict]:
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == shot_id:
                return sc, sh
    raise ImageStudioError("لقطة غير موجودة")


def _save(stem: str, tl: dict) -> None:
    timeline.save(stem, tl)


def _image(sh: dict) -> dict:
    im = sh.setdefault("image", {})
    im.setdefault("candidates", [])
    im.setdefault("chosen", None)
    return im


def product_code(script: dict) -> str:
    import brief as brief_mod
    import review_script
    b = review_script.load_brief(script) or {}
    return brief_mod.slug_code(b.get("product_code") or b.get("product_name")
                               or (script.get("_meta") or {}).get("product") or "")


# ── المراجع ─────────────────────────────────────────────────────────────
def refs_with_roles(stem: str, sh: dict, code: str) -> list[tuple[Path, str]]:
    """الشخصية أولاً (وجه: أمام + ثلاثة أرباع؛ يد: ورقة اليدين) ثم المنتج، وكل صورة بدورها (person/product). حد ٣.
    الوضعيات من refprompts: نفسها اللي بتظهر عليها شارة «بتنبعت مع التوليد» بشاشة الأوراق المرجعية."""
    import characters
    import product_ref
    import refprompts
    refs: list[tuple[Path, str]] = []
    cid = (sh.get("refs") or {}).get("character_id")
    if cid:
        views = refprompts.CHARACTER_HAND_VIEWS if sh.get("type") == "hand_product" else refprompts.CHARACTER_FACE_VIEWS
        for v in views:
            p = characters.sheet_path(cid, v)
            if p:
                refs.append((p, "person"))
    if code:
        p = product_ref.angle_path(code, refprompts.PRODUCT_SENT_SLOT)
        if p:
            refs.append((p, "product"))
    return refs[:3]


def refs_for_shot(stem: str, sh: dict, code: str) -> list[Path]:
    """نفس refs_with_roles بس مسارات (ext_bridge والإضافة بيحتاجوا المسارات بس)."""
    return [p for p, _role in refs_with_roles(stem, sh, code)]


# ── تجهيز الصورة: نسبة 9:16 وحد أدنى 1080×1920 ─────────────────────────
def ensure_frame(src: Path, dest: Path) -> dict:
    """قصّ مركزي لـ 9:16 ثم تكبير Lanczos لو أقل من 1080×1920. بيرجّع {w,h,upscaled,cropped}."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w, h = im.size
    cropped = False
    target = FRAME[0] / FRAME[1]
    if abs(w / h - target) > 0.005:
        if w / h > target:                       # أعرض من اللازم
            nw = round(h * target); x = (w - nw) // 2
            im = im.crop((x, 0, x + nw, h))
        else:                                    # أطول من اللازم
            nh = round(w / target); y = (h - nh) // 2
            im = im.crop((0, y, w, y + nh))
        cropped = True
    w, h = im.size
    up = w < FRAME[0] or h < FRAME[1]
    if up:
        im = im.resize(FRAME, Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "PNG")
    return {"w": im.size[0], "h": im.size[1], "upscaled": up, "cropped": cropped,
            "method": "lanczos" if up else None}


# ── التوليد ─────────────────────────────────────────────────────────────
def refs_supported(overrides: dict | None = None) -> dict:
    """هل مزوّد الصور المضبوط بياخد صور مرجعية؟ {provider, model, supports_refs}. أي مشكلة بقراءة الإعدادات = «بياخد» (السلوك القديم)."""
    try:
        import imagegen
        cfg = imagegen.image_config(overrides)
        return {"provider": cfg["provider"], "model": cfg["model"], "supports_refs": bool(cfg["supports_refs"])}
    except Exception:                                            # noqa: BLE001
        return {"provider": "", "model": "", "supports_refs": True}


def routed_message(sup: dict) -> str:
    return (f"مزوّد الصور المضبوط ({sup.get('provider') or '؟'}) بيولّد من النص بس وما بياخد صور مرجعية. "
            "لقطات الشخصية والمنتج لازم تتولّد بمراجعها (عشان الوجه والعبوة يضلّوا نفسهم)، فبتروح لطابور الإضافة "
            "(ChatGPT أو Flow أو Gemini): شغّلها من لوحة «الإضافة» بنفس هالصفحة. أو بدّل مزوّد الصور بالإعدادات لواحد بياخد مراجع (Google أو OpenAI).")


def _route_to_extension(stem: str) -> None:
    """بنضبط الإضافة على نوع «صور» (بلا ما نشغّلها — التشغيل من نافذتها)."""
    try:
        import ext_bridge
        ext_bridge.set_control(stem, kind="image")
    except Exception:                                            # noqa: BLE001
        pass


def _character_and_country(stem: str, script: dict) -> tuple[dict | None, str]:
    """شخصية السيناريو المختارة وبلد البريف (لبطاقة الهوية الإنجليزية ببرومبت الموديل)."""
    import characters
    import review_script
    cur = characters.chosen(stem)
    ch = characters.get(cur["character_id"]) if cur else None
    try:
        country = (review_script.load_brief(script) or {}).get("country") or ""
    except Exception:                                            # noqa: BLE001
        country = ""
    return ch, country


def _ensure_english(stem: str, script: dict, ids=None) -> None:
    """نسخة إنجليزية (prompt_model) للقطات اللي ما إلها: ترجمة بالذكاء + بطاقة هوية الشخصية، وبتنخزّن بالخط الزمني.
    فشلها ما بيوقف التوليد — البرومبت بيروح بطاقة الهوية + العربي وبتنعاد المحاولة بالتوليد الجاي."""
    import shot_prompts
    try:
        tl = _load(stem)
        ch, country = _character_and_country(stem, script)
        if shot_prompts.english_for(tl, ch, country, only=ids, log=lambda *_: None)["done"]:
            _save(stem, tl)
    except Exception:                                            # noqa: BLE001
        pass


def generate_shot(script_path, shot_id: str, n: int | None = None, overrides: dict | None = None,
                  log=print) -> dict:
    import imagegen
    import shot_prompts
    import usage
    path = Path(script_path)
    stem = path.stem
    script = json.loads(path.read_text(encoding="utf-8"))
    n = n or int(getattr(config, "STUDIO_IMAGE_CANDIDATES", 2))
    code = product_code(script)
    ok, why = studio_state.can_start(stem, 7)
    if not ok:
        raise ImageStudioError(why)
    if refs_for_shot(stem, _shot(_load(stem), shot_id)[1], code):
        sup = refs_supported(overrides)
        if not sup["supports_refs"]:                             # بلا فشل وبلا توليد بلا مراجع: الإضافة بتاخدها (والمحطة ما بتصير «شغّالة»)
            _route_to_extension(stem)
            raise RoutedToExtension(routed_message(sup))
    try:
        studio_state.set_state(stem, 7, "running", f"توليد صور {shot_id}")
    except studio_state.StationBlocked as e:
        raise ImageStudioError(str(e))
    _ensure_english(stem, script, [shot_id])
    ch, country = _character_and_country(stem, script)
    made = 0
    for k in range(n):
        if calls_used(stem) >= cap():
            studio_state.set_state(stem, 7, "failed", f"وصل حد نداءات الصور لهالفيديو ({cap()})")
            raise ImageStudioError(f"وصل حد نداءات الصور لهالفيديو ({cap()}) — ارفع STUDIO_MAX_IMAGE_CALLS من الإعدادات لو بدك تكمّل")
        tl = _load(stem)
        _sc, sh = _shot(tl, shot_id)
        prompt = shot_prompts.model_prompt(sh, ch, country).strip()
        if not prompt:
            raise ImageStudioError(f"لقطة {shot_id} بلا برومبت — اعتمد المحطة ٦ أولاً")
        pairs = refs_with_roles(stem, sh, code)
        refs, roles = [p for p, _role in pairs], [role for _p, role in pairs]
        out = img_dir(stem) / f"{shot_id}_{int(time.time() * 1000)}_{k}.png"
        t_gen = time.time()
        try:
            r = imagegen.generate(prompt, out, overrides, refs=refs, ref_roles=roles)
        except imagegen.ImageError as e:
            production_log.record("image", "failed", script_stem=stem, shot_id=shot_id, path="api",
                                  seconds=time.time() - t_gen, error=str(e))
            studio_state.set_state(stem, 7, "failed", str(e))
            raise ImageStudioError(str(e))
        production_log.record("image", "ok", script_stem=stem, shot_id=shot_id, model_id=r.get("model"),
                              model_name=r.get("provider"), path="api", seconds=time.time() - t_gen)
        _bump(stem)
        try:
            usage.record("image", r["provider"], r["model"], 0, 0)
        except Exception:
            pass
        from PIL import Image
        with Image.open(out) as im:
            w, h = im.size
        tl = _load(stem)                                   # إعادة قراءة: ممكن تغيّر أثناء الانتظار
        _sc, sh = _shot(tl, shot_id)
        _image(sh)["candidates"].append({"path": _rel(stem, out), "provider": r["provider"], "model": r["model"],
                                        "at": _now(), "w": w, "h": h, "refs_used": r.get("refs_used", [])})
        _save(stem, tl)
        made += 1
        log(f"  [✓] {shot_id} خيار {k + 1}/{n} ({w}×{h})")
    studio_state.set_state(stem, 7, "awaiting_choice", "بانتظار اختيارك لكل لقطة")
    return {"shot": shot_id, "made": made, "budget": budget(stem)}


def generate_all(script_path, n: int | None = None, overrides: dict | None = None, log=print) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    todo = [sh["id"] for sc in tl["scenes"] for sh in sc["shots"] if not _image(sh)["candidates"]]
    if todo:
        _ensure_english(stem, json.loads(Path(script_path).read_text(encoding="utf-8")), todo)      # ترجمة دفعة وحدة بدل لقطة لقطة
    done, failed, routed = [], [], []
    for sid in todo:
        try:
            generate_shot(script_path, sid, n, overrides, log)
            done.append(sid)
        except RoutedToExtension as e:
            routed.append(sid)
            if len(routed) == 1:
                log(f"  [→] {e}")
        except ImageStudioError as e:
            failed.append({"shot": sid, "error": str(e)})
            log(f"  [!] {sid}: {e}")
            if "حد نداءات" in str(e):
                break
    if routed:
        log(f"  [→] {len(routed)} لقطة اتحوّلت للإضافة: {'، '.join(routed)}")
    return {"done": done, "failed": failed, "routed": routed, "budget": budget(stem)}


# ── الاختيار ────────────────────────────────────────────────────────────
def choose(script_path, shot_id: str, cand_path: str) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    im = _image(sh)
    cand = next((c for c in im["candidates"] if c["path"] == cand_path), None)
    if not cand:
        raise ImageStudioError("الخيار مش من مرشّحات هاللقطة")
    src = abs_of(stem, cand["path"])
    if not src:
        raise ImageStudioError("ملف الصورة ناقص")
    dest = src.with_name(src.stem + "_1080.png")
    info = ensure_frame(src, dest)
    im.update(chosen=_rel(stem, dest), source=cand["path"], upscaled=info["upscaled"],
              upscale_method=info["method"], cropped=info["cropped"], composite=None, path_used="api")
    sh["product_check"] = None
    sh["face_check"] = None
    (tl.get("checks_approved_by_owner") or {}).pop(shot_id, None)
    _save(stem, tl)
    if studio_state.state_of(stem, 8) == "approved":
        studio_state.set_state(stem, 8, "awaiting_choice", "تغيّرت صورة لقطة")
    return sh


def upscale_candidate(script_path, shot_id: str, cand_path: str) -> dict:
    """نسخة مكبّرة بالذكاء (Real-ESRGAN محلياً) من خيار صورة، بتنضاف خيار جديد 1080×1920 (أحدّ من Lanczos).
    بطيء (حوالي دقيقة على الكرت) ومجاني — ما بيصرف رصيد ولا بيطلع الصورة برّا الجهاز."""
    import upscale
    from PIL import Image
    stem = Path(script_path).stem
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    cand = next((c for c in _image(sh)["candidates"] if c["path"] == cand_path), None)
    if not cand:
        raise ImageStudioError("الخيار مش من مرشّحات هاللقطة")
    src = abs_of(stem, cand["path"])
    if not src:
        raise ImageStudioError("ملف الصورة ناقص")
    if not upscale.available():
        raise ImageStudioError("نموذج التكبير غير منزّل (models/RealESRGAN_x4plus.pth)")
    with Image.open(src) as probe:
        w0, h0 = probe.size
    out = img_dir(stem) / f"{shot_id}_{int(time.time() * 1000)}_ai.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(out.stem + "_raw.png")
    try:
        upscale.upscale_image(src, raw, scale=4 if min(w0, h0) < 540 else 2)
        ensure_frame(raw, out)                                    # قص 9:16
        with Image.open(out) as big:
            if big.size != FRAME:
                big.convert("RGB").resize(FRAME, Image.LANCZOS).save(out, "PNG")
    except upscale.UpscaleError as e:
        raise ImageStudioError(str(e))
    finally:
        raw.unlink(missing_ok=True)
    tl = _load(stem)                                              # إعادة قراءة: الخط الزمني ممكن تغيّر أثناء الانتظار
    _sc, sh = _shot(tl, shot_id)
    _image(sh)["candidates"].append({"path": _rel(stem, out), "provider": "local", "model": "Real-ESRGAN",
                                    "at": _now(), "w": FRAME[0], "h": FRAME[1], "refs_used": [], "path_used": "upscale",
                                    "from": cand["path"]})
    _save(stem, tl)
    return sh


def _final_image(sh: dict) -> str | None:
    im = sh.get("image") or {}
    return im.get("composite") or im.get("chosen")


# ── تركيب المنتج الحقيقي على اللقطات القريبة ────────────────────────────
def composite(script_path, shot_id: str, x: float = 0.5, y: float = 0.72) -> dict:
    from PIL import Image, ImageEnhance, ImageFilter, ImageStat
    import product_ref
    path = Path(script_path)
    stem = path.stem
    script = json.loads(path.read_text(encoding="utf-8"))
    code = product_code(script)
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    if sh.get("type") not in PRODUCT_SHOTS:
        raise ImageStudioError("التركيب للقطات المنتج القريبة بس (قريبة، يد مع المنتج)")
    im = _image(sh)
    base = abs_of(stem, im["chosen"]) if im.get("chosen") else None
    if not base:
        raise ImageStudioError("اختر صورة للقطة أولاً")
    fp = product_ref.angle_path(code, "front")
    if not fp:
        raise ImageStudioError("ما في صورة منتج مفرَّغة (أمام) — ارفعها بملف المنتج المرجعي")
    if not (0.05 <= x <= 0.95 and 0.05 <= y <= 0.95):
        raise ImageStudioError("موضع خارج الإطار")

    scene = Image.open(base).convert("RGBA")
    prod = Image.open(fp).convert("RGBA")
    bbox = prod.getchannel("A").getbbox()
    if bbox:
        prod = prod.crop(bbox)
    ratio = RATIO[sh["type"]]
    tw = round(scene.width * ratio)
    th = round(prod.height * tw / prod.width)
    prod = prod.resize((tw, th), Image.LANCZOS)

    cx, cy = round(scene.width * x), round(scene.height * y)
    left, top = cx - tw // 2, cy - th // 2
    left = max(0, min(scene.width - tw, left))
    top = max(0, min(scene.height - th, top))

    # مواءمة الإضاءة: بنقرّب سطوع المنتج من سطوع المشهد حوله (ضمن حدود معقولة)
    region = scene.crop((left, top, left + tw, top + th)).convert("L")
    scene_l = ImageStat.Stat(region).mean[0]
    prod_l = ImageStat.Stat(prod.convert("L"), mask=prod.getchannel("A")).mean[0] or 1
    gain = max(0.85, min(1.15, scene_l / prod_l))
    rgb = ImageEnhance.Brightness(prod.convert("RGB")).enhance(gain)
    prod = Image.merge("RGBA", (*rgb.split(), prod.getchannel("A")))

    # ظل ناعم تحت المنتج
    shadow = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    ell = Image.new("L", scene.size, 0)
    from PIL import ImageDraw
    ImageDraw.Draw(ell).ellipse((left, top + th - th // 12, left + tw, top + th + th // 10), fill=110)
    shadow.putalpha(ell.filter(ImageFilter.GaussianBlur(max(6, tw // 14))))
    out = Image.alpha_composite(scene, shadow)
    out.alpha_composite(prod, (left, top))

    dest = img_dir(stem) / f"{shot_id}_comp.png"
    out.convert("RGB").save(dest, "PNG")
    achieved = tw / scene.width
    im["composite"] = _rel(stem, dest)
    sh["product_check"] = {"mode": "composite", "size_ratio": round(achieved / ratio, 3), "label_match": True,
                           "similarity": 1.0, "status": "pass",
                           "note": "صورة المنتج الحقيقية مركّبة بالحجم المحسوب"}
    _save(stem, tl)
    return sh


def clear_composite(script_path, shot_id: str) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    _image(sh)["composite"] = None
    sh["product_check"] = None
    _save(stem, tl)
    return sh


# ── الفحص الآلي (بقدر ما هو ممكن فعلاً) ─────────────────────────────────
_OCR = None


def _easyocr_read(path: Path) -> str:
    global _OCR
    if _OCR is None:
        import easyocr
        _OCR = easyocr.Reader(list(getattr(config, "OCR_LANGS", ["ar", "en"])),
                              gpu=bool(getattr(config, "OCR_USE_GPU", False)), verbose=False)
    return " ".join(_OCR.readtext(str(path), detail=0))


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[\s\W_]+", (s or "").lower()) if len(t) >= 2}


def label_score(read_text: str, label_text: str) -> float:
    want = _tokens(label_text)
    return (len(want & _tokens(read_text)) / len(want)) if want else 0.0


def _face_result(character_id: str, img: Path, face=None) -> dict:
    """تطابق وجه اللقطة بصور الشخصية المرجعية، محلياً. أي عطل تقني = «غير مقاس» مع السبب (ما بيوقف الفحص ولا الإنتاج)."""
    import characters
    import facecheck
    try:
        r = (face or facecheck.check_image)(facecheck.character_refs(character_id), img)
    except (facecheck.FaceCheckError, characters.CharacterError) as e:
        return {"status": "unchecked", "similarity": None, "note": str(e)}
    except Exception as e:                                       # noqa: BLE001 — فحص تحسيني: ما بنكسر الإنتاج لأي سبب
        return {"status": "unchecked", "similarity": None, "note": f"تعذّر فحص الوجه ({type(e).__name__})"}
    return {**r, "at": _now()}


def _log_face(stem: str, sh: dict, res: dict) -> None:
    """يسجّل نتيجة الفحص الحاسمة (ناجح/ساقط) لنموذج الصور اللي ولّد اللقطة — هيك النظام بيتعلّم مين بيحافظ على الوجه."""
    im = sh.get("image") or {}
    cands = im.get("candidates", [])
    cand = next((c for c in cands if c.get("path") == im.get("source")), None) or {}
    for _ in range(3):                                           # المكبَّرة بالذكاء بتورّث وجه الصورة الأصلية → النموذج المنسوب إلو هو الأصلي
        if cand.get("path_used") == "upscale" and cand.get("from"):
            cand = next((c for c in cands if c.get("path") == cand["from"]), None) or {}
    pth = cand.get("path_used")
    if pth not in production_log.PATHS:
        pth = "extension" if str(cand.get("provider") or "").startswith("extension") else ("api" if cand.get("provider") else None)
    production_log.record("face_image", "ok" if res["status"] == "pass" else "failed", script_stem=stem, shot_id=sh["id"],
                          model_id=cand.get("model") or cand.get("provider"), model_name=cand.get("provider"),
                          path=pth, score=res.get("similarity"))


def _needs_face(sh: dict) -> bool:
    return bool((sh.get("refs") or {}).get("character_id")) and sh.get("type") != "hand_product"


def check_shot(script_path, shot_id: str, ocr=None, face=None, *, label: bool = True, faces: bool = True) -> dict:
    """نص الملصق بالـOCR + تطابق الوجه (محلي) للقطات المولَّدة. الحجم والتشابه البصري: غير مقاسة.
    face: دالة (صور_مرجعية, صورة) ← نتيجة (للاختبارات)؛ label/faces: أي جزء بدنا نعيد فحصه."""
    import product_ref
    path = Path(script_path)
    stem = path.stem
    script = json.loads(path.read_text(encoding="utf-8"))
    code = product_code(script)
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    rel = _final_image(sh)
    img = abs_of(stem, rel) if rel else None
    if not img:
        raise ImageStudioError("ما في صورة معتمدة للقطة")

    if label and (sh.get("product_check") or {}).get("mode") != "composite":
        label_text = product_ref.load(code)["label_text"] if code else ""
        if not label_text:
            sh["product_check"] = {"mode": "generated", "status": "unchecked", "label_match": None,
                                   "size_ratio": None, "similarity": None,
                                   "note": "ما في نص ملصق بملف المنتج المرجعي — ما بنقدر نفحصه"}
        else:
            try:
                score = label_score((ocr or _easyocr_read)(img), label_text)
            except Exception as e:
                score = None
                note = f"تعذّر تشغيل OCR: {e}"
            else:
                note = f"تطابق نص الملصق {round(score * 100)}٪"
            if score is None:
                sh["product_check"] = {"mode": "generated", "status": "unchecked", "label_match": None,
                                       "size_ratio": None, "similarity": None, "note": note}
            else:
                sh["product_check"] = {"mode": "generated", "label_match": score >= LABEL_PASS,
                                       "label_score": round(score, 2), "size_ratio": None, "similarity": None,
                                       "status": "pass" if score >= LABEL_PASS else "fail",
                                       "note": note + " — الحجم والتشابه البصري غير مقاسين (حكم المالك)"}
    if faces:
        if _needs_face(sh):
            prev = sh.get("face_check") or {}
            res = _face_result(sh["refs"]["character_id"], img, face)
            res["image"] = rel
            if res["status"] in ("pass", "fail"):
                if prev.get("logged") != rel:                    # نفس الصورة ما بتنسجّل مرتين
                    _log_face(stem, sh, res)
                res["logged"] = rel
            sh["face_check"] = res
        else:
            sh["face_check"] = None
    _save(stem, tl)
    return sh


def check_all(script_path, ocr=None, face=None, only_missing: bool = True) -> dict:
    """يفحص كل لقطات الصور المعتمدة (الملصق + الوجه). only_missing: اللي انفحصت قبل ما بتنعاد.
    فشل لقطة وحدة ما بيوقف الباقي."""
    stem = Path(script_path).stem
    tl = _load(stem)
    todo = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if not _final_image(sh):
                continue
            need_label = sh.get("product_check") is None
            need_face = _needs_face(sh) and sh.get("face_check") is None
            if not only_missing or need_label or need_face:
                todo.append((sh["id"], need_label or not only_missing, need_face or not only_missing))
    done, failed = [], []
    for sid, lab, fac in todo:
        try:
            check_shot(script_path, sid, ocr, face, label=lab, faces=fac)
            done.append(sid)
        except ImageStudioError as e:
            failed.append({"shot": sid, "error": str(e)})
    return {"checked": done, "failed": failed}


# ── حكم المالك واعتماد المحطتين ─────────────────────────────────────────
def set_verdict(script_path, shot_id: str, verdict: str, note: str = "") -> dict:
    stem = Path(script_path).stem
    if verdict not in VERDICTS:
        raise ImageStudioError("الحكم: pass أو fail أو override")
    if verdict in ("fail", "override") and not (note or "").strip():
        raise ImageStudioError("اكتب سبب الحكم")
    tl = _load(stem)
    _sc, sh = _shot(tl, shot_id)
    if not _final_image(sh):
        raise ImageStudioError("ما في صورة للقطة")
    tl.setdefault("checks_approved_by_owner", {})[shot_id] = {"verdict": verdict, "note": (note or "").strip(), "at": _now()}
    _save(stem, tl)
    if studio_state.state_of(stem, 8) == "approved":
        studio_state.set_state(stem, 8, "awaiting_choice", "تغيّر حكم على لقطة")
    return tl["checks_approved_by_owner"][shot_id]


def image_problems(tl: dict) -> list[dict]:
    return [{"shot": sh["id"], "message": f"لقطة {sh['id']}: ما في صورة مختارة"}
            for sc in tl["scenes"] for sh in sc["shots"] if not (sh.get("image") or {}).get("chosen")]


def match_problems(tl: dict) -> list[dict]:
    out = []
    owner = tl.get("checks_approved_by_owner") or {}
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            sid = sh["id"]
            if not _final_image(sh):
                out.append({"shot": sid, "message": f"لقطة {sid}: ما في صورة"})
                continue
            v = (owner.get(sid) or {}).get("verdict")
            if v == "fail":
                out.append({"shot": sid, "message": f"لقطة {sid}: ساقطة بحكم المالك — أعد توليدها أو ركّب المنتج"})
                continue
            if v in ("pass", "override"):
                continue
            pc = sh.get("product_check") or {}
            if (sh.get("face_check") or {}).get("status") == "fail":
                out.append({"shot": sid, "message": f"لقطة {sid}: الوجه تغيّر عن الشخصية — أعد التوليد (نموذج تاني أو الإضافة) أو اعتمد صراحة"})
            elif pc.get("status") == "fail":
                out.append({"shot": sid, "message": f"لقطة {sid}: نص الملصق ما تطابق — أعد التوليد أو ركّب المنتج أو اعتمد صراحة"})
            else:
                out.append({"shot": sid, "message": f"لقطة {sid}: بانتظار حكمك"})
    return out


def approve_images(script_path) -> dict:
    stem = Path(script_path).stem
    tl = _load(stem)
    probs = image_problems(tl)
    if probs:
        raise ImageStudioError("؛ ".join(p["message"] for p in probs[:4]))
    studio_state.set_state(stem, 7, "approved", "كل لقطة إلها صورة مختارة")
    return {"approved": True, "shots": sum(len(s["shots"]) for s in tl["scenes"])}


def approve_match(script_path) -> dict:
    stem = Path(script_path).stem
    ok, why = studio_state.can_start(stem, 8)
    if not ok:
        raise ImageStudioError(why)
    tl = _load(stem)
    probs = match_problems(tl)
    if probs:
        raise ImageStudioError("؛ ".join(p["message"] for p in probs[:4]))
    studio_state.set_state(stem, 8, "approved", "طابقت اللقطات كلماتها ومراجعها")
    return {"approved": True}


def main() -> None:
    ap = argparse.ArgumentParser(description="توليد صور الخط الزمني")
    ap.add_argument("action", choices=["gen"])
    ap.add_argument("script")
    ap.add_argument("--shot")
    ap.add_argument("--n", type=int)
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--size")
    a = ap.parse_args()
    ov = {k: v for k, v in {"provider": a.provider, "model": a.model, "size": a.size}.items() if v}
    try:
        r = generate_shot(a.script, a.shot, a.n, ov) if a.shot else generate_all(a.script, a.n, ov)
    except ImageStudioError as e:
        sys.exit(f"[!] {e}")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if isinstance(r, dict) and r.get("failed"):
        sys.exit("[!] بعض اللقطات فشلت — شوف السجل")


if __name__ == "__main__":
    main()
