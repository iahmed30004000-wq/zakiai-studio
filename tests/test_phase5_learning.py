import json
from datetime import datetime, timedelta

import pytest

import learn_patterns
import llm
from vp_b1_helpers import TODAY, install_env, seed_market


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = install_env(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "task_config", lambda task: {"provider": "fake", "model": "fake-1"})
    return e


LEARNED = [{
    "pattern_name": "افتتاح بمقارنة قبل وبعد", "framework": "demo_proof",
    "one_line_summary": "مقارنة مباشرة بأول ثانيتين", "product_category": "eye_care",
    "dialect_or_language": "shami", "target_audience": "x", "hook": {"type": "comparison"},
    "scene_blueprint": [{"slot": 1, "function": "before/after", "emotion": "curiosity", "duration_sec": 4}],
    "evidence_strength": "متوسط — سيناريوهان ناجحان", "evidence_scripts": [], "reusability_score": 6,
}]


def fake_llm(monkeypatch, captured, answer=None):
    def complete_json(task, system, blocks, max_tokens=None):
        captured.append(json.loads(blocks[0]["text"].split("\n", 1)[1]))
        return LEARNED if answer is None else answer
    monkeypatch.setattr(llm, "complete_json", complete_json)


def seed_mixed(env):
    # الوسيط (3.0, 3.0, 6.0, 1.5) → 3.0 : 1=winner, 2 و4=ok, 3=loser, 5 تحت الحد
    return seed_market(env, "kama", [(1, "pa", 1.5, 40), (2, "pb", 3.0, 40), (3, "pc", 6.0, 40),
                                      (4, "pd", 3.0, 40), (5, "pe", 1.0, 10)])


def test_learning_uses_actual_verdicts_winner_vs_loser_only(env, monkeypatch):
    seed_mixed(env)
    sent = []
    fake_llm(monkeypatch, sent)
    r = learn_patterns.run(today=TODAY, log=lambda *_: None)
    assert r["ok"] and r["called_llm"] and r["winners"] == 1 and r["losers"] == 1

    (items,) = sent
    assert {i["result"] for i in items} == {"winner", "loser"}
    assert len(items) == 2                                   # ok وinsufficient ما بيروحوا للموديل
    assert all("cost_per_delivered" in i["metrics"] and "spend" in i["metrics"] for i in items)
    assert all(i["pattern_used"] != "pe" for i in items)      # تحت MIN_DELIVERED = بلا حكم

    saved = json.loads((env.patterns / "proven_افتتاح_بمقارنة_قبل_وبعد.pattern.json").read_text(encoding="utf-8"))
    assert saved["_source"]["type"] == "proven"
    assert r["results"] == [{"pattern_id": "proven_افتتاح_بمقارنة_قبل_وبعد",
                             "name": "افتتاح بمقارنة قبل وبعد", "evidence_strength": "متوسط — سيناريوهان ناجحان"}]


def test_manual_marks_are_not_used_for_learning(env, monkeypatch):
    import performance
    files = seed_market(env, "kama", [(1, "pa", 3.0, 40), (2, "pb", 3.0, 40), (3, "pc", 3.0, 40)])
    for f in files:
        performance.mark(f, "winner")                       # تعليم يدوي ما بيعني شي
    sent = []
    fake_llm(monkeypatch, sent)
    r = learn_patterns.run(today=TODAY, log=lambda *_: None)
    assert not r["called_llm"] and sent == []
    assert r["skipped_reason"] and "MIN_DELIVERED" not in r["skipped_reason"]


def test_skipped_when_no_actual_data_and_state_records_reason(env, monkeypatch):
    sent = []
    fake_llm(monkeypatch, sent)
    r = learn_patterns.run(today=TODAY, log=lambda *_: None)
    assert not r["ok"] and sent == [] and "محكوم عليها" in r["skipped_reason"]
    last = learn_patterns.last_run()
    assert last["skipped_reason"] == r["skipped_reason"] and last["results"] == []
    assert learn_patterns.load_state().get("last_success") is None


def test_no_winner_means_nothing_to_learn(env, monkeypatch):
    seed_market(env, "kama", [(1, "pa", 3.0, 40), (2, "pb", 3.0, 40), (3, "pc", 6.0, 40), (4, "pd", 6.5, 40),
                              (5, "pe", 3.0, 40)])
    r = learn_patterns.run(today=TODAY, log=lambda *_: None)
    assert not r["called_llm"] and "ناجح" in r["skipped_reason"]


def test_llm_failure_is_recorded_not_raised_and_not_a_success(env, monkeypatch):
    seed_mixed(env)
    def boom(*a, **k):
        raise llm.LLMError("انقطع المزوّد")
    monkeypatch.setattr(llm, "complete_json", boom)
    r = learn_patterns.run(today=TODAY, log=lambda *_: None)
    assert not r["ok"] and "انقطع" in r["error"]
    assert learn_patterns.load_state().get("last_success") is None


def test_weekly_runs_only_when_seven_days_passed_and_catches_up_after_offline(env, monkeypatch):
    seed_mixed(env)
    sent = []
    fake_llm(monkeypatch, sent, answer=[])
    t0 = datetime.now()                      # run() بيسجّل last_success بالوقت الحقيقي، فلازم نبدأ منه
    first = learn_patterns.run_weekly_if_due(now=t0, log=lambda *_: None)
    assert first["ran"] and first["ok"] and len(sent) == 1

    again = learn_patterns.run_weekly_if_due(now=t0 + timedelta(days=6, hours=23), log=lambda *_: None)
    assert not again["ran"] and len(sent) == 1

    # الجهاز كان مطفي 20 يوم → أول ما يرجع بيشتغل فوراً
    back = learn_patterns.run_weekly_if_due(now=t0 + timedelta(days=20), log=lambda *_: None)
    assert back["ran"] and len(sent) == 2
    assert learn_patterns.load_state()["last_success"].startswith("20")


def test_weekly_without_data_retries_next_time(env, monkeypatch):
    fake_llm(monkeypatch, [])
    t0 = datetime(2026, 9, 29, 9, 0)
    assert learn_patterns.run_weekly_if_due(now=t0, log=lambda *_: None)["skipped_reason"]
    r = learn_patterns.run_weekly_if_due(now=t0 + timedelta(hours=1), log=lambda *_: None)
    assert r["ran"]                                          # ما استهلك حصة الأسبوع
