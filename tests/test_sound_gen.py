"""توليد موسيقى ومؤثرات بنماذج مكتبة النماذج (sound_gen.py + مساراته): الناتج بيدخل مكتبة الأصوات غير معتمد، وبيقفل طلب السيناريو، وبلا رجوع تلقائي."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ahat  # noqa: E402
import config  # noqa: E402
import ext_tasks  # noqa: E402
import link_app  # noqa: E402
import model_library as ml  # noqa: E402
import production_log  # noqa: E402
import sound_gen  # noqa: E402
from engine_box import box_factory  # noqa: E402,F401  (fixture)
from fake_gradio import FakeGradio  # noqa: E402


@pytest.fixture(autouse=True)
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(config, "SCRIPTS_DIR", tmp_path / "scripts")
    (tmp_path / "library").mkdir()
    (tmp_path / "scripts").mkdir()
    link_app.clear_cache()
    yield tmp_path
    link_app.clear_cache()


@pytest.fixture
def gr():
    s = FakeGradio("6").start()
    yield s
    s.stop()


def app_model(gr, task="music", name="مولّد موسيقى", default=True, **over):
    raw = {"name": name, "task": task, "link": "app", "enabled": True, "licence": {"id": "Apache-2.0", "commercial": "yes"},
           "app": {"url": gr.url, "api_name": "/music", "inputs": [{"param": "prompt", "from": "prompt"}, {"param": "seconds", "from": "seconds"}]}}
    raw.update(over)
    m = ml.create(raw)
    if default:
        ml.set_default(task, m["id"])
    return m


# ── التحقق ────────────────────────────────────────────────────────────────
def test_check_cleans_defaults_and_refuses_bad_input():
    c = sound_gen.check("music", "  بيانو هادئ ", None, "", "calm")
    assert c == {"kind": "music", "prompt": "بيانو هادئ", "seconds": 30.0, "name": "بيانو هادئ", "mood": "calm", "model": None}
    assert sound_gen.check("ahat", "زفرة", "3", "آهة", "any", " lib:ml_001 ")["model"] == "lib:ml_001"
    assert sound_gen.check("ahat", "x", None)["seconds"] == 2.0
    for args, msg in ((("video", "x"), "النوع"), (("music", "  "), "اكتب وصف"), (("music", "x" * 1001), "أطول"), (("music", "x", None, "", "weird"), "مزاج"),
                      (("music", "x", 2), "بين 5 و300"), (("ahat", "x", 99), "بين 0.5 و30"), (("music", "x", "abc"), "رقم"), (("music", "x", 10, "", "any", "ml_001"), "lib:ml_001")):
        with pytest.raises(sound_gen.SoundGenError, match=msg):
            sound_gen.check(*args)


def test_preflight_says_what_to_do_when_no_model_is_ready(gr):
    with pytest.raises(sound_gen.SoundGenError, match="ما في نموذج «الموسيقى» جاهز.*اربط واحد"):
        sound_gen.preflight("music")
    with pytest.raises(sound_gen.SoundGenError, match="مش موجود"):
        sound_gen.preflight("music", "lib:ml_404")
    m = app_model(gr, default=False)
    ml.set_default("music", m["id"])
    ml.update(m["id"], {"enabled": False})
    with pytest.raises(sound_gen.SoundGenError, match="اتخطّى|معطّل"):
        sound_gen.preflight("music")                                                  # الافتراضي اتعطّل: بنقول ليش
    ml.update(m["id"], {"enabled": True})
    assert sound_gen.preflight("music")["id"] == m["id"]
    assert sound_gen.preflight("music", f"lib:{m['id']}")["id"] == m["id"]


# ── التوليد ──────────────────────────────────────────────────────────────
def test_free_generation_lands_in_the_library_unapproved_with_the_no_vocals_rule(gr):
    m = app_model(gr)
    out = sound_gen.generate("music", "بيانو هادئ دافئ", 12, "موسيقى المقدمة", "warm", log=lambda *_: None)
    t = ahat.get(out["track_id"])
    assert out["approved"] is False and t["approved"] is False and t["mood"] == "warm" and t["name"] == "موسيقى المقدمة"
    assert t["source"] == f"model:{m['id']}" and t["kind"] == "music" and t["model_name"] == "مولّد موسيقى" and t["from_script"] is None
    assert ahat.audio_path(t["id"]).suffix == ".mp3" and t["duration_sec"] >= 0.9
    sent = gr.calls[-1]["data"]
    assert sent[0] == "بيانو هادئ دافئ. instrumental, no vocals, no lyrics" and sent[1] == 12                  # الشرط بينضاف لحاله
    row = production_log.recent(5, "music")[0]
    assert row["path"] == "app" and row["status"] == "ok" and row["model_id"] == m["id"]


def test_sound_effects_use_the_sfx_task_with_the_clean_effect_rule(gr):
    m = app_model(gr, "sfx", "مؤثرات")
    out = sound_gen.generate("ahat", "زفرة ارتياح", None, "", "any", log=lambda *_: None)
    assert gr.calls[-1]["data"][0] == "زفرة ارتياح. clean, isolated sound effect, no music" and gr.calls[-1]["data"][1] == 2
    assert ahat.get(out["track_id"])["kind"] == "ahat" and production_log.recent(5, "sfx")[0]["model_id"] == m["id"]


def test_a_pending_request_is_closed_with_the_track(gr, lib):
    m = app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "جاز هادئ", "جاز", "calm", 20)
    out = sound_gen.generate_for_request("scr1", row["id"], log=lambda *_: None)
    done = ext_tasks.list_requests("scr1")[0]
    assert done["status"] == "done" and done["track_id"] == out["track_id"] and done["site"] == f"model:{m['name']}" and done["done_at"]
    t = ahat.get(out["track_id"])
    assert t["from_script"] == "scr1" and t["request_id"] == row["id"] and t["name"] == "جاز" and t["mood"] == "calm" and t["approved"] is False
    assert gr.calls[-1]["data"][1] == 20
    with pytest.raises(sound_gen.SoundGenError, match="خلص من قبل"):
        sound_gen.generate_for_request("scr1", row["id"])
    with pytest.raises(sound_gen.SoundGenError, match="الطلب غير موجود"):
        sound_gen.generate_for_request("scr1", "req_099")
    with pytest.raises(sound_gen.SoundGenError, match="الطلب غير موجود"):
        sound_gen.generate_for_request("nope", "req_001")


def test_a_failing_model_leaves_the_request_pending_and_never_falls_back(gr):
    app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "x", "", "any", 10)
    gr.modes["music"] = "error_null"
    with pytest.raises(sound_gen.SoundGenError, match="البرنامج فشل"):
        sound_gen.generate_for_request("scr1", row["id"], log=lambda *_: None)
    assert ext_tasks.list_requests("scr1")[0]["status"] == "pending" and ahat.list_all() == []
    assert production_log.recent(5, "music")[0]["status"] == "failed"


def test_a_request_is_local_while_the_model_generates_so_the_extension_cannot_take_it(gr, lib, monkeypatch):
    app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "جاز", "", "any", 10)
    seen = {}
    orig = link_app.run

    def spy(ctx):
        r = ext_tasks.list_requests("scr1")[0]
        seen["status"] = r["status"]
        with pytest.raises(ext_tasks.ExtError, match="عم يتولّد"):                          # الإضافة بتحاول ترفع نتيجة لنفس الطلب
            ext_tasks.receive(lib / "scripts" / "scr1.json", "music", row["id"], b"data", "flowmusic")
        with pytest.raises(sound_gen.SoundGenError, match="عم يتولّد"):                      # وتوليد تاني للطلب نفسه بنفس اللحظة
            sound_gen.generate_for_request("scr1", row["id"], log=lambda *_: None)
        seen["listed"] = [t for t in ext_tasks.list_requests("scr1") if t["status"] == "pending"]
        return orig(ctx)
    import model_run
    monkeypatch.setattr(model_run, "_runner", lambda link: spy if link == "app" else None)
    sound_gen.generate_for_request("scr1", row["id"], log=lambda *_: None)
    assert seen["status"] == "local" and seen["listed"] == []
    done = ext_tasks.list_requests("scr1")[0]
    assert done["status"] == "done" and done["track_id"]


def test_a_failed_or_cancelled_generation_puts_the_request_back_to_pending(gr, monkeypatch):
    app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "x", "", "any", 10)

    def killed(ctx):
        assert ext_tasks.list_requests("scr1")[0]["status"] == "local"
        raise SystemExit(143)                                                               # إلغاء المهمة (SIGTERM) بيوصل كـ SystemExit
    import model_run
    monkeypatch.setattr(model_run, "_runner", lambda link: killed if link == "app" else None)
    with pytest.raises(SystemExit):
        sound_gen.generate_for_request("scr1", row["id"], log=lambda *_: None)
    r = ext_tasks.list_requests("scr1")[0]
    assert r["status"] == "pending" and r.get("local_at") is None and r.get("local_id") is None and ahat.list_all() == []


def test_a_stuck_local_request_expires_back_to_pending_and_release_never_touches_other_states(lib):
    from datetime import datetime, timedelta, timezone
    row = ext_tasks.add_request("scr1", "music", "x", "", "any", 10)
    assert ext_tasks.mark_local("scr1", row["id"])["status"] == "local"
    with pytest.raises(ext_tasks.ExtError, match="عم يتولّد"):
        ext_tasks.mark_local("scr1", row["id"])                                              # مرتين بنفس اللحظة ممنوع
    assert ext_tasks.list_requests("scr1")[0]["status"] == "local"                           # طازج: بيضل local
    rows = ext_tasks._requests("scr1")
    rows[0]["local_at"] = (datetime.now(timezone.utc) - timedelta(seconds=ext_tasks.LOCAL_STALE_SEC + 60)).isoformat(timespec="seconds")
    ext_tasks._save_requests("scr1", rows)
    assert ext_tasks.list_requests("scr1")[0]["status"] == "pending"                         # المولّد وقع: بيرجع ينتظر لحاله
    rows = ext_tasks._requests("scr1")
    rows[0].update(status="local", local_at="مش تاريخ")
    ext_tasks._save_requests("scr1", rows)
    assert ext_tasks.list_requests("scr1")[0]["status"] == "pending"                         # تاريخ تالف = قديم
    ext_tasks.complete_request("scr1", row["id"], "ah_001", "x")
    ext_tasks.release_local("scr1", row["id"])
    assert ext_tasks.list_requests("scr1")[0]["status"] == "done"                            # خلص: release ما بيرجّعه
    ext_tasks.release_local("scr1", "req_099")                                               # غير موجود: ما بيرمي
    with pytest.raises(ext_tasks.ExtError, match="خلص من قبل"):
        ext_tasks.mark_local("scr1", row["id"])
    with pytest.raises(ext_tasks.ExtError, match="غير موجود"):
        ext_tasks.mark_local("scr1", "req_099")


def test_a_request_edited_or_replaced_during_generation_is_never_overwritten_by_the_old_result(gr, monkeypatch):
    app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "الوصف القديم", "قديم", "any", 10)
    orig = link_app.run

    def retry_then_run(ctx):                                       # المالك بيعيد المحاولة بوصف تاني أثناء التوليد: الطلب بيرجع pending بوصف جديد
        rows = ext_tasks._requests("scr1")
        rows[0].update(status="pending", prompt="الوصف الجديد")
        rows[0].pop("local_at", None)
        rows[0].pop("local_id", None)
        ext_tasks._save_requests("scr1", rows)
        return orig(ctx)
    import model_run
    monkeypatch.setattr(model_run, "_runner", lambda link: retry_then_run if link == "app" else None)
    logs = []
    out = sound_gen.generate_for_request("scr1", row["id"], log=logs.append)
    after = ext_tasks.list_requests("scr1")[0]
    assert after["status"] == "pending" and after["prompt"] == "الوصف الجديد" and after["track_id"] is None        # ما انكتب فوقه
    assert ahat.get(out["track_id"])["approved"] is False and any("اتغيّر أثناء التوليد" in str(x) for x in logs)  # والمقطع بالمكتبة
    # حذف الطلب وإضافة طلب تاني بنفس الرقم (الأرقام بتتكرر لو انحذف الأخير)
    row2 = ext_tasks.add_request("scr1", "music", "طلب تاني", "", "any", 10)
    ext_tasks.mark_local("scr1", row2["id"])
    token = ext_tasks.list_requests("scr1")[1]["local_id"]
    ext_tasks.delete_request("scr1", row2["id"])
    row3 = ext_tasks.add_request("scr1", "music", "طلب تالت بنفس الرقم", "", "any", 10)
    assert row3["id"] == row2["id"]
    with pytest.raises(ext_tasks.ExtError, match="اتغيّر أثناء التوليد"):
        ext_tasks.complete_request("scr1", row3["id"], "ah_9", "x", hold=token)
    assert ext_tasks.list_requests("scr1")[-1]["status"] == "pending"
    ext_tasks.mark_local("scr1", row3["id"])                                                    # توليد جديد بالرقم نفسه (رمز جديد)
    ext_tasks.release_local("scr1", row3["id"], hold=token)                                    # الرمز القديم ما بيحرّر توليد غيره
    assert ext_tasks.list_requests("scr1")[-1]["status"] == "local"


def test_the_generator_keeps_the_request_alive_with_beats_and_an_io_error_never_leaves_it_stuck(gr, monkeypatch):
    app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "x", "", "any", 10)
    monkeypatch.setattr(sound_gen, "BEAT_SEC", 0.05)
    beats = []
    real = ext_tasks.touch_local
    monkeypatch.setattr(ext_tasks, "touch_local", lambda *a: beats.append(a) or real(*a))
    orig = link_app.run

    def slow(ctx):
        time.sleep(0.5)
        return orig(ctx)
    import model_run
    monkeypatch.setattr(model_run, "_runner", lambda link: slow if link == "app" else None)
    sound_gen.generate_for_request("scr1", row["id"], log=lambda *_: None)
    assert len(beats) >= 3 and all(b[1] == row["id"] for b in beats)                          # نبض طول التوليد
    time.sleep(0.3)                                                                            # نبضة كانت جارية لحظة الوقف تخلص
    n = len(beats)
    time.sleep(0.3)
    assert len(beats) == n                                                                     # وقف النبض بعد ما خلص
    row2 = ext_tasks.add_request("scr1", "music", "y", "", "any", 10)

    def disk_full(*a, **k):
        raise PermissionError("الملف مقفول")                                                    # خطأ كتابة (مش ExtError) بعد ما المقطع دخل المكتبة
    monkeypatch.setattr(ext_tasks, "complete_request", disk_full)
    monkeypatch.setattr(model_run, "_runner", lambda link: orig if link == "app" else None)
    with pytest.raises(PermissionError):
        sound_gen.generate_for_request("scr1", row2["id"], log=lambda *_: None)
    assert [r["status"] for r in ext_tasks.list_requests("scr1")] == ["done", "pending"]       # مش عالق «local»


def test_a_request_deleted_during_generation_still_keeps_the_track(gr, monkeypatch):
    app_model(gr)
    row = ext_tasks.add_request("scr1", "music", "x", "", "any", 10)
    orig = link_app.run

    def delete_then_run(ctx):
        ext_tasks.delete_request("scr1", row["id"])
        return orig(ctx)
    import model_run
    monkeypatch.setattr(model_run, "_runner", lambda link: delete_then_run if link == "app" else None)
    logs = []
    out = sound_gen.generate_for_request("scr1", row["id"], log=logs.append)
    assert ahat.get(out["track_id"])["approved"] is False and any("الطلب غير موجود" in str(x) for x in logs)


# ── صندوق الأوزان (Stable Audio / t2a) ─────────────────────────────────────
def weights_audio(box, task="music", name="ستيريو", model="demo-audio", **over):
    ml.set_box(box.url)
    raw = {"name": name, "task": task, "link": "weights", "enabled": True, "weights": {"model": model}, "caps": {"max_sec": 20},
           "licence": {"id": "Apache-2.0", "commercial": "yes"}}
    raw.update(over)
    m = ml.create(raw)
    ml.set_default(task, m["id"])
    return m


def test_music_and_effects_can_come_from_a_weights_box_and_still_wait_for_the_owners_ear(box_factory):
    box = box_factory()
    m = weights_audio(box)
    out = sound_gen.generate("music", "بيانو هادئ", 6, "مقدمة", "calm", log=lambda *_: None)
    t = ahat.get(out["track_id"])
    assert out["approved"] is False and t["approved"] is False and t["source"] == f"model:{m['id']}" and t["kind"] == "music" and t["mood"] == "calm"
    assert ahat.audio_path(t["id"]).suffix == ".mp3" and 5.5 <= t["duration_sec"] <= 7
    job = next(iter(box.jobs.values()))
    assert job.params == {"mode": "t2a", "model": "demo-audio", "prompt": "بيانو هادئ. instrumental, no vocals, no lyrics", "seconds": 6.0} and job.purged is True
    assert production_log.recent(5, "music")[0]["path"] == "http" and production_log.recent(5, "music")[0]["model_id"] == m["id"]
    fx = weights_audio(box, "sfx", "مؤثرات")
    out2 = sound_gen.generate("ahat", "زفرة ارتياح", None, "", "any", log=lambda *_: None)
    assert list(box.jobs.values())[-1].params["prompt"] == "زفرة ارتياح. clean, isolated sound effect, no music" and list(box.jobs.values())[-1].params["seconds"] == 2.0
    assert ahat.get(out2["track_id"])["kind"] == "ahat" and production_log.recent(5, "sfx")[0]["model_id"] == fx["id"]


def test_a_models_declared_max_seconds_is_checked_before_anything_reaches_the_box(box_factory):
    box = box_factory()
    weights_audio(box)                                                                    # caps.max_sec = 20
    with pytest.raises(sound_gen.SoundGenError, match="أقصى مدة عنده 20 ثانية"):
        sound_gen.generate("music", "x", 30, log=lambda *_: None)
    assert not box.jobs and ahat.list_all() == []
    with pytest.raises(sound_gen.SoundGenError, match="أقصى مدة"):
        sound_gen.preflight("music", None, 25)
    assert sound_gen.preflight("music", None, 20)["name"] == "ستيريو" and sound_gen.preflight("music")["name"] == "ستيريو"      # المدة اختيارية بالفحص
    assert sound_gen.preflight("music", None, 5.5)["caps"]["max_sec"] == 20


def test_a_box_cap_the_library_does_not_know_still_ends_as_a_clear_arabic_error(box_factory):
    box = box_factory(audio_max_seconds=8)
    weights_audio(box, caps={})                                                           # النموذج ما عرّف أقصى مدة: الصندوق هو اللي بيرفض
    with pytest.raises(sound_gen.SoundGenError, match="المدة لازم بين 0.5 و8") as e:
        sound_gen.generate("music", "x", 30, log=lambda *_: None)
    assert "ستيريو" in str(e.value) and ahat.list_all() == [] and production_log.recent(5, "music")[0]["status"] == "failed"


# ── المسارات ─────────────────────────────────────────────────────────────
@pytest.fixture
def client(lib, monkeypatch):
    from web import jobs as webjobs
    from web import routes_montage
    made = []
    monkeypatch.setattr(webjobs, "create_job", lambda kind, label, cmd: made.append((kind, label, cmd)) or f"job-{len(made)}")
    app = FastAPI()
    app.include_router(routes_montage.router)
    c = TestClient(app)
    c.jobs = made
    return c


def test_generate_route_checks_first_then_starts_a_background_job(client, gr):
    r = client.post("/api/ahat/generate", json={"kind": "music", "prompt": "بيانو"})
    assert r.status_code == 409 and "ما في نموذج «الموسيقى»" in r.json()["detail"] and not client.jobs                 # نرفض قبل المهمة
    m = app_model(gr)
    r = client.post("/api/ahat/generate", json={"kind": "music", "prompt": "بيانو هادئ", "seconds": 20, "name": "مقدمة", "mood": "calm"})
    assert r.status_code == 200 and r.json() == {"job_id": "job-1"}
    kind, label, cmd = client.jobs[0]
    assert kind == "sound" and "موسيقى" in label and cmd[:2] == ["sound_gen.py", "free"]
    assert cmd[cmd.index("--kind") + 1] == "music" and cmd[cmd.index("--seconds") + 1] == "20.0" and "--model" not in cmd
    r = client.post("/api/ahat/generate", json={"kind": "music", "prompt": "x", "model": f"lib:{m['id']}"})
    assert r.status_code == 200 and client.jobs[-1][2][-2:] == ["--model", f"lib:{m['id']}"]
    for bad, code in (({"kind": "video", "prompt": "x"}, 409), ({"kind": "music", "prompt": ""}, 409), ({"kind": "music", "prompt": "x", "seconds": 1}, 409),
                      ({"kind": "music", "prompt": "x", "weird": 1}, 400), ({"kind": "music", "prompt": "x", "model": "lib:nope"}, 409)):
        assert client.post("/api/ahat/generate", json=bad).status_code == code, bad


def test_request_route_validates_the_request_and_starts_the_job(client, gr, lib):
    (lib / "scripts" / "scr1.json").write_text("{}", encoding="utf-8")
    row = ext_tasks.add_request("scr1", "ahat", "زفرة", "", "any", 2)
    url = f"/api/studio/scr1.json/sounds/{row['id']}/generate"
    assert client.post(url, json={}).status_code == 409                                                                  # ما في نموذج مؤثرات
    app_model(gr, "sfx", "مؤثرات")
    r = client.post(url, json={})
    assert r.status_code == 200 and r.json() == {"job_id": "job-1"}
    kind, label, cmd = client.jobs[0]
    assert kind == "sound" and cmd[0] == "sound_gen.py" and cmd[1] == "request" and cmd[2].endswith("scr1.json") and cmd[3] == row["id"]
    assert client.post(url.replace(row["id"], "req_099"), json={}).status_code == 404
    assert client.post("/api/studio/missing.json/sounds/req_001/generate", json={}).status_code == 404
    assert client.post(url, json={"model": "ml_001"}).status_code == 400
    ext_tasks.mark_local("scr1", row["id"])
    r = client.post(url, json={})
    assert r.status_code == 409 and "عم يتولّد" in r.json()["detail"]                                                    # شغّال بنفس اللحظة
    ext_tasks.release_local("scr1", row["id"])
    ext_tasks.complete_request("scr1", row["id"], "ah_001", "x")
    assert client.post(url, json={}).status_code == 409 and "خلص من قبل" in client.post(url, json={}).json()["detail"]


def test_routes_reject_a_duration_longer_than_the_models_declared_maximum(client, box_factory, lib):
    box = box_factory()
    weights_audio(box)                                                                    # caps.max_sec = 20
    r = client.post("/api/ahat/generate", json={"kind": "music", "prompt": "x", "seconds": 30})
    assert r.status_code == 409 and "أقصى مدة عنده 20 ثانية" in r.json()["detail"] and not client.jobs
    assert client.post("/api/ahat/generate", json={"kind": "music", "prompt": "x", "seconds": 20}).status_code == 200
    (lib / "scripts" / "scr1.json").write_text("{}", encoding="utf-8")
    row = ext_tasks.add_request("scr1", "music", "جاز", "", "any", 60)
    r = client.post(f"/api/studio/scr1.json/sounds/{row['id']}/generate", json={})
    assert r.status_code == 409 and "أقصى مدة" in r.json()["detail"] and len(client.jobs) == 1
    ok = ext_tasks.add_request("scr1", "music", "جاز", "", "any", 15)
    assert client.post(f"/api/studio/scr1.json/sounds/{ok['id']}/generate", json={}).status_code == 200


def test_complete_request_helper_closes_only_real_requests(lib):
    row = ext_tasks.add_request("scr1", "music", "x", "", "any", 10)
    done = ext_tasks.complete_request("scr1", row["id"].replace("req_", ""), "ah_007", "model:x")
    assert done["status"] == "done" and done["track_id"] == "ah_007"
    with pytest.raises(ext_tasks.ExtError, match="الطلب غير موجود"):
        ext_tasks.complete_request("scr1", "req_050", "ah_1", "x")


def test_command_line_free_and_request_modes(gr, lib, monkeypatch, capsys):
    import job_signals
    monkeypatch.setattr(job_signals, "install", lambda: None)
    app_model(gr)
    monkeypatch.setattr(sys, "argv", ["sound_gen.py", "free", "--kind", "music", "--prompt", "بيانو", "--seconds", "10", "--name", "اختبار", "--mood", "calm"])
    sound_gen.main()
    assert "[✓]" in capsys.readouterr().out and [t["name"] for t in ahat.list_all()] == ["اختبار"]
    row = ext_tasks.add_request("scr2", "music", "جاز", "", "any", 10)
    monkeypatch.setattr(sys, "argv", ["sound_gen.py", "request", str(lib / "scripts" / "scr2.json"), row["id"]])
    sound_gen.main()
    assert ext_tasks.list_requests("scr2")[0]["status"] == "done"
    monkeypatch.setattr(sys, "argv", ["sound_gen.py", "request", str(lib / "scripts" / "scr2.json"), row["id"]])
    with pytest.raises(SystemExit) as e:
        sound_gen.main()
    assert e.value.code == 1 and "[!]" in capsys.readouterr().out


def test_activity_labels_exist_for_both_new_routes():
    import activity
    assert activity.describe("POST", "/api/ahat/generate")[1].startswith("توليد")
    assert "(scr1)" in activity.describe("POST", "/api/studio/scr1.json/sounds/req_001/generate")[1]
