import json
import sys
import types
from pathlib import Path

import pytest

import llm
import queue_worker
import usage
from tests.phase8_support import (CRMOffline, FakeCRM, hide_module, install_fake_crm, isolated)


@pytest.fixture
def env(isolated, monkeypatch):
    (isolated.products / "kama.json").write_text(
        json.dumps({"product_name": "kama", "product_code": "kama"}, ensure_ascii=False), encoding="utf-8")
    isolated.stage3 = types.ModuleType("stage3_generate")
    isolated.writes = []
    isolated.matches = []

    def write_for_product(product_path, pattern_id=None, *, review=True):
        isolated.writes.append((Path(product_path).name, pattern_id, review))
        out = isolated.lib / "scripts" / f"kama__{len(isolated.writes)}.json"
        out.write_text(json.dumps({
            "title": "عنوان", "hook_line": "هوك", "cta_line": "اطلب", "total_duration_sec": 47,
            "scenes": [{"scene_number": 1, "duration_sec": 6, "visual": "v", "voiceover": "vo",
                        "on_screen_text": "t", "secret_extra": "x"}],
            "_meta": {"script_id": "VP-kama-1-v1", "status": "reviewing", "product": "kama",
                      "pattern_id": pattern_id or "p1"}}, ensure_ascii=False), encoding="utf-8")
        return out

    def match_for_product(product_path):
        isolated.matches.append(Path(product_path).name)
        return {"ranked_patterns": [
            {"pattern_id": f"p{i}", "pattern_name": f"n{i}", "fit_score": 90 - i, "reason": "r",
             "category_distance": "same", "transfer_justification": None, "noise": "x"}
            for i in range(1, 6)], "warnings": ["خيارات محدودة"]}

    isolated.stage3.write_for_product = write_for_product
    isolated.stage3.match_for_product = match_for_product
    monkeypatch.setitem(sys.modules, "stage3_generate", isolated.stage3)
    isolated.mp = monkeypatch
    return isolated


def _crm(env, items):
    client = FakeCRM(items)
    install_fake_crm(env.mp, client)
    return client


def _item(i, typ, payload):
    return {"id": i, "type": typ, "payload": payload}


def test_request_stays_pending_until_executed_and_reply_is_a_draft(env):
    client = _crm(env, [_item("r1", "new_script", {"product_code": "kama", "pattern_id": "pX"})])
    assert client.items["r1"]["status"] == "pending"
    assert queue_worker.pending_count() == 0                      # لسا ما التقطنا

    boom = {"n": 0}
    real = env.stage3.write_for_product

    def flaky(*a, **k):
        boom["n"] += 1
        if boom["n"] == 1:
            raise llm.LLMError("مزوّد الموديل مضغوط")
        return real(*a, **k)
    env.stage3.write_for_product = flaky

    res = queue_worker.poll_once()                                # فشل مؤقت
    assert res["ok"] and res["counts"] == {"retry": 1}
    assert client.results == {}                                   # ما في رد
    assert client.items["r1"]["status"] != "done"                 # بعده بانتظار الجهاز
    assert queue_worker.pending_count() == 1

    res = queue_worker.poll_once()                                # نجح
    assert res["counts"] == {"drafted": 1}
    (body,) = client.results["r1"]
    assert body["status"] == "draft" and set(body) == {"status", "draft"}
    d = body["draft"]
    assert d["kind"] == "script" and d["script_id"] == "VP-kama-1-v1" and d["status"] == "reviewing"
    assert d["scenes"][0]["voiceover"] == "vo" and "secret_extra" not in d["scenes"][0]
    assert env.writes[-1] == ("kama.json", "pX", True)
    assert queue_worker.pending_count() == 0


def test_poll_once_is_idempotent(env):
    client = _crm(env, [_item("a", "best_patterns", {"product_code": "kama"})])
    first = queue_worker.poll_once()
    second = queue_worker.poll_once()
    assert first["counts"] == {"drafted": 1}
    assert second["fetched"] == 0 and second["processed"] == []
    assert client.claims == ["a"] and len(client.results["a"]) == 1
    assert env.matches == ["kama.json"]


