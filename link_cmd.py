"""
ربط «أمر تشغيل» (command): سطر أوامر بتكتبه إنت بأماكن للملفات، والنظام بيعبّيها ويشغّله ويجمع الناتج.

    ["python", "gen_image.py", "--prompt", "{prompt}", "--width", "{width}", "--out", "{out}"]

أماكن الملفات (model_library.PLACEHOLDERS): {prompt} {prompt_file} {negative} {text} {text_file} {image} {refs} {audio} {video}
{out} (ملف الناتج) {out_dir} (مجلد للناتج) {seconds} {width} {height} {language} {voice} {scale} {seed} {steps}.

قواعد ثابتة:
  · بلا shell أبداً (قائمة وسائط): اللي بيتحط بالمكان ما بيتفسّر كأمر.
  · بيئة منظّفة: بس متغيّرات التشغيل المعروفة (PATH، TEMP، CUDA…) + متغيّرات النموذج نفسها. أي مفتاح أو توكن (ANTHROPIC_API_KEY،
    VP_SECRETS_KEY، ENGINE_TOKEN…) ما بيوصل للأمر.
  · مجلد مؤقت لكل تشغيل، والأمر بيشتغل بمجموعة عمليات لحاله: لو انتهت المهلة أو انلغت الشغلة بنقتل المجموعة كلها (مش بس الأب).
  · الناتج بينفحص بالمحتوى قبل ما يدخل (model_run).
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path

import model_library
from model_run import Ctx, RunError

OUT_EXT = {"image": ".png", "upscale": ".png", "bgremove": ".png", "voice": ".wav", "music": ".wav", "sfx": ".wav", "lipsync": ".mp4", "stt": ".json"}
DEFAULT_GLOB = {"image": ("*.png", "*.jpg", "*.jpeg", "*.webp"), "upscale": ("*.png", "*.jpg", "*.jpeg", "*.webp"), "bgremove": ("*.png", "*.webp"),
                "voice": ("*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a"), "music": ("*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a"),
                "sfx": ("*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a"), "lipsync": ("*.mp4", "*.mov", "*.webm", "*.mkv"), "stt": ("*.json", "*.txt")}
ENV_KEEP = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "LANG", "TZ", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CUDA_HOME", "CUDA_PATH",
            "LD_LIBRARY_PATH", "HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "TORCH_HOME", "XDG_CACHE_HOME", "NUMBA_CACHE_DIR"}
ENV_KEEP_PREFIX = ("LC_", "CUDA_", "NVIDIA_")
TAIL_BYTES = 20 * 1024
MAX_LOG_LINES = 300
KILL_GRACE_SEC = 5


def clean_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEEP or k.upper().startswith(ENV_KEEP_PREFIX)}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    for k, v in (extra or {}).items():
        if not model_library.ENV_BLOCK_RX.search(k):               # حماية ثانية: القالب نفسه بيرفض هالأسماء وقت الحفظ
            env[k] = str(v)
    return env


def _num_text(v, what: str) -> str:
    if v in (None, ""):
        raise RunError(f"الأمر بدّه {{{what}}} وما في قيمة — حطها بمعاملات النموذج", "config")
    return str(int(v)) if isinstance(v, (int, float)) and float(v) == int(v) else str(v)


def _values(ctx: Ctx, used: set[str], out: Path, out_dir: Path) -> dict[str, str]:
    req, p = ctx.req, ctx.params
    vals: dict[str, str] = {"out": str(out), "out_dir": str(out_dir)}
    for name in used:
        if name in vals:
            continue
        if name in ("prompt", "prompt_file"):
            if not req.prompt.strip():
                raise RunError("ما في وصف للنموذج", "config", False)
            if name == "prompt":
                vals[name] = req.prompt
            else:
                f = ctx.tmp / "prompt.txt"
                f.write_text(req.prompt, encoding="utf-8")
                vals[name] = str(f)
        elif name == "negative":
            vals[name] = str(p.get("negative") or req.negative or "")
        elif name in ("text", "text_file"):
            if not req.text.strip():
                raise RunError("ما في نص للنموذج", "config", False)
            if name == "text":
                vals[name] = req.text
            else:
                f = ctx.tmp / "text.txt"
                f.write_text(req.text, encoding="utf-8")
                vals[name] = str(f)
        elif name in ("image", "audio", "video"):
            src = getattr(req, name)
            if not src or not Path(src).is_file():
                raise RunError(f"الأمر بدّه {{{name}}} وما انعطى ملف", "config", False)
            vals[name] = str(Path(src).resolve())
        elif name == "refs":
            refs = [Path(x) for x in (req.refs or []) if Path(x).is_file()]
            if not refs:
                raise RunError("الأمر بدّه {refs} وما انعطى صور مرجعية", "config", False)
            d = ctx.tmp / "refs"
            d.mkdir(exist_ok=True)
            for i, f in enumerate(refs[:8], 1):
                shutil.copyfile(f, d / f"{i:03d}{f.suffix.lower() or '.png'}")
            vals[name] = str(d)
        elif name == "seconds":
            vals[name] = _num_text(req.seconds if req.seconds is not None else p.get("seconds"), name)
        elif name in ("width", "height", "steps", "seed", "scale"):
            vals[name] = _num_text(p.get(name), name)
        elif name == "language":
            vals[name] = str(req.language or p.get("language") or "ar")
        elif name == "voice":
            vals[name] = str(p.get("voice") or "")
    return vals


def _fill(argv: list[str], vals: dict[str, str]) -> list[str]:
    return [model_library.PLACEHOLDER_RX.sub(lambda m: vals.get(m.group(1), m.group(0)), a) for a in argv]


def _kill(proc: subprocess.Popen) -> None:
    """بيقتل المجموعة كلها (الأب وأي عملية ولّدها)."""
    if proc.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=KILL_GRACE_SEC)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _spawn(argv: list[str], cwd: str | None, env: dict) -> subprocess.Popen:
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "cwd": cwd, "env": env}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(argv, **kw)


def _pump(proc: subprocess.Popen, ctx: Ctx, tail: collections.deque) -> None:
    n = size = 0
    for raw in iter(proc.stdout.readline, b""):
        tail.append(raw)
        size += len(raw)
        while size > TAIL_BYTES and len(tail) > 1:
            size -= len(tail.popleft())
        n += 1
        if n <= MAX_LOG_LINES:
            ctx.log("    [cmd] " + raw.decode("utf-8", "replace").rstrip()[:200])
    try:
        proc.stdout.close()
    except OSError:
        pass


def _find_output(ctx: Ctx, used: set[str], out: Path, out_dir: Path, cfg: dict) -> Path | None:
    task = ctx.req.task
    if "out" in used and out.is_file() and out.stat().st_size > 0:
        return out
    pats = (cfg.get("output_glob"),) if cfg.get("output_glob") else DEFAULT_GLOB[task]
    roots = [out_dir] if "out_dir" in used else []
    if cfg.get("output_glob") or "out" in used:
        roots.append(ctx.tmp)                                          # أدوات بتزيد امتداد على اسم الناتج (out ← out.png)
    cands = []
    for root in roots:
        for pat in pats:
            cands += [f for f in root.glob(pat) if f.is_file() and f.stat().st_size > 0 and f.parent != ctx.tmp / "refs"
                      and f.name not in ("prompt.txt", "text.txt")]
        if "out" in used:
            cands += [f for f in root.glob("out.*") if f.is_file() and f.stat().st_size > 0]
    return max(cands, key=lambda f: f.stat().st_mtime) if cands else None


def _stt_data(path: Path) -> dict:
    import link_std
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        d = json.loads(raw)
    except ValueError:
        d = None
    if isinstance(d, dict):
        return link_std.normalize_transcript(d)
    return {"text": raw.strip(), "language": "", "words": [], "segments": []}


def run(ctx: Ctx) -> dict:
    cfg = ctx.model["command"]
    task = ctx.req.task
    argv_t = cfg["argv"]
    used = {m for a in argv_t for m in model_library.PLACEHOLDER_RX.findall(a)}
    out = ctx.tmp / f"out{OUT_EXT[task]}"
    out_dir = ctx.tmp / "out_dir"
    out_dir.mkdir(exist_ok=True)
    argv = _fill(argv_t, _values(ctx, used, out, out_dir))
    cwd = cfg.get("cwd") or None
    if cwd and not Path(cwd).is_dir():
        raise RunError(f"مجلد التشغيل مش موجود: {cwd}", "config")
    ctx.log(f"    $ {argv[0]} … ({len(argv) - 1} وسيط)")
    try:
        proc = _spawn(argv, cwd, clean_env(cfg.get("env")))
    except FileNotFoundError:
        raise RunError(f"أمر النموذج غير موجود: {argv[0]}", "model_failed") from None
    except OSError as e:
        raise RunError(f"ما قدرت أشغّل أمر النموذج ({type(e).__name__})", "model_failed") from None
    tail: collections.deque = collections.deque()
    reader = threading.Thread(target=_pump, args=(proc, ctx, tail), daemon=True)
    reader.start()
    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            if ctx.cancelled():
                raise RunError("انلغت الشغلة", "cancelled", False)
            if ctx.remaining() <= 0:
                raise RunError(f"الأمر تجاوز المهلة ({int(ctx.model['timeout_sec'])} ثانية)", "timeout")
    except BaseException:                                              # إلغاء/مهلة/إشارة: ما نخلّي أي عملية يتيمة
        _kill(proc)
        raise
    finally:
        reader.join(timeout=5)
    if proc.returncode != 0:
        msg = b"".join(tail).decode("utf-8", "replace").strip()[-300:]
        low = msg.lower()
        raise RunError(f"الموديل فشل ({proc.returncode}): {msg}", "oom" if "out of memory" in low else "model_failed")
    found = _find_output(ctx, used, out, out_dir, cfg)
    if found is None:
        raise RunError("الأمر خلص بنجاح بس ما كتب ملف ناتج — تأكد إنه بيكتب على {out} أو {out_dir}", "bad_output")
    if task == "stt":
        return {"file": None, "data": _stt_data(found)}
    return {"file": found, "data": {}}
