"""واجهة حسابات الموظفين: صفحة الدخول، شريحة المستخدم، تبويبات «الموظفين» و«النشاط»، ومعالجة انتهاء الجلسة."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOGIN = (STATIC / "login.html").read_text(encoding="utf-8")
LJS = (STATIC / "login.js").read_text(encoding="utf-8")
AJS = (STATIC / "accounts.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
BOOT = (STATIC / "boot.js").read_text(encoding="utf-8")
SET = (STATIC / "settings.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def mock(name):
    return json.loads((STATIC / "mock" / f"{name}.json").read_text(encoding="utf-8"))


def test_the_login_page_is_standalone_themed_and_versioned_like_the_app():
    assert 'id="loginBody"' in LOGIN and '<script src="/login.js?v=' in LOGIN and 'name="robots" content="noindex"' in LOGIN
    for f in ("zaki-ui.all.css", "theme.css", "style.css", "ornament.css"):
        assert f in LOGIN, f
    versions = set(re.findall(r"\?v=(\d+)", INDEX)) | set(re.findall(r"\?v=(\d+)", LOGIN))
    assert len(versions) == 1, versions                                                       # نفس الرقم بالصفحتين


def test_the_login_script_covers_setup_login_and_forced_password_change_without_globals():
    assert LJS.lstrip().startswith("/*") and "(function () {" in LJS and LJS.rstrip().endswith("})();")
    assert not re.search(r"^(?:const|let|var|function|async function)\s", LJS, re.M)               # كله جوّا دالة (بلا أسماء عامة)
    for needle in ("أنشئ أول حساب", "/api/auth/setup", "/api/auth/login", "/api/auth/password", "/api/auth/me", "me.needs_setup", "must_change",
                   "كلمتا السر مش متطابقتين", 'autocomplete="new-password"', 'autocomplete="current-password"', '"password"'):
        assert needle in LJS, needle
    assert "console." not in LJS and "localStorage.setItem" not in LJS and "sessionStorage" not in LJS     # ما بنخزّن كلمات السر ولا بنطبعها


def test_the_header_shows_who_is_logged_in_with_a_logout_button():
    assert re.search(r'<span class="who-chip" id="whoChip" hidden>.*?id="whoName".*?id="logoutBtn".*?خروج</button></span>', INDEX, re.S)
    assert "accWho();" in BOOT and "async function accWho()" in AJS
    assert '"/api/auth/logout", { method: "POST" }' in AJS and 'location.href = "/login.html"' in AJS


def test_settings_has_staff_and_activity_tabs_wired_to_their_loaders():
    seg = re.search(r'<div class="seg" id="setTabs".*?</div>', INDEX, re.S).group(0)
    assert 'data-tab="staff">الموظفين</button>' in seg and 'data-tab="activity">النشاط</button>' in seg
    assert 'id="set-staff" class="tabpane"' in INDEX and 'id="set-activity" class="tabpane"' in INDEX
    assert 'case "staff": accStaffLoad(); break;' in SET and 'case "activity": accActivityLoad(); break;' in SET
    assert re.search(r'<script src="/accounts\.js\?v=\d+"></script>', INDEX)


def test_the_staff_tab_has_the_required_actions_and_never_shows_a_password():
    for needle in ("ضيف موظف", "صفّر كلمة السر", "عطّل", "فعّل", "غيّر كلمة سرك", "بدّه كلمة سر جديدة", "seats_note", "بلا صلاحيات",
                   "python accounts.py reset", "كلمات السر مشفّرة وما حدا بيشوفها", "confirm(`تعطّل حساب"):
        assert needle in AJS, needle
    assert AJS.count('type="password"') >= 4 and "console." not in AJS and "localStorage" not in AJS
    assert "u.id === me" in AJS                                                                   # ما بتعطّل ولا بتصفّر حسابك بنفسك
    for url in ("/api/accounts", "/api/accounts/${enc(uid)}/reset", "/api/accounts/${enc(uid)}/active", "/api/auth/password", "/api/activity?"):
        assert url in AJS, url


def test_the_activity_tab_filters_by_employee_kind_and_local_day():
    for needle in ("كل الموظفين", "كل الأنواع", 'id="accfFrom"', 'id="accfTo"', "المزيد", "ما في نشاط بهالفلاتر", "T00:00:00`).toISOString()", "86400000", "e.kind_label"):
        assert needle in AJS, needle
    assert "fmtDate(e.at)" in AJS


def test_the_api_helper_sends_logged_out_users_to_the_login_page_but_not_mock_mode():
    assert "function authRedirect()" in APP and "if (MOCK || " in APP and 'location.href = "/login.html"' in APP
    assert 'r.status === 401 && j.code === "auth_required"' in APP and 'r.status === 403 && j.code === "must_change_password"' in APP


def test_mock_mode_has_the_account_pages_and_routes():
    assert 'path === "/api/auth/me") return mockFile("auth_me")' in APP and 'path === "/api/accounts") return mockFile("accounts")' in APP
    assert 'mockFile("activity")' in APP and re.search(r"accounts\(\\/\[\^/\]\+\\/\(active\|reset\)\)\?", APP)
    me, acc, act = mock("auth_me"), mock("accounts"), mock("activity")
    assert me["user"]["display_name"] and me["needs_setup"] is False
    assert [u["active"] for u in acc["users"]] == [True, True, False] and any(u["must_change"] for u in acc["users"]) and acc["me"] == 1
    assert act["total"] == len(act["items"]) >= 6 and set(act["kinds"]) >= {"create", "upload", "approve", "delete", "account"}
    assert {i["kind"] for i in act["items"]} <= set(act["kinds"]) and any(i["user_id"] == 0 for i in act["items"])
    assert not re.search(r"[٠-٩]", json.dumps([me, acc, act], ensure_ascii=False))


def test_the_styles_exist():
    for cls in (".who-chip", ".login-wrap", ".login-card", ".acc-tbl", ".acc-reset"):
        assert cls in CSS, cls
