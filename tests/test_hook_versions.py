"""نسخ الهوك (المرحلة 3ب): نسخة فيديو لكل هوك بديل بصوت ولقطات مشاهد 2–7 موروثة، والمشهد 1 بس بينتج."""

import json
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_hooks_h1 import ALTS, HOOK, REST, hooked, read  # noqa: E402

import adname  # noqa: E402
import config  # noqa: E402
import ext_bridge  # noqa: E402
import ext_tasks  # noqa: E402
import generate_voice  # noqa: E402
import hook_versions as hv  # noqa: E402
import launch  # noqa: E402
import review_loop  # noqa: E402
import script_hooks as sh  # noqa: E402
import script_versions  # noqa: E402
import shot_prompts  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402
import tts  # noqa: E402
import voice_studio  # noqa: E402

DURS = [6.0, 7.0, 7.0, 7.0, 7.0, 7.0, 6.0]
NEW_SCENE1 = 6.2


def lib(*parts) -> Path:
    return Path(config.LIBRARY_DIR).joinpath(*parts)


@pytest.fixture
def base(env, monkeypatch):
    """سيناريو أساسي بـ3 هوكات: مراجَع (مراجعة حقيقية)، صوته معتمد، وخطه الزمني بلقطات فيها صور وحركة. TTS مزيّف."""
    env.pattern("p1")
    path = hooked(env, "s1.json", n=3, status="approved")
    s = read(path)
    s["hooks_review"] = {h["id"]: {"verdict": "ok", "note": "تمام", "fp": sh.fingerprint(h), "at": "x"} for h in s["hooks"] if h["id"] != "h1"}
    path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    rv = review_loop.review_path(path)
    rv.parent.mkdir(parents=True, exist_ok=True)
    rv.write_text(json.dumps({
        "verdict": "approve", "summary": "سليم", "scores": {"arithmetic": 9}, "blockers": 0, "major": 0, "minor": 2, "rounds": 1,
        "findings": [{"severity": "minor", "scene": 3, "field": "voiceover", "issue": "إيقاع", "evidence": "x", "fix": "y"},
                     {"severity": "minor", "scene": 1, "field": "visual", "issue": "وصف المشهد الأول", "evidence": "x", "fix": "y"}],
        "script_hash": script_versions.content_hash(s), "_meta": {"script": "s1.json", "provider": "fake", "model": "m"}}, ensure_ascii=False), encoding="utf-8")

    st = types.SimpleNamespace(path=path, speak=[], env=env)
    monkeypatch.setattr(tts, "tts_config", lambda o=None: {"provider": (o or {}).get("provider", "elevenlabs"), "model": (o or {}).get("model", "eleven_v3"),
                                                          "voice": (o or {}).get("voice", "v1"), "tone": ""})
    monkeypatch.setattr(tts, "performance_note", lambda c: "")

    def speak(text, out, ov=None, want_timing=False):
        n = int(out.stem.split("_")[1])
        st.speak.append({"stem": out.parent.name, "scene": n, "text": text, "ov": dict(ov or {})})
        d = NEW_SCENE1 if (out.parent.name != "s1" and n == 1) else DURS[n - 1]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"audio-" + out.parent.name.encode() + str(n).encode())
        return {"path": str(out), "duration_sec": d, "provider": "elevenlabs", "model": "eleven_v3", "voice": "v1",
                "words": tts.estimate_words(text, d * 0.97), "timing_source": "provider"}

    monkeypatch.setattr(tts, "speak", speak)
    monkeypatch.setattr(generate_voice, "concat", lambda files, out: (out.write_bytes(b"full"), True)[1])
    monkeypatch.setattr(tts, "audio_duration", lambda p: 47.0)

    voice_studio.produce(path, log=lambda *_: None)
    voice_studio.approve_voice(path)
    tl = timeline.load("s1")
    root = lib("timelines", "s1")
    (root / "img").mkdir(parents=True, exist_ok=True)
    (root / "clips").mkdir(parents=True, exist_ok=True)
    for sc in tl["scenes"]:
        for shot in sc["shots"]:
            sid = shot["id"]
            for suffix in ("a.png", "a_1080.png"):
                (root / "img" / f"{sid}_{suffix}").write_bytes(b"img-" + sid.encode())
            shot["prompt_ar"] = f"برومبت {sid} بدون أي كتابة داخل الصورة"
            shot["image"] = {"candidates": [{"path": f"img/{sid}_a.png"}], "chosen": f"img/{sid}_a_1080.png",
                             "source": f"img/{sid}_a.png", "upscaled": False, "path_used": "api"}
    mshot = next(s for sc in tl["scenes"] if sc["n"] == 2 for s in sc["shots"])
    (root / "clips" / f"{mshot['id']}.mp4").write_bytes(b"clip")
    mshot["motion"] = {"clip": f"clips/{mshot['id']}.mp4", "model_id": "m1", "model_name": "M", "duration_ms": mshot["end_ms"] - mshot["start_ms"]}
    mshot["motion_candidates"] = [{"clip": f"clips/{mshot['id']}.mp4"}]
    timeline.save("s1", tl)
    st.motion_shot = mshot["id"]
    st.speak.clear()
    return st


