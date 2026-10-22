"""بوابة وضع المشروع (studio_gate): موجّه أو حر. المهمة الموجّهة لازم تضل بنفس الرسائل والأكواد بالحرف."""

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401

import config  # noqa: E402
import studio_gate  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402


def _write(env, name, meta):
    p = Path(config.SCRIPTS_DIR) / name
    s = make_script()
    s["_meta"] = meta
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return p


def test_mode_of_is_free_only_for_an_explicit_free_meta():
    assert studio_gate.mode_of({"_meta": {"mode": "free"}}) == "free"
    for bad in (None, {}, {"_meta": None}, {"_meta": {"mode": "guided"}}, {"_meta": {"mode": "FREE"}}, {"_meta": {"mode": 1}}, "free", []):
        assert studio_gate.mode_of(bad) == "guided", bad


def test_is_free_accepts_stem_filename_or_path_and_fails_safe(env):
    _write(env, "free_a.json", {"mode": "free"})
    _write(env, "guided_a.json", {"product": "x"})
    (Path(config.SCRIPTS_DIR) / "broken.json").write_text("{nope", encoding="utf-8")
    for ref in ("free_a", "free_a.json", Path(config.SCRIPTS_DIR) / "free_a.json"):
        assert studio_gate.is_free(ref), ref
    for ref in ("guided_a", "missing", "broken", "", None):
        assert not studio_gate.is_free(ref), ref


def test_guided_gate_keeps_the_exact_voice_and_timeline_messages(env, monkeypatch):
    p = _write(env, "g1.json", {"product": "x"})
    import voice_studio
    monkeypatch.setattr(voice_studio, "voice_is_approved", lambda path: (False, "ما في صوت معتمد لهالسيناريو"))
    with pytest.raises(studio_gate.GateError) as e:
        studio_gate.timeline_for(p)
    assert e.value.status == 409 and str(e.value) == "ما في صوت معتمد لهالسيناريو"
    monkeypatch.setattr(voice_studio, "voice_is_approved", lambda path: (True, ""))
    with pytest.raises(studio_gate.GateError) as e:
        studio_gate.timeline_for(p, "ما في خط زمني — اعتمد الصوت أولاً")
    assert e.value.status == 404 and str(e.value) == "ما في خط زمني — اعتمد الصوت أولاً"
    with pytest.raises(studio_gate.GateError) as e:
        studio_gate.timeline_for(p)
    assert str(e.value) == "ما في خط زمني"


def test_free_gate_needs_only_the_timeline_not_an_approved_voice(env, monkeypatch):
    p = _write(env, "f1.json", {"mode": "free"})
    import voice_studio
    monkeypatch.setattr(voice_studio, "voice_is_approved", lambda path: (_ for _ in ()).throw(AssertionError("ما لازم يُسأل الصوت")))
    with pytest.raises(studio_gate.GateError) as e:
        studio_gate.timeline_for(p)
    assert e.value.status == 404 and str(e.value) == "ما في مشاهد بعد"
    tl = {"mode": "free", "scenes": [], "voice": {}}
    path = timeline.path_for("f1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tl), encoding="utf-8")
    assert studio_gate.timeline_for(p) == tl


def test_require_helpers(env):
    f = _write(env, "f2.json", {"mode": "free"})
    g = _write(env, "g2.json", {"product": "x"})
    studio_gate.require_free(f)
    studio_gate.require_guided(g)
    with pytest.raises(studio_gate.GateError) as e:
        studio_gate.require_free(g)
    assert e.value.status == 409
    with pytest.raises(studio_gate.GateError) as e:
        studio_gate.require_guided(f)
    assert "نزّل الفيديو" in str(e.value)


def test_station_chain_is_relaxed_only_for_free_projects(env):
    _write(env, "f3.json", {"mode": "free"})
    _write(env, "g3.json", {"product": "x"})
    ok, _why = studio_state.can_start("f3", 9)
    assert ok
    ok, why = studio_state.can_start("g3", 9)
    assert not ok and "ما بتبدأ قبل اعتماد" in why
    assert studio_state.can_start("no_such_script", 5)[0] is False            # ملف ناقص = موجّه (قواعد اليوم)
    assert studio_state.can_start("f3", 99) == (False, "محطة غير معروفة")


def test_derive_early_marks_free_projects_ready_without_brief_or_review(env):
    p = _write(env, "f4.json", {"mode": "free"})
    st = studio_state.derive_early("f4", p)
    assert [s["state"] for s in st[:3]] == ["approved"] * 3 and st[0]["note"] == "مشروع حر"
    # بتنعاد بلا تغيير ولا أحداث جديدة
    n = len(studio_state.load("f4")["events"])
    studio_state.derive_early("f4", p)
    assert len(studio_state.load("f4")["events"]) == n


def _mini_app():
    from web import routes_motion, routes_montage, routes_studio
    app = FastAPI()
    for r in (routes_studio.router, routes_motion.router, routes_montage.router):
        app.include_router(r)
    return TestClient(app)


def test_the_three_route_gates_keep_their_own_404_texts_for_guided_scripts(env, monkeypatch):
    p = _write(env, "g5.json", {"product": "x"})
    import voice_studio
    c = _mini_app()
    monkeypatch.setattr(voice_studio, "voice_is_approved", lambda path: (False, "نص السيناريو انعدّل بعد اعتماد الصوت — لازم صوت جديد"))
    for url in ("/api/studio/g5.json/images/info", "/api/studio/g5.json/motion/info", "/api/studio/g5.json/montage/info"):
        r = c.get(url)
        assert r.status_code == 409 and r.json()["detail"] == "نص السيناريو انعدّل بعد اعتماد الصوت — لازم صوت جديد", url
    monkeypatch.setattr(voice_studio, "voice_is_approved", lambda path: (True, ""))
    assert c.get("/api/studio/g5.json/images/info").json()["detail"] == "ما في خط زمني — اعتمد الصوت أولاً"
    assert c.get("/api/studio/g5.json/motion/info").json()["detail"] == "ما في خط زمني"
    assert c.get("/api/studio/g5.json/montage/info").json()["detail"] == "ما في خط زمني"
    assert p.exists()


def test_launch_routes_refuse_free_projects_with_a_clear_code(env):
    _write(env, "f6.json", {"mode": "free"})
    c = _mini_app()
    for method, url in (("get", "/api/studio/f6.json/launch/info"), ("post", "/api/studio/f6.json/launch"),
                        ("post", "/api/studio/f6.json/launch/refresh"), ("post", "/api/studio/f6.json/launch/cancel")):
        r = c.get(url) if method == "get" else c.post(url, json={"mode": "test"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "free_project", url
