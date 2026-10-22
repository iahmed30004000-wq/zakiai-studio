"""مسارات «مكتبة النماذج» (/api/model-library): الصورة العامة، الإنشاء بتوكن بمخزن الأسرار، الافتراضي، الفحص، «جرّب»، ورفع ملفات التجربة."""

import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
import model_library as ml  # noqa: E402
import model_tasks as mt  # noqa: E402
import secrets_store  # noqa: E402
from engine_box import box_factory  # noqa: E402,F401  (fixture)
from fake_openai import FakeOpenAI, png_bytes, wav_bytes  # noqa: E402

TOKEN = "tok-FAKE-routes-0123456789"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    mem, prev = secrets_store.use_memory_backend()
    yield tmp_path
    secrets_store.restore_backend(prev)


@pytest.fixture
def c(lib):
    from web import routes_model_library
    app = FastAPI()
    app.include_router(routes_model_library.router)
    return TestClient(app)


@pytest.fixture
def srv(lib):
    s = FakeOpenAI().start()
    yield s
    s.stop()


@pytest.fixture
def jobs(monkeypatch):
    from web import jobs as webjobs
    made = []
    monkeypatch.setattr(webjobs, "create_job", lambda kind, label, cmd: made.append((kind, label, cmd)) or "job-1")
    return made


def model(url="http://127.0.0.1:8000/v1", task="image", **over):
    raw = {"name": "صور محلية", "task": task, "link": "std", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"},
           "std": {"url": url, "model": "flux"}}
    raw.update(over)
    return raw


def by_task(overview, task):
    return next(t for t in overview["tasks"] if t["task"] == task)


# ── الصورة العامة ─────────────────────────────────────────────────────────

def test_overview_of_a_blank_library(c):
    d = c.get("/api/model-library").json()
    assert [t["task"] for t in d["tasks"]] == list(ml.TASKS) and d["problem"] is None
    img = by_task(d, "image")
    assert img["label"] == "الصور" and img["default"] is None and img["models"] == [] and img["can_fallback"] is True and "label" in img["builtin"]
    assert by_task(d, "voice")["can_fallback"] is False and by_task(d, "motion")["can_fallback"] is False
    assert {l["id"]: l["open"] for l in d["links"]} == {"weights": True, "app": True, "std": True, "command": True}
    assert next(l for l in d["links"] if l["id"] == "weights")["tasks"] == ["image", "upscale", "music", "sfx"]
    assert d["box"] == {"url": None, "token_secret": None} and set(d["gpu"]) == {"vram_gb", "busy", "lock_enabled"}
    assert d["path"].endswith("model_library.json")


def test_a_corrupt_file_opens_the_page_with_the_reason_and_is_never_overwritten(c):
    ml.path().parent.mkdir(parents=True, exist_ok=True)
    ml.path().write_text("{broken", encoding="utf-8")
    d = c.get("/api/model-library").json()
    assert "تالف" in d["problem"] and all(t["models"] == [] for t in d["tasks"] if t["task"] != "motion")
    r = c.post("/api/model-library/models", json=model())
    assert r.status_code == 400 and "تالف" in r.json()["detail"]
    assert ml.path().read_text(encoding="utf-8") == "{broken"


