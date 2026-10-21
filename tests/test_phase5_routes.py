import json
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vp_b1_helpers import TODAY, FakeCRM, ad, day, install_env, load_rows, perf_row, seed_market
from web import jobs, routes_crm

ALLOWED_PATTERN_KEYS = {"pattern_id", "name", "evidence_level", "evidence_score", "delivered", "spend",
                        "cost_per_delivered", "scripts", "reusability_opinion", "reason", "cost_vs_baseline",
                        "baseline_available", "scripts_total", "as_of"}
ALLOWED_SCRIPT_KEYS = {"script_file", "script_id", "delivered", "spend", "cost_per_delivered", "delivery_rate",
                       "verdict", "reason", "pattern_id", "baseline_cpd", "cost_vs_baseline", "as_of"}
FORBIDDEN = ("phone", "name_", "customer", "address", "order_id", "email")


@pytest.fixture
def env(tmp_path, monkeypatch):
    return install_env(tmp_path, monkeypatch)


@pytest.fixture
def client(env, monkeypatch):
    created = []

    def fake_create_job(kind, label, cmd):
        created.append((kind, cmd))
        return "job123"

    monkeypatch.setattr(jobs, "create_job", fake_create_job)
    monkeypatch.setitem(sys.modules, "queue_worker", None)      # وحدات B2: ما بنلمس الحقيقية
    monkeypatch.setitem(sys.modules, "backup", None)
    app = FastAPI()
    app.include_router(routes_crm.router)
    c = TestClient(app)
    c.jobs = created
    return c


def test_config_token_goes_to_secret_store_never_to_file_or_response(env, client):
    r = client.put("/api/crm/config", json={"base_url": "https://crm.example.com/", "token": "SUPER-SECRET-TOKEN"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "base_url": "https://crm.example.com", "token_set": True, "launch_token_set": False}
    assert env.secrets["crm_token"] == "SUPER-SECRET-TOKEN"
    assert "SUPER-SECRET-TOKEN" not in env.settings.read_text(encoding="utf-8")
    assert json.loads(env.settings.read_text(encoding="utf-8"))["CRM"]["base_url"] == "https://crm.example.com"

    st = client.get("/api/crm/status")
    assert st.status_code == 200 and "SUPER-SECRET-TOKEN" not in st.text
    body = st.json()
    assert body["configured"] and body["token_set"] and body["base_url"] == "https://crm.example.com"
    assert set(body) >= {"configured", "token_set", "base_url", "connected", "last_sync", "pending_queue",
                         "last_backup", "days_since_backup", "backup_alert"}
    assert set(body["last_sync"]) == {"at", "ok", "error", "rows"}

    d = client.delete("/api/crm/token")
    assert d.status_code == 200 and d.json()["token_set"] is False and "crm_token" not in env.secrets


def test_config_rejects_insecure_url(env, client):
    r = client.put("/api/crm/config", json={"base_url": "http://crm.example.com"})
    assert r.status_code == 400 and "HTTPS" in r.json()["detail"]


def test_status_when_unconfigured_and_optional_b2_modules_missing(env, client):
    body = client.get("/api/crm/status").json()
    assert body["configured"] is False and body["connected"] is False
    assert body["pending_queue"] is None and body["last_backup"] is None and body["backup_alert"] is None


def test_status_merges_b2_modules_when_present(env, client, monkeypatch):
    qw = types.ModuleType("queue_worker")
    qw.pending_count = lambda: 4
    bk = types.ModuleType("backup")
    bk.status = lambda: {"last_backup": {"at": "2026-09-28", "ok": True, "path": "x"},
                         "days_since_backup": 1, "backup_alert": False}
    monkeypatch.setitem(sys.modules, "queue_worker", qw)
    monkeypatch.setitem(sys.modules, "backup", bk)
    body = client.get("/api/crm/status").json()
    assert body["pending_queue"] == 4 and body["days_since_backup"] == 1 and body["backup_alert"] is False
    assert body["last_backup"]["ok"] is True


def test_sync_creates_job_only_when_configured(env, client):
    assert client.post("/api/crm/sync").status_code == 400
    s = FakeCRM()
    s.configure(env)
    try:
        r = client.post("/api/crm/sync")
    finally:
        s.stop()
    assert r.status_code == 200 and r.json() == {"job_id": "job123"}
    assert client.jobs == [("crm_sync", ["crm.py", "sync"])]


def test_status_after_real_sync_reports_last_sync(env, client):
    import crm
    s = FakeCRM()
    s.configure(env)
    try:
        _, sid = env.script("kama", 1, "p")
        s.rows = [perf_row(ad("kama", sid), day(-1), delivered=10, cpd=3.0)]
        assert crm.sync_performance(today=TODAY)["ok"]
        body = client.get("/api/crm/status").json()
    finally:
        s.stop()
    assert body["connected"] and body["last_sync"]["ok"] and body["last_sync"]["rows"] == 1


def test_ad_name_ready_and_missing(env, client):
    env.product("kama", landing="DawaCare")
    f, sid = env.script("kama", 109, "p", version=2)
    r = client.get(f"/api/scripts/{f}/ad-name").json()
    assert r["ready"] and r["ad_name"] == "SY|kama|DawaCare|video|VP-kama-109-v2" and r["missing"] == []
    assert r["parts"] == {"country": "SY", "product": "kama", "landing_page": "DawaCare",
                          "type": "video", "script_id": "VP-kama-109-v2"}
    assert client.get(f"/api/scripts/{f[:-5]}/ad-name").json()["ready"]          # بدون .json

    env.product("vara", landing="", country="")
    f2, _ = env.script("vara", 1, "p")
    r2 = client.get(f"/api/scripts/{f2}/ad-name").json()
    assert not r2["ready"] and r2["ad_name"] is None and set(r2["missing"]) == {"country", "landing_page"}

    f3, _ = env.script("kama", 2, "p", with_id=False)
    r3 = client.get(f"/api/scripts/{f3}/ad-name").json()
    assert not r3["ready"] and "script_id" in r3["missing"]
    assert client.get("/api/scripts/nope.json/ad-name").status_code == 404


def test_performance_endpoints_shape_order_and_no_personal_fields(env, client):
    env.pattern("good", name="نمط جيد", reusability=1)
    env.pattern("hyped", reusability=10)
    seed_market(env, "kama", [(1, "good", 2.0, 80), (2, "good", 2.0, 80), (3, "x", 4.0, 60), (4, "y", 4.0, 60),
                              (5, "hyped", 9.0, 60)])
    pats = client.get("/api/performance/patterns").json()
    assert pats[0]["pattern_id"] == "good" and pats[0]["evidence_level"] == "proven"
    scores = [p["evidence_score"] for p in pats]
    assert scores == sorted(scores, reverse=True)
    assert all(set(p) == ALLOWED_PATTERN_KEYS for p in pats)
    assert pats[0]["reusability_opinion"] == 1

    scripts = client.get("/api/performance/scripts").json()
    assert all(set(s) == ALLOWED_SCRIPT_KEYS for s in scripts)
    assert {s["verdict"] for s in scripts} <= {"winner", "ok", "loser", "insufficient"}
    blob = json.dumps(pats + scripts).lower()
    assert not any(bad in blob for bad in FORBIDDEN)

    assert client.get("/api/performance/alerts").json() == []


def test_learning_endpoints(env, client):
    last = client.get("/api/learning/last").json()
    assert set(last) >= {"at", "results", "skipped_reason"} and last["results"] == []
    r = client.post("/api/learning/run")
    assert r.json() == {"job_id": "job123"} and client.jobs[-1] == ("learn", ["learn_patterns.py"])
