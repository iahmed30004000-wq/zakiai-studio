"""واجهة بطاقة الهوية الإنجليزية (صفحة الشخصية) والنسخة الإنجليزية بمحطة برومبتات اللقطات."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
CH = (STATIC / "characters.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
PRD = (STATIC / "production.js").read_text(encoding="utf-8")


def test_the_character_page_has_the_identity_panel_before_the_reference_sheet():
    assert CH.index('id="chIdentity"') < CH.index("الورقة المرجعية (5 وضعيات ثابتة)")
    assert "if (!isNew) { chDrawIdentity(c); chDrawSlots(c); }" in CH


def test_the_panel_talks_to_its_three_endpoints_and_confirms_before_discarding_a_manual_card():
    body = re.search(r"async function chDrawIdentity\(c\) \{.*?\n\}\n", CH, re.S).group(0)
    assert "/identity`" in body and "`${base}/rebuild`" in body and 'jo("PUT", { text: $("#idText").value })' in body
    for needle in ("تلقائية", "معدّلة بإيدك", "تلقائية — ناقصة", "d.negative", "confirm(", "ابنِها من جديد", "احفظ تعديلي"):
        assert needle in body, needle
    assert 'jo("PUT", { text: "" })' in body                                           # «ابنِها من جديد» بيرجّع المعدّلة تلقائية أول


def test_mock_mode_serves_and_accepts_the_identity_card():
    assert re.search(r"characters\\/\[\^/\]\+\\/identity\$/\.test\(path\)\) return mockFile\(\"character_identity\"\)", APP)
    assert re.search(r"identity\(\\/rebuild\)\?\$/\.test\(path\) && method !== \"GET\"\) return mockFile\(\"character_identity\"\)", APP)
    d = json.loads((STATIC / "mock" / "character_identity.json").read_text(encoding="utf-8"))
    assert set(d) == {"text", "auto", "complete", "stale", "negative", "country"} and d["auto"] and d["complete"] and not d["stale"]
    assert not re.search(r"[؀-ۿ]", d["text"] + d["negative"])                 # إنجليزي صافي


def test_the_shot_prompt_station_says_what_the_model_receives():
    assert "النسخة المرسلة للموديل (إنجليزي + بطاقة هوية الشخصية)" in PRD
    assert "النسخة الإنجليزية لسا ما انبنت — بتنترجم لحالها لما تولّد الصور." in PRD
