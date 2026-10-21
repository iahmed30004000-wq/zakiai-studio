"""مسارات /api/pattern-lib/*: إنشاء، تعديل، أرشفة، ترجمة. (الأسئلة بترجع 200 {ok:false, confirm}، والأخطاء 400/404/409/423.)"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_pattern_text import sample  # noqa: E402

import pattern_store  # noqa: E402
import review_queue  # noqa: E402

NEW = {
    "pattern_name": "كشف المكوّنات ببطء", "framework": "ingredient_reveal", "product_category": "fragrance",
    "hook": {"type": "سؤال صادم"},
    "scene_blueprint": [{"function": "الهوك", "duration_sec": 3}, {"function": "المنتج", "duration_sec": 20}, {"function": "الدعوة", "duration_sec": 7}],
}


@pytest.fixture
def api(env, monkeypatch):
    monkeypatch.setattr(review_queue, "QUEUE_PATH", env.root / "rq.json")
    from fastapi.testclient import TestClient
    from web.app import app
    c = TestClient(app)
    c.env = env
    return c


def seed_english(env, pid="p1"):
    (env.patterns / f"{pid}.pattern.json").write_text(json.dumps(sample(), ensure_ascii=False, indent=2), encoding="utf-8")


def test_schema_carries_groups_fields_scene_fields_and_closed_options(api):
    d = api.get("/api/pattern-lib/schema").json()
    assert {g["key"] for g in d["groups"]} >= {"basic", "hook", "cta", "why"}
    assert any(f["path"] == "hook.type" and f["required"] for f in d["fields"])
    assert [f["key"] for f in d["scene_fields"]][0] == "function"
    assert "pas" in d["options"]["frameworks"] and d["limits"]["min_scenes_new"] == 3


def test_create_validates_with_a_field_list(api):
    r = api.post("/api/pattern-lib", json={"fields": {"pattern_name": "", "scene_blueprint": []}})
    assert r.status_code == 400
    fields = {e["field"] for e in r.json()["detail"]}
    assert {"pattern_name", "framework", "product_category", "hook.type", "scene_blueprint"} <= fields
    assert pattern_store.list_ids() == []


def test_create_then_read_back_the_editor_view(api):
    r = api.post("/api/pattern-lib", json={"fields": NEW})
    assert r.status_code == 200 and r.json()["ok"] is True
    pid = r.json()["id"]
    v = api.get(f"/api/pattern-lib/{pid}").json()
    assert v["id"] == pid and v["origin"] == "authored" and v["archived"] is False
    assert v["fields"]["pattern_name"] == "كشف المكوّنات ببطء" and len(v["fields"]["scene_blueprint"]) == 3
    assert v["rev"] and v["refs"] == {"count": 0, "names": []} and v["history"][0]["action"] == "create"
    assert any(p["id"] == pid and p["authored"] for p in api.get("/api/patterns").json())          # ظهر بالمكتبة بالعربي


def test_similar_pattern_asks_before_saving_and_saves_after_confirm(api):
    first = api.post("/api/pattern-lib", json={"fields": NEW}).json()["id"]
    r = api.post("/api/pattern-lib", json={"fields": NEW})
    d = r.json()
    assert r.status_code == 200 and d["ok"] is False and d["confirm"] == "similar"
    assert "بنفس الاسم" in d["message"] and d["similar"][0]["pattern_id"] == first and d["similar"][0]["same_name"] is True
    assert pattern_store.list_ids() == [first]                                                    # ما انحفظ
    ok = api.post("/api/pattern-lib", json={"fields": NEW, "confirm": True}).json()
    assert ok["ok"] is True and sorted(pattern_store.list_ids()) == sorted([first, ok["id"]])


def test_similar_endpoint_tolerates_half_filled_forms(api):
    pid = api.post("/api/pattern-lib", json={"fields": NEW}).json()["id"]
    assert api.post("/api/pattern-lib/similar", json={"fields": {}}).json() == {"matches": []}
    m = api.post("/api/pattern-lib/similar", json={"fields": {"pattern_name": "كشف المكوّنات ببطء"}}).json()["matches"]
    assert m and m[0]["pattern_id"] == pid


def test_edit_saves_checks_the_revision_and_reports_errors(api):
    pid = api.post("/api/pattern-lib", json={"fields": NEW}).json()["id"]
    rev0 = api.get(f"/api/pattern-lib/{pid}").json()["rev"]
    r = api.put(f"/api/pattern-lib/{pid}", json={"fields": {"one_line_summary": "ملخص", "reusability_score": 8}, "rev": rev0})
    assert r.status_code == 200 and r.json()["ok"] and set(r.json()["changed"]) == {"one_line_summary", "reusability_score"}
    assert r.json()["rev"] != rev0
    stale = api.put(f"/api/pattern-lib/{pid}", json={"fields": {"one_line_summary": "تاني"}, "rev": rev0})
    assert stale.status_code == 409 and "اتغيّر" in stale.json()["detail"]
    bad = api.put(f"/api/pattern-lib/{pid}", json={"fields": {"framework": "مش موجود"}})
    assert bad.status_code == 400 and bad.json()["detail"][0]["field"] == "framework"
    assert api.put("/api/pattern-lib/nope", json={"fields": {"one_line_summary": "x"}}).status_code == 404
    assert api.get(f"/api/pattern-lib/{pid}").json()["fields"]["one_line_summary"] == "ملخص"


def test_editing_an_untranslated_pattern_keeps_the_rest_english_for_the_translator(api):
    seed_english(api.env)
    v = api.get("/api/pattern-lib/p1").json()
    assert v["fields"]["pattern_name"] == "The Sensory Layer Reveal" and v["missing_ar"] > 5
    r = api.put("/api/pattern-lib/p1", json={"fields": v["fields"], "rev": v["rev"]})
    assert r.json()["changed"] == []                                                              # حفظ بلا تغيير
    assert api.get("/api/pattern-lib/p1").json()["missing_ar"] == v["missing_ar"]
    api.put("/api/pattern-lib/p1", json={"fields": {"pattern_name": "كشف الطبقات"}})
    v2 = api.get("/api/pattern-lib/p1").json()
    assert v2["name"] == "كشف الطبقات" and v2["missing_ar"] == v["missing_ar"] - 1


def test_archive_asks_when_scripts_use_it_then_restores(api):
    pid = api.post("/api/pattern-lib", json={"fields": NEW}).json()["id"]
    api.env.script_file("s1.json", {"hook_line": "x", "scenes": []},
                        meta={"product": "P", "pattern_id": pid, "display_name": "#1 - P", "script_id": "VP-p-1-v1"})
    r = api.post(f"/api/pattern-lib/{pid}/archive", json={})
    d = r.json()
    assert r.status_code == 200 and d["ok"] is False and d["confirm"] == "used" and d["refs"]["count"] == 1 and "#1 - P" in d["message"]
    assert pattern_store.list_ids() == [pid]
    done = api.post(f"/api/pattern-lib/{pid}/archive", json={"confirm": True}).json()
    assert done["ok"] and done["refs"]["count"] == 1 and pattern_store.list_ids() == []
    assert [x["id"] for x in api.get("/api/pattern-lib/archived").json()["items"]] == [pid]
    assert api.get(f"/api/pattern-lib/{pid}").json()["archived"] is True                          # السيناريو لسا بيفتحه
    assert api.post(f"/api/pattern-lib/{pid}/restore").json()["ok"]
    assert pattern_store.list_ids() == [pid] and api.get("/api/pattern-lib/archived").json()["items"] == []
    assert api.post(f"/api/pattern-lib/{pid}/restore").status_code == 404


def test_archive_without_scripts_is_immediate(api):
    pid = api.post("/api/pattern-lib", json={"fields": NEW}).json()["id"]
    assert api.post(f"/api/pattern-lib/{pid}/archive", json={}).json()["ok"] is True
    assert api.post("/api/pattern-lib/nope/archive", json={}).status_code == 404


def test_bad_ids_never_touch_the_disk(api):
    assert api.get("/api/pattern-lib/..%2Fsecret").status_code == 404
    assert api.post("/api/pattern-lib/a%20b/archive", json={"confirm": True}).status_code == 400
    assert api.post("/api/pattern-lib/a%20b/restore").status_code == 400


def test_busy_library_answers_423(api, monkeypatch):
    pid = api.post("/api/pattern-lib", json={"fields": NEW}).json()["id"]
    real = pattern_store.locked
    monkeypatch.setattr(pattern_store, "locked", lambda timeout=0.2, directory=None: real(timeout=0.2, directory=directory))
    with real():
        r = api.put(f"/api/pattern-lib/{pid}", json={"fields": {"one_line_summary": "x"}})
    assert r.status_code == 423 and "مشغولة" in r.json()["detail"]
