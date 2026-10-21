"""فحص ملفات الوسائط بـ ffprobe. لو ffprobe مش موجود أو الملف تالف بيرجّع {}."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe(path) -> dict:
    p = Path(path)
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)],
                           capture_output=True, text=True, check=True, timeout=60)
        d = json.loads(r.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        num, den = (v.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    def ms(x):
        try:
            return round(float(x) * 1000)
        except (TypeError, ValueError):
            return None

    fmt_ms = ms((d.get("format") or {}).get("duration")) or 0
    return {
        "width": v.get("width"), "height": v.get("height"), "fps": fps,
        "has_video": bool(v), "has_audio": bool(a),
        "video_duration_ms": ms(v.get("duration")) if v.get("duration") not in (None, "N/A") else fmt_ms,
        "duration_ms": fmt_ms,
        "size_bytes": p.stat().st_size if p.exists() else 0,
    }
