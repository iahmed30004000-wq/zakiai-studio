"""المرحلة 2 — سلامة البريف: بوابة الاكتمال، حقن القواعد، المراجعة المحلية، مزامنة الحقائق."""

import json
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import (  # noqa: E402
    env, FakeLLM, api_client, make_script, make_brief, review_ok, future_date, words,
)

import brief as brief_mod  # noqa: E402
import review_script  # noqa: E402
import script_versions  # noqa: E402
import stage3_generate  # noqa: E402


def blockers_of(findings):
    return [f for f in findings if f["severity"] == "blocker"]


def rule_findings(findings):
    return [f for f in findings if f.get("rule")]


# ─────────────────────── بوابة الاكتمال ───────────────────────


def test_incomplete_brief_does_not_write(env):
    env.pattern("p1")
    path = env.product("inc.json", core_promise="", pain_points=[], proof_assets=[])
    with pytest.raises(brief_mod.BriefIncomplete) as ei:
        stage3_generate.write_for_product(path, "p1", review=False)
    msg = str(ei.value)
    assert "البريف ناقص" in msg and "الوعد الأساسي" in msg and "نقاط الألم" in msg
    assert env.fake.calls == []                       # ولا نداء موديل
    assert list(env.scripts.glob("*")) == []          # ولا ملف


def test_incomplete_brief_cli_exits_with_arabic_message(env, monkeypatch, capsys):
    env.pattern("p1")
    path = env.product("inc.json", features=[])
    monkeypatch.setattr(sys, "argv", ["stage3_generate.py", str(path), "--pattern", "p1"])
    with pytest.raises(SystemExit) as ei:
        stage3_generate.main()
    assert "البريف ناقص" in str(ei.value.code) and "مميزات المنتج" in str(ei.value.code)
    assert env.fake.calls == []


def test_no_force_flag_exists(env, monkeypatch):
    env.pattern("p1")
    path = env.product("inc.json", features=[])
    monkeypatch.setattr(sys, "argv", ["stage3_generate.py", str(path), "--pattern", "p1", "--force"])
    with pytest.raises(SystemExit):                  # argparse بيرفض العلم غير المعروف
        stage3_generate.main()
    assert env.fake.calls == []


def test_complete_brief_writes_and_injects_hard_rules(env):
    env.pattern("p1")
    path = env.product()
    env.fake.queue("writer", make_script())
    out = stage3_generate.write_for_product(path, "p1", review=False)
    assert out.exists()
    user = env.fake.user("writer")
    assert "## HARD RULES FROM BRIEF" in user
    rules_txt = user.split("## HARD RULES FROM BRIEF", 1)[1].split("## PATTERN TO APPLY", 1)[0]
    assert '"scarcity_allowed": false' in rules_txt
    assert '"offer_allowed_in_cta": false' in rules_txt
    assert '"market_accusations_allowed": false' in rules_txt
    assert "شفاء" in rules_txt                       # forbidden_claims_effective من مكتبة الفئة الصحية
    assert "_provenance" not in user.split("## HARD RULES")[0]     # الحقول الداخلية ما بتروح للموديل


def test_writer_rules_reflect_scarcity_and_offer(env):
    env.pattern("p1")
    path = env.product(no_offer=False, offer="قطعتين بسعر مخفّض", scarcity_deadline=future_date())
    env.fake.queue("writer", make_script())
    stage3_generate.write_for_product(path, "p1", review=False)
    rules_txt = env.fake.user("writer").split("## HARD RULES FROM BRIEF", 1)[1]
    assert '"scarcity_allowed": true' in rules_txt
    assert '"offer_allowed_in_cta": true' in rules_txt


def test_prompts_keep_variables_and_know_the_rules():
    root = Path(__file__).resolve().parent.parent / "prompts"
    w = (root / "script_writer.txt").read_text(encoding="utf-8")
    r = (root / "script_reviewer.txt").read_text(encoding="utf-8")
    for var in ("{{SCENES}}", "{{MIN_SEC}}", "{{MAX_SEC}}"):
        assert var in w
    for key in ("HARD RULES FROM BRIEF", "offer_allowed_in_cta", "scarcity_allowed",
                "market_accusations_allowed", "forbidden_claims_effective"):
        assert key in w and key in r
    assert "claim_safety" in r and "blocker" in r
    assert "الكمية محدودة" in w and "العرض لفترة" in w


