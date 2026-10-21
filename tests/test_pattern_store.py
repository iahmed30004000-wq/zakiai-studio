"""طبقة تخزين الأنماط (pattern_store): قفل، كتابة ذرّية، إنشاء، تعديل، أرشفة، وتكامل طابور المراجعة والعناقيد."""

import copy
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config  # noqa: E402
import clusters  # noqa: E402
import pattern_fields as pf  # noqa: E402
import pattern_store as ps  # noqa: E402
import pattern_text as pt  # noqa: E402
import review_queue  # noqa: E402
import taxonomy  # noqa: E402


def fields(**over) -> dict:
    """أقل نمط يدوي صالح (3 مشاهد)."""
    f = {
        "pattern_name": "كشف المكوّنات ببطء", "framework": "ingredient_reveal", "product_category": "fragrance",
        "hook": {"type": "سؤال صادم", "mechanism": "سؤال بيوقف الإبهام"},
        "scene_blueprint": [
            {"function": "الهوك", "duration_sec": 3, "shot_type": "قريبة"},
            {"function": "عرض المنتج", "duration_sec": 20, "shot_type": "متوسطة"},
            {"function": "الدعوة للشراء", "duration_sec": 7, "shot_type": "ثابتة"},
        ],
    }
    f.update(over)
    return f


@pytest.fixture
def lib(tmp_path, monkeypatch):
    pdir, sdir = tmp_path / "patterns", tmp_path / "scripts"
    pdir.mkdir()
    sdir.mkdir()
    monkeypatch.setattr(config, "PATTERNS_DIR", pdir)
    monkeypatch.setattr(config, "SCRIPTS_DIR", sdir)
    monkeypatch.setattr(review_queue, "QUEUE_PATH", tmp_path / "rq.json")
    monkeypatch.setattr(clusters, "CLUSTERS_PATH", tmp_path / "clusters.json")
    return tmp_path


def read(pid, lib, archived=False):
    d = lib / "patterns" / ("_archive" if archived else "")
    return json.loads((d / f"{pid}.pattern.json").read_text(encoding="utf-8"))


# ═════════════════ القفل والكتابة ═════════════════
def test_write_atomic_replaces_and_leaves_no_temp_file(lib):
    f = lib / "patterns" / "a.pattern.json"
    ps.write_atomic(f, {"x": "عربي"})
    ps.write_atomic(f, {"x": "تاني"})
    assert json.loads(f.read_text(encoding="utf-8")) == {"x": "تاني"}
    assert [p.name for p in (lib / "patterns").iterdir()] == ["a.pattern.json"]


def test_lock_busy_gives_423_not_a_hang(lib):
    with ps.locked():
        with pytest.raises(ps.PatternError) as e:
            with ps.locked(timeout=0.3):
                pass
    assert e.value.status == 423
    with ps.locked(timeout=0.3):          # وانفكّ القفل بعد الخروج
        pass


def test_lock_released_even_when_body_raises(lib):
    with pytest.raises(RuntimeError):
        with ps.locked():
            raise RuntimeError("boom")
    with ps.locked(timeout=0.3):
        pass


def test_bad_ids_are_rejected(lib):
    for bad in ("", "../x", "a/b", "a b", "x" * 200):
        with pytest.raises(ps.PatternError):
            ps.archive(bad)
    assert ps.load_any("../x") is None


# ═════════════════ المعرّفات ═════════════════
def test_new_id_avoids_library_and_archive_collisions(lib):
    base = ps.new_id("اسم")
    assert base == "manual_اسم"
    (lib / "patterns" / f"{base}.pattern.json").write_text("{}", encoding="utf-8")
    assert ps.new_id("اسم") == "manual_اسم_2"
    (lib / "patterns" / "_archive").mkdir()
    (lib / "patterns" / "_archive" / "manual_اسم_2.pattern.json").write_text("{}", encoding="utf-8")
    assert ps.new_id("اسم") == "manual_اسم_3"


# ═════════════════ الإنشاء ═════════════════
def test_create_writes_an_authored_pattern_with_arabic_on_top(lib):
    pid = ps.create(fields(), by="سارة")
    p = read(pid, lib)
    assert p["pattern_name"] == "كشف المكوّنات ببطء"                 # العربي هو النص الأول
    assert p["_source"]["type"] == "authored" and p["_source"]["by"] == "سارة"
    assert p["_legacy"] == {}
    assert set(p["_taxonomy"]["locked"]) == {"framework", "product_category", "dialect_or_language"}
    assert p["_edits"][0]["action"] == "create"
    assert [s["slot"] for s in p["scene_blueprint"]] == [1, 2, 3]
    assert p["pacing"]["scene_count"] == 3 and p["pacing"]["total_duration_sec"] == 30
    assert "ar" not in p


