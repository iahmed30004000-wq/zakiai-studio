"""تسجيل الدخول بفيسبوك وسحب الإعلانات: كله على خادم Graph مزيّف محلي — بلا إنترنت ولا تطبيق ميتا حقيقي."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import ads_meta  # noqa: E402
import config  # noqa: E402
import placements  # noqa: E402
import secrets_store  # noqa: E402
import settings_io  # noqa: E402

APP_ID, APP_SECRET = "123456789012345", "shh-app-secret-xyz"
SHORT, LONG = "short-token-111", "long-token-222"
VP = "VP-vara-3-v1"
FAKE_UA = "act_5550001"


class Graph:
    def __init__(self):
        self.requests = []             # (method, path, query, auth)
        self.scopes = ["ads_read", "public_profile"]
        self.debug_app = APP_ID
        self.expires_at = None         # None = بعد ساعة (قصير ← بيتطوّل)، 0 = ما بينتهي، رقم = وقت محدد
        self.granular = None
        self.exchange_fails = False
        self.fail = None               # (status, error dict) لكل ما عدا oauth
        self.ads = []
        self.insights = []
        self.accounts = [{"id": FAKE_UA, "account_id": "5550001", "name": "متجر صحة", "account_status": 1, "currency": "USD"},
                         {"id": "bad-id", "name": "x"}]
        self.base = ""
        self.next_page = False


def make_graph(g: Graph):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_DELETE(self):
            g.requests.append(("DELETE", self.path, {}, self.headers.get("Authorization")))
            self._send(200, {"success": True})

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            g.requests.append(("GET", u.path, q, self.headers.get("Authorization")))
            p = u.path.split("/", 2)[2] if u.path.count("/") >= 2 else u.path
            if g.fail and p != "oauth/access_token":
                return self._send(*g.fail)
            if p == "oauth/access_token":
                if q.get("grant_type") == "fb_exchange_token":
                    if g.exchange_fails:
                        return self._send(400, {"error": {"code": 100, "message": "x"}})
                    return self._send(200, {"access_token": LONG, "expires_in": 5_000_000})
                if q.get("code") == "good-code":
                    return self._send(200, {"access_token": SHORT})
                return self._send(400, {"error": {"code": 100, "message": "bad code"}})
            if p == "debug_token":
                import time as _t
                exp = int(_t.time()) + 3600 if g.expires_at is None else g.expires_at
                data = {"app_id": g.debug_app, "is_valid": True, "scopes": g.scopes, "expires_at": exp}
                if g.granular is not None:
                    data["granular_scopes"] = g.granular
                return self._send(200, {"data": data})
            if p == "me":
                return self._send(200, {"id": "999", "name": "أحمد"})
            if p == "me/adaccounts":
                return self._send(200, {"data": g.accounts})
            if p.endswith("/ads"):
                out = {"data": g.ads[:1] if g.next_page else g.ads}
                if g.next_page:
                    out["paging"] = {"next": f"{g.base}/v26.0/{FAKE_UA}/ads?after=2"}
                    g.next_page = False
                    g.ads = g.ads[1:]
                return self._send(200, out)
            if p.endswith("/insights"):
                return self._send(200, {"data": g.insights})
            self._send(404, {"error": {"code": 803, "message": "x"}})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def ad(i, name, status="ACTIVE"):
    return {"id": f"61000{i}", "name": name, "effective_status": status, "created_time": "2026-10-12T10:00:00+0000",
            "campaign": {"id": "1200", "name": "حملة اختبار"}, "adset": {"id": "1300", "name": "مجموعة"}}


@pytest.fixture
def meta(env, monkeypatch, tmp_path):
    mem, prev = secrets_store.use_memory_backend()
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    settings_io._cache["sig"] = None
    g = Graph()
    srv = make_graph(g)
    g.base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(ads_meta, "GRAPH_BASE", g.base)
    monkeypatch.setattr(ads_meta, "AUTH_BASE", "https://www.facebook.com")
    ads_meta._pending.clear()
    g.settings = config.SETTINGS_PATH
    yield g
    srv.shutdown()
    secrets_store.restore_backend(prev)
    settings_io._cache["sig"] = None


def connect(g):
    ads_meta.set_app(APP_ID, APP_SECRET)
    url = ads_meta.authorize_url()
    state = parse_qs(urlparse(url).query)["state"][0]
    return ads_meta.complete_login("good-code", state)


# ───────── الإعداد والأسرار ─────────
@pytest.mark.parametrize("a,s", [("abc", "x"), ("", "x"), ("123456789012345", ""), ("123456789012345", "a b"), ("12", "x")])
def test_bad_app_credentials_are_rejected(meta, a, s):
    with pytest.raises(ads_meta.MetaError):
        ads_meta.set_app(a, s)
    assert not ads_meta.configured()


def test_secret_and_token_never_hit_the_settings_file_or_status(meta):
    st = connect(meta)
    raw = meta.settings.read_text(encoding="utf-8")
    for secret in (APP_SECRET, LONG, SHORT):
        assert secret not in raw and secret not in json.dumps(st)
    assert st["connected"] and st["user_name"] == "أحمد" and st["app_id"] == APP_ID and 55 <= st["days_left"] <= 58
    assert secrets_store.get_secret("settings.ADS.META.app_secret") == APP_SECRET
    assert secrets_store.get_secret("settings.ADS.META.access_token") == LONG


def test_changing_the_app_forgets_the_old_login(meta):
    connect(meta)
    ads_meta.set_app("999999999999999", "another-secret")
    assert ads_meta.status()["connected"] is False


def test_redirect_uri_is_always_localhost_on_the_real_port_and_has_no_setter(meta, monkeypatch):
    monkeypatch.delenv("VP_PORT", raising=False)
    assert ads_meta.redirect_uri() == "http://localhost:8000/api/ads/meta/callback"
    monkeypatch.setenv("VP_PORT", "9100")
    assert ads_meta.redirect_uri() == "http://localhost:9100/api/ads/meta/callback"
    monkeypatch.setenv("VP_PORT", "evil.com/x")
    assert ads_meta.redirect_uri() == "http://localhost:8000/api/ads/meta/callback"       # ما بنقبل غير أرقام
    assert not hasattr(ads_meta, "set_redirect_base")                                    # النفق ملغى (بيفتح الاستوديو للإنترنت)


# ───────── حالة الدخول ─────────
def test_authorize_url_carries_only_ads_read_and_the_signed_state(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    u = urlparse(ads_meta.authorize_url())
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.netloc == "www.facebook.com" and u.path == "/v26.0/dialog/oauth"
    assert q["scope"] == "ads_read" and q["client_id"] == APP_ID and q["redirect_uri"].endswith("/api/ads/meta/callback")
    assert APP_SECRET not in u.query and "config_id" not in q


def test_config_id_replaces_scope_for_business_apps(meta):
    ads_meta.set_app(APP_ID, APP_SECRET, "7777000111")
    q = {k: v[0] for k, v in parse_qs(urlparse(ads_meta.authorize_url()).query).items()}
    assert q["config_id"] == "7777000111" and q["response_type"] == "code" and q["override_default_response_type"] == "true"
    assert "scope" not in q and ads_meta.status()["config_id"] == "7777000111"
    ads_meta.set_app(APP_ID, APP_SECRET)                    # None = ما نلمسه
    assert ads_meta.config_id() == "7777000111"
    ads_meta.set_app(APP_ID, APP_SECRET, "")                # فاضي = نمسحه
    assert ads_meta.config_id() == "" and "scope" in parse_qs(urlparse(ads_meta.authorize_url()).query)
    for bad in ("abc", "1" * 30, "12 3"):
        with pytest.raises(ads_meta.MetaError) as e:
            ads_meta.set_app(APP_ID, APP_SECRET, bad)
        assert e.value.code == "bad_config_id"


def test_authorize_needs_configuration(meta):
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.authorize_url()
    assert e.value.code == "not_configured"


def test_state_forgery_replay_expiry_and_foreign_state(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    s = ads_meta.make_state()
    nonce, t, sig = s.split(".")
    for bad in ("", "x", f"{nonce}.{t}.{'0' * 32}", f"{nonce}.{int(t) + 1}.{sig}", "a.b.c"):
        with pytest.raises(ads_meta.MetaError) as e:
            ads_meta.check_state(bad)
        assert e.value.code == "state_invalid"
    ads_meta.check_state(s)                                  # مرة وحدة تمشي
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.check_state(s)                              # وإعادة الاستخدام لا
    assert e.value.code == "state_unknown"
    old = ads_meta.make_state(now=1000)
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.check_state(old, now=1000 + ads_meta.STATE_TTL_SEC + 5)
    assert e.value.code == "state_expired"
    ads_meta._pending.clear()                                # state موقّع صح بس ما بدأ من هالجهاز (مثلاً بعد إعادة تشغيل)
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.check_state(ads_meta.make_state() if False else s)
    assert e.value.code in ("state_unknown", "state_invalid")


def test_callback_with_bad_state_never_reaches_meta(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    with pytest.raises(ads_meta.MetaError):
        ads_meta.complete_login("good-code", "forged.1.2")
    assert meta.requests == []


# ───────── تبديل الكود ─────────
def test_login_checks_the_token_then_lengthens_it_and_uses_header_not_url(meta):
    connect(meta)
    paths = [r[1].rsplit("/", 1)[-1] for r in meta.requests]
    assert paths[:4] == ["access_token", "debug_token", "access_token", "me"]
    assert meta.requests[2][2]["grant_type"] == "fb_exchange_token" and meta.requests[2][2]["fb_exchange_token"] == SHORT
    dbg = meta.requests[1]
    assert dbg[2]["input_token"] == SHORT and dbg[3] == f"Bearer {APP_ID}|{APP_SECRET}"
    me = meta.requests[3]
    assert me[3] == f"Bearer {LONG}" and LONG not in json.dumps(me[2])


def test_a_long_lived_token_is_not_exchanged_again(meta):
    import time
    meta.expires_at = int(time.time()) + 50 * 86400
    ads_meta.set_app(APP_ID, APP_SECRET)
    state = parse_qs(urlparse(ads_meta.authorize_url()).query)["state"][0]
    st = ads_meta.complete_login("good-code", state)
    assert [r[1].rsplit("/", 1)[-1] for r in meta.requests].count("access_token") == 1
    assert 49 <= st["days_left"] <= 50 and secrets_store.get_secret("settings.ADS.META.access_token") == SHORT


def test_exchange_failure_keeps_the_original_token_with_its_real_expiry(meta):
    meta.exchange_fails = True
    st = connect(meta)
    assert st["connected"] and st["days_left"] == 0 and st["expiring_soon"] is True        # ساعة وحدة باقية: بيتنبّه
    assert secrets_store.get_secret("settings.ADS.META.access_token") == SHORT


# ───────── لصق توكن (بديل) ─────────
GOOD_TOKEN = "EAAB" + "x" * 40


def test_pasting_a_never_expiring_system_user_token(meta):
    meta.expires_at = 0
    ads_meta.set_app(APP_ID, APP_SECRET)
    st = ads_meta.set_token(GOOD_TOKEN)
    assert st["connected"] and st["never_expires"] and st["days_left"] is None and st["expired"] is False and st["expiring_soon"] is False
    assert secrets_store.get_secret("settings.ADS.META.access_token") == GOOD_TOKEN
    assert GOOD_TOKEN not in meta.settings.read_text(encoding="utf-8") and GOOD_TOKEN not in json.dumps(st)
    assert [r[1].rsplit("/", 1)[-1] for r in meta.requests].count("access_token") == 0       # ما في تطويل لتوكن بلا انتهاء
    assert ads_meta.accounts()                                                                # وبيشتغل


def test_pasting_a_short_token_gets_lengthened(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    st = ads_meta.set_token(GOOD_TOKEN)
    assert 55 <= st["days_left"] <= 58 and secrets_store.get_secret("settings.ADS.META.access_token") == LONG


@pytest.mark.parametrize("tok", ["", "short", "has space " + "x" * 30, "app|secret" + "x" * 30, "x" * 700])
def test_pasted_garbage_never_reaches_meta(meta, tok):
    ads_meta.set_app(APP_ID, APP_SECRET)
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.set_token(tok)
    assert e.value.code == "bad_token" and meta.requests == []


def test_pasted_token_needs_the_app_first(meta):
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.set_token(GOOD_TOKEN)
    assert e.value.code == "not_configured"


def test_pasted_token_from_another_app_or_without_ads_read_is_refused(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    meta.debug_app = "555"
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.set_token(GOOD_TOKEN)
    assert e.value.code == "token_mismatch"
    meta.debug_app, meta.scopes = APP_ID, ["public_profile"]
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.set_token(GOOD_TOKEN)
    assert e.value.code == "no_scope" and not ads_meta.status()["connected"]


def test_granular_scopes_also_count_as_ads_read(meta):
    meta.scopes, meta.granular = [], [{"scope": "ads_read", "target_ids": ["5550001"]}]
    assert connect(meta)["connected"]


def test_token_from_another_app_is_refused_and_not_saved(meta):
    meta.debug_app = "555"
    with pytest.raises(ads_meta.MetaError) as e:
        connect(meta)
    assert e.value.code == "token_mismatch" and not ads_meta.status()["connected"]


def test_missing_ads_read_scope_is_refused(meta):
    meta.scopes = ["public_profile"]
    with pytest.raises(ads_meta.MetaError) as e:
        connect(meta)
    assert e.value.code == "no_scope" and not ads_meta.status()["connected"]


def test_bad_code_gives_clear_error(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    state = parse_qs(urlparse(ads_meta.authorize_url()).query)["state"][0]
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.complete_login("nope", state)
    assert e.value.code == "bad_request" and APP_SECRET not in str(e.value)


# ───────── الانتهاء ─────────
def test_expiry_warning_and_expired_token_asks_for_relogin(meta):
    connect(meta)
    ads_meta._write(lambda a: a.__setitem__("token_expires_at", "2000-01-01T00:00:00+00:00"))
    st = ads_meta.status()
    assert st["expired"] and not st["connected"]
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.accounts()
    assert e.value.code == "token_expired"
    from datetime import datetime, timedelta, timezone
    ads_meta._write(lambda a: a.__setitem__("token_expires_at", (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()))
    assert ads_meta.status()["expiring_soon"] is True


@pytest.mark.parametrize("status,err,code", [
    (401, {"code": 190, "message": "expired token EAAB-LEAK"}, "token_expired"),
    (403, {"code": 200, "message": "x"}, "permission"),
    (400, {"code": 17, "message": "x"}, "rate_limit"),
    (400, {"code": 100, "message": "x"}, "bad_request"),
    (500, {"code": 1, "message": "x"}, "meta_down"),
])
def test_graph_errors_are_mapped_to_arabic_without_leaking_meta_text(meta, status, err, code):
    connect(meta)
    meta.fail = (status, {"error": err})
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.accounts()
    assert e.value.code == code and "LEAK" not in str(e.value) and any("؀" <= c <= "ۿ" for c in str(e.value))


def test_needs_connection_first(meta):
    ads_meta.set_app(APP_ID, APP_SECRET)
    with pytest.raises(ads_meta.MetaError) as e:
        ads_meta.accounts()
    assert e.value.code == "not_connected"


# ───────── الحسابات والإعلانات ─────────
def test_accounts_are_normalised_and_junk_dropped(meta):
    connect(meta)
    acc = ads_meta.accounts()
    assert acc == [{"id": FAKE_UA, "account_id": "5550001", "name": "متجر صحة", "currency": "USD", "status_code": 1, "status": "شغّال"}]


def test_ads_pagination_spend_and_bad_account_id(meta):
    connect(meta)
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}"), ad(2, "اعلان تاني")]
    meta.insights = [{"ad_id": "610001", "spend": "12.345"}, {"ad_id": "610002", "spend": "abc"}]
    meta.next_page = True
    rows = ads_meta.ads(FAKE_UA)
    assert [r["ad_id"] for r in rows] == ["610001", "610002"] and rows[0]["spend"] == 12.35 and rows[1]["spend"] is None
    assert rows[0]["campaign_name"] == "حملة اختبار" and rows[0]["created"] == "2026-10-12"
    for bad in ("123", "act_", "act_1; DROP", "../me"):
        with pytest.raises(ads_meta.MetaError):
            ads_meta.ads(bad)


def test_pagination_never_follows_a_foreign_next_link(meta, monkeypatch):
    connect(meta)
    meta.ads = [ad(1, "a")]
    orig = ads_meta._graph

    def evil(*a, **k):
        d = orig(*a, **k)
        d["paging"] = {"next": "https://evil.example/steal"}
        return d
    monkeypatch.setattr(ads_meta, "_graph", evil)
    assert len(ads_meta.ads(FAKE_UA)) == 1


# ───────── المزامنة ─────────
def test_sync_registers_only_matched_ads_and_never_guesses(meta):
    connect(meta)
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}"), ad(2, "اعلان غريب بلا VP"), ad(3, "SY|vara|page|video|VP-vara-3-v1", "PAUSED")]
    r = ads_meta.sync(FAKE_UA)
    assert r == {"added": 2, "updated": 0, "unmatched": 1, "skipped": 0}
    es = {e["ad_id"]: e for e in placements.list_for(VP)}
    assert es["610001"]["source"] == "facebook" and es["610001"]["platform"] == "meta" and es["610001"]["status"] == "published"
    assert es["610003"]["status"] == "paused" and es["610001"]["ad_account_id"] == FAKE_UA and es["610001"]["ad_account_name"] == "متجر صحة"
    assert es["610001"]["ad_url"].startswith("https://adsmanager.facebook.com/") and es["610001"]["published_at"] == "2026-10-12"


def test_sync_twice_updates_without_duplicates_and_keeps_notes(meta):
    connect(meta)
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}")]
    ads_meta.sync(FAKE_UA)
    e = placements.list_for(VP)[0]
    placements.update(VP, e["id"], {"notes": "ملاحظتي"})
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}", "ARCHIVED")]
    r = ads_meta.sync(FAKE_UA)
    es = placements.list_for(VP)
    assert r["added"] == 0 and r["updated"] == 1 and len(es) == 1 and es[0]["status"] == "ended" and es[0]["notes"] == "ملاحظتي"


def test_sync_uses_a_previous_manual_registration_for_names_without_vp(meta):
    connect(meta)
    placements.add(VP, {"platform": "meta", "ad_account_name": "x", "ad_name": "اعلان بلا خانة خامسة"})
    meta.ads = [ad(7, "اعلان بلا خانة خامسة")]
    r = ads_meta.sync(FAKE_UA)
    assert r["added"] == 1 and r["unmatched"] == 0


def test_sync_skips_ads_with_pii_in_names_instead_of_failing(meta):
    connect(meta)
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}"), {**ad(2, f"SY|vara|page|video|{VP}x"), "campaign": {"id": "1", "name": "اتصل 963944123456"}}]
    meta.ads[1]["name"] = f"SY|vara|page|video|{VP}"
    meta.ads[1]["id"] = "610002"
    r = ads_meta.sync(FAKE_UA)
    assert r["added"] == 1 and r["skipped"] == 1


def test_preview_flags_matches_without_writing(meta):
    connect(meta)
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}"), ad(2, "x")]
    p = ads_meta.preview(FAKE_UA)
    assert p["matched"] == 1 and p["total"] == 2 and p["ads"][0]["script_id"] == VP
    assert placements.list_for(VP) == []


# ───────── فصل الدخول ─────────
def test_disconnect_revokes_and_clears_token_but_keeps_app(meta):
    connect(meta)
    ads_meta.disconnect()
    assert ("DELETE", "/v26.0/me/permissions") in [(r[0], r[1]) for r in meta.requests]
    st = ads_meta.status()
    assert not st["connected"] and st["configured"] and secrets_store.get_secret("settings.ADS.META.access_token") in (None, "")


def test_clear_app_removes_everything(meta):
    connect(meta)
    ads_meta.clear_app()
    assert not ads_meta.configured() and not ads_meta.status()["connected"]


# ───────── المسارات ─────────
@pytest.fixture
def client(meta):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_ads
    app = FastAPI()
    app.include_router(routes_ads.router)
    return TestClient(app)


def test_routes_login_flow_redirects_with_short_codes_only(meta, client):
    assert client.put("/api/ads/meta/app", json={"app_id": APP_ID, "app_secret": APP_SECRET}).status_code == 200
    url = client.get("/api/ads/meta/start").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    r = client.get("/api/ads/meta/callback", params={"code": "good-code", "state": state}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#/factory/api/keys?meta=connected"
    assert client.get("/api/ads/meta/status").json()["connected"] is True
    r = client.get("/api/ads/meta/callback", params={"code": "good-code", "state": state}, follow_redirects=False)   # إعادة استخدام
    assert r.headers["location"] == "/#/factory/api/keys?meta=error_state_unknown"
    r = client.get("/api/ads/meta/callback", params={"error": "access_denied", "error_description": "x"}, follow_redirects=False)
    assert r.headers["location"] == "/#/factory/api/keys?meta=denied"


def test_route_token_paste_never_echoes_the_token(meta, client):
    meta.expires_at = 0
    client.put("/api/ads/meta/app", json={"app_id": APP_ID, "app_secret": APP_SECRET, "config_id": "123"})
    r = client.put("/api/ads/meta/token", json={"token": GOOD_TOKEN})
    assert r.status_code == 200 and r.json()["never_expires"] and GOOD_TOKEN not in r.text and r.json()["config_id"] == "123"
    assert client.put("/api/ads/meta/token", json={"token": "bad"}).status_code == 400
    assert client.put("/api/ads/meta/redirect-base", json={"redirect_base": "https://x.com"}).status_code in (404, 405)


def test_routes_never_return_secrets_and_report_arabic_errors(meta, client):
    client.put("/api/ads/meta/app", json={"app_id": APP_ID, "app_secret": APP_SECRET})
    body = client.get("/api/ads/meta/status").text
    assert APP_SECRET not in body and "access_token" not in body
    r = client.get("/api/ads/meta/accounts")
    assert r.status_code == 409 and "ما سجّلت دخول" in r.json()["detail"]
    r = client.put("/api/ads/meta/app", json={"app_id": "abc", "app_secret": "x"})
    assert r.status_code == 400 and "App ID" in r.json()["detail"]


def test_routes_accounts_ads_sync_disconnect(meta, client):
    connect(meta)
    meta.ads = [ad(1, f"SY|vara|page|video|{VP}")]
    assert client.get("/api/ads/meta/accounts").json()["accounts"][0]["id"] == FAKE_UA
    assert client.get("/api/ads/meta/ads", params={"account": FAKE_UA}).json()["matched"] == 1
    assert client.post("/api/ads/meta/sync", json={"account": FAKE_UA, "days": "x"}).json()["added"] == 1
    assert client.post("/api/ads/meta/sync", json={"account": "bad"}).status_code == 400
    assert client.delete("/api/ads/meta/connection").json()["connected"] is False


def test_routes_are_local_only(meta, client):
    from fastapi.testclient import TestClient
    remote = TestClient(client.app, client=("8.8.8.8", 5000))
    assert remote.put("/api/ads/meta/token", json={"token": GOOD_TOKEN}).status_code == 403
    for m, p in (("get", "/api/ads/meta/status"), ("get", "/api/ads/meta/start"), ("get", "/api/ads/meta/accounts"),
                 ("get", "/api/ads/meta/callback"), ("delete", "/api/ads/meta/connection")):
        assert getattr(remote, m)(p).status_code == 403, p
    assert remote.put("/api/ads/meta/app", json={"app_id": APP_ID, "app_secret": "x"}).status_code == 403


# ───────── الواجهة ─────────
def test_ui_panel_is_escaped_closed_scope_confirms_and_has_no_secret_handling():
    import re
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "web" / "static"
    js = (static / "adsfb.js").read_text(encoding="utf-8")
    for must in ("${esc(st.redirect_uri)}", "${esc(x.ad_name)}", "${esc(x.name || x.id)}", "esc(st.user_name)", "${esc(x.script_id)}"):
        assert must in js, must
    assert js.count("confirm(") >= 2 and "innerHTML" in js
    assert not re.search(r"[٠-٩]", js)
    assert 'type="password"' in js and "localStorage" not in js and "sessionStorage" not in js
    assert "ngrok" in js and "fbSaveBase" not in js and "redirect-base" not in js        # ذكر النفق بس للتحذير منه
    assert 'id="fbConfig"' in js and 'id="fbToken"' in js and "/api/ads/meta/token" in js
    assert r"meta=([\w]+)" in js                                       # الرجوع بيقبل رمز قصير بس
    idx = (static / "index.html").read_text(encoding="utf-8")
    assert 'id="fbPanel"' in idx and "/adsfb.js" in idx
    assert "adsFbLoad" in (static / "settings.js").read_text(encoding="utf-8")
    prod = (static / "production.js").read_text(encoding="utf-8")
    assert "adsFbPullAll" in prod and 'id="plFb"' in prod
    import test_ui_globals
    assert test_ui_globals.is_closed_scope(js)
    assert (static / "mock" / "ads_meta.json").exists()