def test_meta_has_new_contract_fields(env):
    env.pattern("p1")
    path = env.product()
    env.fake.queue("writer", make_script())
    out = stage3_generate.write_for_product(path, "p1", review=False)
    s = json.loads(out.read_text(encoding="utf-8"))
    m = s["_meta"]
    assert m["product_file"] == "testp.json" and m["product_code"] == "testp"
    assert m["version"] == 1 and m["number"] == 1
    assert m["script_id"] == "VP-testp-1-v1"
    assert m["status"] == "draft"
    assert m["content_hash"] == script_versions.content_hash(s)
    assert (env.scripts / "versions" / out.stem / "v1.json").exists()
    assert out.with_suffix(".md").exists()


# ─────────────────────── فحص الادعاءات المحلي ───────────────────────


def _script_in_env(env, **kw):
    env.product()
    s = make_script(**kw)
    s["_meta"] = {"product": "TESTP", "product_file": "testp.json"}
    return s


def test_clean_script_has_no_local_findings(env):
    assert review_script.local_checks(_script_in_env(env)) == []


def test_healing_claim_is_blocker_in_healthy_looking_script(env):
    s = _script_in_env(env)
    s["scenes"][2]["voiceover"] = "قطرة لطيفة بتعطي شفاء للعين بسرعة كبيرة جداً وبكل سهولة وراحة"
    findings = review_script.local_checks(s)
    hits = [f for f in rule_findings(findings) if "شفاء" in f["issue"]]
    assert hits and hits[0]["severity"] == "blocker"
    assert hits[0]["scene"] == 3 and hits[0]["axis"] == "claim_safety"


def test_scarcity_without_basis_is_blocked(env):
    s = _script_in_env(env, cta="الكمية محدودة اطلب الآن وادفع عند الاستلام")
    f = [x for x in review_script.local_checks(s) if "ندرة" in x["issue"]]
    assert f and f[0]["severity"] == "blocker" and f[0]["field"] == "cta_line"


def test_scarcity_allowed_with_future_deadline(env):
    env.product(scarcity_deadline=future_date(10))
    s = make_script(cta="الكمية محدودة اطلب الآن وادفع عند الاستلام")
    s["_meta"] = {"product": "TESTP", "product_file": "testp.json"}
    assert not [x for x in review_script.local_checks(s) if "ندرة" in x["issue"]]


def test_scarcity_allowed_with_real_stock(env):
    env.product(stock_units=25)
    s = make_script(cta="آخر القطع اطلب الآن")
    s["_meta"] = {"product": "TESTP", "product_file": "testp.json"}
    assert not [x for x in review_script.local_checks(s) if "ندرة" in x["issue"]]


def test_offer_with_no_offer_confirmed_is_blocked(env):
    s = _script_in_env(env, cta="اطلب الآن واستفيد من الخصم الخاص")
    f = [x for x in review_script.local_checks(s) if "عرض" in x["issue"]]
    assert f and f[0]["severity"] == "blocker" and f[0]["field"] == "cta_line"


def test_offer_allowed_when_brief_has_offer(env):
    env.product(no_offer=False, offer="قطعتين بسعر مخفّض")
    s = make_script(cta="اطلب الآن واستفيد من الخصم الخاص")
    s["_meta"] = {"product": "TESTP", "product_file": "testp.json"}
    assert not [x for x in review_script.local_checks(s) if "عرض" in x["issue"]]


def test_market_accusation_without_evidence_is_blocked(env):
    s = _script_in_env(env)
    s["scenes"][1]["voiceover"] = "القطرات الثانية بالسوق ملوثة وبتأذي العين كل يوم بكل سهولة وراحة"
    f = [x for x in review_script.local_checks(s) if "اتهام" in x["issue"]]
    assert f and f[0]["severity"] == "blocker" and f[0]["scene"] == 2


def test_market_accusation_allowed_with_evidence(env):
    env.product(market_claims_evidence=["تقرير مختبر مرفق"])
    s = make_script()
    s["scenes"][1]["voiceover"] = "القطرات الثانية بالسوق ملوثة وبتأذي العين كل يوم بكل سهولة وراحة"
    s["_meta"] = {"product": "TESTP", "product_file": "testp.json"}
    assert not [x for x in review_script.local_checks(s) if "اتهام" in x["issue"]]


