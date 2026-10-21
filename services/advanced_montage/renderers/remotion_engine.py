"""
محرّك Remotion: بيجهّز مجلد عمل (الوسائط + الصوت المدموج + props.json + الخطوط) وبيشغّل Remotion CLI بالمتصفح الموجود
على الجهاز (بلا تنزيل Chromium) ويكتب فيديو mp4 واحد.

قواعد الأمان:
  · بلا shell=True، وكل مسار بيتمرّق كوسيط مستقل (مش دمج نصوص). Remotion بيتشغّل بـ node مباشرة على ملف CLI المحلي
    (نفس اللي بيعمله `npx remotion` بس بدون cmd.exe وبدون أي احتمال لتنزيل شي من الشبكة).
  · أي مسار بيظهر برسالة خطأ بيتشال منه المجلدات (يضل اسم الملف بس).
  · مهلة كلية + إلغاء نظيف (بنقتل شجرة العمليات كلها: node + المتصفح).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import constants as C
from ..adapter.audio_mix import MIX_NAME, build_audio_mix
from ..adapter.paths import resolve_in
from ..adapter.stage_media import stage_media
from ..adapter.text import redact_paths, scan_job_for_leaks
from ..errors import RenderError, StageError

REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"
FONTS_SRC = REMOTION_DIR / "fonts"
ENTRY = "src/index.ts"
COMPOSITION = "AdVertical"
CLI_REL = Path("node_modules") / "@remotion" / "cli" / "remotion-cli.js"
EXPECTED_REMOTION = "4.0.530"
MIN_NODE_MAJOR = 18

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")


class RenderFailed(RenderError):
    """المحرّك وقع بخطأ (مش مهلة ولا إلغاء) — بنعيد المحاولة مرة وحدة بتوازي أقل."""


# ───────────────────────── فحص البيئة ─────────────────────────
@dataclass
class Check:
    key: str
    ok: bool
    detail: str


def find_node() -> str | None:
    return shutil.which("node")


def find_npm() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _run_version(exe: str, *args: str) -> str | None:
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or "").strip()
    return out.splitlines()[0] if r.returncode == 0 and out else None


def node_version(node: str) -> tuple[int, ...] | None:
    v = _run_version(node, "--version")
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def browser_candidates() -> list[Path]:
    env = os.environ
    cands: list[Path] = []
    if env.get("VP_CHROME"):
        cands.append(Path(env["VP_CHROME"]))
    for base in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("LOCALAPPDATA")):
        if base:
            cands.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    cands += [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
              Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable"),
              Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser"),
              Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    return cands


def find_browser() -> Path | None:
    """VP_CHROME أول (لو محدد لازم يكون موجود)، وبعدين المسارات المعروفة. بنرفض التنزيل التلقائي كلياً."""
    custom = os.environ.get("VP_CHROME")
    if custom:
        p = Path(custom)
        return p if p.is_file() else None
    for p in browser_candidates():
        if p.is_file():
            return p
    return None


def cli_entry() -> Path:
    return REMOTION_DIR / CLI_REL


def project_ready() -> tuple[bool, str]:
    if not (REMOTION_DIR / "package.json").is_file() or not (REMOTION_DIR / ENTRY).is_file():
        return False, "ملفات مشروع Remotion ناقصة"
    if not cli_entry().is_file():
        return False, "حزم Remotion مش منزّلة — شغّل «npm ci» من مجلد services/advanced_montage/remotion"
    try:
        v = json.loads((REMOTION_DIR / "node_modules" / "remotion" / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return False, "حزمة remotion مش منزّلة — شغّل «npm ci» من مجلد services/advanced_montage/remotion"
    return True, v


def doctor_checks() -> list[Check]:
    checks: list[Check] = []
    node = find_node()
    if not node:
        checks.append(Check("node", False, "Node.js مش مثبّت (لازم الإصدار 18 أو أحدث) — نزّله من nodejs.org"))
    else:
        ver = node_version(node)
        if not ver:
            checks.append(Check("node", False, "Node.js موجود بس ما قدرنا نقرأ إصداره"))
        elif ver[0] < MIN_NODE_MAJOR:
            checks.append(Check("node", False, f"إصدار Node.js قديم ({'.'.join(map(str, ver))}) — لازم {MIN_NODE_MAJOR} أو أحدث"))
        else:
            checks.append(Check("node", True, f"Node.js {'.'.join(map(str, ver))}"))
    npm = find_npm()
    nv = _run_version(npm, "--version") if npm else None
    checks.append(Check("npm", bool(nv), f"npm {nv}" if nv else "npm مش موجود (بييجي مع Node.js)"))
    ok, info = project_ready()
    if ok:
        note = "" if info == EXPECTED_REMOTION else f" (المتوقع {EXPECTED_REMOTION})"
        checks.append(Check("remotion", info == EXPECTED_REMOTION, f"مشروع Remotion جاهز — الإصدار {info}{note}"))
    else:
        checks.append(Check("remotion", False, info))
    fonts_ok = all((FONTS_SRC / f"ibm-plex-sans-arabic-{w}-{s}.woff2").is_file()
                   for w in (400, 500, 600, 700) for s in ("arabic", "latin"))
    checks.append(Check("fonts", fonts_ok, "الخطوط العربية (IBM Plex Sans Arabic) موجودة" if fonts_ok
                        else "ملفات الخطوط ناقصة بمجلد remotion/fonts"))
    br = find_browser()
    if br:
        checks.append(Check("browser", True, f"المتصفح موجود: {br.name}"))
    elif os.environ.get("VP_CHROME"):
        checks.append(Check("browser", False, "المتغيّر VP_CHROME بيشير لملف مش موجود"))
    else:
        checks.append(Check("browser", False, "ما لقينا Google Chrome — ثبّته أو حط مساره بالمتغيّر VP_CHROME"))
    checks.append(Check("ffmpeg", bool(find_ffmpeg()), "ffmpeg موجود" if find_ffmpeg() else "ffmpeg مش مثبّت (لازم لدمج الصوت)"))
    checks.append(Check("ffprobe", bool(shutil.which("ffprobe")), "ffprobe موجود" if shutil.which("ffprobe")
                        else "ffprobe مش مثبّت (لازم لفحص الفيديو الناتج)"))
    return checks


def ensure_ready() -> tuple[str, Path]:
    """بيرجّع (node, browser) أو بيرمي RenderError برسالة عربية بسيطة عن أول شي ناقص."""
    node = find_node()
    if not node:
        raise RenderError("Node.js مش مثبّت — لازم الإصدار 18 أو أحدث (nodejs.org). جرّب الأمر doctor للتفاصيل")
    ver = node_version(node)
    if ver and ver[0] < MIN_NODE_MAJOR:
        raise RenderError(f"إصدار Node.js قديم — لازم {MIN_NODE_MAJOR} أو أحدث")
    ok, info = project_ready()
    if not ok:
        raise RenderError(info)
    br = find_browser()
    if not br:
        raise RenderError("المتصفح (Google Chrome) مش موجود — ثبّته أو حط مساره بالمتغيّر VP_CHROME. "
                          "ما بننزّل متصفح لحالنا")
    if not find_ffmpeg():
        raise RenderError("ffmpeg مش مثبّت — لازم لدمج الصوت")
    return node, br


# ───────────────────────── الأمر وتشغيله ─────────────────────────
def default_concurrency() -> int:
    return max(1, min(8, (os.cpu_count() or 2) // 2))


def default_timeout_s(total_frames: int) -> int:
    return max(900, int(total_frames) * 4)


def build_command(node: str, subcommand: str, out: Path, props: Path, public_dir: Path, browser: Path, *,
                  concurrency: int, delay_timeout_ms: int = 120_000, crf: int = 18, frame: int | None = None) -> list[str]:
    """قائمة وسائط (بلا shell). subcommand: render أو still."""
    cmd = [node, str(cli_entry()), subcommand, ENTRY, COMPOSITION, str(out),
           f"--props={props}", f"--public-dir={public_dir}", f"--browser-executable={browser}",
           "--chrome-mode=chrome-for-testing", f"--timeout={delay_timeout_ms}", "--log=info", "--overwrite"]
    if subcommand == "render":
        cmd += ["--codec=h264", f"--crf={crf}", "--pixel-format=yuv420p", f"--concurrency={concurrency}",
                "--image-format=jpeg", "--jpeg-quality=95", "--audio-codec=aac", "--audio-bitrate=192k",
                "--enforce-audio-track"]
    else:
        cmd += ["--image-format=png", f"--frame={0 if frame is None else int(frame)}"]
    return cmd


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=20)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _clean_line(s: str) -> str:
    return redact_paths(_ANSI.sub("", s)).strip()[:180]


def _key_lines(tail: list[str]) -> list[str]:
    """أهم أسطر الخطأ: أول أسطر فيها «error» (بدون ضجيج Chrome وأسطر التتبّع) + آخر سطرين."""
    keys = []
    for x in tail:
        low = x.lower()
        if "error" in low and not low.startswith(("chrome", "at ")) and "update_service" not in low and x not in keys:
            keys.append(x)
    out = keys[:3]
    for x in tail[-2:]:
        if x and x not in out and not x.startswith("at "):
            out.append(x)
    return out or [x for x in tail if x][-3:]


def _explain_failure(code: int, tail: list[str]) -> str:
    blob = "\n".join(tail).lower()
    if "browser" in blob and ("not found" in blob or "could not find" in blob or "executable" in blob):
        why = "المتصفح ما اشتغل — تأكد من مسار Chrome (المتغيّر VP_CHROME)"
    elif "cannot find module" in blob or "enoent" in blob:
        why = "ملفات Remotion ناقصة — شغّل «npm ci» من مجلد المشروع"
    elif "timeout" in blob or "delayrender" in blob:
        why = "الصفحة أخذت وقت أكتر من المسموح (غالباً مقطع ثقيل أو خط ما انحمّل)"
    elif "out of memory" in blob or "heap" in blob:
        why = "الذاكرة خلصت — جرّب تقلل التوازي أو سكّر برامج تانية"
    else:
        why = "المحرّك وقف بخطأ"
    last = " | ".join(_key_lines(tail))[-420:]
    return f"فشل الرندر (رمز {code}): {why}" + (f". آخر الأسطر: {last}" if last else "")


def run_remotion(cmd: list[str], *, cwd: Path, timeout_s: int, cancel: Callable[[], bool] | threading.Event | None,
                 log: Callable[[str], None], out_file: Path | None, log_path: Path | None = None) -> None:
    """بيشغّل الأمر ويراقبه. المهلة والإلغاء بيقتلوا شجرة العمليات. فشل = RenderError."""
    is_cancelled = (cancel.is_set if isinstance(cancel, threading.Event) else cancel) if cancel else (lambda: False)
    tail: deque[str] = deque(maxlen=80)
    env = dict(os.environ, NO_COLOR="1", FORCE_COLOR="0", CI="1")
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env, stdin=subprocess.DEVNULL, **kw)
    except FileNotFoundError:
        raise RenderError("Node.js مش موجود أو انحذف")
    except OSError as e:
        raise RenderError(f"ما قدرنا نشغّل المحرّك ({type(e).__name__})")

    state = {"last_pct": -10}

    def pump() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = _clean_line(raw)
            if not line:
                continue
            tail.append(line)
            if logf and not line.startswith(("Rendered ", "Encoded ")):
                logf.write(line + chr(10))
                logf.flush()
            m = _PROGRESS.search(line)
            if m and "render" in line.lower():
                done, total = int(m.group(1)), int(m.group(2))
                pct = int(100 * done / total) if total else 0
                if pct >= state["last_pct"] + 10 or done == total:
                    state["last_pct"] = pct
                    log(f"[…] الرندر {pct}% ({done}/{total} إطار)")

    logf = None
    if log_path:
        try:
            logf = open(log_path, "w", encoding="utf-8")
        except OSError:
            logf = None
    th = threading.Thread(target=pump, daemon=True)
    th.start()
    t0 = time.monotonic()
    try:
        while True:
            try:
                proc.wait(timeout=0.4)
                break
            except subprocess.TimeoutExpired:
                pass
            if is_cancelled():
                _kill_tree(proc)
                proc.wait(timeout=20)
                _drop(out_file)
                raise RenderError("انلغى الرندر بطلبك")
            if time.monotonic() - t0 > timeout_s:
                _kill_tree(proc)
                proc.wait(timeout=20)
                _drop(out_file)
                raise RenderError(f"الرندر أخذ أكتر من {timeout_s // 60} دقيقة (المهلة) وانوقف — جرّب فيديو أقصر أو قلّل التوازي")
    except BaseException:
        if proc.poll() is None:
            _kill_tree(proc)
        raise
    finally:
        th.join(timeout=5)
        if logf:
            logf.close()
    if proc.returncode != 0:
        _drop(out_file)
        raise RenderFailed(_explain_failure(proc.returncode, list(tail)))


def _drop(p: Path | None) -> None:
    try:
        if p and p.exists():
            p.unlink()
    except OSError:
        pass


# ───────────────────────── تجهيز مجلد العمل ─────────────────────────
def _needs_staging(job: dict, workdir: Path) -> bool:
    srcs = [c["source"].get("src") for c in job.get("cuts", [])]
    srcs.append(((job.get("audio") or {}).get("voice") or {}).get("src"))
    if not all(srcs):
        return True
    try:
        return not all(resolve_in(workdir, s).is_file() for s in srcs)
    except ValueError:
        return True


def copy_fonts(workdir: Path) -> None:
    dst = workdir / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    files = sorted(FONTS_SRC.glob("*.woff2")) if FONTS_SRC.is_dir() else []
    if not files:
        raise RenderError("ملفات الخطوط ناقصة بمجلد remotion/fonts")
    for f in files:
        d = dst / f.name
        if not d.exists() or d.stat().st_size != f.stat().st_size:
            shutil.copy2(f, d)


def normalize_clips(job: dict, workdir, *, ffmpeg: str = "ffmpeg", workers: int = 4) -> None:
    """بيعيد ترميز مقاطع الفيديو بمجلد العمل لشكل ثابت يحبّه Remotion (1080x1920، 30 إطار ثابت، بلا B-frames،
    مفتاح كل 15 إطار، ومدّ آخر إطار لو المقطع أقصر من اللقطة). بيمنع أخطاء «No frame found» وبيسرّع القفز بالفيديو.
    الملفات المربوطة (hardlink) من المكتبة بتنستبدل باسمها بنسخة جديدة — ملف المكتبة الأصلي ما بينلمس."""
    from concurrent.futures import ThreadPoolExecutor
    wd = Path(workdir)
    need: dict[str, int] = {}
    for c in job.get("cuts", []):
        s = c["source"]
        if s.get("kind") == "video" and s.get("src"):
            need[s["src"]] = max(need.get(s["src"], 0), int(c["duration_ms"]))

    def one(item: tuple[str, int]) -> None:
        src, dur_ms = item
        target = resolve_in(wd, src)
        tmp = target.with_name(target.stem + "_norm.mp4")
        secs = dur_ms / 1000 + 0.15
        vf = (f"scale={C.WIDTH}:{C.HEIGHT}:force_original_aspect_ratio=increase,crop={C.WIDTH}:{C.HEIGHT},setsar=1,"
              f"fps={C.FPS},tpad=stop_mode=clone:stop_duration=3,format=yuv420p")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(target), "-an", "-vf", vf, "-t", f"{secs:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-g", "15", "-bf", "0", "-movflags", "+faststart", str(tmp)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        except FileNotFoundError:
            raise RenderError("ffmpeg مش مثبّت — لازم لتجهيز المقاطع")
        except subprocess.TimeoutExpired:
            raise RenderError("تجهيز مقطع أخذ وقت أكتر من اللازم وانلغى")
        if r.returncode != 0 or not tmp.is_file():
            lines = [x for x in redact_paths(r.stderr or "").splitlines() if x.strip()]
            raise RenderError("فشل تجهيز مقطع فيديو: " + (" | ".join(lines[-3:])[:300] or "بدون تفاصيل"))
        os.replace(tmp, target)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one, need.items()))


def prepare_workdir(job: dict, workdir, library_dir=None, *, ffmpeg: str = "ffmpeg") -> tuple[dict, Path]:
    """(staged_job, props_path). بيجهّز: الوسائط + الصوت المدموج + الخطوط + props.json."""
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    staged = job
    if _needs_staging(job, wd):
        if library_dir is None:
            raise RenderError("ملفات الوسائط مش مجهّزة ومجلد المكتبة ما انعطى")
        try:
            staged = stage_media(job, library_dir, wd)
        except StageError as e:
            raise RenderError(f"تجهيز الملفات فشل: {e}")
    else:
        import copy
        staged = copy.deepcopy(job)
    normalize_clips(staged, wd, ffmpeg=ffmpeg)
    build_audio_mix(staged, wd, ffmpeg=ffmpeg)
    staged["audio"]["mixed"] = {"src": f"media/{MIX_NAME}", "duration_ms": staged["duration_ms"], "rate": C.AUDIO_RATE}
    copy_fonts(wd)
    leaks = scan_job_for_leaks(staged)
    if leaks:
        raise RenderError("المهمة فيها بيانات ممنوعة: " + "؛ ".join(leaks[:3]))
    props = wd / "props.json"
    props.write_text(json.dumps(staged, ensure_ascii=False, indent=1), encoding="utf-8")
    return staged, props


# ───────────────────────── الواجهة العامة ─────────────────────────
def render_remotion(job: dict, workdir, *, library_dir=None, output=None, cancel=None, timeout_s: int | None = None,
                    concurrency: int | None = None, crf: int = 18, log: Callable[[str], None] = print) -> Path:
    """job ← mp4. بيرجّع مسار الفيديو (workdir/out/<script_id>.mp4 ما لم ينعطى output)."""
    node, browser = ensure_ready()
    wd = Path(workdir).resolve()
    staged, props = prepare_workdir(job, wd, library_dir)
    out = Path(output).resolve() if output else wd / "out" / f"{staged['script_id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    _drop(out)
    cmd = build_command(node, "render", out, props, wd, browser, concurrency=concurrency or default_concurrency(), crf=crf)
    total = int(staged["total_frames"])
    log(f"[…] رندر Remotion: {total} إطار ({staged['duration_ms'] / 1000:.1f} ثانية)، توازي {concurrency or default_concurrency()}")
    tmo = timeout_s or default_timeout_s(total)
    try:
        run_remotion(cmd, cwd=REMOTION_DIR, timeout_s=tmo, cancel=cancel, log=log, out_file=out, log_path=wd / "render.log")
    except RenderFailed as first:
        # أعطال متقطّعة نادرة بقراءة الفيديو أثناء التوازي العالي: محاولة ثانية بتوازي أقل
        slower = max(1, (concurrency or default_concurrency()) // 2)
        log(f"[!] المحاولة الأولى وقفت — بنعيد مرة بتوازي {slower}")
        cmd = build_command(node, "render", out, props, wd, browser, concurrency=slower, crf=crf)
        try:
            run_remotion(cmd, cwd=REMOTION_DIR, timeout_s=tmo, cancel=cancel, log=log, out_file=out,
                         log_path=wd / "render.log")
        except RenderFailed as second:
            raise RenderError(str(second) + " (بعد محاولتين)") from first
    if not out.is_file() or out.stat().st_size < 1000:
        raise RenderError("الرندر خلص بس ما طلع ملف فيديو")
    return out


def render_still(job: dict, workdir, frame: int, output, *, library_dir=None, timeout_s: int = 600,
                 cancel=None, log: Callable[[str], None] = print) -> Path:
    """لقطة PNG لإطار واحد (للفحص البصري)."""
    node, browser = ensure_ready()
    wd = Path(workdir).resolve()
    _, props = prepare_workdir(job, wd, library_dir)
    out = Path(output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    _drop(out)
    cmd = build_command(node, "still", out, props, wd, browser, concurrency=1, frame=frame)
    run_remotion(cmd, cwd=REMOTION_DIR, timeout_s=timeout_s, cancel=cancel, log=log, out_file=out,
                 log_path=wd / "render.log")
    if not out.is_file():
        raise RenderError("ما طلعت اللقطة")
    return out
