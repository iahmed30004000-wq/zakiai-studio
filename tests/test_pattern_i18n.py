"""ترجمة الأنماط للعربي (pattern_i18n + translate_patterns): بدفعات، بتعبّي الناقص بس، ما بتضرب تعديل المالك، وقابلة للرجوع."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import clusters  # noqa: E402
import config  # noqa: E402
import pattern_i18n as i18n  # noqa: E402
import pattern_store as ps  # noqa: E402
import pattern_text as pt  # noqa: E402
import review_queue  # noqa: E402
import translate_patterns as tp  # noqa: E402
from test_pattern_text import sample  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    pdir = tmp_path / "patterns"
    pdir.mkdir()
    monkeypatch.setattr(config, "PATTERNS_DIR", pdir)
    monkeypatch.setattr(config, "SCRIPTS_DIR", tmp_path / "scripts")
    monkeypatch.setattr(review_queue, "QUEUE_PATH", tmp_path / "rq.json")
    monkeypatch.setattr(clusters, "CLUSTERS_PATH", tmp_path / "clusters.json")
    return tmp_path


def put(lib, pid="p1", **over):
    p = sample()
    p.update(over)
    (lib / "patterns" / f"{pid}.pattern.json").write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read(lib, pid="p1"):
    return json.loads((lib / "patterns" / f"{pid}.pattern.json").read_text(encoding="utf-8"))


class Fake:
    """موديل مزيّف: بيترجم كل مفتاح لنص عربي فريد، وبيسجّل الدفعات."""

    def __init__(self, drop=(), english=(), before=None):
        self.batches, self.drop, self.english, self.before, self.n = [], set(drop), set(english), before, 0

    def __call__(self, system, user):
        assert "Arabic copy editor" in system
        req = json.loads(user)
        keys = list(req["texts"])
        self.batches.append(keys)
        if self.before:
            self.before()
            self.before = None
        out = {}
        for k in keys:
            if k in self.drop and len(self.batches) == 1:
                continue
            if k in self.english and len(self.batches) == 1:
                out[k] = req["texts"][k]                    # رجّع الإنجليزي كما هو (غلط)
                continue
            self.n += 1
            out[k] = f"نص عربي رقم {self.n}"
        return {"translations": out}


# ═════════════════ الدفعات والتحقق ═════════════════
def test_texts_go_in_batches_of_at_most_50_keys(lib):
    big = sample()
    big["scene_blueprint"] = [{"slot": i, "function": f"Scene function {i}", "duration_sec": 1, "shot_type": f"shot {i}", "vo_intent": f"intent {i}",
                               "on_screen_text_role": f"role {i}", "emotion": f"emotion {i}"} for i in range(1, 31)]
    fake = Fake()
    got = i18n.translate_texts(big, fake)
    assert len(fake.batches) >= 3 and all(len(b) <= i18n.BATCH_KEYS for b in fake.batches)
    assert set(got) == set(pt.missing_ar_keys(big))


def test_missing_and_english_answers_are_retried_once_for_those_keys_only(lib):
    p = sample()
    keys = pt.missing_ar_keys(p)
    drop, eng = "one_line_summary", "pattern_name"
    fake = Fake(drop=[drop], english=[eng])
    got = i18n.translate_texts(p, fake)
    assert len(fake.batches) == 2 and sorted(fake.batches[1]) == sorted([drop, eng])
    assert set(got) == set(keys)


def test_a_key_that_never_translates_stays_pending_for_the_next_run(lib):
    p = sample()

    def stubborn(system, user):
        t = json.loads(user)["texts"]
        return {"translations": {k: ("Still English" if k == "pattern_name" else "نص عربي") for k in t}}

    got = i18n.translate_texts(p, stubborn)
    assert "pattern_name" not in got and "one_line_summary" in got


def test_usable_accepts_arabic_and_untranslatable_sources_only():
    assert i18n._usable("Hello there", "مرحبا")
    assert not i18n._usable("Hello there", "Hello there")
    assert not i18n._usable("Hello there", "")
    assert not i18n._usable("Hello there", None)
    assert i18n._usable("30%", "30%") and i18n._usable("[A], [B]", "[A]، [B]")       # ما فيه كلمات تنترجم
    assert i18n._usable("Kama tonic", "مقوّي Kama")


def test_garbage_replies_do_not_crash(lib):
    p = sample()
    for bad in (None, [], {"translations": None}, {"translations": []}, {"x": 1}):
        assert i18n.translate_texts(p, lambda s, u, b=bad: b) == {}


# ═════════════════ نمط واحد ═════════════════
def test_translate_pattern_fills_ar_only_and_records_history(lib):
    put(lib)
    before = read(lib)
    res = i18n.translate_pattern("p1", ask=Fake())
    p = read(lib)
    assert res["keys"] > 5 and res["applied"] == res["keys"] and res["pending"] == 0
    assert p["pattern_name"] == before["pattern_name"] == "The Sensory Layer Reveal"       # الأصل الإنجليزي ما اتغيّر
    assert p["hook"] == before["hook"] and p["scene_blueprint"][0]["function"] == before["scene_blueprint"][0]["function"]
    assert pt.display_name(p).startswith("نص عربي") and pt.localized(p)["scene_blueprint"][1]["function"].startswith("نص عربي")
    assert p["_edits"][-1]["action"] == "translate" and p["_edits"][-1]["by"] == "ai"
    again = Fake()
    assert i18n.translate_pattern("p1", ask=again)["keys"] == 0 and again.batches == []      # ما بيعيد ولا بيدفع


def test_owner_edit_made_while_waiting_for_the_model_survives(lib):
    put(lib)

    def owner_edits():
        ps.save_edit("p1", {"one_line_summary": "ملخصي أنا"})

    i18n.translate_pattern("p1", ask=Fake(before=owner_edits))
    p = read(lib)
    assert p["ar"]["one_line_summary"] == "ملخصي أنا"                  # ما انكتب فوقه
    assert pt.display_name(p).startswith("نص عربي")                     # والباقي اتترجم


def test_a_list_is_written_only_when_every_item_arrived(lib):
    put(lib)

    def partial(system, user):
        t = json.loads(user)["texts"]
        return {"translations": {k: "نص عربي" for k in t if not k.startswith("objection_handled.1")}}

    res = i18n.translate_pattern("p1", ask=partial)
    p = read(lib)
    assert "objection_handled" not in (p.get("ar") or {})
    assert res["pending"] >= 2                                           # القائمة كاملة لسا ناقصة (بنودها)
    assert "why_it_works" in p["ar"]                                      # قائمة تانية وصلت كاملة


def test_arabic_patterns_are_never_sent(lib):
    ps.create({"pattern_name": "نمط عربي", "framework": "pas", "product_category": "fragrance", "hook": {"type": "سؤال"},
               "scene_blueprint": [{"function": "أ"}, {"function": "ب"}, {"function": "ج"}]})
    pid = ps.list_ids()[0]
    fake = Fake()
    assert i18n.translate_pattern(pid, ask=fake)["keys"] == 0 and fake.batches == []


def test_missing_pattern_is_a_clear_error(lib):
    with pytest.raises(i18n.TranslateError):
        i18n.translate_pattern("nope", ask=Fake())


def test_translate_new_never_raises(lib, capsys):
    put(lib)

    def boom(system, user):
        raise RuntimeError("no key")

    import llm
    orig = llm.complete_json
    llm.complete_json = lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("ما في مفتاح"))
    try:
        i18n.translate_new("p1")
    finally:
        llm.complete_json = orig
    assert "تأجّلت" in capsys.readouterr().out and "ar" not in read(lib)


# ═════════════════ التشغيلة والرجوع ═════════════════
def test_status_and_pending_list(lib):
    put(lib, "a")
    put(lib, "b")
    i18n.translate_pattern("b", ask=Fake())
    assert [pid for pid, _ in i18n.pending_patterns()] == ["a"]
    s = tp.status()
    assert s["patterns"] == 2 and s["pending_patterns"] == 1 and s["pending_keys"] > 5


def test_run_makes_a_backup_with_a_manifest_and_respects_limit(lib):
    for pid in ("a", "b", "c"):
        put(lib, pid)
    res = tp.run(limit=2, ask=Fake())
    assert res["done"] == 2 and res["remaining"] == 1 and res["failed"] == []
    folder = tp.backups_dir() / res["stamp"]
    mf = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert set(mf["files"]) == {"a", "b"} and (folder / "a.pattern.json").exists()
    assert "ar" not in json.loads((folder / "a.pattern.json").read_text(encoding="utf-8"))      # النسخة = قبل الترجمة
    assert tp.run(ask=Fake())["remaining"] == 0                           # التشغيلة التانية بتكمّل الباقي بس
    assert not tp.run(ask=Fake())["stamp"]                                # وما بقي شي


def test_run_with_ids_and_failures_are_reported_and_leave_no_empty_backup(lib):
    put(lib, "a")
    put(lib, "b")

    def fail(system, user):
        raise i18n.TranslateError("المزوّد رفض")

    res = tp.run(ids=["a"], ask=fail)
    assert res["done"] == 0 and res["failed"] == [{"id": "a", "error": "المزوّد رفض"}] and res["stamp"] is None
    assert "ar" not in read(lib, "a") and tp.status()["pending_patterns"] == 2
    assert not tp.backups_dir().exists() or not list(tp.backups_dir().iterdir())          # ما بقي مجلد نسخة فاضي


def test_run_stops_after_three_failures_in_a_row(lib, capsys):
    for pid in "abcde":
        put(lib, pid)
    calls = []

    def fail(system, user):
        calls.append(1)
        raise i18n.TranslateError("مفتاح الـ API مرفوض")

    res = tp.run(ask=fail)
    assert len(res["failed"]) == tp.MAX_FAIL_STREAK == 3 and len(calls) >= 3 and res["remaining"] == 5
    assert "وقفت بعد 3 فشل متتالي" in capsys.readouterr().out


def test_a_success_resets_the_failure_streak(lib):
    for pid in "abcde":
        put(lib, pid)
    plan = iter([False, False, True, False, False])                     # فشل فشل نجاح فشل فشل ← ما بيوصل 3 متتالية

    def flaky(system, user):
        if not next(plan):
            raise i18n.TranslateError("مؤقت")
        return Fake()(system, user)

    res = tp.run(ask=flaky)
    assert res["done"] == 1 and len(res["failed"]) == 4 and res["stamp"]


def test_the_cli_exits_non_zero_when_nothing_was_translated(lib, monkeypatch):
    put(lib, "a")
    monkeypatch.setattr(sys, "argv", ["translate_patterns.py"])
    monkeypatch.setattr(i18n, "_llm_ask", lambda system, user: (_ for _ in ()).throw(i18n.TranslateError("x")))
    with pytest.raises(SystemExit) as e:
        tp.main()
    assert e.value.code == 1


def test_rollback_restores_untouched_files_and_skips_ones_edited_after(lib):
    put(lib, "a")
    put(lib, "b")
    tp.run(ask=Fake())
    ps.save_edit("b", {"one_line_summary": "عدّلته بعد الترجمة"})
    out = tp.rollback()
    assert out["restored"] == ["a"] and out["skipped"] == [{"id": "b", "why": "تعدّل بعد الترجمة — ما انلمس"}]
    assert "ar" not in read(lib, "a")                                      # رجع إنجليزي
    assert read(lib, "b")["ar"]["one_line_summary"] == "عدّلته بعد الترجمة"
    assert tp.status()["pending_patterns"] == 1                            # a رجع ناقص، b ما انلمس


def test_rollback_by_name_and_without_backups(lib, capsys):
    assert tp.rollback() == {"restored": [], "skipped": []}
    put(lib, "a")
    stamp = tp.run(ask=Fake())["stamp"]
    assert tp.latest_stamp() == stamp
    assert tp.rollback(stamp)["restored"] == ["a"]
    with pytest.raises(SystemExit):
        tp.rollback("ar_not_a_real_folder")


def test_task_and_prompt_are_registered():
    import connections
    import llm
    assert "translate" in llm.TASK_LABELS and "translate" in connections.TASK_PROFILE and "translate" in llm.LEGACY_MODEL_KEYS
    from web.app import PROMPT_INFO
    assert PROMPT_INFO["pattern_translator.txt"]["task"] == "translate"
    root = os.path.dirname(os.path.dirname(__file__))
    live = open(os.path.join(root, "prompts", "pattern_translator.txt"), "rb").read()
    assert live == open(os.path.join(root, "prompts", ".defaults", "pattern_translator.txt"), "rb").read()