def test_merchant_forbidden_claim_added_on_top_of_library(env):
    env.product(forbidden_claims=["ألماني الصنع"])
    s = make_script()
    s["scenes"][0]["voiceover"] = "قطرة ألماني الصنع لطيفة للعين يومياً بسهولة وراحة مع الشاشة والتعب"
    s["_meta"] = {"product": "TESTP", "product_file": "testp.json"}
    assert any("ألماني الصنع" in x["issue"] for x in review_script.local_checks(s))


def test_missing_brief_is_a_blocker(env):
    s = make_script()
    s["_meta"] = {"product": "TESTP", "product_file": "does_not_exist.json"}
    f = review_script.local_checks(s)
    assert any("بريف المنتج" in x["issue"] and x["severity"] == "blocker" for x in f)


def test_legacy_script_finds_brief_by_product_name(env):
    env.product()
    s = make_script()
    s["scenes"][0]["voiceover"] = "قطرة لطيفة شفاء للعين يومياً بسهولة وراحة مع الشاشة والتعب الكبير"
    s["_meta"] = {"product": "TESTP"}                 # بلا product_file (سيناريو قديم)
    assert rule_findings(review_script.local_checks(s))


def test_arithmetic_checks_still_run(env):
    s = _script_in_env(env)
    s["scenes"] = s["scenes"][:6]
    assert any(f["severity"] == "blocker" and "عدد المشاهد" in f["issue"]
               for f in review_script.local_checks(s))


# ─────────────────────── ملف المراجعة + البصمة ───────────────────────


def test_review_records_script_hash_and_merges_claims(env):
    env.product()
    s = make_script(cta="الكمية محدودة اطلب الآن")
    path = env.script_file("a.json", s)
    env.fake.queue("reviewer", review_ok("approve"))            # الموديل يوافق وهو غلطان
    result = review_script.review(path)
    assert result["blockers"] >= 1
    assert result["verdict"] == "revise"                        # مانع قاطع ← ما بيعتمد
    saved = json.loads((env.lib / "reviews" / "a.review.json").read_text(encoding="utf-8"))
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert saved["script_hash"] == script_versions.content_hash(on_disk)
    assert saved["rounds"] == 0
    assert "## HARD RULES FROM BRIEF" in env.fake.user("reviewer")


def test_content_hash_normalizes_whitespace_but_sees_content():
    a = make_script()
    b = json.loads(json.dumps(a, ensure_ascii=False))
    b["hook_line"] = "  " + b["hook_line"].replace(" ", "   ") + "\n"
    b["scenes"][0]["voiceover"] = b["scenes"][0]["voiceover"].replace(" ", "  ")
    assert script_versions.content_hash(a) == script_versions.content_hash(b)
    b["scenes"][3]["voiceover"] += " كلمة"
    assert script_versions.content_hash(a) != script_versions.content_hash(b)
    c = json.loads(json.dumps(a, ensure_ascii=False))
    c["cta_line"] = "غيرها"
    assert script_versions.content_hash(a) != script_versions.content_hash(c)


# ─────────────────────── endpoints البريف ───────────────────────


def test_schema_and_completeness_endpoints(env):
    env.product("full.json")
    env.product("inc.json", core_promise="", offer="", no_offer=False)
    c = api_client()
    sch = c.get("/api/brief/schema").json()
    assert {"key": "offer", "label": "العرض", "type": "text", "group": "commercial"} in sch["fields"]
    assert "core_promise" in sch["required"] and "landing_page" in sch["publish_required"]

    full = c.get("/api/products/full.json/completeness").json()
    assert full["ready"] is True and full["score"] == 100 and full["missing"] == []
    assert full["offer_policy"] == "none" and full["scarcity"] == {"allowed": False, "basis": ""}
    assert "شفاء" in full["forbidden_effective"]

    inc = c.get("/api/products/inc.json/completeness").json()
    assert inc["ready"] is False and {"core_promise", "offer"} <= set(inc["missing"])
    assert c.get("/api/products/nope.json/completeness").status_code == 404


