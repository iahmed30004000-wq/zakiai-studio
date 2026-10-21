"""
جسر إضافة المتصفح (المحطة ٧ — المسار الثاني).

الإضافة (extension/) بتشتغل على موقع جيميناي أو شات جي بي تي بحساب المالك المسجّل بنفسه، بتبويب واحد
ولقطة بالمرة. هالوحدة هي طرف الاستوديو: طابور اللقطات، استقبال الصور، سجل الخطوات، وأوامر التحكم.

  · الإضافة بتبدأ الاتصال (سحب/رفع من المتصفح لـ localhost) — الاستوديو ما بينادي الإضافة.
  · توكن اقتران محلي بمخزن الأسرار (رأس X-VP-Ext-Token) لنقاط الإضافة.
  · ما بنخزّن كلمات سر ولا بنسجّل دخول. أي تحقق/كابتشا/تحذير/طلب دخول ← وقوف كامل + حفظ المكان + تنبيه.
    الاستوديو ما بيحاول يتجاوز أي حماية، والإضافة كمان.
  · مسار الإضافة بيخالف عادةً شروط استخدام المواقع وبيعرّض الحساب للإيقاف — التحذير ظاهر بالواجهة.
"""

from __future__ import annotations

import hmac
import io
import json
import re
import secrets
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import config
import ext_config
import studio_state
import timeline

MODES = {"natural": "طبيعي", "fast": "أسرع", "max": "أقصى"}
COMMANDS = ("idle", "run", "pause", "stop")
MODE_WARNINGS = {
    "natural": "",
    "fast": "الوضع الأسرع بيرفع احتمال إن الموقع يلاحظ الأتمتة ويوقف الحساب.",
    "max": "الوضع الأقصى بأقل انتظار بيرفع احتمال الكشف والإيقاف كتير. استخدمه على مسؤوليتك.",
}
# المواقع والأنواع المعرّفة بالعقد (المصدر الأصلي بـ ext_config)
SITES = ext_config.SITES
KINDS = ext_config.KINDS
STEP_MODES = ("all", "one_by_one")
REVIEW_REASON = "راجع النتيجة ثم كمّل"
UNSET = object()                                              # «ما انبعتت» مقابل null الصريحة
MAX_ONLY = 500
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_LOG_LINES = 2000


class ExtError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── التوكن ──────────────────────────────────────────────────────────────
def _secrets():
    import secrets_store
    return secrets_store


def token() -> str:
    """توكن الاقتران: بيتولّد مرة وبينحفظ بمخزن الأسرار (مش بأي ملف)."""
    s = _secrets()
    t = s.get_secret("studio_ext_token")
    if not t:
        t = secrets.token_urlsafe(24)
        s.set_secret("studio_ext_token", t)
    return t


def rotate_token() -> str:
    t = secrets.token_urlsafe(24)
    _secrets().set_secret("studio_ext_token", t)
    return t


def verify(presented: str | None) -> bool:
    if not presented:
        return False
    try:
        return hmac.compare_digest(str(presented), token())
    except Exception:
        return False


# ── الحالة والتحكم ──────────────────────────────────────────────────────
def _dir(stem: str) -> Path:
    return Path(config.LIBRARY_DIR) / "studio" / stem


def _control_path(stem: str) -> Path:
    return _dir(stem) / "ext_control.json"


