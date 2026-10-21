"""مكتبة الادعاءات الممنوعة القابلة للتعديل: المالك بيعدّل/بيحذف/بيضيف، والفحص بالكود بيتبع تعديلاته فوراً."""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401

import claims  # noqa: E402
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def hits(text, category="eye_care"):
    return [f["issue"] for f in claims.try_text(text, category)]


def labels(group):
    return [r["label"] for r in claims.rules_state()["groups"][group]["rules"]]


def rid(group, label):
    return next(r["id"] for r in claims.rules_state()["groups"][group]["rules"] if r["label"] == label)


# ───────── الافتراضي = السلوك القديم بالضبط ─────────
def test_defaults_match_the_original_hard_coded_rules(env):
    st = claims.rules_state()
    assert labels("health") == ["شفاء", "علاج", "بديل عن الطبيب", "نتيجة مضمونة"]
    assert labels("beauty") == ["بدون تهيّج لكل البشرات", "نتيجة نهائية"] and st["groups"]["all"]["rules"] == []
    assert st["customized"] == [] and st["log"] == []
    assert dict(claims.category_rules("eye_care")) == dict(claims.HEALTH_RULES)      # نفس الأنماط بعد التقسيم ثم الدمج
    assert dict(claims.category_rules("skincare")) == dict(claims.BEAUTY_RULES)
    assert claims.category_rules("electronics") == []
    assert any("علاج" in h for h in hits("بيعالج العين")) and any("بديل عن الطبيب" in h for h in hits("بديل عن الطبيب"))


def test_split_alts_ignores_pipes_inside_groups():
    assert claims._split_alts(r"a(?:b|c)|d|[x|y]z") == [r"a(?:b|c)", "d", "[x|y]z"]


# ───────── حذف وتعديل وتعطيل وإضافة ─────────
def test_deleting_a_rule_stops_blocking_it_everywhere_and_is_logged(env):
    assert any("علاج" in h for h in hits("بيعالج العين"))
    claims.delete_rule("health", rid("health", "علاج"))
    assert not any("علاج" in h for h in hits("بيعالج العين"))
    assert any("نتيجة مضمونة" in h for h in hits("نتيجة مضمونة"))            # الباقي ضل شغّال
    st = claims.rules_state()
    assert "علاج" not in labels("health") and st["customized"] == ["health"]
    assert st["log"][0]["action"] == "delete" and st["log"][0]["label"] == "علاج" and st["log"][0]["before"]
    assert (Path(config.LIBRARY_DIR) / "claims_rules.json").exists()          # بالمكتبة المعزولة مش بالحقيقية


def test_editing_patterns_changes_what_is_caught(env):
    r = rid("health", "شفاء")
    claims.edit_rule("health", r, patterns=["معجزة"])
    assert not any("شفاء" in h for h in hits("بيشفي العين"))
    assert any("شفاء" in h for h in hits("منتج معجزة"))
    claims.edit_rule("health", r, label="ادعاء معجزة")
    assert "ادعاء معجزة" in labels("health") and "شفاء" not in labels("health")


def test_adding_a_plain_phrase_is_escaped_and_whitespace_flexible(env):
    claims.add_rule("health", "خالي من الآثار الجانبية", phrase="خالي من (الآثار) الجانبية؟")
    assert any("خالي" in h for h in hits("منتج خالي   من (الآثار) الجانبية؟"))
    assert not hits("منتج خالي من الآثار الجانبية")                              # الأقواس والرموز حرفية مش regex
    new_id = rid("health", "خالي من الآثار الجانبية")
    claims.edit_rule("health", new_id, phrase="بدون آثار جانبية")                  # صيغة إضافية لنفس الادعاء
    assert any("خالي" in h for h in hits("بدون   آثار جانبية"))
    rule = next(r for r in claims.rules_state()["groups"]["health"]["rules"] if r["id"] == new_id)
    assert len(rule["patterns"]) == 2


def test_all_group_applies_to_every_category(env):
    claims.add_rule("all", "أرخص من السوق", phrase="أرخص من السوق")
    for cat in ("eye_care", "skincare", "hair_removal", "electronics", None):
        assert any("أرخص" in h for h in hits("أرخص من السوق", cat)), cat


def test_disabling_keeps_the_rule_but_stops_enforcing(env):
    r = rid("health", "علاج")
    claims.edit_rule("health", r, enabled=False)
    assert "علاج" in labels("health") and not any("علاج" in h for h in hits("بيعالج"))
    claims.edit_rule("health", r, enabled=True)
    assert any("علاج" in h for h in hits("بيعالج"))


def test_reset_restores_defaults_and_keeps_the_audit_trail(env):
    claims.delete_rule("health", rid("health", "شفاء"))
    claims.add_rule("health", "جديد", phrase="كلمة جديدة")
    st = claims.reset_group("health")
    assert labels("health") == ["شفاء", "علاج", "بديل عن الطبيب", "نتيجة مضمونة"] and st["customized"] == []
    assert [x["action"] for x in st["log"]][:3] == ["reset", "add", "delete"] and len(st["log"]) == 3


