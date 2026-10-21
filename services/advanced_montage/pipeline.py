"""
مسار كامل: سيناريو ← job ← رندر Remotion ← فحص ← نشر بمجلد exports.
(بيستعمله أمر `render` بالـ CLI، وبيقدر يستدعيه أي كود تاني بنفس الطريقة.)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from .adapter.build_job import build_job
from .adapter.paths import resolve_in
from .adapter.verify import verify_output
from .render import render
from .renderers.remotion_engine import ensure_ready


def publish(video: Path, job: dict, library_dir) -> Path:
    """بينقل الفيديو (بعد ما نجح الفحص) لـ library/exports/<script_id>.mp4 بشكل ذرّي."""
    lib = Path(library_dir).resolve()
    dst = resolve_in(lib, job["output"]["library_rel"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    try:
        import shutil
        shutil.copy2(video, tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return dst


def render_script(script_path, library_dir=None, products_dir=None, out_dir=None, *,
                  cancel=None, timeout_s: int | None = None, concurrency: int | None = None,
                  log: Callable[[str], None] = print) -> dict:
    """بيرجّع {"job", "video", "published", "errors"}. errors فاضية = الفيديو مطابق واننشر.
    أخطاء البيئة/الرندر بترمي RenderError (عربي)، وأخطاء الـ job بترمي JobError."""
    ensure_ready()                                                   # نفشل بدري لو Node/المتصفح ناقص
    if library_dir is None:
        import config
        library_dir = config.LIBRARY_DIR
    lib = Path(library_dir).resolve()
    job = build_job(script_path, lib, products_dir)
    out = Path(out_dir) if out_dir else lib / "exports" / f"{Path(script_path).stem}_adv"
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    t0 = time.monotonic()
    video = render(job, out / "work", renderer="remotion", library_dir=lib, cancel=cancel,
                   timeout_s=timeout_s, concurrency=concurrency, log=log)
    seconds = time.monotonic() - t0
    errors = verify_output(video, job)
    published = None
    if not errors:
        published = publish(video, job, lib)
    return {"job": job, "video": video, "published": published, "errors": errors, "seconds": seconds}