# ═════════════════ الشروط ═════════════════
def test_a_ready_alternative_can_become_a_version(base):
    assert hv.can_create(base.path, "h2") == (True, "", 200)
    assert hv.can_create(base.path, "h3")[0] is True


@pytest.mark.parametrize("breaker,reason,status", [
    ("no_review", "مراجَع ومعتمد", 400),
    ("blocker", "مانع", 400),
    ("unreviewed", "ما انراجع بالذكاء", 400),
    ("stale_review", "ما انراجع بالذكاء", 400),
    ("rejected", "رفضه المراجع", 400),
    ("no_voice", "اعتمد صوت", 400),
])
def test_creation_is_refused_with_a_clear_reason(base, breaker, reason, status):
    s = read(base.path)
    if breaker == "no_review":
        review_loop.review_path(base.path).unlink()
    elif breaker == "blocker":
        s["hooks"][1]["spoken"] = " ".join(["كلمة"] * 30)
    elif breaker == "unreviewed":
        s["hooks_review"].pop("h2")
    elif breaker == "stale_review":
        s["hooks_review"]["h2"]["fp"] = "قديمة"
    elif breaker == "rejected":
        s["hooks_review"]["h2"] = {**s["hooks_review"]["h2"], "verdict": "reject", "note": "وعد علاجي"}
    elif breaker == "no_voice":
        voice_approval = studio_state.Path(config.LIBRARY_DIR) / "studio" / "s1" / "voice_approval.json"
        voice_approval.unlink()
    base.path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    ok, why, code = hv.can_create(base.path, "h2")
    assert ok is False and reason in why and code == status
    with pytest.raises(hv.HookVersionError):
        hv.create(base.path, "h2")
    assert not hv.version_file(base.path, "h2").exists()


def test_the_main_hook_a_missing_hook_and_a_version_itself_are_refused(base):
    assert hv.can_create(base.path, "h1")[2] == 400 and "الأساسي" in hv.can_create(base.path, "h1")[1]
    assert hv.can_create(base.path, "h9")[2] == 404
    assert hv.can_create(base.path.with_name("nope.json"), "h2")[2] == 404
    res = hv.create(base.path, "h2")
    assert hv.can_create(base.path, "h2")[2] == 409
    ok, why, code = hv.can_create(base.path.with_name(res["file"]), "h2")
    assert not ok and code == 400 and "نسخة هوك أصلاً" in why


# ═════════════════ الإنشاء ═════════════════
def test_create_writes_an_independent_single_hook_script_with_the_alternative_opening(base):
    res = hv.create(base.path, "h2")
    assert res["file"] == "s1__h2.json" and res["stem"] == "s1__h2" and res["script_id"] == "VP-testp-1-v1-h2"
    v, b = read(base.path.with_name(res["file"])), read(base.path)
    assert adname.is_script_id(v["_meta"]["script_id"])
    assert v["hook_line"] == ALTS[0][1] and v["scenes"][0]["voiceover"] == f"{ALTS[0][1]} {REST}" and v["scenes"][0]["on_screen_text"] == "٣ من ٥"
    assert v["scenes"][1:] == b["scenes"][1:] and v["cta_line"] == b["cta_line"] and v["title"] == b["title"]
    assert not {"hooks", "hook_main", "hooks_review"} & set(v)                                 # سيناريو بهوك واحد
    m = v["_meta"]
    assert m["status"] == "approved" and m["hooks_requested"] == 1 and m["number"] == 1 and m["pattern_id"] == b["_meta"]["pattern_id"]
    assert m["hook_of"]["base"] == "s1" and m["hook_of"]["base_script_id"] == "VP-testp-1-v1" and m["hook_of"]["hook_id"] == "h2"
    assert m["hook_of"]["type"] == "number" and "هوك 2" in m["display_name"] and "رقم" in m["display_name"]
    assert m["content_hash"] == script_versions.content_hash(v)
    assert (lib("scripts", "versions", "s1__h2", "v1.json")).exists()
    assert read(base.path)["hooks"] == b["hooks"]                                               # الأساسي ما انلمس


