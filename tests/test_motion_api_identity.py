"""تحريك الـ API وثبات الشخصية: صورة النهاية، ممنوعات الهوية بالبرومبت السلبي، ونموذج Kling O1 المرجعي (أسماء الحقول من صفحات fal)."""

import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from test_motion_api import fal, spec, FAST, KEY  # noqa: E402,F401

import identity  # noqa: E402
import motion_api as ma  # noqa: E402

IMG, END = "data:image/jpeg;base64,IMG", "data:image/jpeg;base64,END"
REFS = {"front": "data:front", "three_quarter": "data:tq", "side": "data:side"}


def preset(key):
    return ma.validate_spec(ma.PRESETS[key])


# ───────────────────────── القوالب ─────────────────────────
def test_every_preset_validates_and_the_character_locks_are_on():
    for key in ma.PRESETS:
        assert ma.validate_spec(ma.PRESETS[key])["durations"]
    assert ma.PRESETS["kling26"]["end_image_field"] == "end_image_url" and ma.PRESETS["hailuo02"]["end_image_field"] == "end_image_url"
    assert ma.PRESETS["hailuo02"]["input"]["prompt_optimizer"] is False                  # بيعيد كتابة كلامنا وبيضيّع بطاقة الهوية
    assert "end_image_field" not in ma.PRESETS["grok"] and "end_image_field" not in ma.PRESETS["klingo1"]


def test_the_o1_preset_follows_the_documented_fields():
    p = ma.PRESETS["klingo1"]
    assert p["endpoint"] == "fal-ai/kling-video/o1/standard/reference-to-video"
    i = p["input"]
    assert i["image_urls"] == ["{image}"] and i["aspect_ratio"] == "9:16" and i["duration"] == "{duration_str}"
    assert i["elements"] == [{"frontal_image_url": "{ref_front}", "reference_image_urls": ["{ref_three_quarter}", "{ref_side}"]}]
    assert "@Image1" in i["prompt"] and "@Element1" in i["prompt"] and i["prompt"].endswith("{prompt}")
    assert p["durations"] == [3, 4, 5, 6, 7, 8, 9, 10] and "negative_prompt" not in i                 # O1 ما بياخد سلبي
    assert "faces" in p["strengths"] and "720p" in p["note"] and "مش مؤكَّد" in p["note"]


def test_spec_validation_keeps_or_rejects_the_end_image_field():
    assert ma.validate_spec(spec(end_image_field="end_image_url"))["end_image_field"] == "end_image_url"
    assert "end_image_field" not in ma.validate_spec(spec())
    assert "end_image_field" not in ma.validate_spec(spec(end_image_field=""))
    for bad in ("End-Image", "x", "a b", "../x", 5):
        with pytest.raises(ma.ApiMotionError, match="صورة النهاية"):
            ma.validate_spec(spec(end_image_field=bad))


# ───────────────────────── صورة النهاية ─────────────────────────
def test_the_end_image_goes_only_to_models_that_declare_the_field():
    k = ma.build_payload(preset("kling26"), IMG, "p", 5, end_uri=END)
    assert k["end_image_url"] == END and k["start_image_url"] == IMG
    h = ma.build_payload(preset("hailuo02"), IMG, "p", 6, end_uri=END)
    assert h["end_image_url"] == END and h["image_url"] == IMG and h["prompt_optimizer"] is False
    assert "end_image_url" not in ma.build_payload(preset("grok"), IMG, "p", 6, end_uri=END)
    assert "end_image_url" not in ma.build_payload(preset("kling26"), IMG, "p", 5)                # بلا end_uri بلا حقل
    assert "end_image_url" not in ma.build_payload(ma.validate_spec(spec()), IMG, "p", 5, end_uri=END)


# ───────────────────────── البرومبت السلبي ─────────────────────────
def test_identity_negatives_are_appended_without_replacing_or_duplicating():
    base = ma.PRESETS["kling26"]["input"]["negative_prompt"]
    pl = ma.build_payload(preset("kling26"), IMG, "p", 5, negative=identity.NEGATIVE)
    neg = pl["negative_prompt"]
    assert neg.startswith(base) and "East Asian facial features" in neg and "face morphing" in neg
    assert neg.lower().count("extra fingers") == 1 and len(neg) <= ma.MAX_NEGATIVE
    assert ma.build_payload(preset("kling26"), IMG, "p", 5)["negative_prompt"] == base          # بلا ممنوعات = متل ما كان
    for key in ("hailuo02", "grok", "klingo1"):
        assert "negative_prompt" not in ma.build_payload(preset(key), IMG, "p", 6, negative=identity.NEGATIVE, refs=REFS)


def test_merge_negative_is_case_insensitive_and_keeps_order():
    assert ma._merge_negative("blur, Extra Fingers", "extra fingers, different person,  ,blur") == "blur, Extra Fingers, different person"
    assert ma._merge_negative("", "a, b") == "a, b" and ma._merge_negative("a", "") == "a"
    assert len(ma._merge_negative("x" * 2000, "y" * 2000)) == ma.MAX_NEGATIVE


