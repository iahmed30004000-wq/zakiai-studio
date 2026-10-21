"""الأنماط بالعربي عند كل القرّاء: المطابقة، الكاتب، المراجع، لوحة الأداء، وواجهات الويب (الأصل الإنجليزي بيضل للبصمة بس)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_brief, make_pattern  # noqa: E402,F401

import clusters  # noqa: E402,F401
import evidence  # noqa: E402
import pattern_store  # noqa: E402
import pattern_text as pt  # noqa: E402
import review_queue  # noqa: E402
import review_script  # noqa: E402
import stage3_generate  # noqa: E402

AR = {
    "pattern_name": "كشف الطبقات ببطء", "one_line_summary": "ملخص عربي", "target_audience": "جمهور عربي",
    "hook": {"type": "سؤال صادم"}, "proof_mechanism": "إثبات عربي", "why_it_works": ["سبب عربي"],
    "best_for": ["عطور"], "emotional_arc": ["فضول", "ترقّب"],
}


def seed(env, pid="p1", translated=True, **over):
    p = make_pattern(name="The Sensory Layer Reveal", **over)
    p.update({"one_line_summary": "English summary", "proof_mechanism": "English proof", "why_it_works": ["english reason"],
              "best_for": ["fragrance"], "emotional_arc": ["curiosity"], "target_audience": "English audience",
              "hook": {"type": "shock question"}, "cluster_id": "cl_001", "cluster_role": "primary",
              "_source": {"type": "mined", "views": 1234}, "_legacy": {"framework": "PAS"}})
    if translated:
        p["ar"] = json.loads(json.dumps(AR))
    (env.patterns / f"{pid}.pattern.json").write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def lib(env, monkeypatch):
    monkeypatch.setattr(review_queue, "QUEUE_PATH", env.root / "rq.json")
    return env


# ═════════════════ المطابقة ═════════════════
def test_match_summary_is_arabic_and_falls_back_to_english_when_untranslated(lib):
    seed(lib, "p1")
    seed(lib, "p2", translated=False)
    ps = {p["_pattern_id"]: p for p in stage3_generate.load_patterns()}
    a, e = stage3_generate.summarize(ps["p1"]), stage3_generate.summarize(ps["p2"])
    assert (a["pattern_name"], a["hook_type"], a["audience"], a["proof_type"]) == ("كشف الطبقات ببطء", "سؤال صادم", "جمهور عربي", "إثبات عربي")
    assert a["why_it_works"] == ["سبب عربي"] and a["best_for"] == ["عطور"] and a["emotional_arc"] == ["فضول", "ترقّب"]
    assert (e["pattern_name"], e["hook_type"], e["proof_type"]) == ("The Sensory Layer Reveal", "shock question", "English proof")
    assert a["framework"] == e["framework"] == "pas"                    # القيم المغلقة ما بتتغيّر


def test_the_model_sees_the_arabic_library_and_names_come_back_from_the_library(lib):
    seed(lib, "p1")
    lib.product("testp.json", category="eye_care")
    lib.fake.queue("match", {"product_read": {}, "ranked_patterns": [
        {"rank": 1, "pattern_id": "p1", "pattern_name": "name the model made up", "fit_score": 80, "reason": "سبب", "required_adaptation": "تكييف", "risk": "x"}],
        "not_recommended": [], "asset_gaps": []})
    res = stage3_generate.match_for_product(lib.products / "testp.json")
    sent = lib.fake.user("match")
    assert "كشف الطبقات ببطء" in sent and "The Sensory Layer Reveal" not in sent
    assert res["ranked_patterns"][0]["pattern_name"] == "كشف الطبقات ببطء"


def test_matcher_prompt_asks_for_arabic_free_text_and_keeps_json_keys_english():
    for name in ("prompts/pattern_matcher.txt", "prompts/.defaults/pattern_matcher.txt"):
        txt = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), name), encoding="utf-8").read()
        assert "Output English only" not in txt
        assert "simple, clear Arabic" in txt and "Keys, ids, slugs and enum values stay in English" in txt
        assert "category_distance" in txt                               # النسخة الافتراضية صارت بنفس مستوى الحيّة


# ═════════════════ الكاتب والمراجع ═════════════════
def test_writer_gets_the_arabic_blueprint_without_internal_keys(lib):
    p = seed(lib, "p1")
    p["_pattern_id"] = "p1"
    lib.fake.queue("writer", {"title": "t", "scenes": []})
    stage3_generate.write_script(make_brief(), p, {})
    sent = lib.fake.user("writer").split("## PATTERN TO APPLY (full blueprint)\n", 1)[1].split("## ALREADY USED", 1)[0]
    got = json.loads(sent)
    assert got["pattern_name"] == "كشف الطبقات ببطء" and got["hook"]["type"] == "سؤال صادم"
    assert got["framework"] == "pas" and len(got["scene_blueprint"]) == 7
    assert not [k for k in got if k.startswith("_") or k.startswith("cluster_")] and "ar" not in got


def test_reviewer_context_is_arabic_and_finds_archived_patterns(lib):
    seed(lib, "p1")
    _, pat = review_script.load_context({"_meta": {"pattern_id": "p1"}})
    assert pat["pattern_name"] == "كشف الطبقات ببطء" and "_source" not in pat and "ar" not in pat
    pattern_store.archive("p1", by="test")
    _, pat = review_script.load_context({"_meta": {"pattern_id": "p1"}})
    assert pat["pattern_name"] == "كشف الطبقات ببطء"                  # سيناريو قديم مبني على نمط مؤرشف لسا بينراجع
    assert review_script.load_context({"_meta": {"pattern_id": "nope"}})[1] == {}


def test_rewrite_still_finds_an_archived_pattern_and_sends_it_in_arabic(lib):
    seed(lib, "p1")
    pattern_store.archive("p1", by="test")
    meta = {"pattern_id": "p1", "product": "TESTP", "product_file": "testp.json"}
    path = lib.script_file("s.json", {"hook_line": "x", "scenes": []}, meta=meta)
    lib.product("testp.json")

    def stop(call):
        raise RuntimeError("reached the writer")

    lib.fake.queue("writer", stop)
    with pytest.raises(RuntimeError, match="reached the writer"):
        stage3_generate.rewrite_from_review(path, {"verdict": "revise", "findings": []})
    assert "كشف الطبقات ببطء" in lib.fake.user("writer")


# ═════════════════ الأداء والعناقيد ═════════════════
def test_performance_board_names_use_the_arabic_display_name(lib, monkeypatch):
    seed(lib, "p1")
    monkeypatch.setattr(evidence.crm, "data_as_of", lambda: "2026-10-21")
    assert evidence.pattern_evidence(verdicts={})["p1"]["name"] == "كشف الطبقات ببطء"


def test_cluster_index_carries_the_display_name(lib):
    seed(lib, "p1")
    clusters.apply()
    assert json.loads((lib.lib / "clusters.json").read_text(encoding="utf-8"))["clusters"][0]["primary_name"] == "كشف الطبقات ببطء"


# ═════════════════ واجهات الويب ═════════════════
@pytest.fixture
def client(lib):
    from fastapi.testclient import TestClient
    from web.app import app
    return TestClient(app)


def test_pattern_list_rows_are_arabic(client, lib):
    seed(lib, "p1")
    seed(lib, "p2", translated=False)
    p1 = json.loads((lib.patterns / "p1.pattern.json").read_text(encoding="utf-8"))
    p1["_similar_to"] = [{"pattern_id": "p2", "pattern_name": "stale english name", "is_duplicate": True}]
    (lib.patterns / "p1.pattern.json").write_text(json.dumps(p1, ensure_ascii=False), encoding="utf-8")
    rows = {r["id"]: r for r in client.get("/api/patterns").json()}
    a, e = rows["p1"], rows["p2"]
    assert (a["name"], a["summary"], a["hook_type"], a["proof"]) == ("كشف الطبقات ببطء", "ملخص عربي", "سؤال صادم", "إثبات عربي")
    assert e["name"] == "The Sensory Layer Reveal" and e["summary"] == "English summary"       # لسا ما اتترجم ← الأصل
    assert a["duplicate_of"] == "The Sensory Layer Reveal"                                        # اسم المكتبة الحالي مش القديم المخزّن
    assert a["framework"] and a["framework"] != "pas"                                             # تسمية عربية للقيمة المغلقة


def test_pattern_detail_is_localized_and_serves_archived_ones(client, lib):
    seed(lib, "p1")
    d = client.get("/api/patterns/p1").json()
    assert d["pattern_name"] == "كشف الطبقات ببطء" and d["hook"]["type"] == "سؤال صادم" and "ar" not in d
    assert d["_archived"] is False and d["_source"]["type"] == "mined"
    pattern_store.archive("p1", by="test")
    d = client.get("/api/patterns/p1").json()
    assert d["_archived"] is True and d["pattern_name"] == "كشف الطبقات ببطء"
    assert client.get("/api/patterns/nope").status_code == 404
    assert client.get("/api/patterns/..%2Fsecret").status_code == 404


def test_duplicates_endpoint_names_are_arabic(client, lib):
    seed(lib, "p1")
    seed(lib, "p2")
    pairs = client.get("/api/duplicates").json()
    assert pairs and pairs[0]["a"]["name"] == "كشف الطبقات ببطء" and pairs[0]["b"]["name"] == "كشف الطبقات ببطء"


def test_review_queue_items_carry_the_arabic_name_and_the_translated_original(client, lib):
    p = seed(lib, "p1")
    p["ar"]["_legacy"] = {"framework": "كشف الطبقات | عرض عملي"}
    (lib.patterns / "p1.pattern.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    review_queue.add("framework", "p1", "Layer Reveal | Demo", ["demo_proof"])
    review_queue.add("dialect", "p1", "weird dialect", [])
    review_queue.add("country", "product:kama", "السوق العربي", [])
    items = {i["kind"]: i for i in client.get("/api/review-queue").json()["items"]}
    assert items["framework"]["pattern_name"] == "كشف الطبقات ببطء" and items["framework"]["raw_ar"] == "كشف الطبقات | عرض عملي"
    assert items["framework"]["raw"] == "Layer Reveal | Demo"                           # الأصل ما بينشال
    assert items["dialect"]["pattern_name"] == "كشف الطبقات ببطء" and "raw_ar" not in items["dialect"]   # لسا ما اتترجم
    assert "pattern_name" not in items["country"] and "raw_ar" not in items["country"]   # بند منتج مش نمط
