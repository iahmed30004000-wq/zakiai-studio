import json

import pytest

import evidence
import performance
from vp_b1_helpers import TODAY, ad, day, install_env, load_rows, perf_row, seed_market


@pytest.fixture
def env(tmp_path, monkeypatch):
    return install_env(tmp_path, monkeypatch)


def verdicts_by_number(env, v):
    return {int(k.split("__")[-1].split("v")[0]): x for k, x in v.items()}


def test_performance_is_linked_to_script_and_pattern(env):
    env.pattern("pat_a", name="نمط أ")
    files = seed_market(env, "kama", [(1, "pat_a", 3.0, 50), (2, "pat_a", 3.0, 50), (3, "pat_b", 6.0, 40)])
    v = evidence.script_verdicts(TODAY)
    f1 = next(f for f in files if "__1v" in f)
    assert v[f1]["delivered"] == 50 and v[f1]["pattern_id"] == "pat_a" and v[f1]["script_id"] == "VP-kama-1-v1"
    pe = evidence.pattern_evidence(TODAY)
    assert pe["pat_a"]["delivered"] == 100 and pe["pat_a"]["scripts"] == 2 and pe["pat_a"]["name"] == "نمط أ"
    assert pe["pat_a"]["cost_per_delivered"] == 3.0


def test_verdicts_relative_to_product_country_median_baseline(env):
    seed_market(env, "kama", [(1, "a", 2.0, 40), (2, "b", 4.0, 40), (3, "c", 4.4, 40), (4, "d", 8.0, 40)])
    v = verdicts_by_number(env, evidence.script_verdicts(TODAY))
    # الوسيط = (4.0 + 4.4) / 2 = 4.2
    assert v[1]["verdict"] == "winner" and v[2]["verdict"] == "ok" and v[3]["verdict"] == "ok"
    assert v[4]["verdict"] == "loser"
    assert v[1]["baseline_cpd"] == 4.2 and "أرخص" in v[1]["reason"] and "%" in v[1]["reason"]
    assert "أغلى" in v[4]["reason"]


def test_no_verdict_under_min_delivered(env):
    seed_market(env, "kama", [(1, "a", 1.0, 19), (2, "b", 4.0, 40), (3, "c", 4.0, 40), (4, "d", 4.0, 40)])
    v = verdicts_by_number(env, evidence.script_verdicts(TODAY))
    assert v[1]["verdict"] == "insufficient" and "19" in v[1]["reason"] and "20" in v[1]["reason"]
    # بالحد بالضبط بيصير في حكم
    seed_market(env, "vara", [(1, "a", 1.0, 20), (2, "b", 4.0, 40), (3, "c", 4.0, 40)])
    v = evidence.script_verdicts(TODAY)
    assert next(x for x in v.values() if x["script_id"] == "VP-vara-1-v1")["verdict"] == "winner"


def test_baseline_needs_enough_scripts_and_same_country(env):
    seed_market(env, "kama", [(1, "a", 2.0, 40), (2, "b", 8.0, 40)])          # سيناريوهان بس
    v = evidence.script_verdicts(TODAY)
    assert all(x["verdict"] == "insufficient" and "خط أساس" in x["reason"] for x in v.values())

    # نفس المنتج ببلد تاني ما بيدخل بأساس سوريا
    seed_market(env, "kama", [(3, "c", 4.0, 40), (4, "d", 4.0, 40)], country="SA")
    v = evidence.script_verdicts(TODAY)
    assert all(x["verdict"] == "insufficient" for x in v.values())


def test_script_without_data_and_legacy_script_without_id(env):
    env.script("kama", 1, "a")
    env.script("kama", 2, "a", with_id=False)
    v = evidence.script_verdicts(TODAY)
    assert len(v) == 1                                   # اللي بلا script_id بره
    only = next(iter(v.values()))
    assert only["verdict"] == "insufficient" and only["delivered"] == 0


def test_non_vp_ad_is_out_of_evidence(env):
    seed_market(env, "kama", [(1, "a", 3.0, 50), (2, "b", 3.0, 50), (3, "c", 3.0, 50)])
    load_rows([perf_row("SY|kama|DawaCare|video", day(-10), delivered=500, cpd=0.1)])
    pe = evidence.pattern_evidence(TODAY)
    assert sum(e["delivered"] for e in pe.values()) == 150


