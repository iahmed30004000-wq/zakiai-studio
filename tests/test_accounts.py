"""حسابات الموظفين (accounts.py): إنشاء، تشفير، دخول، قفل المحاولات، جلسات، قواعد الأمان، مين عم يشتغل، وسطر الأوامر."""

import os
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import accounts as ac  # noqa: E402

PW = "pass-word-123"


@pytest.fixture(autouse=True)
def clean(env, monkeypatch):
    ac._fails.clear()
    ac._last_slide.clear()
    monkeypatch.delenv("VP_ACTOR", raising=False)
    yield
    ac.ACTOR.set(None)


def owner(name="سارة", user="sara"):
    return ac.create_first(name, user, PW)


def staff(user="omar", name="عمر", pw=PW):
    return ac.add_user(name, user, pw, by="سارة")


def err(fn, *a, **k):
    with pytest.raises(ac.AccountError) as e:
        fn(*a, **k)
    return e.value


# ───────────────────────── الإنشاء والتحقق ─────────────────────────
def test_the_first_account_is_created_once_and_nobody_else_can_use_the_setup_path():
    assert ac.needs_setup() is True and ac.count_users() == 0
    u = owner()
    assert u["username"] == "sara" and u["display_name"] == "سارة" and u["active"] and not u["must_change"] and u["created_by"] == "setup"
    assert ac.needs_setup() is False
    e = err(ac.create_first, "ثاني", "second", PW)
    assert e.code == "setup_done" and e.status == 409 and "انعمل أصلاً" in str(e)


@pytest.mark.parametrize("user", ["ab", "A", "has space", "اسم", "-abc", "a" * 33, "ab!", "", None])
def test_usernames_are_strict(user):
    e = err(ac.create_first, "سارة", user, PW)
    assert e.code == "bad_input" and "اسم المستخدم" in str(e)


def test_usernames_are_lowercased_and_accept_dots_dashes_and_underscores():
    assert owner(user="Sara.Ahmad-1_x")["username"] == "sara.ahmad-1_x"


@pytest.mark.parametrize("name", ["", "ا", "x" * 41, None])
def test_display_names_have_a_length(name):
    assert "الاسم الظاهر" in str(err(ac.create_first, name, "sara", PW))


def test_display_names_are_normalised():
    assert ac.create_first("  سارة    أحمد ", "sara", PW)["display_name"] == "سارة أحمد"


@pytest.mark.parametrize("pw,msg", [("short", "8 أحرف"), ("", "8 أحرف"), (None, "8 أحرف"), ("x" * 201, "طويلة"), ("sarasara", "نفس اسم المستخدم")])
def test_password_rules(pw, msg):
    assert msg in str(err(ac.create_first, "سارة", "sarasara", pw))


def test_passwords_are_stored_as_argon2id_and_never_in_the_clear():
    owner()
    with sqlite3.connect(ac.db_path()) as con:
        h = con.execute("SELECT pw_hash FROM users").fetchone()[0]
    assert h.startswith("$argon2id$") and PW not in h
    assert PW.encode() not in ac.db_path().read_bytes()
    assert "pw_hash" not in str(ac.list_users()) and "argon2" not in str(ac.list_users())


def test_duplicate_usernames_are_refused_case_insensitively():
    owner()
    e = err(ac.add_user, "تانية", "SARA", PW)
    assert e.code == "exists" and e.status == 409 and "مستعمل" in str(e)


def test_a_new_employee_must_change_the_temporary_password():
    owner()
    u = staff()
    assert u["must_change"] is True and u["active"] is True and u["created_by"] == "سارة"
    assert [x["username"] for x in ac.list_users()] == ["sara", "omar"]
    assert ac.get(u["id"])["username"] == "omar" and ac.get(999) is None


# ───────────────────────── الدخول والقفل ─────────────────────────
def test_login_checks_the_password_and_records_the_time():
    owner()
    assert ac.get(1)["last_login"] is None
    u = ac.authenticate("SARA", PW)                                                 # بلا حساسية لحالة الأحرف
    assert u["username"] == "sara" and ac.get(1)["last_login"]
    e = err(ac.authenticate, "sara", "wrong-password")
    assert e.code == "bad_login" and e.status == 401 and str(e) == "الاسم أو كلمة السر غلط"


