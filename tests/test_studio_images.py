"""استوديو الإنتاج — المحطة ٧ (الصور) والمحطة ٨ (فحص التطابق) وملف المنتج المرجعي."""

import io
import json
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
import test_studio_voice_timeline as tv  # noqa: E402
import test_studio_characters_shots as tc  # noqa: E402

import characters  # noqa: E402
import config  # noqa: E402
import image_studio as ims  # noqa: E402
import imagegen  # noqa: E402
import product_ref  # noqa: E402
import shot_prompts  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import voice_studio  # noqa: E402


def png_bytes(size=(64, 64), color=(200, 30, 30, 255), alpha_hole=False, corner=False):
    im = Image.new("RGBA", size, color)
    if corner:
        im.putpixel((0, 0), (0, 0, 0, 0))
    if alpha_hole:
        im.paste((0, 0, 0, 0), (0, 0, size[0] // 4, size[1]))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def stage(env, monkeypatch):
    """مرحلة جاهزة: صوت وخط زمني وبرومبتات معتمدة، ومولّد صور مزيّف."""
    st = tv.produce_ok(env, monkeypatch)
    ch = tc.mk(env, name="ريم")
    characters.choose("s1", json.loads(st.script.read_text(encoding="utf-8")), ch["id"])
    voice_studio.approve_voice(st.script)
    tl = timeline.load("s1")
    shot_prompts.build(tl, json.loads(st.script.read_text(encoding="utf-8")), "كاما", ch, "testp")
    timeline.save("s1", tl)
    studio_state.set_state("s1", 6, "approved", "x")

    st.calls = []
    st.size = (1024, 1536)

    def fake_generate(visual, out, overrides=None, extra="", refs=None, ref_roles=None):
        st.calls.append({"visual": visual, "refs": [r.name for r in (refs or [])], "ov": overrides, "roles": ref_roles})
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", st.size, (40, 90, 160)).save(out, "PNG")
        return {"path": str(out), "prompt": visual, "provider": "fake", "model": "img-1",
                "refs_used": [r.name for r in (refs or [])], "size": 5000}

    monkeypatch.setattr(imagegen, "generate", fake_generate)
    import usage
    monkeypatch.setattr(usage, "record", lambda *a, **k: None)
    st.ch = ch
    return st


def first_shot(tl, typ=None):
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if typ is None or sh["type"] == typ:
                return sh
    return None


# ───────────────────────── تجهيز الإطار ─────────────────────────
def test_ensure_frame_crops_to_9_16_and_upscales_lanczos(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (1024, 1536), (1, 2, 3)).save(src)
    info = ims.ensure_frame(src, tmp_path / "o.png")
    assert (info["w"], info["h"]) == (1080, 1920) and info["upscaled"] and info["cropped"] and info["method"] == "lanczos"
    assert Image.open(tmp_path / "o.png").size == (1080, 1920)


def test_ensure_frame_keeps_full_size_untouched(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (1080, 1920)).save(src)
    info = ims.ensure_frame(src, tmp_path / "o.png")
    assert not info["upscaled"] and not info["cropped"]
    src2 = tmp_path / "b.png"
    Image.new("RGB", (2160, 3840)).save(src2)
    info2 = ims.ensure_frame(src2, tmp_path / "o2.png")
    assert (info2["w"], info2["h"]) == (2160, 3840) and not info2["upscaled"]


# ───────────────────────── التوليد ─────────────────────────
def test_generate_shot_makes_candidates_with_refs_and_relative_paths(stage):
    tl = timeline.load("s1")
    sh = first_shot(tl)
    r = ims.generate_shot(stage.script, sh["id"], n=2, log=lambda *_: None)
    assert r["made"] == 2 and r["budget"]["used"] == 2
    tl = timeline.load("s1")
    cands = first_shot(tl)["image"]["candidates"]
    assert len(cands) == 2 and all(":\\" not in c["path"] and not c["path"].startswith("/") for c in cands)
    assert all(ims.abs_of("s1", c["path"]) for c in cands)
    assert timeline.validate(tl)["ok"]
    assert studio_state.state_of("s1", 7) == "awaiting_choice"
    call = stage.calls[0]
    assert "front.png" in call["refs"] and "three_quarter.png" in call["refs"]      # مرجع الشخصية
    assert call["roles"] == ["person", "person"]                                    # كل صورة بدورها (الشخص أول)
    # الترجمة بالذكاء مش متاحة بالاختبار → بيروح بطاقة هوية الشخصية (إنجليزي) + البرومبت العربي
    assert call["visual"].startswith("Subject (identical in every shot): a 32-year-old Syrian (Levantine Arab) woman")
    assert call["visual"].endswith(sh["prompt_ar"])


def test_model_prompt_is_preferred_and_hand_shots_use_hands_sheet(stage):
    tl = timeline.load("s1")
    sh = first_shot(tl)
    sh["prompt_model"] = "english prompt. No text."
    hand = next(s for sc in tl["scenes"] for s in sc["shots"] if s["type"] == "hand_product")
    timeline.save("s1", tl)
    ims.generate_shot(stage.script, sh["id"], n=1, log=lambda *_: None)
    assert stage.calls[-1]["visual"].startswith("english prompt")
    ims.generate_shot(stage.script, hand["id"], n=1, log=lambda *_: None)
    assert stage.calls[-1]["refs"] == ["hands.png"]


def test_product_front_cutout_is_attached_as_reference(stage):
    product_ref.set_angle("testp", "front", png_bytes(alpha_hole=True))
    sh = first_shot(timeline.load("s1"))
    ims.generate_shot(stage.script, sh["id"], n=1, log=lambda *_: None)
    assert "front.png" in stage.calls[-1]["refs"] and len(stage.calls[-1]["refs"]) == 3
    assert stage.calls[-1]["roles"] == ["person", "person", "product"]


def test_images_need_approved_prompts_station(stage):
    studio_state.set_state("s1", 6, "awaiting_choice", "x")
    with pytest.raises(ims.ImageStudioError):
        ims.generate_shot(stage.script, first_shot(timeline.load("s1"))["id"], n=1, log=lambda *_: None)
    assert stage.calls == []


def test_per_video_call_cap_stops_generation(stage, monkeypatch):
    monkeypatch.setattr(config, "STUDIO_MAX_IMAGE_CALLS", 3)
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    ims.generate_shot(stage.script, ids[0], n=2, log=lambda *_: None)
    with pytest.raises(ims.ImageStudioError) as e:
        ims.generate_shot(stage.script, ids[1], n=2, log=lambda *_: None)
    assert "حد نداءات" in str(e.value) and len(stage.calls) == 3
    assert ims.budget("s1") == {"used": 3, "cap": 3, "left": 0}
    assert studio_state.state_of("s1", 7) == "failed"


def test_generate_all_skips_done_shots_and_continues_after_a_failure(stage, monkeypatch):
    tl = timeline.load("s1")
    ids = [s["id"] for sc in tl["scenes"] for s in sc["shots"]]
    ims.generate_shot(stage.script, ids[0], n=1, log=lambda *_: None)
    real = imagegen.generate

    def flaky(visual, out, overrides=None, extra="", refs=None, ref_roles=None):
        if "s1c2" in out.name:
            raise imagegen.ImageError("مزوّد مشغول")
        return real(visual, out, overrides, extra, refs, ref_roles)

    monkeypatch.setattr(imagegen, "generate", flaky)
    r = ims.generate_all(stage.script, n=1, log=lambda *_: None)
    assert ids[0] not in r["done"] and any(f["shot"] == "s1c2" for f in r["failed"])
    assert len(r["done"]) == len(ids) - 2


# ───────────────────────── الاختيار ─────────────────────────
def gen_and_choose(stage, typ=None):
    sh = first_shot(timeline.load("s1"), typ)
    ims.generate_shot(stage.script, sh["id"], n=1, log=lambda *_: None)
    cand = first_shot(timeline.load("s1"), typ)["image"]["candidates"][0]["path"]
    return sh["id"], cand


def test_choose_processes_to_1080x1920_and_resets_checks(stage):
    sid, cand = gen_and_choose(stage)
    tl = timeline.load("s1")
    _sc, sh = ims._shot(tl, sid)
    sh["product_check"] = {"status": "pass"}
    tl["checks_approved_by_owner"][sid] = {"verdict": "pass", "note": ""}
    timeline.save("s1", tl)
    out = ims.choose(stage.script, sid, cand)
    im = out["image"]
    assert im["upscaled"] and im["upscale_method"] == "lanczos" and im["cropped"]
    assert Image.open(ims.abs_of("s1", im["chosen"])).size == (1080, 1920)
    tl = timeline.load("s1")
    assert timeline.load("s1") and sid not in tl["checks_approved_by_owner"] and ims._shot(tl, sid)[1]["product_check"] is None
    with pytest.raises(ims.ImageStudioError):
        ims.choose(stage.script, sid, "img/other.png")


def test_approve_images_needs_every_shot_chosen(stage):
    sid, cand = gen_and_choose(stage)
    ims.choose(stage.script, sid, cand)
    with pytest.raises(ims.ImageStudioError):
        ims.approve_images(stage.script)
    tl = timeline.load("s1")
    ids = [s["id"] for sc in tl["scenes"] for s in sc["shots"] if s["id"] != sid]
    for other in ids:
        ims.generate_shot(stage.script, other, n=1, log=lambda *_: None)
        c = ims._shot(timeline.load("s1"), other)[1]["image"]["candidates"][0]["path"]
        ims.choose(stage.script, other, c)
    assert ims.approve_images(stage.script)["approved"]
    assert studio_state.state_of("s1", 7) == "approved"


# ───────────────────────── تركيب المنتج ─────────────────────────
def test_composite_places_real_product_at_the_computed_size(stage):
    tl = timeline.load("s1")
    close = first_shot(tl, "close")
    assert close, "لازم في لقطة قريبة"
    product_ref.set_angle("testp", "front", png_bytes((100, 200), (250, 0, 0, 255), corner=True))
    sid, cand = gen_and_choose(stage, "close")
    ims.choose(stage.script, sid, cand)
    sh = ims.composite(stage.script, sid, 0.5, 0.6)
    assert sh["product_check"]["mode"] == "composite" and sh["product_check"]["status"] == "pass"
    assert abs(sh["product_check"]["size_ratio"] - 1.0) <= ims.TOLERANCE
    out = Image.open(ims.abs_of("s1", sh["image"]["composite"])).convert("RGB")
    assert out.size == (1080, 1920)
    r, g, b = out.getpixel((540, round(1920 * 0.6)))
    assert r > 180 and g < 80 and b < 80                       # لون المنتج الحقيقي عند مركزه
    assert out.getpixel((10, 10)) != (r, g, b)
    # قياس عرض المنتج: نسبة الأحمر بصف المركز ≈ RATIO["close"] × 1080
    row = [out.getpixel((x, round(1920 * 0.6))) for x in range(1080)]
    red = sum(1 for p in row if p[0] > 180 and p[1] < 80 and p[2] < 80)
    assert abs(red - 1080 * ims.RATIO["close"]) <= 1080 * ims.RATIO["close"] * ims.TOLERANCE + 4


def test_composite_refuses_wrong_shot_type_missing_ref_and_off_frame(stage):
    tl = timeline.load("s1")
    wide = first_shot(tl, "wide") or first_shot(tl, "medium")
    close = first_shot(tl, "close")
    sid, cand = gen_and_choose(stage, wide["type"])
    ims.choose(stage.script, sid, cand)
    product_ref.set_angle("testp", "front", png_bytes(alpha_hole=True))
    with pytest.raises(ims.ImageStudioError):
        ims.composite(stage.script, sid)                      # نوع غلط
    cid, ccand = gen_and_choose(stage, "close")
    with pytest.raises(ims.ImageStudioError):
        ims.composite(stage.script, cid)                      # ما اختار صورة
    ims.choose(stage.script, cid, ccand)
    with pytest.raises(ims.ImageStudioError):
        ims.composite(stage.script, cid, 1.5, 0.5)            # خارج الإطار
    import shutil
    shutil.rmtree(product_ref.dir_of("testp"))
    with pytest.raises(ims.ImageStudioError):
        ims.composite(stage.script, cid)                      # ما في صورة منتج


# ───────────────────────── الفحص الآلي وحكم المالك ─────────────────────────
def test_label_ocr_pass_fail_and_unchecked_without_label(stage):
    product_ref.set_details("testp", label_text="ماء الكمأة قطرة عينية")
    sid, cand = gen_and_choose(stage, "close")
    ims.choose(stage.script, sid, cand)
    ok = ims.check_shot(stage.script, sid, ocr=lambda p: "ماء الكمأة قطرة عينية 10 مل")
    assert ok["product_check"]["status"] == "pass" and ok["product_check"]["size_ratio"] is None
    bad = ims.check_shot(stage.script, sid, ocr=lambda p: "نص مختلف تماماً")
    assert bad["product_check"]["status"] == "fail" and bad["product_check"]["label_match"] is False
    boom = ims.check_shot(stage.script, sid, ocr=lambda p: (_ for _ in ()).throw(RuntimeError("no gpu")))
    assert boom["product_check"]["status"] == "unchecked"
    shutil_label = product_ref.dir_of("testp") / "ref.json"
    shutil_label.write_text(json.dumps({**product_ref.load("testp"), "label_text": ""}), encoding="utf-8")
    none = ims.check_shot(stage.script, sid, ocr=lambda p: "x")
    assert none["product_check"]["status"] == "unchecked" and "ما في نص ملصق" in none["product_check"]["note"]


def test_face_and_size_are_never_faked_as_measured(stage):
    sid, cand = gen_and_choose(stage, "medium")
    ims.choose(stage.script, sid, cand)
    sh = ims.check_shot(stage.script, sid, ocr=lambda p: "")
    # صور الشخصية بالاختبار مش وجوه حقيقية: يا «ما في مرجع صالح» (الموديل موجود) يا «غير مقاس» (الموديل مش منزّل) — مش «ناجح» أبداً
    assert sh["face_check"]["status"] in ("no_ref", "unchecked") and sh["face_check"]["similarity"] is None
    hand = first_shot(timeline.load("s1"), "hand_product")
    hid, hcand = gen_and_choose(stage, "hand_product")
    ims.choose(stage.script, hid, hcand)
    assert ims.check_shot(stage.script, hid, ocr=lambda p: "")["face_check"] is None


def test_composite_shot_passes_check_without_ocr(stage):
    product_ref.set_angle("testp", "front", png_bytes(alpha_hole=True))
    sid, cand = gen_and_choose(stage, "close")
    ims.choose(stage.script, sid, cand)
    ims.composite(stage.script, sid)
    out = ims.check_shot(stage.script, sid, ocr=lambda p: (_ for _ in ()).throw(AssertionError("لا OCR")))
    assert out["product_check"]["mode"] == "composite" and out["product_check"]["status"] == "pass"


def test_verdict_rules_and_match_approval(stage):
    tl = timeline.load("s1")
    ids = [s["id"] for sc in tl["scenes"] for s in sc["shots"]]
    for sid in ids:
        ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
        c = ims._shot(timeline.load("s1"), sid)[1]["image"]["candidates"][0]["path"]
        ims.choose(stage.script, sid, c)
    ims.approve_images(stage.script)
    with pytest.raises(ims.ImageStudioError):
        ims.set_verdict(stage.script, ids[0], "maybe")
    with pytest.raises(ims.ImageStudioError):
        ims.set_verdict(stage.script, ids[0], "fail", "")
    with pytest.raises(ims.ImageStudioError):
        ims.approve_match(stage.script)                       # لسا ما حكم على أي لقطة
    assert len(ims.match_problems(timeline.load("s1"))) == len(ids)
    for sid in ids[:-1]:
        ims.set_verdict(stage.script, sid, "pass")
    ims.set_verdict(stage.script, ids[-1], "fail", "الوجه مختلف")
    with pytest.raises(ims.ImageStudioError) as e:
        ims.approve_match(stage.script)
    assert "ساقطة" in str(e.value)
    ims.set_verdict(stage.script, ids[-1], "override", "اعتمدتها رغم الاختلاف الطفيف")
    assert ims.approve_match(stage.script)["approved"]
    assert studio_state.state_of("s1", 8) == "approved"
    # تغيير حكم بعد الاعتماد ← بترجع بانتظار
    ims.set_verdict(stage.script, ids[0], "fail", "قرار جديد")
    assert studio_state.state_of("s1", 8) == "awaiting_choice"


def test_failed_label_needs_explicit_owner_decision(stage):
    product_ref.set_details("testp", label_text="نص الملصق")
    sid, cand = gen_and_choose(stage, "close")
    ims.choose(stage.script, sid, cand)
    ims.check_shot(stage.script, sid, ocr=lambda p: "غلط")
    msgs = " | ".join(p["message"] for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid)
    assert "ما تطابق" in msgs
    ims.set_verdict(stage.script, sid, "override", "الملصق بالمنتج الحقيقي مطابق")
    assert not [p for p in ims.match_problems(timeline.load("s1")) if p["shot"] == sid]


# ───────────────────────── ملف المنتج المرجعي ─────────────────────────
def test_product_ref_requires_transparent_png_and_valid_details(env):
    with pytest.raises(product_ref.ProductRefError):
        product_ref.set_angle("kama", "front", png_bytes())                 # بلا شفافية
    with pytest.raises(product_ref.ProductRefError):
        product_ref.set_angle("kama", "front", b"not an image")
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "JPEG")
    with pytest.raises(product_ref.ProductRefError):
        product_ref.set_angle("kama", "front", buf.getvalue())
    with pytest.raises(product_ref.ProductRefError):
        product_ref.set_angle("kama", "diagonal", png_bytes(alpha_hole=True))
    ref = product_ref.set_angle("kama", "front", png_bytes(alpha_hole=True))
    assert ref["angles"]["front"] == "angles/front.png" and product_ref.can_composite("kama")
    assert "زاوية: خلف" in product_ref.missing(ref) and "نص الملصق الحرفي" in product_ref.missing(ref)
    with pytest.raises(product_ref.ProductRefError):
        product_ref.set_details("kama", dims_cm={"h": "abc"})
    with pytest.raises(product_ref.ProductRefError):
        product_ref.set_details("kama", dims_cm={"h": 900})
    ref = product_ref.set_details("kama", dims_cm={"h": 9, "w": 3, "d": 3}, label_text="ماء الكمأة", colors=["أبيض", "أزرق"])
    assert product_ref.missing(ref) == [f"زاوية: {product_ref.ANGLES[a]}" for a in ("back", "left", "right", "top", "bottom")]
    with pytest.raises(product_ref.ProductRefError):
        product_ref.load("../..")


# ───────────────────────── API ─────────────────────────
def test_api_images_and_match_flow(stage):
    c = tc.client()
    info = c.get("/api/studio/s1.json/images/info").json()
    assert info["budget"]["used"] == 0 and info["problems"] and info["product_code"] == "testp"
    assert c.post("/api/studio/s1.json/images/generate").status_code == 200
    assert stage.env.jobs[-1]["cmd"][:2] == ["image_studio.py", "gen"]
    studio_state.set_state("s1", 6, "awaiting_choice", "x")
    assert c.post("/api/studio/s1.json/images/generate").status_code == 409
    studio_state.set_state("s1", 6, "approved", "x")

    sid = first_shot(timeline.load("s1"))["id"]
    ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
    cand = first_shot(timeline.load("s1"))["image"]["candidates"][0]["path"]
    assert c.get(f"/api/studio/s1.json/img/{cand}").status_code == 200
    assert c.get("/api/studio/s1.json/img/../../../etc/passwd").status_code in (404, 400)
    assert c.get("/api/studio/s1.json/img/..%2F..%2Fstate.json").status_code == 404
    assert c.post(f"/api/studio/s1.json/shots/{sid}/choose", json={"path": "nope.png"}).status_code == 409
    assert c.post(f"/api/studio/s1.json/shots/{sid}/choose", json={"path": cand}).status_code == 200
    assert c.post(f"/api/studio/s1.json/shots/{sid}/verdict", json={"verdict": "fail"}).status_code == 409
    assert c.post(f"/api/studio/s1.json/shots/{sid}/verdict", json={"verdict": "pass"}).status_code == 200
    assert c.post("/api/studio/s1.json/images/approve").status_code == 409     # لقطات ناقصة
    assert c.post("/api/studio/s1.json/match/approve").status_code == 409


def test_api_product_ref_endpoints(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_characters
    app = FastAPI()
    app.include_router(routes_characters.router)
    c = TestClient(app)
    r = c.post("/api/product-refs/kama/angle/front", files={"file": ("f.png", png_bytes(alpha_hole=True), "image/png")})
    assert r.status_code == 200 and r.json()["angles"]["front"]
    assert c.post("/api/product-refs/kama/angle/front", files={"file": ("f.png", png_bytes(), "image/png")}).status_code == 400
    assert c.put("/api/product-refs/kama", json={"dims_cm": {"h": 9, "w": 3, "d": 3}, "label_text": "ماء"}).status_code == 200
    got = c.get("/api/product-refs/kama").json()
    assert got["can_composite"] and got["label_text"] == "ماء"
    assert c.get("/api/product-refs/kama/angle/front").status_code == 200
    assert c.get("/api/product-refs/kama/angle/back").status_code == 404
    assert c.get("/api/product-refs/!!!").status_code == 400