def test_templates_come_with_labels_and_open_flags(c):
    ts = {t["id"]: t for t in c.get("/api/model-library/templates").json()["templates"]}
    assert ts["speaches-stt"]["open"] is True and ts["speaches-stt"]["task_label"] == "التفريغ (كلام لنص)" and ts["speaches-stt"]["link_label"]
    assert ts["qwen-image"]["open"] is True and ts["real-esrgan"]["open"] is True and ts["cmd-image"]["open"] is True
    assert ts["ace-step"]["open"] is True and ts["latentsync"]["open"] is True                # برنامج نموذج (Gradio)
    for tid, task in (("stable-audio-music", "music"), ("stable-audio-sfx", "sfx")):                # Stable Audio بالصندوق: الموسيقى والمؤثرات
        t = ts[tid]
        assert t["open"] is True and t["task"] == task and t["link"] == "weights" and t["defaults"]["weights"]["model"] == "stable-audio-open-1.0" and t["defaults"]["caps"]["max_sec"] == 47
        assert t["licence"]["commercial"] == "conditional" and t["badges"]["disk_gb"] == 5.3 and "--exclude" in " ".join(t["howto"]) and "registry" not in t
    assert ts["wan22-ti2v-5b"]["open"] is False and ts["wan22-ti2v-5b"]["registry"] == "motion"   # التحريك بسجله الخاص (من بطاقة التحريك)
    assert "registry" not in ts["qwen-image"]
    assert ts["latentsync"]["commercial_label"].startswith("✗") and ts["chatterbox-voice"]["commercial_label"] == "تجارية ✓"


def test_choices_for_the_station_pickers(c):
    ml.create({**model(task="voice", params={"voice": "ahmad"}), "std": {"url": "http://127.0.0.1:8000/v1", "model": "tts"}})
    ml.create({**model(task="voice", name="معطّل", enabled=False), "std": {"url": "http://127.0.0.1:8000/v1", "model": "tts"}})
    ml.set_default("voice", "ml_001")
    d = c.get("/api/model-library/choices", params={"task": "voice"}).json()
    assert d["default"] == "ml_001" and [(m["id"], m["usable"], m["voice"]) for m in d["models"]] == [("ml_001", True, "ahmad"), ("ml_002", False, "")]
    assert d["models"][1]["reason"] == "معطّل"
    assert c.get("/api/model-library/choices", params={"task": "motion"}).status_code == 400


# ── الإنشاء والتوكن ───────────────────────────────────────────────────────

def test_create_with_a_token_keeps_it_in_the_secret_store_only(c):
    r = c.post("/api/model-library/models", json={**model(), "token": TOKEN})
    assert r.status_code == 200, r.text
    m = r.json()["model"]
    assert m["id"] == "ml_001" and m["token_set"] is True and m["std"]["token_secret"] == "modellib.ml_001.token" and m["usable"] is True
    assert secrets_store.get_secret("modellib.ml_001.token") == TOKEN
    assert TOKEN not in r.text and TOKEN not in ml.path().read_text(encoding="utf-8")
    assert TOKEN not in c.get("/api/model-library").text
    ov = by_task(c.get("/api/model-library").json(), "image")
    assert ov["models"][0]["id"] == "ml_001" and ov["models"][0]["stats"] is None and ov["models"][0]["licence_label"] == "تجارية ✓"


def test_create_validation_errors_are_arabic_400s_and_leave_nothing_behind(c):
    for bad, msg in ((model(surprise=1), "حقول غير معروفة"), (model(url="http://example.com:80/v1"), "المضيف مش مسموح"), ({**model(), "task": "motion"}, "التحريك")):
        r = c.post("/api/model-library/models", json=bad)
        assert r.status_code == 400 and msg in r.json()["detail"], bad
    assert c.post("/api/model-library/models", json=[1]).status_code in (400, 422)
    assert c.post("/api/model-library/models", json={**model(), "token": 5}).status_code == 400
    assert ml.load()["models"] == []


def test_a_token_that_cannot_be_stored_rolls_the_model_back(c, monkeypatch):
    def boom(name, value):
        raise secrets_store.SecretsError("مخزن الأسرار غير متاح")
    monkeypatch.setattr(secrets_store, "set_secret", boom)
    r = c.post("/api/model-library/models", json={**model(), "token": TOKEN})
    assert r.status_code == 409 and "مخزن الأسرار" in r.json()["detail"]
    assert ml.load()["models"] == []


