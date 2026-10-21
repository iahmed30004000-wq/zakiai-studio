"""الترجمة التلقائية للأنماط: بتبدأ لحالها بالخلفية، ما بتشتغل مرتين، بتنتظر بعد الفشل، وما بتحرق محاولات على نص بيفشل دايماً."""

import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import clusters  # noqa: E402
import config  # noqa: E402
import oplock  # noqa: E402
import pattern_excel as px  # noqa: E402
import pattern_i18n as i18n  # noqa: E402
import pattern_store as ps  # noqa: E402
import pattern_text as pt  # noqa: E402
import review_queue  # noqa: E402
import translate_patterns as tp  # noqa: E402
from test_pattern_i18n import Fake, put, read  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    pdir = tmp_path / "library" / "patterns"
    pdir.mkdir(parents=True)
    monkeypatch.setattr(config, "PATTERNS_DIR", pdir)
    monkeypatch.setattr(config, "SCRIPTS_DIR", tmp_path / "library" / "scripts")
    monkeypatch.setattr(review_queue, "QUEUE_PATH", tmp_path / "rq.json")
    monkeypatch.setattr(clusters, "CLUSTERS_PATH", tmp_path / "library" / "clusters.json")
    monkeypatch.setattr(i18n, "_STATE", {"running": False, "done": 0, "total": 0, "started_at": None})
    monkeypatch.setattr(i18n, "_THREAD", None)
    monkeypatch.setenv("VP_AUTO_TRANSLATE", "1")
    monkeypatch.setattr(i18n, "_llm_ask", Fake())
    return tmp_path / "library"


def finish():
    assert i18n.wait(20), "الخيط ما خلص"


def seed(lib, *pids):
    for pid in pids:
        put(lib, pid)


# ═════════════════ البدء والانتهاء ═════════════════
def test_it_starts_by_itself_translates_everything_and_stops(lib):
    seed(lib, "a", "b", "c")
    r = i18n.ensure_running()
    assert r["started"] is True and r["pending_patterns"] == 3
    finish()
    s = i18n.status()
    assert s["pending_patterns"] == 0 and s["running"] is False and s["error"] == "" and s["retry_in"] == 0
    assert all(pt.display_name(read(lib, p)).startswith("نص عربي") for p in "abc")
    assert any(f.name.startswith("ar_") for f in (lib / "_backups").iterdir())             # نسخة احتياطية لكل تشغيلة


def test_nothing_pending_means_nothing_starts(lib):
    r = i18n.ensure_running()
    assert r["started"] is False and r["pending_patterns"] == 0 and i18n.wait(1)


def test_a_second_call_while_running_does_not_start_another_worker(lib, monkeypatch):
    seed(lib, "a")
    gate, entered = threading.Event(), threading.Event()

    def slow_run(**kw):
        entered.set()
        gate.wait(10)
        return {"done": 1, "failed": [], "stamp": None, "remaining": 0}

    monkeypatch.setattr(tp, "run", slow_run)
    assert i18n.ensure_running()["started"] is True
    assert entered.wait(5)
    again = i18n.ensure_running()
    assert again["started"] is False and again["running"] is True
    gate.set()
    finish()
    assert i18n.status()["running"] is False


def test_progress_is_visible_while_it_runs(lib, monkeypatch):
    seed(lib, "a")
    mid, gate = threading.Event(), threading.Event()

    def run(on_progress=None, **kw):
        on_progress(1, 3)
        mid.set()
        gate.wait(10)
        return {"done": 3, "failed": [], "stamp": None, "remaining": 0}

    monkeypatch.setattr(tp, "run", run)
    i18n.ensure_running()
    assert mid.wait(5)
    s = i18n.status()
    assert (s["running"], s["done"], s["total"]) == (True, 1, 3)
    gate.set()
    finish()


def test_the_run_reports_per_pattern_progress_to_the_callback(lib):
    seed(lib, "a", "b")
    seen = []
    tp.run(on_progress=lambda d, t: seen.append((d, t)), auto=True)
    assert seen[0] == (0, 2) and seen[-1] == (2, 2)