def test_create_survives_the_taxonomy_migration(lib):
    """إعادة تشغيل الهجرة ما بترجّع قيم المالك: الحقول المقفولة بتضل متل ما هي."""
    pid = ps.create(fields(framework="demo_proof", dialect_or_language="shami"))
    p = read(pid, lib)
    again, issues = taxonomy.apply_to_pattern(copy.deepcopy(p))
    assert issues == []
    assert again["framework"] == "demo_proof" and again["dialect_or_language"] == "shami"
    assert again["_taxonomy"]["locked"] == p["_taxonomy"]["locked"]


def test_create_reports_every_error_as_a_list(lib):
    with pytest.raises(ps.PatternError) as e:
        ps.create({"pattern_name": "", "scene_blueprint": [{"function": "x"}]})
    assert e.value.status == 400
    fl = {x["field"] for x in e.value.detail}
    assert {"pattern_name", "framework", "product_category", "hook.type", "scene_blueprint"} <= fl
    assert ps.list_ids() == []


def test_create_reclusters_without_deadlock(lib):
    """_recluster بياخد القفل بنفسه بعد ما create يفكّ قفله، ولو فشل بيبلعه، فبنتأكد إنو فعلاً اشتغل."""
    pid = ps.create(fields())
    assert read(pid, lib).get("cluster_id")
    assert (lib / "clusters.json").exists()


def test_two_creates_with_the_same_name_get_different_ids(lib):
    a, b = ps.create(fields()), ps.create(fields())
    assert a != b and sorted(ps.list_ids()) == sorted([a, b])


# ═════════════════ التعديل ═════════════════
def test_edit_puts_text_in_ar_and_numbers_on_top(lib):
    pid = ps.create(fields())
    v = ps.view(pid)
    out = ps.save_edit(pid, {"one_line_summary": "ملخص جديد", "reusability_score": 8}, base_rev=v["rev"], by="سارة")
    p = read(pid, lib)
    assert p["ar"]["one_line_summary"] == "ملخص جديد"
    assert p["reusability_score"] == 8
    assert "one_line_summary" in out["changed"] and "reusability_score" in out["changed"]
    last = p["_edits"][-1]
    assert last["action"] == "edit" and last["by"] == "سارة" and "one_line_summary" in last["fields"]
    assert ps.view(pid)["fields"]["one_line_summary"] == "ملخص جديد"


def test_edit_without_change_does_not_add_history(lib):
    pid = ps.create(fields())
    ps.save_edit(pid, {"pattern_name": "كشف المكوّنات ببطء"})
    assert len(read(pid, lib)["_edits"]) == 1


def test_saving_every_field_unchanged_adds_nothing_to_ar(lib):
    """المحرّر بيبعت كل الحقول؛ النص اللي ما اتغيّر ما بيدخل ar (وإلا الترجمة بتتخطّاه)."""
    pid = ps.create(fields())
    p = read(pid, lib)
    p["pattern_name"], p["ar"] = "English name", {}
    ps.write_atomic(lib / "patterns" / f"{pid}.pattern.json", p)
    v = ps.view(pid)
    assert ps.save_edit(pid, v["fields"], base_rev=v["rev"])["changed"] == []
    q = read(pid, lib)
    assert "ar" not in q or q["ar"] == {}
    assert pt.missing_ar_keys(q) == pt.missing_ar_keys(p)


def test_edit_with_stale_revision_is_409_and_changes_nothing(lib):
    pid = ps.create(fields())
    rev0 = ps.view(pid)["rev"]
    ps.save_edit(pid, {"one_line_summary": "من موظف أول"}, base_rev=rev0)
    with pytest.raises(ps.PatternError) as e:
        ps.save_edit(pid, {"one_line_summary": "من موظف تاني"}, base_rev=rev0)
    assert e.value.status == 409
    assert read(pid, lib)["ar"]["one_line_summary"] == "من موظف أول"


def test_edit_of_missing_or_archived_pattern_is_404(lib):
    with pytest.raises(ps.PatternError) as e:
        ps.save_edit("nope", {"one_line_summary": "x"})
    assert e.value.status == 404
    pid = ps.create(fields())
    ps.archive(pid)
    with pytest.raises(ps.PatternError) as e:
        ps.save_edit(pid, {"one_line_summary": "x"})
    assert e.value.status == 404 and "مؤرشف" in str(e.value)


def test_edit_validation_errors_come_back_as_a_list(lib):
    pid = ps.create(fields())
    with pytest.raises(ps.PatternError) as e:
        ps.save_edit(pid, {"framework": "مش موجود", "reusability_score": 99})
    assert e.value.status == 400 and {x["field"] for x in e.value.detail} == {"framework", "reusability_score"}