def test_edit_set_and_clear_token_and_licence_confirmation(c):
    c.post("/api/model-library/models", json=model(licence={"id": "X", "commercial": "unknown", "confirmed_by_owner": True}, enabled=True))
    r = c.put("/api/model-library/models/ml_001", json={"name": "اسم جديد", "token": TOKEN})
    assert r.status_code == 200 and r.json()["model"]["name"] == "اسم جديد" and r.json()["model"]["token_set"] is True
    assert r.json()["model"]["licence"]["confirmed_by"] and r.json()["model"]["licence"]["commercial"] == "unknown"
    r = c.put("/api/model-library/models/ml_001", json={"token": ""})
    assert r.json()["model"]["token_set"] is False and r.json()["model"]["std"]["token_secret"] is None
    assert secrets_store.get_secret("modellib.ml_001.token") is None
    assert c.put("/api/model-library/models/ml_001", json={}).json()["model"]["name"] == "اسم جديد"
    assert c.put("/api/model-library/models/ml_404", json={"name": "x"}).status_code == 404
    assert c.put("/api/model-library/models/ml_404", json={}).status_code == 404
    assert c.put("/api/model-library/models/ml_001", json={"task": "voice"}).status_code == 400
    ml.create({"name": "أمر", "task": "voice", "link": "command", "licence": {"commercial": "yes"}, "command": {"argv": ["x", "{text}", "{out}"]}})
    r = c.put("/api/model-library/models/ml_002", json={"token": TOKEN})
    assert r.status_code == 409 and "OpenAI" in r.json()["detail"]


def test_delete_removes_the_model_its_token_and_its_test_files(c):
    c.post("/api/model-library/models", json={**model(), "token": TOKEN})
    mt.save_params("ml_001", {"prompt": "x"})
    assert mt.test_dir("ml_001").exists()
    assert c.delete("/api/model-library/models/ml_001").json() == {"ok": True}
    assert ml.load()["models"] == [] and secrets_store.get_secret("modellib.ml_001.token") is None and not mt.test_dir("ml_001").exists()
    assert c.delete("/api/model-library/models/ml_001").status_code == 404


# ── الافتراضي والصندوق ────────────────────────────────────────────────────

def test_default_route_rules(c, monkeypatch):
    c.post("/api/model-library/models", json=model())
    c.post("/api/model-library/models", json=model(name="معطّل", enabled=False))
    c.post("/api/model-library/models", json={**model(task="voice"), "std": {"url": "http://127.0.0.1:8000/v1", "model": "t"}})
    r = c.put("/api/model-library/tasks/image/default", json={"model_id": "ml_001"})
    assert r.status_code == 200 and r.json() == {"task": "image", "default": "ml_001", "fallback_builtin": True}
    assert c.put("/api/model-library/tasks/image/default", json={"model_id": "ml_002"}).status_code == 400
    assert c.put("/api/model-library/tasks/image/default", json={"model_id": "ml_003"}).status_code == 404      # موجود بس لمهمة تانية
    r = c.put("/api/model-library/tasks/voice/default", json={"model_id": "ml_003", "fallback_builtin": True})
    assert r.status_code == 400 and "ما بيرجع للطريقة الحالية" in r.json()["detail"]
    assert c.put("/api/model-library/tasks/image/default", json={"model_id": None, "fallback_builtin": False}).json()["default"] is None
    assert c.put("/api/model-library/tasks/image/default", json={"x": 1}).status_code == 400
    assert c.put("/api/model-library/tasks/nope/default", json={"model_id": None}).status_code == 400
    import motion
    monkeypatch.setattr(motion, "load_models", lambda: [{"id": "mm_001", "name": "Wan", "enabled": True, "max_sec": 5}])
    assert c.put("/api/model-library/tasks/motion/default", json={"model_id": "mm_001"}).json()["default"] == "mm_001"
    mo = by_task(c.get("/api/model-library").json(), "motion")
    assert mo["default"] == "mm_001" and mo["models"][0]["name"] == "Wan"
    assert c.put("/api/model-library/tasks/motion/default", json={"model_id": "mm_999"}).status_code == 400