# ───────────────────────── Kling O1 المرجعي ─────────────────────────
def test_o1_receives_the_start_image_and_the_character_sheets_as_an_element():
    pl = ma.build_payload(preset("klingo1"), IMG, "She smiles slightly", 4, refs=REFS)
    assert pl["image_urls"] == [IMG] and pl["duration"] == "4" and pl["aspect_ratio"] == "9:16"
    assert pl["elements"] == [{"frontal_image_url": "data:front", "reference_image_urls": ["data:tq", "data:side"]}]
    assert pl["prompt"].startswith("Start from @Image1 as the first frame. The person is @Element1") and pl["prompt"].endswith("She smiles slightly")


def test_missing_reference_views_are_dropped_from_the_request():
    pl = ma.build_payload(preset("klingo1"), IMG, "p", 4, refs={"front": "data:front", "three_quarter": "data:tq"})
    assert pl["elements"][0]["reference_image_urls"] == ["data:tq"]
    only = ma.build_payload(preset("klingo1"), IMG, "p", 4, refs={"front": "data:front"})
    assert only["elements"] == [{"frontal_image_url": "data:front"}]
    none = ma.build_payload(preset("klingo1"), IMG, "p", 4)
    assert "elements" not in none and none["image_urls"] == [IMG]                              # بلا «أمام» العنصر كله بيروح
    nofront = ma.build_payload(preset("klingo1"), IMG, "p", 4, refs={"three_quarter": "data:tq"})
    assert "elements" not in nofront


def test_prompt_text_is_never_scanned_for_placeholders():
    pl = ma.build_payload(preset("klingo1"), IMG, "استعمل {ref_front} حرفياً", 4, refs=REFS)
    assert pl["prompt"].endswith("استعمل {ref_front} حرفياً")


def test_needs_refs_reads_the_template():
    assert ma.needs_refs(preset("klingo1")) == {"front", "three_quarter", "side"}
    assert ma.needs_refs(preset("kling26")) == set() and ma.needs_refs({}) == set()


# ───────────────────────── التشغيل الكامل ─────────────────────────
def sheets(tmp, *views):
    out = {}
    for v in views:
        p = tmp / f"{v}.png"
        Image.new("RGB", (64, 96), (200, 150, 120)).save(p)
        out[v] = p
    return out


def posted(fal):
    return next(b for m, path, a, b in fal.requests if m == "POST")


def test_run_job_sends_the_end_frame_and_identity_negatives(fal):
    s = ma.validate_spec(ma.PRESETS["kling26"])
    out = fal.tmp / "clips" / "raw.mp4"
    logs = []
    ma.run_job(s, fal.img, "calm", 4, out, log=logs.append, end_image=fal.img, negative=identity.NEGATIVE, **FAST)
    body = posted(fal)
    assert body["end_image_url"].startswith("data:image/jpeg;base64,") and "East Asian facial features" in body["negative_prompt"]
    assert any("صورة نهاية" in m for m in logs) and out.exists()
    fal.requests.clear()
    ma.run_job(s, fal.img, "calm", 4, fal.tmp / "clips" / "b.mp4", **FAST)
    body = posted(fal)
    assert "end_image_url" not in body and body["negative_prompt"] == ma.PRESETS["kling26"]["input"]["negative_prompt"]


def test_run_job_ignores_an_end_frame_for_models_without_the_field(fal):
    s = ma.validate_spec(ma.PRESETS["grok"])
    ma.run_job(s, fal.img, "calm", 6, fal.tmp / "clips" / "g.mp4", end_image=fal.img, **FAST)
    assert "end_image_url" not in posted(fal) and not any("صورة نهاية" in str(x) for x in posted(fal).values())


def test_run_job_o1_uploads_only_the_sheets_the_template_asks_for(fal):
    s = ma.validate_spec(ma.PRESETS["klingo1"])
    logs = []
    ma.run_job(s, fal.img, "calm", 3, fal.tmp / "clips" / "o.mp4", log=logs.append,
               refs=sheets(fal.tmp, "front", "three_quarter", "side", "hands"), **FAST)
    body = posted(fal)
    el = body["elements"][0]
    assert el["frontal_image_url"].startswith("data:image/jpeg;base64,") and len(el["reference_image_urls"]) == 2
    assert body["image_urls"][0].startswith("data:image/jpeg;base64,") and body["duration"] == "3"
    assert any("مراجع الشخصية" in m for m in logs)
    assert "hands" not in str(body)                                                              # وضعية مش مطلوبة ما بتنبعت


def test_run_job_o1_without_a_front_sheet_fails_clearly_before_any_request(fal):
    s = ma.validate_spec(ma.PRESETS["klingo1"])
    for refs in (None, {}, sheets(fal.tmp, "three_quarter")):
        with pytest.raises(ma.ApiMotionError, match="«أمام»"):
            ma.run_job(s, fal.img, "calm", 3, fal.tmp / "clips" / "o.mp4", refs=refs, **FAST)
    assert fal.requests == []


def test_the_estimate_for_o1_uses_the_duration_it_will_bill():
    s = preset("klingo1")
    assert ma.pick_duration(s, 2.1) == 3 and ma.estimate_cost(s, 2.1) == pytest.approx(0.336)
    assert ma.estimate_cost(s, 3.4) == pytest.approx(0.448) and ma.estimate_cost(s, 11) is None