# ───────── تحقق وأمان ─────────
@pytest.mark.parametrize("bad,msg", [
    ("(", "مش صالحة"),
    ("a*", "بتطابق أي نص"),
    ("x" * 201, "أطول"),
])
def test_invalid_empty_matching_or_long_patterns_are_rejected_and_nothing_is_saved(env, bad, msg):
    with pytest.raises(claims.ClaimsError, match=msg):
        claims.add_rule("health", "تجربة", patterns=[bad])
    assert "تجربة" not in labels("health")
    assert not (Path(config.LIBRARY_DIR) / "claims_rules.json").exists()


def test_catastrophic_pattern_is_rejected_by_the_separate_process_probe_and_never_hangs_the_server(env):
    """(?:ا+)+$ بيعلّق re لو انشغّل بنفس العملية. الفحص بعملية منفصلة بمهلة، فبينرفض بدل ما يعلّق الخادم."""
    import time
    t = time.perf_counter()
    with pytest.raises(claims.ClaimsError, match="ثقيلة"):
        claims.add_rule("health", "خبيثة", patterns=["(?:ا+)+$"])
    assert time.perf_counter() - t < claims.PROBE_TIMEOUT_SEC + 2
    assert "خبيثة" not in labels("health")


def test_labels_limits_and_unknown_groups(env):
    with pytest.raises(claims.ClaimsError):
        claims.add_rule("health", "", phrase="x")
    with pytest.raises(claims.ClaimsError):
        claims.add_rule("health", "ا" * 61, phrase="x")
    with pytest.raises(claims.ClaimsError, match="مجموعة"):
        claims.add_rule("nope", "x", phrase="y")
    with pytest.raises(claims.ClaimsError, match="غير موجود"):
        claims.delete_rule("health", "health_999")
    with pytest.raises(claims.ClaimsError):
        claims.add_rule("health", "x")                      # بلا صيغة ولا عبارة


def test_corrupt_store_falls_back_to_defaults_instead_of_crashing(env):
    p = Path(config.LIBRARY_DIR) / "claims_rules.json"
    p.write_text("{not json", encoding="utf-8")
    assert labels("health")[0] == "شفاء"
    p.write_text('{"groups": {"health": {"rules": "x"}}}', encoding="utf-8")
    assert labels("health")[0] == "شفاء"


def test_brief_level_additions_still_work_on_top(env):
    claims.delete_rule("health", rid("health", "علاج"))
    brief = {"category": "eye_care", "forbidden_claims": ["حصري"]}
    assert "علاج" not in claims.effective_forbidden(brief) and "حصري" in claims.effective_forbidden(brief)
    found = claims.scan_script({"scenes": [{"scene_number": 1, "voiceover": "عرض حصري"}]}, {**brief, "offer": "x"})
    assert any("حصري" in f["issue"] for f in found)


# ───────── المسارات ─────────
@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient
    from web.app import app
    return TestClient(app)


def test_routes_full_cycle(client):
    r = client.get("/api/claims/rules")
    assert r.status_code == 200 and [x["label"] for x in r.json()["groups"]["health"]["rules"]][0] == "شفاء"
    assert "eye_care" in r.json()["category_labels"]
    r = client.post("/api/claims/rules/health", json={"label": "أفضل منتج", "phrase": "أفضل منتج بالعالم"})
    assert r.status_code == 200
    new_id = [x["id"] for x in r.json()["groups"]["health"]["rules"] if x["label"] == "أفضل منتج"][0]
    assert client.post("/api/claims/try", json={"text": "هذا أفضل   منتج بالعالم", "category": "eye_care"}).json()["found"]
    r = client.put(f"/api/claims/rules/health/{new_id}", json={"label": "أفضل منتج", "enabled": False})
    assert r.status_code == 200
    assert not client.post("/api/claims/try", json={"text": "أفضل منتج بالعالم", "category": "eye_care"}).json()["found"]
    assert client.delete(f"/api/claims/rules/health/{new_id}").status_code == 200
    assert client.post("/api/claims/reset/health").json()["customized"] == []


def test_routes_return_arabic_400s(client):
    r = client.post("/api/claims/rules/health", json={"label": "x", "patterns": ["("]})
    assert r.status_code == 400 and "مش صالحة" in r.json()["detail"]
    assert client.delete("/api/claims/rules/health/zzz").status_code == 400
    assert client.post("/api/claims/reset/nope").status_code == 400


# ───────── الواجهة ─────────
def test_ui_has_the_claims_tab_escapes_text_and_confirms_destructive_actions():
    js = (ROOT / "web/static/claims.js").read_text(encoding="utf-8")
    idx = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
    shell = (ROOT / "web/static/shell.js").read_text(encoding="utf-8")
    assert 'data-tab="claims"' in idx and 'id="libs-claims"' in idx and "/claims.js?v=" in idx
    assert '"claims"' in shell and "VIEWS.claims.enter" in shell
    assert js.count("confirm(") >= 2                                          # الحذف والاسترجاع بيطلبوا تأكيد
    assert "${esc(r.label)}" in js and "${esc(f.evidence)}" in js             # نصوص بتنهرّب
    assert not re.search(r"[٠-٩]", js)                                        # أرقام غربية بالكود