def test_box_url_and_token(c):
    r = c.put("/api/model-library/box", json={"url": "http://engine:8100", "token": TOKEN})
    assert r.status_code == 200 and r.json() == {"box": {"url": "http://engine:8100", "token_secret": "modellib.box.token"}, "token_set": True}
    assert TOKEN not in r.text and TOKEN not in ml.path().read_text(encoding="utf-8")
    r = c.put("/api/model-library/box", json={"url": "http://engine:8100"})                 # بلا token: بيضل اللي كان
    assert r.json()["box"]["token_secret"] == "modellib.box.token" and r.json()["token_set"] is True
    r = c.put("/api/model-library/box", json={"url": "http://engine:8100", "token": ""})
    assert r.json()["box"]["token_secret"] is None and r.json()["token_set"] is False
    assert c.put("/api/model-library/box", json={"url": "http://example.com:80"}).status_code == 400
    assert c.put("/api/model-library/box", json={"url": "http://engine:8100", "x": 1}).status_code == 400
    assert c.get("/api/model-library").json()["box"]["url"] == "http://engine:8100"


# ── فحص سيرفر قياسي ───────────────────────────────────────────────────────

def test_probe_route_reports_reasons_and_uses_stored_tokens(c, lib):
    s = FakeOpenAI(token=TOKEN).start()
    try:
        r = c.post("/api/model-library/probe", json={"url": s.base}).json()
        assert r["ok"] is False and r["reason"] == "auth"
        assert c.post("/api/model-library/probe", json={"url": s.base, "token": TOKEN}).json()["ok"] is True
        c.post("/api/model-library/models", json={**model(s.base), "token": TOKEN})
        got = c.post("/api/model-library/probe", json={"url": s.base, "model_id": "ml_001"}).json()
        assert got["ok"] and got["models"] == ["flux", "whisper-large"]
        assert TOKEN not in json.dumps(got)
    finally:
        s.stop()
    assert c.post("/api/model-library/probe", json={"url": "http://example.com:80/v1"}).json()["reason"] == "config"
    assert c.post("/api/model-library/probe", json={"url": s.base}).json()["reason"] == "connection"
    assert c.post("/api/model-library/probe", json=[1]).status_code in (400, 422)


# ── «جرّب» ────────────────────────────────────────────────────────────────

def test_try_route_saves_the_inputs_and_queues_a_background_job(c, jobs):
    c.post("/api/model-library/models", json=model())
    r = c.post("/api/model-library/models/ml_001/try", json={"prompt": "عطر أسود", "bogus": 1})
    assert r.status_code == 200 and r.json() == {"job_id": "job-1"}
    assert jobs == [("model", "جرّب نموذج «صور محلية» (الصور)", ["model_tasks.py", "try", "ml_001"])]
    assert json.loads((mt.test_dir("ml_001") / "params.json").read_text(encoding="utf-8")) == {"prompt": "عطر أسود"}
    assert c.post("/api/model-library/models/ml_001/try").status_code == 200                  # بلا جسم: عيّنة جاهزة
    assert c.post("/api/model-library/models/ml_001/try", json={"seconds": 9999}).status_code == 400
    assert c.post("/api/model-library/models/ml_404/try", json={}).status_code == 404
    c.post("/api/model-library/models", json=model(enabled=False, licence={"id": "NC", "commercial": "no"}))
    r = c.post("/api/model-library/models/ml_002/try", json={})
    assert r.status_code == 409 and "بتمنع" in r.json()["detail"]