def test_pattern_without_performance_is_unproven(env):
    env.pattern("lonely", reusability=10)
    pe = evidence.pattern_evidence(TODAY)
    assert pe["lonely"]["evidence_level"] == "unproven" and pe["lonely"]["evidence_score"] == 0
    assert "غير مثبت" in pe["lonely"]["reason"]


def test_levels_unproven_weak_proven(env):
    for p in ("p_small", "p_one", "p_good", "p_bad"):
        env.pattern(p)
    seed_market(env, "kama", [
        (1, "p_small", 2.0, 15),           # تحت الحد
        (2, "p_one", 2.0, 70),             # حجم كافي بس سيناريو واحد
        (3, "p_good", 2.0, 40), (4, "p_good", 2.0, 40),
        (5, "p_bad", 8.0, 40), (6, "p_bad", 8.0, 40), (7, "x", 4.0, 40), (8, "y", 4.0, 40)])
    pe = evidence.pattern_evidence(TODAY)
    assert pe["p_small"]["evidence_level"] == "unproven"
    assert pe["p_one"]["evidence_level"] == "weak" and "سيناريو واحد" in pe["p_one"]["reason"]
    assert pe["p_good"]["evidence_level"] == "proven" and pe["p_good"]["cost_vs_baseline"] < 1
    assert pe["p_bad"]["evidence_level"] == "weak" and "أغلى" in pe["p_bad"]["reason"]
    assert pe["p_good"]["evidence_score"] > pe["p_bad"]["evidence_score"]


def test_evidence_score_formula_sample_saturation_and_efficiency(env):
    env.pattern("half")
    env.pattern("half_big")
    seed_market(env, "kama", [(1, "half", 2.0, 60), (2, "half_big", 2.0, 300), (3, "z", 4.0, 60),
                              (4, "z2", 4.0, 60), (5, "z3", 4.0, 60)])
    pe = evidence.pattern_evidence(TODAY)
    # الوسيط 4.0 → rel = 0.5 → كفاءة 100؛ العيّنة 1-e^(-n/100)
    assert pe["half"]["cost_vs_baseline"] == 0.5
    assert pe["half"]["evidence_score"] == round(100 * (1 - 2.718281828 ** -0.6))
    assert pe["half_big"]["evidence_score"] > pe["half"]["evidence_score"]
    assert pe["half_big"]["evidence_score"] <= 100


def test_ranking_follows_evidence_not_model_opinion(env):
    env.pattern("hyped", reusability=10)
    env.pattern("quiet", reusability=2)
    env.pattern("zero", reusability=9)
    seed_market(env, "kama", [(1, "quiet", 2.0, 80), (2, "quiet", 2.0, 80),
                              (3, "hyped", 8.0, 80), (4, "hyped", 8.0, 80), (5, "m", 4.0, 60), (6, "n", 4.0, 60)])
    ranked = [e["pattern_id"] for e in evidence.ranked_patterns(TODAY)]
    assert ranked.index("quiet") < ranked.index("hyped") < ranked.index("zero") or \
        ranked.index("quiet") < ranked.index("zero")
    assert ranked[0] == "quiet"
    top = evidence.ranked_patterns(TODAY)[0]
    assert top["reusability_opinion"] == 2

    board = performance.pattern_scoreboard()
    assert list(board)[0] == "quiet"
    q = board["quiet"]
    for legacy in ("winner", "ok", "loser", "untested", "win_rate", "roas", "judged", "scripts",
                   "total_revenue", "total_spend"):
        assert legacy in q                                # المطابقة القديمة بتقراها
    assert q["delivered"] == 160 and q["evidence_level"] and q["cost_per_delivered"] == 2.0
    assert q["reusability_opinion"] == 2 and "zero" not in board


def test_scoreboard_keeps_manual_marks_when_no_crm(env):
    env.pattern("old")
    f, _ = env.script("kama", 1, "old")
    performance.mark(f, "winner", {"revenue": 100, "spend": 40})
    b = performance.pattern_scoreboard()["old"]
    assert b["winner"] == 1 and b["win_rate"] == 1.0 and b["roas"] == 2.5
    assert b["evidence_level"] == "unproven" and b["delivered"] == 0


def test_immature_days_are_excluded(env, monkeypatch):
    monkeypatch.setattr(evidence.config, "PERF_MATURITY_DAYS", 3)
    env.script("kama", 1, "a")
    sid = "VP-kama-1-v1"
    load_rows([perf_row(ad("kama", sid), day(-5), delivered=30, cpd=3.0),
               perf_row(ad("kama", sid), day(-1), delivered=200, cpd=1.0)])       # يوم لسا ما نضج
    v = next(iter(evidence.script_verdicts(TODAY).values()))
    assert v["delivered"] == 30 and v["last_date"] == day(-5)


