"""القص على إيقاع الموسيقى (اقتراح البحث 6): كشف الإيقاع، تكراره مع الموسيقى، وزيح حدود اللقطات بأمان."""

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import beats  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg غير متوفر")


def drum(path, bpm, sec=20):
    per = 60 / bpm
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"aevalsrc=0.9*sin(2*PI*60*t)*exp(-30*mod(t\\,{per}))+0.02*random(0):s=44100:d={sec}", "-ac", "1", str(path)], check=True)
    return path


@needs_ffmpeg
@pytest.mark.parametrize("bpm", [90, 120, 150])
def test_detects_tempo_and_beats_within_a_quarter_frame(tmp_path, bpm):
    r = beats.detect(drum(tmp_path / "m.wav", bpm))
    per = 60000 / bpm
    assert abs(r["bpm"] - bpm) <= 0.5
    assert all(abs(b - round(b / per) * per) <= 15 for b in r["beats_ms"])      # أقل من نص إطار (33ms)
    assert 19000 <= r["duration_ms"] <= 20100


@needs_ffmpeg
def test_silence_has_no_beats(tmp_path):
    p = tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "5", str(p)], check=True)
    assert beats.detect(p)["beats_ms"] == []


def test_beats_repeat_when_the_music_loops():
    assert beats.looped({"beats_ms": [0, 500], "duration_ms": 1000}, 2600) == [0, 500, 1000, 1500, 2000, 2500]


def tl_of(*scenes):
    return {"scenes": [{"key": f"s{i}", "shots": [{"id": f"s{i}_{k}", "start_ms": a, "end_ms": b} for k, (a, b) in enumerate(sh)]}
                       for i, sh in enumerate(scenes)]}


def test_snap_moves_inner_cuts_to_the_nearest_beat_and_never_scene_edges():
    tl = tl_of([(0, 1180), (1180, 3000)], [(3000, 4100), (4100, 6000)])
    out, moved = beats.snap_timeline(tl, list(range(0, 7000, 500)))
    s0, s1 = out["scenes"]
    assert (s0["shots"][0]["end_ms"], s0["shots"][1]["start_ms"]) == (1000, 1000)                    # 1180 ← 1000
    assert (s1["shots"][0]["end_ms"], s1["shots"][1]["start_ms"]) == (4000, 4000)                    # 4100 ← 4000
    assert s0["shots"][0]["start_ms"] == 0 and s0["shots"][-1]["end_ms"] == 3000 and s1["shots"][-1]["end_ms"] == 6000
    assert moved == 2 and tl["scenes"][0]["shots"][0]["end_ms"] == 1180                              # الأصل ما تغيّر


def test_snap_keeps_shots_long_enough_and_ignores_far_beats():
    tl = tl_of([(0, 700), (700, 3000)])
    out, moved = beats.snap_timeline(tl, [400, 2000])                                                # 400 بتخلّي اللقطة 400ms
    assert moved == 0 and out["scenes"][0]["shots"][0]["end_ms"] == 700
    out, moved = beats.snap_timeline(tl_of([(0, 1600), (1600, 3000)]), [2000])                        # أبعد من 250ms
    assert moved == 0
