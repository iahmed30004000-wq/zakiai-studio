"""بنك الهوكات (المرحلة 3ج): فهرس مشتق من السيناريوهات + يدوي + نجمة + أرشفة + نتايج + أمثلة للكاتب."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_hooks_h1 import ALTS, HOOK, hooked, read  # noqa: E402

import config  # noqa: E402
import evidence  # noqa: E402
import hooks_bank as hb  # noqa: E402
import script_hooks as sh  # noqa: E402


def write_version(env, base_stem, hid, *, sid):
    """سيناريو نسخة هوك (بالـ _meta.hook_of) بدون المرور بخط الإنتاج."""
    b = read(env.scripts / f"{base_stem}.json")
    v = sh.as_script(b, hid)
    for k in ("hooks", "hook_main", "hooks_review"):
        v.pop(k, None)
    v["_meta"] = {**b["_meta"], "script_id": sid, "hook_of": {"base": base_stem, "base_script_id": b["_meta"]["script_id"], "hook_id": hid, "type": "number"}}
    (env.scripts / f"{base_stem}__{hid}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def bank(env, monkeypatch):
    """سيناريو بـ3 هوكات (kama، فئة eye_care) + سيناريو قديم بهوك واحد + نسخة فيديو لـ h2. نتايج الأداء مزيّفة بالاختبار."""
    p1 = hooked(env, "s1.json", n=3, status="approved")
    env.script_file("legacy.json", make_script(hook="هوك قديم وحيد"), meta={"product": "VARA", "product_file": "testp.json", "product_code": "vara",
                                                                                "script_id": "VP-vara-4-v1", "number": 4, "version": 1, "status": "draft"})
    write_version(env, "s1", "h2", sid="VP-testp-1-v1-h2")
    monkeypatch.setattr(evidence, "script_verdicts", lambda *a, **k: {})
    return types_ns(env, p1, monkeypatch)


class types_ns:
    def __init__(self, env, path, mp):
        self.env, self.path, self.mp = env, path, mp

    def results(self, rows):
        self.mp.setattr(evidence, "script_verdicts", lambda *a, **k: {f"{r['script_id']}.json": r for r in rows})


def row(sid, verdict="winner", delivered=60, spend=120.0, vs=0.62):
    return {"script_id": sid, "verdict": verdict, "reason": f"سبب {verdict}", "delivered": delivered, "spend": spend,
            "orders": delivered + 5, "cost_per_delivered": round(spend / delivered, 2), "cost_vs_baseline": vs}


# ═════════════════ الفهرس المشتق ═════════════════
def test_every_hook_of_every_script_is_indexed_once_with_its_role(bank):
    d = hb.list_entries(include_archived=True)
    keys = {e["key"]: e for e in d["items"]}
    assert set(keys) == {"VP-testp-1-v1.h1", "VP-testp-1-v1.h2", "VP-testp-1-v1.h3", "VP-vara-4-v1.h1"}      # نسخة الهوك مش هوك جديد
    assert keys["VP-testp-1-v1.h1"]["role"] == "main" and keys["VP-testp-1-v1.h3"]["role"] == "alt"
    assert keys["VP-testp-1-v1.h2"]["role"] == "video" and keys["VP-testp-1-v1.h2"]["version"] == {"file": "s1__h2.json", "script_id": "VP-testp-1-v1-h2"}
    h = keys["VP-testp-1-v1.h2"]
    assert (h["text"], h["on_screen_text"], h["type"], h["type_label"]) == (ALTS[0][1], "٣ من ٥", "number", "رقم") and h["product"] == "TESTP"
    assert h["script_file"] == "s1.json" and h["script_id"] == "VP-testp-1-v1" and h["source"] == "script" and h["why"]
    legacy = keys["VP-vara-4-v1.h1"]
    assert legacy["role"] == "main" and legacy["text"] == "هوك قديم وحيد" and legacy["type_label"] == "غير محدد" and legacy["category"] == "eye_care"


def test_a_script_without_an_id_is_keyed_by_its_file_name(bank, env):
    s = make_script(hook="هوك بلا هوية")
    s["_meta"] = {"product": "X"}
    (env.scripts / "old.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert "f_old.h1" in {e["key"] for e in hb.entries({})}


def test_broken_or_non_object_script_files_are_skipped(bank, env):
    (env.scripts / "bad.json").write_text("{nope", encoding="utf-8")
    (env.scripts / "list.json").write_text("[1,2]", encoding="utf-8")
    assert len(hb.entries({})) == 4


# ═════════════════ النتايج ═════════════════
def test_results_attach_to_the_main_hook_and_to_the_video_version_of_an_alternative(bank):
    bank.results([row("VP-testp-1-v1", "ok", 80, 160.0, 1.0), row("VP-testp-1-v1-h2", "winner", 60, 90.0, 0.62)])
    by = {e["key"]: e for e in hb.entries()}
    assert by["VP-testp-1-v1.h1"]["result"]["verdict"] == "ok" and by["VP-testp-1-v1.h1"]["result"]["delivered"] == 80
    r = by["VP-testp-1-v1.h2"]["result"]
    assert r["verdict"] == "winner" and r["script_id"] == "VP-testp-1-v1-h2" and r["cost_per_delivered"] == 1.5 and r["cost_vs_baseline"] == 0.62
    assert by["VP-testp-1-v1.h3"]["result"] is None and by["VP-vara-4-v1.h1"]["result"] is None          # لسا ما اتجرّبوا


def test_rows_without_any_spend_or_orders_are_not_results(bank):
    bank.results([{"script_id": "VP-testp-1-v1", "verdict": "insufficient", "reason": "x", "delivered": 0, "spend": 0, "orders": 0}])
    assert next(e for e in hb.entries() if e["key"] == "VP-testp-1-v1.h1")["result"] is None


def test_the_bank_works_when_the_oms_data_is_unavailable(bank):
    def boom(*a, **k):
        raise RuntimeError("OMS غير مربوط")

    bank.mp.setattr(evidence, "script_verdicts", boom)
    d = hb.list_entries()
    assert len(d["items"]) == 4 and all(e["result"] is None for e in d["items"]) and d["counts"]["tested"] == 0


def test_counts_filters_and_sort_order(bank):
    bank.results([row("VP-testp-1-v1", "loser", 50, 200.0, 1.6), row("VP-testp-1-v1-h2", "winner", 60, 90.0, 0.62)])
    hb.set_star("VP-testp-1-v1.h3", True)
    d = hb.list_entries()
    assert d["counts"] == {"total": 4, "starred": 1, "tested": 2, "winners": 1, "archived": 0}
    order = [e["key"] for e in d["items"]]
    assert order[0] == "VP-testp-1-v1.h3"                                                       # النجمة أول
    assert order.index("VP-testp-1-v1.h2") < order.index("VP-testp-1-v1.h1")                    # الرابح قبل الخاسر
    assert order.index("VP-testp-1-v1.h1") < order.index("VP-vara-4-v1.h1")                    # المجرّب (ولو خاسر) قبل غير المجرّب
    assert d["products"] == ["TESTP", "VARA"] and set(d["types"]) == set(sh.TYPES)
    assert [e["key"] for e in hb.list_entries(product="VARA")["items"]] == ["VP-vara-4-v1.h1"]
    assert {e["key"] for e in hb.list_entries(type="number")["items"]} == {"VP-testp-1-v1.h2"}
    assert [e["key"] for e in hb.list_entries(star=True)["items"]] == ["VP-testp-1-v1.h3"]
    assert [e["key"] for e in hb.list_entries(role="video")["items"]] == ["VP-testp-1-v1.h2"]
    assert [e["key"] for e in hb.list_entries(q="حرقة")["items"]] == []
    assert [e["key"] for e in hb.list_entries(q="الساعة")["items"]] == ["VP-testp-1-v1.h3"]
    assert [e["key"] for e in hb.list_entries(q="وحيد")["items"]] == ["VP-vara-4-v1.h1"]


# ═════════════════ اليدوي ═════════════════
def test_manual_hooks_can_be_added_edited_and_deleted(bank):
    e = hb.add_manual("  شو بتعمل لو عينك   بتحرقك؟ ", type="question", product="kama", note="سمعتها من زبونة")
    assert e["key"] == "m_1" and e["source"] == "manual" and e["role"] == "manual" and e["text"] == "شو بتعمل لو عينك بتحرقك؟"
    assert e["type"] == "question" and e["type_label"] == "سؤال" and e["product"] == "kama" and e["note"] == "سمعتها من زبونة" and e["created_at"]
    t = hb.add_manual("هوك تاني بدون نوع", type="مش نوع")
    assert t["type"] is None and t["type_label"] == "غير محدد" and t["key"] == "m_2"
    e2 = hb.update_manual("m_1", text="نص معدّل بالكامل", type="number", product="", note="")
    assert e2["text"] == "نص معدّل بالكامل" and e2["type"] == "number" and e2["product"] is None and e2["note"] == ""
    hb.delete_manual("m_1")
    assert all(e["key"] != "m_1" for e in hb.entries({}))
    with pytest.raises(hb.BankError) as ex:
        hb.update_manual("m_1", text="x" * 5)
    assert ex.value.status == 404


def test_manual_validation(bank):
    for bad in ("", "  ", "ab", "x" * 301):
        with pytest.raises(hb.BankError):
            hb.add_manual(bad)
    with pytest.raises(hb.BankError):
        hb.add_manual("نص سليم هون", product="p" * 81)
    with pytest.raises(hb.BankError):
        hb.add_manual("نص سليم هون", note="n" * 301)
    assert hb.entries({}) and not [e for e in hb.entries({}) if e["source"] == "manual"]


def test_manual_ids_never_repeat_after_a_delete(bank):
    a = hb.add_manual("هوك أول يدوي")["key"]
    hb.delete_manual(a)
    assert hb.add_manual("هوك تاني يدوي")["key"] == "m_2"


def test_derived_hooks_cannot_be_deleted_or_edited_through_the_manual_api(bank):
    with pytest.raises(hb.BankError):
        hb.delete_manual("VP-testp-1-v1.h1")
    with pytest.raises(hb.BankError):
        hb.update_manual("VP-testp-1-v1.h1", text="تعديل")


# ═════════════════ النجمة والأرشفة ═════════════════
def test_star_and_archive_work_on_derived_and_manual_hooks(bank):
    m = hb.add_manual("هوك يدوي للتجربة")["key"]
    for key in ("VP-testp-1-v1.h2", m):
        assert hb.set_star(key, True)["star"] is True and hb.set_star(key, False)["star"] is False
        assert hb.set_archived(key, True)["archived"] is True
    d = hb.list_entries()
    assert {e["key"] for e in d["items"]} == {"VP-testp-1-v1.h1", "VP-testp-1-v1.h3", "VP-vara-4-v1.h1"} and d["counts"]["archived"] == 2
    inc = hb.list_entries(include_archived=True)
    assert len(inc["items"]) == 5 and next(e for e in inc["items"] if e["key"] == m)["archived"] is True
    assert hb.set_archived(m, False)["archived"] is False


def test_unknown_or_odd_keys_are_a_404_and_write_nothing(bank):
    for key in ("nope", "../x", "a b", "x" * 200, ""):
        with pytest.raises(hb.BankError) as e:
            hb.set_star(key, True)
        assert e.value.status == 404
    assert not hb._file().exists()                                                              # ما انكتب شي


def test_the_bank_file_survives_corruption_and_has_no_temp_leftovers(bank):
    hb.set_star("VP-testp-1-v1.h1", True)
    f = hb._file()
    assert json.loads(f.read_text(encoding="utf-8"))["stars"] == {"VP-testp-1-v1.h1": True}
    assert [p.name for p in f.parent.glob("hooks_bank*")] == ["hooks_bank.json"]
    f.write_text("{مكسور", encoding="utf-8")
    assert hb.list_entries()["counts"]["starred"] == 0 and len(hb.entries({})) == 4


def test_the_bank_never_changes_the_scripts(bank, env):
    before = {p.name: p.read_bytes() for p in env.scripts.glob("*.json")}
    hb.add_manual("هوك يدوي جديد")
    hb.set_star("VP-testp-1-v1.h2", True)
    hb.set_archived("VP-testp-1-v1.h3", True)
    assert {p.name: p.read_bytes() for p in env.scripts.glob("*.json")} == before


# ═════════════════ أمثلة الكاتب ═════════════════
def test_writer_examples_are_starred_or_winning_hooks_best_first(bank):
    assert hb.writer_examples() == [] and hb.writer_block([]) == ""
    bank.results([row("VP-testp-1-v1", "winner", 90, 90.0, 0.7), row("VP-testp-1-v1-h2", "winner", 60, 60.0, 0.5), row("VP-vara-4-v1", "loser", 40, 120.0, 1.7)])
    hb.set_star("VP-testp-1-v1.h3", True)
    ex = hb.writer_examples()
    assert [e["text"] for e in ex] == [ALTS[0][1], HOOK, ALTS[1][1]]                           # رابح أرخص، رابح، ثم المنجّم بلا نتيجة
    assert ex[0]["result"] == "winner — cost per delivered order 50% of the product baseline — 60 delivered orders"
    assert ex[2]["result"] is None and ex[2]["starred_by_owner"] is True and ex[0]["product"] == "TESTP" and ex[0]["type"] == "number"
    assert all(set(e) == {"type", "text", "product", "starred_by_owner", "result"} for e in ex)


def test_writer_examples_prefer_the_same_category_even_over_a_better_result(bank, env):
    env.product("sk.json", category="skincare")
    env.script_file("sk.json", make_script(hook="كريم بشرة هوك ناجح"), meta={"product": "SK", "product_file": "sk.json", "product_code": "sk",
                                                                           "script_id": "VP-sk-1-v1", "number": 1, "version": 1, "status": "draft"})
    bank.results([row("VP-testp-1-v1", "winner", 90, 90.0, 0.9), row("VP-sk-1-v1", "winner", 90, 90.0, 0.1)])
    assert [e["text"] for e in hb.writer_examples(category="eye_care")] == [HOOK, "كريم بشرة هوك ناجح"]
    assert [e["text"] for e in hb.writer_examples(category="skincare")] == ["كريم بشرة هوك ناجح", HOOK]


def test_writer_examples_skip_archived_hooks_dedupe_text_and_respect_the_limit(bank):
    bank.results([row("VP-testp-1-v1", "winner", 90, 90.0, 0.7)])
    hb.set_archived("VP-testp-1-v1.h1", True)
    assert hb.writer_examples() == []                                                           # المؤرشف ما بيصير مثال
    hb.set_archived("VP-testp-1-v1.h1", False)
    k = hb.add_manual(HOOK)["key"]                                                              # نفس نص هوك السيناريو، منجّم يدوياً
    hb.set_star(k, True)
    assert [e["text"] for e in hb.writer_examples()].count(HOOK) == 1
    for i in range(10):
        hb.set_star(hb.add_manual(f"هوك يدوي رقم {i} للأمثلة")["key"], True)
    assert len(hb.writer_examples()) == hb.WRITER_EXAMPLES and len(hb.writer_examples(limit=3)) == 3


def test_writer_block_format(bank):
    bank.results([row("VP-testp-1-v1", "winner", 90, 90.0, 0.7)])
    block = hb.writer_block(hb.writer_examples())
    assert block.startswith("## HOOK EXAMPLES THAT WORKED\n") and block.endswith("\n\n") and "MECHANISM" in block and "never the wording" in block
    payload = json.loads(block.split("forbids repeating any of them.\n", 1)[1])
    assert payload[0]["text"] == HOOK and payload[0]["result"].startswith("winner")
