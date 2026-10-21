"""المرحلة 3 — توازن المكتبة، خطة الحصاد وطابور المرشّحين، المطابقة الواعية بالفئة."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, api_client, make_script, review_ok  # noqa: E402

import config  # noqa: E402
import harvest_plan  # noqa: E402
import library_stats  # noqa: E402
import stage3_generate  # noqa: E402
import taxonomy  # noqa: E402


def ranked(*rows):
    """رد مطابقة مزيّف: rows = (pattern_id, fit_score, transfer_justification)."""
    return {
        "product_read": {},
        "ranked_patterns": [
            {"rank": i, "pattern_id": pid, "pattern_name": pid, "fit_score": fit,
             "reason": "r", "required_adaptation": "a", "risk": "x",
             **({"transfer_justification": tj} if tj is not None else {})}
            for i, (pid, fit, tj) in enumerate(rows, 1)],
        "not_recommended": [], "asset_gaps": [],
    }


def user_library(env):
    txt = env.fake.user("match").split("## PATTERN LIBRARY\n", 1)[1]
    return json.loads(txt)


# ─────────────────────── توازن المكتبة ───────────────────────


def seed_library(env, fragrance=12, eye=3, variants=3):
    env.product("perfume.json", product_name="PERF", product_code="perf", category="fragrance")
    env.product("drops.json", category="eye_care")
    (env.products / "_template.json").write_text(json.dumps({"category": "gadgets"}), encoding="utf-8")
    for i in range(fragrance):
        env.pattern(f"f{i}", category="fragrance", framework="pas" if i % 2 else "story")
    for i in range(variants):
        env.pattern(f"fv{i}", category="fragrance", role="variant")
    for i in range(eye):
        env.pattern(f"e{i}", category="eye_care", dialect="msa_simple")


def test_active_categories_from_product_files_skip_template(env):
    seed_library(env)
    assert library_stats.active_categories() == ["eye_care", "fragrance"]


def test_coverage_matrix_quota_and_gaps(env):
    seed_library(env)
    cov = library_stats.coverage()
    assert cov["quota"] == config.LIBRARY_QUOTA == 10
    per = {r["category"]: r for r in cov["per_category"]}
    assert per["fragrance"] == {"category": "fragrance", "label": "عطور", "count": 12,
                                "quota_met": True, "gap": 0}        # النسخ الـ3 ما بتنحسب
    assert per["eye_care"]["count"] == 3 and per["eye_care"]["quota_met"] is False
    assert cov["gaps"] == [{"category": "eye_care", "label": "عناية بالعين", "missing": 7}]
    cell = [m for m in cov["matrix"] if m["category"] == "eye_care"]
    assert cell == [{"category": "eye_care", "framework": "pas", "dialect": "msa_simple", "count": 3}]
    assert sum(m["count"] for m in cov["matrix"]) == 15
    assert cov["variants_not_counted"] == 3


def test_coverage_respects_quota_setting(env, monkeypatch):
    seed_library(env)
    monkeypatch.setattr(config, "LIBRARY_QUOTA", 3)
    cov = library_stats.coverage()
    assert cov["gaps"] == [] and all(r["quota_met"] for r in cov["per_category"])


def test_coverage_endpoint(env):
    seed_library(env)
    d = api_client().get("/api/library/coverage").json()
    assert d["quota"] == 10 and d["active_categories"] == ["eye_care", "fragrance"]
    assert d["gaps"][0]["missing"] == 7


# ─────────────────────── خطة الحصاد ───────────────────────


def test_plan_without_apify_token_gives_manual_plan_no_crash(env):
    seed_library(env)
    plan = harvest_plan.plan_for_category("eye_care", missing=7, have=3)
    assert not plan["apify_configured"]
    assert plan["queries"]["ar"] and plan["queries"]["en"]
    assert all(s.get("commands", []) == [] for s in plan["sources"])
    assert any("APIFY_TOKEN" in m for m in plan["manual_steps"])
    meta = next(s for s in plan["sources"] if s["source"] == "adlibrary")
    assert meta["links"][0]["url"].startswith("https://www.facebook.com/ads/library/")
    assert "country=SY" in meta["links"][0]["url"]            # بلد منتج الفئة
    assert env.jobs == []


def test_every_taxonomy_category_has_queries():
    for slug in taxonomy.CATEGORIES:
        q = harvest_plan.CATEGORY_QUERIES[slug]
        assert q["ar"] and q["en"] and q["hashtags"]


def test_plan_with_token_lists_commands_but_does_not_run(env, monkeypatch):
    seed_library(env)
    monkeypatch.setenv("APIFY_TOKEN", "x")
    plan = harvest_plan.plan_for_category("eye_care")
    cmds = [c for s in plan["sources"] for c in s.get("commands", [])]
    assert cmds and all(c[0] == "stage0_harvest.py" and "--category" in c for c in cmds)
    assert env.jobs == []


def test_plan_endpoint_single_category_and_all_gaps(env):
    seed_library(env)
    c = api_client()
    r = c.post("/api/harvest/plan?category=eye_care").json()
    assert r["category"] == "eye_care" and r["missing"] == 7 and r["have"] == 3
    allp = c.post("/api/harvest/plan").json()
    assert [p["category"] for p in allp["plans"]] == ["eye_care"]
    assert c.post("/api/harvest/plan?category=%D9%85%D8%AC%D9%87%D9%88%D9%84").status_code == 400


def test_plan_run_needs_apify_token(env, monkeypatch):
    seed_library(env)
    c = api_client()
    assert c.post("/api/harvest/plan?category=eye_care&run=true").status_code == 400
    assert env.jobs == []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    r = c.post("/api/harvest/plan?category=eye_care&run=true").json()
    assert r["job_ids"] and env.jobs and all(j["cmd"][0] == "stage0_harvest.py" for j in env.jobs)


# ─────────────────────── طابور المرشّحين ───────────────────────


def test_queue_add_manual_and_validation(env):
    c = api_client()
    r = c.post("/api/harvest/candidates", json={
        "url": "https://www.tiktok.com/@a/video/1", "category": "eye_care", "note": "ملاحظة"})
    item = r.json()["item"]
    assert r.status_code == 200 and item["status"] == "pending" and item["platform"] == "tiktok"
    assert item["category"] == "eye_care" and item["id"].startswith("c_")
    assert c.post("/api/harvest/candidates", json={
        "url": "https://www.tiktok.com/@a/video/1", "category": "eye_care"}).status_code == 409
    assert c.post("/api/harvest/candidates", json={"url": "ftp://x", "category": "eye_care"}).status_code == 400
    assert c.post("/api/harvest/candidates", json={
        "url": "https://x.com/1", "category": "غير_معروفة_تماماً"}).status_code == 400
    assert c.post("/api/harvest/candidates", json={"url": "https://x.com/1"}).status_code == 400
    assert (env.lib / "candidates" / "queue.json").exists()


def test_approve_starts_extract_job_only_after_human_approval(env):
    c = api_client()
    item = c.post("/api/harvest/candidates", json={
        "url": "https://www.facebook.com/ads/library/?id=5", "category": "fragrance"}).json()["item"]
    assert env.jobs == []                                     # المرشّح لحاله ما بيستخرج
    r = c.post(f"/api/harvest/candidates/{item['id']}/approve").json()
    assert r["job_id"] == "job1" and r["item"]["status"] == "approved"
    assert env.jobs == [{"kind": "extract", "label": env.jobs[0]["label"],
                         "cmd": ["stage1_extract.py", "https://www.facebook.com/ads/library/?id=5"]}]
    assert c.post(f"/api/harvest/candidates/{item['id']}/approve").status_code == 409   # مرتين لأ


def test_approved_becomes_extracted_when_job_done(env, monkeypatch):
    from web import jobs
    c = api_client()
    item = c.post("/api/harvest/candidates", json={
        "url": "https://youtu.be/abc", "category": "fragrance"}).json()["item"]
    c.post(f"/api/harvest/candidates/{item['id']}/approve")
    monkeypatch.setattr(jobs, "get_job", lambda jid: {"status": "done"})
    items = c.get("/api/harvest/candidates?status=extracted").json()["items"]
    assert [i["id"] for i in items] == [item["id"]]
    assert c.get("/api/harvest/candidates?status=pending").json()["items"] == []


def test_reject_and_filters(env):
    c = api_client()
    a = c.post("/api/harvest/candidates", json={"url": "https://a.com/1", "category": "fragrance"}).json()["item"]
    b = c.post("/api/harvest/candidates", json={"url": "https://a.com/2", "category": "eye_care"}).json()["item"]
    assert c.post(f"/api/harvest/candidates/{a['id']}/reject").json()["item"]["status"] == "rejected"
    assert c.post(f"/api/harvest/candidates/{a['id']}/approve").status_code == 409   # المرفوض ما بيتوافق
    assert [i["id"] for i in c.get("/api/harvest/candidates?status=pending").json()["items"]] == [b["id"]]
    assert [i["id"] for i in c.get("/api/harvest/candidates?category=fragrance").json()["items"]] == [a["id"]]
    assert c.post("/api/harvest/candidates/c_nope/approve").status_code == 404
    assert c.get("/api/harvest/candidates?status=bogus").status_code == 400
    assert env.jobs == []


def test_add_candidates_from_harvest_dedupes(env):
    res = harvest_plan.add_candidates("fragrance", "tiktok", [
        {"url": "https://t.co/1", "views": 200000, "likes": 5000},
        {"url": "https://t.co/1"}, {"url": ""}], query="عطر")
    assert res == {"added": 1, "skipped": 2}
    assert "مشاهدات" in harvest_plan.list_items()[0]["note"]


# ─────────────────────── المطابقة الواعية بالفئة ───────────────────────


def match_setup(env, same=12):
    env.product()                                        # eye_care
    for i in range(same):
        env.pattern(f"same{i}", category="eye_care")
    env.pattern("adj", category="supplements")           # نفس مجموعة الصحة ← مجاور
    env.pattern("far1", category="fragrance")            # مجموعة التجميل ← بعيد
    env.pattern("far2", category="apparel")


def test_far_without_justification_excluded_with_justification_penalized(env):
    match_setup(env)
    env.fake.queue("match", ranked(
        ("far1", 95, ""), ("far2", 90, "آلية الإثبات بالمقارنة بتنقل لأي منتج بصري"),
        ("same0", 80, None), ("adj", 79, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    ids = [r["pattern_id"] for r in res["ranked_patterns"]]
    assert "far1" not in ids                                  # بلا مبرر ← استُبعد
    assert {"pattern_id": "far1", "why": "فئة بعيدة عن المنتج وبلا مبرر نقل مكتوب"} in res["excluded_patterns"]
    by = {r["pattern_id"]: r for r in res["ranked_patterns"]}
    assert by["far2"]["fit_score"] == 65 and by["far2"]["fit_score_raw"] == 90
    assert by["far2"]["category_distance"] == "far" and by["far2"]["category_penalty"] == 25
    assert by["far2"]["transfer_justification"].startswith("آلية")
    assert by["adj"]["fit_score"] == 74 and by["adj"]["category_distance"] == "adjacent"
    assert by["same0"]["fit_score"] == 80 and by["same0"]["category_distance"] == "same"
    # إعادة الترتيب بعد الخصم: far2 كان الأول بالـ90 وصار الأخير
    assert ids == ["same0", "adj", "far2"]
    assert [r["rank"] for r in res["ranked_patterns"]] == [1, 2, 3]


def test_penalty_values_come_from_config(env, monkeypatch):
    match_setup(env)
    monkeypatch.setattr(config, "FAR_CATEGORY_PENALTY", 40)
    monkeypatch.setattr(config, "ADJACENT_CATEGORY_PENALTY", 10)
    env.fake.queue("match", ranked(("far2", 90, "مبرر كافي"), ("adj", 80, None), ("same0", 60, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    by = {r["pattern_id"]: r["fit_score"] for r in res["ranked_patterns"]}
    assert by == {"far2": 50, "adj": 70, "same0": 60}
    assert [r["pattern_id"] for r in res["ranked_patterns"]] == ["adj", "same0", "far2"]


def test_only_top_three_kept_and_unknown_ids_dropped(env):
    match_setup(env)
    env.fake.queue("match", ranked(("ghost", 99, None), ("same0", 90, None), ("same1", 85, None),
                                   ("same2", 80, None), ("same3", 75, None), ("same4", 70, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    assert [r["pattern_id"] for r in res["ranked_patterns"]] == ["same0", "same1", "same2"]
    assert any(e["pattern_id"] == "ghost" for e in res["excluded_patterns"])


def test_limited_options_warning_below_quota(env):
    match_setup(env, same=3)
    env.fake.queue("match", ranked(("same0", 80, None), ("same1", 70, None), ("same2", 60, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    assert any("خيارات محدودة: 3 من 10" in w for w in res["warnings"])


def test_no_limited_warning_when_quota_met(env):
    match_setup(env, same=10)
    env.fake.queue("match", ranked(("same0", 80, None), ("same1", 70, None), ("same2", 60, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    assert not any("خيارات محدودة" in w for w in res["warnings"])


def test_warning_when_too_few_valid_after_exclusion(env):
    match_setup(env)
    env.fake.queue("match", ranked(("far1", 90, ""), ("same0", 70, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    assert any("بقي 1 أنماط صالحة" in w for w in res["warnings"])


def test_match_runs_on_cluster_primaries_with_copy_counts(env):
    match_setup(env, same=2)
    env.pattern("same0_copy", category="eye_care")
    (env.lib / "clusters.json").write_text(json.dumps({"clusters": [
        {"cluster_id": "cl_001", "primary": "same0", "variants": [{"pattern_id": "same0_copy", "score": 0.7}], "size": 2},
        {"cluster_id": "cl_002", "primary": "same1", "variants": [], "size": 1},
        {"cluster_id": "cl_003", "primary": "adj", "variants": [], "size": 1}]}), encoding="utf-8")
    env.fake.queue("match", ranked(("same0", 80, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    lib = {p["pattern_id"]: p for p in user_library(env)}
    assert "same0_copy" not in lib                             # النسخة ما بتدخل المطابقة
    assert lib["same0"]["cluster_copies"] == 2 and lib["same1"]["cluster_copies"] == 1
    assert "far1" in lib                                       # نمط لسا ما انفهرس ما بينحجب
    assert res["_meta"]["pool_uses_clusters"] is True
    # عدّاد الحصة بيعدّ الأساسية بس: same0 و same1 = 2
    assert any("خيارات محدودة: 2 من 10" in w for w in res["warnings"])


def test_without_cluster_index_all_patterns_are_matched(env):
    match_setup(env, same=2)
    env.fake.queue("match", ranked(("same0", 80, None)))
    res = stage3_generate.match_for_product(env.products / "testp.json")
    assert len(user_library(env)) == 5 and res["_meta"]["pool_uses_clusters"] is False


def test_summary_carries_distance_and_labeled_slugs(env):
    match_setup(env, same=1)
    env.fake.queue("match", ranked(("same0", 80, None)))
    stage3_generate.match_for_product(env.products / "testp.json")
    lib = {p["pattern_id"]: p for p in user_library(env)}
    s = lib["far1"]
    assert s["category_distance"] == "far" and s["product_category"] == "fragrance"
    assert s["category_label"] == "عطور" and s["framework"] == "pas"
    assert s["framework_label"] == taxonomy.FRAMEWORKS["pas"] and s["dialect"] == "shami"
    assert s["dialect_label"] == "شامي"
    assert lib["adj"]["category_distance"] == "adjacent" and lib["same0"]["category_distance"] == "same"


def test_summarize_direct_labels():
    p = {"_pattern_id": "x", "framework": "us_vs_them", "dialect_or_language": "gulf",
         "product_category": "makeup"}
    s = stage3_generate.summarize(p, product_category="skincare")
    assert (s["framework_label"], s["dialect_label"], s["category_label"]) == ("نحن مقابل هم", "خليجي", "مكياج")
    assert s["category_distance"] == "adjacent"


def test_category_filter_works_with_slugs(env):
    match_setup(env, same=2)
    env.fake.queue("match", ranked(("far1", 80, "مبرر")))
    res = stage3_generate.match_for_product(env.products / "testp.json", category="fragrance")
    assert [p["pattern_id"] for p in user_library(env)] == ["far1"]
    assert res["_meta"]["patterns_considered"] == 1


def test_category_filter_legacy_free_text_and_error(env):
    match_setup(env, same=2)
    pats = stage3_generate.load_patterns()
    assert {p["_pattern_id"] for p in stage3_generate.filter_by_category(pats, "perfume")} == {"far1"}
    assert {p["_pattern_id"] for p in stage3_generate.filter_by_category(pats, "عناية بالعين")} == {"same0", "same1"}
    with pytest.raises(stage3_generate.PipelineError) as ei:
        stage3_generate.filter_by_category(pats, "makeup")
    assert "eye_care" in str(ei.value) and "fragrance" in str(ei.value)


def test_match_result_saved_for_ui(env):
    match_setup(env, same=2)
    env.fake.queue("match", ranked(("same0", 80, None)))
    stage3_generate.match_for_product(env.products / "testp.json")
    saved = json.loads((env.lib / "matches" / "testp.json").read_text(encoding="utf-8"))
    assert saved["ranked_patterns"][0]["pattern_id"] == "same0" and "warnings" in saved


def test_match_endpoint(env):
    match_setup(env, same=2)
    env.fake.queue("match", ranked(("far2", 90, "مبرر"), ("same0", 80, None)))
    c = api_client()
    r = c.post("/api/match", json={"product_file": "testp.json"}).json()
    assert [x["pattern_id"] for x in r["ranked_patterns"]] == ["same0", "far2"]
    assert r["ranked_patterns"][1]["category_distance"] == "far" and "warnings" in r
    assert c.post("/api/match", json={"product_file": "nope.json"}).status_code == 404
    assert c.post("/api/match", json={"product_file": "testp.json", "category": "makeup"}).status_code == 422


def test_write_for_product_uses_top_match_when_no_pattern_given(env):
    match_setup(env, same=2)
    env.fake.queue("match", ranked(("far2", 90, "مبرر"), ("same1", 80, None), ("same0", 60, None)))
    env.fake.queue("writer", make_script())
    out = stage3_generate.write_for_product(env.products / "testp.json", review=False)
    meta = json.loads(out.read_text(encoding="utf-8"))["_meta"]
    assert meta["pattern_id"] == "same1"                       # far2 نزل بالخصم (65 < 80)


def test_write_for_product_with_only_unjustified_far_patterns_stops(env):
    match_setup(env, same=1)
    env.fake.queue("match", ranked(("far1", 90, ""), ("far2", 80, "")))
    with pytest.raises(stage3_generate.PipelineError):
        stage3_generate.write_for_product(env.products / "testp.json", review=False)
    assert env.fake.count("writer") == 0


def test_evidence_weighting_fields_still_reach_the_matcher(env):
    match_setup(env, same=1)
    p = json.loads((env.patterns / "same0.pattern.json").read_text(encoding="utf-8"))
    p["_source"] = {"type": "proven", "evidence": "e"}
    p["evidence_strength"] = "قوي"
    (env.patterns / "same0.pattern.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    env.fake.queue("match", ranked(("same0", 80, None)))
    stage3_generate.match_for_product(env.products / "testp.json")
    s = {x["pattern_id"]: x for x in user_library(env)}["same0"]
    assert s["origin"] == "proven" and s["evidence_strength"] == "قوي"
    assert "proven" in env.fake.calls[0]["system"] and "mined" in env.fake.calls[0]["system"]