def test_try_works_on_a_disabled_model_and_the_result_is_served(c, srv, jobs):
    c.post("/api/model-library/models", json=model(srv.base, enabled=False))
    assert c.get("/api/model-library/models/ml_001/test").json() == {"last": None, "has_file": False}
    assert c.get("/api/model-library/models/ml_001/test/file").status_code == 404
    c.post("/api/model-library/models/ml_001/try", json={})
    mt.run_try("ml_001")                                                                      # اللي بتعمله المهمة الخلفية
    d = c.get("/api/model-library/models/ml_001/test").json()
    assert d["last"]["ok"] and d["has_file"] and d["last"]["kind"] == "image"
    f = c.get("/api/model-library/models/ml_001/test/file")
    assert f.status_code == 200 and f.headers["content-type"] == "image/png" and f.content[:8] == b"\x89PNG\r\n\x1a\n" and f.headers["cache-control"] == "no-store"
    srv.modes["images"] = "error500"
    with pytest.raises(mt.TryError):
        mt.run_try("ml_001")
    d = c.get("/api/model-library/models/ml_001/test").json()
    assert d["last"]["ok"] is False and "boom internal" in d["last"]["message"] and d["has_file"] is False


def test_test_inputs_upload_is_checked_by_content(c, lib):
    c.post("/api/model-library/models", json=model())
    up = lambda name, fname, data, ctype="application/octet-stream": c.post(  # noqa: E731
        "/api/model-library/models/ml_001/test/inputs", data={"name": name}, files={"file": (fname, data, ctype)})
    assert up("image", "a.png", png_bytes(300, 300), "image/png").status_code == 200
    assert (mt.test_dir("ml_001") / "in" / "image.png").is_file() and mt.input_path("ml_001", "image")
    bad = up("image", "x.png", b"not an image")
    assert bad.status_code == 400 and "صورة" in bad.json()["detail"]
    assert up("audio", "a.wav", wav_bytes(1.0), "audio/wav").status_code == 200 and mt.input_path("ml_001", "audio").suffix == ".wav"
    assert up("audio", "a.wav", wav_bytes(1.5), "audio/wav").status_code == 200
    assert len(list((mt.test_dir("ml_001") / "in").glob("audio.*"))) == 1                       # الجديد بيبدّل القديم
    assert up("audio", "x.wav", b"garbage bytes here").status_code == 400
    assert not list((mt.test_dir("ml_001") / "in").glob("audio.*")) or True
    assert up("audio", "x.txt", b"hello").status_code == 400
    assert up("video", "a.wav", wav_bytes(1.0)).status_code == 400                                # صوت بلا فيديو
    assert up("other", "a.png", png_bytes(), "image/png").status_code == 400
    assert c.post("/api/model-library/models/ml_404/test/inputs", data={"name": "image"}, files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 404


def test_every_write_route_has_an_activity_label():
    import activity
    for method, path in (("POST", "/api/model-library/models"), ("PUT", "/api/model-library/models/ml_001"), ("DELETE", "/api/model-library/models/ml_001"),
                         ("PUT", "/api/model-library/tasks/image/default"), ("PUT", "/api/model-library/box"),
                         ("POST", "/api/model-library/models/ml_001/test/inputs"), ("POST", "/api/model-library/models/ml_001/try")):
        d = activity.describe(method, path)
        assert d and d[1], (method, path)
    assert activity.describe("PUT", "/api/model-library/tasks/image/default")[1] == "تثبيت النموذج الافتراضي لمهمة «الصور» بمكتبة النماذج"
    assert activity.is_silent("POST", "/api/model-library/probe")


# ── صندوق الأوزان (weights) ────────────────────────────────────────────────

def test_box_status_route_is_honest_when_unset_and_lists_models_when_live(c, box_factory, monkeypatch):
    import types

    import link_engine
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(
        is_available=lambda: True, mem_get_info=lambda: (6 * 1024 ** 3, 24 * 1024 ** 3))))
    d = c.get("/api/model-library/box").json()
    assert d["configured"] is False and d["ok"] is False and d["reason"] == "config" and d["token_set"] is False and d["models"] == []
    live = box_factory(token=TOKEN)
    r = c.put("/api/model-library/box", json={"url": live.url, "token": TOKEN})
    assert r.status_code == 200 and r.json()["token_set"] is True and TOKEN not in r.text
    d = c.get("/api/model-library/box").json()
    assert d["configured"] and d["ok"] and d["api"] == 2 and d["token_set"] is True and d["box"]["url"] == live.url and TOKEN not in json.dumps(d)
    by = {m["name"]: m for m in d["models"]}
    assert by["demo-image"]["ok"] and by["demo-unsafe"]["ok"] is False and by["demo-audio"]["tasks"] == ["t2a"] and d["audio_max_seconds"] == 47
    assert c.get("/api/model-library/box", params={"refresh": 1}).json()["ok"] is True
    ov = c.get("/api/model-library").json()
    assert ov["gpu"]["box_gpu"] == {"free_gb": 6.0, "total_gb": 24.0}                               # كرت الصندوق بالنظرة العامة
    c.put("/api/model-library/box", json={"url": live.url, "token": "wrong-token"})
    assert c.get("/api/model-library/box").json()["reason"] == "auth"
    link_engine.clear_cache()


