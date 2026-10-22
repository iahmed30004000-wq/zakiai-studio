"""سيناريو بإيدك داخل المهمة الموجّهة (manual_script + review_loop.approve_local + المسارات): نفس القواعد (7 مشاهد، 45–50ث، المراجعة)،
والموافقة بالفحص الحسابي بس، و«ابدأ من تسجيلك» — بتفريغ وهمي."""

import io
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env, make_script  # noqa: E402,F401
from test_ext_tasks import vs  # noqa: E402,F401

import config  # noqa: E402
import manual_script as ms  # noqa: E402
import review_loop  # noqa: E402
import scene_import  # noqa: E402
import script_hooks  # noqa: E402
import script_versions  # noqa: E402
import studio_state  # noqa: E402

FFMPEG = shutil.which("ffmpeg") is not None


def seven(words=16, dur=None):
    """7 صفوف مشاهد بكلام مميّز لكل مشهد."""
    out = []
    for i in range(1, 8):
        r = {"voiceover": " ".join(f"م{i}ك{j}" for j in range(words)) + ".", "visual": f"لقطة {i}", "on_screen_text": "", "shot_type": None, "emotion": ""}
        r["duration_sec"] = dur if dur else scene_import.default_duration(r["voiceover"])
        out.append(r)
    return out


def setup(env):
    env.product()
    env.pattern("p1")
    return "testp.json", "p1"


