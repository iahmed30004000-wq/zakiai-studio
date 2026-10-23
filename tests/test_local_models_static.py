# -*- coding: utf-8 -*-
"""فحوص ساكنة لسكربتات النماذج المحلية على جهاز المالك (tools/local_models/).
بلا إنترنت وبلا تشغيل — بس قراءة الملفات: لا أسرار، تراخيص مذكورة، أنماط مسموحة، وصياغة صحيحة."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "local_models"

# المحتوى بـ .ps1، وجنب كل واحد .bat بنفس الاسم بس لينفتح بالنقر المزدوج
SCRIPTS = ["1_whisper_turbo_ar.ps1", "2_chatterbox.ps1", "3_ace_step.ps1", "4_stable_audio.ps1",
           "تشغيل الصوت العربي.ps1", "تشغيل الموسيقى.ps1"]

# أنماط أسرار شائعة (توكنات/مفاتيح) — لازم ما يكون ولا وحدة بسكربتات الجهاز
SECRET_RX = [
    re.compile(r"hf_[A-Za-z0-9]{20,}"),           # توكن HuggingFace
    re.compile(r"sk-[A-Za-z0-9]{20,}"),           # مفتاح OpenAI
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"][^'\"]{8,}"),
]

ALLOWED_REPO_DIRS = {"models"}                   # الأوزان دايماً تحت models/


def _text(name: str) -> str:
    return (TOOLS / name).read_text(encoding="utf-8-sig")


# ───────── أسرار ─────────
@pytest.mark.parametrize("name", SCRIPTS + ["fetch_model.py", "stable_audio_cmd.py"])
def test_no_secrets_in_scripts(name):
    t = _text(name)
    for rx in SECRET_RX:
        assert not rx.search(t), f"أسرار ممنوعة بـ {name}: {rx.pattern}"


# ───────── تراخيص مذكورة ─────────
@pytest.mark.parametrize("name,licence", [
    ("1_whisper_turbo_ar.ps1", "Apache-2.0"),
    ("2_chatterbox.ps1", "MIT"),
    ("2_chatterbox.ps1", "AGPL-3.0"),
    ("3_ace_step.ps1", "Apache-2.0"),
    ("4_stable_audio.ps1", "Stability AI Community"),
    ("stable_audio_cmd.py", "Stability AI Community"),
])
def test_licence_note_present(name, licence):
    assert licence in _text(name), f"الترخيص {licence} لازم يكون مكتوب بـ {name}"


# ───────── fetch_model.py ─────────
def test_fetch_model_uses_allow_patterns_and_no_trust_remote_code():
    t = _text("fetch_model.py")
    assert "allow_patterns" in t
    assert "trust_remote_code=True" not in t           # ما مننفّذ كود من النت
    assert "MODELS_DIR" in t and "models" in t         # الأوزان تحت models/
    assert "token=None" in t or "huggingface-cli login" in t   # ما منخزّن توكن
    assert "snapshot_download" in t


def test_fetch_model_snapshot_download_kwargs_exist():
    # وسيط مش موجود بالدالة بيوقّع التنزيل بـ TypeError (صار مع trust_remote_code)
    hub = pytest.importorskip("huggingface_hub")
    import ast
    import inspect
    accepted = set(inspect.signature(hub.snapshot_download).parameters)
    calls = [n for n in ast.walk(ast.parse(_text("fetch_model.py")))
             if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "snapshot_download"]
    assert calls, "fetch_model.py لازم ينادي snapshot_download"
    for c in calls:
        unknown = {k.arg for k in c.keywords if k.arg} - accepted
        assert not unknown, f"وسائط مش موجودة بـ snapshot_download: {unknown}"


def test_fetch_model_checks_disk_and_gpu():
    t = _text("fetch_model.py")
    assert "disk_usage" in t                            # فحص المساحة
    assert "nvidia-smi" in t                            # فحص كرت الشاشة
    assert "already_done" in t                          # السكربت idempotent: بينط لو منزّل


# ───────── مشغّل .bat: cmd بينادي PowerShell عالـ .ps1 اللي جنبه ─────────
@pytest.mark.parametrize("name", SCRIPTS)
def test_bat_launcher_runs_sibling_ps1(name):
    bat = TOOLS / name.replace(".ps1", ".bat")
    assert bat.exists(), f"ناقص المشغّل {bat.name}"
    raw = bat.read_bytes()
    assert raw.isascii(), f"{bat.name} لازم يكون إنجليزي بس (cmd بيخربط العربي)"
    t = raw.decode("ascii")
    assert t.lower().startswith("@echo off")
    assert "powershell" in t.lower() and '-File "%~dp0%~n0.ps1"' in t
    assert "<#" not in t and "$ErrorActionPreference" not in t   # ما في PowerShell جوّا الـ .bat


@pytest.mark.parametrize("name", SCRIPTS)
def test_ps1_has_utf8_bom(name):
    # PowerShell 5.1 بيقرأ الملف بلا BOM كـ ANSI فالعربي بيطلع مخربط
    assert (TOOLS / name).read_bytes().startswith(b"\xef\xbb\xbf"), f"{name} لازم UTF-8 مع BOM"


# ───────── كل سكربت تنزيل بينادي fetch_model.py بأوزان تحت models/ ─────────
@pytest.mark.parametrize("name", [b for b in SCRIPTS if b[0].isdigit()])
def test_fetch_scripts_call_fetch_model_with_models_dest(name):
    t = _text(name)
    assert "fetch_model.py" in t, f"{name} لازم ينادي fetch_model.py"
    m = re.search(r'--dest\s+"(models/[^"]+)"', t)
    assert m, f"{name} لازم يحدد --dest تحت models/"
    assert m.group(1).split("/")[0] in ALLOWED_REPO_DIRS
    assert re.search(r'--allow\s+"', t), f"{name} لازم يحدد أنماط ملفات مسموحة"


# ───────── موديلات مقيّدة بدها login قبلها ─────────
def test_gated_model_tells_owner_to_login():
    t = _text("4_stable_audio.ps1")
    assert "huggingface-cli login" in t
    assert "stabilityai/stable-audio-open-1.0" in t
    t2 = _text("fetch_model.py")
    assert "--gated" in t2


# ───────── منافذ محلية بس (net_allow يقبل 127.0.0.1 بمنفذ صريح) ─────────
@pytest.mark.parametrize("name,host", [
    ("تشغيل الصوت العربي.ps1", "127.0.0.1"),
    ("تشغيل الموسيقى.ps1", "127.0.0.1"),
])
def test_servers_bind_loopback_only(name, host):
    t = _text(name)
    assert host in t
    assert "0.0.0.0" not in t, f"{name} لازم يسمع على {host} بس، مش عالشبكة"


# ───────── صياغة بايثون ─────────
@pytest.mark.parametrize("name", ["fetch_model.py", "stable_audio_cmd.py"])
def test_py_compile(name):
    r = subprocess.run([sys.executable, "-m", "py_compile", str(TOOLS / name)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ───────── stable_audio_cmd يفهم أماكن الملفات القياسية ─────────
def test_stable_audio_cmd_uses_std_placeholders():
    t = _text("stable_audio_cmd.py")
    for ph in ("--prompt", "--prompt-file", "--out", "--seconds"):
        assert ph in t, f"ناقص {ph} — ضروري للربط بـ «أمر تشغيل» (PLACEHOLDERS)"
    assert "StableAudioPipeline" in t
    assert "enable_model_cpu_offload" in t              # كرت 6 غيغا — لازم CPU offload
    assert "float16" in t or "fp16" in t


# ───────── مقاطع الأوزان اللي بنمط allow_patterns موجودة فعلاً بالريبو ─────────
def test_whisper_allow_patterns_cover_the_bin():
    t = _text("1_whisper_turbo_ar.ps1")
    assert '"*.bin"' in t and '"*.json"' in t           # model.bin + config/tokenizer