def control(stem: str) -> dict:
    p = _control_path(stem)
    base = {"command": "idle", "mode": "natural", "site": "gemini", "kind": "image", "step_mode": "all", "only": None,
            "updated_at": None, "stop_reason": None, "stop_code": None, "position": None}
    if p.exists():
        try:
            base.update(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return base


def _write_control(stem: str, c: dict) -> dict:
    p = _control_path(stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    c["updated_at"] = _now()
    p.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    return c


def _clean_only(only):
    """only: قائمة task_id أو None (قائمة فاضية = None)."""
    if only is None:
        return None
    if (not isinstance(only, list) or len(only) > MAX_ONLY
            or not all(isinstance(x, str) and 0 < len(x.strip()) <= 40 for x in only)):
        raise ExtError("only: قائمة معرّفات مهام (أو null لكل المهام)")
    out = list(dict.fromkeys(x.strip() for x in only))
    return out or None


def set_control(stem: str, command: str | None = None, mode: str | None = None, site: str | None = None,
                kind: str | None = None, step_mode: str | None = None, only=UNSET) -> dict:
    c = control(stem)
    if mode is not None:
        if mode not in MODES:
            raise ExtError("الوضع: natural أو fast أو max")
        c["mode"] = mode
    if site is not None:
        if site not in SITES:
            raise ExtError("الموقع: " + " أو ".join(SITES))
        c["site"] = site
    if kind is not None:
        if kind not in KINDS:
            raise ExtError("النوع: " + " أو ".join(KINDS))
        c["kind"] = kind
    if step_mode is not None:
        if step_mode not in STEP_MODES:
            raise ExtError("نمط الخطوات: all (الكل مرة وحدة) أو one_by_one (لقطة لقطة مع مراجعة)")
        c["step_mode"] = step_mode
    if only is not UNSET:
        c["only"] = _clean_only(only)
    if command is not None:
        if command not in COMMANDS:
            raise ExtError("الأمر: idle أو run أو pause أو stop")
        if command == "run" and c.get("stop_code") and c["command"] == "stop":
            pass                                              # الاستئناف بعد وقوف = المالك ضغط «كمّل» بنفسه
        c["command"] = command
        if command == "run" or (command == "idle" and c.get("stop_code") == "review"):
            c["stop_reason"], c["stop_code"] = None, None
    c["warning"] = MODE_WARNINGS.get(c["mode"], "")
    return _write_control(stem, c)


def review_pause(stem: str) -> dict | None:
    """وضع «لقطة لقطة مع مراجعة»: بعد كل نتيجة ناجحة الأمر بيصير pause (مش stop) والمالك بيكمّل بنفسه."""
    c = control(stem)
    if c.get("step_mode") != "one_by_one" or c.get("command") == "stop":
        return None
    c.update(command="pause", stop_code="review", stop_reason=REVIEW_REASON, position=None)
    append_log(stem, {"step": "review", "level": "info", "msg": REVIEW_REASON})
    return _write_control(stem, c)


def record_stop(stem: str, code: str, reason: str, position: dict | None) -> dict:
    """الإضافة وقفت: بنحفظ السبب والمكان، وبنعلّم الأمر «stop» — ما في استئناف تلقائي أبداً."""
    c = control(stem)
    c.update(command="stop", stop_code=str(code)[:60], stop_reason=str(reason)[:300], position=position)
    append_log(stem, {"step": "stop", "level": "warn", "msg": f"{code}: {reason}", "shot": (position or {}).get("shot_id")})
    return _write_control(stem, c)


# ── السجل ───────────────────────────────────────────────────────────────
def _log_path(stem: str) -> Path:
    return _dir(stem) / "ext_log.jsonl"


def append_log(stem: str, entry: dict) -> None:
    p = _log_path(stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now(), "step": str(entry.get("step", ""))[:40], "level": str(entry.get("level", "info"))[:10],
           "shot": str(entry.get("shot") or "")[:20], "msg": str(entry.get("msg", ""))[:300]}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) > MAX_LOG_LINES:
        p.write_text("\n".join(lines[-MAX_LOG_LINES:]) + "\n", encoding="utf-8")


def tail(stem: str, n: int = 40) -> list[dict]:
    p = _log_path(stem)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ── الطابور ─────────────────────────────────────────────────────────────
def _refs(stem: str, sh: dict, code: str):
    import image_studio
    return image_studio.refs_for_shot(stem, sh, code)


def build_queue(script_path, n: int | None = None) -> list[dict]:
    """اللقطات اللي ناقصها خيارات (٢ افتراضياً)، بالترتيب، مع مراجعها."""
    import image_studio
    path = Path(script_path)
    stem = path.stem
    tl = timeline.load(stem)
    if not tl:
        raise ExtError("ما في خط زمني")
    if studio_state.state_of(stem, 6) != "approved":
        raise ExtError("اعتمد برومبتات اللقطات (محطة 6) قبل الصور")
    script = json.loads(path.read_text(encoding="utf-8"))
    code = image_studio.product_code(script)
    n = n or int(getattr(config, "STUDIO_IMAGE_CANDIDATES", 2))
    out = []
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if sh.get("inherited"):                      # نسخة هوك: اللقطة جاية بصورتها من الفيديو الأساسي
                continue
            have = len((sh.get("image") or {}).get("candidates", []))
            prompt = (sh.get("prompt_model") or sh.get("prompt_ar") or "").strip()
            if have >= n or not prompt:
                continue
            refs = _refs(stem, sh, code)
            out.append({"shot_id": sh["id"], "scene": sc["n"], "type": sh["type"], "prompt": prompt, "want": n - have,
                        "refs": [{"index": i, "name": r.name} for i, r in enumerate(refs)]})
    return out


def ref_path(script_path, shot_id: str, index: int) -> Path:
    import image_studio
    path = Path(script_path)
    stem = path.stem
    tl = timeline.load(stem)
    script = json.loads(path.read_text(encoding="utf-8"))
    _sc, sh = image_studio._shot(tl, shot_id)
    refs = _refs(stem, sh, image_studio.product_code(script))
    if not 0 <= index < len(refs):
        raise ExtError("مرجع غير موجود")
    return refs[index]


# ── استقبال الصور ───────────────────────────────────────────────────────
def add_candidate(script_path, shot_id: str, data: bytes, site: str) -> dict:
    """صورة رجعت من الإضافة ← مرشّح لللقطة (path_used = extension). بنتحقق إنها صورة فعلاً."""
    import image_studio
    from PIL import Image
    if site not in SITES:
        raise ExtError("موقع غير معروف")
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ExtError("الصورة فاضية أو كبيرة كتير")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ExtError("الملف مش صورة صالحة")
    if min(im.size) < 256:
        raise ExtError(f"الصورة صغيرة ({im.size[0]}×{im.size[1]}) — غالباً مصغّرة مش النتيجة الكاملة")
    path = Path(script_path)
    stem = path.stem
    try:
        tl = image_studio._load(stem)
        image_studio._shot(tl, shot_id)
    except image_studio.ImageStudioError as e:
        raise ExtError(str(e))
    out = image_studio.img_dir(stem) / f"{shot_id}_{int(time.time() * 1000)}_ext.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out, "PNG")
    tl = image_studio._load(stem)
    _sc, sh = image_studio._shot(tl, shot_id)
    image_studio._image(sh)["candidates"].append({
        "path": image_studio._rel(stem, out), "provider": f"extension:{site}", "model": "web", "at": _now(),
        "w": im.size[0], "h": im.size[1], "refs_used": [], "path_used": "extension"})
    image_studio._save(stem, tl)
    if studio_state.state_of(stem, 7) != "running":
        try:
            studio_state.set_state(stem, 7, "running", "الإضافة بتولّد الصور")
        except studio_state.StationBlocked as e:
            raise ExtError(str(e))
    append_log(stem, {"step": "result", "shot": shot_id, "msg": f"وصلت صورة {im.size[0]}×{im.size[1]} من {site}"})
    return {"shot": shot_id, "candidates": len(sh["image"]["candidates"]), "size": list(im.size)}


def finish_if_done(script_path) -> bool:
    """لو ما بقي شي بالطابور ← المحطة ٧ بتنتظر اختيار المالك."""
    stem = Path(script_path).stem
    if not build_queue(script_path):
        studio_state.set_state(stem, 7, "awaiting_choice", "خلص الطابور — اختر صورة لكل لقطة")
        set_control(stem, "idle")
        return True
    return False


def status(script_path) -> dict:
    import ext_tasks
    stem = Path(script_path).stem
    c = control(stem)
    try:
        q = build_queue(script_path)
    except ExtError as e:
        q, c["blocked"] = [], str(e)
    counts, blocked = ext_tasks.counts(script_path)
    return {"control": c, "queue": len(q), "next": (q[0]["shot_id"] if q else None), "log": tail(stem, 25),
            "modes": MODES, "mode_warning": MODE_WARNINGS.get(c["mode"], ""),
            "kinds": counts, "blocked_kinds": blocked, "requests": ext_tasks.list_requests(stem),
            "sites": ext_config.sites_summary()}


# ── ملف الإضافة للتنزيل والإصدار ────────────────────────────────────────
ZIP_SKIP_DIRS = {"__pycache__", "node_modules", ".git"}
ZIP_SKIP_SUFFIX = {".zip", ".pyc", ".log", ".map", ".bak", ".tmp", ".swp"}


def extension_dir() -> Path:
    return Path(__file__).resolve().parent / "extension"


def extension_version() -> str:
    try:
        v = json.loads((extension_dir() / "manifest.json").read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError):
        v = None
    if not v:
        raise ExtError("ملف الإضافة (manifest.json) ناقص")
    return str(v)


def _zip_skip(rel: Path) -> bool:
    """ملفات مؤقتة أو اختبار أو مخفية ما بتنحط بالزيب (المؤقتة بتبدأ بـ tmp من ملفات الاختبار)."""
    if any(part in ZIP_SKIP_DIRS or part.startswith(".") for part in rel.parts):
        return True
    n = rel.name.lower()
    return n.startswith("tmp") or n.startswith("test") or ".test." in n or rel.suffix.lower() in ZIP_SKIP_SUFFIX


def build_zip() -> tuple[str, bytes]:
    """زيب مجلد extension/ بالذاكرة. آمن: ما بيدخل إلا ملفات حقيقية جوّا المجلد (بدون روابط رمزية أو خروج منه)."""
    root = extension_dir().resolve()
    if not root.is_dir():
        raise ExtError("مجلد الإضافة غير موجود")
    ver = re.sub(r"[^0-9A-Za-z._-]", "", extension_version()) or "0"
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_symlink() or not f.is_file():
                continue
            real = f.resolve()
            if root not in real.parents:
                continue
            rel = real.relative_to(root)
            if _zip_skip(rel):
                continue
            z.write(real, rel.as_posix())
            n += 1
    if not n:
        raise ExtError("مجلد الإضافة فاضي")
    return f"zakiai-extension-{ver}.zip", buf.getvalue()