def script_of(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ───────────────────────── القراءة والمدد ─────────────────────────
def test_rows_from_text_excel_and_errors():
    rows, warn = ms.rows_from("مشهد أول\nصورة: وصف\n\nمشهد تاني")
    assert [r["voiceover"] for r in rows] == ["مشهد أول", "مشهد تاني"] and rows[0]["visual"] == "وصف" and warn == []
    wb = openpyxl.load_workbook(io.BytesIO(scene_import.template()))
    wb["المشاهد"].append(["كلام من إكسل", None, None, 4, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    rows, _ = ms.rows_from(xlsx=buf.getvalue())
    assert rows[0]["voiceover"] == "كلام من إكسل" and rows[0]["duration_sec"] == 4.0
    for bad in ({"text": ""}, {"text": "   "}, {"xlsx": b"junk"}):
        with pytest.raises(ms.ManualScriptError):
            ms.rows_from(**bad)


def test_fit_durations_stretches_into_the_safe_range_unless_the_owner_gave_durations():
    short = seven(8)                                                       # كلام قليل: مجموعه الطبيعي أقل من 45
    d = ms.fit_durations(short)
    assert 45 <= sum(d) <= 50 and all(x > 0 for x in d)
    long = seven(30)                                                       # كلام كتير
    assert 45 <= sum(ms.fit_durations(long)) <= 50
    ok = seven(16)
    assert ms.fit_durations(ok) == [r["duration_sec"] for r in ok] or 45 <= sum(ms.fit_durations(ok)) <= 50
    given = seven(16, dur=4.0)                                             # حدّد المالك المدد: بتضل (والفحص بيحكم)
    assert ms.fit_durations(given) == [4.0] * 7


# ───────────────────────── الإنشاء ─────────────────────────
def test_create_writes_a_script_shaped_like_the_writers_and_registers_it(env):
    pf, pid = setup(env)
    p = ms.create(pf, pid, seven(), title="سيناريو بإيدي", by="سارة")
    s = script_of(p)
    for k in make_script():                                                # كل مفاتيح سيناريو الكاتب موجودة
        assert k in s, k
    assert len(s["scenes"]) == 7 and [sc["scene_number"] for sc in s["scenes"]] == list(range(1, 8)) and s["title"] == "سيناريو بإيدي"
    assert 45 <= s["total_duration_sec"] <= 50 and s["hook_line"].startswith("م1ك0") and s["cta_line"].startswith("م7ك") or s["cta_line"]
    meta = s["_meta"]
    assert meta["status"] == "draft" and meta["source"] == "manual" and meta["created_by"] == "سارة" and meta["number"] == 1
    assert meta["script_id"] == "VP-testp-1-v1" and meta["display_name"] == "#1 - TESTP" and meta["pattern_id"] == "p1" and meta["product_file"] == "testp.json"
    assert meta["content_hash"] == script_versions.content_hash(s) and p.with_suffix(".md").exists()
    assert (Path(config.SCRIPTS_DIR) / "versions" / p.stem).exists()
    assert len(script_hooks.hooks_of(s)) == 1
    p2 = ms.create(pf, pid, seven())
    assert script_of(p2)["_meta"]["number"] == 2 and p2 != p
    assert "manual" in p.name


def test_create_enforces_seven_scenes_text_in_each_and_valid_product_and_pattern(env):
    pf, pid = setup(env)
    with pytest.raises(ms.ManualScriptError, match="7 مشاهد بالضبط.*مشروع حر"):
        ms.create(pf, pid, seven()[:6])
    rows = seven()
    rows[3]["voiceover"] = "  "
    with pytest.raises(ms.ManualScriptError, match="مشهد 4: الكلام فاضي"):
        ms.create(pf, pid, rows)
    with pytest.raises(ms.ManualScriptError) as e:
        ms.create("nope.json", pid, seven())
    assert e.value.status == 404
    with pytest.raises(ms.ManualScriptError) as e:
        ms.create(pf, "no_such_pattern", seven())
    assert e.value.status == 404 and not list(Path(config.SCRIPTS_DIR).glob("*.json"))


# ───────────────────────── الموافقة بالفحص الحسابي ─────────────────────────
def test_local_approval_checks_arithmetic_and_claims_and_opens_the_normal_gate(env):
    pf, pid = setup(env)
    p = ms.create(pf, pid, seven())
    assert not review_loop.is_cleared(p)[0]                                # لسا ما انراجع
    st = review_loop.approve_local(p, by="سارة")
    assert st["approved"] and st["status"] == "approved"
    ok, why = review_loop.is_cleared(p)
    assert ok, why
    rv = review_loop.load_review(p)
    assert rv["_meta"]["provider"] == "local" and rv["local_only"] and rv["blockers"] == 0 and rv["script_hash"] == script_versions.content_hash(script_of(p))
    meta = script_of(p)["_meta"]
    assert meta["approval_mode"] == "local" and meta["approved_by"] == "سارة" and meta["status"] == "approved"
    s = script_of(p)                                                       # تعديل بعد الموافقة ← بتصير قديمة (نفس بوابة المراجعة العادية)
    s["scenes"][0]["voiceover"] += " زيادة"
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert not review_loop.is_cleared(p)[0]


def test_local_approval_blocks_on_any_blocker_without_override(env):
    pf, pid = setup(env)
    short = ms.create(pf, pid, seven(16, dur=3.0))                         # 21ث: برّا 45–50
    with pytest.raises(review_loop.ApprovalError, match="مانع.*المدة الكلية"):
        review_loop.approve_local(short)
    fast = ms.create(pf, pid, seven(40, dur=7.0))                          # 40 كلمة بـ7ث: أسرع من الممكن
    with pytest.raises(review_loop.ApprovalError, match="أسرع من الممكن"):
        review_loop.approve_local(fast)
    assert not review_loop.is_cleared(fast)[0]
    rows = seven()
    rows[2]["voiceover"] = "هالقطرة بتعالج الجفاف نهائياً وبتشفي العيون"       # ادعاء ممنوع (فئة صحة العين)
    claimy = ms.create(pf, pid, rows)
    with pytest.raises(review_loop.ApprovalError, match="مانع"):
        review_loop.approve_local(claimy)
    assert review_loop.load_review(claimy) is None                          # ما انكتبت مراجعة


def test_an_existing_ai_review_with_blockers_needs_an_explicit_confirm(env):
    pf, pid = setup(env)
    p = ms.create(pf, pid, seven())
    h = script_versions.content_hash(script_of(p))
    rp = review_loop.review_path(p)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"verdict": "revise", "blockers": 2, "findings": [], "script_hash": h, "_meta": {"provider": "fake"}}), encoding="utf-8")
    with pytest.raises(review_loop.ConfirmNeeded, match="متأكد"):
        review_loop.approve_local(p)
    assert not review_loop.is_cleared(p)[0]
    assert review_loop.approve_local(p, confirm=True)["approved"]
    assert review_loop.load_review(p)["_meta"]["provider"] == "local"
    review_loop.approve_local(p)                                           # مراجعة حسابية قبلها: ما بتحتاج تأكيد تاني


def test_from_recording_ignores_only_the_pace_blocker(env):
    pf, pid = setup(env)
    fast = ms.create(pf, pid, seven(40, dur=7.0))
    assert review_loop.approve_local(fast, from_recording=True)["approved"]
    claimy_rows = seven()
    claimy_rows[0]["voiceover"] = "نتيجة مضمونة بالكامل وعلاج نهائي للجفاف"
    claimy = ms.create(pf, pid, claimy_rows)
    with pytest.raises(review_loop.ApprovalError):
        review_loop.approve_local(claimy, from_recording=True)               # الادعاءات بتمنع حتى من تسجيل