def test_an_unknown_name_looks_exactly_like_a_wrong_password():
    owner()
    a, b = err(ac.authenticate, "ghost", PW), err(ac.authenticate, "sara", "nope-nope-1")
    assert (a.code, a.status, str(a)) == (b.code, b.status, str(b))


def test_a_disabled_account_cannot_log_in_but_only_a_correct_password_reveals_that():
    owner()
    o = staff()
    ac.set_active(1, o["id"], False)
    e = err(ac.authenticate, "omar", PW)
    assert e.code == "disabled" and e.status == 403 and "معطّل" in str(e)
    assert err(ac.authenticate, "omar", "wrong-wrong-1").code == "bad_login"


def test_five_wrong_attempts_lock_the_name_even_for_the_right_password_then_it_opens(monkeypatch):
    owner()
    staff()
    for _ in range(ac.LOGIN_FAILS):
        err(ac.authenticate, "sara", "bad-bad-bad-1")
    e = err(ac.authenticate, "sara", PW)
    assert e.code == "locked" and e.status == 429 and "دقيقة" in str(e)
    assert ac.authenticate("omar", PW)["username"] == "omar"                         # اسم تاني ما تأثّر
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + ac.LOGIN_WINDOW_SEC + 5)
    assert ac.authenticate("sara", PW)["username"] == "sara"


def test_a_good_login_clears_the_failure_count():
    owner()
    for _ in range(ac.LOGIN_FAILS - 1):
        err(ac.authenticate, "sara", "bad-bad-bad-1")
    ac.authenticate("sara", PW)
    for _ in range(ac.LOGIN_FAILS - 1):
        err(ac.authenticate, "sara", "bad-bad-bad-1")
    assert ac.authenticate("sara", PW)


# ───────────────────────── الجلسات ─────────────────────────
def test_sessions_store_only_a_hash_and_identify_the_user():
    u = owner()
    tok = ac.create_session(u["id"], "UA/1.0")
    assert len(tok) >= 40
    with sqlite3.connect(ac.db_path()) as con:
        row = con.execute("SELECT token_hash, ua FROM sessions").fetchone()
    assert row[0] != tok and tok not in row[0] and len(row[0]) == 64 and row[1] == "UA/1.0"
    assert tok.encode() not in ac.db_path().read_bytes()
    assert ac.session_user(tok)["username"] == "sara"
    for bad in (None, "", "garbage", "x" * 300, tok + "x"):
        assert ac.session_user(bad) is None


def test_expired_sessions_and_disabled_users_are_rejected():
    owner()
    o = staff()
    t1, t2 = ac.create_session(1), ac.create_session(o["id"])
    with sqlite3.connect(ac.db_path()) as con:
        con.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?", (ac._hash_token(t1),))
        con.commit()
    assert ac.session_user(t1) is None and ac.session_user(t2)["username"] == "omar"
    with sqlite3.connect(ac.db_path()) as con:
        con.execute("UPDATE users SET active=0 WHERE id=?", (o["id"],))
        con.commit()
    assert ac.session_user(t2) is None


def test_sessions_slide_forward_but_not_on_every_request(monkeypatch):
    u = owner()
    tok = ac.create_session(u["id"])

    def expires():
        with sqlite3.connect(ac.db_path()) as con:
            return con.execute("SELECT expires_at FROM sessions").fetchone()[0]

    with sqlite3.connect(ac.db_path()) as con:
        con.execute("UPDATE sessions SET expires_at='2099-01-01T00:00:00+00:00'")
        con.commit()
    ac.session_user(tok)                                    # أول مرة: بيجدّد
    first = expires()
    assert first < "2099"
    with sqlite3.connect(ac.db_path()) as con:
        con.execute("UPDATE sessions SET expires_at='2099-01-01T00:00:00+00:00'")
        con.commit()
    ac.session_user(tok)                                    # بعدها بلحظة: ما بيجدّد
    assert expires() == "2099-01-01T00:00:00+00:00"
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + ac.SLIDE_EVERY_SEC + 1)
    ac.session_user(tok)
    assert expires() < "2099"


