"""ربط «أمر التشغيل» (link_cmd) عبر model_run: تعبئة الأماكن بلا shell، بيئة منظّفة، قتل مجموعة العمليات، وفحص الناتج. بسكربتات بايثون صغيرة."""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
import link_cmd  # noqa: E402
import model_library as ml  # noqa: E402
import model_run as mr  # noqa: E402
import production_log  # noqa: E402

PY = sys.executable

SCRIPTS = {
    "gen_png.py": """
import sys, json
from PIL import Image
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
open("seen_prompt.txt", "w", encoding="utf-8").write(a.get("--prompt", ""))
Image.new("RGB", (int(a["--width"]), int(a["--height"])), (10, 120, 200)).save(a["--out"])
""",
    "env_png.py": """
import sys, os, json
from PIL import Image
json.dump(sorted(os.environ), open("env_keys.json", "w"))
Image.new("RGB", (128, 128), (1, 2, 3)).save(sys.argv[1])
""",
    "fail.py": """
import sys
sys.stderr.write(sys.argv[2] + "\\n")
sys.exit(int(sys.argv[1]))
""",
    "sleeper.py": """
import subprocess, sys, json, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
json.dump({"parent": __import__("os").getpid(), "child": child.pid}, open("pids.json", "w"))
time.sleep(120)
""",
    "noop.py": "pass\n",
    "outdir_wav.py": """
import sys, wave
d = sys.argv[1]
with wave.open(d + "/result_123.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\\x10\\x00" * 8000)
open(d + "/notes.txt", "w").write("ignore me")
""",
    "stt_json.py": """
import sys, json
json.dump({"text": "نص مفرّغ", "words": [{"word": "نص", "start": 0, "end": 0.4}, {"word": "مفرّغ", "start": 0.5, "end": 1}]}, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
""",
    "stt_text.py": """
import sys
open(sys.argv[1], "w", encoding="utf-8").write("  نص عادي بلا JSON  \\n")
""",
    "chatty.py": """
import sys
for i in range(150000):
    sys.stdout.write("line %d padding padding padding padding\\n" % i)
sys.stdout.flush()
sys.exit(5)
""",
    "stdin_png.py": """
import sys
from PIL import Image
data = sys.stdin.read()
open("stdin_len.txt", "w").write(str(len(data)))
Image.new("RGB", (100, 100), (9, 9, 9)).save(sys.argv[1])
""",
    "readfile.py": """
import sys
src = open(sys.argv[1], encoding="utf-8").read()
open("seen_file.txt", "w", encoding="utf-8").write(src)
from PIL import Image
Image.new("RGB", (100, 100), (9, 9, 9)).save(sys.argv[2])
""",
    "refs_png.py": """
import sys, os, json
json.dump(sorted(os.listdir(sys.argv[1])), open("seen_refs.json", "w"))
from PIL import Image
Image.new("RGB", (100, 100), (9, 9, 9)).save(sys.argv[2])
""",
    "bg_png.py": """
import sys
from PIL import Image
im = Image.new("RGBA", (200, 200), (255, 0, 0, 0))
im.putpixel((5, 5), (255, 0, 0, 255))
im.save(sys.argv[1])
""",
}


