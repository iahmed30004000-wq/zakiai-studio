"""شريحة الصرف بالهيدر: GET /api/usage?balances=false لازم يرجّع نفس البيانات بلا ما يسأل المزوّدين عن أرصدتهم."""

import pytest
from fastapi.testclient import TestClient

import llm
import usage
from tests.phase8_support import isolated, sample_settings  # noqa: F401  (fixtures)
import settings_io


@pytest.fixture
def client(isolated, monkeypatch):  # noqa: F811
    """تطبيق الويب الحقيقي، بس بلا شبكة: رصيد المزوّد مرقّم بدل ما ينادى."""
    settings_io.save(sample_settings())
    settings_io._cache["sig"] = None

    calls = []
    monkeypatch.setattr(usage, "provider_balance",
                        lambda provider, key: calls.append(provider) or {"supported": False, "reason": "اختبار"})
    monkeypatch.setattr(llm, "task_config",
                        lambda task: {"provider": "openai", "api_key": "", "model": ""})

    from web.app import app
    usage.record("writer", "openai", "gpt-5", 1000, 500)
    c = TestClient(app)
    c.calls = calls
    return c


def test_bila_arssida_ma_bis2al_3an_el_mozawedin(client):
    """balances=false: ولا نداء شبكة واحد لرصيد المزوّدين."""
    r = client.get("/api/usage?balances=false")
    assert r.status_code == 200
    assert client.calls == [], "ما لازم ينادى أي مزوّد لما balances=false"
    assert "balances" not in r.json(), "الأرصدة ما لازم تكون بالرد لما balances=false"


def test_bila_arssida_ba2i_el_rad_ma_biyitghayar(client):
    """باقي الرد (المجموع، حسب الموديل، حسب المهمة، آخر النداءات) نفسه بالحالتين."""
    bila = client.get("/api/usage?balances=false").json()
    ma3 = client.get("/api/usage?balances=true").json()
    assert client.calls, "لما balances=true لازم يسأل المزوّد"
    assert set(ma3) - set(bila) == {"balances"}, "الفرق الوحيد بين الردّين هو الأرصدة"
    for key, value in bila.items():
        assert ma3[key] == value, f"القيمة '{key}' تغيّرت لما طفّينا الأرصدة"
    assert bila["calls"] == 1 and bila["cost_usd"] > 0, "الاستهلاك المسجّل لازم يبين بالرد"


def test_el_iftiradi_bijib_el_arssida(client):
    """بلا ما تحدّد balances، السلوك القديم نفسه: الأرصدة موجودة."""
    body = client.get("/api/usage").json()
    assert "balances" in body and client.calls == ["openai"]


def test_days_bishtighal_ma3_balances_false(client):
    """days و balances بينشغّلوا سوا."""
    body = client.get("/api/usage?days=7&balances=false").json()
    assert "balances" not in body and client.calls == []
