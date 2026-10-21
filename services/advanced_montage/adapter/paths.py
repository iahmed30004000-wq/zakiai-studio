"""مسارات آمنة: كل ملف لازم يكون جوّا مجلد المكتبة، بمسار نسبي بدون «..» ولا قرص ولا شرطة عكسية."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def clean_rel(rel) -> str:
    """بيتأكد إنو المسار النسبي مقبول شكلاً (قبل ما نلمس القرص). بيرجّع مسار بصيغة posix."""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError("مسار فاضي")
    if "\\" in rel or ":" in rel or "\x00" in rel:
        raise ValueError("المسار فيه شرطة عكسية أو قرص أو رمز ممنوع")
    p = PurePosixPath(rel)
    if p.is_absolute() or rel.startswith(("/", "~")):
        raise ValueError("المسار مطلق")
    if any(part in ("..", "") for part in rel.split("/")) or ".." in p.parts:
        raise ValueError("المسار فيه «..»")
    return p.as_posix()


def resolve_in(base: Path, rel) -> Path:
    """بيحلّ المسار النسبي تحت `base` ويتأكد إنه فعلاً جوّاه (حتى بعد اتباع الروابط الرمزية)."""
    rel = clean_rel(rel)
    root = Path(base).resolve()
    p = (root / rel).resolve()
    if root != p and root not in p.parents:
        raise ValueError("المسار بيطلع خارج المكتبة")
    return p