def test_logout_ends_only_that_session():
    u = owner()
    a, b = ac.create_session(u["id"]), ac.create_session(u["id"])
    ac.end_session(a)
    ac.end_session(None)
    assert ac.session_user(a) is None and ac.session_user(b) is not None


# ───────────────────────── قواعد الأمان ─────────────────────────
def test_nobody_can_disable_themselves_and_unknown_accounts_are_404():
    owner()
    o = staff()
    e = err(ac.set_active, 1, 1, False)
    assert e.code == "rules" and "بنفسك" in str(e)
    assert ac.set_active(1, o["id"], False)["active"] is False
    assert ac.set_active(1, o["id"], True)["active"] is True
    assert err(ac.set_active, 1, 99, False).code == "not_found" and err(ac.set_active, 1, 99, True).status == 404


def test_the_last_active_account_cannot_be_disabled_by_anyone_else():
    owner()
    o = staff()
    ac.set_active(1, o["id"], False)                                                  # سارة آخر فعّالة
    e = err(ac.set_active, o["id"], 1, False)
    assert e.code == "rules" and "آخر حساب" in str(e)


def test_disabling_kicks_the_employee_out_of_every_session():
    owner()
    o = staff()
    toks = [ac.create_session(o["id"]) for _ in range(3)]
    ac.set_active(1, o["id"], False)
    assert all(ac.session_user(t) is None for t in toks)
    ac.set_active(1, o["id"], True)
    assert all(ac.session_user(t) is None for t in toks)                              # التفعيل ما بيرجّع الجلسات القديمة


def test_resetting_a_password_forces_a_change_and_ends_sessions_but_never_your_own():
    owner()
    o = staff()
    tok = ac.create_session(o["id"])
    ac.change_password(o["id"], PW, "my-own-secret-1")
    assert ac.authenticate("omar", "my-own-secret-1")["must_change"] is False
    r = ac.reset_password(1, o["id"], "temp-temp-123")
    assert r["must_change"] is True and ac.session_user(tok) is None
    assert err(ac.authenticate, "omar", "my-own-secret-1").code == "bad_login"
    assert ac.authenticate("omar", "temp-temp-123")["must_change"] is True
    e = err(ac.reset_password, 1, 1, "temp-temp-123")
    assert e.code == "rules" and "بنفسك" in str(e)
    assert err(ac.reset_password, 1, 99, "temp-temp-123").status == 404
    assert "8 أحرف" in str(err(ac.reset_password, 1, o["id"], "short"))


def test_a_reset_also_clears_a_login_lock():
    owner()
    o = staff()
    for _ in range(ac.LOGIN_FAILS):
        err(ac.authenticate, "omar", "bad-bad-bad-1")
    assert err(ac.authenticate, "omar", PW).code == "locked"
    ac.reset_password(1, o["id"], "temp-temp-123")
    assert ac.authenticate("omar", "temp-temp-123")


def test_changing_your_own_password_needs_the_old_one_and_keeps_only_the_current_session():
    u = owner()
    cur, other = ac.create_session(u["id"]), ac.create_session(u["id"])
    e = err(ac.change_password, u["id"], "wrong-wrong-1", "new-password-9", cur)
    assert e.code == "bad_login" and e.status == 403
    assert "مختلفة" in str(err(ac.change_password, u["id"], PW, PW, cur))
    assert "8 أحرف" in str(err(ac.change_password, u["id"], PW, "short", cur))
    ac.change_password(u["id"], PW, "new-password-9", cur)
    assert ac.session_user(cur) is not None and ac.session_user(other) is None
    assert ac.authenticate("sara", "new-password-9") and err(ac.authenticate, "sara", PW).code == "bad_login"


def test_the_remotion_seat_reminder_counts_active_accounts_only():
    owner()
    for i in range(2):
        staff(f"emp{i}", f"موظف {i}")
    assert ac.seats_note() == "" and ac.active_count() == 3
    fourth = staff("emp9", "الرابع")
    note = ac.seats_note()
    assert "4 موظفين" in note and "Remotion" in note and "3" in note
    ac.set_active(1, fourth["id"], False)
    assert ac.seats_note() == ""