def test_closing_a_value_locks_it_and_closes_its_review_items(lib):
    pid = ps.create(fields())
    p = read(pid, lib)
    p["_taxonomy"] = {"version": 1, "complete": False}                    # كأنو نمط مستخرج منه بنود مراجعة
    ps.write_atomic(lib / "patterns" / f"{pid}.pattern.json", p)
    review_queue.add("framework", pid, "x | y", ["demo_proof"])
    review_queue.add("dialect", pid, "غريب", [])
    assert review_queue.open_count(pid) == 2
    ps.save_edit(pid, {"framework": "demo_proof"}, by="سارة")
    q = read(pid, lib)
    assert q["framework"] == "demo_proof" and "framework" in q["_taxonomy"]["locked"]
    assert review_queue.open_count(pid) == 1                              # بند اللهجة لسا مفتوح
    assert q["_taxonomy"]["complete"] is False                             # وما اتسكّر لأنو ما اتحسم
    ps.save_edit(pid, {"dialect_or_language": "shami"})
    assert review_queue.open_count(pid) == 0
    assert read(pid, lib)["_taxonomy"]["complete"] is True


def test_saving_the_whole_form_without_touching_closed_values_decides_nothing(lib):
    """المحرّر بيبعت كل الحقول؛ تعديل الملخص ما بيسكّر بنود المراجعة ولا بيقفل الإطار/الفئة/اللهجة."""
    pid = ps.create(fields())
    p = read(pid, lib)
    p["_taxonomy"] = {"version": 1, "complete": False}                    # نمط مستخرج بانتظار مراجعة
    ps.write_atomic(lib / "patterns" / f"{pid}.pattern.json", p)
    review_queue.add("framework", pid, "x | y", ["demo_proof"])
    review_queue.add("dialect", pid, "غريب", [])
    v = ps.view(pid)
    ps.save_edit(pid, {**v["fields"], "one_line_summary": "ملخص جديد"}, base_rev=v["rev"])
    q = read(pid, lib)
    assert q["ar"]["one_line_summary"] == "ملخص جديد"
    assert review_queue.open_count(pid) == 2 and "locked" not in q["_taxonomy"] and q["_taxonomy"]["complete"] is False


def test_changing_dialect_clears_a_sub_dialect_that_no_longer_fits(lib):
    sub, (_, parent) = next(iter(taxonomy.DIALECT_SUBS.items()))
    other = next(k for k in taxonomy.DIALECTS if k != parent)
    pid = ps.create(fields(dialect_or_language=parent, dialect_sub=sub))
    assert read(pid, lib)["dialect_sub"] == sub
    ps.save_edit(pid, {"dialect_or_language": other})
    assert read(pid, lib)["dialect_sub"] is None


def test_scene_edit_keeps_scene_texts_and_updates_pacing(lib):
    pid = ps.create(fields())
    rows = ps.view(pid)["fields"]["scene_blueprint"]
    rows[1]["function"] = "عرض المنتج بالتفصيل"
    rows.append({"function": "مشهد رابع", "duration_sec": 5, "_k": None})
    ps.save_edit(pid, {"scene_blueprint": rows})
    p = read(pid, lib)
    assert p["pacing"]["scene_count"] == 4
    assert [s["function"] for s in pt.editable(p)["scene_blueprint"]] == ["الهوك", "عرض المنتج بالتفصيل", "الدعوة للشراء", "مشهد رابع"]


def test_edit_history_is_capped(lib, monkeypatch):
    monkeypatch.setattr(ps, "HISTORY_MAX", 5)
    pid = ps.create(fields())
    for i in range(9):
        ps.save_edit(pid, {"one_line_summary": f"نسخة {i}"})
    h = read(pid, lib)["_edits"]
    assert len(h) == 5 and h[-1]["action"] == "edit" and h[-1]["after"]["one_line_summary"] == "نسخة 8"
    assert ps.HISTORY_MAX == 5 and h[0]["action"] == "edit"                 # الأقدم (create) انشال


def test_edit_keeps_keys_outside_the_schema(lib):
    pid = ps.create(fields())
    p = read(pid, lib)
    p["cta"] = {"type": "طلب مباشر", "extra_key": "خلّيني"}
    ps.write_atomic(lib / "patterns" / f"{pid}.pattern.json", p)
    ps.save_edit(pid, {"cta": {"wording_style": "رقم بس"}})
    q = read(pid, lib)
    assert q["cta"]["extra_key"] == "خلّيني" and q["cta"]["type"] == "طلب مباشر"


