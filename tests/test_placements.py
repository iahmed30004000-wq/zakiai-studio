"""تسجيل الإعلان المنشور بالحساب الإعلاني (ميتا/تيك توك/سناب…): تحقق، تكرار، ربط بالأداء، حملات العمليات، المسارات."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import config  # noqa: E402
import crm  # noqa: E402
import placements  # noqa: E402

VP = "VP-vara-3-v1"


def good(**kw):
    d = {"platform": "meta", "ad_account_name": "متجر صحة بلس", "ad_account_id": "act_1234567890",
         "campaign_name": "اختبار VARA", "campaign_id": "120210000000001", "ad_name": f"SY|vara|page|video|{VP}",
         "published_at": "2026-10-20", "budget_daily": 15, "currency": "usd"}
    d.update(kw)
    return d


# ───────── التحقق ─────────
@pytest.mark.parametrize("bad,msg", [
    ({"platform": "myspace"}, "المنصة"),
    ({"status": "x"}, "الحالة"),
    ({"source": "x"}, "مصدر"),
    ({"ad_name": ""}, "اسم الإعلان"),
    ({"ad_name": "a\nb"}, "سطر واحد"),
    ({"ad_name": "x" * 201}, "أطول"),
    ({"ad_account_name": "", "ad_account_id": ""}, "الحساب الإعلاني"),
    ({"ad_account_id": "act 123"}, "أحرف إنجليزية"),
    ({"campaign_id": "ح" * 5}, "أحرف إنجليزية"),
    ({"ad_url": "http://x.com/a"}, "https"),
    ({"ad_url": "https://x.com/a b"}, "https"),
    ({"published_at": "20/10/2026"}, "YYYY-MM-DD"),
    ({"budget_daily": "abc"}, "رقم"),
    ({"budget_daily": -5}, "المعقول"),
    ({"notes": "كلّم ahmed@mail.com"}, "إيميلات"),
    ({"notes": "رقمه 0944 123 456"}, "هواتف"),
    ({"campaign_name": "اتصل 963944123456"}, "هواتف"),
])
def test_invalid_entries_are_rejected_with_arabic_reasons(env, bad, msg):
    with pytest.raises(placements.PlacementError, match=msg):
        placements.add(VP, good(**bad))
    assert placements.list_for(VP) == []


def test_long_ids_are_fine_and_not_mistaken_for_phone_numbers(env):
    e = placements.add(VP, good(ad_account_id="act_123456789012345678", campaign_id="120210000000123456", ad_id="6123456789012345"))
    assert e["campaign_id"] == "120210000000123456" and e["currency"] == "USD" and e["budget_daily"] == 15.0


# ───────── الإضافة والتعديل والحذف ─────────
def test_add_edit_delete_and_file_lives_in_the_library(env):
    e = placements.add(VP, good())
    assert e["id"].startswith("pl_") and e["status"] == "published" and e["source"] == "manual"
    assert (config.LIBRARY_DIR / "placements" / f"{VP}.json").exists()
    upd = placements.update(VP, e["id"], {"status": "paused", "notes": "وقفناه للاختبار"})
    assert upd["status"] == "paused" and upd["ad_name"] == e["ad_name"] and upd["updated_at"] >= e["created_at"]
    placements.delete(VP, e["id"])
    assert placements.list_for(VP) == []
    with pytest.raises(placements.PlacementError, match="غير موجود"):
        placements.delete(VP, e["id"])
    with pytest.raises(placements.PlacementError, match="غير موجود"):
        placements.update(VP, "pl_nope", {})


def test_duplicate_ad_is_refused_but_other_platforms_or_accounts_are_fine(env):
    a = placements.add(VP, good())
    with pytest.raises(placements.PlacementError, match="مسجّل أصلاً"):
        placements.add(VP, good(campaign_name="تاني"))                                 # نفس الاسم والحساب والمنصة
    placements.add(VP, good(platform="tiktok"))                                       # منصة تانية
    placements.add(VP, good(ad_account_id="act_999"))                                 # حساب تاني
    with pytest.raises(placements.PlacementError, match="مسجّل أصلاً"):
        placements.add(VP, good(ad_name="غير هيك", ad_id="777", ad_account_id="act_555"))   # ما اتكرر بعد
        placements.add(VP, good(ad_name="غير هيك 2", ad_id="777", ad_account_id="act_556"))
    with pytest.raises(placements.PlacementError, match="بيطابق"):
        placements.update(VP, a["id"], {"platform": "tiktok"})


def test_limit_per_script(env, monkeypatch):
    monkeypatch.setattr(placements, "MAX_ENTRIES", 2)
    placements.add(VP, good(ad_name="a1"))
    placements.add(VP, good(ad_name="a2"))
    with pytest.raises(placements.PlacementError, match="الحد"):
        placements.add(VP, good(ad_name="a3"))


def test_no_script_id_gives_a_clear_message(env):
    with pytest.raises(placements.PlacementError, match="script_id"):
        placements.add("", good())
    assert placements.list_for("") == []


# ───────── الربط بالأداء ─────────
def test_script_for_matches_registered_ad_names_and_never_guesses(env):
    other = "VP-vara-4-v1"
    placements.add(VP, good(ad_name="  اعلان  عادي بدون VP "))
    assert placements.script_for("اعلان عادي بدون vp") == VP                           # مسافات وحروف كبيرة مو مشكلة
    assert placements.script_for("اعلان غير مسجّل") is None
    placements.add(other, good(ad_name="اعلان عادي بدون VP"))                         # نفس الاسم لسيناريو تاني ← غموض
    assert placements.script_for("اعلان عادي بدون VP") is None


def test_performance_rows_link_to_the_script_through_the_registry(env, monkeypatch):
    rows = [{"ad_name": "اعلان بلا خانة خامسة", "date": "2026-10-10", "spend": 20.0, "orders": 4, "delivered": 3, "collected": 100,
             "delivery_rate": 0.75, "cost_per_delivered": 6.67, "engagement": None},
            {"ad_name": f"SY|vara|page|video|{VP}", "date": "2026-10-10", "spend": 5.0, "orders": 1, "delivered": 1, "collected": 30,
             "delivery_rate": 1.0, "cost_per_delivered": 5.0, "engagement": None}]
    crm.upsert_rows(rows)
    sid = lambda nm: next(r["script_id"] for r in crm.perf_rows() if r["ad_name"] == nm)
    assert sid("اعلان بلا خانة خامسة") is None and sid(f"SY|vara|page|video|{VP}") == VP    # بدون تسجيل: برّا التعلّم
    placements.add(VP, good(ad_name="اعلان بلا خانة خامسة"))                          # التسجيل بيربط الصفوف المخزّنة فوراً
    assert sid("اعلان بلا خانة خامسة") == VP
    crm.upsert_rows(rows)                                                              # والمزامنة الجاية كمان بتحافظ عليه
    assert sid("اعلان بلا خانة خامسة") == VP
    assert [r["script_id"] for r in crm.perf_rows(vp_only=True)].count(VP) == 2


def test_existing_vp_fifth_slot_still_wins_over_the_registry(env):
    placements.add("VP-vara-9-v9", good(ad_name=f"SY|vara|page|video|{VP}"))            # تسجيل مضلّل
    crm.upsert_rows([{"ad_name": f"SY|vara|page|video|{VP}", "date": "2026-10-10", "spend": 1.0, "orders": 0, "delivered": 0,
                      "collected": 0, "delivery_rate": None, "cost_per_delivered": None, "engagement": None}])
    assert crm.perf_rows()[0]["script_id"] == VP


# ───────── حملات العمليات ─────────
def test_oms_options_unavailable_without_config_or_endpoint(env, monkeypatch):
    monkeypatch.setattr(crm, "is_configured", lambda: False)
    o = placements.oms_options()
    assert o["available"] is False and "مش مربوطة" in o["reason"]
    monkeypatch.setattr(crm, "is_configured", lambda: True)

    class Boom:
        def get(self, *a, **k):
            raise crm.CRMError("404")
    monkeypatch.setattr(crm, "get_client", lambda: Boom())
    assert placements.oms_options()["available"] is False and "ما عندها نقطة" in placements.oms_options()["reason"]


def test_oms_options_are_normalised_trimmed_and_carry_no_secrets(env, monkeypatch):
    monkeypatch.setattr(crm, "is_configured", lambda: True)
    payload = {"accounts": [{"platform": "TIKTOK", "accountId": "7000", "accountName": "  حساب  تيك ", "currency": "usd",
                             "tokenEncrypted": "SECRET", "token": "SECRET2"}],
               "campaigns": [{"platform": "META", "name": "حملة", "externalId": "120", "code": "c1", "status": "active",
                              "accountId": "7000", "access_token": "SECRET3"}, "junk", 5]}

    class Ok:
        def get(self, *a, **k):
            return payload
    monkeypatch.setattr(crm, "get_client", lambda: Ok())
    o = placements.oms_options()
    assert o["available"] and o["accounts"] == [{"platform": "tiktok", "account_id": "7000", "account_name": "حساب تيك", "currency": "USD"}]
    assert o["campaigns"][0]["platform"] == "meta" and o["campaigns"][0]["campaign_id"] == "120" and o["campaigns"][0]["status"] == "ACTIVE"
    assert "SECRET" not in json.dumps(o) and len(o["campaigns"]) == 1


# ───────── المسارات ─────────
@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from web import routes_placements
    import timeline
    app = FastAPI()
    app.include_router(routes_placements.router)
    script = config.SCRIPTS_DIR / "s1.json"
    script.write_text(json.dumps({"_meta": {"script_id": VP}, "scenes": []}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(timeline, "load", lambda stem: {})
    monkeypatch.setattr(crm, "is_configured", lambda: False)
    return TestClient(app)


def test_routes_full_cycle_and_arabic_errors(client):
    r = client.get("/api/studio/s1.json/placements")
    d = r.json()
    assert r.status_code == 200 and d["vp_id"] == VP and d["entries"] == [] and "meta" in d["platforms"] and d["oms"]["available"] is False
    r = client.post("/api/studio/s1.json/placements", json=good())
    assert r.status_code == 200
    pid = r.json()["id"]
    assert client.post("/api/studio/s1.json/placements", json=good()).status_code == 400
    bad = client.post("/api/studio/s1.json/placements", json=good(platform="x"))
    assert bad.status_code == 400 and "المنصة" in bad.json()["detail"]
    assert client.put(f"/api/studio/s1.json/placements/{pid}", json={"status": "ended"}).json()["status"] == "ended"
    assert len(client.get("/api/studio/s1.json/placements").json()["entries"]) == 1
    assert client.delete(f"/api/studio/s1.json/placements/{pid}").status_code == 200
    assert client.delete(f"/api/studio/s1.json/placements/{pid}").status_code == 400
    assert client.get("/api/studio/none.json/placements").status_code == 404


# ───────── الواجهة ─────────
def test_ui_panel_escapes_text_confirms_delete_and_uses_latin_digits():
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "web/static/production.js").read_text(encoding="utf-8")
    block = js[js.index("تسجيل الإعلان بالحساب الإعلاني (ميتا/تيك توك/سناب"):]
    assert "drawPlacements(file)" in js and 'id="plPanel"' in js
    for must in ("${esc(x.ad_name)}", "${esc(x.ad_account_name || x.ad_account_id)}", "${esc(x.campaign_name)}", "${esc(c.campaign_name)}"):
        assert must in block, must
    assert "confirm(" in block
    assert 'rel="noopener noreferrer"' in block and "esc(x.ad_url)" in block
    assert not re.search(r"[٠-٩]", block)
