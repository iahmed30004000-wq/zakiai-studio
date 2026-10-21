"""المرحلة 4 — حلقة المراجعة وإعادة الكتابة، بوابة الإنتاج، نسخ السيناريو."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, api_client, make_script, review_ok  # noqa: E402

import config  # noqa: E402
import review_loop  # noqa: E402
import review_script  # noqa: E402
import script_versions  # noqa: E402
import stage3_generate  # noqa: E402

BAD_CTA = "اطلب الآن وادفع عند الاستلام فهو شفاء بإذن الله"     # «شفاء» ← blocker بالكود
GOOD_CTA = "اطلب الآن وادفع عند الاستلام بلا مخاطرة"


def blocker_finding(text="ادعاء مبالغ"):
    return {"severity": "blocker", "scene": None, "field": "cta_line", "issue": text,
            "evidence": "x", "fix": "y"}


def setup_write(env):
    env.pattern("p1")
    return env.product()


def read_script(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ─────────────────────── الحلقة ───────────────────────


def test_revise_then_rewrite_then_approve(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(hook="هوك النسخة الأولى", cta=BAD_CTA),
                   make_script(hook="هوك النسخة الثانية", cta=GOOD_CTA, salt=3))
    # الموديل نفسه يوافق بالمرة الأولى — الكود بيمسك «شفاء» ويقلبها revise
    env.fake.queue("reviewer", review_ok("approve"), review_ok("approve"))

    path = stage3_generate.write_for_product(product, "p1", review=True)

    s = read_script(path)
    assert s["_meta"]["status"] == "approved"
    assert s["_meta"]["version"] == 2 and s["_meta"]["script_id"] == "VP-testp-1-v2"
    assert s["hook_line"] == "هوك النسخة الثانية" and s["_meta"]["approved_by"] == "auto"
    assert env.fake.count("writer") == 2 and env.fake.count("reviewer") == 2
    assert path.name.count("__") == 2                      # اسم الملف ما تغيّر

    review = json.loads((env.lib / "reviews" / f"{path.stem}.review.json").read_text(encoding="utf-8"))
    assert review["blockers"] == 0 and review["rounds"] == 1
    assert [h["blockers"] > 0 for h in review["history"]] == [True, False]
    assert review["script_hash"] == script_versions.content_hash(s)
    assert review_loop.is_cleared(path)[0] is True

    # رسالة إعادة الكتابة: المسودة السابقة + الملاحظات + أمر الإصلاح
    msg = env.fake.user("writer", 1)
    assert "## PREVIOUS DRAFT AND REVIEWER FEEDBACK" in msg
    assert "هوك النسخة الأولى" in msg.split("## PREVIOUS DRAFT AND REVIEWER FEEDBACK")[1]
    assert "شفاء" in msg.split("### REVIEWER FEEDBACK")[1]
    assert "blocker or major" in msg and "Keep what already works" in msg
    assert "## HARD RULES FROM BRIEF" in msg
    assert "## PREVIOUS DRAFT" not in env.fake.user("writer", 0)      # الكتابة الأولى بلا هالقسم


def test_clean_first_review_approves_without_rewrite(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    path = stage3_generate.write_for_product(product, "p1")
    s = read_script(path)
    assert s["_meta"]["status"] == "approved" and s["_meta"]["version"] == 1
    assert env.fake.count("writer") == 1


def test_revise_with_only_majors_rewrites_and_approves(env):
    product = setup_write(env)
    major = {"severity": "major", "scene": 1, "field": "hook_line", "issue": "هوك ضعيف",
             "evidence": "x", "fix": "y"}
    env.fake.queue("writer", make_script(hook="ضعيف"), make_script(hook="أقوى", salt=2))
    env.fake.queue("reviewer", review_ok("revise", [major]), review_ok("approve"))
    path = stage3_generate.write_for_product(product, "p1")
    s = read_script(path)
    assert s["_meta"]["status"] == "approved" and s["_meta"]["version"] == 2


def test_two_rounds_without_resolution_goes_to_owner(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(cta=BAD_CTA))              # بيكرّر نفس الغلط دايماً
    env.fake.queue("reviewer", review_ok("revise", [blocker_finding("مبالغة بالوعد")]))

    path = stage3_generate.write_for_product(product, "p1")

    s = read_script(path)
    assert config.SCRIPT_MAX_REVIEW_ROUNDS == 2
    assert s["_meta"]["status"] == "needs_owner"
    assert "2" in s["_meta"]["status_reason"] and "عائق" in s["_meta"]["status_reason"]
    assert env.fake.count("writer") == 3 and env.fake.count("reviewer") == 3   # كتابة + 2 إعادة، 3 مراجعات
    assert s["_meta"]["version"] == 3
    ok, reason = review_loop.is_cleared(path)
    assert ok is False and "عائق" in reason
    st = review_loop.status(path)
    assert st["status"] == "needs_owner" and st["approved"] is False and st["rounds"] == 2
    assert st["blockers"] >= 1 and st["reason"]


def test_rounds_limit_comes_from_config(env, monkeypatch):
    product = setup_write(env)
    monkeypatch.setattr(config, "SCRIPT_MAX_REVIEW_ROUNDS", 1)
    env.fake.queue("writer", make_script(cta=BAD_CTA))
    env.fake.queue("reviewer", review_ok("revise", [blocker_finding()]))
    path = stage3_generate.write_for_product(product, "p1")
    assert env.fake.count("writer") == 2
    assert read_script(path)["_meta"]["status"] == "needs_owner"


def test_rewrite_failure_escalates_instead_of_crashing(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(cta=BAD_CTA), lambda call: (_ for _ in ()).throw(
        __import__("llm").LLMError("انقطع الاتصال")))
    env.fake.queue("reviewer", review_ok("revise"))
    path = stage3_generate.write_for_product(product, "p1")
    s = read_script(path)
    assert s["_meta"]["status"] == "needs_owner" and "انقطع الاتصال" in s["_meta"]["status_reason"]


def test_reviewer_failure_leaves_draft_without_crash(env):
    import llm
    product = setup_write(env)
    env.fake.queue("writer", make_script())
    env.fake.queue("reviewer", lambda call: (_ for _ in ()).throw(llm.LLMError("رصيد منتهي")))
    path = stage3_generate.write_for_product(product, "p1")
    s = read_script(path)
    assert s["_meta"]["status"] == "draft" and "رصيد منتهي" in s["_meta"]["status_reason"]
    assert review_loop.is_cleared(path)[0] is False


# ─────────────────────── الموافقة اليدوية ───────────────────────


def _needs_owner_script(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(cta=BAD_CTA))
    env.fake.queue("reviewer", review_ok("revise"))
    return stage3_generate.write_for_product(product, "p1")


def test_manual_approve_only_when_blockers_zero(env):
    path = _needs_owner_script(env)
    c = api_client()
    r = c.post(f"/api/scripts/{path.name}/approve")
    assert r.status_code == 409 and "عائق" in r.json()["detail"]
    assert read_script(path)["_meta"]["status"] == "needs_owner"

    # المالك بيصلّح النص بإيده ثم بيعيد المراجعة
    s = read_script(path)
    s["cta_line"] = GOOD_CTA
    path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert c.post(f"/api/scripts/{path.name}/approve").status_code == 409     # المراجعة قديمة
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(path)
    assert review_loop.is_cleared(path)[0] is False          # لسا needs_owner لحد الموافقة
    r = c.post(f"/api/scripts/{path.name}/approve").json()
    assert r["ok"] is True and r["status"] == "approved" and r["approved"] is True
    assert review_loop.is_cleared(path)[0] is True


def test_approve_endpoint_missing_review_and_missing_file(env):
    env.product()
    p = env.script_file("x.json", make_script())
    c = api_client()
    assert c.post("/api/scripts/x.json/approve").status_code == 409
    assert c.post("/api/scripts/nope.json/approve").status_code == 404


# ─────────────────────── بوابة الصور والصوت ───────────────────────


def test_is_cleared_requires_a_review(env):
    env.product()
    p = env.script_file("a.json", make_script())
    ok, reason = review_loop.is_cleared(p)
    assert ok is False and "ما انراجع" in reason


def test_is_cleared_passes_with_clean_matching_review(env):
    env.product()
    p = env.script_file("a.json", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(p)
    assert review_loop.is_cleared(p)[0] is True


def test_is_cleared_blocks_review_with_blockers(env):
    env.product()
    p = env.script_file("a.json", make_script(cta=BAD_CTA))
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(p)
    ok, reason = review_loop.is_cleared(p)
    assert ok is False and "عائق" in reason


def test_is_cleared_blocks_stale_review_after_edit(env):
    env.product()
    p = env.script_file("a.json", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(p)
    assert review_loop.is_cleared(p)[0] is True
    s = read_script(p)
    s["scenes"][2]["voiceover"] += " زيادة"
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    ok, reason = review_loop.is_cleared(p)
    assert ok is False and "انعدّل" in reason
    assert review_loop.status(p)["approved"] is False


def test_is_cleared_blocks_legacy_review_without_hash(env):
    env.product()
    p = env.script_file("a.json", make_script())
    (env.lib / "reviews").mkdir()
    (env.lib / "reviews" / "a.review.json").write_text(
        json.dumps({"verdict": "approve", "blockers": 0, "findings": []}), encoding="utf-8")
    ok, reason = review_loop.is_cleared(p)
    assert ok is False and "بصمة" in reason


def test_status_change_does_not_stale_the_review(env):
    env.product()
    p = env.script_file("a.json", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(p)
    review_loop._set_meta(p, status="approved", edited_at="2026-01-01")
    assert review_loop.is_cleared(p)[0] is True


def _run_main(module, monkeypatch, script):
    monkeypatch.setattr(sys, "argv", [module.__name__ + ".py", str(script)])
    return module.main


def test_generate_images_refuses_without_review(env, monkeypatch):
    import generate_images
    env.product()
    p = env.script_file("a.json", make_script())
    with pytest.raises(SystemExit) as ei:
        _run_main(generate_images, monkeypatch, p)()
    assert "ما بيشتغل" in str(ei.value.code) and "ما انراجع" in str(ei.value.code)


def test_generate_voice_refuses_stale_review(env, monkeypatch):
    import generate_voice
    env.product()
    p = env.script_file("a.json", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(p)
    s = read_script(p)
    s["hook_line"] = "هوك اتغيّر بعد المراجعة"
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        _run_main(generate_voice, monkeypatch, p)()
    assert "انعدّل بعد آخر مراجعة" in str(ei.value.code)


class _Passed(Exception):
    pass


def test_gates_let_a_cleared_script_through(env, monkeypatch):
    import generate_images
    import generate_voice
    env.product()
    p = env.script_file("a.json", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(p)

    def sentinel(*a, **k):
        raise _Passed()

    import voice_studio
    monkeypatch.setattr(generate_images.imagegen, "image_config", sentinel)
    monkeypatch.setattr(generate_voice.tts, "tts_config", sentinel)
    # الصور بتحتاج كمان فويس أوفر معتمد (الصوت هو الساعة)
    with pytest.raises(SystemExit):
        _run_main(generate_images, monkeypatch, p)()
    monkeypatch.setattr(voice_studio, "voice_is_approved", lambda path: (True, ""))
    with pytest.raises(_Passed):
        _run_main(generate_images, monkeypatch, p)()
    with pytest.raises(_Passed):
        _run_main(generate_voice, monkeypatch, p)()


# ─────────────────────── النسخ والفرق ───────────────────────


def test_versions_saved_and_diffs_per_scene_field(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(hook="هوك قديم", cta=BAD_CTA),
                   make_script(hook="هوك جديد", cta=GOOD_CTA, salt=4))
    env.fake.queue("reviewer", review_ok("approve"))
    path = stage3_generate.write_for_product(product, "p1")

    vdir = env.scripts / "versions" / path.stem
    assert sorted(f.name for f in vdir.glob("v*.json")) == ["v1.json", "v2.json"]
    v1 = json.loads((vdir / "v1.json").read_text(encoding="utf-8"))
    assert v1["hook_line"] == "هوك قديم" and v1["_meta"]["script_id"] == "VP-testp-1-v1"

    c = api_client()
    d = c.get(f"/api/scripts/{path.name}/versions").json()
    assert [(v["version"], v["script_id"], v["status"]) for v in d["versions"]] == [
        (1, "VP-testp-1-v1", "superseded"), (2, "VP-testp-1-v2", "approved")]
    assert d["versions"][0]["file"].endswith("v1.json") and d["versions"][1]["file"] == path.name
    diff = d["diffs"][0]
    assert (diff["from"], diff["to"]) == (1, 2)
    fields = {(ch["scene"], ch["field"]) for ch in diff["changes"]}
    assert (None, "hook_line") in fields and (None, "cta_line") in fields
    assert (3, "voiceover") in fields and (1, "visual") in fields
    hook = next(ch for ch in diff["changes"] if ch["field"] == "hook_line")
    assert hook["before"] == "هوك قديم" and hook["after"] == "هوك جديد" and 0 <= hook["similarity"] < 1


def test_diff_ignores_whitespace_only_changes():
    a = make_script()
    b = json.loads(json.dumps(a, ensure_ascii=False))
    b["scenes"][0]["voiceover"] = "  " + b["scenes"][0]["voiceover"].replace(" ", "  ")
    b["scenes"][1]["duration_sec"] = 6.5
    ch = script_versions.diff_scripts(a, b)
    assert [(c["scene"], c["field"]) for c in ch] == [(2, "duration_sec")]


def test_versions_of_legacy_script_shows_single_live_version(env):
    env.product()
    p = env.script_file("legacy.json", make_script(), meta={"product": "TESTP", "number": 3})
    d = api_client().get("/api/scripts/legacy.json/versions").json()
    assert len(d["versions"]) == 1 and d["versions"][0]["version"] == 1 and d["diffs"] == []


def test_rewrite_does_not_ban_its_own_previous_hook(env):
    product = setup_write(env)
    # سيناريو سابق لنفس المنتج + سيناريو لمنتج تاني
    env.script_file("older.json", make_script(hook="هوك من سيناريو تاني", salt=9, title="عنوان قديم"),
                    meta={"product": "TESTP", "number": 1, "pattern_id": "p1", "version": 1})
    env.script_file("other.json", make_script(hook="هوك منتج ثاني تماماً"),
                    meta={"product": "OTHER", "number": 1})
    env.fake.queue("writer", make_script(hook="هوك النسخة 1", cta=BAD_CTA),
                   make_script(hook="هوك النسخة 2", salt=5))
    env.fake.queue("reviewer", review_ok("approve"))
    path = stage3_generate.write_for_product(product, "p1")

    def used_of(msg):
        tail = msg.split("## ALREADY USED — DO NOT REPEAT ANY OF THESE\n", 1)[1]
        obj, _ = json.JSONDecoder().raw_decode(tail)
        return obj

    first, second = used_of(env.fake.user("writer", 0)), used_of(env.fake.user("writer", 1))
    assert "هوك من سيناريو تاني" in first["hooks"] and "هوك النسخة 1" not in first["hooks"]
    assert "هوك من سيناريو تاني" in second["hooks"]                   # سيناريوهات المنتج التانية بتمنع
    assert "هوك النسخة 1" not in second["hooks"]                      # نسخته السابقة لا
    assert "هوك منتج ثاني تماماً" in second["hooks_used_on_other_products"]
    # بعد إعادة الكتابة السجل بيحمل هوك النسخة الجديدة بس
    reg = json.loads(config.REGISTRY_PATH.read_text(encoding="utf-8"))["TESTP"]
    assert "هوك النسخة 2" in reg["hooks"] and "هوك النسخة 1" not in reg["hooks"]


def test_new_script_after_rewrite_still_bans_the_final_hook(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(hook="الهوك الأول", cta=BAD_CTA),
                   make_script(hook="الهوك النهائي", salt=1), make_script(hook="هوك سيناريو ثاني", salt=2))
    env.fake.queue("reviewer", review_ok("approve"))
    stage3_generate.write_for_product(product, "p1")
    stage3_generate.write_for_product(product, "p1")
    tail = env.fake.user("writer", 2).split("## ALREADY USED — DO NOT REPEAT ANY OF THESE\n", 1)[1]
    used, _ = json.JSONDecoder().raw_decode(tail)
    assert "الهوك النهائي" in used["hooks"] and "الهوك الأول" not in used["hooks"]


def test_second_script_gets_next_number_and_id(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script(hook="أ"), make_script(hook="ب", salt=1))
    env.fake.queue("reviewer", review_ok("approve"))
    a = stage3_generate.write_for_product(product, "p1")
    b = stage3_generate.write_for_product(product, "p1")
    assert a != b                                             # حتى بنفس الدقيقة والنمط
    assert read_script(a)["_meta"]["script_id"] == "VP-testp-1-v1"
    assert read_script(b)["_meta"]["script_id"] == "VP-testp-2-v1"


# ─────────────────────── endpoints الحلقة ───────────────────────


def test_review_loop_endpoint_starts_job(env):
    env.product()
    p = env.script_file("a.json", make_script())
    r = api_client().post("/api/scripts/a.json/review-loop").json()
    assert r == {"job_id": "job1"}
    assert env.jobs[0]["cmd"] == ["review_loop.py", str(p)] and env.jobs[0]["kind"] == "review"
    assert api_client().post("/api/scripts/none.json/review-loop").status_code == 404


def test_status_endpoint_shapes(env):
    env.product()
    env.script_file("a.json", make_script())
    c = api_client()
    st = c.get("/api/scripts/a.json/status").json()
    assert st["status"] == "draft" and st["approved"] is False and st["blockers"] is None
    assert st["rounds"] == 0 and "reason" in st
    env.fake.queue("reviewer", review_ok("approve"))
    review_script.review(env.scripts / "a.json")
    st = c.get("/api/scripts/a.json/status").json()
    assert st["blockers"] == 0 and st["approved"] is True and st["reviewed"] is True


def test_status_reports_draft_when_approved_script_was_edited(env):
    product = setup_write(env)
    env.fake.queue("writer", make_script())
    env.fake.queue("reviewer", review_ok("approve"))
    path = stage3_generate.write_for_product(product, "p1")
    assert review_loop.status(path)["status"] == "approved"
    s = read_script(path)
    s["cta_line"] = "غيّرتها بإيدي"
    path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    st = review_loop.status(path)
    assert st["status"] == "draft" and st["approved"] is False


def test_loop_cli_exit_codes(env, monkeypatch):
    product = setup_write(env)
    env.fake.queue("writer", make_script(cta=BAD_CTA))
    env.fake.queue("reviewer", review_ok("revise", [blocker_finding()]))
    path = stage3_generate.write_for_product(product, "p1", review=False)
    assert read_script(path)["_meta"]["status"] == "draft"
    monkeypatch.setattr(sys, "argv", ["review_loop.py", str(path)])
    with pytest.raises(SystemExit) as ei:
        review_loop.main()
    assert "قرار المالك" in str(ei.value.code)
    assert read_script(path)["_meta"]["status"] == "needs_owner"
