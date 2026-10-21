import json
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backup
import secrets_store
import settings_io
import usage
from tests.phase8_support import (FakeCRM, install_fake_crm, isolated, make_library,
                                  sample_settings)
from web import routes_ops


@pytest.fixture
def client(isolated, monkeypatch):
    make_library(isolated)
    settings_io.save(sample_settings())
    app = FastAPI()
    app.include_router(routes_ops.router)
    isolated.mp = monkeypatch
    isolated.out = isolated.tmp / "drive"
    return TestClient(app)


def test_spend_limits_get_put(client, isolated):
    r = client.get("/api/settings/spend-limits")
    assert r.status_code == 200 and r.json()["daily_usd"] is None and r.json()["blocked"] is False
    r = client.put("/api/settings/spend-limits", json={"daily_usd": 5, "monthly_usd": 100})
    assert r.status_code == 200 and r.json()["daily_usd"] == 5.0 and r.json()["monthly_usd"] == 100.0
    assert client.get("/api/settings/spend-limits").json()["monthly_usd"] == 100.0
    bad = client.put("/api/settings/spend-limits", json={"daily_usd": -3})
    assert bad.status_code == 400 and "detail" in bad.json()
    usage.record("writer", "openai", "gpt-5", 10_000_000, 0)
    client.put("/api/settings/spend-limits", json={"daily_usd": 1})
    body = client.get("/api/settings/spend-limits").json()
    assert body["blocked"] is True and "حد الإنفاق" in body["reason"] and body["spent_today_usd"] > 1


def test_backup_endpoints_end_to_end(client, isolated):
    st = client.get("/api/backup/status").json()
    assert st["alert"] is True and st["configured"] is False
    err = client.post("/api/backup/run")
    assert err.status_code == 400 and "مضبوط" in err.json()["detail"]

    r = client.put("/api/backup/config", json={"dir": str(isolated.out)})
    assert r.status_code == 200 and r.json()["dir"] == str(isolated.out)
    run = client.post("/api/backup/run")
    assert run.status_code == 200 and run.json()["ok"] and run.json()["files"] > 5
    st = client.get("/api/backup/status").json()
    assert st["alert"] is False and st["last"]["ok"] is True

    rt = client.post("/api/backup/restore-test").json()
    assert rt["ok"] and rt["match"] and rt["files_backup"] == rt["files_restored"]


def test_export_key_once_and_local_only(client, isolated):
    client.put("/api/backup/config", json={"dir": str(isolated.out)})
    first = client.post("/api/backup/export-key").json()
    assert first["ok"] and first["key"] == secrets_store.get_secret("backup_key")
    second = client.post("/api/backup/export-key").json()
    assert second["ok"] is False and "key" not in second

    remote = TestClient(client.app, client=("192.168.1.50", 5555))
    r = remote.post("/api/backup/export-key")
    assert r.status_code == 403 and "key" not in r.text


def test_queue_endpoints(client, isolated):
    (isolated.products / "kama.json").write_text('{"product_code": "kama"}', encoding="utf-8")
    stage3 = types.ModuleType("stage3_generate")
    stage3.match_for_product = lambda p: {"ranked_patterns": [{"pattern_id": "p1", "pattern_name": "n"}]}
    isolated.mp.setitem(sys.modules, "stage3_generate", stage3)
    fake = FakeCRM([{"id": "q1", "type": "best_patterns", "payload": {"product_code": "kama"}}])
    install_fake_crm(isolated.mp, fake)

    assert client.get("/api/queue").json()["pending_count"] == 0
    res = client.post("/api/queue/poll").json()
    assert res["ok"] and res["counts"] == {"drafted": 1}
    view = client.get("/api/queue").json()
    assert view["pending_count"] == 0 and view["items"][0]["id"] == "q1"
    assert view["items"][0]["status"] == "done"
    assert fake.results["q1"][0]["status"] == "draft"


def test_scheduler_status_endpoint(client, isolated):
    r = client.get("/api/scheduler/status")
    assert r.status_code == 200
    body = r.json()
    assert {t["task"] for t in body["tasks"]} >= {"queue_poll", "backup_daily", "library_sync"}


def test_errors_are_arabic_detail_and_no_keys_in_responses(client, isolated):
    everything = ""
    for method, path in (("get", "/api/backup/status"), ("get", "/api/queue"),
                         ("get", "/api/scheduler/status"), ("get", "/api/settings/spend-limits"),
                         ("get", "/api/backup/config")):
        everything += getattr(client, method)(path).text
    for k in ("FAKEKEY",):
        assert k not in everything
    (isolated.tmp / "a_file").write_text("x", encoding="utf-8")
    r = client.put("/api/backup/config", json={"dir": str(isolated.tmp / "a_file" / "x")})
    assert r.status_code == 400 and "detail" in r.json()
