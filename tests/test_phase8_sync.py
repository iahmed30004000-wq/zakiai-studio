import json
import sys
import types

import pytest

import library_sync
from tests.phase8_support import FakeCRM, hide_module, install_fake_crm, isolated

RAW_TEXT = "RAW_TRANSCRIPT_PRIVATE_TEXT"
PHONE = "0791234567"


def _pattern(ns, name, **extra):
    p = {
        "pattern_name": "نمط " + name, "framework": "pas", "product_category": "fragrance",
        "one_line_summary": "ملخص", "dialect_or_language": "shami",
        "hook": {"type": "question", "duration_sec": 3, "mechanism": "آلية",
                 "transferable_template": "قالب"},
        "scene_blueprint": [{"vo_intent": RAW_TRANSCRIPT_IN_BLUEPRINT}],
        "transcript": RAW_TEXT, "customer_phone": PHONE, "customer_name": "أبو محمد",
        "frames": ["a.jpg"], "video_path": "C:/x/1.mp4",
        "_source": {"video_id": name, "source": "https://ads.example.com/" + name, "views": 500,
                    "likes": 10, "local_path": "C:/secret/local.mp4"},
        "_legacy": {"notes": RAW_TEXT}, "cluster_id": "c1", "cluster_role": "primary",
        **extra,
    }
    (ns.lib / "patterns" / f"{name}.pattern.json").write_text(
        json.dumps(p, ensure_ascii=False), encoding="utf-8")


RAW_TRANSCRIPT_IN_BLUEPRINT = "BLUEPRINT_RAW_LINE"


@pytest.fixture
def env(isolated, monkeypatch):
    _pattern(isolated, "p1")
    _pattern(isolated, "p2")
    isolated.client = FakeCRM()
    install_fake_crm(monkeypatch, isolated.client)
    isolated.mp = monkeypatch
    return isolated


def test_pushes_patterns_without_raw_text_or_customer_data(env):
    res = library_sync.push_if_changed()
    assert res["ok"] and res["pushed"] and res["patterns"] == 2
    (body,) = env.client.library_puts
    blob = json.dumps(body, ensure_ascii=False)
    for forbidden in (RAW_TEXT, RAW_TRANSCRIPT_IN_BLUEPRINT, PHONE, "أبو محمد", "a.jpg",
                      "1.mp4", "local.mp4", "scene_blueprint", "transcript", "frames"):
        assert forbidden not in blob, forbidden
    p = next(x for x in body["patterns"] if x["pattern_id"] == "p1")
    assert p["pattern_name"] == "نمط p1" and p["framework"] == "pas"
    assert p["hook"]["transferable_template"] == "قالب"
    assert p["source"] == {"views": 500, "likes": 10, "url": "https://ads.example.com/p1"}
    assert body["pattern_count"] == 2 and body["content_hash"]


def test_does_not_push_when_unchanged(env):
    assert library_sync.push_if_changed()["pushed"] is True
    again = library_sync.push_if_changed()
    assert again["ok"] and again["pushed"] is False and again["changed"] is False
    assert len(env.client.library_puts) == 1
    assert library_sync.push_if_changed(force=True)["pushed"] is True
    assert len(env.client.library_puts) == 2


def test_pushes_again_after_a_change(env):
    library_sync.push_if_changed()
    _pattern(env, "p3")
    assert library_sync.push_if_changed()["pushed"] is True
    _pattern(env, "p1", pattern_name="اسم جديد")
    assert library_sync.push_if_changed()["pushed"] is True
    assert len(env.client.library_puts) == 3
    assert library_sync.push_if_changed()["pushed"] is False


def test_change_only_in_private_fields_does_not_trigger_push(env):
    library_sync.push_if_changed()
    _pattern(env, "p1", transcript="نص خام مختلف تماماً", customer_phone="0000")
    assert library_sync.push_if_changed()["pushed"] is False


def test_failed_push_is_retried_not_marked_done(env):
    env.client.put_status = 503
    res = library_sync.push_if_changed()
    assert res["ok"] is False and res["pushed"] is False
    env.client.put_status = 200
    assert library_sync.push_if_changed()["pushed"] is True
    assert len(env.client.library_puts) == 1


def test_offline_is_reported_not_raised(env):
    env.client.offline = True
    res = library_sync.push_if_changed()
    assert res["ok"] is False and res["offline"] is True


def test_skips_when_crm_missing_or_not_configured(env):
    hide_module(env.mp, "crm")
    assert library_sync.push_if_changed()["skipped"]
    install_fake_crm(env.mp, env.client, configured=False)
    assert library_sync.push_if_changed()["skipped"]
    assert env.client.library_puts == []


def test_evidence_results_are_included_when_available(env):
    ev = types.ModuleType("evidence")
    ev.pattern_evidence = lambda: {"p1": {"evidence_level": "proven", "evidence_score": 82,
                                          "delivered": 120, "spend": 300.0, "cost_per_delivered": 2.5,
                                          "customer_phone": PHONE, "orders": [{"name": "x"}]}}
    env.mp.setitem(sys.modules, "evidence", ev)
    library_sync.push_if_changed()
    (body,) = env.client.library_puts
    p1 = next(x for x in body["patterns"] if x["pattern_id"] == "p1")
    assert p1["evidence"] == {"evidence_level": "proven", "evidence_score": 82, "delivered": 120,
                              "spend": 300.0, "cost_per_delivered": 2.5}
    blob = json.dumps(body, ensure_ascii=False)
    assert PHONE not in blob and "orders" not in blob


def test_bundle_hash_ignores_timestamps_and_text_is_clipped(env):
    _pattern(env, "big", why_it_works="ن" * 5000)
    b = library_sync.build_bundle()
    big = next(p for p in b["patterns"] if p["pattern_id"] == "big")
    assert len(big["why_it_works"]) <= library_sync.MAX_TEXT_CHARS + 1
    assert library_sync.bundle_hash(b) == library_sync.bundle_hash(library_sync.build_bundle())


def test_state_records_last_push(env):
    library_sync.push_if_changed()
    st = library_sync.status()
    assert st["last_ok"] is True and st["patterns"] == 2 and st["last_hash"]