def test_completeness_scarcity_basis(env):
    env.product("s.json", stock_units=12, no_offer=False, offer="قطعتين")
    d = api_client().get("/api/products/s.json/completeness").json()
    assert d["scarcity"]["allowed"] is True and "12" in d["scarcity"]["basis"]
    assert d["offer_policy"] == "allowed"


# ─────────────────────── مزامنة الحقائق ───────────────────────


def _fake_crm(monkeypatch, facts=None, offline=False):
    m = types.ModuleType("crm")

    class CRMOffline(Exception):
        pass

    class CRMError(Exception):
        pass

    m.CRMOffline, m.CRMError = CRMOffline, CRMError
    m.calls = []

    def fetch(code, country):
        m.calls.append((code, country))
        if offline:
            raise CRMOffline("no network")
        return facts

    m.fetch_product_facts = fetch
    monkeypatch.setitem(sys.modules, "crm", m)
    return m


def test_facts_sync_applies_crm_fields_with_provenance(env, monkeypatch):
    path = env.product()
    crm = _fake_crm(monkeypatch, {
        "price": "49 د.أ", "offers": ["قطعتين بسعر قطعة ونص"], "guarantee": "استرجاع 7 أيام",
        "country": "Jordan", "dialect": "shami", "junk": "x", "landing_page": ""})
    r = api_client().post("/api/products/testp.json/facts/sync").json()
    assert crm.calls == [("testp", "SY")]
    assert r["stale"] is False and r["cached_at"]
    assert {"price", "offer", "guarantee", "country", "dialect", "no_offer", "no_guarantee"} <= set(r["applied"])
    assert "junk" not in r["applied"] and "landing_page" not in r["applied"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["price"] == "49 د.أ" and saved["offer"] == "قطعتين بسعر قطعة ونص"
    assert saved["country"] == "JO" and saved["no_offer"] is False and saved["no_guarantee"] is False
    assert saved["_provenance"]["price"]["source"] == "crm"
    assert (env.lib / "crm_cache" / "products" / "testp.json").exists()


def test_facts_sync_skips_unknown_country(env, monkeypatch):
    env.product()
    _fake_crm(monkeypatch, {"price": "10", "country": "السوق العربي"})
    r = api_client().post("/api/products/testp.json/facts/sync").json()
    assert "country" not in r["applied"] and r["skipped"][0]["key"] == "country"


def test_facts_sync_offline_returns_cached_stale(env, monkeypatch):
    path = env.product()
    _fake_crm(monkeypatch, {"price": "49 د.أ"})
    api_client().post("/api/products/testp.json/facts/sync")
    # بعدين الـ CRM يوقع
    _fake_crm(monkeypatch, offline=True)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["price"] = ""
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    r = api_client().post("/api/products/testp.json/facts/sync").json()
    assert r["stale"] is True and r["cached_at"] and "price" in r["applied"]
    assert json.loads(path.read_text(encoding="utf-8"))["price"] == "49 د.أ"


def test_facts_sync_offline_without_cache_is_503(env, monkeypatch):
    env.product()
    _fake_crm(monkeypatch, offline=True)
    r = api_client().post("/api/products/testp.json/facts/sync")
    assert r.status_code == 503 and "نسخة مخزّنة" in r.json()["detail"]


def test_facts_sync_when_crm_module_missing(env, monkeypatch):
    env.product()
    monkeypatch.setitem(sys.modules, "crm", None)              # import crm ← ImportError
    r = api_client().post("/api/products/testp.json/facts/sync")
    assert r.status_code == 503
    # ومع نسخة مخزّنة بيشتغل stale
    cache = env.lib / "crm_cache" / "products"
    cache.mkdir(parents=True)
    (cache / "testp.json").write_text(json.dumps(
        {"cached_at": "2026-09-01T10:00:00", "facts": {"price": "7"}}), encoding="utf-8")
    r = api_client().post("/api/products/testp.json/facts/sync").json()
    assert r["stale"] is True and r["cached_at"] == "2026-09-01T10:00:00" and r["applied"] == ["price"]


def test_facts_sync_crm_error_is_502(env, monkeypatch):
    env.product()
    m = _fake_crm(monkeypatch, {})

    def boom(code, country):
        raise m.CRMError("401")

    m.fetch_product_facts = boom
    r = api_client().post("/api/products/testp.json/facts/sync")
    assert r.status_code == 502
