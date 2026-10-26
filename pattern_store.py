"""
كل كتابة لملفات الأنماط من الواجهة والاستيراد بتمرّ من هون:
قفل بسيط (oplock) + كتابة ذرّية + سجل تعديلات (_edits) + أرشفة بدل الحذف (library/patterns/_archive/).

قواعد:
  · معرّف النمط (اسم الملف) مفتاح أجنبي (سيناريوهات، سجل الاستعمال، حزمة الـ OMS): ما بيتغيّر ولا بينحذف أبداً.
  · القفل مش «إعادة دخول»: لا تنادي دالة بتاخد القفل وإنت ماسكه. clusters.apply() بياخده بنفسه، فنادِه بعد ما تفكّ قفلك.
  · القفل والأرشيف تحت مجلد الأنماط نفسه (config.PATTERNS_DIR) عشان الاختبارات اللي بتحوّل المجلد ما تكتب بمكتبتك الحقيقية.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config
import oplock
import pattern_fields as pf
import pattern_text as pt
import taxonomy

ID_RX = re.compile(r"^[\w؀-ۿ-]{1,80}$")
HISTORY_MAX = 100
_CLOSED = ("framework", "product_category", "dialect_or_language")
_KIND_OF = {"framework": ("framework", "framework_order"), "product_category": ("category",), "dialect_or_language": ("dialect",)}


class PatternError(Exception):
    """status: 400 بيانات، 404 مش موجود، 409 تعارض، 423 المكتبة مشغولة. detail: نص أو قائمة [{field,msg}]."""

    def __init__(self, msg: str, status: int = 400, detail=None):
        super().__init__(msg)
        self.status = status
        self.detail = detail if detail is not None else msg


def _dir(directory=None) -> Path:
    return Path(directory) if directory else Path(config.PATTERNS_DIR)


def archive_dir(directory=None) -> Path:
    return _dir(directory) / "_archive"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ═════════════════ القفل والكتابة ═════════════════
@contextmanager
def locked(timeout: float = 10.0, directory=None):
    """بيمسك قفل مجلد الأنماط (بينتظر لحد timeout ثانية). بيرمي PatternError(423) لو ضل مشغول."""
    lockfile = _dir(directory) / ".lock"
    deadline = time.time() + timeout
    while True:
        with oplock.file_lock(lockfile, stale_seconds=120) as got:
            if got:
                yield
                return
        if time.time() >= deadline:
            raise PatternError("المكتبة مشغولة بعملية تانية — جرّب بعد لحظات", 423)
        time.sleep(0.1)


def write_atomic(path: Path, data: dict) -> None:
    """كتابة لملف مؤقت ثم استبدال، فما بيضل ملف نص مكتوب. إعادة محاولة قصيرة لـ PermissionError (ويندوز)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for i in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    os.replace(tmp, path)


# ═════════════════ القراءة ═════════════════
def _check_id(pid: str) -> str:
    if not ID_RX.match(str(pid or "")):
        raise PatternError("معرّف النمط غير صالح", 400)
    return str(pid)


def _file(pid: str, directory=None) -> Path:
    return _dir(directory) / f"{_check_id(pid)}.pattern.json"


def _afile(pid: str, directory=None) -> Path:
    return archive_dir(directory) / f"{_check_id(pid)}.pattern.json"


def list_ids(directory=None) -> list[str]:
    return sorted(f.name.replace(".pattern.json", "") for f in _dir(directory).glob("*.pattern.json"))


def load(pid: str, directory=None) -> dict | None:
    f = _file(pid, directory)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def is_archived(pid: str, directory=None) -> bool:
    return not _file(pid, directory).exists() and _afile(pid, directory).exists()


def load_any(pid: str, directory=None) -> dict | None:
    """النمط من المكتبة، وإلا من الأرشيف. (السيناريوهات القديمة المبنية على نمط مؤرشف لازم تلاقيه.)"""
    try:
        f = _file(pid, directory)
    except PatternError:
        return None
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    a = _afile(pid, directory)
    return json.loads(a.read_text(encoding="utf-8")) if a.exists() else None