@pytest.mark.parametrize("bad_status,outcome", [(503, "offline"), (429, "retry")])
def test_server_keeps_listing_item_after_lost_result_and_we_do_not_recompute(env, bad_status, outcome):
    client = _crm(env, [_item("a", "new_script", {"product_code": "kama"})])
    client.result_status = bad_status                             # الإرسال فشل
    res = queue_worker.poll_once()
    assert res["counts"] == {outcome: 1} and client.results == {}
    assert len(env.writes) == 1
    # المسودة انحفظت محلياً قبل الإرسال
    assert list((env.lib / "queue_results").glob("*.json"))

    client.result_status = 200
    res = queue_worker.poll_once()
    assert res["counts"] == {"reported": 1}
    assert len(env.writes) == 1                                   # ما دفعنا مرتين
    assert len(client.claims) == 1
    assert client.results["a"][0]["status"] == "draft"
    assert list((env.lib / "queue_results").glob("*.json"))       # ما بنحذف شي محلياً


def test_result_conflict_means_settled_elsewhere(env):
    client = _crm(env, [_item("a", "best_patterns", {"product_code": "kama"})])
    client.result_status = 409                                    # حدا تاني حسمه
    res = queue_worker.poll_once()
    assert res["counts"] == {"drafted": 1}
    assert queue_worker.poll_once()["processed"] == []
    assert queue_worker.pending_count() == 0


def test_permanent_failure_is_reported_as_failed_with_reason(env):
    client = _crm(env, [_item("x", "new_script", {"product_code": "ghost"}),
                        _item("y", "unknown_type", {}),
                        _item("z", "extract_ad_features", {"url": "http://192.168.1.5/v.mp4"})])
    res = queue_worker.poll_once()
    assert res["counts"] == {"failed": 3}
    for i in "xyz":
        (body,) = client.results[i]
        assert body["status"] == "failed" and body["reason"]
    assert "مش موجود" in client.results["x"][0]["reason"]
    assert env.writes == []
    assert queue_worker.pending_count() == 0
    assert queue_worker.poll_once()["fetched"] == 0
    assert len(client.results["x"]) == 1


def test_transient_failure_retries_then_gives_up_after_max_attempts(env, monkeypatch):
    client = _crm(env, [_item("t", "new_script", {"product_code": "kama"})])

    def down(*a, **k):
        raise llm.LLMError("انقطع الاتصال بالمزوّد")
    env.stage3.write_for_product = down
    for n in (1, 2):
        res = queue_worker.poll_once()
        assert res["counts"] == {"retry": 1} and client.results == {}
        assert queue_worker.local_view()["items"][0]["attempts"] == n
    res = queue_worker.poll_once()                                # المحاولة الثالثة = آخر واحدة
    assert res["counts"] == {"failed": 1}
    (body,) = client.results["t"]
    assert body["status"] == "failed" and "3 محاولات" in body["reason"]


def test_spend_limit_is_transient_without_burning_attempts_and_stops_batch(env):
    client = _crm(env, [_item("a", "new_script", {"product_code": "kama"}),
                        _item("b", "new_script", {"product_code": "kama"})])
    usage.set_limits(1.0, None)
    usage.record("writer", "openai", "gpt-5", 10_000_000, 0)      # ≈ $12.5

    def blocked(*a, **k):
        llm._enforce_spend_limit()
    env.stage3.write_for_product = blocked
    res = queue_worker.poll_once()
    assert res["counts"] == {"spend_limit": 1}                    # الثاني ما اتجرّب
    assert client.results == {}
    view = {i["id"]: i for i in queue_worker.local_view()["items"]}
    assert view["a"]["attempts"] == 0 and "b" not in view


def test_offline_crm_is_graceful(env):
    client = _crm(env, [_item("a", "new_script", {"product_code": "kama"})])
    client.offline = True
    res = queue_worker.poll_once()
    assert res["ok"] is False and res["offline"] is True
    assert env.writes == []
    client.offline = False
    assert queue_worker.poll_once()["counts"] == {"drafted": 1}