# ───────────────────────── مين عم يشتغل ─────────────────────────
def test_who_prefers_the_logged_in_employee_then_the_environment_then_the_fallback(monkeypatch):
    assert ac.who() == "" and ac.who("owner") == "owner"
    monkeypatch.setenv("VP_ACTOR", "عمر")
    assert ac.who("owner") == "عمر"
    tok = ac.ACTOR.set({"id": 1, "display_name": "سارة"})
    try:
        assert ac.who("owner") == "سارة" and ac.actor()["id"] == 1
    finally:
        ac.ACTOR.reset(tok)
    assert ac.who("owner") == "عمر"


def test_actor_name_only_replaces_the_generic_defaults(monkeypatch):
    assert [ac.actor_name(x) for x in ("system", "owner", "", "ai", "سارة")] == ["system", "owner", "", "ai", "سارة"]
    tok = ac.ACTOR.set({"id": 1, "display_name": "سارة"})
    try:
        assert [ac.actor_name(x) for x in ("system", "owner", "", "ai", "check")] == ["سارة", "سارة", "سارة", "ai", "check"]
    finally:
        ac.ACTOR.reset(tok)


def test_the_station_state_log_carries_the_employee_name(env):
    import studio_state
    tok = ac.ACTOR.set({"id": 1, "display_name": "سارة"})
    try:
        st = studio_state.set_state("s1", 4, "awaiting_choice", "x")
    finally:
        ac.ACTOR.reset(tok)
    assert st["events"][-1]["by"] == "سارة"
    assert studio_state.set_state("s1", 4, "approved", "y")["events"][-1]["by"] == "system"


# ───────────────────────── سطر الأوامر ─────────────────────────
def run_cli(monkeypatch, argv, passwords=()):
    import getpass
    it = iter(passwords)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(it))
    monkeypatch.setattr(sys, "argv", ["accounts.py", *argv])
    ac.main()


def test_the_cli_can_create_the_first_account_then_employees_and_reset_a_locked_out_owner(monkeypatch, capsys):
    run_cli(monkeypatch, ["create", "sara", "سارة", "أحمد"], [PW, PW])
    assert ac.list_users()[0]["display_name"] == "سارة أحمد" and not ac.list_users()[0]["must_change"]
    run_cli(monkeypatch, ["create", "omar", "عمر"], [PW, PW])
    assert ac.get(2)["must_change"] is True and "لازم يغيّر" in capsys.readouterr().out
    ac.set_active(1, 2, False)
    ac.create_session(1)
    run_cli(monkeypatch, ["reset", "sara"], ["brand-new-pass-1", "brand-new-pass-1"])
    assert ac.get(1)["must_change"] is True and ac.authenticate("sara", "brand-new-pass-1")
    run_cli(monkeypatch, ["reset", "omar"], ["brand-new-pass-2", "brand-new-pass-2"])
    assert ac.get(2)["active"] is True                                               # الاسترجاع بيفتح الحساب المعطّل
    run_cli(monkeypatch, ["list"])
    out = capsys.readouterr().out
    assert "sara" in out and "omar" in out and "بدّه كلمة سر جديدة" in out


def test_the_cli_reports_mismatches_and_unknown_names(monkeypatch):
    owner()
    with pytest.raises(SystemExit, match="مش متطابقتين"):
        run_cli(monkeypatch, ["reset", "sara"], ["one-pass-123", "two-pass-123"])
    with pytest.raises(SystemExit, match="ما في موظف بهالاسم"):
        run_cli(monkeypatch, ["reset", "ghost"], [PW, PW])
    with pytest.raises(SystemExit, match="8 أحرف"):
        run_cli(monkeypatch, ["create", "newbie", "جديد"], ["short", "short"])


def test_a_missing_argon2_is_reported_in_arabic(monkeypatch):
    monkeypatch.setattr(ac, "_hasher", None)
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("argon2"):
            raise ImportError("no argon2", name="argon2")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert "argon2-cffi" in str(err(ac.create_first, "سارة", "sara", PW))
