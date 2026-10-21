"""
مكتبة المراجع البصرية — صورة المنتج وصورة الشخصية.

ليش لازمة: بدون مرجع ثابت، كل لقطة بتطلع بمنتج مختلف وممثلة مختلفة، والإعلان
بيصير مفكّك. المرجع بينبعت مع كل طلب توليد فبيضل الشكل ثابت عبر المشاهد.

الأولوية عند الإرسال: **الشخصية أولاً** ثم المنتج — لأن ثبات الوجه أصعب
على الموديل من ثبات العبوة، فبيحتاج الإشارة الأقوى.

الأنواع:
  product   — العبوة/المنتج (تُرفع عادةً)
  character — الممثل/الممثلة (تُرفع أو تُولَّد)
  scene_ref — أي مرجع إضافي (مكان، ستايل)
"""

from __future__ import annotations

import base64
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

ASSETS_DIR = Path(config.LIBRARY_DIR) / "assets"
INDEX_PATH = ASSETS_DIR / "assets.json"

KINDS = {
    "product": "صورة المنتج",
    "character": "الشخصية",
    "scene_ref": "مرجع إضافي",
}

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 12 * 1024 * 1024


class AssetError(Exception):
    """خطأ بالمراجع — برسالة جاهزة للعرض."""


def _resolve(stored: str) -> Path:
    """المخزَّن نسبي لمجلد الأصول. المسار المطلق القديم بيضل شغّال لحد الترحيل."""
    pth = Path(stored)
    return pth if pth.is_absolute() else ASSETS_DIR / pth


def _load() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(data: dict) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_assets(product: str | None = None, kind: str | None = None) -> list[dict]:
    out = []
    for aid, a in _load().items():
        if product and a.get("product") not in (product, None, ""):
            continue
        if kind and a.get("kind") != kind:
            continue
        out.append({"id": aid, **{k: v for k, v in a.items() if k != "path"},
                    "file": _resolve(a["path"]).name})
    return sorted(out, key=lambda a: (a.get("kind", ""), a.get("created_at", "")))


def get(asset_id: str) -> dict | None:
    a = _load().get(asset_id)
    return {"id": asset_id, **a} if a else None


def path_of(asset_id: str) -> Path | None:
    a = _load().get(asset_id)
    p = _resolve(a["path"]) if a else None
    return p if p and p.exists() else None


def add_file(src: Path, kind: str, product: str = "", label: str = "",
             notes: str = "") -> dict:
    if kind not in KINDS:
        raise AssetError(f"نوع غير معروف: {kind}")
    if src.suffix.lower() not in ALLOWED_EXT:
        raise AssetError(f"صيغة غير مدعومة: {src.suffix}")
    if src.stat().st_size > MAX_BYTES:
        raise AssetError("الصورة أكبر من 12 ميجا")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    aid = f"a_{uuid.uuid4().hex[:8]}"
    dest = ASSETS_DIR / f"{aid}{src.suffix.lower()}"
    shutil.copy(src, dest)

    data = _load()
    data[aid] = {
        "kind": kind, "product": product, "label": label or src.stem,
        "notes": notes, "path": dest.name, "source": "upload",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(data)
    return {"id": aid, **data[aid]}


def add_bytes(raw: bytes, ext: str, kind: str, product: str = "",
              label: str = "", notes: str = "", source: str = "generated") -> dict:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    aid = f"a_{uuid.uuid4().hex[:8]}"
    dest = ASSETS_DIR / f"{aid}{ext}"
    dest.write_bytes(raw)

    data = _load()
    data[aid] = {
        "kind": kind, "product": product, "label": label or aid,
        "notes": notes, "path": dest.name, "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(data)
    return {"id": aid, **data[aid]}


def update(asset_id: str, **fields) -> dict:
    data = _load()
    if asset_id not in data:
        raise AssetError("المرجع غير موجود")
    for k in ("label", "notes", "product", "kind"):
        if k in fields and fields[k] is not None:
            data[asset_id][k] = fields[k]
    _save(data)
    return {"id": asset_id, **data[asset_id]}


def delete(asset_id: str) -> None:
    data = _load()
    a = data.pop(asset_id, None)
    if a:
        _resolve(a["path"]).unlink(missing_ok=True)
        _save(data)


def as_data_url(asset_id: str) -> str | None:
    p = path_of(asset_id)
    if not p:
        return None
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp"}[p.suffix.lower().lstrip(".")]
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def refs_for(product: str, character_id: str = "", product_id: str = "") -> list[dict]:
    """
    المراجع المرتّبة حسب الأولوية: الشخصية أولاً ثم المنتج.
    لو ما انحدد شي، بياخد آخر مرجع محفوظ من كل نوع لهذا المنتج.
    """
    all_assets = list_assets(product=product)
    picked = []

    def pick(kind: str, forced: str) -> dict | None:
        if forced:
            a = get(forced)
            return a if a else None
        same = [a for a in all_assets if a["kind"] == kind]
        return get(same[-1]["id"]) if same else None

    char = pick("character", character_id)
    prod = pick("product", product_id)
    # الترتيب مقصود — الشخصية أصعب بالثبات فبتاخد الأولوية
    for a in (char, prod):
        if a:
            picked.append(a)
    return picked