# ═════════════════ الإيقاف والتفعيل ═════════════════
def test_the_flag_off_blocks_auto_start_but_the_retry_button_still_works(lib, monkeypatch):
    seed(lib, "a")
    monkeypatch.setenv("VP_AUTO_TRANSLATE", "0")
    r = i18n.ensure_running()
    assert r["started"] is False and r["auto"] is False and r["pending_patterns"] == 1
    r = i18n.ensure_running(force=True)
    assert r["started"] is True
    finish()
    assert i18n.status()["pending_patterns"] == 0


def test_the_config_switch_also_turns_it_off(lib, monkeypatch):
    monkeypatch.setattr(config, "AUTO_TRANSLATE_PATTERNS", False, raising=False)
    assert i18n.auto_enabled() is False


# ═════════════════ الفشل والانتظار ═════════════════
def test_a_failure_waits_before_trying_again_and_the_button_skips_the_wait(lib, monkeypatch):
    seed(lib, "a", "b", "c", "d")

    def refuse(system, user):
        raise i18n.TranslateError("مفتاح الـ API مرفوض")

    monkeypatch.setattr(i18n, "_llm_ask", refuse)
    assert i18n.ensure_running()["started"] is True
    finish()
    s = i18n.status()
    assert s["error"] == "مفتاح الـ API مرفوض" and s["retry_in"] > 0 and s["pending_patterns"] == 4 and s["running"] is False
    assert i18n.ensure_running()["started"] is False                       # لسا بالانتظار
    monkeypatch.setattr(i18n, "_llm_ask", Fake())                          # المالك صلّح المفتاح
    r = i18n.ensure_running(force=True)
    assert r["started"] is True
    finish()
    s = i18n.status()
    assert s["error"] == "" and s["retry_in"] == 0 and s["pending_patterns"] == 0       # النجاح بيمسح الخطأ


def test_after_the_wait_it_retries_by_itself(lib, monkeypatch):
    seed(lib, "a", "b", "c")

    def refuse(system, user):
        raise i18n.TranslateError("انقطع الاتصال")

    monkeypatch.setattr(i18n, "_llm_ask", refuse)
    i18n.ensure_running()
    finish()
    assert i18n.retry_in() > 0
    monkeypatch.setattr(i18n, "RETRY_AFTER_SEC", 0)
    monkeypatch.setattr(i18n, "_llm_ask", Fake())
    assert i18n.ensure_running()["started"] is True
    finish()
    assert i18n.status()["pending_patterns"] == 0


def test_the_failure_survives_a_restart(lib, monkeypatch):
    i18n.record_failure("مفتاح مرفوض")
    monkeypatch.setattr(i18n, "_STATE", {"running": False, "done": 0, "total": 0, "started_at": None})     # «إعادة تشغيل»
    assert i18n.status()["error"] == "مفتاح مرفوض" and i18n.retry_in() > 0
    assert json.loads(i18n._state_file().read_text(encoding="utf-8"))["error"] == "مفتاح مرفوض"


def test_an_unexpected_crash_in_the_worker_is_recorded_not_swallowed(lib, monkeypatch):
    seed(lib, "a")

    def boom(**kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tp, "run", boom)
    i18n.ensure_running()
    finish()
    s = i18n.status()
    assert s["error"] == "disk full" and s["running"] is False


# ═════════════════ حد المحاولات ═════════════════
def test_a_pattern_that_never_finishes_stops_being_retried_until_the_button(lib, monkeypatch):
    seed(lib, "a")

    def stubborn(system, user):
        t = json.loads(user)["texts"]
        return {"translations": {k: ("Still English text" if k == "pattern_name" else "نص عربي") for k in t}}

    monkeypatch.setattr(i18n, "_llm_ask", stubborn)
    for _ in range(i18n.MAX_ATTEMPTS):
        assert i18n.ensure_running()["started"] is True
        finish()
    s = i18n.status()
    assert s["stuck"] == 1 and s["pending_patterns"] == 1 and s["error"] == ""
    assert i18n.ensure_running()["started"] is False                       # استسلمت: ما بتحرق مصاري
    monkeypatch.setattr(i18n, "_llm_ask", Fake())
    assert i18n.ensure_running(force=True)["started"] is True              # الزر بيصفّر العدّاد
    finish()
    assert i18n.status()["pending_patterns"] == 0 and i18n.status()["stuck"] == 0


