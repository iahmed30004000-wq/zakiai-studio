from datetime import date, timedelta

import pytest

import drafts
import fatigue
from vp_b1_helpers import TODAY, ad, day, install_env, load_rows, series


@pytest.fixture
def env(tmp_path, monkeypatch):
    return install_env(tmp_path, monkeypatch)


def setup_ad(env, rows_builder, **kw):
    env.product("kama")
    _, sid = env.script("kama", 1, "kama_pat")
    name = ad("kama", sid)
    load_rows(rows_builder(name, **kw) if callable(rows_builder) else rows_builder)
    return name, sid


def test_seven_rises_and_falling_engagement_is_fatigue_and_makes_pending_draft(env):
    name, sid = setup_ad(env, series, points=8)
    alerts = fatigue.scan(TODAY)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["type"] == "fatigue" and a["ad_name"] == name and a["script_id"] == sid
    assert a["days"] == 7 and a["since"] == day(-7) and a["until"] == day(0)
    assert "ارتفعت 7 أيام" in a["detail"] and "التفاعل نازل" in a["detail"]

    ids = fatigue.scan_and_draft(TODAY)
    assert len(ids) == 1
    d = drafts.get(ids[0])
    assert d["status"] == "pending" and d["ad_name"] == name and d["approved_at"] is None
    assert d["product"]["file"] == "kama.json" and d["product"]["code"] == "kama"


def test_six_rises_is_not_enough(env):
    setup_ad(env, series, points=7)
    assert fatigue.scan(TODAY) == []
    assert fatigue.scan_and_draft(TODAY) == []
    assert drafts.list_drafts() == []


def test_fatigue_days_comes_from_config(env, monkeypatch):
    monkeypatch.setattr(fatigue.config, "FATIGUE_DAYS", 5)
    setup_ad(env, series, points=7)                       # 6 ارتفاعات ≥ 5
    assert [a["type"] for a in fatigue.scan(TODAY)] == ["fatigue"]


def test_no_engagement_data_means_watch_only_no_draft(env):
    setup_ad(env, series, points=8, engagement=None)
    (a,) = fatigue.scan(TODAY)
    assert a["type"] == "watch" and "تفاعل" in a["detail"]
    assert fatigue.scan_and_draft(TODAY) == [] and drafts.list_drafts() == []


def test_mostly_missing_engagement_is_treated_as_no_data(env):
    name, _ = setup_ad(env, [])
    rows = series(name, 8, engagement=(0.03, 0.02))
    for r in rows[:5]:
        r.pop("engagement")                               # 3 من 8 بس
    load_rows(rows)
    (a,) = fatigue.scan(TODAY)
    assert a["type"] == "watch"


def test_cost_rising_but_engagement_not_falling_is_only_watch(env):
    setup_ad(env, series, points=8, engagement=(0.020, 0.030))
    (a,) = fatigue.scan(TODAY)
    assert a["type"] == "watch" and "مش إرهاق مؤكد" in a["detail"]
    assert fatigue.scan_and_draft(TODAY) == []


def test_low_volume_falling_engagement_downgraded_to_watch(env):
    setup_ad(env, series, points=8, delivered=2)          # 16 مُسلَّم بالفترة < 20
    (a,) = fatigue.scan(TODAY)
    assert a["type"] == "watch" and "قليلة" in a["detail"]


def test_non_vp_ad_is_ignored_entirely(env):
    env.product("kama")
    load_rows(series("SY|kama|DawaCare|video", 10))
    assert fatigue.scan(TODAY) == []


def test_gap_or_zero_delivered_day_breaks_the_streak(env):
    setup_ad(env, series, points=12, skip=(4,))           # آخر 7 نقاط متتالية = 6 ارتفاعات فقط
    assert fatigue.scan(TODAY) == []


def test_zero_delivered_day_breaks_the_streak(env):
    setup_ad(env, series, points=10, zero_delivered=(5,))
    assert fatigue.scan(TODAY) == []


def test_stopped_ad_is_not_flagged(env):
    setup_ad(env, series, points=8, end_offset=-10)
    assert fatigue.scan(TODAY) == []


def test_immature_days_do_not_count(env, monkeypatch):
    monkeypatch.setattr(fatigue.config, "PERF_MATURITY_DAYS", 3)
    setup_ad(env, series, points=8)                       # آخر 3 أيام غير ناضجة → 5 نقاط بس
    assert fatigue.scan(TODAY) == []


def test_scan_and_draft_is_idempotent_across_runs_and_growing_streak(env):
    name, _ = setup_ad(env, series, points=8)
    first = fatigue.scan_and_draft(TODAY)
    assert len(first) == 1 and fatigue.scan_and_draft(TODAY) == []
    assert len(drafts.list_drafts()) == 1

    # يوم كمان بنفس الاتجاه: نفس الفترة (نفس بداية السلسلة) → ما بتتكرر المسودة
    tomorrow = TODAY + timedelta(days=1)
    load_rows(series(name, 9, end_offset=1))
    (a,) = fatigue.scan(tomorrow)
    assert a["days"] == 8 and a["since"] == day(-7)
    assert fatigue.scan_and_draft(tomorrow) == []
    assert len(drafts.list_drafts()) == 1


def test_new_streak_after_break_gets_new_draft(env):
    name, _ = setup_ad(env, series, points=8)
    assert len(fatigue.scan_and_draft(TODAY)) == 1
    later = date.fromisoformat(day(20))
    load_rows(series(name, 8, end_offset=20, base=2.0))
    assert len(fatigue.scan_and_draft(later)) == 1
    assert len(drafts.list_drafts()) == 2