def test_crm_missing_or_unconfigured_skips_without_error(env):
    hide_module(env.mp, "crm")
    res = queue_worker.poll_once()
    assert res["ok"] and res["skipped"]
    install_fake_crm(env.mp, FakeCRM([]), configured=False)
    assert queue_worker.poll_once()["skipped"]


def test_claim_conflict_is_skipped(env):
    client = _crm(env, [_item("a", "new_script", {"product_code": "kama"})])
    client.claim_status = 409
    res = queue_worker.poll_once()
    assert res["counts"] == {"skipped": 1} and env.writes == [] and client.results == {}


def test_best_patterns_returns_top_three_draft(env):
    client = _crm(env, [_item("b", "best_patterns", {"product_file": "kama.json"})])
    queue_worker.poll_once()
    (body,) = client.results["b"]
    d = body["draft"]
    assert body["status"] == "draft" and d["kind"] == "best_patterns"
    assert [p["pattern_id"] for p in d["patterns"]] == ["p1", "p2", "p3"]
    assert all("noise" not in p for p in d["patterns"])
    assert d["warnings"] == ["خيارات محدودة"]


def test_product_file_path_traversal_is_refused(env):
    client = _crm(env, [_item("b", "best_patterns", {"product_file": "../settings.json"})])
    queue_worker.poll_once()
    assert client.results["b"][0]["status"] == "failed"
    assert env.matches == []


def test_extract_ad_features_returns_pattern_summary_without_raw_text(env):
    (env.lib / "patterns").mkdir(exist_ok=True)
    s1, s2 = types.ModuleType("stage1_extract"), types.ModuleType("stage2_pattern")
    seen = {}

    def process(url, video_id=None, force=False):
        seen["url"], seen["vid"] = url, video_id
        return env.lib / "raw" / video_id / "extract.json"

    def mine(extract_path):
        out = env.lib / "patterns" / f"{extract_path.parent.name}.pattern.json"
        out.write_text(json.dumps({
            "pattern_name": "نمط جديد", "framework": "pas", "product_category": "fragrance",
            "hook": {"type": "question", "mechanism": "m", "transferable_template": "t"},
            "scene_blueprint": [{"vo_intent": "RAW_TRANSCRIPT_LINE"}],
            "_source": {"video_id": "v", "source": "https://ads.example.com/1", "views": 10}},
            ensure_ascii=False), encoding="utf-8")
        return out

    s1.process, s2.mine = process, mine
    env.mp.setitem(sys.modules, "stage1_extract", s1)
    env.mp.setitem(sys.modules, "stage2_pattern", s2)
    client = _crm(env, [_item("e1", "extract_ad_features", {"url": "https://ads.example.com/watch?v=1"})])
    queue_worker.poll_once()
    (body,) = client.results["e1"]
    assert body["status"] == "draft" and seen["vid"] == "crm_e1"
    d = body["draft"]
    assert d["kind"] == "ad_features" and d["pattern"]["pattern_name"] == "نمط جديد"
    assert "RAW_TRANSCRIPT_LINE" not in json.dumps(d, ensure_ascii=False)


def test_extract_system_exit_counts_as_transient(env):
    s1, s2 = types.ModuleType("stage1_extract"), types.ModuleType("stage2_pattern")

    def process(url, video_id=None, force=False):
        raise SystemExit("[!] فشل التحميل")
    s1.process, s2.mine = process, lambda p: None
    env.mp.setitem(sys.modules, "stage1_extract", s1)
    env.mp.setitem(sys.modules, "stage2_pattern", s2)
    client = _crm(env, [_item("e", "extract_ad_features", {"url": "https://x.example.com/v"})])
    assert queue_worker.poll_once()["counts"] == {"retry": 1}
    assert client.results == {}


def test_max_per_poll_bounds_spend(env):
    client = _crm(env, [_item(f"i{n}", "best_patterns", {"product_code": "kama"}) for n in range(8)])
    res = queue_worker.poll_once()
    assert len(res["processed"]) == 5 and res["pending"] == 3
    assert queue_worker.pending_count() == 3
    queue_worker.poll_once()
    assert len(client.results) == 8