# ───────────────────────── المسارات ─────────────────────────
def client():
    from web import routes_pipeline
    app = FastAPI()
    app.include_router(routes_pipeline.router)
    return TestClient(app)


def paragraphs(n=7, words=16):
    return "\n\n".join(" ".join(f"م{i}ك{j}" for j in range(words)) + "." for i in range(1, n + 1))


def test_create_route_text_excel_and_errors(env):
    pf, pid = setup(env)
    c = client()
    r = c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid, "title": "ع", "text": paragraphs()})
    assert r.status_code == 200 and r.json()["file"].endswith(".json") and r.json()["status"] == "draft" and r.json()["reviewed"] is False
    assert script_of(Path(config.SCRIPTS_DIR) / r.json()["file"])["title"] == "ع"
    wb = openpyxl.load_workbook(io.BytesIO(scene_import.template()))
    for i in range(7):
        wb["المشاهد"].append([" ".join(f"إ{i}ك{j}" for j in range(16)), None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid}, files={"file": ("s.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200
    both = c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid, "text": "x"}, files={"file": ("s.xlsx", buf.getvalue(), "application/octet-stream")})
    assert both.status_code == 400 and "مش الاتنين" in both.json()["detail"]
    r = c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid, "text": paragraphs(5)})
    assert r.status_code == 400 and "7 مشاهد بالضبط" in r.json()["detail"]
    assert c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid, "text": ""}).status_code == 400
    assert c.post("/api/scripts/manual", data={"product_file": "x.json", "pattern_id": pid, "text": paragraphs()}).status_code == 404
    assert c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": "zz", "text": paragraphs()}).status_code == 404
    assert c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid}, files={"file": ("s.xlsx", b"junk", "application/octet-stream")}).status_code == 400


def test_approve_local_route_confirm_flow_and_free_projects(env):
    pf, pid = setup(env)
    c = client()
    f = c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid, "text": paragraphs()}).json()["file"]
    p = Path(config.SCRIPTS_DIR) / f
    h = script_versions.content_hash(script_of(p))
    rp = review_loop.review_path(p)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"verdict": "revise", "blockers": 1, "findings": [], "script_hash": h, "_meta": {"provider": "x"}}), encoding="utf-8")
    r = c.post(f"/api/scripts/{f}/approve-local", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "needs_confirm" and "متأكد" in r.json()["detail"]["message"]
    r = c.post(f"/api/scripts/{f}/approve-local", json={"confirm": True})
    assert r.status_code == 200 and r.json()["approved"] and r.json()["status"] == "approved"
    bad = c.post("/api/scripts/manual", data={"product_file": pf, "pattern_id": pid, "text": "\n\n".join(["كلمة وحدة\nمدة: 3"] * 7)}).json()["file"]
    r = c.post(f"/api/scripts/{bad}/approve-local", json={})
    assert r.status_code == 409 and "مانع" in r.json()["detail"]
    import free_project as fp
    free = fp.create("حر")["file"]
    assert c.post(f"/api/scripts/{free}/approve-local", json={}).status_code == 409
    assert c.post("/api/scripts/none.json/approve-local", json={}).status_code == 404


# ───────────────────────── ابدأ من تسجيلك ─────────────────────────
def wav(path, seconds, rate=16000):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}:sample_rate={rate}", str(path)], check=True, capture_output=True)
    return Path(path)


def spoken(n_sent=7, words=10, per=0.62, gap=1.0, junk=""):
    t, out = 0.4, []
    for i in range(1, n_sent + 1):
        for j in range(words):
            out.append({"text": f"{junk}ج{i}ك{j}", "start": round(t, 3), "end": round(t + per - 0.05, 3)})
            t += per
        out[-1]["text"] += "."
        t += gap
    return out, t


