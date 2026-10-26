"""
القص على إيقاع الموسيقى (اقتراح البحث 6) — للمشروع الحر بس.

كاشف إيقاع خفيف بالأرقام (numpy + ffmpeg)، بلا نماذج ولا تنزيل، فبيشتغل على الجهاز وعلى السيرفر:
  1. ffmpeg بيفك الموسيقى لصوت مونو 11025Hz.
  2. «قوة البدايات»: زيادة الطاقة بكل نافذة صغيرة (spectral flux).
  3. السرعة (BPM) من الارتباط الذاتي لقوة البدايات (بين 70 و180).
  4. الطور: الإزاحة اللي بتجمع أقوى بدايات على شبكة الضربات.

بعدها snap_timeline بيزيح حدود اللقطات جوّا كل مشهد لأقرب ضربة (±SNAP_MS)، بلا ما يلمس حدود المشاهد
(فالصوت والترجمة بيضلّوا متزامنين)، وبلا ما تصير لقطة أقصر من MIN_SHOT_MS.
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import numpy as np

SR = 11025
HOP = 256                       # ~23ms
WIN = 1024
BPM_RANGE = (70.0, 180.0)
SNAP_MS = 250                   # أبعد زيحة مسموحة لحد اللقطة
MIN_SHOT_MS = 500


def _decode(path: Path, max_sec: float = 180.0) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-t", f"{max_sec:.0f}", "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


def _onset_envelope(x: np.ndarray) -> np.ndarray:
    if len(x) < WIN * 4:
        return np.zeros(0)
    n = 1 + (len(x) - WIN) // HOP
    frames = np.lib.stride_tricks.as_strided(x, shape=(n, WIN), strides=(x.strides[0] * HOP, x.strides[0]))
    mag = np.abs(np.fft.rfft(frames * np.hanning(WIN), axis=1))
    mag = np.log1p(100 * mag)
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")          # نشيل الخلفية البطيئة
    return np.maximum(flux, 0.0)


def detect(path: Path) -> dict:
    """{"bpm": float, "beats_ms": [..]} — قائمة فاضية لو الموسيقى قصيرة أو بلا إيقاع واضح."""
    x = _decode(Path(path))
    env = _onset_envelope(x)
    dur_ms = int(len(x) / SR * 1000)
    if env.size < 32 or not env.any():
        return {"bpm": 0.0, "beats_ms": [], "duration_ms": dur_ms}
    fps = SR / HOP
    ac = np.correlate(env, env, mode="full")[env.size - 1:]
    lo, hi = int(fps * 60 / BPM_RANGE[1]), int(fps * 60 / BPM_RANGE[0])
    hi = min(hi, ac.size - 1)
    if hi <= lo:
        return {"bpm": 0.0, "beats_ms": []}
    rough = lo + int(np.argmax(ac[lo:hi + 1]))
    # تدقيق: الفترة بكسور (مش بس أرقام صحيحة) والطور معها، بأعلى مجموع لقوة البدايات على شبكة الضربات
    best = (-1.0, float(rough), 0.0)
    for period in np.arange(rough - 1.0, rough + 1.0001, 0.02):
        for phase in np.arange(0.0, period, 0.5):
            idx = np.round(np.arange(phase, env.size - 1, period)).astype(int)
            score = float(env[idx].sum()) / max(1, idx.size)
            if score > best[0]:
                best = (score, float(period), float(phase))
    _, period, phase = best
    # النافذة بتشوف الضربة من أول ما تدخلها، فالوقت المحسوب من بدايتها بيطلع بكّير بـ (WIN-HOP) عيّنة (~70ms)
    beats = (np.arange(phase, env.size, period) * HOP + (WIN - HOP)) / SR * 1000
    return {"bpm": round(60 * fps / period, 1), "beats_ms": [int(round(b)) for b in beats if b < dur_ms], "duration_ms": dur_ms}


def looped(info: dict, total_ms: int) -> list[int]:
    """الموسيقى بتتكرر لو أقصر من الفيديو: نفس الضربات بتنعاد بعد كل لفّة."""
    b, d = info.get("beats_ms") or [], int(info.get("duration_ms") or 0)
    if not b or d <= 0:
        return b
    out, k = [], 0
    while k * d < total_ms:
        out += [x + k * d for x in b if x + k * d <= total_ms]
        k += 1
    return out


def _nearest(beats: list[int], t: int) -> int | None:
    i = int(np.searchsorted(beats, t))
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(beats) and (best is None or abs(beats[j] - t) < abs(best - t)):
            best = beats[j]
    return best if best is not None and abs(best - t) <= SNAP_MS else None


def snap_timeline(tl: dict, beats_ms: list[int]) -> tuple[dict, int]:
    """نسخة من الخط الزمني بحدود اللقطات الداخلية على الضربات. بيرجّع (النسخة، عدد الحدود اللي انزاحت).
    حدود المشاهد ما بتنلمس، وما في لقطة بتصير أقصر من MIN_SHOT_MS."""
    out = copy.deepcopy(tl)
    if not beats_ms:
        return out, 0
    moved = 0
    for sc in out.get("scenes") or []:
        shots = sc.get("shots") or []
        for k in range(len(shots) - 1):
            a, b = shots[k], shots[k + 1]
            cut = int(a["end_ms"])
            t = _nearest(beats_ms, cut)
            if t is None or t == cut:
                continue
            if t - int(a["start_ms"]) < MIN_SHOT_MS or int(b["end_ms"]) - t < MIN_SHOT_MS:
                continue
            a["end_ms"] = b["start_ms"] = t
            moved += 1
    return out, moved
