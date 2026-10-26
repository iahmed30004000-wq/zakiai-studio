"""حارس الدخول (web/auth_gate.py) + مسارات الدخول والموظفين والنشاط (web/routes_auth.py) — على تطبيق صغير بنفس الطبقات."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import accounts  # noqa: E402
import activity  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
PW = "pass-word-123"
GOOD_TOKEN = "ext-token-good"


@pytest.fixture
def app(env, monkeypatch):
    from fastapi import FastAPI, WebSocket
    from fastapi.staticfiles import StaticFiles
    from web import auth_gate, routes_auth, routes_presets
    import ext_bridge
    monkeypatch.setattr(auth_gate, "ACTIVE", True)
    monkeypatch.setattr(ext_bridge, "verify", lambda t: t == GOOD_TOKEN)
    monkeypatch.delenv("VP_ALLOW_REMOTE_SETUP", raising=False)
    accounts._fails.clear()
    a = FastAPI()
    a.add_middleware(auth_gate.AuthGate)
    a.include_router(routes_auth.router)
    a.include_router(routes_presets.router)

    @a.get("/api/whoami")
    def whoami():
        return {"who": accounts.who("nobody")}

    @a.get("/api/async-whoami")
    async def async_whoami():
        return {"who": accounts.who("nobody")}

    @a.get("/api/scripts")
    def scripts():
        return {"who": accounts.who("nobody")}

    @a.get("/api/studio/{f}/ext/queue")
    def ext_queue(f: str):
        return {"who": accounts.who("nobody")}

    @a.post("/api/studio/{f}/ext/result")
    def ext_result(f: str):
        return {"ok": True}

    @a.post("/api/studio/{f}/ext/log")
    def ext_log(f: str):
        return {"ok": True}

    @a.get("/api/ext/download")
    def ext_download():
        return {"zip": True}

    @a.get("/api/ads/meta/callback")
    def fb_callback():
        return {"callback": True}

    @a.post("/api/boom")
    def boom():
        from fastapi import HTTPException
        raise HTTPException(409, "x")

    @a.websocket("/api/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("hi")
        await socket.close()

    a.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
    return a


def client(app, **kw):
    from fastapi.testclient import TestClient
    return TestClient(app, **kw)


def owner_client(app):
    c = client(app)
    r = c.post("/api/auth/setup", json={"display_name": "سارة", "username": "sara", "password": PW})
    assert r.status_code == 200, r.text
    return c


def login(app, username, password=PW):
    c = client(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    return c, r


def add_employee(c, user="omar", name="عمر", pw="temp-pass-123"):
    r = c.post("/api/accounts", json={"display_name": name, "username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["user"]


# ───────────────────────── مين محمي ومين عام ─────────────────────────
def test_the_public_paths_work_without_a_session(app):
    c = client(app)
    me = c.get("/api/auth/me").json()
    assert me == {"user": None, "needs_setup": True, "seats_note": ""}
    assert c.get("/api/ext/download").json() == {"zip": True} and c.get("/api/ads/meta/callback").json() == {"callback": True}
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/login.html").status_code == 200 and c.get("/app.js").status_code == 200 and c.get("/theme.css").status_code == 200


def test_every_other_api_path_needs_a_login_with_a_clear_arabic_error(app):
    c = client(app)
    for method, url in (("get", "/api/presets"), ("get", "/api/whoami"), ("post", "/api/presets"), ("get", "/api/accounts"), ("get", "/api/activity"),
                        ("post", "/api/auth/password"), ("put", "/api/accounts/1/active"), ("get", "/api/ext/other")):
        r = getattr(c, method)(url) if method == "get" else getattr(c, method)(url, json={})
        assert r.status_code == 401 and r.json() == {"detail": "لازم تسجّل دخولك", "code": "auth_required"}, (method, url, r.status_code)
    assert "charset=utf-8" in c.get("/api/presets").headers["content-type"]


def test_the_app_page_redirects_to_login_but_mock_mode_and_assets_stay_open(app):
    c = client(app)
    for url in ("/", "/index.html"):
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login.html" and r.headers["cache-control"] == "no-store"
    assert c.get("/?mock=1", follow_redirects=False).status_code == 200
    assert c.get("/?mock=2", follow_redirects=False).status_code == 303
    assert c.get("/mock/presets.json").status_code == 200
    owner_client_ = owner_client(app)
    assert owner_client_.get("/", follow_redirects=False).status_code == 200


def test_websockets_need_a_session_too(app):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with client(app).websocket_connect("/api/ws"):
            pass
    assert e.value.code == 1008
    c = owner_client(app)
    with c.websocket_connect("/api/ws") as ws:
        assert ws.receive_text() == "hi"


# ───────────────────────── الحساب الأول والدخول ─────────────────────────
def test_the_first_account_is_created_from_this_machine_only_and_only_once(app, monkeypatch):
    far = client(app, client=("10.0.0.7", 5000))
    r = far.post("/api/auth/setup", json={"display_name": "س", "username": "sara", "password": PW})
    assert r.status_code == 403 and "نفس الجهاز" in r.json()["detail"] and accounts.needs_setup()
    monkeypatch.setenv("VP_ALLOW_REMOTE_SETUP", "1")
    assert far.post("/api/auth/setup", json={"display_name": "سارة", "username": "sara", "password": PW}).status_code == 200
    monkeypatch.delenv("VP_ALLOW_REMOTE_SETUP")
    again = client(app).post("/api/auth/setup", json={"display_name": "ثاني", "username": "second", "password": PW})
    assert again.status_code == 409 and "انعمل أصلاً" in again.json()["detail"]


def test_setup_validates_and_sets_a_safe_cookie(app):
    c = client(app)
    bad = c.post("/api/auth/setup", json={"display_name": "سارة", "username": "ab", "password": PW})
    assert bad.status_code == 400 and "اسم المستخدم" in bad.json()["detail"] and accounts.needs_setup()
    ok = c.post("/api/auth/setup", json={"display_name": "سارة", "username": "sara", "password": PW})
    cookie = ok.headers["set-cookie"]
    assert ok.json()["user"]["username"] == "sara" and "password" not in ok.text and "pw_hash" not in ok.text
    assert cookie.startswith("vp_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie and "Max-Age=2592000" in cookie
    assert "Secure" not in cookie
    me = c.get("/api/auth/me").json()
    assert me["user"]["display_name"] == "سارة" and me["needs_setup"] is False


def test_the_cookie_is_secure_over_https(app):
    c = client(app, base_url="https://testserver")
    r = c.post("/api/auth/setup", json={"display_name": "سارة", "username": "sara", "password": PW})
    assert "Secure" in r.headers["set-cookie"]


def test_login_logout_and_the_session_dies_with_the_cookie(app):
    owner_client(app)
    c, r = login(app, "SARA")
    assert r.status_code == 200 and c.get("/api/whoami").json() == {"who": "سارة"}
    token = c.cookies.get("vp_session")
    out = c.post("/api/auth/logout")
    sc = out.headers["set-cookie"]
    assert out.status_code == 200 and ('vp_session="";' in sc or "vp_session=;" in sc)
    assert accounts.session_user(token) is None
    assert c.get("/api/whoami").status_code == 401


def test_wrong_credentials_and_the_attempt_lock(app):
    owner_client(app)
    c, r = login(app, "sara", "wrong-wrong-1")
    assert r.status_code == 401 and r.json()["detail"] == "الاسم أو كلمة السر غلط" and "set-cookie" not in r.headers
    assert login(app, "ghost")[1].json()["detail"] == "الاسم أو كلمة السر غلط"
    for _ in range(accounts.LOGIN_FAILS):
        login(app, "sara", "wrong-wrong-1")
    locked = login(app, "sara")[1]
    assert locked.status_code == 429 and "دقيقة" in locked.json()["detail"]


def test_each_login_gets_its_own_session_and_a_bad_cookie_is_just_logged_out(app):
    owner_client(app)
    a, _ = login(app, "sara")
    b, _ = login(app, "sara")
    assert a.cookies.get("vp_session") != b.cookies.get("vp_session")
    from fastapi.testclient import TestClient
    bad = TestClient(app, cookies={"vp_session": "garbage"})
    assert bad.get("/api/whoami").status_code == 401


# ───────────────────────── الموظفين: كلمة مؤقتة وتعطيل وتصفير ─────────────────────────
def test_a_new_employee_is_locked_to_the_password_change_until_they_change_it(app):
    boss = owner_client(app)
    u = add_employee(boss)
    assert u["must_change"] is True and u["username"] == "omar"
    c, r = login(app, "omar", "temp-pass-123")
    assert r.status_code == 200 and r.json()["user"]["must_change"] is True
    blocked = c.get("/api/whoami")
    assert blocked.status_code == 403 and blocked.json() == {"detail": "لازم تغيّر كلمة السر أول شي", "code": "must_change_password"}
    assert c.get("/api/auth/me").json()["user"]["must_change"] is True                  # مسموحة
    assert c.post("/api/auth/password", json={"old": "temp-pass-123", "new": "short"}).status_code == 400
    assert c.post("/api/auth/password", json={"old": "wrong-wrong-1", "new": "my-new-secret-1"}).status_code == 403
    ok = c.post("/api/auth/password", json={"old": "temp-pass-123", "new": "my-new-secret-1"})
    assert ok.status_code == 200 and ok.json()["user"]["must_change"] is False
    assert c.get("/api/whoami").json() == {"who": "عمر"}


def test_the_employee_list_never_exposes_secrets_and_anyone_can_manage_it(app):
    boss = owner_client(app)
    add_employee(boss)
    c, _ = login(app, "omar", "temp-pass-123")
    c.post("/api/auth/password", json={"old": "temp-pass-123", "new": "my-new-secret-1"})
    d = c.get("/api/accounts").json()                       # بلا صلاحيات: عمر بيشوف ويدير كلشي
    assert [u["username"] for u in d["users"]] == ["sara", "omar"] and d["me"] == 2 and d["free_seats"] == 3
    assert "pw_hash" not in str(d) and "argon2" not in str(d) and PW not in str(d)
    third = c.post("/api/accounts", json={"display_name": "لينا", "username": "lina", "password": "temp-pass-123"})
    assert third.status_code == 200 and third.json()["user"]["created_by"] == "عمر"


def test_account_rules_come_back_as_arabic_errors(app):
    boss = owner_client(app)
    emp = add_employee(boss)
    assert boss.post("/api/accounts", json={"display_name": "عمر", "username": "OMAR", "password": "temp-pass-123"}).status_code == 409
    assert boss.post("/api/accounts", json={"display_name": "x", "username": "bad name", "password": "temp-pass-123"}).status_code == 400
    r = boss.put("/api/accounts/1/active", json={"active": False})
    assert r.status_code == 409 and "بنفسك" in r.json()["detail"]
    r = boss.post("/api/accounts/1/reset", json={"password": "temp-pass-123"})
    assert r.status_code == 409 and "بنفسك" in r.json()["detail"]
    assert boss.put("/api/accounts/99/active", json={"active": False}).status_code == 404
    assert boss.post(f"/api/accounts/{emp['id']}/reset", json={"password": "short"}).status_code == 400


def test_disabling_an_employee_cuts_their_live_session_at_once(app):
    boss = owner_client(app)
    emp = add_employee(boss)
    c, _ = login(app, "omar", "temp-pass-123")
    c.post("/api/auth/password", json={"old": "temp-pass-123", "new": "my-new-secret-1"})
    assert c.get("/api/whoami").status_code == 200
    assert boss.put(f"/api/accounts/{emp['id']}/active", json={"active": False}).json()["user"]["active"] is False
    assert c.get("/api/whoami").status_code == 401
    r = login(app, "omar", "my-new-secret-1")[1]
    assert r.status_code == 403 and "معطّل" in r.json()["detail"]
    assert boss.put(f"/api/accounts/{emp['id']}/active", json={"active": True}).json()["user"]["active"] is True


def test_resetting_a_password_logs_the_employee_out_and_forces_a_new_one(app):
    boss = owner_client(app)
    emp = add_employee(boss)
    c, _ = login(app, "omar", "temp-pass-123")
    c.post("/api/auth/password", json={"old": "temp-pass-123", "new": "my-new-secret-1"})
    r = boss.post(f"/api/accounts/{emp['id']}/reset", json={"password": "another-temp-1"})
    assert r.status_code == 200 and r.json()["user"]["must_change"] is True
    assert c.get("/api/whoami").status_code == 401
    assert login(app, "omar", "my-new-secret-1")[1].status_code == 401
    c2, r2 = login(app, "omar", "another-temp-1")
    assert r2.json()["user"]["must_change"] is True and c2.get("/api/whoami").status_code == 403


def test_the_seat_reminder_appears_with_the_fourth_account(app):
    boss = owner_client(app)
    for i in range(2):
        assert add_employee(boss, f"emp{i}", f"موظف {i}") and boss.get("/api/accounts").json()["seats_note"] == ""
    r = boss.post("/api/accounts", json={"display_name": "الرابع", "username": "fourth", "password": "temp-pass-123"})
    assert "Remotion" in r.json()["seats_note"] and "Remotion" in boss.get("/api/accounts").json()["seats_note"]
    assert "Remotion" in boss.get("/api/auth/me").json()["seats_note"]


# ───────────────────────── الإضافة ─────────────────────────
def test_the_extension_token_opens_only_the_extension_paths_and_acts_as_the_extension(app):
    c = client(app)
    h = {"X-VP-Ext-Token": GOOD_TOKEN}
    assert c.get("/api/studio/s1.json/ext/queue", headers=h).json() == {"who": "الإضافة"}
    assert c.get("/api/scripts", headers=h).json() == {"who": "الإضافة"}
    assert c.post("/api/studio/s1.json/ext/result", headers=h).status_code == 200
    for url in ("/api/whoami", "/api/presets", "/api/accounts", "/api/activity"):
        assert c.get(url, headers=h).status_code == 401, url                      # التوكن لوحده ما بيفتح باقي الاستوديو
    assert c.post("/api/presets", json={}, headers=h).status_code == 401
    assert c.get("/api/scripts", headers={"X-VP-Ext-Token": "wrong"}).status_code == 401
    assert c.get("/api/studio/s1.json/ext/queue").status_code == 401
    assert c.post("/api/scripts", headers=h).status_code in (401, 405)             # التوكن لقراءة القائمة بس


def test_a_failing_token_check_is_a_plain_401_not_a_crash(app, monkeypatch):
    import ext_bridge

    def boom(t):
        raise RuntimeError("secret store down")

    monkeypatch.setattr(ext_bridge, "verify", boom)
    assert client(app).get("/api/scripts", headers={"X-VP-Ext-Token": GOOD_TOKEN}).status_code == 401


# ───────────────────────── مين عم يشتغل داخل المسارات ─────────────────────────
def test_the_current_employee_reaches_sync_and_async_routes(app):
    boss = owner_client(app)
    assert boss.get("/api/whoami").json() == {"who": "سارة"} and boss.get("/api/async-whoami").json() == {"who": "سارة"}
    assert accounts.actor() is None                                            # وما بيتسرّب خارج الطلب


# ───────────────────────── النشاط ─────────────────────────
def test_successful_writes_are_logged_with_the_employee_and_a_plain_arabic_sentence(app):
    boss = owner_client(app)
    activity_before = activity.list_events()["total"]
    ok = boss.post("/api/presets", json={"name_ar": "حركتي", "category": "camera", "recipes": {"default": "A slow push toward the product"}})
    assert ok.status_code == 200
    items = activity.list_events()["items"]
    e = items[0]
    assert e["user_name"] == "سارة" and e["kind"] == "create" and e["label"] == "إضافة حركة سينمائية جديدة" and e["kind_label"] == "إضافة"
    assert activity.list_events()["total"] == activity_before + 1


def test_failed_reads_and_silent_requests_are_not_logged(app):
    boss = owner_client(app)
    n = activity.list_events()["total"]
    boss.get("/api/presets")
    assert boss.post("/api/presets", json={"name_ar": "ا"}).status_code == 400
    assert boss.post("/api/boom").status_code == 409
    boss.post("/api/studio/s1.json/ext/log")
    assert activity.list_events()["total"] == n


def test_the_extension_is_logged_as_the_extension(app):
    owner_client(app)
    client(app).post("/api/studio/s1.json/ext/result", headers={"X-VP-Ext-Token": GOOD_TOKEN})
    e = activity.list_events()["items"][0]
    assert e["user_name"] == "الإضافة" and e["user_id"] == 0 and e["kind"] == "upload" and "تسليم نتيجة من الإضافة (s1)" in e["label"]


def test_account_actions_are_logged_by_name(app):
    boss = owner_client(app)
    emp = add_employee(boss)
    boss.put(f"/api/accounts/{emp['id']}/active", json={"active": False})
    boss.post(f"/api/accounts/{emp['id']}/reset", json={"password": "another-temp-1"})
    login(app, "sara")
    labels = [x["label"] for x in activity.list_events()["items"]]
    assert "أنشأ الحساب الأول (صاحب الاستوديو)" in labels
    assert "أضاف الموظف «عمر» (omar)" in labels and "عطّل حساب «عمر»" in labels and "صفّر كلمة سر «عمر» (بيغيّرها بأول دخول)" in labels
    assert labels[0] == "سجّل دخوله"


def test_changing_your_password_is_logged_through_the_gate(app):
    boss = owner_client(app)
    boss.post("/api/auth/password", json={"old": PW, "new": "my-new-secret-1"})
    assert activity.list_events()["items"][0]["label"] == "غيّر كلمة سره" and activity.list_events()["items"][0]["kind"] == "account"


def test_the_activity_route_filters_pages_and_validates(app):
    boss = owner_client(app)
    emp = add_employee(boss)
    c2, _ = login(app, "omar", "temp-pass-123")
    c2.post("/api/auth/password", json={"old": "temp-pass-123", "new": "my-new-secret-1"})
    c2.post("/api/presets", json={"name_ar": "حركة عمر", "category": "camera", "recipes": {"default": "A slow push toward the product"}})
    d = boss.get("/api/activity").json()
    assert d["total"] >= 5 and d["kinds"]["upload"] == "رفع" and {"id": 0, "name": "الإضافة"} in d["users"]
    assert {"id": emp["id"], "name": "عمر"} in d["users"]
    mine = boss.get("/api/activity", params={"user": emp["id"]}).json()
    assert mine["total"] >= 2 and {x["user_name"] for x in mine["items"]} == {"عمر"}
    assert [x["kind"] for x in boss.get("/api/activity", params={"kind": "create"}).json()["items"]] == ["create"] * boss.get("/api/activity", params={"kind": "create"}).json()["total"]
    assert boss.get("/api/activity", params={"kind": "nope"}).status_code == 400
    page = boss.get("/api/activity", params={"limit": 2, "offset": 1}).json()
    assert len(page["items"]) == 2 and page["total"] == d["total"] and page["items"][0]["id"] == d["items"][1]["id"]
    assert boss.get("/api/activity", params={"since": "2999-01-01T00:00:00+00:00"}).json()["total"] == 0
    assert boss.get("/api/activity", params={"until": "2000-01-01T00:00:00+00:00"}).json()["items"] == []


def test_the_gate_can_be_switched_off(app, monkeypatch):
    from web import auth_gate
    monkeypatch.setattr(auth_gate, "ACTIVE", False)
    assert client(app).get("/api/presets").status_code == 200
    assert client(app).get("/", follow_redirects=False).status_code == 200


def test_fastapi_docs_need_a_login_too(app):
    """/openapi.json و/docs و/redoc بيكشفوا قائمة كل المسارات: بدهم جلسة متل باقي الـ API."""
    c = client(app)
    for url in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 401 and r.json()["code"] == "auth_required", (url, r.status_code)
    o = owner_client(app)
    assert o.get("/openapi.json").status_code == 200 and o.get("/docs").status_code == 200


def test_odd_looking_paths_never_reach_a_protected_route_without_a_session(app):
    c = client(app)
    for url in ("//api/whoami", "/api//whoami", "/api/whoami/", "/API/whoami", "/%61pi/whoami", "/api/%2e%2e/api/whoami", "/x/../api/whoami",
                "/api/auth/me/../whoami", "/api/auth/me%2f..%2fwhoami", "/api/auth/mee", "/api/ext/download/../whoami"):
        r = c.get(url, follow_redirects=False)
        assert not (r.status_code == 200 and "who" in r.text), (url, r.status_code, r.text[:80])


def test_privacy_page_is_public_for_google_consent(app):
    """جوجل بيطلب رابط «سياسة خصوصية» عام لنشر تطبيق درايف: لازم ينفتح بلا جلسة."""
    r = client(app).get("/privacy.html")
    assert r.status_code == 200 and "drive.file" in r.text and "Privacy Policy" in r.text and "سياسة الخصوصية" in r.text
