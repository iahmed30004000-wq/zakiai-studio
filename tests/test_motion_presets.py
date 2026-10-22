"""الحركات السينمائية: بيانات الوصفات، وصفات المالك، التطبيق على لقطة، كلام الكاميرا لكل موديل، الترتيب، الأمثلة، والمسارات."""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage  # noqa: E402,F401
from test_studio_motion import lavfi, model, ready  # noqa: E402,F401
from test_motion_api import fal, spec  # noqa: E402,F401

import config  # noqa: E402
import image_studio as ims  # noqa: E402
import motion  # noqa: E402
import motion_api  # noqa: E402
import motion_presets as mp  # noqa: E402
import timeline  # noqa: E402

HAILUO_COMMANDS = {"Truck left", "Truck right", "Pan left", "Pan right", "Push in", "Pull out", "Pedestal up", "Pedestal down",
                   "Tilt up", "Tilt down", "Zoom in", "Zoom out", "Shake", "Tracking shot", "Static shot"}


def arabic(t):
    return any(0x600 <= ord(c) <= 0x6FF for c in t)


def good(**kw):
    d = {"name_ar": "حركتي", "category": "camera", "desc_ar": "وصف", "recipes": {"default": "A slow push toward the product"},
         "camera_move": True, "duration_s": [3, 5], "best_for": ["close"], "prefer": ["kling"]}
    d.update(kw)
    return d


def shot_id(stage, typ=None):
    for sc in timeline.load("s1")["scenes"]:
        for s in sc["shots"]:
            if typ is None or s["type"] == typ:
                return s["id"]


@pytest.fixture
def lib(env):
    return env.lib


