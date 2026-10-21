"""
نسخ السيناريو: كل نسخة محفوظة بـ library/scripts/versions/<stem>/v<N>.json
مع الفرق بين النسخ لكل مشهد/حقل، وبصمة المحتوى (content_hash) اللي بتربط
المراجعة بنص السيناريو بالضبط.

ملف السيناريو الحيّ (library/scripts/<stem>.json) هو دايماً آخر نسخة، وما بيتغيّر
اسمه لما ينكتب إلو نسخة جديدة. النسخ الأقدم بتنحفظ هون قبل ما تنكتب فوقها.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import config

# حقول المشهد اللي بتعتبر «محتوى» — تعديل أي منها بعد المراجعة بيخلّي المراجعة قديمة
SCENE_FIELDS = ("duration_sec", "shot_type", "purpose", "visual", "voiceover",
                "on_screen_text", "emotion")
TOP_FIELDS = ("title", "hook_line", "cta_line")


def norm_text(value) -> str:
    return " ".join(str(value or "").split())


def _num(value) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def content_hash(script: dict) -> str:
    """sha256 لمحتوى المشاهد + الهوك + الـCTA بعد تطبيع المسافات."""
    scenes = []
    for sc in script.get("scenes") or []:
        row = {"scene_number": sc.get("scene_number")}
        for f in SCENE_FIELDS:
            row[f] = _num(sc.get(f)) if f == "duration_sec" else norm_text(sc.get(f))
        scenes.append(row)
    payload = {
        "hook_line": norm_text(script.get("hook_line")),
        "cta_line": norm_text(script.get("cta_line")),
        "scenes": scenes,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_script_id(product_code: str, number, version: int, hook=None) -> str:
    """hook: رقم الهوك (2 أو "h2") لنسخة هوك بديل: VP-kama-2-v1-h2. بدونه = السيناريو الأساسي."""
    sid = f"VP-{product_code}-{number}-v{version}"
    if hook:
        h = str(hook).lstrip("hH")
        if h.isdigit():
            sid += f"-h{int(h)}"
    return sid


def scripts_dir() -> Path:
    return Path(config.SCRIPTS_DIR)


def versions_dir(stem: str) -> Path:
    return scripts_dir() / "versions" / stem


def version_of(script: dict) -> int:
    v = (script.get("_meta") or {}).get("version")
    return v if isinstance(v, int) and v >= 1 else 1


def save_version(stem: str, script: dict) -> Path:
    """يحفظ لقطة من السيناريو كنسخة `_meta.version` (بتنكتب فوق نفس الرقم لو موجود)."""
    d = versions_dir(stem)
    d.mkdir(parents=True, exist_ok=True)
    snap = json.loads(json.dumps(script, ensure_ascii=False))
    snap.setdefault("_meta", {})["snapshot_at"] = datetime.now().isoformat(timespec="seconds")
    out = d / f"v{version_of(script)}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _load_versions(script_path: Path) -> list[dict]:
    """[{version, script, file, snapshot}] بترتيب النسخ؛ الأخيرة هي الملف الحيّ."""
    script_path = Path(script_path)
    live = json.loads(script_path.read_text(encoding="utf-8"))
    latest = version_of(live)
    out: dict[int, dict] = {}
    d = versions_dir(script_path.stem)
    if d.is_dir():
        for f in d.glob("v*.json"):
            try:
                n = int(f.stem[1:])
                snap = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                continue
            if n < latest:
                out[n] = {"version": n, "script": snap, "file": f"versions/{script_path.stem}/{f.name}"}
    out[latest] = {"version": latest, "script": live, "file": script_path.name}
    return [out[k] for k in sorted(out)]


def list_versions(script_path) -> list[dict]:
    rows = _load_versions(Path(script_path))
    result = []
    for i, r in enumerate(rows):
        meta = r["script"].get("_meta") or {}
        last = i == len(rows) - 1
        result.append({
            "version": r["version"],
            "script_id": meta.get("script_id"),
            "created_at": meta.get("rewritten_at") or meta.get("snapshot_at") or meta.get("generated_at"),
            "file": r["file"],
            "status": (meta.get("status") or "draft") if last else "superseded",
        })
    return result


def diff_scripts(a: dict, b: dict) -> list[dict]:
    """[{scene, field, before, after, similarity}] لكل حقل اختلف بين نسختين."""
    changes: list[dict] = []

    def cmp(scene, field, before, after):
        if norm_text(before) == norm_text(after):
            return
        sim = round(SequenceMatcher(None, norm_text(before), norm_text(after)).ratio(), 3)
        changes.append({"scene": scene, "field": field, "before": before, "after": after,
                        "similarity": sim})

    for f in TOP_FIELDS:
        cmp(None, f, a.get(f, ""), b.get(f, ""))

    sa = {s.get("scene_number"): s for s in a.get("scenes") or []}
    sb = {s.get("scene_number"): s for s in b.get("scenes") or []}
    for n in sorted(set(sa) | set(sb), key=lambda x: (x is None, x)):
        for f in SCENE_FIELDS:
            va = (sa.get(n) or {}).get(f, "")
            vb = (sb.get(n) or {}).get(f, "")
            if f == "duration_sec":
                if _num(va) == _num(vb):
                    continue
                changes.append({"scene": n, "field": f, "before": va, "after": vb, "similarity": 0.0})
            else:
                cmp(n, f, va, vb)
    return changes


def diffs(script_path) -> list[dict]:
    """فرق كل نسخة عن اللي قبلها."""
    rows = _load_versions(Path(script_path))
    out = []
    for prev, cur in zip(rows, rows[1:]):
        out.append({"from": prev["version"], "to": cur["version"],
                    "changes": diff_scripts(prev["script"], cur["script"])})
    return out