def test_the_version_has_a_derived_review_that_clears_the_gate_without_an_ai_call(base, env):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    ok, why = review_loop.is_cleared(v)
    assert ok, why
    rv = review_loop.load_review(v)
    assert rv["verdict"] == "approve" and rv["blockers"] == 0 and rv["script_hash"] == script_versions.content_hash(read(v))
    assert rv["derived_from"]["stem"] == "s1" and rv["derived_from"]["hook_id"] == "h2" and rv["_meta"]["provider"] == "derived"
    fields = [(f["scene"], f["field"]) for f in rv["findings"]]
    assert (3, "voiceover") in fields and (1, "visual") not in fields                           # ملاحظة افتتاحية المشهد 1 ما بتنتقل
    assert env.fake.count("reviewer") == 0
    assert review_loop.status(v)["approved"] is True


def test_the_script_is_not_cleared_if_it_is_edited_after_creation(base):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    s = read(v)
    s["scenes"][2]["voiceover"] += " كلمة"
    v.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert review_loop.is_cleared(v)[0] is False                                                # البصمة تغيّرت


def test_create_inherits_the_voice_of_scenes_two_to_seven_with_files_and_a_manifest(base):
    res = hv.create(base.path, "h2")
    assert res["inherited_scenes"] == [2, 3, 4, 5, 6, 7]
    m = voice_studio.load_manifest("s1__h2")
    assert m["inherited"] == [2, 3, 4, 5, 6, 7] and [s["scene"] for s in m["scenes"]] == [2, 3, 4, 5, 6, 7] and m["combined"] is None
    for s in m["scenes"]:
        assert s["path"] == f"voice/s1__h2/scene_{s['scene']:02d}.mp3" and (lib() / s["path"]).read_bytes() == f"audio-s1{s['scene']}".encode()
        assert s["words"] and s["text"]
    assert m["total_actual_sec"] == sum(DURS[1:]) and not (lib("voice", "s1__h2", "scene_01.mp3")).exists()
    assert read(base.path.with_name("s1__h2.json"))["_meta"]["hook_of"]["inherited_scenes"] == [2, 3, 4, 5, 6, 7]
    assert voice_studio.load_manifest("s1")["scenes"][1]["path"] == "voice/s1/scene_02.mp3"      # الأساسي ما انلمس


def test_create_keeps_the_same_character_and_derives_the_early_stations(base):
    cdir = lib("studio", "s1")
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "character.json").write_text(json.dumps({"character_id": "ch_x", "chosen_at": "t"}), encoding="utf-8")
    hv.create(base.path, "h2")
    assert json.loads(lib("studio", "s1__h2", "character.json").read_text(encoding="utf-8"))["character_id"] == "ch_x"
    assert studio_state.state_of("s1__h2", 2) == "approved" and studio_state.state_of("s1__h2", 3) == "approved"


def test_the_ids_listing_and_progress(base):
    assert hv.list_versions(base.path) == []
    hv.create(base.path, "h3")
    hv.create(base.path, "h2")
    vs = hv.list_versions(base.path)
    assert [v["hook_id"] for v in vs] == ["h2", "h3"] and vs[0]["script_id"] == "VP-testp-1-v1-h2" and vs[0]["status"] == "approved"
    assert vs[0]["progress"]["total"] == 11 and vs[0]["progress"]["approved"] >= 2 and vs[0]["progress"]["current"]
    assert vs[0]["inherited_scenes"] == [2, 3, 4, 5, 6, 7] and vs[1]["type"] == "life_moment"
    assert hv.list_versions(base.path.with_name("s1__h2.json")) == []                           # النسخة ما إلها نسخ