@pytest.fixture
def box(tmp_path, monkeypatch):
    """مجلد التشغيل (cwd) فيه كل السكربتات + مكتبة مؤقتة."""
    monkeypatch.setattr(config, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    work = tmp_path / "work"
    work.mkdir()
    for name, body in SCRIPTS.items():
        (work / name).write_text(body, encoding="utf-8")
    return work


def cmd_model(work: Path, task: str, argv: list, *, env=None, glob=None, params=None, caps=None, **kw):
    raw = {"name": "أمر وهمي", "task": task, "link": "command", "enabled": True, "licence": {"id": "MIT", "commercial": "yes"},
           "command": {"argv": argv, "cwd": str(work), "output_glob": glob, "env": env or {}}, "params": params or {}, "caps": caps or {}, **kw}
    return ml.create(raw)


def alive(pid: int) -> bool:
    import psutil
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def wait_dead(pid: int, sec: float = 8.0) -> bool:
    end = time.monotonic() + sec
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


# ── الحالة الطبيعية ───────────────────────────────────────────────────────

def test_image_command_fills_the_placeholders_and_the_result_is_checked_and_logged(box, tmp_path):
    m = cmd_model(box, "image", [PY, "gen_png.py", "--prompt", "{prompt}", "--width", "{width}", "--height", "{height}", "--out", "{out}"],
                  params={"width": 640, "height": 480})
    out = tmp_path / "shots" / "x.png"
    weird = 'a "quoted" $(whoami) ; echo hi `id` %PATH% \'single\' end'
    res = mr.run(m, mr.RunRequest(task="image", prompt=weird, out=out, params={"width": 320}, script_stem="S", shot_id="f1"))
    assert res.kind == "image" and res.info["width"] == 320 and res.info["height"] == 480           # معامل النداء غلب معامل النموذج
    assert (box / "seen_prompt.txt").read_text(encoding="utf-8") == weird                            # بلا shell: ولا رمز اتفسّر
    row = production_log.recent(1, "image")[0]
    assert row["status"] == "ok" and row["path"] == "command" and row["model_id"] == m["id"]
    assert mr.tmp_root().exists() and list(mr.tmp_root().iterdir()) == []


def test_out_dir_and_glob_collect_the_newest_matching_file(box, tmp_path):
    m = cmd_model(box, "voice", [PY, "outdir_wav.py", "{out_dir}", "{text}"], glob="*.wav", params={"voice": "x"})
    out = tmp_path / "v.mp3"
    res = mr.run(m, mr.RunRequest(task="voice", text="مرحبا", out=out))
    assert res.kind == "audio" and out.is_file()
    import media_check
    assert media_check._audio_codec(out) == "mp3"                                                    # نفس قاعدة الواجهة القياسية: الامتداد صادق
    m2 = cmd_model(box, "voice", [PY, "outdir_wav.py", "{out_dir}", "{text}"], params={"voice": "x"})          # بلا glob: الأنماط الافتراضية للمهمة
    assert mr.run(m2, mr.RunRequest(task="voice", text="مرحبا", out=tmp_path / "v2.wav")).path.is_file()


def test_prompt_file_text_file_and_refs_are_real_files(box, tmp_path):
    m = cmd_model(box, "image", [PY, "readfile.py", "{prompt_file}", "{out}"])
    mr.run(m, mr.RunRequest(task="image", prompt="سطر أول\nسطر ثاني — وصف طويل", out=tmp_path / "a.png"))
    assert (box / "seen_file.txt").read_text(encoding="utf-8") == "سطر أول\nسطر ثاني — وصف طويل"
    v = cmd_model(box, "voice", [PY, "readfile.py", "{text_file}", "{out}"], params={})
    from PIL import Image
    # الأمر هون بيكتب صورة مش صوت، فنفحص بس إن الملف النصي انقرا (الفشل بالفحص متوقع)
    with pytest.raises(mr.RunError):
        mr.run(v, mr.RunRequest(task="voice", text="كلام المشهد", out=tmp_path / "v.mp3"))
    assert (box / "seen_file.txt").read_text(encoding="utf-8") == "كلام المشهد"
    r1, r2 = tmp_path / "r1.png", tmp_path / "r2.jpg"
    Image.new("RGB", (80, 80)).save(r1)
    Image.new("RGB", (80, 80)).save(r2)
    m2 = cmd_model(box, "image", [PY, "refs_png.py", "{refs}", "{out}", "{prompt}"], caps={"refs": True})
    mr.run(m2, mr.RunRequest(task="image", prompt="x", out=tmp_path / "b.png", refs=[r1, r2]))
    assert json.loads((box / "seen_refs.json").read_text()) == ["001.png", "002.jpg"]


def test_stt_command_parses_json_with_words_or_plain_text(box):
    audio = box / "a.wav"
    import fake_openai
    audio.write_bytes(fake_openai.wav_bytes(1.0))
    m = cmd_model(box, "stt", [PY, "stt_json.py", "{out}"] + ["{audio}"])
    d = mr.run(m, mr.RunRequest(task="stt", audio=audio)).data
    assert d["text"] == "نص مفرّغ" and [w["text"] for w in d["words"]] == ["نص", "مفرّغ"] and d["words"][1]["end"] == 1.0
    m2 = cmd_model(box, "stt", [PY, "stt_text.py", "{out}", "{audio}"])
    d2 = mr.run(m2, mr.RunRequest(task="stt", audio=audio)).data
    assert d2["text"] == "نص عادي بلا JSON" and d2["words"] == []


def test_bgremove_must_come_back_with_transparency(box, tmp_path):
    src = tmp_path / "in.png"
    from PIL import Image
    Image.new("RGB", (200, 200), (5, 5, 5)).save(src)
    good = cmd_model(box, "bgremove", [PY, "bg_png.py", "{out}", "{image}"])
    res = mr.run(good, mr.RunRequest(task="bgremove", image=src, out=tmp_path / "cut.png"))
    assert res.info["alpha"] is True
    flat = cmd_model(box, "bgremove", [PY, "gen_png.py", "--width", "200", "--height", "200", "--out", "{out}", "--prompt", "{image}"])
    with pytest.raises(mr.RunError, match="خلفية شفافة") as e:
        mr.run(flat, mr.RunRequest(task="bgremove", image=src, out=tmp_path / "flat.png"))
    assert e.value.reason == "bad_output" and e.value.technical
    with pytest.raises(mr.RunError, match="شفافية|PNG|png"):                                          # JPG ما بيحمل شفافية
        mr.run(good, mr.RunRequest(task="bgremove", image=src, out=tmp_path / "cut.jpg"))


# ── الأمان: بيئة منظّفة ───────────────────────────────────────────────────

def test_the_command_never_sees_keys_or_tokens_from_our_environment(box, tmp_path, monkeypatch):
    secrets = {"ANTHROPIC_API_KEY": "sk-ant-FAKE-aaaa", "VP_SECRETS_KEY": "FAKE-vault-pass-1234567", "ENGINE_TOKEN": "FAKE-tok",
               "AWS_SECRET_ACCESS_KEY": "FAKE-aws", "HF_TOKEN": "FAKE-hf", "VP_ACTOR": "سارة", "CUDA_VISIBLE_DEVICES": "0", "MY_FLAG": "x"}
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    m = cmd_model(box, "image", [PY, "env_png.py", "{out}", "{prompt}"], env={"MY_FLAG": "1", "TTS_MODE": "fast"})
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "e.png"))
    seen = set(json.loads((box / "env_keys.json").read_text()))
    assert not seen & {"ANTHROPIC_API_KEY", "VP_SECRETS_KEY", "ENGINE_TOKEN", "AWS_SECRET_ACCESS_KEY", "HF_TOKEN", "VP_ACTOR"}
    assert {"PATH", "CUDA_VISIBLE_DEVICES", "MY_FLAG", "TTS_MODE", "PYTHONIOENCODING"} <= seen