def test_replies_never_carry_publish_or_spend_actions(env):
    client = _crm(env, [_item("a", "new_script", {"product_code": "kama", "publish": True, "budget": 500})])
    queue_worker.poll_once()
    blob = json.dumps(client.results["a"], ensure_ascii=False)
    assert "budget" not in blob and '"publish"' not in blob
    assert client.results["a"][0]["status"] == "draft"


def test_state_never_holds_payload_or_keys(env):
    _crm(env, [_item("a", "new_script", {"product_code": "kama", "customer_phone": "0791234567"})])
    queue_worker.poll_once()
    state_text = (env.lib / "queue_state.json").read_text(encoding="utf-8")
    assert "0791234567" not in state_text


class _HTTP:
    """requests.request وهمي بيقلّد سيرفر الـ CRM بعقد CRM_CONTRACT_QUEUE.md."""

    def __init__(self):
        self.calls = []
        self.queue = [{"id": "q1", "type": "best_patterns", "payload": {"product_code": "kama"}}]
        self.claim_code = 200
        self.result_code = 200

    def __call__(self, method, url, headers=None, timeout=None, allow_redirects=None, **kw):
        self.calls.append((method, url, kw.get("json"), (headers or {}).get("Authorization")))

        class R:
            def __init__(s, code, data):
                s.status_code, s._d = code, data

            def json(s):
                return s._d
        if method == "GET":
            return R(200, {"items": self.queue})
        if url.endswith("/claim"):
            return R(self.claim_code, {})
        if url.endswith("/result"):
            return R(self.result_code, {})
        return R(404, {})


def _real_crm(env, monkeypatch):
    crm = pytest.importorskip("crm")
    from tests.phase8_support import FAKE_CRM_TOKEN
    import secrets_store, settings_io
    monkeypatch.delitem(sys.modules, "crm", raising=False)
    import importlib
    crm = importlib.import_module("crm")
    secrets_store.set_secret("crm_token", FAKE_CRM_TOKEN)
    settings_io.update(lambda s: s.__setitem__("CRM", {"base_url": "https://crm.example.com"}))
    http = _HTTP()
    monkeypatch.setattr(crm.requests, "request", http)
    return crm, http


def test_works_with_the_real_crm_client_interface(env, monkeypatch):
    from tests.phase8_support import FAKE_CRM_TOKEN
    crm, http = _real_crm(env, monkeypatch)
    res = queue_worker.poll_once()
    assert res["ok"] and res["counts"] == {"drafted": 1}
    methods = [(m, u) for m, u, _, _ in http.calls]
    assert methods == [("GET", "https://crm.example.com/api/vidpattern/queue"),
                       ("POST", "https://crm.example.com/api/vidpattern/queue/q1/claim"),
                       ("POST", "https://crm.example.com/api/vidpattern/queue/q1/result")]
    assert all(a == f"Bearer {FAKE_CRM_TOKEN}" for *_, a in http.calls)
    assert http.calls[-1][2]["status"] == "draft"


def test_real_client_409_on_claim_is_skipped_and_5xx_is_offline(env, monkeypatch):
    crm, http = _real_crm(env, monkeypatch)
    http.claim_code = 409
    assert queue_worker.poll_once()["counts"] == {"skipped": 1}
    http.claim_code = 503
    res = queue_worker.poll_once()
    assert res["ok"] is False and res["offline"] is True
    http.claim_code = 200
    assert queue_worker.poll_once()["counts"] == {"drafted": 1}


def test_real_client_bad_token_is_a_clean_error(env, monkeypatch):
    crm, http = _real_crm(env, monkeypatch)
    real = http.__call__

    def denied(method, url, **kw):
        http.calls.append((method, url, None, None))
        return type("R", (), {"status_code": 401, "json": lambda s: {}})()
    monkeypatch.setattr(crm.requests, "request", denied)
    res = queue_worker.poll_once()
    assert res["ok"] is False and "التوكن" in res["error"] and not res.get("offline")