# ═════════════════ الأرشفة ═════════════════
def test_archive_moves_the_file_and_old_scripts_still_find_it(lib):
    pid = ps.create(fields())
    (lib / "scripts" / "s1.json").write_text(json.dumps({"_meta": {"pattern_id": pid, "display_name": "سكريبت 1"}}), encoding="utf-8")
    (lib / "scripts" / "s2.json").write_text(json.dumps({"_meta": {"pattern_id": "other"}}), encoding="utf-8")
    (lib / "scripts" / "bad.json").write_text("{not json", encoding="utf-8")
    out = ps.archive(pid, by="سارة")
    assert out["refs"] == {"count": 1, "names": ["سكريبت 1"]}
    assert ps.list_ids() == [] and ps.load(pid) is None
    assert ps.is_archived(pid)
    p = ps.load_any(pid)
    assert p["pattern_name"] == "كشف المكوّنات ببطء" and p["_edits"][-1]["action"] == "archive"
    assert ps.list_archived()[0]["id"] == pid and ps.list_archived()[0]["by"] == "سارة"


def test_archive_closes_open_review_items(lib):
    pid = ps.create(fields())
    review_queue.add("dialect", pid, "غريب", [])
    ps.archive(pid)
    assert review_queue.open_count(pid) == 0
    assert review_queue.list_items(status="dismissed")[0]["pattern_id"] == pid


def test_archive_and_restore_errors(lib):
    with pytest.raises(ps.PatternError) as e:
        ps.archive("nope")
    assert e.value.status == 404
    with pytest.raises(ps.PatternError) as e:
        ps.restore("nope")
    assert e.value.status == 404
    pid = ps.create(fields())
    ps.archive(pid)
    clash = lib / "patterns" / f"{pid}.pattern.json"
    clash.write_text("{}", encoding="utf-8")
    with pytest.raises(ps.PatternError) as e:
        ps.restore(pid)
    assert e.value.status == 409


def test_restore_puts_it_back_with_its_history(lib):
    pid = ps.create(fields())
    ps.archive(pid)
    ps.restore(pid, by="سارة")
    p = read(pid, lib)
    assert [e["action"] for e in p["_edits"]] == ["create", "archive", "restore"]
    assert not ps.is_archived(pid) and ps.list_archived() == []


# ═════════════════ التشابه ═════════════════
def test_similar_flags_the_same_name_even_when_text_differs(lib):
    pid = ps.create(fields())
    hits = ps.similar(fields(hook={"type": "رقم", "mechanism": "x"}, scene_blueprint=fields()["scene_blueprint"]))
    assert hits and hits[0]["pattern_id"] == pid and hits[0]["same_name"] is True
    other = ps.similar(fields(pattern_name="اسم مختلف تماماً", hook={"type": "x"}, scene_blueprint=[
        {"function": "a"}, {"function": "b"}, {"function": "c"}], framework="problem_solution", product_category="gadgets"))
    assert not any(m["same_name"] for m in other)


# ═════════════════ طابور المراجعة والتصنيف ═════════════════
def test_queue_resolve_locks_the_decided_field(lib):
    f = lib / "patterns" / "p1.pattern.json"
    f.write_text(json.dumps({"framework": "a | b", "_legacy": {"framework": "a | b"}, "_taxonomy": {"version": 1, "complete": False}}), encoding="utf-8")
    it = review_queue.add("framework", "p1", "a | b", ["demo_proof", "ingredient_reveal"])
    review_queue.resolve(it["id"], "demo_proof", "ingredient_reveal")
    p = json.loads(f.read_text(encoding="utf-8"))
    assert p["framework"] == "demo_proof" and p["framework_secondary"] == "ingredient_reveal"
    assert "framework" in p["_taxonomy"]["locked"] and p["_taxonomy"]["complete"] is True
    again, issues = taxonomy.apply_to_pattern(copy.deepcopy(p))
    assert again["framework"] == "demo_proof"                            # الهجرة ما بترجّع الإطار القديم
    assert not [i for i in issues if i["kind"] in ("framework", "framework_order")]
    assert [x for x in os.listdir(lib / "patterns") if x.endswith(".tmp")] == []


def test_clusters_apply_writes_tags_without_losing_owner_edits(lib):
    pid = ps.create(fields())
    ps.save_edit(pid, {"one_line_summary": "عدّلته إيدي"})
    clusters.apply()
    p = read(pid, lib)
    assert p["ar"]["one_line_summary"] == "عدّلته إيدي" and p["cluster_role"] == "primary"
    assert p["_edits"][-1]["action"] == "edit"


def test_clusters_apply_waits_for_the_lock_then_writes(lib):
    pid = ps.create(fields())
    p = read(pid, lib)
    p.pop("cluster_id"), p.pop("cluster_role")
    ps.write_atomic(lib / "patterns" / f"{pid}.pattern.json", p)
    done = []
    with ps.locked():
        t = threading.Thread(target=lambda: done.append(clusters.apply()))
        t.start()
        time.sleep(0.4)
        assert not done and "cluster_id" not in read(pid, lib)         # لسا واقف عالقفل
    t.join(10)
    assert done and read(pid, lib)["cluster_id"]
