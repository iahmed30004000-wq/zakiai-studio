import json
import sqlite3
from datetime import date

import pytest

import crm
from vp_b1_helpers import FakeCRM, TODAY, ad, day, install_env, perf_row


@pytest.fixture
def env(tmp_path, monkeypatch):
    return install_env(tmp_path, monkeypatch)


@pytest.fixture
def server(env):
    s = FakeCRM()
    s.configure(env)
    yield s
    s.stop()


def test_sync_pulls_performance_and_links_script(env, server):
    f, sid = env.script("kama", 1, "p1")
    name = ad("kama", sid)
    server.rows = [perf_row(name, day(-2), delivered=10, cpd=3.0, engagement=0.02),
                   perf_row(name, day(-1), delivered=12, cpd=3.1, engagement=0.021)]
    r = crm.sync_performance(today=TODAY)
    assert r["ok"] and r["rows"] == 2
    rows = crm.perf_rows()
    assert [x["date"] for x in rows] == [day(-2), day(-1)]
    assert all(x["script_id"] == sid for x in rows)
    st = crm.sync_state()
    assert st["last_success"] and st["last_error"] is None and st["synced_through"] == TODAY.isoformat()


def test_device_off_three_days_then_catches_up_all_three(env, server):
    _, sid = env.script("kama", 1, "p1")
    name = ad("kama", sid)
    server.rows = [perf_row(name, day(-1), delivered=10, cpd=3.0)]
    assert crm.sync_performance(today=TODAY)["ok"]
    assert len(crm.perf_rows()) == 1

    # الجهاز مطفي 3 أيام: الـ OMS بيتراكم فيه أداء الأيام 0 و+1 و+2
    server.rows += [perf_row(name, day(i), delivered=10 + i, cpd=3.2) for i in (0, 1, 2)]
    server.requests.clear()
    back_on = date.fromisoformat(day(3))
    r = crm.sync_performance(today=back_on)
    assert r["ok"]
    assert [x["date"] for x in crm.perf_rows()] == [day(-1), day(0), day(1), day(2)]

    # نقطة البداية كانت قبل آخر مزامنة ناجحة (مش بعدها) — ما ضاع أي يوم
    ((path, params),) = server.requests
    assert params["since"] <= day(0) and params["until"] == back_on.isoformat()
    assert crm.sync_state()["synced_through"] == back_on.isoformat()


def test_failed_sync_does_not_advance_state_and_next_sync_recovers(env, server):
    _, sid = env.script("kama", 1, "p1")
    name = ad("kama", sid)
    server.rows = [perf_row(name, day(-1), delivered=10, cpd=3.0)]
    assert crm.sync_performance(today=TODAY)["ok"]
    through = crm.sync_state()["synced_through"]

    server.mode = "503"
    server.rows.append(perf_row(name, day(0), delivered=9, cpd=3.0))
    r = crm.sync_performance(today=date.fromisoformat(day(1)))
    assert not r["ok"] and r["offline"] and "الـ OMS" in r["error"]
    st = crm.sync_state()
    assert st["synced_through"] == through and st["last_error"]

    server.mode = "ok"
    assert crm.sync_performance(today=date.fromisoformat(day(1)))["ok"]
    assert {x["date"] for x in crm.perf_rows()} == {day(-1), day(0)}


def test_upsert_is_idempotent_and_updates_matured_delivery(env, server):
    _, sid = env.script("kama", 1, "p1")
    name = ad("kama", sid)
    server.rows = [perf_row(name, day(-2), delivered=5, cpd=4.0)]
    crm.sync_performance(today=TODAY)
    crm.sync_performance(today=TODAY)
    assert len(crm.perf_rows()) == 1

    server.rows = [perf_row(name, day(-2), delivered=9, cpd=4.0)]   # التسليم نضج
    crm.sync_performance(today=TODAY)
    rows = crm.perf_rows()
    assert len(rows) == 1 and rows[0]["delivered"] == 9


def test_no_customer_data_is_stored(env, server):
    _, sid = env.script("kama", 1, "p1")
    name = ad("kama", sid)
    dirty = perf_row(name, day(-1), delivered=10, cpd=3.0, customer_phone="0999123456",
                     customer_name="سارة", address="شارع الثورة", order_id="A-991")
    server.rows = [dirty]
    assert crm.sync_performance(today=TODAY)["ok"]

    with sqlite3.connect(crm.perf_db_path()) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(ad_daily)")}
    assert cols == set(crm.ROW_KEYS) | {"script_id", "synced_at"}
    raw = crm.perf_db_path().read_bytes()
    for leaked in ("0999123456", "سارة", "شارع", "A-991"):
        assert leaked.encode("utf-8") not in raw
    assert set(crm.perf_rows()[0]) <= set(crm.ROW_KEYS) | {"script_id", "synced_at"}


