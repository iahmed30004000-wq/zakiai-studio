"""المرحلة ٢ (الأساس): اكتمال البريف وفحص الادعاءات."""
from datetime import date, timedelta

import pytest

import brief
import claims


def full(**kw):
    b = brief.empty_brief()
    b.update(category="eye_care", dialect="shami", core_promise="راحة للعين",
             what_it_does="ترطيب", features=["ترطيب"], pain_points=["جفاف"],
             objections=["السعر"], proof_assets=["فيديو"], offer="خصم 20%",
             guarantee="استرجاع", production_constraints="بدون وجوه")
    b.update(kw)
    return b


def script(**kw):
    s = {"hook_line": "جرّب اليوم", "cta_line": "اطلب الآن", "title": "t",
         "scenes": [{"scene_number": 1, "voiceover": "منتج لطيف", "on_screen_text": ""}]}
    s.update(kw)
    return s


def test_empty_brief_incomplete_and_gate_raises():
    b = brief.empty_brief()
    c = brief.completeness(b)
    assert not c["ready"] and "core_promise" in c["missing"]
    with pytest.raises(brief.BriefIncomplete):
        brief.require_complete(b)


def test_complete_brief_passes_gate():
    brief.require_complete(full())
    assert brief.completeness(full())["score"] == 100


def test_no_offer_flag_satisfies_offer_but_blank_does_not():
    assert "offer" in brief.completeness(full(offer=""))["missing"]
    assert "offer" not in brief.completeness(full(offer="", no_offer=True))["missing"]


def test_crm_field_needs_reason_for_manual_edit():
    b = full()
    brief.set_field(b, "price", "10", source="crm")
    with pytest.raises(ValueError):
        brief.set_field(b, "price", "12", source="manual")
    brief.set_field(b, "price", "12", source="manual", reason="تحديث عرض")
    assert b["price"] == "12"


def test_health_claims_blocked():
    for word in ("يشفي عينيك", "علاج نهائي للنظر", "نتيجة مضمونة", "بديل عن الطبيب"):
        f = claims.scan_script(script(hook_line=word), full())
        assert any(x["severity"] == "blocker" for x in f), word


def test_clean_health_script_has_no_findings():
    assert claims.scan_script(script(), full()) == []


def test_scarcity_blocked_without_deadline_or_stock():
    s = script(cta_line="الكمية محدودة اطلب")
    assert [f for f in claims.scan_script(s, full()) if "ندرة" in f["issue"]]
    future = full(scarcity_deadline=(date.today() + timedelta(days=3)).isoformat())
    assert not [f for f in claims.scan_script(s, future) if "ندرة" in f["issue"]]
    assert not [f for f in claims.scan_script(s, full(stock_units=12)) if "ندرة" in f["issue"]]
    past = full(scarcity_deadline=(date.today() - timedelta(days=1)).isoformat())
    assert [f for f in claims.scan_script(s, past) if "ندرة" in f["issue"]]


def test_no_offer_blocks_offer_words_in_cta():
    b = full(offer="", no_offer=True)
    f = claims.scan_script(script(cta_line="اطلب الآن مع خصم خاص"), b)
    assert any("عرض" in x["issue"] for x in f)
    assert not claims.writer_rules(b)["offer_allowed_in_cta"]


def test_market_accusation_needs_evidence():
    s = script(hook_line="منتجات السوق ملوثة")
    assert any("اتهام" in x["issue"] for x in claims.scan_script(s, full()))
    assert not any("اتهام" in x["issue"]
                   for x in claims.scan_script(s, full(market_claims_evidence="تقرير مخبري")))


def test_beauty_absolute_claims_blocked():
    b = full(category="hair_removal")
    assert claims.scan_script(script(hook_line="إزالة نهائية لكل البشرات"), b)


def test_merchant_cannot_remove_library_claims():
    b = full(forbidden_claims=["مجاني تماماً"])
    eff = claims.effective_forbidden(b)
    assert "مجاني تماماً" in eff and len(eff) > 1


def test_normalize_keeps_legacy_and_flags_country():
    old = {"product_name": "Kama", "category": "كريم إزالة الشعر", "dialect": "شامي",
           "market": "السوق العربي"}
    out, issues = brief.normalize(old, "kama")
    assert out["category"] == "hair_removal" and out["_legacy"]["market"] == "السوق العربي"
    assert any(i["kind"] == "country" for i in issues)