def tc_client():
    """مسارات الوصفات + التحريك + الاستوديو بتطبيق وحد."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_motion, routes_presets, routes_studio
    app = FastAPI()
    for r in (routes_presets, routes_motion, routes_studio):
        app.include_router(r.router)
    return TestClient(app)


# ───────────────────────── الوصفات الجاهزة ─────────────────────────
def test_the_shipped_presets_are_well_formed():
    ps = mp.base()["presets"]
    ids = [p["id"] for p in ps]
    assert len(ids) == len(set(ids)) >= 20 and all(mp.ID_RX.match(i) for i in ids)
    cats = {c["id"] for c in mp.categories()}
    assert cats == {"camera", "product", "character"}
    for p in ps:
        assert p["category"] in cats and arabic(p["name_ar"]) and arabic(p["desc_ar"]) and arabic(p["motion_desc_ar"]), p["id"]
        assert isinstance(p["camera_move"], bool) and set(p["recipes"]) <= set(mp.FAMILIES) and p["recipes"]["default"], p["id"]
        for fam, t in p["recipes"].items():
            assert not arabic(t) and 10 < len(t) <= mp.MAX_RECIPE, (p["id"], fam)
        lo, hi = p["duration_s"]
        assert 1 <= lo <= hi <= 15 and set(p["best_for"]) <= set(mp.SHOT_TYPES) and set(p["prefer"]) <= set(mp.FAMILIES), p["id"]


def test_all_fifteen_hailuo_director_commands_are_covered_and_follow_the_bracket_style():
    used = set()
    for p in mp.base()["presets"]:
        h = p["recipes"].get("hailuo", "")
        for m in re.findall(r"\[([^\]]+)\]", h):
            used.update(x.strip() for x in m.split(","))
        assert len(re.findall(r"\[", h)) <= 1, p["id"]                                          # أمر واحد بالوصفة (الدمج حد 3 بس نحن بنكتفي بواحد)
    assert used == HAILUO_COMMANDS
    for p in mp.base()["presets"]:
        h = p["recipes"].get("hailuo", "")
        if h.startswith("["):
            assert len(h.split("] ", 1)[1]) > 15                                                 # أمر + جملة طبيعية (Hailuo 02 مش مؤكَّدة رسمياً)


def test_still_presets_never_look_like_camera_moves_to_the_fallback_detector():
    for p in mp.base()["presets"]:
        if not p["camera_move"]:
            assert not motion._CAMERA_MOVE_RX.search(p["motion_desc_ar"]), p["id"]
            assert not motion._CAMERA_MOVE_RX.search(p["recipes"]["default"]), p["id"]
    still = {p["id"] for p in mp.base()["presets"] if not p["camera_move"]}
    assert {"static", "face_breath", "look_camera", "hand_present", "product_spin"} <= still


def test_the_lens_tables_match_the_open_source_tables_we_credit():
    t = mp.looks()
    assert [len(t[k]) for k in ("cameras", "lenses", "focals", "apertures")] == [6, 11, 6, 3]
    assert {c["en"] for c in t["cameras"]} >= {"classic 16mm film camera", "Super 35 studio digital camera"}
    assert {x["mm"]: x["en"] for x in t["focals"]} == {8: "ultra-wide perspective", 14: "wide-angle perspective", 24: "wide-angle dynamic perspective",
                                                       35: "natural cinematic perspective", 50: "standard portrait perspective", 85: "classic portrait perspective"}
    assert [a["en"] for a in t["apertures"]] == ["shallow depth of field, creamy bokeh", "balanced depth of field", "deep focus clarity, sharp foreground to background"]
    notice = (mp.BASE_PATH.parent.parent / "third_party" / "open-generative-ai" / "NOTICE").read_text(encoding="utf-8")
    assert "MIT License" in notice and "Open Generative AI Contributors" in notice and "CinemaStudio.jsx" in notice


# ───────────────────────── العائلة والكلام ─────────────────────────
@pytest.mark.parametrize("m,fam", [
    ({"kind": "api", "name": "Hailuo 02 Standard (fal)", "api": {"endpoint": "fal-ai/minimax/hailuo-02/standard/image-to-video"}}, "hailuo"),
    ({"kind": "api", "name": "x", "api": {"endpoint": "fal-ai/minimax/video-01"}}, "hailuo"),
    ({"kind": "api", "name": "Kling 2.6 Pro", "api": {"endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video"}}, "kling"),
    ({"kind": "api", "name": "Kling O1 — من المراجع", "api": {"endpoint": "fal-ai/kling-video/o1/standard/reference-to-video"}}, "kling"),
    ({"kind": "api", "name": "Grok", "api": {"endpoint": "xai/grok-imagine-video/image-to-video"}}, "grok"),
    ({"kind": "api", "name": "غريب", "api": {"endpoint": "fal-ai/other/model"}}, "default"),
    ({"kind": "http", "name": "LTX"}, "local"), ({"kind": "command", "name": "Wan"}, "local"), ({"name": "بلا نوع"}, "local"), (None, "default"),
])
def test_family_detection(m, fam):
    assert mp.family_of(m) == fam


def test_recipe_text_falls_back_to_the_default():
    p = mp.get("push_in")
    assert mp.recipe_text(p, "hailuo").startswith("[Push in] ") and mp.recipe_text(p, "kling").startswith("The camera slowly pushes in")
    assert mp.recipe_text(p, "grok") == mp.recipe_text(p, "default") == mp.recipe_text(p, "local") == p["recipes"]["default"]


def test_the_look_sentence_follows_the_open_source_wording():
    full = {"camera": "classic_16mm", "lens": "vintage_prime", "focal": "35", "aperture": "4"}
    assert mp.look_text(full) == ("shot on a classic 16mm film camera, using a vintage prime lens at 35mm (natural cinematic perspective), "
                                  "aperture f/4 (balanced depth of field)")
    assert mp.look_text({"lens": "halation"}) == "using a halation diffusion filter"
    assert mp.look_text({"focal": "85"}) == "at 85mm (classic portrait perspective)"
    assert mp.look_text({"camera": "grand_70mm", "aperture": "1.4"}) == "shot on a grand format 70mm film camera, aperture f/1.4 (shallow depth of field, creamy bokeh)"
    assert mp.look_text({}) == "" and mp.look_text(None) == "" and mp.look_text({"camera": "nope"}) == ""


def test_clean_look_keeps_valid_choices_only():
    assert mp.clean_look({"camera": "classic_16mm", "lens": "nope", "focal": "35", "aperture": "99", "x": 1}) == {"camera": "classic_16mm", "focal": "35"}
    assert mp.clean_look("x") == {} and mp.clean_look(None) == {}


# ───────────────────────── وصفات المالك ─────────────────────────
def test_the_owner_can_add_edit_and_remove_recipes_without_code(lib):
    base_n = len(mp.all_presets())
    p = mp.create(good(recipes={"default": "A slow push toward the product", "kling": "Slowly push in", "hailuo": "[Push in] slow"}))
    assert p["id"] == "custom" and p["custom"] is True and p["overridden"] is False and len(mp.all_presets()) == base_n + 1
    assert mp.create(good(name_ar="حركة تانية"))["id"] == "custom_2"
    assert json.loads(mp.user_path().read_text(encoding="utf-8"))["presets"][0]["name_ar"] == "حركتي"
    assert not list(mp.user_path().parent.glob("*.tmp"))
    upd = mp.update("custom", good(name_ar="اسم جديد", camera_move=False))
    assert upd["name_ar"] == "اسم جديد" and upd["camera_move"] is False and upd["custom"] is True and len(mp.all_presets()) == base_n + 2
    mp.delete("custom")
    assert mp.get("custom") is None and len(mp.all_presets()) == base_n + 1


def test_editing_a_shipped_recipe_overrides_it_and_deleting_the_edit_restores_it(lib):
    orig = mp.get("push_in")
    new = mp.update("push_in", good(name_ar="دفع مخصّص", desc_ar="خاص بي"))
    assert new["overridden"] is True and new["custom"] is False and new["name_ar"] == "دفع مخصّص" and len(mp.all_presets()) == len(mp.base()["presets"])
    assert mp.all_presets()[[p["id"] for p in mp.all_presets()].index("push_in")]["name_ar"] == "دفع مخصّص"
    back = mp.delete("push_in")
    assert back["name_ar"] == orig["name_ar"] and back["overridden"] is False
    with pytest.raises(mp.PresetError, match="ما بتنحذف"):
        mp.delete("push_in")                                                               # الأصلية ما بتنحذف
    with pytest.raises(mp.PresetError, match="غير موجودة"):
        mp.delete("nope")
    with pytest.raises(mp.PresetError, match="غير موجودة"):
        mp.update("nope", good())


@pytest.mark.parametrize("bad,msg", [
    ({"name_ar": "ا"}, "اسم الوصفة"), ({"name_ar": "ا" * 41}, "اسم الوصفة"), ({"category": "x"}, "القسم"),
    ({"desc_ar": "ا" * 201}, "200"), ({"motion_desc_ar": "ا" * 301}, "300"),
    ({"recipes": {}}, "العام"), ({"recipes": {"default": "  "}}, "العام"), ({"recipes": {"kling": "only kling"}}, "العام"),
    ({"recipes": {"default": "حركة بطيئة"}}, "بالإنجليزي"), ({"recipes": {"default": "x" * 401}}, "400"),
    ({"recipes": {"default": "ok text here", "mystery": "x"}}, "غير معروفة"),
    ({"duration_s": ["a", 3]}, "رقمين"), ({"duration_s": [0, 3]}, "1 و15"), ({"duration_s": [5, 3]}, "1 و15"), ({"duration_s": [3, 99]}, "1 و15"),
])
def test_recipe_validation_gives_arabic_reasons(lib, bad, msg):
    with pytest.raises(mp.PresetError, match=msg):
        mp.create(good(**bad))
    assert not mp.user_path().exists()                                                       # ما انكتب شي


def test_validation_normalises_the_optional_fields(lib):
    p = mp.create(good(best_for=["close", "nope"], prefer=["kling", "default", "x"], motion_desc_ar="", desc_ar="وصف قصير"))
    assert p["best_for"] == ["close"] and p["prefer"] == ["kling"] and p["motion_desc_ar"] == "وصف قصير"
    q = mp.create(good(name_ar="ثانية", best_for=[], duration_s=None, recipes={"default": "  a   slow  \n move  "}))
    assert q["best_for"] == list(mp.SHOT_TYPES) and q["duration_s"] == [3.0, 5.0] and q["recipes"]["default"] == "a slow move"


def test_a_corrupt_owner_file_is_ignored(lib):
    mp.user_path().write_text("{not json", encoding="utf-8")
    assert len(mp.all_presets()) == len(mp.base()["presets"])
    mp.user_path().write_text(json.dumps({"presets": [{"nameless": True}, "x", {"id": "ok_one", **good()}]}), encoding="utf-8")
    assert [p["id"] for p in mp.all_presets()][-1] == "ok_one" and len(mp.all_presets()) == len(mp.base()["presets"]) + 1


# ───────────────────────── التطبيق على لقطة ─────────────────────────
def test_applying_a_preset_stores_it_on_the_shot_and_clearing_removes_it(stage):
    sid = shot_id(stage)
    sh = mp.apply(stage.script, sid, "push_in", {"camera": "classic_16mm", "lens": "bogus"})
    assert sh["camera_preset"]["id"] == "push_in" and sh["camera_preset"]["look"] == {"camera": "classic_16mm"} and sh["camera_preset"]["at"]
    assert sh["motion_desc"] == mp.get("push_in")["motion_desc_ar"] and sh["motion_prompt"] is None
    stored = ims._shot(timeline.load("s1"), sid)[1]
    assert stored["camera_preset"]["id"] == "push_in" and timeline.validate(timeline.load("s1"))["ok"]
    assert mp.of_shot(stored)["id"] == "push_in" and mp.camera_move_of(stored) is True
    cleared = mp.clear(stage.script, sid)
    assert "camera_preset" not in cleared and mp.of_shot(cleared) is None and mp.camera_move_of(cleared) is None
    with pytest.raises(mp.PresetError, match="غير موجودة"):
        mp.apply(stage.script, sid, "nope")
    with pytest.raises(mp.PresetError, match="لقطة"):
        mp.apply(stage.script, "s9c9", "push_in")


def test_a_deleted_preset_on_a_shot_is_ignored_gracefully(stage, lib):
    sid = shot_id(stage)
    mp.create(good())
    mp.apply(stage.script, sid, "custom")
    mp.delete("custom")
    sh = ims._shot(timeline.load("s1"), sid)[1]
    assert mp.of_shot(sh) is None and mp.camera_move_of(sh) is None and mp.preference(sh, {"kind": "api", "name": "Kling"}) == 0
    assert "Animate the reference image" in motion.build_prompt_en(sh, None, 3000)


def test_preferred_families_get_ranking_points():
    shot = {"type": "wide", "start_ms": 0, "end_ms": 3000, "camera_preset": {"id": "orbit", "look": {}}}
    kling = {"kind": "api", "name": "Kling 2.6", "api": {"endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video"}}
    hailuo = {"kind": "api", "name": "Hailuo 02", "api": {"endpoint": "fal-ai/minimax/hailuo-02/standard/image-to-video"}}
    assert mp.preference(shot, kling) == mp.PREFER_BONUS and mp.preference(shot, hailuo) == 0           # الدوران بيفضّل Kling
    assert mp.preference({**shot, "camera_preset": {"id": "push_in"}}, hailuo) == mp.PREFER_BONUS
    assert mp.preference({"type": "wide"}, kling) == 0


# ───────────────────────── كلام الكاميرا بالبرومبت ─────────────────────────
HAILUO = {"kind": "api", "name": "Hailuo 02", "api": {"endpoint": "fal-ai/minimax/hailuo-02/standard/image-to-video"}}
KLING = {"kind": "api", "name": "Kling 2.6", "api": {"endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video"}}


def test_the_prompt_uses_the_recipe_of_the_models_family(stage):
    sid = shot_id(stage)
    sh = mp.apply(stage.script, sid, "push_in")
    h = motion.build_prompt_en(sh, None, 3000, model=HAILUO)
    k = motion.build_prompt_en(sh, None, 3000, model=KLING)
    local = motion.build_prompt_en(sh, None, 3000, model={"kind": "http", "name": "LTX"})
    nomodel = motion.build_prompt_en(sh, None, 3000)
    assert "[Push in] Slow, steady push-in" in h and "The camera slowly pushes in toward the subject" in k
    assert "Slow, steady push-in toward the subject while the subject stays in place" in local and local == nomodel
    assert not any(arabic(x) for x in (h, k, local))


def test_the_look_sentence_is_appended_to_the_recipe(stage):
    sid = shot_id(stage)
    sh = mp.apply(stage.script, sid, "static", {"camera": "classic_16mm", "focal": "35"})
    p = motion.build_prompt_en(sh, None, 3000, model=KLING)
    assert "only the subject moves" in p
    assert "shot on a classic 16mm film camera, at 35mm (natural cinematic perspective)" in p


def test_without_a_preset_the_prompt_is_unchanged(stage):
    sid = shot_id(stage)
    sh = ims._shot(timeline.load("s1"), sid)[1]
    before = motion.build_prompt_en(sh, None, 3000)
    assert before == motion.build_prompt_en(sh, None, 3000, model=HAILUO) and "[" not in before


def test_the_preset_decides_about_the_end_frame_not_the_text(stage):
    sid = shot_id(stage, "medium")
    tl = timeline.load("s1")
    ims._shot(tl, sid)[1]["motion_desc"] = "تقريب بطيء"                                        # الوصف العادي = حركة كاميرا
    timeline.save("s1", tl)
    sh = ims._shot(timeline.load("s1"), sid)[1]
    assert motion._end_frame_ok(sh) is False
    still = mp.apply(stage.script, sid, "face_breath")
    assert motion._end_frame_ok(still) is True                                                # الوصفة الثابتة بتغلب
    moving = mp.apply(stage.script, sid, "tilt_up")                                          # وصفها العربي ما فيه كلمة حركة كاميرا بالتخمين
    assert not motion._CAMERA_MOVE_RX.search(moving["motion_desc"]) and motion._end_frame_ok(moving) is False
    mp.clear(stage.script, sid)


def test_ranking_adds_the_presets_preference_bonus(env, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    k = motion.upsert_model({"name": "Kling 2.6 Pro", "kind": "api", "strengths": ["realism"], "max_sec": 10,
                             "api": spec(endpoint="fal-ai/kling-video/v2.6/pro/image-to-video", durations=[5, 10], cost_per_sec=0.07)})
    h = motion.upsert_model({"name": "Hailuo 02", "kind": "api", "strengths": ["realism"], "max_sec": 10,
                             "api": spec(endpoint="fal-ai/minimax/hailuo-02/standard/image-to-video", durations=[6, 10], cost_per_sec=0.045)})
    plain = {"type": "wide", "start_ms": 0, "end_ms": 3000}
    r = motion.rank_models(plain, vram_gb=6)["ranked"]
    assert [x["model"]["id"] for x in r][0] == h["id"] and all(x["preset_bonus"] == 0 for x in r)            # الأرخص أول
    r2 = motion.rank_models({**plain, "camera_preset": {"id": "orbit", "look": {}}}, vram_gb=6)["ranked"]
    assert [x["model"]["id"] for x in r2][0] == k["id"] and r2[0]["preset_bonus"] == mp.PREFER_BONUS


# ───────────────────────── الأمثلة من شغلنا ─────────────────────────
pytestmark_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def tiny_clip(path, seconds=1):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s=540x960:d={seconds}:r=10", "-pix_fmt", "yuv420p", str(path)],
                   capture_output=True, check=True)
    return path


@pytestmark_ffmpeg
def test_the_first_video_of_a_preset_is_kept_as_its_example_and_later_ones_do_not_replace_it(lib, tmp_path):
    a = tiny_clip(tmp_path / "a.mp4")
    assert mp.example_path("push_in") is None and mp.public(mp.get("push_in"))["example"] is None
    assert mp.remember_example("push_in", a, {"model": "Kling", "shot": "s1c1", "stem": "s1"}) is True
    f = mp.example_path("push_in")
    assert f and f.stat().st_size < a.stat().st_size and f.parent == mp.examples_dir()
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == "360,640"                                                                 # عرض 360 للمعاينة
    pub = mp.public(mp.get("push_in"))["example"]
    assert pub["url"] == "/api/presets/push_in/example" and pub["model"] == "Kling" and pub["shot"] == "s1c1" and pub["at"]
    assert mp.remember_example("push_in", tiny_clip(tmp_path / "b.mp4", 2), {"model": "Other"}) is False
    assert mp.examples()["push_in"]["model"] == "Kling"


@pytestmark_ffmpeg
def test_examples_ignore_unknown_presets_missing_files_and_unsafe_ids(lib, tmp_path):
    a = tiny_clip(tmp_path / "a.mp4")
    assert mp.remember_example("nope", a) is False and mp.remember_example("push_in", tmp_path / "missing.mp4") is False
    assert mp.example_path("../etc/passwd") is None and mp.example_path("") is None and mp.example_path("PUSH IN") is None
    assert not mp.examples_dir().exists() or not list(mp.examples_dir().glob("*.mp4"))


# ───────────────────────── التشغيل الفعلي ─────────────────────────
pytestmark_run = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def api_model(name, endpoint, **kw):
    s = spec(endpoint=endpoint, durations=[5, 10], cost_per_sec=0.07)
    d = {"name": name, "kind": "api", "api": s, "strengths": ["product", "realism", "faces", "camera_motion"]}
    d.update(kw)
    return d


@pytestmark_run
def test_a_preset_run_sends_the_families_wording_and_saves_the_example(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    sid = shot_id(ready, "close") or shot_id(ready)
    mp.apply(ready.script, sid, "push_in", {"camera": "classic_16mm"})
    h = motion.upsert_model(api_model("Hailuo 02", "fal-ai/minimax/hailuo-02/standard/image-to-video"))
    r = motion.run_shot(ready.script, sid, model_id=h["id"], log=lambda *_: None, face_check=lambda refs, v: {"status": "no_face", "similarity": None})
    assert r["model"] == h["id"]
    body = next(b for m, p, a, b in fal.requests if m == "POST")
    assert "[Push in] Slow, steady push-in" in body["prompt"] and "shot on a classic 16mm film camera" in body["prompt"] and not arabic(body["prompt"])
    ex = mp.examples()["push_in"]
    assert ex["model"] == "Hailuo 02" and ex["shot"] == sid and mp.example_path("push_in")
    fal.requests.clear()
    k = motion.upsert_model(api_model("Kling 2.6 Pro", "fal-ai/kling-video/v2.6/pro/image-to-video"))
    motion.run_shot(ready.script, sid, model_id=k["id"], log=lambda *_: None, face_check=lambda refs, v: {"status": "no_face", "similarity": None})
    body = next(b for m, p, a, b in fal.requests if m == "POST")
    assert body["prompt"].count("The camera slowly pushes in toward the subject") == 1 and "[Push in]" not in body["prompt"]
    assert mp.examples()["push_in"]["model"] == "Hailuo 02"                                    # المثال الأول بيضل


@pytestmark_run
def test_a_camera_move_preset_sends_no_end_frame_but_a_still_one_does(ready, fal, monkeypatch):
    fal.polls_before_done = 0
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    monkeypatch.setattr(motion_api.time, "sleep", lambda s: None)
    face = shot_id(ready, "medium")
    k = motion.upsert_model(api_model("Kling 2.6 Pro", "fal-ai/kling-video/v2.6/pro/image-to-video",
                                      api={**spec(endpoint="fal-ai/kling-video/v2.6/pro/image-to-video", durations=[5, 10], cost_per_sec=0.07),
                                           "end_image_field": "end_image_url"}))
    nofc = lambda refs, v: {"status": "no_face", "similarity": None}                              # noqa: E731
    mp.apply(ready.script, face, "pull_out")
    motion.run_shot(ready.script, face, model_id=k["id"], log=lambda *_: None, face_check=nofc)
    assert "end_image_url" not in next(b for m, p, a, b in fal.requests if m == "POST")
    fal.requests.clear()
    mp.apply(ready.script, face, "face_breath")
    motion.run_shot(ready.script, face, model_id=k["id"], log=lambda *_: None, face_check=nofc)
    assert next(b for m, p, a, b in fal.requests if m == "POST")["end_image_url"].startswith("data:image/jpeg;base64,")


# ───────────────────────── المسارات ─────────────────────────
def test_the_library_route_lists_presets_with_categories_looks_and_counts(env):
    d = tc_client().get("/api/presets").json()
    assert d["counts"]["total"] == len(mp.base()["presets"]) and d["counts"]["custom"] == 0 and d["counts"]["with_example"] == 0
    assert {c["id"] for c in d["categories"]} == {"camera", "product", "character"} and set(d["families"]) == set(mp.FAMILIES)
    assert len(d["looks"]["lenses"]) == 11 and d["shot_types"] == list(mp.SHOT_TYPES) and all(p["example"] is None for p in d["presets"])
    only = tc_client().get("/api/presets", params={"category": "character"}).json()
    assert {p["category"] for p in only["presets"]} == {"character"} and only["counts"]["total"] == 2


def test_routes_create_edit_delete_and_report_arabic_errors(env):
    c = tc_client()
    r = c.post("/api/presets", json=good())
    assert r.status_code == 200 and r.json()["id"] == "custom" and r.json()["custom"] is True and r.json()["example"] is None
    assert c.post("/api/presets", json=good(name_ar="ا")).status_code == 400
    assert "اسم الوصفة" in c.post("/api/presets", json=good(name_ar="ا")).json()["detail"]
    u = c.put("/api/presets/custom", json=good(name_ar="معدّلة")).json()
    assert u["name_ar"] == "معدّلة"
    o = c.put("/api/presets/push_in", json=good(name_ar="دفعي")).json()
    assert o["overridden"] is True
    assert c.get("/api/presets").json()["counts"]["custom"] == 1
    d = c.delete("/api/presets/push_in").json()
    assert d["ok"] is True and d["restored"]["overridden"] is False and d["restored"]["name_ar"] != "دفعي"
    assert c.delete("/api/presets/custom").json() == {"ok": True, "restored": None}
    assert c.delete("/api/presets/push_in").status_code == 400 and c.put("/api/presets/nope", json=good()).status_code == 400


@pytestmark_ffmpeg
def test_the_example_route_serves_the_saved_clip_or_404s(env, tmp_path):
    c = tc_client()
    assert c.get("/api/presets/push_in/example").status_code == 404
    mp.remember_example("push_in", tiny_clip(tmp_path / "a.mp4"), {"model": "K"})
    r = c.get("/api/presets/push_in/example")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and len(r.content) > 500
    assert c.get("/api/presets").json()["counts"]["with_example"] == 1
    assert c.get("/api/presets/..%2Fx/example").status_code == 404


def test_the_shot_routes_apply_and_clear_a_preset(stage):
    c = tc_client()
    sid = shot_id(stage)
    r = c.post(f"/api/studio/s1.json/shots/{sid}/preset", json={"preset_id": "orbit", "look": {"lens": "vintage_prime", "x": 1}})
    assert r.status_code == 200 and r.json()["shot"]["camera_preset"] == {"id": "orbit", "look": {"lens": "vintage_prime"}, "at": r.json()["shot"]["camera_preset"]["at"]}
    assert c.post(f"/api/studio/s1.json/shots/{sid}/preset", json={"preset_id": "nope"}).status_code == 400
    assert c.post(f"/api/studio/s1.json/shots/s9c9/preset", json={"preset_id": "orbit"}).status_code == 400
    assert c.post(f"/api/studio/none.json/shots/{sid}/preset", json={"preset_id": "orbit"}).status_code == 404
    assert c.delete(f"/api/studio/s1.json/shots/{sid}/preset").json()["shot"].get("camera_preset") is None


def test_the_motion_info_route_exposes_the_preset_and_its_bonus(ready, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    sid = shot_id(ready)
    mp.apply(ready.script, sid, "orbit")
    d = tc_client().get("/api/studio/s1.json/motion/info").json()
    s = next(x for x in d["shots"] if x["id"] == sid)
    assert s["camera_preset"]["id"] == "orbit" and next(x for x in d["shots"] if x["id"] != sid)["camera_preset"] is None
