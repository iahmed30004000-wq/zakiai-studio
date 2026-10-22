"""سجل النشاط (activity.py): وصف عربي لكل مسار كتابة، تسجيل الناجح بس، الفلاتر والترقيم."""

import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import activity as act  # noqa: E402

SARA = {"id": 1, "display_name": "سارة"}


# ───────────────────────── التغطية ─────────────────────────
def write_routes():
    from web.app import app
    spec = app.openapi()
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops if m.upper() in {"POST", "PUT", "PATCH", "DELETE"}]


def test_every_write_route_of_the_app_has_a_description_or_is_explicitly_silent():
    routes = write_routes()
    assert len(routes) > 150
    missing = [r for r in routes if not act.covered(*r)]
    assert missing == [], f"مسارات كتابة بلا وصف بسجل النشاط (ضيف قاعدة بـ activity._R أو SILENT): {missing}"


def test_no_rule_describes_a_route_that_does_not_exist():
    concrete = [(m, re.sub(r"\{[^}]+\}", "x1", p)) for m, p in write_routes()]
    dead = [(m, rx.pattern) for m, rx, _k, _t in act.RULES if not any(mm == m and rx.match(pp) for mm, pp in concrete)]
    assert dead == []
    silent_dead = [(m, rx.pattern) for m, rx in act.SILENT_RX if not any(mm == m and rx.match(pp) for mm, pp in concrete)]
    assert silent_dead == []


def test_rules_and_silent_routes_never_overlap_and_kinds_are_known():
    for m, rx, kind, text in act.RULES:
        assert kind in act.KINDS and text.strip() and not re.search(r"[A-Za-z]{6,}\s+[A-Za-z]{6,}", re.sub(r"\{[^}]+\}", "", text)), (m, rx.pattern)
    for m, p in write_routes():
        concrete = re.sub(r"\{[^}]+\}", "x1", p)
        assert not (act.describe(m, concrete) and act.is_silent(m, concrete)), (m, p)


def test_arabic_labels_do_not_leak_python_format_leftovers():
    for m, p in write_routes():
        d = act.describe(m, re.sub(r"\{[^}]+\}", "x1", p))
        if d:
            assert "{" not in d[1] and "}" not in d[1] and "None" not in d[1], (m, p, d)


# ───────────────────────── الوصف ─────────────────────────
@pytest.mark.parametrize("method,path,kind,text", [
    ("POST", "/api/product-refs/kama/angle/front", "upload", "رفع صورة وضعية «أمام» لمنتج kama"),
    ("DELETE", "/api/product-refs/kama/angle/in_hand", "delete", "حذف صورة وضعية «بيد» لمنتج kama"),
    ("POST", "/api/characters/ch_f_001/sheet/three_quarter", "upload", "رفع صورة وضعية «ثلاثة أرباع» للشخصية ch_f_001"),
    ("POST", "/api/studio/VARA__ad_109__20260913_1348.json/shots/s1c1/choose", "approve", "اختيار صورة للقطة s1c1 (VARA__ad_109__20260913_1348)"),
    ("PUT", "/api/studio/x.json/shots/s2c3/prompt", "edit", "تعديل برومبت اللقطة s2c3 (x)"),
    ("POST", "/api/studio/x.json/launch", "approve", "إطلاق إعلان من السيناريو x"),
    ("POST", "/api/scripts/s1.json/hooks/h2/version", "create", "عمل نسخة فيديو للهوك (h2) من السيناريو s1"),
    ("DELETE", "/api/presets/custom_2", "delete", "حذف أو إرجاع حركة سينمائية (custom_2)"),
    ("PUT", "/api/settings", "settings", "حفظ الإعدادات"),
    ("POST", "/api/providers/openai/models", "settings", "إضافة موديل لمزوّد openai"),
    ("DELETE", "/api/providers/openai/models/gpt-5/mini", "settings", "حذف موديل gpt-5/mini من مزوّد openai"),
    ("POST", "/api/auth/password", "account", "غيّر كلمة سره"),
])
def test_descriptions_read_like_the_example_in_the_plan(method, path, kind, text):
    assert act.describe(method, path) == (kind, text)


def test_paths_are_url_decoded_and_long_names_are_trimmed():
    assert act.describe("POST", "/api/studio/%D8%B3.json/shots/s1c1/choose")[1] == "اختيار صورة للقطة s1c1 (س)"
    long = "ا" * 80
    assert act.describe("PUT", f"/api/scripts/{long}.json")[1] == "حفظ تعديل السيناريو " + "ا" * 45 + "…"
    assert act.describe("get", "/api/presets") is None and act.describe("PATCH", "/api/presets") is None


