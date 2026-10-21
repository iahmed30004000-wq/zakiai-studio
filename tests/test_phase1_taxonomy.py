"""المرحلة ١: القوائم المغلقة، طابور المراجعة، العناقيد."""
import json
import re

import pytest

import review_queue
import taxonomy


# ── اللهجة ──────────────────────────────────────────────────────────────
def test_dialect_empty():
    assert taxonomy.normalize_dialect("").status == "empty"


def test_dialect_mixed_goes_to_review_not_guess():
    n = taxonomy.normalize_dialect("شامي ومصري")
    assert n.status == "review" and n.value is None and len(n.candidates) >= 2


def test_dialect_values_are_closed():
    for raw in ("شامي", "خليجي", "فصحى مبسطة", "بلا كلام", "مغاربي"):
        n = taxonomy.normalize_dialect(raw)
        assert n.value in taxonomy.DIALECTS, raw


# ── الإطار ──────────────────────────────────────────────────────────────
def test_framework_merged_is_split_primary_secondary():
    n = taxonomy.normalize_framework("Authority Reveal | Us vs Them")
    assert n.value == "authority_reveal" and n.secondary == "us_vs_them"
    assert n.needs_confirm


def test_framework_unknown_goes_to_review():
    n = taxonomy.normalize_framework("Something Totally New")
    assert n.status == "review" and n.value is None


def test_framework_value_never_contains_separator():
    for raw in ("Ingredient Reveal / Demo-Proof", "Authority Reveal | Us vs Them"):
        n = taxonomy.normalize_framework(raw)
        assert n.value in taxonomy.FRAMEWORKS
        assert not re.search(r"[|/]", n.value)


# ── الفئة ───────────────────────────────────────────────────────────────
def test_category_hair_removal_wins_over_hair_care():
    n = taxonomy.normalize_category("كريم إزالة الشعر")
    assert n.status == "ok" and n.value == "hair_removal"


def test_category_distance():
    assert taxonomy.category_distance("skincare", "skincare") == "same"
    assert taxonomy.category_distance("skincare", "makeup") == "adjacent"
    assert taxonomy.category_distance("skincare", "eye_care") == "far"
    assert taxonomy.category_distance(None, "eye_care") == "unknown"
    assert taxonomy.category_distance("skincare", "other") == "unknown"


def test_country_arab_market_is_not_a_country():
    assert taxonomy.normalize_country("السوق العربي").status == "review"
    assert taxonomy.normalize_country("سوريا").value == "SY"


# ── تطبيق على نمط ────────────────────────────────────────────────────────
def test_apply_to_pattern_keeps_legacy_and_flags_review():
    p = {"dialect_or_language": "شامي ومصري", "framework": "Weird Thing",
         "product_category": "كريم إزالة الشعر"}
    out, issues = taxonomy.apply_to_pattern(p)
    assert out["_legacy"]["framework"] == "Weird Thing"
    assert out["product_category"] == "hair_removal"
    assert out["framework"] is None and out["dialect_or_language"] is None
    assert {"dialect", "framework"} <= {i["kind"] for i in issues}
    assert out["_taxonomy"]["complete"] is False


def test_apply_is_idempotent():
    p = {"dialect_or_language": "شامي", "framework": "Us vs Them", "product_category": "skincare"}
    a, _ = taxonomy.apply_to_pattern(dict(p))
    b, _ = taxonomy.apply_to_pattern(json.loads(json.dumps(a)))
    for k in ("dialect_or_language", "framework", "product_category"):
        assert a[k] == b[k]
    assert b["_legacy"] == a["_legacy"]


def test_inject_vocab_replaces_marker_or_appends():
    assert "CLOSED VOCABULARIES" in taxonomy.inject_vocab("x {{VOCAB}} y")
    assert "{{VOCAB}}" not in taxonomy.inject_vocab("x {{VOCAB}} y")
    assert "CLOSED VOCABULARIES" in taxonomy.inject_vocab("no marker")


# ── طابور المراجعة ───────────────────────────────────────────────────────
@pytest.fixture
def rq(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(review_queue, "QUEUE_PATH", tmp_path / "rq.json")
    monkeypatch.setattr(config, "PATTERNS_DIR", tmp_path / "patterns")
    (tmp_path / "patterns").mkdir()
    return tmp_path


def test_queue_dedupes_open_items(rq):
    a = review_queue.add("dialect", "p1", "شامي ومصري", ["shami", "masri"])
    b = review_queue.add("dialect", "p1", "شامي ومصري", ["shami", "masri"])
    assert a["id"] == b["id"] and len(review_queue.list_items()) == 1


def test_queue_resolve_writes_pattern_and_rejects_free_text(rq):
    pf = rq / "patterns" / "p1.pattern.json"
    pf.write_text(json.dumps({"dialect_or_language": None}), encoding="utf-8")
    it = review_queue.add("dialect", "p1", "x", [])
    with pytest.raises(ValueError):
        review_queue.resolve(it["id"], "لهجة مخترعة")
    review_queue.resolve(it["id"], "shami")
    assert json.loads(pf.read_text(encoding="utf-8"))["dialect_or_language"] == "shami"
    assert review_queue.list_items() == []


def test_queue_resolve_country_writes_product(rq, monkeypatch):
    import config
    prods = rq / "products"
    prods.mkdir()
    monkeypatch.setattr(config, "PRODUCTS_DIR", prods)
    (prods / "kama.json").write_text(json.dumps({"country": ""}), encoding="utf-8")
    it = review_queue.add("country", "product:kama", "السوق العربي", [])
    with pytest.raises(ValueError):
        review_queue.resolve(it["id"], "XX")
    review_queue.resolve(it["id"], "SY")
    saved = json.loads((prods / "kama.json").read_text(encoding="utf-8"))
    assert saved["country"] == "SY"
