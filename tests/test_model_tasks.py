"""«جرّب» (model_tasks): عيّنات جاهزة أو ملفات المالك، نتيجة محفوظة، قبل التفعيل، وبلا تأثير على سجل الإنتاج."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
import media_check  # noqa: E402
import model_library as ml  # noqa: E402
import model_tasks as mt  # noqa: E402
import production_log  # noqa: E402
from fake_openai import FakeOpenAI, wav_bytes  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    return tmp_path


@pytest.fixture
def srv(lib):
    s = FakeOpenAI().start()
    yield s
    s.stop()


def std(base, task, **kw):
    raw = {"name": "نموذج", "task": task, "link": "std", "enabled": False, "licence": {"id": "MIT", "commercial": "yes"},
           "std": {"url": base, "model": "m1"}, **kw}
    return ml.create(raw)


def cmd(work, task, argv, **kw):
    raw = {"name": "أمر", "task": task, "link": "command", "enabled": False, "licence": {"id": "MIT", "commercial": "yes"},
           "command": {"argv": argv, "cwd": str(work)}, **kw}
    return ml.create(raw)


def test_image_try_runs_before_enabling_with_the_builtin_sample_and_is_not_counted(lib, srv):
    m = std(srv.base, "image")
    assert m["enabled"] is False
    last = mt.run_try(m["id"])
    assert last["ok"] and last["kind"] == "image" and last["file"] == "result.png" and last["info"]["width"] == 512
    f = mt.result_file(m["id"])
    assert f and f.is_file() and mt.last_result(m["id"])["ok"]
    assert "perfume" in srv.last("/images/generations")["json"]["prompt"]
    assert production_log.recent(5) == []                                                  # التجربة ما بتنحسب بنسبة النجاح


def test_owner_inputs_replace_the_sample_and_are_validated(lib, srv):
    m = std(srv.base, "voice", params={"voice": "x"})
    mt.save_params(m["id"], {"text": "  جملتي أنا  "})
    last = mt.run_try(m["id"])
    assert last["file"] == "result.mp3" and srv.last("/audio/speech")["json"]["input"] == "جملتي أنا"
    assert media_check._audio_codec(mt.result_file(m["id"])) == "mp3"
    assert mt.clean_params({"prompt": "p", "seconds": "3", "junk": 1, "text": "  "}) == {"prompt": "p", "seconds": 3.0}
    for bad in ({"prompt": "x" * 501}, {"seconds": "abc"}, {"seconds": 0}, {"seconds": 500}):
        with pytest.raises(mt.TryError):
            mt.clean_params(bad)
    assert mt.clean_params("junk") == {}


def test_transcription_needs_an_uploaded_recording_and_returns_text_with_timing_info(lib, srv):
    m = std(srv.base, "stt")
    with pytest.raises(mt.TryError, match="ارفع تسجيل"):
        mt.run_try(m["id"])
    d = mt.test_dir(m["id"]) / "in"
    d.mkdir(parents=True)
    (d / "audio.wav").write_bytes(wav_bytes(1.2))
    last = mt.run_try(m["id"])
    assert last["data"] == {"text": "مرحبا بكم", "language": "ar", "words": 2, "word_timing": True, "segments": 1} and last["file"] is None
    assert mt.result_file(m["id"]) is None


def test_upscale_and_bgremove_use_a_generated_sample_image(lib):
    w = lib / "w"
    w.mkdir()
    (w / "up.py").write_text("import sys\nfrom PIL import Image\nim = Image.open(sys.argv[1])\nim.resize((im.width * 2, im.height * 2)).save(sys.argv[2])\n", encoding="utf-8")
    (w / "bg.py").write_text("import sys\nfrom PIL import Image\nim = Image.open(sys.argv[1]).convert('RGBA')\nim.putalpha(Image.new('L', im.size, 200))\nim.save(sys.argv[2])\n", encoding="utf-8")
    up = cmd(w, "upscale", [sys.executable, "up.py", "{image}", "{out}"], params={"scale": 2})
    last = mt.run_try(up["id"])
    assert last["info"]["width"] == 512 and last["info"]["height"] == 768                  # عيّنة 256×384 ← ×2
    bg = cmd(w, "bgremove", [sys.executable, "bg.py", "{image}", "{out}"])
    assert mt.run_try(bg["id"])["info"]["alpha"] is True


def test_failures_are_saved_and_the_old_result_disappears(lib, srv):
    m = std(srv.base, "image")
    mt.run_try(m["id"])
    assert mt.result_file(m["id"])
    srv.modes["images"] = "error500"
    with pytest.raises(mt.TryError, match="boom internal"):
        mt.run_try(m["id"])
    last = mt.last_result(m["id"])
    assert last["ok"] is False and last["reason"] == "model_failed" and "boom internal" in last["message"]
    assert mt.result_file(m["id"]) is None and not list(mt.test_dir(m["id"]).glob("result.*"))


def test_the_licence_gate_still_applies_to_tests(lib, srv):
    no = std(srv.base, "image", licence={"id": "NC", "commercial": "no"})
    with pytest.raises(mt.TryError, match="بتمنع الاستخدام التجاري"):
        mt.run_try(no["id"])
    unsure = std(srv.base, "image", licence={"id": "X", "commercial": "unknown"})
    with pytest.raises(mt.TryError, match="محتاجة مراجعتك"):
        mt.run_try(unsure["id"])
    ml.update(unsure["id"], {"licence": {"confirmed_by_owner": True}}, by="أحمد")
    assert mt.run_try(unsure["id"])["ok"]
    assert srv.requests                                                                    # الممنوع والمعلّق ما بعتوا ولا طلب قبل التأكيد
    with pytest.raises(mt.TryError, match="مش موجود"):
        mt.run_try("ml_404")
    with pytest.raises(mt.TryError, match="غير صالح"):
        mt.test_dir("../x")


def test_input_files_are_found_by_kind_and_clear_removes_everything(lib, srv):
    m = std(srv.base, "stt")
    d = mt.test_dir(m["id"]) / "in"
    d.mkdir(parents=True)
    (d / "audio.mp3").write_bytes(b"x")
    (d / "notes.txt").write_text("x")
    assert mt.input_path(m["id"], "audio").name == "audio.mp3" and mt.input_path(m["id"], "video") is None and mt.input_path(m["id"], "../x") is None
    mt.clear(m["id"])
    assert not mt.test_dir(m["id"]).exists()


def test_the_cli_entry_reports_success_and_exits_with_the_message_on_failure(lib, srv, monkeypatch, capsys):
    m = std(srv.base, "image")
    monkeypatch.setattr(sys, "argv", ["model_tasks.py", "try", m["id"]])
    mt.main()
    assert "[✓]" in capsys.readouterr().out
    srv.modes["images"] = "error500"
    with pytest.raises(SystemExit) as e:
        mt.main()
    assert str(e.value).startswith("[!]") and "boom internal" in str(e.value)
