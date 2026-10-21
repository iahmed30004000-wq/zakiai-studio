from datetime import datetime, timedelta, timezone

import pytest

import llm
import settings_io
import usage
from tests.phase8_support import isolated


def _cfg(kind="openai"):
    return {"task": "writer", "provider": "openai", "kind": kind, "model": "gpt-5",
            "base_url": "https://api.example.test/v1", "api_key": "x", "vision": True}


@pytest.fixture
def wired(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "task_config", lambda task: _cfg())
    monkeypatch.setattr(llm, "_call_openai", lambda cfg, s, b, m: calls.append("openai") or "ok")
    monkeypatch.setattr(llm, "_call_anthropic", lambda cfg, s, b, m: calls.append("anthropic") or "ok")

    def no_network(*a, **k):
        raise AssertionError("ممنوع شبكة حقيقية")
    monkeypatch.setattr(llm.requests, "post", no_network)
    isolated.calls = calls
    return isolated


def _blocks():
    return [{"type": "text", "text": "hi"}]


def _spend(amount, at=None):
    usage.init_db()
    with usage._connect() as conn:
        conn.execute(
            "INSERT INTO calls (at, task, provider, model, input_tokens, output_tokens, cost_usd, ok) "
            "VALUES (?,?,?,?,?,?,?,1)",
            ((at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
             "writer", "openai", "gpt-5", 1, 1, amount))


def test_daily_limit_blocks_the_call(wired):
    usage.set_limits(1.0, None)
    _spend(2.0)
    with pytest.raises(llm.LLMError, match="حد الإنفاق اليومي"):
        llm.complete("writer", "s", _blocks())
    assert wired.calls == []                      # النداء ما طلع أبداً


def test_monthly_limit_blocks_the_call(wired):
    usage.set_limits(None, 5.0)
    _spend(6.0)
    with pytest.raises(llm.LLMError, match="حد الإنفاق الشهري"):
        llm.complete("writer", "s", _blocks())
    assert wired.calls == []


def test_under_limit_passes_through(wired):
    usage.set_limits(10.0, 100.0)
    _spend(2.0)
    assert llm.complete("writer", "s", _blocks()) == "ok"
    assert wired.calls == ["openai"]


def test_limit_reached_exactly_blocks(wired):
    usage.set_limits(2.0, None)
    _spend(2.0)
    with pytest.raises(llm.LLMError):
        llm.complete("writer", "s", _blocks())


def test_no_limit_means_unlimited(wired):
    usage.set_limits(None, None)
    _spend(9999.0)
    assert llm.complete("writer", "s", _blocks()) == "ok"
    usage.set_limits(0, 0)
    assert usage.get_limits() == {"daily_usd": None, "monthly_usd": None}
    assert llm.complete("writer", "s", _blocks()) == "ok"


def test_yesterdays_spend_does_not_count_toward_daily(wired):
    usage.set_limits(1.0, None)
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    _spend(50.0, at=(midnight - timedelta(minutes=1)).astimezone(timezone.utc))
    assert llm.complete("writer", "s", _blocks()) == "ok"


def test_anthropic_kind_is_also_guarded(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "task_config", lambda task: _cfg("anthropic"))
    monkeypatch.setattr(llm, "_call_anthropic", lambda *a: calls.append(1) or "ok")
    usage.set_limits(1.0, None)
    _spend(3.0)
    with pytest.raises(llm.LLMError):
        llm.complete("writer", "s", _blocks())
    assert calls == []


def test_complete_json_is_guarded_too(wired):
    usage.set_limits(1.0, None)
    _spend(3.0)
    with pytest.raises(llm.LLMError, match="حد الإنفاق"):
        llm.complete_json("writer", "s", _blocks())
    assert wired.calls == []


def test_limits_persist_in_settings_and_validate(isolated):
    assert usage.set_limits("5", 40) == {"daily_usd": 5.0, "monthly_usd": 40.0}
    assert settings_io.load()["SPEND_LIMITS"] == {"daily_usd": 5.0, "monthly_usd": 40.0}
    with pytest.raises(ValueError):
        usage.set_limits(-1, None)
    with pytest.raises(ValueError):
        usage.set_limits("abc", None)


def test_record_then_block_end_to_end(wired, monkeypatch):
    """تسجيل حقيقي عبر usage.record (مش إدخال يدوي) بيدخل بالحساب."""
    usage.set_limits(0.01, None)
    usage.record("writer", "openai", "gpt-5", 1_000_000, 0)        # ≈ $1.25
    with pytest.raises(llm.LLMError):
        llm.complete("writer", "s", _blocks())


def test_limit_status_shape(wired):
    usage.set_limits(1.0, 10.0)
    _spend(0.5)
    st = usage.limit_status()
    assert st["blocked"] is False and st["spent"]["daily_usd"] == 0.5
    assert st["limits"] == {"daily_usd": 1.0, "monthly_usd": 10.0}