def test_four_part_ad_is_stored_but_has_no_script(env, server):
    server.rows = [perf_row("SY|kama|DawaCare|video", day(-1), delivered=10, cpd=3.0)]
    assert crm.sync_performance(today=TODAY)["ok"]
    rows = crm.perf_rows()
    assert len(rows) == 1 and rows[0]["script_id"] is None
    assert crm.perf_rows(vp_only=True) == []


def test_error_taxonomy(env, server):
    server.mode = "503"
    with pytest.raises(crm.CRMOffline):
        crm.get_client().get(crm.PERF_PATH, params={"since": "2026-01-01", "until": "2026-01-02"})
    server.mode = "badjson"
    with pytest.raises(crm.CRMError):
        crm.get_client().get(crm.PERF_PATH)
    server.mode = "redirect"
    with pytest.raises(crm.CRMError):
        crm.get_client().get(crm.PERF_PATH)
    server.mode = "ok"
    env.secrets["crm_token"] = "wrong"
    with pytest.raises(crm.CRMError):
        crm.get_client().get(crm.PERF_PATH)


def test_wrong_shape_is_crm_error_not_stored(env, server):
    server.rows = [{"ad_name": "x|y|z|video", "date": "2026-09-01", "spend": "abc", "orders": 1, "delivered": 1}]
    r = crm.sync_performance(today=TODAY)
    assert not r["ok"] and r["offline"] is False
    assert crm.perf_rows() == []


def test_connection_refused_is_offline(env):
    s = FakeCRM()
    s.configure(env)
    s.stop()
    r = crm.sync_performance(today=TODAY)
    assert not r["ok"] and r["offline"]


def test_not_configured_is_offline_subclass(env):
    assert not crm.is_configured()
    with pytest.raises(crm.CRMOffline):
        crm.get_client()
    r = crm.sync_performance(today=TODAY)
    assert not r["ok"] and "غير مضبوط" in r["error"]


def test_base_url_falls_back_to_settings_file_and_env_token(env, monkeypatch):
    env.settings.write_text(json.dumps({"CRM": {"base_url": "https://crm.example.com/"}}), encoding="utf-8")
    assert crm.base_url() == "https://crm.example.com"
    assert not crm.is_configured()
    monkeypatch.setenv("VP_CRM_TOKEN", "t")
    assert crm.is_configured()


def test_https_is_enforced_except_localhost():
    assert crm.validate_base_url("https://crm.example.com/") == "https://crm.example.com"
    assert crm.validate_base_url("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
    for bad in ("http://crm.example.com", "ftp://x", "", "https://user:pw@crm.example.com", "https://a.com?x=1"):
        with pytest.raises(crm.CRMError):
            crm.validate_base_url(bad)


def test_product_facts_normalized_cached_and_offline_uses_cache(env, server):
    server.facts = {"kama": {
        "country": "sy", "dialect": "Shami", "price": {"amount": 45000, "currency": "SYP", "display": "45,000 ل.س"},
        "offer_tiers": [{"qty": 2, "price": {"amount": 80000, "currency": "SYP"}}], "cod": True,
        "delivery": {"days_min": 2, "days_max": 4}, "guarantee": None, "customer_phone": "0999123456"}}
    facts = crm.fetch_product_facts("kama", "SY")
    assert facts["price"] == "45,000 ل.س" and facts["country"] == "SY" and facts["dialect"] == "shami"
    assert facts["offer"] == "2 بـ 80000 SYP" and facts["no_offer"] is False
    assert facts["guarantee"] == "" and facts["no_guarantee"] is True
    assert not any(k.startswith("_") or k == "customer_phone" for k in facts)
    assert crm.market_extras("kama", "SY")["cod"] is True

    server.mode = "503"
    with pytest.raises(crm.CRMOffline) as ei:
        crm.fetch_product_facts("kama", "SY")
    assert ei.value.cached["country"] == "SY" and ei.value.cached_at
    assert crm.cached_product_facts("kama", "SY")[0]["country"] == "SY"


def test_absent_fields_do_not_erase_brief(env, server):
    server.facts = {"kama": {"price": "12"}}
    assert crm.fetch_product_facts("kama", "SY") == {"price": "12"}


def test_failure_reasons_aggregate_only(env, server):
    server.failures = {"kama": {"reasons": [
        {"reason": "رفض الاستلام", "count": 14, "customer_phone": "0999"},
        {"reason": "الزبون ما ردّ", "count": 31},
        {"reason": "اتصل على 0999123456", "count": 5},
        {"reason": "ahmed@mail.com", "count": 2}]}}
    got = crm.fetch_failure_reasons("kama", "SY")
    assert got == [{"reason": "الزبون ما ردّ", "count": 31}, {"reason": "رفض الاستلام", "count": 14}]
    server.mode = "503"
    with pytest.raises(crm.CRMOffline) as ei:
        crm.fetch_failure_reasons("kama", "SY")
    assert ei.value.cached == got
