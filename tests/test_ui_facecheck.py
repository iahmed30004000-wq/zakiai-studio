"""واجهة فحص الوجه بمحطة التطابق (٨): الشارة، الفحص التلقائي عند الفتح، وبيانات التجربة."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
JS = (STATIC / "production.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def mock(name):
    return json.loads((STATIC / "mock" / f"{name}.json").read_text(encoding="utf-8"))


def test_the_face_badge_covers_every_status_and_shows_the_raw_number():
    body = re.search(r"function faceBadge\(c\) \{.*?\n\}", JS, re.S).group(0)
    for needle in ("مطابق", "تغيّر", "ما انكشف وجه", "ما في مرجع صالح", "غير مقاس", "toFixed(2)", "c.note"):
        assert needle in body, needle
    assert 'pass: ["ok"' in body and 'fail: ["danger"' in body and 'no_face: ["warn"' in body


def test_hand_shots_have_no_face_badge_and_the_old_wording_is_gone():
    assert 'sh.type !== "hand_product" ? faceBadge(sh.face_check)' in JS
    assert 'checkBadge("الوجه"' not in JS and "وجه الشخصية <b>غير مقاسة</b>" not in JS
    assert "ما في موديل وجوه على الجهاز" not in json.dumps(mock("studio_timeline"), ensure_ascii=False)


def test_opening_the_match_station_checks_what_was_not_checked_yet():
    body = re.search(r"async function renderMatchStation\(body\) \{.*?\n\}", JS, re.S).group(0)
    assert "/match/check" in body and "!MOCK" in body and "product_check == null" in body and "face_check == null" in body
    assert 'sh.type !== "hand_product"' in body and body.count("await api(") == 1                       # مرة وحدة، بلا حلقة
    assert "عم بفحص اللقطات" in body


def test_a_changed_face_points_the_owner_to_the_images_station():
    assert 'sh.face_check.status === "fail"' in JS and "محطة الصور" in JS and "prodHash(file, 7)" in JS
    assert re.search(r'data-check="\$\{esc\(sh\.id\)\}"[^>]*>افحص</button>', JS)


def test_mock_mode_has_the_new_route_and_shows_a_pass_and_a_fail():
    assert re.search(r"match\\/check\$/\.test\(path\) && method === \"POST\"\) return \{ checked: \[\], failed: \[\] \}", APP)
    statuses = {}
    for sc in mock("studio_timeline")["timeline"]["scenes"]:
        for sh in sc["shots"]:
            if sh.get("face_check"):
                statuses[sh["id"]] = sh["face_check"]
    assert {c["status"] for c in statuses.values()} == {"pass", "fail"}
    assert all(0 <= c["similarity"] <= 1 and c["threshold"] == 0.363 and c["note"] for c in statuses.values())
    msgs = [p["message"] for p in mock("studio_images_info")["match_problems"]]
    assert any("الوجه تغيّر" in m for m in msgs)


# ═════════════════ محطة التحريك (٩) ═════════════════
def test_the_motion_station_shows_the_face_result_per_video_and_the_models_record():
    assert "${c.face ? ` ${faceBadge(c.face)}` : \"\"}</figcaption>" in JS
    assert "حفظ الوجه ${Math.round(m.face_rate.rate * 100)}٪" in JS and "m.face_rate.checks >= 3" in JS


def test_choosing_a_video_whose_face_changed_asks_first_and_the_hint_points_to_another_model():
    assert 'data-facefail="${c.face && c.face.status === "fail" ? "1" : ""}"' in JS
    assert 'if (b.dataset.facefail && !confirm("وجه الشخصية بهالفيديو تغيّر عن صورتها المرجعية. متأكد بدك تختاره؟")) return;' in JS
    assert "جرّب موديل تاني من القائمة وكبسة «خيارات جديدة»" in JS


def test_the_mock_motion_info_has_a_matching_and_a_changed_face_and_a_model_record():
    d = mock("motion_info")
    cands = d["shots"][0]["candidates"]
    assert [c["face"]["status"] for c in cands] == ["pass", "fail"] and len({c["clip"] for c in cands}) == 2
    fr = d["shots"][0]["ranked"][0]["face_rate"]
    assert fr["checks"] >= 3 and 0 <= fr["rate"] <= 1 and fr["passed"] <= fr["checks"]


# ═════════════════ مزوّد الصور بلا مراجع ← الإضافة ═════════════════
def test_the_image_station_explains_the_routing_and_leads_to_the_extension_panel():
    body = re.search(r"function drawImageStation\(body, tl, info\) \{.*?\n\}\n", JS, re.S).group(0)
    for needle in ("info.ext_routed", "info.image_provider", 'id="imRouteNote"', 'id="imToExt"', "بتتولّد بالإضافة مش بالـ API", "prov.note",
                   "allRouted", "كل اللقطات الناقصة فيها مراجع", '/ext/control`, { method: "POST"', 'kind: "image"', "افتح لوحة الإضافة"):
        assert needle in body, needle


def test_the_mock_images_info_shows_a_provider_without_references():
    d = mock("studio_images_info")
    assert d["image_provider"]["supports_refs"] is False and d["image_provider"]["note"] and len(d["ext_routed"]) == 3