def list_archived(directory=None) -> list[dict]:
    out = []
    for f in sorted(archive_dir(directory).glob("*.pattern.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        last = next((e for e in reversed(p.get("_edits") or []) if e.get("action") == "archive"), {})
        out.append({"id": f.name.replace(".pattern.json", ""), "name": pt.display_name(p), "archived_at": last.get("at"), "by": last.get("by")})
    return out


def script_refs(pid: str) -> dict:
    """كم سيناريو مبني على هالنمط (وأسماء أول 5)."""
    names = []
    n = 0
    for f in sorted(Path(config.SCRIPTS_DIR).glob("*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(s, dict) and (s.get("_meta") or {}).get("pattern_id") == pid:
            n += 1
            if len(names) < 5:
                names.append((s.get("_meta") or {}).get("display_name") or f.stem)
    return {"count": n, "names": names}


# ═════════════════ المعرّفات والبناء ═════════════════
def new_id(name: str, prefix: str = "manual", directory=None) -> str:
    """معرّف جديد آمن (ما بيصطدم لا بالمكتبة ولا بالأرشيف)."""
    base = f"{prefix}_{pf.clean_slug_for_id(name)}"
    cand, n = base, 1
    while _file(cand, directory).exists() or _afile(cand, directory).exists():
        n += 1
        cand = f"{base}_{n}"
    return cand


def _blank_pattern(clean: dict, *, via: str, by: str, extra_source: dict | None = None) -> dict:
    """نمط جديد (يدوي/Excel): النص العربي هو النص الأول بالحقول العليا، والقيم المغلقة مقفولة (قرار بشري)."""
    p: dict = {}
    for spec in pf.FIELDS:
        path, kind = spec["path"], spec["type"]
        val = pf.get_path(clean, path)
        if val is None and kind == "list":
            val = []
        elif val is None and kind in ("text", "textarea"):
            val = ""
        pf.set_path(p, path, val)
    scenes = []
    for i, sc in enumerate(clean.get("scene_blueprint") or [], 1):
        row = {k: sc.get(k) for k in pt.SCENE_KEYS}
        row.update({k: sc.get(k) for k in pt.SCENE_NUM_KEYS})
        row["slot"] = i
        scenes.append(row)
    p["scene_blueprint"] = scenes
    pace = p.setdefault("pacing", {})
    total = pace.get("total_duration_sec") or round(sum((s.get("duration_sec") or 0) for s in scenes), 2) or None
    pace["total_duration_sec"] = total
    pace["scene_count"] = len(scenes)
    pace["avg_scene_sec"] = round(total / len(scenes), 2) if total and scenes else None
    p["_source"] = {"type": "authored", "via": via, "created_at": _now(), "by": by, **(extra_source or {})}
    p["_legacy"] = {}
    p["_taxonomy"] = {"version": 1, "complete": True, "locked": sorted(_CLOSED)}
    p["_edits"] = [{"at": _now(), "by": by, "action": "create", "via": via}]
    return p


def _changed_paths(before: dict, after: dict) -> list[str]:
    out = []
    for spec in pf.FIELDS:
        a, b = pf.get_path(before, spec["path"]), pf.get_path(after, spec["path"])
        if a != b:
            out.append(spec["path"])
    if before.get("scene_blueprint") != after.get("scene_blueprint"):
        out.append("scene_blueprint")
    return out


def _clip(v, n: int = 300):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"


def _record(p: dict, action: str, by: str, **extra) -> None:
    h = p.setdefault("_edits", [])
    h.append({"at": _now(), "by": by, "action": action, **extra})
    del h[:-HISTORY_MAX]


# ═════════════════ التشابه ═════════════════
def similar(fields: dict, limit: int = 3, exclude: str | None = None) -> list[dict]:
    """أقرب أنماط بالمكتبة (عربي مقابل عربي) + نفس الاسم بالضبط. تحذير بس، ما بيمنع."""
    import pattern_dedupe
    clean, _ = pf.validate(fields, "create")
    cand = _blank_pattern(clean, via="check", by="check")
    cand["_pattern_id"] = "__new__"
    lib, same = [], []
    name = (cand.get("pattern_name") or "").strip().casefold()
    for pid in list_ids():
        if pid == exclude:
            continue
        p = load(pid)
        if p is None:
            continue
        lp = pt.localized(p)
        lp["_pattern_id"] = pid
        lib.append(lp)
        if name and pt.display_name(p).strip().casefold() == name:
            same.append(pid)
    out = pattern_dedupe.find_duplicates(cand, lib, limit)
    have = {m["pattern_id"] for m in out}
    for pid in same:
        if pid not in have:
            out.insert(0, {"pattern_id": pid, "pattern_name": pt.display_name(load(pid)), "score": 1.0, "is_duplicate": True, "parts": {}})
    for m in out:
        m["same_name"] = m["pattern_id"] in same
    return out[:limit]


# ═════════════════ الكتابة ═════════════════
def view(pid: str) -> dict:
    """اللي بيحتاجه المحرّر: الحقول (عربي) + النسخة (rev) + الارتباطات."""
    p = load_any(pid)
    if p is None:
        raise PatternError("النمط غير موجود", 404)
    import review_queue
    return {"id": pid, "rev": pt.rev(p), "archived": is_archived(pid), "origin": (p.get("_source") or {}).get("type") or "mined",
            "name": pt.display_name(p), "fields": pt.editable(p), "missing_ar": len(pt.missing_ar_keys(p)),
            "refs": script_refs(pid), "open_review": review_queue.open_count(pid),
            "history": (p.get("_edits") or [])[-20:][::-1]}


def create(fields: dict, *, via: str = "manual", by: str = "owner", extra_source: dict | None = None,
           recluster: bool = True) -> str:
    """recluster=False للاستيراد الجماعي: بيستدعي recluster() مرة وحدة بالآخر بدل كل نمط."""
    clean, errs = pf.validate(fields, "create")
    if errs:
        raise PatternError("بيانات النمط فيها أخطاء", 400, errs)
    with locked():
        pid = new_id(clean.get("pattern_name") or "pattern", prefix="manual" if via == "manual" else via)
        newp = _blank_pattern(clean, via=via, by=by, extra_source=extra_source)
        write_atomic(_file(pid), newp)
    if recluster:
        _recluster()
        if pt.missing_ar_keys(newp):                      # كتبه بالإنجليزي ← بينترجم لحاله
            import pattern_i18n
            pattern_i18n.kick()
    return pid


def save_edit(pid: str, fields: dict, *, base_rev: str | None = None, by: str = "owner") -> dict:
    p0 = load(pid)
    if p0 is None:
        raise PatternError("النمط غير موجود بالمكتبة" + (" (مؤرشف — رجّعه أول)" if is_archived(pid) else ""), 404)
    existing = {**p0, "pattern_name": pt.display_name(p0)}
    clean, errs = pf.validate(fields, "edit", existing=existing)
    if errs:
        raise PatternError("بيانات النمط فيها أخطاء", 400, errs)
    import review_queue
    with locked():
        p = load(pid)
        if p is None:
            raise PatternError("النمط انحذف أثناء التعديل", 404)
        if base_rev and pt.rev(p) != base_rev:
            raise PatternError("النمط اتغيّر من حدا تاني — حدّث الصفحة وعدّل من جديد", 409)
        before = pt.editable(p)
        q = pt.merge_edit(p, clean)
        sub, dia = q.get("dialect_sub"), q.get("dialect_or_language")
        if sub and taxonomy.DIALECT_SUBS.get(sub, (None, None))[1] != dia:        # اللهجة تغيّرت والفرعية القديمة ما عادت تابعة
            q["dialect_sub"] = None
        if q.get("framework_secondary") and q["framework_secondary"] == q.get("framework"):
            q["framework_secondary"] = None
        tax = q.setdefault("_taxonomy", {"version": 1})
        # قرار بشري = قيمة مغلقة اتغيّرت فعلاً؛ المحرّر بيبعت كل الحقول، فالقيمة اللي ما انلمست ما بتنعدّ قرار
        # (وإلا أي حفظ لملخص بيسكّر بنود المراجعة المفتوحة بدون ما المالك يقرّر شي)
        decided = [k for k in _CLOSED if pf.has_path(clean, k) and pf.get_path(clean, k) != p.get(k)]
        if decided:                                                              # ما بتنعاد حسابته من _legacy
            tax["locked"] = sorted(set(tax.get("locked") or []) | set(decided))
            review_queue.close_for_pattern(pid, {kind: q.get(k) for k in decided for kind in _KIND_OF[k]}, by)
            tax["complete"] = review_queue.open_count(pid, applied=False) == 0
        after = pt.editable(q)
        changed = _changed_paths(before, after)
        if changed:
            _record(q, "edit", by, fields=changed[:30],
                    **({"before": {k: _clip(pf.get_path(before, k)) for k in changed[:5] if k != "scene_blueprint"},
                        "after": {k: _clip(pf.get_path(after, k)) for k in changed[:5] if k != "scene_blueprint"}}))
        write_atomic(_file(pid), q)
    if "framework" in decided or "scene_blueprint" in changed:
        _recluster()
    return {"id": pid, "rev": pt.rev(q), "changed": changed}


def archive(pid: str, *, by: str = "owner") -> dict:
    """يشيل النمط من المكتبة (للأرشيف). السيناريوهات المبنية عليه بتضل شغّالة (load_any)."""
    _check_id(pid)
    import review_queue
    with locked():
        f = _file(pid)
        if not f.exists():
            raise PatternError("النمط غير موجود بالمكتبة", 404)
        p = json.loads(f.read_text(encoding="utf-8"))
        refs = script_refs(pid)
        _record(p, "archive", by, scripts=refs["count"])
        write_atomic(_afile(pid), p)
        f.unlink()
    review_queue.dismiss_for_pattern(pid, "أُرشف النمط")
    _recluster()
    return {"id": pid, "refs": refs}


def restore(pid: str, *, by: str = "owner") -> dict:
    _check_id(pid)
    with locked():
        a = _afile(pid)
        if not a.exists():
            raise PatternError("النمط مش بالأرشيف", 404)
        if _file(pid).exists():
            raise PatternError("في نمط بنفس المعرّف بالمكتبة", 409)
        p = json.loads(a.read_text(encoding="utf-8"))
        _record(p, "restore", by)
        write_atomic(_file(pid), p)
        a.unlink()
    _recluster()
    return {"id": pid}


def apply_translation(pid: str, translations: dict, *, by: str = "ai") -> int:
    """يكتب ترجمة جاهزة {مفتاح مسطّح: نص عربي} على النمط (الناقص بس). بيعيد قراءة الملف تحت القفل،
    فتعديل المالك اللي صار أثناء انتظار الموديل ما بينضرب. بيرجّع عدد المفاتيح اللي انكتبت."""
    with locked():
        p = load(pid)
        if p is None:
            return 0
        q, n = pt.apply_ar(p, translations)
        if n:
            _record(q, "translate", by, keys=n)
            write_atomic(_file(pid), q)
    return n


# ═════════════════ نقل المكتبة (ملف مضغوط) ═════════════════
# تصدير الأنماط النشطة بملف واحد، واستيرادها على جهاز تاني (مثلاً من جهاز المالك للموقع على السيرفر).
# الملف بيحمل الأنماط كاملة متل ما هي (مش من حقول الفورم)، فما بيضيع شي من تشريحها.
BUNDLE_MAX_BYTES = 50 * 1024 * 1024
BUNDLE_MAX_FILES = 2000
_BUNDLE_I18N = "pattern_i18n_state.json"


def export_bundle(directory=None) -> bytes:
    """zip فيه patterns/<id>.pattern.json لكل نمط نشط (+ حالة الترجمة إذا موجودة). الأرشيف ما بيطلع."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for pid in list_ids(directory):
            z.write(_file(pid, directory), f"patterns/{pid}.pattern.json")
        i18n = _dir(directory).parent / _BUNDLE_I18N
        if i18n.exists():
            z.write(i18n, _BUNDLE_I18N)
    return buf.getvalue()


def import_bundle(data: bytes, *, by: str = "owner", directory=None) -> dict:
    """بيضيف الأنماط اللي مش موجودة (لا نشطة ولا بالأرشيف). الموجود ما بينلمس، والملف الغلط بينرفض لحاله.
    بيرجّع {added: [ids], skipped: [ids], bad: [{name, error}]}."""
    import io
    import zipfile
    if len(data) > BUNDLE_MAX_BYTES:
        raise PatternError("الملف أكبر من 50 ميغا")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PatternError("هاد مش ملف مكتبة مضغوط — صدّره من «صدّر المكتبة» بالاستوديو التاني")
    names = [n for n in z.namelist() if not n.endswith("/")]
    if len(names) > BUNDLE_MAX_FILES:
        raise PatternError("الملف فيه ملفات أكتر من اللازم")
    added, skipped, bad, i18n = [], [], [], None
    with locked(directory=directory):
        for name in names:
            base = name.rsplit("/", 1)[-1]
            if name.startswith("/") or "\\" in name or ".." in name.split("/"):
                bad.append({"name": name, "error": "مسار غير مسموح"})
                continue
            if base == _BUNDLE_I18N:
                i18n = name
                continue
            if not base.endswith(".pattern.json"):
                bad.append({"name": base, "error": "مش ملف نمط"})
                continue
            pid = base[: -len(".pattern.json")]
            if not ID_RX.match(pid):                     # اسم غريب (مسار، رموز): ما منكتبه أبداً
                bad.append({"name": base, "error": "اسم ملف غير صالح"})
                continue
            if _file(pid, directory).exists() or _afile(pid, directory).exists():
                skipped.append(pid)
                continue
            try:
                p = json.loads(z.read(name).decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                bad.append({"name": base, "error": "مش JSON صالح"})
                continue
            if not isinstance(p, dict):
                bad.append({"name": base, "error": "مش نمط"})
                continue
            _record(p, "import_bundle", by)
            write_atomic(_file(pid, directory), p)
            added.append(pid)
        # حالة الترجمة: بس إذا ما في وحدة محلية (ما منمسح تقدّم ترجمة موجود)
        target = _dir(directory).parent / _BUNDLE_I18N
        if i18n and added and not target.exists():
            try:
                write_atomic(target, json.loads(z.read(i18n).decode("utf-8-sig")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
    if added:
        _recluster()
    return {"added": added, "skipped": skipped, "bad": bad}


def _recluster() -> None:
    import clusters
    try:
        clusters.apply()
    except Exception:                                    # العناقيد تحسين، فشلها ما بيفشّل التعديل
        pass


recluster = _recluster