def test_offline_data_is_stamped_with_last_sync(env):
    seed_market(env, "kama", [(1, "a", 3.0, 30)])
    assert next(iter(evidence.script_verdicts(TODAY).values()))["as_of"] is None   # ما في مزامنة بعد
    import crm
    crm._write_json(crm._state_path(), {"last_success": "2026-09-27T10:00:00+03:00"})
    assert next(iter(evidence.script_verdicts(TODAY).values()))["as_of"] == "2026-09-27T10:00:00+03:00"


def test_scoreboard_stays_compatible_with_stage3_match_summary(env):
    import stage3_generate
    env.pattern("quiet")
    seed_market(env, "kama", [(1, "quiet", 2.0, 80), (2, "quiet", 2.0, 80), (3, "m", 4.0, 60), (4, "n", 4.0, 60)])
    board = performance.pattern_scoreboard()
    p = {"_pattern_id": "quiet", "pattern_name": "quiet", "framework": "pas"}
    yr = stage3_generate.summarize(p, board)["your_results"]
    assert set(yr) == {"winners", "ok", "losers", "win_rate", "roas"}
    assert yr["winners"] + yr["ok"] + yr["losers"] == 2


# ───────────────────────── نسخ الهوك: مجموعة وحدة ─────────────────────────
def hook_version(env, base_sid, number, hid, *, code="kama", pattern="pat_a"):
    """سيناريو نسخة هوك: نفس رقم الأساسي ومعرّفه بـ -hN، وبالـ _meta الربط hook_of."""
    sid = f"{base_sid}-{hid}"
    meta = {"product": code, "product_file": f"{code}.json", "product_code": code, "number": number, "version": 1,
            "pattern_id": pattern, "status": "approved", "script_id": sid,
            "hook_of": {"base": f"{code}__{pattern}__{number}v1", "base_script_id": base_sid, "hook_id": hid}}
    s = {"title": f"نسخة {hid}", "hook_line": "هوك", "scenes": [{"scene_number": 1, "duration_sec": 7, "voiceover": "..."}], "_meta": meta}
    (env.scripts / f"{code}__{pattern}__{number}v1__{hid}.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return sid


def test_hook_versions_are_one_sample_for_the_baseline_and_one_script_for_the_pattern(env):
    env.pattern("pat_a")
    seed_market(env, "kama", [(1, "pat_a", 3.0, 30), (2, "x", 4.0, 40), (3, "y", 5.0, 40)])
    s2, s3 = hook_version(env, "VP-kama-1-v1", 1, "h2"), hook_version(env, "VP-kama-1-v1", 1, "h3")
    load_rows([perf_row(ad("kama", s2), day(-10), delivered=30, cpd=2.0), perf_row(ad("kama", s3), day(-10), delivered=30, cpd=4.0)])
    v = evidence.script_verdicts(TODAY)
    assert len(v) == 5 and {x["script_id"] for x in v.values()} >= {"VP-kama-1-v1", s2, s3}
    # المجموعة 1 مجموعة: (90 + 60 + 120) ÷ 90 = 3.0؛ الوسيط بين 3.0 و4.0 و5.0 = 4.0 (مش 3.0 لو انحسبوا 5 عيّنات)
    assert {x["baseline_cpd"] for x in v.values()} == {4.0}
    pe = evidence.pattern_evidence(TODAY)
    assert pe["pat_a"]["scripts"] == 1 and pe["pat_a"]["scripts_total"] == 3 and pe["pat_a"]["delivered"] == 90
    assert pe["pat_a"]["cost_per_delivered"] == 3.0
    assert all(x["group"] == "VP-kama-1-v1" for x in v.values() if x["script_id"] in ("VP-kama-1-v1", s2, s3))


def test_a_group_without_hook_versions_behaves_exactly_as_before(env):
    seed_market(env, "kama", [(1, "a", 2.0, 40), (2, "b", 4.0, 40), (3, "c", 4.4, 40), (4, "d", 8.0, 40)])
    v = verdicts_by_number(env, evidence.script_verdicts(TODAY))
    assert v[1]["baseline_cpd"] == 4.2 and v[1]["group"] == "VP-kama-1-v1" and v[4]["verdict"] == "loser"