# ═════════════════ الإنتاج: المشهد 1 بس ═════════════════
def test_voice_production_speaks_scene_one_only_with_the_base_voice_and_merges_the_rest(base):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    r = voice_studio.produce(v, log=lambda *_: None)
    assert r["status"] == "awaiting_owner_approval" and r["gate"]["ok"]
    calls = [c for c in base.speak if c["stem"] == "s1__h2"]
    assert [(c["scene"], c["text"].split()[0]) for c in calls] == [(1, ALTS[0][1].split()[0])] and calls[0]["text"].startswith(ALTS[0][1])
    assert calls[0]["ov"]["voice"] == "v1" and calls[0]["ov"]["provider"] == "elevenlabs"        # نفس صوت الفيديو الأساسي
    m = voice_studio.load_manifest("s1__h2")
    assert [s["scene"] for s in m["scenes"]] == [1, 2, 3, 4, 5, 6, 7] and m["inherited"] == [2, 3, 4, 5, 6, 7]
    assert m["total_actual_sec"] == round(NEW_SCENE1 + sum(DURS[1:]), 2) and m["combined"]["path"] == "voice/s1__h2/full.mp3"
    assert m["total_planned_sec"] == 47.0 and m["scenes_off"] == []


def test_an_inherited_scene_whose_text_changed_is_regenerated_too(base):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    s = read(v)
    s["scenes"][2]["voiceover"] = "نص جديد للمشهد التالت بالكامل هون"
    v.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    generate_voice.generate(v, {}, log=lambda *_: None)
    spoken = sorted(c["scene"] for c in base.speak if c["stem"] == "s1__h2")
    assert spoken == [1, 3]
    m = voice_studio.load_manifest("s1__h2")
    assert m["inherited"] == [2, 4, 5, 6, 7] and next(x for x in m["scenes"] if x["scene"] == 3)["text"].startswith("نص جديد")


def test_a_base_script_never_skips_scenes(base):
    voice_studio.produce(base.path, log=lambda *_: None)
    assert sorted(c["scene"] for c in base.speak if c["stem"] == "s1") == [1, 2, 3, 4, 5, 6, 7]


def finish_voice(base):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    voice_studio.produce(v, log=lambda *_: None)
    return v, voice_studio.approve_voice(v)


def test_approving_the_version_voice_builds_a_timeline_that_inherits_the_shots(base):
    v, r = finish_voice(base)
    assert r["approved"] and r["timeline_ok"], r["errors"]
    tl, btl = timeline.load("s1__h2"), timeline.load("s1")
    assert r["inherited_shots"] == sum(len(sc["shots"]) for sc in tl["scenes"] if sc["n"] != 1) > 0
    assert tl["voice"]["duration_ms"] == round((NEW_SCENE1 + sum(DURS[1:])) * 1000) and timeline.validate(tl)["ok"]
    for sc in tl["scenes"]:
        for shot in sc["shots"]:
            if sc["n"] == 1:
                assert not shot.get("inherited") and not shot["image"]["candidates"] and not shot["prompt_ar"]
            else:
                b = next(x for x in next(s for s in btl["scenes"] if s["n"] == sc["n"])["shots"] if x["id"] == shot["id"])
                assert shot["inherited"] is True and shot["image"] == b["image"] and shot["prompt_ar"] == b["prompt_ar"]
                assert shot["start_ms"] != b["start_ms"] or sc["n"] == 1                               # الأوقات اتحسبت من جديد
                assert lib("timelines", "s1__h2", shot["image"]["chosen"]).read_bytes() == f"img-{shot['id']}".encode()
                assert lib("timelines", "s1__h2", shot["image"]["candidates"][0]["path"]).exists()
    ms = next(s for sc in tl["scenes"] for s in sc["shots"] if s["id"] == base.motion_shot)
    assert ms["motion"]["clip"] == f"clips/{base.motion_shot}.mp4" and ms["motion_candidates"] and ms["inherited"]
    assert lib("timelines", "s1__h2", ms["motion"]["clip"]).read_bytes() == b"clip"
    assert timeline.load("s1") == btl                                                              # الأساسي ما انلمس


def test_inheritance_only_takes_identical_shots(base):
    """لقطة بمدة أو كلمات مختلفة ما بتورّث (مثلاً مشهد انعدّل نصه)."""
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    s = read(v)
    s["scenes"][3]["voiceover"] = "نص جديد للمشهد الرابع بالكامل هون"
    v.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    generate_voice.generate(v, {}, log=lambda *_: None)
    m = voice_studio.load_manifest("s1__h2")
    script = read(v)
    tl = timeline.build(script, m, script_hash="h", audio_rel="voice/s1__h2/full.mp3")
    n = hv.overlay_timeline("s1__h2", tl, script)
    scene4 = next(sc for sc in tl["scenes"] if sc["n"] == 4)
    assert all(not shot.get("inherited") for shot in scene4["shots"])
    assert n == sum(len(sc["shots"]) for sc in tl["scenes"] if sc["n"] not in (1, 4))