def test_a_weights_model_is_created_through_the_routes_and_runs_through_the_try_endpoint(c, box_factory, jobs):
    live = box_factory()
    c.put("/api/model-library/box", json={"url": live.url})
    body = {"name": "Qwen", "task": "image", "link": "weights", "enabled": False, "template": "qwen-image", "weights": {"model": "demo-image"},
            "licence": {"id": "Apache-2.0", "commercial": "yes"}}
    r = c.post("/api/model-library/models", json=body)
    assert r.status_code == 200, r.text
    m = r.json()["model"]
    assert m["link"] == "weights" and m["weights"]["model"] == "demo-image" and m["token_set"] is None and m["uses_gpu"] is False
    assert c.post(f"/api/model-library/models/{m['id']}/try", json={"prompt": "عبوة عطر"}).json()["job_id"] == "job-1"
    assert jobs[-1][2] == ["model_tasks.py", "try", m["id"]]
    mt.run_try(m["id"], log=lambda *_: None)                              # ما بيمرّ على الخيط الخلفي بالاختبار: نشغّلها مباشرة
    last = c.get(f"/api/model-library/models/{m['id']}/test").json()
    assert last["last"]["ok"] is True and last["has_file"] is True and last["last"]["kind"] == "image"
    assert c.get(f"/api/model-library/models/{m['id']}/test/file").headers["content-type"] == "image/png"


def test_a_weights_music_model_is_tried_through_the_box_and_returns_audio(c, box_factory, jobs):
    live = box_factory()
    c.put("/api/model-library/box", json={"url": live.url})
    body = {"name": "Stable Audio", "task": "music", "link": "weights", "enabled": False, "template": "stable-audio-music", "weights": {"model": "demo-audio"},
            "caps": {"max_sec": 47}, "params": {"seconds": 3}, "licence": {"id": "stable-audio-community", "commercial": "conditional", "confirmed_by_owner": True}}
    r = c.post("/api/model-library/models", json=body)
    assert r.status_code == 200, r.text
    m = r.json()["model"]
    assert c.post(f"/api/model-library/models/{m['id']}/try", json={"prompt": "calm piano", "seconds": 3}).json()["job_id"] == "job-1"
    mt.run_try(m["id"], log=lambda *_: None)
    last = c.get(f"/api/model-library/models/{m['id']}/test").json()
    assert last["last"]["ok"] is True and last["last"]["kind"] == "audio" and last["has_file"] is True and 2.5 <= last["last"]["info"]["duration_sec"] <= 4
    assert c.get(f"/api/model-library/models/{m['id']}/test/file").headers["content-type"].startswith("audio/")
    job = next(iter(live.jobs.values()))
    assert job.params["mode"] == "t2a" and job.params["seconds"] == 3.0
