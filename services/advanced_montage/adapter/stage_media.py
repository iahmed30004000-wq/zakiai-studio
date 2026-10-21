"""
تجهيز مجلد عمل مؤقت للمحرّك: كل ملف مطلوب بيتنسخ (أو بيتربط) باسم ASCII آمن تحت workdir/media/.
أي مسار خارج مجلد المكتبة (path traversal) أو بصيغة مطلقة = StageError، وما بنلمس القرص قبل ما نتأكد.
"""

from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

from .. import constants as C
from ..errors import StageError
from .paths import resolve_in

_ALLOWED = {"video": C.VIDEO_EXT, "image": C.IMAGE_EXT, "audio": C.AUDIO_EXT}


def _plan(job: dict) -> list[tuple[dict, str, str]]:
    """[(الكائن اللي بنكتب فيه src, الصنف, الاسم المقترح)] بالترتيب."""
    items = []
    for c in job.get("cuts", []):
        s = c["source"]
        items.append((s, s.get("kind"), f"cut_{c['index']:03d}"))
    v = (job.get("audio") or {}).get("voice")
    if v:
        items.append((v, "audio", "voice"))
    for i, a in enumerate((job.get("audio") or {}).get("ahat") or [], 1):
        items.append((a, "audio", f"ahat_{i:02d}"))
    return items


def _link_or_copy(src: Path, dst: Path, mode: str) -> None:
    if dst.exists():
        dst.unlink()
    if mode == "auto":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def stage_media(job: dict, library_dir, workdir, mode: str = "auto") -> dict:
    """بيرجّع نسخة من الـ job فيها كل `src` مسار نسبي لـ workdir (مثل «media/cut_001.mp4»)."""
    if mode not in ("auto", "copy"):
        raise StageError("وضع التجهيز: auto أو copy")
    lib = Path(library_dir).resolve()
    out = copy.deepcopy(job)

    # 1) تحقق من كل المسارات قبل ما نكتب أي شي
    resolved: list[tuple[dict, Path, str]] = []
    for obj, kind, base in _plan(out):
        rel = obj.get("library_path")
        try:
            p = resolve_in(lib, rel)
        except ValueError as e:
            raise StageError(f"مسار مرفوض ({e}): {str(rel)[:60]}")
        if kind not in _ALLOWED:
            raise StageError(f"نوع وسائط غير معروف: {kind}")
        ext = p.suffix.lower()
        if ext not in _ALLOWED[kind]:
            raise StageError(f"صيغة ملف غير مسموحة: {ext or 'بدون امتداد'}")
        if not p.is_file():
            raise StageError(f"الملف مش موجود بالمكتبة: {rel}")
        resolved.append((obj, p, base))
    out_rel = (job.get("output") or {}).get("library_rel")
    try:
        resolve_in(lib, out_rel)
    except ValueError as e:
        raise StageError(f"مسار الإخراج مرفوض ({e})")
    if not str(out_rel).startswith("exports/"):
        raise StageError("الإخراج لازم يكون تحت exports/")

    # 2) مجلد العمل
    wd = Path(workdir)
    if wd.exists() and not wd.is_dir():
        raise StageError("مجلد العمل موجود كملف")
    media = wd / "media"
    media.mkdir(parents=True, exist_ok=True)

    # 3) النسخ/الربط بأسماء ثابتة (نفس الملف مستعمل أكتر من مرة = نسخة وحدة)
    done: dict[Path, str] = {}
    for obj, p, base in resolved:
        if p not in done:
            name = f"{base}{p.suffix.lower()}"
            _link_or_copy(p, media / name, mode)
            done[p] = f"media/{name}"
        obj["src"] = done[p]
    return out