def test_overlay_is_a_noop_for_a_normal_script_or_a_missing_base_timeline(base):
    tl = timeline.load("s1")
    assert hv.overlay_timeline("s1", tl, read(base.path)) == 0
    hv.create(base.path, "h2")
    lib("timelines", "s1", "timeline.json").unlink()
    v = read(base.path.with_name("s1__h2.json"))
    assert hv.overlay_timeline("s1__h2", timeline.load("s1") or tl, v) == 0


def test_the_overlay_never_copies_files_outside_the_base_folder(base, tmp_path, monkeypatch):
    hv.create(base.path, "h2")
    btl = timeline.load("s1")
    secret = tmp_path / "secret.txt"                       # tmp_path/library/timelines/s1 ← 3 مستويات فوق = tmp_path
    secret.write_text("x", encoding="utf-8")
    shot = next(s for sc in btl["scenes"] if sc["n"] == 3 for s in sc["shots"])
    shot["image"]["candidates"].append({"path": "../../../" + secret.name})
    timeline.save("s1", btl)
    copies = []
    real = hv.shutil.copy2
    monkeypatch.setattr(hv.shutil, "copy2", lambda src, dst: (copies.append(Path(src).resolve()), real(src, dst))[1])
    v = base.path.with_name("s1__h2.json")
    voice_studio.produce(v, log=lambda *_: None)
    voice_studio.approve_voice(v)
    assert copies and secret.resolve() not in copies                                    # فعلاً نسخ ملفات شرعية، بس مش الخارجي
    assert not list(lib("timelines", "s1__h2").rglob("secret.txt"))


def test_shot_prompts_keep_inherited_prompts_and_write_scene_one(base):
    v, _ = finish_voice(base)
    tl = timeline.load("s1__h2")
    shot_prompts.build(tl, read(v), "كاما", None, "testp")
    for sc in tl["scenes"]:
        for shot in sc["shots"]:
            if sc["n"] == 1:
                assert shot["prompt_ar"] and "بدون أي كتابة" in shot["prompt_ar"] and not shot["prompt_ar"].startswith("برومبت s")
            else:
                assert shot["prompt_ar"] == f"برومبت {shot['id']} بدون أي كتابة داخل الصورة"


def test_the_extension_asks_only_for_scene_one_voice_and_scene_one_images(base):
    v, _ = finish_voice(base)
    studio_state.set_state("s1__h2", 4, "approved", "x")
    tl = timeline.load("s1__h2")
    shot_prompts.build(tl, read(v), "كاما", None, "testp")
    timeline.save("s1__h2", tl)
    studio_state.set_state("s1__h2", 6, "approved", "x")
    q = ext_bridge.build_queue(v)
    assert q and {x["scene"] for x in q} == {1}                                                     # لقطات المشهد 1 بس
    # نفس الطابور بدون التوريث كان بيطلب لقطات كل المشاهد (كل لقطة عندها خيار واحد والمطلوب 2)
    tl = timeline.load("s1__h2")
    for sc in tl["scenes"]:
        for shot in sc["shots"]:
            shot.pop("inherited", None)
    timeline.save("s1__h2", tl)
    assert {x["scene"] for x in ext_bridge.build_queue(v)} == {1, 2, 3, 4, 5, 6, 7}


def test_the_extension_voice_tasks_skip_inherited_scenes_until_the_owner_marks_a_retry(base):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    tasks = ext_tasks.tasks(v, "voice")
    assert [t["task_id"] for t in tasks] == ["scene_1"]
    ext_tasks._marks  # noqa: B018 — الدالة موجودة
    marks = {"voice:scene_3": {"prompt": "نص بديل"}}
    import unittest.mock as um
    with um.patch.object(ext_tasks, "_marks", lambda stem: marks):
        assert [t["task_id"] for t in ext_tasks.tasks(v, "voice")] == ["scene_1", "scene_3"]      # إعادة صريحة من المالك


def test_a_voice_arriving_from_the_extension_keeps_the_inherited_marker(base):
    hv.create(base.path, "h2")
    v = base.path.with_name("s1__h2.json")
    import unittest.mock as um
    with um.patch.object(ext_tasks, "_check_blob", lambda *a, **k: None), \
            um.patch.object(ext_tasks, "_convert_audio", lambda data, name, out: (out.write_bytes(b"new"), NEW_SCENE1)[1]), \
            um.patch.object(ext_tasks, "_words", lambda target, text, dur: (tts.estimate_words(text, dur * 0.97), "provider")):
        out = ext_tasks._receive_voice(v, "scene_1", b"abc", "elevenlabs", "a.mp3")
    assert out["complete"] is True
    m = voice_studio.load_manifest("s1__h2")
    assert m["inherited"] == [2, 3, 4, 5, 6, 7] and len(m["scenes"]) == 7
    assert [t["task_id"] for t in ext_tasks.tasks(v, "voice")] == []                               # ما بقي شي ينطلب