def test_clean_env_guards_against_secret_looking_extras_too():
    env = link_cmd.clean_env({"API_KEY": "x", "MY_TOKEN": "y", "SAFE_NAME": "z"})
    assert "API_KEY" not in env and "MY_TOKEN" not in env and env["SAFE_NAME"] == "z" and env["PYTHONUTF8"] == "1"


def test_there_is_no_shell_and_stdin_is_closed(box, tmp_path):
    m = cmd_model(box, "image", [PY, "stdin_png.py", "{out}", "{prompt}"])
    mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "s.png"))
    assert (box / "stdin_len.txt").read_text() == "0"                                                # ما استنى إدخال


# ── الفشل ─────────────────────────────────────────────────────────────────

def test_exit_codes_and_output_tail_become_the_message(box, tmp_path):
    m = cmd_model(box, "image", [PY, "fail.py", "3", "{prompt}", "{out}"])
    with pytest.raises(mr.RunError, match=r"فشل \(3\): تعطّل بسبب كذا") as e:
        mr.run(m, mr.RunRequest(task="image", prompt="تعطّل بسبب كذا", out=tmp_path / "f.png"))
    assert e.value.reason == "model_failed" and e.value.technical
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="CUDA out of memory. Tried to allocate 20 GiB", out=tmp_path / "f.png"))
    assert e.value.reason == "oom"
    assert [r["status"] for r in production_log.recent(2, "image")] == ["failed", "failed"]


