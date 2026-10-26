"""مونتاج المشروع الحر (free_montage): عدد إطارات دقيق، كاش المقاطع، صوت المشهد والموسيقى والمؤثرات، ترجمة آمنة، بصمة «قديم»، والمسارات."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_free_media import make_video  # noqa: E402

import ahat  # noqa: E402
import config  # noqa: E402
import free_montage as fm  # noqa: E402
import free_project as fp  # noqa: E402
import montage  # noqa: E402
import timeline  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")
SIZE = (90, 160)
QUIET = lambda m: None          # noqa: E731


def sp(made):
    return Path(config.SCRIPTS_DIR) / made["file"]


def png(tmp, name="a.png", color=(200, 40, 40)):
    p = Path(tmp) / name
    Image.new("RGB", (320, 480), color).save(p)
    return p


def wav(path, seconds=2, freq=440):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", str(path)], check=True, capture_output=True)
    return Path(path)


def project(tmp_path, kinds=("image", "video", "image"), title="مشروعي", audio=False):
    made = fp.create(title)
    p = sp(made)
    files = []
    for i, k in enumerate(kinds):
        if k == "image":
            files.append({"kind": "image", "tmp": png(tmp_path, f"i{i}.png", (40 * i + 20, 80, 120)), "filename": f"i{i}.png"})
        else:
            files.append({"kind": "video", "tmp": make_video(tmp_path / f"v{i}.mp4", 2, audio=audio, size="160x288"), "filename": f"v{i}.mp4"})
    fp.add_media(p, files)
    return p


def edit(p, mutate):
    b = fp.board(p)
    s = {"rev": b["rev"], "scenes": [
        {"key": sc["key"], "voiceover": sc["voiceover"], "visual": sc["visual"], "emotion": sc["emotion"],
         "shots": [{"id": sh["id"], "duration_ms": sh["end_ms"] - sh["start_ms"], "text": sh["text"], "still_motion": sh["still_motion"],
                    "trim_in_ms": sh["trim_in_ms"], "keep_audio": sh["keep_audio"]} for sh in sc["shots"]]} for sc in b["scenes"]]}
    mutate(s)
    return fp.apply_structure(p, s)


def frames_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return int(r.stdout.strip())


def max_volume(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"max_volume: (-?[\d.]+|-inf) dB", r.stderr)
    return -99.0 if not m or m.group(1) == "-inf" else float(m.group(1))


def sound(tmp_path, name="موسيقى", approve=True, freq=330):
    t = ahat.add(name, "calm", "x.wav", wav(Path(tmp_path) / f"s{freq}.wav", 2, freq).read_bytes())
    if approve:
        ahat.approve(t["id"], True)
    return t["id"]


def out_of(res):
    return Path(config.LIBRARY_DIR) / res["file"]


# ───────────────────────── نصوص الترجمة (بلا ffmpeg) ─────────────────────────
def test_ass_text_strips_override_tags_backslashes_and_newlines():
    assert fm.ass_text("عرض {\\an8}خاص\\N لليوم\n\nفقط") == "عرض an8خاصN لليوم فقط"
    assert "{" not in fm.ass_text("{x}") and "\\" not in fm.ass_text("a\\b") and fm.ass_text(None) == ""


def test_cues_follow_the_owner_options_and_sanitize_everything():
    tl = {"words": [{"i": 0, "text": "مرحبا", "start_ms": 0, "end_ms": 400}, {"i": 1, "text": "{بكم}", "start_ms": 500, "end_ms": 900}],
          "voice": {"duration_ms": 3000}, "captions_opts": {"voice": True, "shot_text": True},
          "scenes": [{"shots": [{"start_ms": 0, "end_ms": 3000, "text": "خصم \\ 50%"}, {"start_ms": 3000, "end_ms": 5000, "text": "  "}]}]}
    v, t = fm.cues_of(tl)
    assert [c["text"] for c in v] == ["مرحبا بكم"] and [c["text"] for c in t] == ["خصم 50%"] and t[0]["end_ms"] == 3000
    tl["captions_opts"] = {"voice": False, "shot_text": True}
    assert fm.cues_of(tl)[0] == []
    tl["captions_opts"] = {"voice": True, "shot_text": False}
    assert fm.cues_of(tl)[1] == [] and len(fm.cues_of(tl)[0]) == 1


def test_write_ass_has_two_styles_and_clean_events(tmp_path):
    out = tmp_path / "c.ass"
    fm.write_ass([{"start_ms": 0, "end_ms": 1000, "text": "كلام"}], [{"start_ms": 0, "end_ms": 2000, "text": "نص"}], out, (540, 960))
    s = out.read_text(encoding="utf-8")
    assert "Style: Voice," in s and "Style: Text," in s and "PlayResX: 540" in s
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Voice,,0,0,0,,كلام" in s and "Dialogue: 1,0:00:00.00,0:00:02.00,Text,,0,0,0,,نص" in s


def test_frames_are_computed_cumulatively_so_the_total_never_drifts():
    shots = [{"start_ms": i * 1017, "end_ms": (i + 1) * 1017} for i in range(40)]
    assert sum(fm._frames(sh) for sh in shots) == round(40 * 1017 * 30 / 1000)
    assert fm._frames({"start_ms": 0, "end_ms": 500}) == 15


def test_render_refuses_missing_media_empty_projects_wrong_modes_and_guided_scripts(env):
    p = sp(fp.create("فاضي"))
    with pytest.raises(fm.FreeMontageError, match="ما في صورة أو فيديو"):
        fm.render(p, "preview", size=SIZE, log=QUIET)
    with pytest.raises(fm.FreeMontageError, match="الوضع"):
        fm.render(p, "weird")
    env.script_file("g.json", make_script())
    with pytest.raises(fm.FreeMontageError, match="مش مشروع حر"):
        fm.preflight(env.scripts / "g.json")
    tl = timeline.load(p.stem)
    tl["scenes"] = []
    tl["length_ms"] = 0
    timeline.save(p.stem, tl)
    with pytest.raises(fm.FreeMontageError, match="ما في لقطات"):
        fm.preflight(p)


def test_sources_prefer_the_clip_over_its_poster_image(env, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg غير متوفر")
    p = project(tmp_path, kinds=("image", "video"))
    srcs = fm.sources(p.stem, timeline.load(p.stem))
    assert [k for k, _ in srcs.values()] == ["image", "video"]


# ───────────────────────── الرندر ─────────────────────────
@needs_ffmpeg
def test_preview_has_exact_frames_size_duration_audio_and_a_fingerprint(env, tmp_path):
    p = project(tmp_path)
    res = fm.render(p, "preview", size=SIZE, log=QUIET)
    out = out_of(res)
    info = montage.probe(out)
    tl = timeline.load(p.stem)
    assert (info["width"], info["height"]) == SIZE and info["has_audio"] and abs(info["fps"] - 30) < 0.5
    assert abs(info["duration_ms"] - tl["length_ms"]) <= fm.EPS_MS
    assert frames_of(out) == round(tl["length_ms"] * 30 / 1000)
    rec = tl["render"]["preview"]
    assert rec["fingerprint"] == fm.fingerprint(p.stem, tl, "preview", SIZE) and res["segments"] == {"total": 3, "cached": 0}
    st = fm.render_state(p, tl)["preview"]
    assert st["exists"] and not st["stale"]
    assert fp.board(p)["render"]["preview"] == st                                # اللوحة بتعرض نفس الحالة


@needs_ffmpeg
def test_cache_is_reused_and_each_kind_of_edit_invalidates_only_what_it_touches(env, tmp_path):
    p = project(tmp_path)
    fm.render(p, "preview", size=SIZE, log=QUIET)
    assert fm.render(p, "preview", size=SIZE, log=QUIET)["segments"] == {"total": 3, "cached": 3}
    # نص شاشة جديد: المقاطع بتضل من الكاش، والناتج بيصير «قديم» لحد ما نعيد الرندر
    edit(p, lambda s: s["scenes"][0]["shots"][0].update(text="عرض اليوم"))
    tl = timeline.load(p.stem)
    assert fm.fingerprint(p.stem, tl, "preview", SIZE) != tl["render"]["preview"]["fingerprint"]
    r = fm.render(p, "preview", size=SIZE, log=QUIET)
    assert r["segments"]["cached"] == 3 and r["cues"] == {"voice": 0, "text": 1}
    # تقصير لقطة: مقطعها بس بيعاد، والإطارات بتضل دقيقة
    edit(p, lambda s: s["scenes"][0]["shots"][0].update(duration_ms=2000))
    r = fm.render(p, "preview", size=SIZE, log=QUIET)
    tl = timeline.load(p.stem)
    assert r["segments"] == {"total": 3, "cached": 2} and tl["length_ms"] == 7000
    assert frames_of(out_of(r)) == 210
    # صورة جديدة بنفس اللقطة: مقطعها بس كمان
    fp.upload_to_shot(p, tl["scenes"][2]["shots"][0]["id"], png(tmp_path, "new.png", (0, 200, 0)), "new.png")
    assert fm.render(p, "preview", size=SIZE, log=QUIET)["segments"]["cached"] == 2


@needs_ffmpeg
def test_every_still_motion_and_video_fit_gives_the_exact_frame_count(env, tmp_path):
    p = project(tmp_path, kinds=("image", "image", "image", "video", "video"))

    def mutate(s):
        sc = s["scenes"]
        for k, m in enumerate(("zoom_in", "zoom_out", "none")):
            sc[k]["shots"][0].update(still_motion=m, duration_ms=1500)
        sc[3]["shots"][0].update(duration_ms=4000, trim_in_ms=1000)         # الفيديو 2ث: بعد القص 1ث ثم بيتجمّد آخر كادر
        sc[4]["shots"][0].update(duration_ms=1000)                          # أطول من اللقطة: بيتقصّ
    edit(p, mutate)
    r = fm.render(p, "preview", size=SIZE, log=QUIET)
    tl = timeline.load(p.stem)
    assert tl["length_ms"] == 3 * 1500 + 4000 + 1000
    assert frames_of(out_of(r)) == round(tl["length_ms"] * 30 / 1000)
    assert abs(montage.probe(out_of(r))["duration_ms"] - tl["length_ms"]) <= fm.EPS_MS


@needs_ffmpeg
def test_video_audio_is_kept_only_when_the_owner_asks_for_it(env, tmp_path):
    p = project(tmp_path, kinds=("video",), audio=True)
    assert timeline.load(p.stem)["scenes"][0]["shots"][0]["keep_audio"] is True            # الرفع بيحتفظ بصوت الفيديو افتراضياً
    assert max_volume(out_of(fm.render(p, "preview", size=SIZE, log=QUIET))) > -40
    edit(p, lambda s: s["scenes"][0]["shots"][0].update(keep_audio=False))
    assert max_volume(out_of(fm.render(p, "preview", size=SIZE, log=QUIET))) < -60


@needs_ffmpeg
def test_scene_voice_sits_in_its_scene_and_feeds_clean_captions(env, tmp_path):
    p = project(tmp_path, kinds=("image", "image"))
    wav(Path(config.LIBRARY_DIR) / "timelines" / p.stem / "voice" / "c001.wav", 2)
    tl = timeline.load(p.stem)
    tl["scenes"][0]["voice"] = {"audio": f"timelines/{p.stem}/voice/c001.wav", "duration_ms": 2000, "source": "upload",
                                "words": [{"text": "مرحبا", "start_ms": 0, "end_ms": 500}, {"text": "بكم", "start_ms": 600, "end_ms": 1100}]}
    tl["scenes"][0]["shots"][0]["text"] = "عرض {خاص}\\N"
    fp.retime(tl)
    timeline.save(p.stem, tl)
    r = fm.render(p, "preview", size=SIZE, log=QUIET)
    events = (fm.work_dir(p.stem) / "captions.ass").read_text(encoding="utf-8").split("[Events]")[1]
    assert "مرحبا بكم" in events and "Voice," in events and "Text,,0,0,0,,عرض خاصN" in events
    assert not re.search(r"[{}\\]", events)
    assert r["cues"] == {"voice": 1, "text": 1} and max_volume(out_of(r)) > -40
    # لو صوت المشهد أطول من المشهد: بيتقصّ على حدوده (ما بيزحّط الباقي) والمدة بتضل نفسها
    assert abs(montage.probe(out_of(r))["duration_ms"] - tl["length_ms"]) <= fm.EPS_MS


@needs_ffmpeg
def test_music_and_sfx_are_mixed_in_and_must_be_approved(env, tmp_path):
    p = project(tmp_path, kinds=("image", "image"))
    t = sound(tmp_path)
    b = fm.save_settings(p, {"music": {"track_id": t, "level_db": -10}, "sfx": [{"track_id": t, "at_ms": 1000, "gain_db": -6}],
                             "captions": {"voice": False}})
    assert b["ambience"] == {"track_id": t, "approved": True, "duck_db": -10.0} and b["sfx"] == [{"track_id": t, "at_ms": 1000, "gain_db": -6.0}]
    assert b["captions_opts"] == {"voice": False, "shot_text": True}
    r = fm.render(p, "preview", size=SIZE, log=QUIET)
    rec = timeline.load(p.stem)["render"]["preview"]
    assert rec["music"] is True and rec["sfx"] == 1 and max_volume(out_of(r)) > -40
    assert fp.board(p)["render"]["preview"]["stale"] is False
    ahat.revoke(t)                                                                         # سحب الاعتماد: التصدير القديم بيصير «قديم» والرندر الجديد بيرفض
    assert fp.board(p)["render"]["preview"]["stale"] is True
    with pytest.raises(fm.FreeMontageError, match="مش معتمدة بالسمع"):
        fm.render(p, "preview", size=SIZE, log=QUIET)


@needs_ffmpeg
def test_music_under_a_voice_is_ducked_and_the_render_still_matches_the_spec(env, tmp_path):
    p = project(tmp_path, kinds=("image",))
    wav(Path(config.LIBRARY_DIR) / "timelines" / p.stem / "voice" / "c001.wav", 2, 600)
    tl = timeline.load(p.stem)
    tl["scenes"][0]["voice"] = {"audio": f"timelines/{p.stem}/voice/c001.wav", "duration_ms": 2000, "words": []}
    timeline.save(p.stem, tl)
    fm.save_settings(p, {"music": {"track_id": sound(tmp_path), "level_db": -6}})
    r = fm.render(p, "preview", size=SIZE, log=QUIET)
    info = montage.probe(out_of(r))
    assert info["has_audio"] and abs(info["duration_ms"] - 3000) <= fm.EPS_MS and (info["width"], info["height"]) == SIZE


@needs_ffmpeg
def test_final_needs_no_preview_and_lands_in_exports_by_script_id(env, tmp_path):
    p = project(tmp_path, kinds=("image",))
    sid = json.loads(p.read_text(encoding="utf-8"))["_meta"]["script_id"]
    r = fm.render(p, "final", size=SIZE, log=QUIET)
    assert r["file"] == f"exports/{sid}.mp4" and out_of(r).is_file() and sid.startswith("FREE-")
    assert "preview" not in (timeline.load(p.stem).get("render") or {})
    assert not list(Path(config.LIBRARY_DIR, "exports").glob("*.part.mp4"))


@needs_ffmpeg
def test_a_bad_source_fails_cleanly_without_leaving_partial_files(env, tmp_path):
    p = project(tmp_path, kinds=("image", "image"))
    tl = timeline.load(p.stem)
    sh = tl["scenes"][0]["shots"][0]
    import image_studio
    image_studio.abs_of(p.stem, sh["image"]["chosen"]).write_bytes(b"not an image")
    with pytest.raises(fm.FreeMontageError, match="فشل ffmpeg"):
        fm.render(p, "preview", size=SIZE, log=QUIET)
    wd = fm.work_dir(p.stem)
    assert not list(wd.rglob("*.part.mp4")) and not (wd / "preview.mp4").exists()


# ───────────────────────── الخيارات ─────────────────────────
@needs_ffmpeg
def test_settings_validation_and_partial_updates(env, tmp_path):
    p = project(tmp_path, kinds=("image",))
    ok = sound(tmp_path)
    bad = sound(tmp_path, "غير معتمد", approve=False, freq=500)
    cases = [
        ({"music": {"track_id": bad}}, 409, "معتمد"), ({"music": {"track_id": "nope"}}, 404, "غير موجود"),
        ({"music": {"track_id": ok, "level_db": 5}}, 400, "dB"), ({"music": {"track_id": ok, "level_db": "x"}}, 400, "رقم"),
        ({"music": {"level_db": -5}}, 400, "اختار"), ({"sfx": "x"}, 400, "قائمة"),
        ({"sfx": [{"track_id": ok, "at_ms": 999999}]}, 400, "ضمن مدة"), ({"sfx": [{"track_id": ok, "at_ms": 100, "gain_db": 20}]}, 400, "dB"),
        ({"sfx": [{"track_id": ok, "at_ms": "x"}]}, 400, "أرقام"), ({"sfx": [{"track_id": bad, "at_ms": 0}]}, 409, "معتمد"),
        ({"sfx": [{"track_id": ok, "at_ms": 0}] * 21}, 400, "أكتر من 20"), ({"captions": "x"}, 400, "الكتابة"), ("x", 400, "شكل"),
    ]
    for payload, status, word in cases:
        with pytest.raises(fp.FreeError) as e:
            fm.save_settings(p, payload)
        assert e.value.status == status and word in str(e.value), (payload, str(e.value))
    fm.save_settings(p, {"music": {"track_id": ok}})
    b = fm.save_settings(p, {"captions": {"shot_text": False}})                           # المفاتيح الغايبة ما بتتغيّر
    assert b["ambience"]["track_id"] == ok and b["ambience"]["duck_db"] == fm.MUSIC_DEFAULT_DB and b["captions_opts"]["shot_text"] is False
    b = fm.save_settings(p, {"sfx": [{"track_id": ok, "at_ms": 2000}, {"track_id": ok, "at_ms": 500, "gain_db": -3}]})
    assert [e["at_ms"] for e in b["sfx"]] == [500, 2000]                                  # مرتّبة بالوقت
    assert fm.save_settings(p, {"music": None})["ambience"] is None and fm.save_settings(p, {"sfx": []})["sfx"] == []
    assert fp.board(p)["rev"] == b["rev"]                                                  # الإعدادات ما بتبطّل rev البنية


def test_settings_are_refused_for_guided_scripts(env):
    env.script_file("g.json", make_script())
    with pytest.raises(fp.FreeError) as e:
        fm.save_settings(env.scripts / "g.json", {"captions": {"voice": True}})
    assert e.value.status == 409


# ───────────────────────── المسارات ─────────────────────────
def client():
    from web import routes_free, routes_montage
    app = FastAPI()
    app.include_router(routes_free.router)
    app.include_router(routes_montage.router)
    return TestClient(app)


@needs_ffmpeg
def test_routes_render_job_settings_and_download(env, tmp_path):
    c = client()
    f = c.post("/api/free/projects", data={"title": "عنوان/غريب:؟"}).json()["file"]
    r = c.post(f"/api/studio/{f}/montage/render", params={"mode": "preview"})
    assert r.status_code == 409 and "ما في صورة أو فيديو" in r.json()["detail"]                    # رسالة فورية بدل مهمة بتفشل
    c.post(f"/api/studio/{f}/free/media", files=[("files", ("a.png", png(tmp_path).read_bytes(), "image/png"))])
    r = c.post(f"/api/studio/{f}/montage/render", params={"mode": "final"})
    assert r.status_code == 200 and env.jobs[-1]["cmd"][:2] == ["free_montage.py", "final"] and env.jobs[-1]["kind"] == "montage"
    assert c.post(f"/api/studio/{f}/montage/render", params={"mode": "advanced"}).status_code == 409
    assert c.post(f"/api/studio/{f}/montage/render", params={"mode": "zzz"}).status_code == 400
    t = sound(tmp_path)
    r = c.put(f"/api/studio/{f}/free/montage", json={"music": {"track_id": t, "level_db": -12}, "sfx": [{"track_id": t, "at_ms": 100}]})
    assert r.status_code == 200 and r.json()["ambience"]["duck_db"] == -12 and len(r.json()["sfx"]) == 1
    assert c.put(f"/api/studio/{f}/free/montage", json={"music": {"track_id": "ah_999"}}).status_code == 404
    assert c.put(f"/api/studio/{f}/free/montage", json={"captions": "x"}).status_code == 400
    sc = Path(config.SCRIPTS_DIR) / f
    fm.render(sc, "final", size=SIZE, log=QUIET)
    r = c.get(f"/api/studio/{f}/free/render/final")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and "attachment" not in r.headers.get("content-disposition", "")
    r = c.get(f"/api/studio/{f}/free/render/final", params={"download": "1"})
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and ".mp4" in cd and "/" not in cd.split("filename")[1]
    assert c.get(f"/api/studio/{f}/free/render/preview").status_code == 404 and c.get(f"/api/studio/{f}/free/render/zzz").status_code == 404
    b = fp.board(sc)
    assert b["render"]["final"]["exists"] is True and b["render"]["final"]["stale"] is False
    c.put(f"/api/studio/{f}/free/montage", json={"captions": {"shot_text": False}})
    assert fp.board(sc)["render"]["final"]["stale"] is True                                  # تغيّر خيار بعد التصدير ← «قديم»
    env.script_file("g.json", make_script())
    assert c.get("/api/studio/g.json/free/render/final").status_code == 409
    assert c.put("/api/studio/g.json/free/montage", json={}).status_code == 409


def test_guided_render_route_is_unchanged_for_guided_scripts(env):
    c = client()
    env.script_file("g.json", make_script())
    r = c.post("/api/studio/g.json/montage/render", params={"mode": "preview"})
    assert r.status_code in (404, 409) and "free_montage" not in json.dumps(env.jobs)


@needs_ffmpeg
def test_beat_snap_is_saved_only_when_on_changes_the_fingerprint_and_renders(env, tmp_path):
    p = project(tmp_path, kinds=("image", "image"))
    t = sound(tmp_path)
    b = fm.save_settings(p, {"music": {"track_id": t, "level_db": -10}})
    assert "beat_snap" not in b["ambience"]
    before = fm.fingerprint(p.stem, timeline.load(p.stem), "preview", SIZE)
    b = fm.save_settings(p, {"music": {"track_id": t, "level_db": -10, "beat_snap": True}})
    assert b["ambience"]["beat_snap"] is True
    assert fm.fingerprint(p.stem, timeline.load(p.stem), "preview", SIZE) != before            # تفعيله بيخلّي التصدير القديم «قديم»
    logs = []
    r = fm.render(p, "preview", size=SIZE, log=logs.append)
    assert out_of(r).is_file() and any("إيقاع الموسيقى" in m for m in logs)
