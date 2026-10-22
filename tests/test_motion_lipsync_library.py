"""مزامنة الشفاه من مكتبة النماذج: نموذج افتراضي بيخدم أي موديل تحريك ما إله أمر مزامنة، والأمر الخاص بالموديل أولى، وبلا بديل لو وقع."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import model_library as ml  # noqa: E402
import motion  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")

SHOT = {"id": "s1c1", "type": "medium", "start_ms": 0, "end_ms": 1000, "motion_desc": "", "refs": {}, "talking": True}
PLAIN = {"id": "mm_001", "name": "تحريك بلا مزامنة", "kind": "command", "max_sec": 6, "vram_gb": 0, "strengths": ["faces", "realism"], "speed_sec_per_sec": 10,
         "command": ["python", "x.py"], "lipsync_command": None, "lipsync": False, "enabled": True}
OWN = {**PLAIN, "id": "mm_002", "name": "تحريك بمزامنته", "lipsync_command": ["python", "-c", "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[3]); open(sys.argv[3] + '.own', 'w').write('own')",
                                                                              "{video}", "{audio}", "{out}"], "lipsync": True}
COPY = ["python", "-c", "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[3])", "{video}", "{audio}", "{out}"]
FAIL = ["python", "-c", "import sys; sys.exit(3)", "{video}", "{audio}", "{out}"]


@pytest.fixture(autouse=True)
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    return tmp_path


def lipsync_model(argv=COPY, **over):
    raw = {"name": "مزامنة من المكتبة", "task": "lipsync", "link": "command", "enabled": True, "licence": {"id": "Apache-2.0", "commercial": "yes"}, "command": {"argv": argv}, "timeout_sec": 60}
    raw.update(over)
    m = ml.create(raw)
    ml.set_default("lipsync", m["id"])
    return m


def make_video(path: Path, sec: float = 1.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=s=96x160:d={sec}:r=12", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture
def voice(tmp_path, monkeypatch):
    """مانيفست صوت مدموج حقيقي (ثانية صمت) كي تقص منه _lipsync مقطع اللقطة."""
    wav = tmp_path / "library" / "voice_full.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "2", str(wav)], check=True)
    import voice_studio
    monkeypatch.setattr(voice_studio, "load_manifest", lambda stem: {"combined": {"path": "voice_full.wav"}})
    return wav


def test_a_talking_shot_accepts_every_model_when_the_library_has_a_default_lipsync_model():
    r = motion.rank_models(SHOT, [PLAIN, OWN], vram_gb=8, talking=True)
    assert [x["model"]["id"] for x in r["ranked"]] == ["mm_002"] and "ما بيدعم مزامنة شفاه" in r["excluded"][0]["reason"]          # بلا افتراضي: بس اللي إله أمر
    lipsync_model()
    r = motion.rank_models(SHOT, [PLAIN, OWN], vram_gb=8, talking=True)
    assert {x["model"]["id"] for x in r["ranked"]} == {"mm_001", "mm_002"} and not r["excluded"]
    plain_shot = {**SHOT, "talking": False}
    assert len(motion.rank_models(plain_shot, [PLAIN, OWN], vram_gb=8)["ranked"]) == 2                                       # لقطة بلا كلام: ما بتتأثر


def test_a_disabled_or_forbidden_library_model_is_not_a_default_for_ranking():
    m = lipsync_model()
    ml.update(m["id"], {"enabled": False})
    assert [x["model"]["id"] for x in motion.rank_models(SHOT, [PLAIN, OWN], vram_gb=8, talking=True)["ranked"]] == ["mm_002"]
    bad = ml.create({"name": "ممنوع", "task": "lipsync", "link": "command", "enabled": False, "licence": {"id": "NC", "commercial": "no"}, "command": {"argv": COPY}})
    with pytest.raises(ml.ModelLibraryError, match="ما بنقدر نجعله الافتراضي"):
        ml.set_default("lipsync", bad["id"])                                              # رخصته بتمنع: ما بينجعل افتراضي أبداً
    assert motion._library_lipsync() is None


def test_lipsync_uses_the_library_model_for_a_model_without_its_own_command(tmp_path, voice):
    lipsync_model()
    video = make_video(tmp_path / "v.mp4")
    out, lip = motion._lipsync("s1", SHOT, PLAIN, video, tmp_path, lambda *_: None)
    assert lip is True and out.name.endswith("_lip_fit.mp4") and out.exists() and out.stat().st_size > 1000
    assert (tmp_path / "s1c1_voice.wav").exists()                                          # مقطع الصوت المقصوص للقطة
    import production_log
    row = production_log.recent(5, "lipsync")[0]
    assert row["path"] == "command" and row["status"] == "ok" and row["shot_id"] == "s1c1"


def test_the_models_own_lipsync_command_wins_over_the_library_default(tmp_path, voice):
    lipsync_model()
    video = make_video(tmp_path / "v2.mp4")
    out, lip = motion._lipsync("s1", SHOT, OWN, video, tmp_path, lambda *_: None)
    assert lip is True and (tmp_path / "v2_lip.mp4.own").exists()                          # اشتغل أمر الموديل مش نموذج المكتبة


def test_no_command_and_no_library_default_is_a_clear_owner_error(tmp_path, voice):
    with pytest.raises(motion.MotionError, match="ما في نموذج مزامنة افتراضي بمكتبة النماذج"):
        motion._lipsync("s1", SHOT, PLAIN, make_video(tmp_path / "v3.mp4"), tmp_path, lambda *_: None)


def test_a_failing_library_lipsync_is_a_motion_error_never_a_silent_switch(tmp_path, voice):
    lipsync_model(FAIL)
    with pytest.raises(motion.MotionError) as e:
        motion._lipsync("s1", SHOT, PLAIN, make_video(tmp_path / "v4.mp4"), tmp_path, lambda *_: None)
    assert not isinstance(e.value, motion.TechnicalError)                                  # خطأ مالك/حالة: ما في بديل (ما بنجرّب موديل تحريك تاني بنفس المزامنة)
    assert "مزامنة الشفاه بنموذج «مزامنة من المكتبة» فشلت" in str(e.value)
    import production_log
    assert production_log.recent(5, "lipsync")[0]["status"] == "failed"
