"""
واجهة الرندر: render(job, workdir, renderer="remotion", **خيارات).
سجل محرّكات (dict): كل محرّك دالة fn(job, workdir, **خيارات) ← Path لملف الفيديو الناتج.
المحرّك الجاهز: "remotion" (renderers/remotion_engine.py). غيابه (Node/المتصفح) بيطلع RenderError عربي وقت التشغيل.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import constants as C
from .errors import RendererUnavailable

RENDERERS: dict[str, Callable] = {}
KNOWN = {"remotion": "Remotion", "ffmpeg": "ffmpeg"}


def register_renderer(name: str, fn: Callable) -> None:
    RENDERERS[name] = fn


def available_renderers() -> list[str]:
    return sorted(RENDERERS)


def render(job: dict, workdir, renderer: str = "remotion", **opts) -> Path:
    fn = RENDERERS.get(renderer)
    if fn is None:
        if renderer in KNOWN:
            raise RendererUnavailable(
                f"المحرّك المتقدّم غير مثبّت بعد ({KNOWN[renderer]}) — جهّزنا المهمة بس ما في رندر")
        raise RendererUnavailable(
            f"المحرّك «{renderer}» مش معروف — المتاح: {'، '.join(available_renderers()) or 'ولا محرّك'}")
    if job.get("version") != C.JOB_VERSION:
        raise RendererUnavailable("إصدار المهمة مش متوافق مع المحرّك")
    return Path(fn(job, Path(workdir), **opts))


def _register_builtin() -> None:
    from .renderers.remotion_engine import render_remotion
    register_renderer("remotion", render_remotion)


_register_builtin()