# ═════════════════ الإطلاق والمسارات ═════════════════
def test_launch_meta_groups_versions_with_the_base_ad(base):
    b = read(base.path)
    assert launch.hook_meta(b, "VP-testp-1-v1") == {"hook_group": "VP-testp-1-v1", "hook_index": 1}
    hv.create(base.path, "h3")
    v = read(base.path.with_name("s1__h3.json"))
    assert launch.hook_meta(v, "VP-testp-1-v1-h3") == {"hook_group": "VP-testp-1-v1", "hook_index": 3}
    assert launch.hook_meta(make_script(), "VP-x-1-v1") == {}


def test_launch_meta_for_a_base_whose_main_was_switched_carries_the_new_index(base):
    s = sh.select_main(read(base.path), "h2")
    assert launch.hook_meta(s, "VP-testp-1-v1") == {"hook_group": "VP-testp-1-v1", "hook_index": 2}


@pytest.fixture
def api(base):
    from fastapi.testclient import TestClient
    from web.app import app
    c = TestClient(app)
    c.base = base
    return c


def test_the_hooks_view_tells_which_alternatives_can_become_versions(api):
    d = api.get("/api/scripts/s1.json/hooks").json()
    by = {h["id"]: h for h in d["hooks"]}
    assert by["h1"].get("can_version") is None and by["h1"]["version"] is None
    assert by["h2"]["can_version"] == {"ok": True, "reason": ""} and by["h2"]["version"] is None and d["version_of"] is None


def test_creating_a_version_through_the_api_and_listing_it(api):
    r = api.post("/api/scripts/s1.json/hooks/h2/version")
    assert r.status_code == 200
    d = r.json()
    assert d["created"]["file"] == "s1__h2.json" and d["created"]["inherited_scenes"] == [2, 3, 4, 5, 6, 7]
    h2 = next(h for h in d["hooks"] if h["id"] == "h2")
    assert h2["version"]["file"] == "s1__h2.json" and h2["version"]["script_id"] == "VP-testp-1-v1-h2" and "can_version" not in h2
    assert next(h for h in d["hooks"] if h["id"] == "h3")["can_version"]["ok"] is True
    again = api.post("/api/scripts/s1.json/hooks/h2/version")
    assert again.status_code == 409 and "نسخة" in again.json()["detail"]
    assert api.post("/api/scripts/s1.json/hooks/h9/version").status_code == 404
    assert api.post("/api/scripts/s1.json/hooks/h1/version").status_code == 400
    assert api.post("/api/scripts/nope.json/hooks/h2/version").status_code == 404


def test_the_version_is_a_normal_script_in_the_scripts_list_and_has_its_own_hooks_view(api):
    api.post("/api/scripts/s1.json/hooks/h2/version")
    listing = {s["file"]: s for s in api.get("/api/scripts").json()}
    assert "s1__h2.json" in listing and listing["s1__h2.json"]["script_id"] == "VP-testp-1-v1-h2" and "هوك 2" in listing["s1__h2.json"]["display_name"]
    d = api.get("/api/scripts/s1__h2.json/hooks").json()
    assert d["version_of"] == "s1" and d["legacy"] is True and len(d["hooks"]) == 1 and d["hooks"][0]["spoken"] == ALTS[0][1]
    assert all("can_version" not in h for h in d["hooks"])
    assert api.post("/api/scripts/s1__h2.json/hooks/h1/version").status_code == 400


def test_the_creation_refusals_come_back_as_400_with_the_reason(api):
    voice_approval = lib("studio", "s1", "voice_approval.json")
    voice_approval.unlink()
    r = api.post("/api/scripts/s1.json/hooks/h2/version")
    assert r.status_code == 400 and "اعتمد صوت" in r.json()["detail"]
    h = next(x for x in api.get("/api/scripts/s1.json/hooks").json()["hooks"] if x["id"] == "h2")
    assert h["can_version"]["ok"] is False and "اعتمد صوت" in h["can_version"]["reason"]
