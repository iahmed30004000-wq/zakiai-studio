"""بنك الهوكات: المسارات + أمثلة الكاتب داخل برومبت الكتابة."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_hooks_bank import bank, row  # noqa: E402,F401
from test_hooks_h1 import ALTS, HOOK, writer_script  # noqa: E402

import hooks_bank as hb  # noqa: E402
import stage3_generate  # noqa: E402


@pytest.fixture
def api(bank):
    from fastapi.testclient import TestClient
    from web.app import app
    c = TestClient(app)
    c.bank = bank
    return c


def test_list_returns_items_counts_products_and_types(api):
    d = api.get("/api/hooks-bank").json()
    assert len(d["items"]) == 4 and d["counts"]["total"] == 4 and d["products"] == ["TESTP", "VARA"] and "question" in d["types"]
    e = next(x for x in d["items"] if x["key"] == "VP-testp-1-v1.h2")
    assert e["role"] == "video" and e["version"]["file"] == "s1__h2.json" and e["star"] is False and e["archived"] is False


def test_list_filters_through_query_params(api):
    assert [e["key"] for e in api.get("/api/hooks-bank", params={"product": "VARA"}).json()["items"]] == ["VP-vara-4-v1.h1"]
    assert {e["key"] for e in api.get("/api/hooks-bank", params={"type": "number"}).json()["items"]} == {"VP-testp-1-v1.h2"}
    assert {e["key"] for e in api.get("/api/hooks-bank", params={"role": "video"}).json()["items"]} == {"VP-testp-1-v1.h2"}
    assert [e["key"] for e in api.get("/api/hooks-bank", params={"q": "الساعة"}).json()["items"]] == ["VP-testp-1-v1.h3"]
    api.post("/api/hooks-bank/VP-testp-1-v1.h3/star", json={"on": True})
    assert [e["key"] for e in api.get("/api/hooks-bank", params={"star": "true"}).json()["items"]] == ["VP-testp-1-v1.h3"]
    assert len(api.get("/api/hooks-bank", params={"product": "", "type": ""}).json()["items"]) == 4          # فاضي = بلا فلتر


def test_manual_hooks_through_the_api(api):
    r = api.post("/api/hooks-bank", json={"text": "شو بتعمل لو عينك بتحرقك؟", "type": "question", "product": "kama", "note": "من زبونة"})
    assert r.status_code == 200 and r.json()["entry"]["key"] == "m_1" and r.json()["entry"]["type_label"] == "سؤال"
    assert api.get("/api/hooks-bank").json()["counts"]["total"] == 5
    e = api.put("/api/hooks-bank/m_1", json={"text": "نص معدّل تماماً", "note": ""}).json()["entry"]
    assert e["text"] == "نص معدّل تماماً" and e["note"] == "" and e["type"] == "question"                    # اللي ما انبعت ما تغيّر
    assert api.delete("/api/hooks-bank/m_1").json() == {"ok": True}
    assert api.get("/api/hooks-bank").json()["counts"]["total"] == 4


def test_api_errors_are_arabic_with_the_right_status(api):
    r = api.post("/api/hooks-bank", json={"text": "ab"})
    assert r.status_code == 400 and "3 أحرف" in r.json()["detail"]
    assert api.post("/api/hooks-bank", json={}).status_code == 400
    assert api.put("/api/hooks-bank/m_9", json={"text": "نص مقبول هون"}).status_code == 404
    assert api.delete("/api/hooks-bank/VP-testp-1-v1.h1").status_code == 404                               # المشتق ما بينحذف
    assert api.post("/api/hooks-bank/nope/star", json={"on": True}).status_code == 404
    assert api.post("/api/hooks-bank/nope/archive", json={}).status_code == 404


def test_star_and_archive_endpoints_and_the_archived_flag(api):
    k = "VP-testp-1-v1.h3"
    assert api.post(f"/api/hooks-bank/{k}/star", json={"on": True}).json()["entry"]["star"] is True
    assert api.post(f"/api/hooks-bank/{k}/star", json={"on": False}).json()["entry"]["star"] is False
    assert api.post(f"/api/hooks-bank/{k}/archive", json={}).json()["entry"]["archived"] is True              # بلا on = شغّل
    d = api.get("/api/hooks-bank").json()
    assert all(e["key"] != k for e in d["items"]) and d["counts"]["archived"] == 1
    assert any(e["key"] == k for e in api.get("/api/hooks-bank", params={"archived": "true"}).json()["items"])
    assert api.post(f"/api/hooks-bank/{k}/archive", json={"on": False}).json()["entry"]["archived"] is False


# ═════════════════ الكاتب بيشوف الأمثلة ═════════════════
def writer_user(env, hooks=2):
    env.pattern("p1")
    path = env.product("kama.json")
    env.fake.queue("writer", writer_script(hooks))
    stage3_generate.write_for_product(path, "p1", review=False, hooks=hooks)
    return env.fake.user("writer")


def test_the_writer_gets_the_starred_and_winning_hooks_before_the_registry(env):
    hooked_path = __import__("test_hooks_h1").hooked(env, "old.json", n=3)
    hb.set_star("VP-testp-1-v1.h3", True)
    user = writer_user(env)
    assert "## HOOK EXAMPLES THAT WORKED" in user and user.index("## PATTERN TO APPLY") < user.index("## HOOK EXAMPLES THAT WORKED") < user.index("## ALREADY USED")
    block = user.split("## HOOK EXAMPLES THAT WORKED", 1)[1].split("## ALREADY USED", 1)[0]
    assert ALTS[1][1] in block and "never the wording" in block and "starred_by_owner" in block
    assert HOOK not in block                                                                                # الأساسي ما نجّمناه ولا اتجرّب


def test_with_no_good_hooks_the_prompt_has_no_examples_block(env):
    __import__("test_hooks_h1").hooked(env, "old.json", n=3)
    assert "HOOK EXAMPLES" not in writer_user(env)


def test_a_failing_bank_never_breaks_writing(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("بنك تالف")

    monkeypatch.setattr(hb, "writer_examples", boom)
    user = writer_user(env)
    assert "## ALREADY USED" in user and "HOOK EXAMPLES" not in user


def test_the_examples_prefer_the_products_category(env, monkeypatch):
    seen = []
    real = hb.writer_examples
    monkeypatch.setattr(hb, "writer_examples", lambda category=None, limit=6: seen.append(category) or real(category, limit))
    writer_user(env)
    assert seen == ["eye_care"]                                                                             # فئة بريف المنتج