def test_chatty_output_does_not_deadlock_and_the_tail_stays_small(box, tmp_path):
    m = cmd_model(box, "image", [PY, "chatty.py", "{out}", "{prompt}"])
    logged = []
    t0 = time.monotonic()
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "c.png", log=logged.append))
    assert time.monotonic() - t0 < 60 and "فشل (5)" in str(e.value) and len(str(e.value)) < 500
    assert len(logged) <= link_cmd.MAX_LOG_LINES + 5                                                  # سجل المهمة ما بيغرق بملايين السطور


def test_success_without_an_output_file_is_a_bad_output(box, tmp_path):
    m = cmd_model(box, "image", [PY, "noop.py", "{out}", "{prompt}"])
    with pytest.raises(mr.RunError, match="ما كتب ملف ناتج") as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "n.png"))
    assert e.value.reason == "bad_output"


def test_missing_program_and_missing_cwd_and_missing_inputs(box, tmp_path):
    m = cmd_model(box, "image", ["definitely-not-a-program-xyz", "{prompt}", "{out}"])
    with pytest.raises(mr.RunError, match="غير موجود") as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "a.png"))
    assert e.value.reason == "model_failed" and e.value.technical
    m2 = cmd_model(box, "image", [PY, "noop.py", "{prompt}", "{out}"])
    m2["command"]["cwd"] = str(tmp_path / "nowhere")
    with pytest.raises(mr.RunError, match="مجلد التشغيل مش موجود") as e:
        mr.run(m2, mr.RunRequest(task="image", prompt="x", out=tmp_path / "b.png"))
    assert e.value.reason == "config"
    m3 = cmd_model(box, "image", [PY, "gen_png.py", "--width", "{width}", "--height", "10", "--prompt", "{prompt}", "--out", "{out}"])
    with pytest.raises(mr.RunError, match=r"\{width\}") as e:
        mr.run(m3, mr.RunRequest(task="image", prompt="x", out=tmp_path / "c.png"))
    assert e.value.reason == "config"
    up = cmd_model(box, "upscale", [PY, "noop.py", "{image}", "{out}"])
    with pytest.raises(mr.RunError, match=r"\{image\}") as e:
        mr.run(up, mr.RunRequest(task="upscale", out=tmp_path / "d.png"))
    assert e.value.reason == "config" and not e.value.technical


# ── المهلة والإلغاء: قتل المجموعة كلها ────────────────────────────────────

def test_timeout_kills_the_whole_process_group(box, tmp_path):
    m = cmd_model(box, "image", [PY, "sleeper.py", "{prompt}", "{out}"])
    m["timeout_sec"] = 5
    t0 = time.monotonic()
    with pytest.raises(mr.RunError, match="تجاوز المهلة") as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "t.png"))
    assert e.value.reason == "timeout" and e.value.technical and time.monotonic() - t0 < 30
    pids = json.loads((box / "pids.json").read_text())
    assert wait_dead(pids["parent"]) and wait_dead(pids["child"])                                       # حتى الابن اللي ولّده الأمر


def test_cancel_kills_the_group_and_is_not_a_technical_failure(box, tmp_path):
    m = cmd_model(box, "image", [PY, "sleeper.py", "{prompt}", "{out}"])
    ev = threading.Event()
    threading.Timer(3.0, ev.set).start()
    t0 = time.monotonic()
    with pytest.raises(mr.RunError) as e:
        mr.run(m, mr.RunRequest(task="image", prompt="x", out=tmp_path / "c.png", cancel=ev))
    assert e.value.reason == "cancelled" and e.value.technical is False and time.monotonic() - t0 < 30
    pids = json.loads((box / "pids.json").read_text())
    assert wait_dead(pids["parent"]) and wait_dead(pids["child"])
    assert mr.tmp_root().exists() and list(mr.tmp_root().iterdir()) == []                              # المجلد المؤقت انشال حتى بالإلغاء