def test_a_connection_failure_does_not_count_as_a_pattern_attempt(lib, monkeypatch):
    seed(lib, "a", "b", "c")
    monkeypatch.setattr(i18n, "_llm_ask", lambda s, u: (_ for _ in ()).throw(i18n.TranslateError("x")))
    i18n.ensure_running()
    finish()
    assert i18n.load_state()["attempts"] == {} and i18n.status()["stuck"] == 0


# ═════════════════ سباق مع عملية تانية ═════════════════
def test_when_another_process_is_translating_the_worker_stands_down(lib):
    seed(lib, "a")
    with oplock.file_lock(i18n._lock_file()) as got:
        assert got
        i18n.ensure_running()
        finish()
    s = i18n.status()
    assert s["pending_patterns"] == 1 and s["running"] is False and not (lib / "_backups").exists()


# ═════════════════ مين بيشغّلها ═════════════════
def test_a_new_english_pattern_starts_it_but_an_arabic_one_does_not(lib, monkeypatch):
    calls = []
    monkeypatch.setattr(i18n, "kick", lambda: calls.append(1))
    base = {"framework": "pas", "product_category": "fragrance", "hook": {"type": "سؤال"},
            "scene_blueprint": [{"function": "أ"}, {"function": "ب"}, {"function": "ج"}]}
    ps.create({**base, "pattern_name": "نمط عربي كامل"})
    assert calls == []
    ps.create({**base, "pattern_name": "Slow ingredient reveal"})
    assert calls == [1]


def test_an_excel_import_kicks_once_at_the_end(lib, monkeypatch):
    from test_pattern_excel import example_pattern, make_xlsx
    calls = []
    monkeypatch.setattr(i18n, "kick", lambda: calls.append(1))
    a, asc = example_pattern(pattern_name="أول")
    b, bsc = example_pattern(pattern_name="تاني")
    out = px.commit(px.preview(make_xlsx([a, b], asc + bsc))["token"])
    assert len(out["created"]) == 2 and calls == [1]


def test_startup_schedules_a_delayed_daemon_timer_only_when_enabled(lib, monkeypatch):
    made = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.delay, self.fn, self.daemon, self.started = delay, fn, False, False
            made.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(i18n.threading, "Timer", FakeTimer)
    i18n.schedule_startup(5)
    assert len(made) == 1 and made[0].delay == 5 and made[0].daemon is True and made[0].started and made[0].fn is i18n.kick
    monkeypatch.setenv("VP_AUTO_TRANSLATE", "0")
    i18n.schedule_startup(5)
    assert len(made) == 1


def test_the_server_startup_calls_it():
    src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "app.py"), encoding="utf-8").read()
    assert "pattern_i18n.schedule_startup()" in src


def test_kick_never_raises(lib, monkeypatch):
    monkeypatch.setattr(i18n, "ensure_running", lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
    i18n.kick()


# ═════════════════ المسارات ═════════════════
@pytest.fixture
def client(lib):
    from fastapi.testclient import TestClient
    from web.app import app
    return TestClient(app)


def test_the_routes_expose_status_and_start_it(client, lib):
    seed(lib, "a", "b")
    s = client.get("/api/pattern-lib/translation").json()
    assert set(s) == {"patterns", "pending_patterns", "pending_keys", "running", "done", "total", "auto", "error", "retry_in", "stuck"}
    assert s["patterns"] == 2 and s["pending_patterns"] == 2 and s["auto"] is True and s["running"] is False
    r = client.post("/api/pattern-lib/translate", json={}).json()
    assert r["ok"] is True and r["started"] is True
    finish()
    assert client.get("/api/pattern-lib/translation").json()["pending_patterns"] == 0
    assert client.post("/api/pattern-lib/translate", json={}).json()["started"] is False         # ما في شي ناقص


def test_the_retry_flag_skips_the_wait(client, lib, monkeypatch):
    seed(lib, "a")
    i18n.record_failure("مفتاح مرفوض")
    assert client.post("/api/pattern-lib/translate", json={}).json()["started"] is False         # لسا بالانتظار
    r = client.post("/api/pattern-lib/translate", json={"retry": True}).json()
    assert r["started"] is True
    finish()


def test_a_bad_limit_is_a_400(client):
    assert client.post("/api/pattern-lib/translate", json={"limit": "abc"}).status_code == 400