def test_unknown_and_silent_paths_have_no_description():
    assert act.describe("POST", "/api/not/a/route") is None
    assert act.is_silent("POST", "/api/studio/s1.json/ext/log") and act.is_silent("POST", "/api/auth/login") and not act.is_silent("GET", "/api/ext/diag")
    assert act.describe("POST", "/api/studio/s1.json/ext/log") is None


# ───────────────────────── التسجيل ─────────────────────────
def test_only_successful_known_writes_are_recorded(env):
    assert act.record(SARA, "POST", "/api/presets", 200) is True
    assert act.record(SARA, "POST", "/api/presets", 399) is True
    assert act.record(SARA, "POST", "/api/presets", 400) is False and act.record(SARA, "POST", "/api/presets", 500) is False
    assert act.record(SARA, "GET", "/api/presets", 200) is False
    assert act.record(SARA, "POST", "/api/unknown/path", 200) is False
    assert act.record(SARA, "POST", "/api/studio/s1.json/ext/log", 200) is False
    items = act.list_events()["items"]
    assert len(items) == 2 and all(i["user_name"] == "سارة" and i["user_id"] == 1 and i["label"] == "إضافة حركة سينمائية جديدة" for i in items)


def test_events_carry_time_kind_and_the_users_name(env):
    act.record_event(SARA, "edit", "عدّل شي")
    act.record_event(None, "bogus", "حدث بلا موظف")
    a, b = act.list_events()["items"]
    assert b["user_name"] == "سارة" and b["kind_label"] == "تعديل" and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", b["at"])
    assert a["user_name"] == "—" and a["user_id"] is None and a["kind"] == "edit"                 # نوع غريب بيصير «تعديل»


def test_a_broken_database_never_breaks_the_request(env, monkeypatch):
    def boom():
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(act, "_db", boom)
    assert act.record_event(SARA, "edit", "x") is False and act.record(SARA, "POST", "/api/presets", 200) is False
    assert act.list_events() == {"items": [], "total": 0}


def test_labels_are_capped(env):
    act.record_event(SARA, "edit", "ا" * 500)
    assert len(act.list_events()["items"][0]["label"]) == 300


# ───────────────────────── القراءة والفلاتر ─────────────────────────
def seed():
    rows = [(1, "سارة", "create", "2026-10-20T08:00:00+00:00", "أ"), (2, "عمر", "upload", "2026-10-21T09:30:00+00:00", "ب"),
            (1, "سارة", "delete", "2026-10-21T20:00:00+00:00", "ج"), (0, "الإضافة", "upload", "2026-10-22T01:00:00+00:00", "د"),
            (2, "عمر", "approve", "2026-10-22T07:45:00+00:00", "هـ")]
    with act._db() as con:
        for u, n, k, at, label in rows:
            con.execute("INSERT INTO events(at, user_id, user_name, kind, label) VALUES(?,?,?,?,?)", (at, u, n, k, label))


def test_newest_first_with_totals_and_paging(env):
    seed()
    d = act.list_events()
    assert d["total"] == 5 and [i["label"] for i in d["items"]] == ["هـ", "د", "ج", "ب", "أ"]
    p = act.list_events(limit=2, offset=1)
    assert [i["label"] for i in p["items"]] == ["د", "ج"] and p["total"] == 5
    assert act.list_events(limit=0)["items"][0]["label"] == "هـ" and len(act.list_events(limit=0)["items"]) == 1
    assert len(act.list_events(limit=99999)["items"]) == 5 and act.list_events(offset=-5)["items"][0]["label"] == "هـ"


def test_filters_by_employee_kind_and_day_range(env):
    seed()
    assert [i["label"] for i in act.list_events(user_id=2)["items"]] == ["هـ", "ب"]
    assert [i["label"] for i in act.list_events(user_id=0)["items"]] == ["د"]
    assert [i["label"] for i in act.list_events(kind="upload")["items"]] == ["د", "ب"]
    assert [i["label"] for i in act.list_events(since="2026-10-21T00:00:00+00:00", until="2026-10-22T00:00:00+00:00")["items"]] == ["ج", "ب"]
    assert [i["label"] for i in act.list_events(user_id=2, kind="upload", since="2026-10-21T00:00:00+00:00")["items"]] == ["ب"]
    assert act.list_events(user_id=77) == {"items": [], "total": 0}
