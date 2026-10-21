import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import drafts
import fatigue
import stage3_generate
from vp_b1_helpers import FakeCRM, TODAY, ad, install_env, load_rows, seed_market, series
from web import jobs, routes_crm


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = install_env(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "queue_worker", None)
    monkeypatch.setitem(sys.modules, "backup", None)
    return e


@pytest.fixture
def server(env):
    s = FakeCRM()
    s.configure(env)
    yield s
    s.stop()


@pytest.fixture
def written(monkeypatch):
    calls = []

    def fake_write(product_path, pattern_id=None, *, review=True):
        calls.append((Path(product_path), pattern_id))
        return Path(product_path).parent / f"new_{pattern_id}.json"

    monkeypatch.setattr(stage3_generate, "write_for_product", fake_write, raising=False)
    return calls


def fatigued_kama(env):
    """kama بإعلان مُتعب + مكتبة أنماط فيها مثبت/مستخدم/بعيد/ضعيف."""
    env.product("kama", category="eye_care")
    env.product("vara", category="eye_care")
    _, sid = env.script("kama", 1, "kama_used")
    env.script("kama", 2, "great_used")                   # kama استخدمه قبل
    for p, cat in (("good", "eye_care"), ("great_used", "eye_care"), ("far_best", "apparel"),
                   ("adjacent_ok", "supplements"), ("weak_one", "eye_care"), ("kama_used", "eye_care")):
        env.pattern(p, category=cat, name=f"نمط {p}")
    seed_market(env, "vara", [
        (1, "good", 2.0, 80), (2, "good", 2.0, 80),
        (3, "great_used", 1.5, 90), (4, "great_used", 1.5, 90),
        (5, "far_best", 1.0, 100), (6, "far_best", 1.0, 100),
        (7, "adjacent_ok", 2.6, 60), (8, "adjacent_ok", 2.6, 60),
        (9, "weak_one", 1.8, 90),
        (10, "filler", 4.0, 60), (11, "filler2", 4.0, 60), (12, "filler3", 4.0, 60)])
    load_rows(series(ad("kama", sid), 8))
    return ad("kama", sid)


def test_draft_picks_best_proven_unused_pattern_in_reachable_category(env, server):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    d = drafts.get(did)
    sp = d["suggested_pattern"]
    assert sp["pattern_id"] == "good"                     # great_used مستخدم، far_best فئة بعيدة، weak_one مش مثبت
    assert sp["evidence_level"] == "proven"
    assert "نمط good" in d["pattern_note"] and "مثبت" in d["pattern_note"]
    assert d["status"] == "pending" and d["product"]["file"] == "kama.json"


def test_draft_has_no_unproven_suggestion_when_nothing_proven(env, server):
    env.product("kama")
    _, sid = env.script("kama", 1, "kama_used")
    env.pattern("kama_used")
    load_rows(series(ad("kama", sid), 8))
    (did,) = fatigue.scan_and_draft(TODAY)
    d = drafts.get(did)
    assert d["suggested_pattern"] is None and "ما في نمط مثبت" in d["pattern_note"]


def test_draft_carries_aggregated_failure_reasons_live(env, server):
    server.failures = {"kama": {"reasons": [{"reason": "رفض الاستلام", "count": 14, "customer_phone": "0999123456"},
                                            {"reason": "الزبون ما ردّ", "count": 31}]}}
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    fr = drafts.get(did)["failure_reasons"]
    assert fr["status"] == "live" and fr["items"] == [{"reason": "الزبون ما ردّ", "count": 31},
                                                     {"reason": "رفض الاستلام", "count": 14}]
    assert "0999123456" not in str(drafts.get(did))


def test_offline_uses_last_cached_failure_reasons_and_says_so(env, server):
    server.failures = {"kama": {"reasons": [{"reason": "رفض الاستلام", "count": 14}]}}
    import crm
    crm.fetch_failure_reasons("kama", "SY")               # نسخة مخزّنة من قبل
    server.mode = "503"
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    d = drafts.get(did)
    assert d["failure_reasons"]["status"] == "offline_cached"
    assert d["failure_reasons"]["items"] == [{"reason": "رفض الاستلام", "count": 14}]
    assert d["failure_reasons"]["as_of"] and "غير متصل" in d["brief_text"] and "مخزّنة" in d["brief_text"]