def fake_stt(monkeypatch, words):
    import stt
    monkeypatch.setattr(stt, "transcribe", lambda audio, language=None: {"words": words, "segments": [], "full_text": " ".join(w["text"] for w in words),
                                                                      "language": "ar", "provider": "fake", "model": "fake-1"})


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg غير متوفر")
def test_from_voice_builds_the_script_approves_it_and_splits_the_voice(vs, tmp_path, monkeypatch):
    import voice_studio
    words, total = spoken()
    fake_stt(monkeypatch, words)
    res = ms.from_voice("testp.json", "p1", wav(tmp_path / "rec.wav", math.ceil(total) + 1), by="سارة", log=lambda m: None)
    assert res["ok"] and res["voice"]["ok"] and res["voice"]["scenes"] == 7 and res["file"].endswith(".json") and not res["reason"]
    p = Path(config.SCRIPTS_DIR) / res["file"]
    s = script_of(p)
    assert s["_meta"]["source"] == "manual" and "manual_voice" in p.name and len(s["scenes"]) == 7 and 45 <= s["total_duration_sec"] <= 50
    assert all(sc["voiceover"].startswith(f"ج") for sc in s["scenes"])
    assert review_loop.is_cleared(p)[0] and s["_meta"]["approval_mode"] == "local"
    assert studio_state.state_of(p.stem, 4) == "awaiting_choice"
    m = voice_studio.load_manifest(p.stem)
    assert m["provider"] == "upload" and len(m["scenes"]) == 7 and m["coverage"] == 1.0
    assert not list(ms.jobs_dir().glob("*")) or not any(ms.jobs_dir().iterdir())                      # الشغل المؤقت اتنضّف


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg غير متوفر")
def test_from_voice_with_too_few_sentences_or_a_claim_fails_clearly(vs, tmp_path, monkeypatch):
    words, total = spoken(n_sent=4)
    fake_stt(monkeypatch, words)
    with pytest.raises(ms.ManualScriptError, match="4 جمل بس.*7 مشاهد"):
        ms.from_voice("testp.json", "p1", wav(tmp_path / "a.wav", math.ceil(total) + 1), log=lambda m: None)
    assert not [f for f in Path(config.SCRIPTS_DIR).glob("*.json") if "manual" in f.name]
    words, total = spoken()
    words[3]["text"] = "علاج"
    words[4]["text"] = "نهائي"
    words[5]["text"] = "للجفاف"
    fake_stt(monkeypatch, words)
    res = ms.from_voice("testp.json", "p1", wav(tmp_path / "b.wav", math.ceil(total) + 1), log=lambda m: None)
    assert not res["ok"] and "الموافقة الحسابية" in res["reason"] and res["file"]                       # السيناريو انكتب (بتكمّل منه)، والموافقة وقفت
    assert review_loop.load_review(Path(config.SCRIPTS_DIR) / res["file"]) is None                     # ما انكتبت مراجعة محلية


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg غير متوفر")
def test_from_voice_route_makes_a_job_and_the_cli_writes_the_result_the_ui_polls(vs, tmp_path, monkeypatch):
    c = client()
    words, total = spoken()
    rec = wav(tmp_path / "rec.wav", math.ceil(total) + 1)
    url = "/api/scripts/manual/from-voice"
    data = {"product_file": "testp.json", "pattern_id": "p1"}
    assert c.post(url, data=data, files={"file": ("x.png", b"123", "image/png")}).status_code == 400
    assert c.post(url, data={**data, "product_file": "no.json"}, files={"file": ("r.wav", rec.read_bytes(), "audio/wav")}).status_code == 404
    assert c.post(url, data={**data, "pattern_id": "zz"}, files={"file": ("r.wav", rec.read_bytes(), "audio/wav")}).status_code == 404
    assert c.post(url, data=data, files={"file": ("bad.wav", b"not audio", "audio/wav")}).status_code == 400
    r = c.post(url, data={**data, "language": "ar"}, files={"file": ("r.wav", rec.read_bytes(), "audio/wav")})
    assert r.status_code == 200 and len(r.json()["token"]) == 32
    job = vs.env.jobs[-1]
    cmd = job["cmd"]
    assert job["kind"] == "voice" and cmd[:2] == ["manual_script.py", "from-voice"] and cmd[cmd.index("--token") + 1] == r.json()["token"]
    assert c.get(f"/api/scripts/manual/result/{r.json()['token']}").status_code == 404                  # لسا ما خلصت
    fake_stt(monkeypatch, words)
    monkeypatch.setattr(sys, "argv", ["manual_script.py", *cmd[1:]])
    ms.main()
    res = c.get(f"/api/scripts/manual/result/{r.json()['token']}").json()
    assert res["ok"] and res["file"].endswith(".json") and res["voice"]["scenes"] == 7
    assert c.get("/api/scripts/manual/result/zzz").status_code == 400
