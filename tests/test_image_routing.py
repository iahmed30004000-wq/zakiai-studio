"""مزوّد الصور اللي ما بياخد صور مرجعية (UnoRouter): لقطات الشخصية/المنتج بتروح للإضافة بدل ما تفشل، والنظام بيشرح ليش."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from test_studio_images import stage, first_shot  # noqa: E402,F401
import test_studio_characters_shots as tc  # noqa: E402

import ext_bridge  # noqa: E402
import image_studio as ims  # noqa: E402
import imagegen  # noqa: E402
import production_log  # noqa: E402
import studio_state  # noqa: E402
import timeline  # noqa: E402

REAL = ims.refs_supported                       # الأصلية (conftest بيبدّلها بنسخة «بياخد» لكل اختبار)
NO_REFS = {"provider": "unorouter", "model": "gpt-image-2", "supports_refs": False}


@pytest.fixture
def no_refs(monkeypatch):
    monkeypatch.setattr(ims, "refs_supported", lambda overrides=None: NO_REFS)


def refless_shot(stage):
    """لقطة بلا شخصية ولا صورة منتج: فيها صفر مراجع."""
    tl = timeline.load("s1")
    sh = first_shot(tl)
    sh["refs"] = {"character_id": None, "product_ref": None}
    timeline.save("s1", tl)
    return sh["id"]


# ───────────────────────── القرار ─────────────────────────
def test_the_real_check_reads_the_configured_providers_capability(monkeypatch):
    monkeypatch.setattr(imagegen, "image_config", lambda o=None: {"provider": "unorouter", "model": "gpt-image-2", "supports_refs": False})
    assert REAL() == NO_REFS
    monkeypatch.setattr(imagegen, "image_config", lambda o=None: {"provider": "google", "model": "nano", "supports_refs": True})
    assert REAL()["supports_refs"] is True
    seen = []
    monkeypatch.setattr(imagegen, "image_config", lambda o=None: seen.append(o) or {"provider": "x", "model": "y", "supports_refs": True})
    REAL({"provider": "openai"})
    assert seen == [{"provider": "openai"}]


def test_a_broken_settings_read_keeps_the_old_behaviour(monkeypatch):
    def boom(o=None):
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(imagegen, "image_config", boom)
    assert REAL() == {"provider": "", "model": "", "supports_refs": True}


def test_the_explanation_says_why_and_what_to_do(no_refs):
    m = ims.routed_message(NO_REFS)
    assert "unorouter" in m and "صور مرجعية" in m and "الإضافة" in m and "Google أو OpenAI" in m


# ───────────────────────── التوليد ─────────────────────────
def test_a_shot_with_references_is_routed_to_the_extension_not_failed(stage, no_refs):
    sh = first_shot(timeline.load("s1"))
    before = studio_state.state_of("s1", 7)
    with pytest.raises(ims.RoutedToExtension) as e:
        ims.generate_shot(stage.script, sh["id"], n=2, log=lambda *_: None)
    assert "unorouter" in str(e.value) and isinstance(e.value, ims.ImageStudioError)
    assert stage.calls == []                                                     # ما انولّدت صورة بلا الوجه المرجعي
    assert studio_state.state_of("s1", 7) == before != "failed"                    # المحطة ما صارت «شغّالة» ولا «فاشلة»
    assert production_log.recent(10, "image") == [] and ims.calls_used("s1") == 0
    assert ext_bridge.control("s1")["kind"] == "image" and ext_bridge.control("s1")["command"] == "idle"   # مضبوطة على الصور بلا تشغيل


def test_the_station_gate_still_comes_first(stage, no_refs):
    studio_state.set_state("s1", 6, "awaiting_choice", "x")
    with pytest.raises(ims.ImageStudioError) as e:
        ims.generate_shot(stage.script, first_shot(timeline.load("s1"))["id"], n=1, log=lambda *_: None)
    assert not isinstance(e.value, ims.RoutedToExtension) and "برومبتات" in str(e.value)


def test_a_shot_without_references_is_still_generated_through_the_api(stage, no_refs):
    sid = refless_shot(stage)
    r = ims.generate_shot(stage.script, sid, n=1, log=lambda *_: None)
    assert r["made"] == 1 and stage.calls[-1]["refs"] == []


def test_overrides_reach_the_capability_check(stage, monkeypatch):
    seen = []
    monkeypatch.setattr(ims, "refs_supported", lambda overrides=None: seen.append(overrides) or {"provider": "google", "model": "m", "supports_refs": True})
    ims.generate_shot(stage.script, first_shot(timeline.load("s1"))["id"], n=1, overrides={"provider": "google"}, log=lambda *_: None)
    assert seen == [{"provider": "google"}]


def test_generate_all_reports_routed_shots_separately_from_failures(stage, no_refs):
    sid = refless_shot(stage)
    lines = []
    r = ims.generate_all(stage.script, n=1, log=lines.append)
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    assert r["done"] == [sid] and r["failed"] == [] and r["routed"] == [i for i in ids if i != sid]
    assert len(stage.calls) == 1
    assert sum("unorouter" in l for l in lines) == 1                              # الشرح مرة وحدة مش لكل لقطة
    assert any(f"{len(r['routed'])} لقطة اتحوّلت للإضافة" in l for l in lines)


def test_generate_all_with_a_capable_provider_has_nothing_routed(stage):
    r = ims.generate_all(stage.script, n=1, log=lambda *_: None)
    assert r["routed"] == [] and r["failed"] == [] and len(r["done"]) > 3


# ───────────────────────── المعلومات للواجهة ─────────────────────────
def test_the_info_route_lists_the_shots_waiting_for_the_extension(stage, no_refs):
    c = tc.client()
    d = c.get("/api/studio/s1.json/images/info").json()
    ids = [s["id"] for sc in timeline.load("s1")["scenes"] for s in sc["shots"]]
    assert d["image_provider"]["supports_refs"] is False and d["image_provider"]["provider"] == "unorouter"
    assert d["ext_routed"] == ids and "الإضافة" in d["image_provider"]["note"]
    ims.generate_shot(stage.script, refless_shot(stage), n=1, log=lambda *_: None)
    d2 = c.get("/api/studio/s1.json/images/info").json()
    assert d2["ext_routed"] == [i for i in ids if i != first_shot(timeline.load("s1"))["id"]]             # اللي انولّدت ما بتنعد


def test_with_a_capable_provider_the_info_has_no_routing(stage):
    d = tc.client().get("/api/studio/s1.json/images/info").json()
    assert d["image_provider"]["supports_refs"] is True and d["ext_routed"] == [] and d["image_provider"]["note"] == ""
