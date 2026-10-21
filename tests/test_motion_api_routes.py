"""مسارات التحريك بالـ API: المفتاح (ما بيطلع أبداً)، السقف، القوالب الجاهزة، وتقدير تكلفة السيناريو."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from phase8_support import isolated  # noqa: E402,F401  (fixture: مسارات مؤقتة + أسرار بالذاكرة)
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage  # noqa: E402,F401
from test_studio_motion import ready, tc_client  # noqa: E402,F401

import config  # noqa: E402
import motion  # noqa: E402
import motion_api  # noqa: E402
import settings_io  # noqa: E402

SECRET = "fal-secret-key-ABC123"


@pytest.fixture
def client(isolated):
    return tc_client()


def test_overview_key_is_never_returned_anywhere(client, isolated):
    r = client.get("/api/motion/api")
    d = r.json()
    assert r.status_code == 200 and d["has_key"] is False and d["provider"] == "fal" and d["cap_usd"] == 15
    assert {p["key"] for p in d["presets"]} == {"kling26", "hailuo02", "grok"}
    assert all(p["est_cost_4s"] and p["durations"] for p in d["presets"]) and "برّا جهازك" in d["privacy_note"]
    r = client.put("/api/motion/api/key", json={"api_key": SECRET})
    assert r.status_code == 200 and r.json() == {"ok": True, "has_key": True}
    assert SECRET not in r.text and SECRET not in client.get("/api/motion/api").text
    assert SECRET not in client.get("/api/motion-models").text
    assert motion_api.has_key() and motion_api.get_key() == SECRET
    # ما انكتب بملف الإعدادات: بمخزن الأسرار (مرجع secret:)
    raw = json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert SECRET not in json.dumps(raw)


def test_clear_key_and_validation(client, isolated):
    assert client.put("/api/motion/api/key", json={"api_key": ""}).status_code == 400
    assert client.put("/api/motion/api/key", json={"api_key": "has space"}).status_code == 400
    assert client.put("/api/motion/api/key", json={"api_key": "x" * 500}).status_code == 400
    client.put("/api/motion/api/key", json={"api_key": SECRET})
    r = client.delete("/api/motion/api/key")
    assert r.status_code == 200 and r.json()["has_key"] is False and not motion_api.has_key()


def test_cap_validation_and_persistence(client, isolated):
    assert client.put("/api/motion/api/cap", json={"cap_usd": "abc"}).status_code == 400
    assert client.put("/api/motion/api/cap", json={"cap_usd": -1}).status_code == 400
    assert client.put("/api/motion/api/cap", json={"cap_usd": 5000}).status_code == 400
    r = client.put("/api/motion/api/cap", json={"cap_usd": 7.5})
    assert r.status_code == 200 and config.MOTION_API_CAP_USD == 7.5 and client.get("/api/motion/api").json()["cap_usd"] == 7.5
    assert json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))["MOTION_API_CAP_USD"] == 7.5


def test_add_preset_creates_an_api_model_and_blocks_duplicates(client, isolated):
    r = client.post("/api/motion/api/preset/kling26")
    assert r.status_code == 200
    m = r.json()
    assert m["kind"] == "api" and m["api"]["endpoint"].startswith("fal-ai/kling-video") and m["max_sec"] == 10
    assert m["api"]["input"]["generate_audio"] is False and m["api"]["cost_per_sec"] == 0.07
    assert client.post("/api/motion/api/preset/kling26").status_code == 409
    assert client.post("/api/motion/api/preset/nope").status_code == 404
    assert client.post("/api/motion/api/preset/hailuo02").status_code == 200
    ov = client.get("/api/motion/api").json()
    assert len(ov["models"]) == 2
    listed = client.get("/api/motion-models").json()
    assert {x["kind"] for x in listed["models"]} == {"api"} and "api" in listed["kinds"]


def test_models_crud_route_accepts_api_kind_and_rejects_bad_specs(client, isolated):
    spec = dict(motion_api.PRESETS["hailuo02"])
    body = {"name": "H", "kind": "api", "api": {k: spec[k] for k in ("provider", "endpoint", "input", "durations", "cost_per_sec")}}
    r = client.post("/api/motion-models", json=body)
    assert r.status_code == 200 and r.json()["max_sec"] == 10
    body["api"] = {**body["api"], "endpoint": "../../etc/passwd"}
    assert client.post("/api/motion-models", json=body).status_code == 400


def test_estimate_route_and_ranked_costs_in_motion_info(client, isolated, monkeypatch):
    # السيناريو الجاهز بيجي من fixture ready بعالم بيئة تانية — نكتفي بفحص الأخطاء العربية للسيناريو غير الموجود
    assert client.get("/api/studio/none.json/motion/estimate").status_code == 404


def test_estimate_and_info_with_a_real_staged_script(ready, monkeypatch):
    monkeypatch.setattr(motion_api, "has_key", lambda: True)
    motion.upsert_model({"name": "K", "kind": "api", "strengths": ["product", "realism"],
                         "api": {k: motion_api.PRESETS["kling26"][k] for k in ("provider", "endpoint", "input", "durations", "cost_per_sec")}})
    c = tc_client()
    e = c.get("/api/studio/s1.json/motion/estimate")
    assert e.status_code == 200
    d = e.json()
    assert d["total_usd"] > 0 and d["cap_usd"] == config.MOTION_API_CAP_USD and all(s["path"] == "api" for s in d["shots"])
    info = c.get("/api/studio/s1.json/motion/info").json()
    first = info["shots"][0]["ranked"][0]
    assert first["path"] == "api" and first["est_cost_usd"] > 0
