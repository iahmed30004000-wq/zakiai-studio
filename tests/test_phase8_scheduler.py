import json
import sys
import time
import types
from datetime import datetime, timedelta, timezone

import pytest

import agent
import backup
import config
import library_sync
import queue_worker
import scheduler
from tests.phase8_support import FAKE_KEY_A, hide_module, isolated


@pytest.fixture
def env(isolated, monkeypatch):
    calls = []
    isolated.calls = calls
    isolated.clock = {"now": datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(scheduler, "_now", lambda: isolated.clock["now"])
    monkeypatch.setattr(queue_worker, "poll_once", lambda: calls.append("queue_poll") or {"ok": True})
    monkeypatch.setattr(backup, "run_daily_if_due", lambda: calls.append("backup_daily") or {"ok": True})
    monkeypatch.setattr(library_sync, "push_if_changed", lambda: calls.append("library_sync") or {"ok": True})

    def fake(modname, func, label, ret):
        m = types.ModuleType(modname)
        setattr(m, func, lambda: calls.append(label) or ret)
        monkeypatch.setitem(sys.modules, modname, m)

    fake("crm", "sync_performance", "crm_sync", {"ok": True, "rows": 10})
    fake("fatigue", "scan_and_draft", "fatigue_scan", ["d1"])
    fake("learn_patterns", "run_weekly_if_due", "learn_weekly", {"skipped_reason": "not due"})
    isolated.mp = monkeypatch
    return isolated


def _state(env):
    return json.loads((env.lib / "scheduler_state.json").read_text(encoding="utf-8"))["tasks"]


def test_catch_up_runs_everything_due_in_order(env):
    res = scheduler.run_due()
    assert [r["task"] for r in res] == scheduler.TASK_NAMES
    assert all(r["ran"] and r.get("ok") for r in res)
    assert env.calls == ["queue_poll", "crm_sync", "fatigue_scan", "learn_weekly",
                         "backup_daily", "library_sync"]
    st = _state(env)
    assert set(st) == set(scheduler.TASK_NAMES)
    assert all(st[t]["last_success"] and st[t]["last_error"] is None for t in st)


def test_nothing_runs_again_until_due(env):
    scheduler.run_due()
    env.calls.clear()
    env.clock["now"] += timedelta(minutes=10)
    assert [r for r in scheduler.run_due() if r["ran"]] == []
    assert env.calls == []


def test_intervals_and_daily_rules(env):
    scheduler.run_due()
    env.calls.clear()
    env.clock["now"] += timedelta(minutes=61)                      # ساعة: الطابور والرفع
    scheduler.run_due()
    assert set(env.calls) == {"queue_poll", "learn_weekly", "library_sync", "backup_daily"}
    assert "crm_sync" not in env.calls and "fatigue_scan" not in env.calls
    env.calls.clear()
    env.clock["now"] += timedelta(days=1)                          # يوم جديد: كله
    scheduler.run_due()
    assert "crm_sync" in env.calls and "fatigue_scan" in env.calls


def test_queue_poll_follows_config_minutes(env, monkeypatch):
    monkeypatch.setattr(config, "CRM_QUEUE_POLL_MINUTES", 10)
    scheduler.run_due()
    env.calls.clear()
    env.clock["now"] += timedelta(minutes=11)
    scheduler.run_due()
    assert env.calls == ["queue_poll"]


def test_catch_up_after_being_off_for_days(env):
    """الجهاز كان مطفي 5 أيام: أول تشغيل بيكمّل كل المستحق من آخر نقطة."""
    scheduler.run_due()
    env.calls.clear()
    env.clock["now"] += timedelta(days=5)
    res = scheduler.run_due()
    assert [r["task"] for r in res if r["ran"]] == scheduler.TASK_NAMES
    assert len(env.calls) == 6


def test_missing_module_is_skipped_without_crashing(env):
    for m in ("crm", "fatigue", "learn_patterns"):
        hide_module(env.mp, m)
    res = {r["task"]: r for r in scheduler.run_due()}
    for t in ("crm_sync", "fatigue_scan", "learn_weekly"):
        assert res[t]["ran"] and res[t]["skipped"]
    for t in ("queue_poll", "backup_daily", "library_sync"):
        assert res[t].get("ok")
    assert "queue_poll" in env.calls and "backup_daily" in env.calls
    st = _state(env)
    assert st["crm_sync"]["last_outcome"] == "skipped" and st["crm_sync"].get("last_success") is None


def test_missing_module_is_rechecked_hourly_not_every_minute(env):
    hide_module(env.mp, "crm")
    scheduler.run_due()
    env.clock["now"] += timedelta(minutes=5)
    assert not scheduler.run_task("crm_sync")["ran"]
    env.clock["now"] += timedelta(minutes=60)
    assert scheduler.run_task("crm_sync")["ran"]


def test_missing_function_in_existing_module_is_skipped(env):
    env.mp.setitem(sys.modules, "fatigue", types.ModuleType("fatigue"))
    r = scheduler.run_task("fatigue_scan", force=True)
    assert r["ran"] and r["skipped"]


def test_task_error_does_not_stop_the_others_and_is_recorded_redacted(env):
    def boom():
        raise RuntimeError(f"فشل بمفتاح {FAKE_KEY_A}")
    env.mp.setattr(queue_worker, "poll_once", boom)
    crm = types.ModuleType("crm")
    crm.sync_performance = lambda: {"ok": False, "error": "الـ OMS مش متصل"}
    env.mp.setitem(sys.modules, "crm", crm)

    res = {r["task"]: r for r in scheduler.run_due()}
    assert res["queue_poll"]["error"] and FAKE_KEY_A not in res["queue_poll"]["error"]
    assert res["crm_sync"]["error"] == "الـ OMS مش متصل"
    for t in ("fatigue_scan", "learn_weekly", "backup_daily", "library_sync"):
        assert res[t].get("ok"), t
    assert env.calls == ["fatigue_scan", "learn_weekly", "backup_daily", "library_sync"]
    st = _state(env)
    assert st["queue_poll"]["last_error"] and st["queue_poll"]["failures"] == 1
    assert st["queue_poll"].get("last_success") is None
    assert FAKE_KEY_A not in (env.lib / "scheduler_state.json").read_text(encoding="utf-8")
    assert st["fatigue_scan"]["last_error"] is None


def test_failed_daily_task_retries_after_short_wait_not_every_minute(env):
    crm = types.ModuleType("crm")
    crm.sync_performance = lambda: {"ok": False, "error": "x"}
    env.mp.setitem(sys.modules, "crm", crm)
    scheduler.run_due()
    env.clock["now"] += timedelta(minutes=5)
    assert not scheduler.run_task("crm_sync")["ran"]
    env.clock["now"] += timedelta(minutes=11)
    assert scheduler.run_task("crm_sync")["ran"]


def test_agent_run_once_and_exit_codes(env, capsys):
    assert agent.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "queue_poll" in out and len(env.calls) == 6
    env.mp.setattr(queue_worker, "poll_once", lambda: {"ok": False, "error": "x"})
    env.clock["now"] += timedelta(days=2)
    assert agent.main(["run"]) == 1
    assert agent.main(["run", "--only", "nope"]) == 2
    env.calls.clear()
    env.clock["now"] += timedelta(days=2)
    assert agent.main(["run", "--only", "backup_daily", "--json"]) == 0
    assert env.calls == ["backup_daily"]


def test_agent_force_runs_even_if_not_due(env):
    scheduler.run_due()
    env.calls.clear()
    assert agent.main(["run", "--force", "--only", "library_sync"]) == 0
    assert env.calls == ["library_sync"]


def test_cross_process_lock_prevents_double_run(env):
    import oplock
    with oplock.file_lock(env.lib / ".sched_queue_poll.lock") as got:
        assert got
        r = scheduler.run_task("queue_poll")
    assert r["ran"] is False and "عملية تانية" in r["reason"]
    assert "queue_poll" not in env.calls
    assert scheduler.run_task("queue_poll")["ran"]


def test_background_thread_catches_up_on_start_and_stops(env):
    assert scheduler.start(initial_delay=0, check_every=0.05) is True
    try:
        assert scheduler.start(initial_delay=0, check_every=0.05) is False     # idempotent
        deadline = time.time() + 5
        while len(env.calls) < 6 and time.time() < deadline:
            time.sleep(0.05)
        assert set(env.calls) == set(scheduler.TASK_NAMES)
        assert scheduler.status()["running"] is True
    finally:
        scheduler.stop()
    time.sleep(0.2)
    assert scheduler.status()["running"] is False


def test_can_be_disabled_by_env(env, monkeypatch):
    monkeypatch.setenv("VIDPATTERN_NO_SCHEDULER", "1")
    assert scheduler.start(initial_delay=0) is False


def test_status_lists_every_task(env):
    scheduler.run_due()
    st = scheduler.status()
    assert [t["task"] for t in st["tasks"]] == scheduler.TASK_NAMES
    assert all(t["last_success"] for t in st["tasks"])


def test_offline_is_not_counted_as_a_failure(env):
    env.mp.setattr(queue_worker, "poll_once", lambda: {"ok": False, "offline": True, "error": "الـ OMS مش متصل"})
    r = scheduler.run_task("queue_poll")
    assert r["ran"] and r["offline"] and "error" not in r
    st = _state(env)["queue_poll"]
    assert st["last_outcome"] == "offline" and st["last_error"] is None and st.get("failures", 0) == 0
    assert agent.main(["run", "--only", "queue_poll", "--force"]) == 0       # ما بيخرّب Task Scheduler
