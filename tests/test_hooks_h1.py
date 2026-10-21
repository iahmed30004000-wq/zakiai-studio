"""الهوكات (المرحلة 3أ): الكاتب بيطلّع 3–5، المراجعة بتمرّ عليهم كلهم، وواجهة برمجية لاختيار/تعديل/حذف/توليد هوك."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script, review_ok  # noqa: E402,F401

import hook_writer  # noqa: E402
import review_loop  # noqa: E402
import review_script  # noqa: E402
import script_hooks as sh  # noqa: E402
import script_versions  # noqa: E402
import stage3_generate  # noqa: E402

HOOK = "تعبانة من جفاف عينك؟"
REST = "جرّبي قطرة بتريّح عينك من أول يوم بدون حرقة أبداً"          # 10 كلمات: مع هوك 4–6 كلمات المشهد 1 (6ث) بيضل بمدى النطق
ALTS = [
    ("number", "٣ من ٥ أشخاص عيونهم بتتعب", "٣ من ٥", "أرقام فوق وجه"),
    ("life_moment", "الساعة ١٢ وعينك لسا بالشاشة", "١٢ بالليل", "غرفة معتمة وشاشة"),
    ("contrarian", "نظرك مش ضعيف عينك جافة", "", "لقطة قريبة للعين"),
    ("visual_shock", "شوفي شو بيصير لعينك بعد يوم", "", "مقارنة قريبة"),
]


def writer_script(n=3, **over):
    s = make_script(hook=HOOK)
    s["scenes"][0]["voiceover"] = f"{HOOK} {REST}"
    s["scenes"][0]["on_screen_text"] = "جفاف العين"
    s["scenes"][0]["visual"] = "وجه امرأة تفرك عينها"
    s["hooks"] = [{"id": "h1", "type": "question", "spoken": HOOK, "on_screen_text": "جفاف العين", "visual": "وجه امرأة تفرك عينها", "why": "سؤال مباشر"}] + [
        {"id": f"h{i}", "type": t, "spoken": sp, "on_screen_text": ost, "visual": vis, "why": "سبب"}
        for i, (t, sp, ost, vis) in enumerate(ALTS[:max(0, n - 1)], 2)]
    s.update(over)
    return s


def hooked(env, name="s1.json", n=3, status="approved", **over):
    if not (env.products / "testp.json").exists():
        env.product("testp.json")                                  # بريف المنتج لازم يكون موجود (وإلا المراجع بيعلّم «ما لقيت البريف»)
    s = sh.normalize(writer_script(n, **over), n)
    meta = {"product": "TESTP", "product_file": "testp.json", "product_code": "testp", "number": 1, "version": 1,
            "script_id": "VP-testp-1-v1", "pattern_id": "p1", "status": status, "hooks_requested": n,
            "content_hash": script_versions.content_hash(s)}
    return env.script_file(name, s, meta=meta)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def api(env):
    from fastapi.testclient import TestClient
    from web.app import app
    env.product("testp.json")
    c = TestClient(app)
    c.env = env
    return c


# ═════════════════ الكاتب ═════════════════
def test_the_writer_is_asked_for_n_hooks_and_the_reply_is_normalized_and_saved(env):
    env.pattern("p1")
    path = env.product()
    env.fake.queue("writer", writer_script(4))
    out = stage3_generate.write_for_product(path, "p1", review=False, hooks=4)
    s = read(out)
    system = env.fake.calls[-1]["system"]
    assert "write 4 different opening hooks" in system and "{{HOOKS}}" not in system and "exactly 4 entries" in system
    assert [h["id"] for h in s["hooks"]] == ["h1", "h2", "h3", "h4"] and s["hook_main"] == "h1" and s["hook_line"] == HOOK
    assert s["_meta"]["hooks_requested"] == 4 and s["scenes"][0]["voiceover"].startswith(HOOK)


def test_the_default_is_three_hooks_and_a_hookless_reply_stays_a_single_hook_script(env):
    env.pattern("p1")
    path = env.product()
    env.fake.queue("writer", writer_script(5), make_script())
    out = stage3_generate.write_for_product(path, "p1", review=False)
    assert "write 3 different opening hooks" in env.fake.calls[-1]["system"]
    assert len(read(out)["hooks"]) == 3                                        # الزيادة (5) انقصّت لـ 3
    out2 = stage3_generate.write_for_product(path, "p1", review=False)
    s2 = read(out2)
    assert "hooks" not in s2 and s2["_meta"]["hooks_requested"] == 3 and sh.hooks_of(s2)[0]["spoken"] == s2["hook_line"]


def test_every_hook_goes_into_the_no_repeat_registry(env):
    env.pattern("p1")
    path = env.product()
    env.fake.queue("writer", writer_script(3))
    stage3_generate.write_for_product(path, "p1", review=False, hooks=3)
    used = stage3_generate.used_for("TESTP")
    assert HOOK in used["hooks"] and ALTS[0][1] in used["hooks"] and ALTS[1][1] in used["hooks"]


def test_a_rewrite_keeps_the_same_number_of_hooks_and_a_legacy_script_stays_single(env):
    env.pattern("p1")
    env.product()
    p3 = hooked(env, "three.json", 3, status="draft")
    env.fake.queue("writer", writer_script(3, title="بعد الإعادة"))
    stage3_generate.rewrite_from_review(p3, {"verdict": "revise", "findings": []})
    assert "write 3 different opening hooks" in env.fake.calls[-1]["system"] and len(read(p3)["hooks"]) == 3
    legacy = env.script_file("legacy.json", make_script(), meta={"product": "TESTP", "product_file": "testp.json", "number": 2, "version": 1,
                                                                 "script_id": "VP-testp-2-v1", "pattern_id": "p1", "status": "draft"})
    env.fake.queue("writer", make_script(title="قديم معاد"))
    stage3_generate.rewrite_from_review(legacy, {"verdict": "revise", "findings": []})
    assert "write 1 different opening hooks" in env.fake.calls[-1]["system"] and "hooks" not in read(legacy)


def test_the_hooks_block_is_in_both_writer_prompts_and_they_are_identical():
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
    live = open(os.path.join(root, "script_writer.txt"), "rb").read()
    assert live == open(os.path.join(root, ".defaults", "script_writer.txt"), "rb").read()
    txt = live.decode("utf-8")
    for needle in ("{{HOOKS}}", "question | number | life_moment | contrarian | visual_shock", '"hooks": [', "HARD RULES FROM BRIEF"):
        assert needle in txt
    assert open(os.path.join(root, "hook_writer.txt"), "rb").read() == open(os.path.join(root, ".defaults", "hook_writer.txt"), "rb").read()


# ═════════════════ المراجعة ═════════════════
def test_local_checks_cover_the_alternatives_but_never_block_the_main_script(env):
    p = hooked(env, n=3)
    s = read(p)
    s["hooks"][1]["spoken"] = " ".join(["كلمة"] * 30)                       # بديل غير قابل للنطق
    local = review_script.local_checks(s)
    alt = [f for f in local if f.get("hook_id")]
    assert alt and all(f["hook_id"] == "h2" for f in alt) and any(f["severity"] == "blocker" for f in alt)
    assert review_script.count_main(local, "blocker") == 0 and review_script.is_hook_finding(alt[0])
    assert not [f for f in local if not f.get("hook_id") and f.get("severity") == "blocker"]


def test_an_alternative_with_a_forbidden_claim_is_reported_per_hook_using_the_brief_rules(env):
    p = hooked(env, n=3)
    env.product("testp.json", forbidden_claims=["عيونهم بتتعب"])
    local = review_script.local_checks(read(p))
    f = [x for x in local if x.get("hook_id") == "h2" and x.get("rule")]
    assert f and f[0]["axis"] == "claim_safety" and review_script.count_main(local, "blocker") == 0


def test_the_ai_review_stores_a_verdict_per_alternative_and_ignores_hook_findings_for_the_main_verdict(env):
    p = hooked(env, n=3, status="draft")
    env.fake.queue("reviewer", {**review_ok("approve"), "findings": [
        {"severity": "blocker", "scene": 1, "field": "hook_line", "hook_id": "h3", "axis": "claim_safety", "issue": "وعد علاجي", "evidence": "x", "fix": "y"},
        {"severity": "major", "scene": 1, "field": "hook_line", "hook_id": "h2", "axis": "coherence", "issue": "ضعيف", "evidence": "x", "fix": "y"}],
        "hooks_review": [{"id": "h2", "verdict": "fix", "note": "أضعف من الأساسي"}, {"id": "h3", "verdict": "reject", "note": "وعد علاجي"},
                         {"id": "h1", "verdict": "ok", "note": "الأساسي: ما بينحفظ"}, {"id": "h9", "verdict": "ok", "note": "مش موجود"}]})
    res = review_script.review(p)
    assert res["verdict"] == "approve" and res["blockers"] == 0 and res["major"] == 0 and res["hook_blockers"] == 1
    s = read(p)
    assert set(s["hooks_review"]) == {"h2", "h3"}                              # الأساسي والمجهول ما بيتخزّنوا
    assert s["hooks_review"]["h3"]["verdict"] == "reject" and s["hooks_review"]["h2"]["note"] == "أضعف من الأساسي"
    assert s["hooks_review"]["h2"]["fp"] == sh.fingerprint(sh.get(s, "h2"))
    assert review_loop.is_cleared(p)[0] is True                                  # موانع الهوكات ما بتمنع الموافقة
    assert sh.public(s)["hooks"][1]["ai"]["fresh"] is True


def test_the_verdict_stays_bound_to_main_blockers_only(env):
    p = hooked(env, n=3, status="draft")
    env.fake.queue("reviewer", {**review_ok("approve"), "findings": [
        {"severity": "blocker", "scene": 3, "field": "voiceover", "axis": "claim_safety", "issue": "ادعاء", "evidence": "x", "fix": "y"}]})
    res = review_script.review(p)
    assert res["verdict"] == "revise" and res["blockers"] == 1


def test_a_bad_hooks_review_payload_is_ignored(env):
    p = hooked(env, n=3, status="draft")
    env.fake.queue("reviewer", {**review_ok("approve"), "hooks_review": "مش قائمة"})
    review_script.review(p)
    assert "hooks_review" not in read(p)
    env.fake.queue("reviewer", {**review_ok("approve"), "hooks_review": [{"id": "h2", "verdict": "غريب", "note": "x" * 900}]})
    review_script.review(p)
    h = read(p)["hooks_review"]["h2"]
    assert h["verdict"] == "fix" and len(h["note"]) == 300


def test_the_reviewer_prompt_knows_about_hooks():
    txt = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "script_reviewer.txt"), encoding="utf-8").read()
    for needle in ("ALTERNATIVE HOOKS", "hook_id", "hooks_review", "NEVER change the verdict"):
        assert needle in txt


# ═════════════════ المسارات ═════════════════
def test_get_hooks_of_a_legacy_script_is_one_main_hook(api):
    p = api.env.script_file("legacy.json", make_script(), meta={"product": "TESTP", "product_file": "testp.json", "status": "draft"})
    d = api.get("/api/scripts/legacy.json/hooks").json()
    assert d["ok"] and d["legacy"] is True and len(d["hooks"]) == 1 and d["hooks"][0]["main"] is True and d["max"] == 5
    assert api.get("/api/scripts/nope.json/hooks").status_code == 404


def test_selecting_another_main_hook_rewrites_scene_one_and_resets_approval(api):
    p = hooked(api.env, n=3, status="approved")
    before = read(p)
    d = api.post("/api/scripts/s1.json/hooks/select", json={"id": "h2"}).json()
    s = read(p)
    assert d["main"] == "h2" and s["hook_main"] == "h2" and s["hook_line"] == ALTS[0][1]
    assert s["scenes"][0]["voiceover"] == f"{ALTS[0][1]} {REST}" and s["scenes"][0]["on_screen_text"] == "٣ من ٥"
    assert s["_meta"]["status"] == "draft" and s["_meta"]["content_hash"] != before["_meta"]["content_hash"]
    assert s["_meta"]["content_hash"] == script_versions.content_hash(s)
    assert [h["spoken"] for h in s["hooks"] if h["id"] == "h1"] == [HOOK]                    # الأساسي القديم بديل
    again = api.post("/api/scripts/s1.json/hooks/select", json={"id": "h2"}).json()
    assert again["main"] == "h2"                                                              # نفس الأساسي: ما في تغيير
    assert api.post("/api/scripts/s1.json/hooks/select", json={"id": "h9"}).status_code == 404


def test_selecting_on_a_legacy_script_materializes_nothing_when_already_main(api):
    api.env.script_file("legacy.json", make_script(), meta={"product": "TESTP", "product_file": "testp.json", "status": "approved"})
    d = api.post("/api/scripts/legacy.json/hooks/select", json={"id": "h1"}).json()
    assert d["ok"] and "hooks" not in read(api.env.scripts / "legacy.json")


def test_editing_an_alternative_does_not_touch_the_approved_content(api):
    p = hooked(api.env, n=3, status="approved")
    s = read(p)
    s["hooks_review"] = {"h2": {"verdict": "ok", "note": "", "fp": sh.fingerprint(sh.get(s, "h2")), "at": "x"}}
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    h0 = s["_meta"]["content_hash"]
    d = api.put("/api/scripts/s1.json/hooks/h2", json={"spoken": "رقم جديد بالكامل هون", "on_screen_text": "٤ من ٥", "type": "number"}).json()
    s = read(p)
    assert sh.get(s, "h2")["spoken"] == "رقم جديد بالكامل هون" and s["_meta"]["content_hash"] == h0 and s["_meta"]["status"] == "approved"
    assert "h2" not in (s.get("hooks_review") or {})                                           # حكم المراجع القديم انمسح
    assert d["hooks"][1]["ai"] is None


def test_editing_the_main_hook_edits_the_script_itself(api):
    p = hooked(api.env, n=3, status="approved")
    h0 = read(p)["_meta"]["content_hash"]
    d = api.put("/api/scripts/s1.json/hooks/h1", json={"spoken": "عينك تعبانة من الشاشة؟", "on_screen_text": "تعب الشاشة", "type": "question"}).json()
    s = read(p)
    assert s["hook_line"] == "عينك تعبانة من الشاشة؟" and s["scenes"][0]["voiceover"] == f"عينك تعبانة من الشاشة؟ {REST}"
    assert s["scenes"][0]["on_screen_text"] == "تعب الشاشة" and s["scenes"][0]["word_count"] == len((s["scenes"][0]["voiceover"]).split())
    assert sh.get(s, "h1")["spoken"] == "عينك تعبانة من الشاشة؟" and s["_meta"]["content_hash"] != h0 and s["_meta"]["status"] == "draft"
    assert d["main"] == "h1"


def test_hook_edit_validation(api):
    hooked(api.env, n=3)
    url = "/api/scripts/s1.json/hooks/h2"
    assert api.put(url, json={"spoken": "   "}).status_code == 400
    assert api.put(url, json={"spoken": "x" * 301}).status_code == 400
    assert api.put(url, json={"on_screen_text": "x" * 81}).status_code == 400
    assert api.put(url, json={"type": "غريب"}).status_code == 400
    assert api.put("/api/scripts/s1.json/hooks/h9", json={"spoken": "x"}).status_code == 404
    assert api.put(url, json={"why": "سبب جديد"}).status_code == 200


def test_deleting_an_alternative_but_never_the_main(api):
    p = hooked(api.env, n=3)
    d = api.delete("/api/scripts/s1.json/hooks/h3").json()
    assert [h["id"] for h in d["hooks"]] == ["h1", "h2"] and [h["id"] for h in read(p)["hooks"]] == ["h1", "h2"]
    assert api.delete("/api/scripts/s1.json/hooks/h1").status_code == 400
    assert api.delete("/api/scripts/s1.json/hooks/h3").status_code == 404


def test_generating_a_new_alternative_uses_the_hook_writer_with_the_brief_rules(api):
    p = hooked(api.env, n=2)
    api.env.fake.queue("writer", {"hook": {"type": "contrarian", "spoken": "نظرك سليم عينك بس جافة", "on_screen_text": "عينك جافة", "visual": "لقطة قريبة", "why": "معاكس"}})
    d = api.post("/api/scripts/s1.json/hooks", json={"type": "contrarian"}).json()
    assert d["new_id"] == "h3" and d["attempts"] == 1 and [h["id"] for h in d["hooks"]] == ["h1", "h2", "h3"]
    sent = api.env.fake.user("writer")
    assert "## HARD RULES FROM BRIEF" in sent and '"type": "contrarian"' in sent and HOOK in sent and ALTS[0][1] in sent
    assert read(p)["hooks"][2]["spoken"] == "نظرك سليم عينك بس جافة"


def test_the_writer_retries_once_with_the_blockers_as_feedback(api):
    hooked(api.env, n=2)
    api.env.product("testp.json", forbidden_claims=["بتشفي"])
    bad = {"hook": {"type": "contrarian", "spoken": "بتشفي عينك من أول قطرة", "on_screen_text": "", "visual": "لقطة", "why": "x"}}
    good = {"hook": {"type": "contrarian", "spoken": "عينك جافة مش ضعيفة", "on_screen_text": "", "visual": "لقطة", "why": "x"}}
    api.env.fake.queue("writer", bad, good)
    d = api.post("/api/scripts/s1.json/hooks", json={}).json()
    assert d["attempts"] == 2 and d["hooks"][-1]["spoken"] == "عينك جافة مش ضعيفة"
    assert '"feedback"' in api.env.fake.user("writer", -1) and "ادعاء ممنوع" in api.env.fake.user("writer", -1)


def test_when_both_attempts_are_blocked_the_last_one_comes_back_flagged(api):
    hooked(api.env, n=2)
    api.env.product("testp.json", forbidden_claims=["بتشفي"])
    bad = {"hook": {"type": "contrarian", "spoken": "بتشفي عينك من أول قطرة", "on_screen_text": "", "visual": "لقطة", "why": "x"}}
    api.env.fake.queue("writer", bad, bad)
    d = api.post("/api/scripts/s1.json/hooks", json={}).json()
    assert d["attempts"] == 2 and d["hooks"][-1]["blockers"] >= 1


def test_the_limit_is_five_hooks_and_the_main_cannot_be_regenerated(api):
    hooked(api.env, n=5)
    assert api.post("/api/scripts/s1.json/hooks", json={}).status_code == 400
    assert api.post("/api/scripts/s1.json/hooks/h1/regenerate", json={}).status_code == 400
    assert api.post("/api/scripts/s1.json/hooks/h9/regenerate", json={}).status_code == 400


def test_regenerating_an_alternative_replaces_it_and_forgets_its_old_review(api):
    p = hooked(api.env, n=3)
    s = read(p)
    s["hooks_review"] = {"h3": {"verdict": "reject", "note": "x", "fp": "x", "at": "x"}}
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    api.env.fake.queue("writer", {"hook": {"type": "visual_shock", "spoken": "شوفي شو بيصير لعينك هلق", "on_screen_text": "", "visual": "لقطة", "why": "x"}})
    d = api.post("/api/scripts/s1.json/hooks/h3/regenerate", json={"type": "visual_shock"}).json()
    s = read(p)
    assert d["new_id"] == "h3" and sh.get(s, "h3")["spoken"] == "شوفي شو بيصير لعينك هلق" and "h3" not in (s.get("hooks_review") or {})
    assert '"replace": "h3"' in api.env.fake.user("writer")


def test_an_empty_or_garbage_model_reply_is_a_clear_error(api):
    hooked(api.env, n=2)
    api.env.fake.queue("writer", {"nothing": 1}, {"hook": "مش كائن"})
    r = api.post("/api/scripts/s1.json/hooks", json={})
    assert r.status_code == 400 and "هوك صالح" in r.json()["detail"]


def test_generating_without_the_product_brief_is_refused(api):
    p = hooked(api.env, n=2)
    s = read(p)
    s["_meta"]["product_file"] = "gone.json"
    s["_meta"]["product"] = "غير موجود"
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    r = api.post("/api/scripts/s1.json/hooks", json={})
    assert r.status_code == 400 and "بريف" in r.json()["detail"]


def test_the_manual_script_save_keeps_the_hook_line_scene_one_and_the_main_hook_in_sync(api):
    p = hooked(api.env, n=3, status="approved")
    r = api.put("/api/scripts/s1.json", json={"hook_line": "جملة افتتاح جديدة تماماً"})
    assert r.status_code == 200
    s = read(p)
    assert s["scenes"][0]["voiceover"] == f"جملة افتتاح جديدة تماماً {REST}" and sh.get(s, "h1")["spoken"] == "جملة افتتاح جديدة تماماً"
    assert s["_meta"]["status"] == "draft" and s["hooks"][1]["spoken"] == ALTS[0][1]            # البدائل ما انلمست
    r = api.put("/api/scripts/s1.json", json={"scenes": [{"scene_number": 1, "on_screen_text": "نص جديد", "visual": "وصف جديد"}]})
    s = read(p)
    assert sh.get(s, "h1")["on_screen_text"] == "نص جديد" and sh.get(s, "h1")["visual"] == "وصف جديد"


def test_the_generate_endpoint_passes_the_hook_count(api):
    r = api.post("/api/generate", data={"product_file": "testp.json", "hooks": "4"}).json()
    assert r["job_id"] and "--hooks" in api.env.jobs[-1]["cmd"] and api.env.jobs[-1]["cmd"][api.env.jobs[-1]["cmd"].index("--hooks") + 1] == "4"
    api.post("/api/generate", data={"product_file": "testp.json", "hooks": "99"})
    assert api.env.jobs[-1]["cmd"][api.env.jobs[-1]["cmd"].index("--hooks") + 1] == "5"
    api.post("/api/generate", data={"product_file": "testp.json"})
    assert "--hooks" not in api.env.jobs[-1]["cmd"]


def test_hook_writer_validates_its_arguments_without_calling_the_model(env):
    s = sh.normalize(writer_script(3), 3)
    with pytest.raises(hook_writer.HookWriterError):
        hook_writer.propose(s, None)
    with pytest.raises(hook_writer.HookWriterError):
        hook_writer.propose(s, {"x": 1}, replace_id="h9")
    with pytest.raises(hook_writer.HookWriterError):
        hook_writer.propose(s, {"x": 1}, replace_id="h1")
    full = sh.normalize(writer_script(5), 5)
    with pytest.raises(hook_writer.HookWriterError):
        hook_writer.propose(full, {"x": 1})
    assert env.fake.count("writer") == 0