def test_offline_without_cache_says_unavailable(env, server):
    server.mode = "503"
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    fr = drafts.get(did)["failure_reasons"]
    assert fr["status"] == "offline_none" and fr["items"] == []
    assert "غير متوفرة" in drafts.get(did)["brief_text"]


def test_crm_not_configured_still_drafts(env):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    assert drafts.get(did)["failure_reasons"]["status"] == "offline_none"


def test_nothing_is_written_until_approved_then_calls_writer_with_pattern(env, server, written):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    assert written == []                                   # بيستنى موافقة
    d = drafts.approve(did)
    assert written == [(env.products / "kama.json", "good")]
    assert d["status"] == "approved" and d["result_script"] == "new_good.json" and d["approved_at"]
    with pytest.raises(drafts.DraftError):
        drafts.approve(did)                                # ما بتنكتب مرتين
    assert len(written) == 1


def test_writer_failure_returns_draft_to_pending_with_error(env, server, monkeypatch):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)

    def boom(*a, **k):
        raise RuntimeError("فشل الكاتب")
    monkeypatch.setattr(stage3_generate, "write_for_product", boom, raising=False)
    with pytest.raises(RuntimeError):
        drafts.approve(did)
    d = drafts.get(did)
    assert d["status"] == "pending" and "فشل الكاتب" in d["error"]


def test_dismiss_and_rules(env, server, written):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    assert drafts.dismiss(did)["status"] == "dismissed"
    assert fatigue.scan_and_draft(TODAY) == []             # المرفوضة ما بتنعاد
    with pytest.raises(drafts.DraftError):
        drafts.approve(did)
    assert written == []
    with pytest.raises(drafts.DraftError):
        drafts.dismiss("dr_nonexistent")


def test_drafts_cli_approve(env, server, written, capsys):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    drafts.begin_approve(did)
    assert drafts.main(["approve", did, "--started"]) == 0
    assert "new_good.json" in capsys.readouterr().out and written[0][1] == "good"


# ───────────── المسارات ─────────────


@pytest.fixture
def client(env, monkeypatch):
    created = []
    monkeypatch.setattr(jobs, "create_job", lambda kind, label, cmd: created.append((kind, cmd)) or "job9")
    app = FastAPI()
    app.include_router(routes_crm.router)
    c = TestClient(app)
    c.jobs = created
    return c


def test_alerts_endpoint_links_draft_and_dismiss_hides_it(env, server, client):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    alerts = client.get("/api/performance/alerts").json()
    assert len(alerts) == 1 and alerts[0]["type"] == "fatigue" and alerts[0]["draft_id"] == did
    assert set(alerts[0]) >= {"id", "ad_name", "script_id", "type", "since", "detail", "draft_id"}

    lst = client.get("/api/drafts").json()
    assert [d["id"] for d in lst] == [did] and lst[0]["status"] == "pending"

    r = client.post(f"/api/drafts/{did}/dismiss")
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert client.get("/api/performance/alerts").json() == []
    assert client.post(f"/api/drafts/{did}/dismiss").status_code == 409
    assert client.post("/api/drafts/dr_missing/dismiss").status_code == 404


def test_approve_endpoint_starts_job_and_blocks_double_approval(env, server, client):
    fatigued_kama(env)
    (did,) = fatigue.scan_and_draft(TODAY)
    r = client.post(f"/api/drafts/{did}/approve")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "job_id": "job9", "draft_id": did, "status": "approving"}
    assert client.jobs == [("draft_approve", ["drafts.py", "approve", did, "--started"])]
    assert client.post(f"/api/drafts/{did}/approve").status_code == 409
    assert len(client.jobs) == 1
    assert client.post("/api/drafts/dr_missing/approve").status_code == 404
    assert client.post("/api/drafts/scan").json()["created"] == []
