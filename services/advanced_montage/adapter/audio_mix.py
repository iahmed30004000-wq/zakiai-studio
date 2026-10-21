"""
ملف الصوت المدموج الواحد للمحرّك: صوت + آهات معتمدة بتوقيتها، خفض تلقائي (sidechain) تحت الصوت، ومعايرة loudnorm.
نفس سلسلة montage.build_command (والقيم من constants/الـ job)، لكن بتطلع wav 48k جاهز لـ <Audio> بدل ما تنحرق بفيديو.

الـ job لازم يكون بعد stage_media (كل `src` مسار نسبي لمجلد العمل).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import constants as C
from ..errors import RenderError
from .paths import resolve_in
from .text import redact_paths

MIX_NAME = "mix.wav"


def _tail(text: str, n: int = 6) -> str:
    lines = [ln.strip() for ln in redact_paths(text or "").splitlines() if ln.strip()]
    return " | ".join(lines[-n:])[-500:]


def _vol(gain_db: float) -> float:
    return round(10 ** (float(gain_db) / 20), 3)


def build_mix_command(job: dict, workdir, out: Path, ffmpeg: str = "ffmpeg") -> list[str]:
    """أمر ffmpeg كامل (قائمة وسائط). بيرمي RenderError لو الـ job مش مجهّز."""
    wd = Path(workdir)
    audio = job.get("audio") or {}
    voice = audio.get("voice") or {}
    if not voice.get("src"):
        raise RenderError("ملف الصوت مش مجهّز بمجلد العمل")
    try:
        voice_p = resolve_in(wd, voice["src"])
    except ValueError as e:
        raise RenderError(f"مسار الصوت مرفوض ({e})")
    if not voice_p.is_file():
        raise RenderError("ملف الصوت مش موجود بمجلد العمل")
    dur_ms = int(job["duration_ms"])
    dur_s = dur_ms / 1000
    tracks = list(audio.get("ahat") or [])
    duck = audio.get("duck") or {}
    ln = audio.get("loudnorm") or C.LOUDNORM
    rate = int(voice.get("rate") or C.AUDIO_RATE)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(voice_p)]
    parts: list[str] = []
    ahat_labels: list[str] = []
    for i, t in enumerate(tracks, 1):
        if not t.get("src"):
            raise RenderError("ملف الآهات مش مجهّز بمجلد العمل")
        try:
            tp = resolve_in(wd, t["src"])
        except ValueError as e:
            raise RenderError(f"مسار الآهات مرفوض ({e})")
        if not tp.is_file():
            raise RenderError("ملف الآهات مش موجود بمجلد العمل")
        cmd += ["-i", str(tp)]
        start = max(0, int(t.get("start_ms", 0)))
        length = max(0.1, (min(int(t.get("end_ms", dur_ms)), dur_ms) - start) / 1000)
        fin = float(t.get("fade_in_s", C.AHAT_FADE_IN_S))
        fout = float(t.get("fade_out_s", C.AHAT_FADE_OUT_S))
        chain = [f"aresample={rate}"]
        if t.get("loop", True):
            chain.append("aloop=loop=-1:size=2000000000")
        chain += [f"atrim=0:{length:.3f}", "asetpts=PTS-STARTPTS", f"volume={_vol(t.get('gain_db', C.DUCK_DB))}",
                  f"afade=t=in:d={fin:g}", f"afade=t=out:st={max(0.0, length - fout):.3f}:d={fout:g}"]
        if start:
            chain.append(f"adelay=delays={start}:all=1")
        lab = f"amb{i}"
        parts.append(f"[{i}:a]" + ",".join(chain) + f"[{lab}]")
        ahat_labels.append(lab)

    voice_chain = f"[0:a]aresample={rate},apad=whole_dur={dur_s:.3f}"
    if ahat_labels:
        parts.insert(0, voice_chain + ",asplit=2[vs][vm]")
        if len(ahat_labels) == 1:
            amb = ahat_labels[0]
        else:
            parts.append("".join(f"[{x}]" for x in ahat_labels)
                         + f"amix=inputs={len(ahat_labels)}:duration=longest:normalize=0[ambmix]")
            amb = "ambmix"
        parts.append(f"[{amb}][vs]sidechaincompress=threshold={duck.get('threshold', C.DUCK_THRESHOLD)}:"
                     f"ratio={duck.get('ratio', C.DUCK_RATIO)}:attack={duck.get('attack_ms', C.DUCK_ATTACK_MS)}:"
                     f"release={duck.get('release_ms', C.DUCK_RELEASE_MS)}[duck]")
        parts.append("[vm][duck]amix=inputs=2:duration=first:normalize=0[mix]")
    else:
        parts.insert(0, voice_chain + "[mix]")
    parts.append(f"[mix]loudnorm=I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']}[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[a]", "-t", f"{dur_s:.3f}",
            "-c:a", "pcm_s16le", "-ar", str(rate), str(out)]
    return cmd


def build_audio_mix(job: dict, workdir, *, ffmpeg: str = "ffmpeg", timeout: int = 600) -> Path:
    """بيبني workdir/media/mix.wav ويرجّع مساره. فشل ffmpeg/غيابه = RenderError عربي."""
    wd = Path(workdir)
    out = wd / "media" / MIX_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_mix_command(job, wd, out, ffmpeg)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        raise RenderError("ffmpeg مش مثبّت أو مش بالمسار — لازم لدمج الصوت")
    except subprocess.TimeoutExpired:
        raise RenderError("دمج الصوت أخذ وقت أكتر من اللازم وانلغى")
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 1000:
        raise RenderError("فشل دمج الصوت: " + (_tail(r.stderr) or "بدون تفاصيل"))
    return out
