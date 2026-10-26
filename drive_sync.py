"""
مزامنة نواتج الاستوديو مع Google Drive (فوق gdrive.py).

الطريق:
  ١. لحظة موافقة (محطة معتمدة، سيناريو معتمد، مقطع صوت معتمد، تصدير نهائي لمشروع حر) بتنادي request_ad(stem) أو request(…):
     إدخال سريع بـ library/drive.db، ما بيرمي أخطاء أبداً، وما بيعمل شي إذا درايف مش مربوط أو «التلقائي» مطفي.
     (أغلب الموافقات بتصير بعمليات خلفية — فهون بس منسجّل، والرفع بيعمله عامل واحد بالسيرفر.)
  ٢. العامل (خيط بالسيرفر، عليه قفل ملف) بيجمع قائمة الملفات من الحالة الحالية للإعلان (collect)، وبيقارن بصمة كل ملف (sha256)
     مع آخر رفع: نفس البصمة ← ما بينبعت؛ بصمة جديدة ← بيتحدّث نفس الملف بدرايف (مش نسخة تانية).
  ٣. الطابور بيعيد المحاولة (1، 5، 15، 60 دقيقة، بعدين كل 3 ساعات) وبيكمّل بعد إعادة التشغيل؛ الكبير بالقطع وبيكمّل من وين وقف.
     انقطاع الإذن أو درايف مليان ← الطابور بيوقف وبتطلع الحالة بالواجهة.

الترتيب بدرايف:
  Zakiai/<المنتج>/<VP-…>/1-نص · 2-صور · 3-صوت · 4-تحريك · 5-موسيقى · 6-نهائي   (رقم الإعلان بلا -vN: ثابت مع إعادة الكتابة)
  Zakiai/الأنماط/ · Zakiai/مكتبة الصوت/
ما منمسح شي من درايف أبداً، وبنبعت النهائي بس (الصورة المختارة لكل لقطة، المقطع المختار)، مش كل التجارب.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config
import gdrive

ROOT = "Zakiai"
SUB = {"script": "1-نص", "images": "2-صور", "voice": "3-صوت", "motion": "4-تحريك", "music": "5-موسيقى", "final": "6-نهائي"}
PATTERNS_DIR_NAME = "الأنماط"
SOUNDS_DIR_NAME = "مكتبة الصوت"
FREE_PRODUCT = "مشاريع حرة"
NO_PRODUCT = "بلا منتج"
SCRIPT_DOC = "النص والهوكات"
BACKOFF = (60, 300, 900, 3600, 10800)
MAX_ATTEMPTS = 8                      # بعدها «فشل» وبيستنى «جرّب هلق»
MAX_FILE = 2 * 1024 ** 3              # أكبر من هيك ما بينبعت (بينكتب السبب)
POLL_SEC = 30
RUN_BUDGET_SEC = 600
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska", ".m4v": "video/mp4",
        ".html": "text/html"}

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


# ── القاعدة ─────────────────────────────────────────────────────────────
def db_path() -> Path:
    return Path(config.LIBRARY_DIR) / "drive.db"


@contextmanager
def _db():
    """اتصال لكل عملية: commit بالنجاح وإغلاق دايماً (ويندوز ما بيسمح يمسح ملف مفتوح)."""
    c = _open()
    try:
        with c:
            yield c
    finally:
        c.close()


def _open() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS requests (target TEXT PRIMARY KEY, manual INTEGER NOT NULL DEFAULT 0, at TEXT);
        CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, drive_id TEXT, sha256 TEXT, size INTEGER, at TEXT);
        CREATE TABLE IF NOT EXISTS folders (path TEXT PRIMARY KEY, drive_id TEXT);
        CREATE TABLE IF NOT EXISTS outbox (key TEXT PRIMARY KEY, target TEXT, local_path TEXT, folder TEXT, name TEXT, mime TEXT,
            convert TEXT, sha256 TEXT, size INTEGER, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_at REAL NOT NULL DEFAULT 0, last_error TEXT, upload_url TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS targets (target TEXT PRIMARY KEY, folder TEXT, last_ok TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
    """)
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── التسجيل (من لحظات الموافقة) ─────────────────────────────────────────
def enabled_auto() -> bool:
    if gdrive.disabled_env():
        return False
    try:
        return gdrive.connected() and gdrive.status()["auto"]
    except Exception:                                   # noqa: BLE001
        return False


def request(target: str, manual: bool = False) -> bool:
    """بيسجّل طلب مزامنة (ad:<stem> · patterns · sounds). ما بيرمي أبداً. True إذا انسجّل."""
    try:
        if gdrive.disabled_env() or not (manual or enabled_auto()) or (manual and not gdrive.connected()):
            return False
        with _db() as c:
            c.execute("INSERT INTO requests(target, manual, at) VALUES(?,?,?) ON CONFLICT(target) DO UPDATE SET at=excluded.at",
                      (target, int(manual), _now()))
        _wake.set()
        return True
    except Exception:                                   # noqa: BLE001 — المزامنة ما بتوقف الإنتاج أبداً
        return False


def request_ad(stem: str, manual: bool = False) -> bool:
    return request(f"ad:{stem}", manual)


# ── أسماء المجلدات ──────────────────────────────────────────────────────
def clean_name(s, limit: int = 80) -> str:
    s = re.sub(r"[\\/\x00-\x1f\x7f]+", "-", str(s or "")).strip(" .-")
    return s[:limit].strip() or ""


def stable_id(script: dict, stem: str) -> str:
    """VP-kama-2-v3 ← VP-kama-2 (ثابت مع إعادة الكتابة)، ونسخة الهوك VP-kama-2-v1-h2 ← VP-kama-2-h2."""
    meta = script.get("_meta") or {}
    sid = str(meta.get("script_id") or "")
    if sid:
        return clean_name(re.sub(r"-v\d+(?=(-h\d+)?$)", "", sid))
    if meta.get("number") and (meta.get("product_code") or meta.get("product")):
        return clean_name(f"VP-{meta.get('product_code') or meta.get('product')}-{meta['number']}")
    return clean_name(stem)


def ad_folder(script: dict, stem: str) -> list[str]:
    import studio_gate
    meta = script.get("_meta") or {}
    free = studio_gate.mode_of(script) == "free"
    product = clean_name(meta.get("product")) or (FREE_PRODUCT if free else NO_PRODUCT)
    return [ROOT, product, stable_id(script, stem)]


# ── الجمع: شو بينبعت لكل إعلان ──────────────────────────────────────────
def _item(key: str, path: Path, folder: list[str], name: str, convert: str | None = None) -> dict:
    return {"key": key, "path": Path(path), "folder": folder, "name": name,
            "mime": MIME.get(Path(path).suffix.lower(), "application/octet-stream"), "convert": convert}


def _cache_file(key: str, text: str) -> Path:
    d = Path(config.LIBRARY_DIR) / "_drive_cache"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".html")
    if not p.exists() or p.read_text(encoding="utf-8") != text:
        p.write_text(text, encoding="utf-8")
    return p


def _doc(title: str, blocks: list[str]) -> str:
    style = "direction:rtl;text-align:right;font-family:Arial"
    body = "".join(blocks)
    return (f'<html dir="rtl" lang="ar"><head><meta charset="utf-8"><title>{html.escape(title)}</title></head>'
            f'<body dir="rtl" style="{style}"><h1 dir="rtl">{html.escape(title)}</h1>{body}</body></html>')


def _p(label: str, value) -> str:
    v = value if isinstance(value, str) else ("، ".join(str(x) for x in value) if isinstance(value, list) else str(value or ""))
    if not v.strip():
        return ""
    return f'<p dir="rtl"><b>{html.escape(label)}:</b> {html.escape(v)}</p>'


def script_doc_html(script: dict, stem: str) -> str:
    import script_hooks
    meta = script.get("_meta") or {}
    title = script.get("title") or meta.get("display_name") or stable_id(script, stem)
    blocks = [_p("رقم الإعلان", meta.get("script_id") or stable_id(script, stem)), _p("المنتج", meta.get("product")),
              _p("الحالة", "معتمد" if meta.get("status") == "approved" else meta.get("status"))]
    try:
        hooks = script_hooks.hooks_of(script)
        main = script_hooks.main_id(script)
    except Exception:                                   # noqa: BLE001
        hooks, main = [], ""
    if hooks:
        blocks.append('<h2 dir="rtl">الهوكات</h2>')
        for h in hooks:
            star = " ⭐ الأساسي" if h.get("id") == main else ""
            blocks.append(f'<p dir="rtl"><b>{html.escape(str(h.get("id")))}{star}:</b> {html.escape(str(h.get("spoken") or ""))}</p>')
            blocks.append(_p("نص الشاشة", h.get("on_screen_text")))
    blocks.append('<h2 dir="rtl">المشاهد</h2>')
    for sc in script.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        n = sc.get("scene_number")
        dur = sc.get("duration_sec")
        blocks.append(f'<h3 dir="rtl">مشهد {html.escape(str(n))}{f" · {dur} ث" if dur else ""}</h3>')
        for label, k in (("الهدف", "purpose"), ("الكلام", "voiceover"), ("نص الشاشة", "on_screen_text"), ("الصورة", "visual"), ("الإحساس", "emotion")):
            blocks.append(_p(label, sc.get(k)))
    blocks.append(_p("الدعوة للشراء", script.get("cta_line")))
    return _doc(str(title), blocks)


def _approved(stem: str, n: int) -> bool:
    import studio_state
    return studio_state.state_of(stem, n) == "approved"


def _scene_shots(tl: dict):
    for sc in tl.get("scenes") or []:
        for k, sh in enumerate(sc.get("shots") or [], 1):
            yield int(sc.get("n") or 0), k, sh


def collect_ad(stem: str) -> list[dict]:
    """قائمة ملفات الإعلان المعتمدة هلق (كل ناتج بس لما محطته معتمدة؛ المشروع الحر: كل الموجود)."""
    import image_studio
    import motion
    import studio_gate
    import timeline
    sp = Path(config.SCRIPTS_DIR) / f"{stem}.json"
    if not sp.exists():
        return []
    script = json.loads(sp.read_text(encoding="utf-8"))
    free = studio_gate.mode_of(script) == "free"
    folder = ad_folder(script, stem)
    kb = f"ad/{folder[1]}/{folder[2]}"
    lib = Path(config.LIBRARY_DIR)
    out: list[dict] = []

    def add(sub: str, path: Path | None, name: str, convert: str | None = None):
        if path and Path(path).is_file():
            out.append(_item(f"{kb}/{SUB[sub]}/{name}", path, folder + [SUB[sub]], name, convert))

    meta = script.get("_meta") or {}
    if free or meta.get("status") == "approved" or _approved(stem, 2):
        add("script", _cache_file(f"{kb}/script", script_doc_html(script, stem)), SCRIPT_DOC, gdrive.DOC_MIME)

    tl = timeline.load(stem) or {}
    if tl and (free or _approved(stem, 7)):
        for n, k, sh in _scene_shots(tl):
            im = sh.get("image") or {}
            rel = im.get("composite") or im.get("chosen")
            p = image_studio.abs_of(stem, rel) if rel else None
            if p:
                add("images", p, f"مشهد-{n:02d}-لقطة-{k}{p.suffix.lower()}")
    if free:
        for sc in tl.get("scenes") or []:
            rel = (sc.get("voice") or {}).get("audio")
            p = (lib / rel) if rel else None
            if p and lib.resolve() in p.resolve().parents:
                add("voice", p, f"مشهد-{int(sc.get('n') or 0):02d}{p.suffix.lower()}")
    elif _approved(stem, 4):
        import voice_studio
        man = voice_studio.load_manifest(stem) or {}
        full = (man.get("combined") or {}).get("path") or ((tl.get("voice") or {}).get("audio"))
        if full:
            add("voice", lib / full, f"الصوت-كامل{Path(full).suffix.lower()}")
        for s in man.get("scenes") or []:
            if s.get("path"):
                add("voice", lib / s["path"], f"مشهد-{int(s.get('scene') or 0):02d}{Path(s['path']).suffix.lower()}")
    if tl and (free or _approved(stem, 9)):
        for n, k, sh in _scene_shots(tl):
            clip = (sh.get("motion") or {}).get("clip")
            p = motion.abs_of(stem, clip) if clip else None
            if p:
                add("motion", p, f"مشهد-{n:02d}-لقطة-{k}{p.suffix.lower()}")
    if tl:
        import ahat
        ids = [(tl.get("ambience") or {}).get("track_id")] + [e.get("track_id") for e in tl.get("sfx") or []]
        for tid in dict.fromkeys(i for i in ids if i):
            t = ahat.get(tid)
            p = ahat.audio_path(tid) if t and t.get("approved") else None
            if p:
                add("music", p, f"{clean_name(t.get('name'), 60) or tid}{p.suffix.lower()}")
        fin = ((tl.get("render") or {}).get("final") or {}).get("file")
        if fin and (free or _approved(stem, 10)):
            add("final", lib / fin, Path(fin).name)
    return out


def collect_patterns() -> list[dict]:
    import pattern_text
    out = []
    folder = [ROOT, PATTERNS_DIR_NAME]
    for p in sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json")):
        try:
            pat = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = p.name[:-len(".pattern.json")]
        loc = pattern_text.localized(pat)
        name = clean_name(pattern_text.display_name(pat), 90) or pid
        hook, cta = loc.get("hook") or {}, loc.get("cta") or {}
        blocks = [_p("الملخص", loc.get("one_line_summary")), _p("الجمهور", loc.get("target_audience")),
                  _p("نوع الهوك", hook.get("type")), _p("آلية الهوك", hook.get("mechanism")), _p("قالب الهوك", hook.get("transferable_template")),
                  _p("المسار العاطفي", loc.get("emotional_arc")), _p("الدعوة للشراء", cta.get("type")),
                  _p("ليش بينجح", loc.get("why_it_works")), _p("نقاط الضعف", loc.get("weak_points")),
                  _p("بيناسب", loc.get("best_for")), _p("ما بيناسب", loc.get("avoid_for"))]
        bp = [s for s in (loc.get("scene_blueprint") or []) if isinstance(s, dict)]
        if bp:
            blocks.append('<h2 dir="rtl">تسلسل المشاهد</h2>')
            blocks += [_p(f"{s.get('slot')}", s.get("function")) for s in bp]
        key = f"patterns/{pid}"
        out.append(_item(key, _cache_file(key, _doc(name, blocks)), folder, f"{name} ({pid})", gdrive.DOC_MIME))
    return out


def collect_sounds() -> list[dict]:
    import ahat
    out = []
    for t in ahat.list_all():
        if not t.get("approved"):
            continue
        p = ahat.audio_path(t["id"])
        if p:
            name = f"{t['id']} - {clean_name(t.get('name'), 60)}{p.suffix.lower()}"
            out.append(_item(f"sounds/{t['id']}", p, [ROOT, SOUNDS_DIR_NAME], name))
    return out


def collect(target: str) -> list[dict]:
    if target.startswith("ad:"):
        return collect_ad(target[3:])
    if target == "patterns":
        return collect_patterns()
    if target == "sounds":
        return collect_sounds()
    return []


# ── من الطلبات للطابور ──────────────────────────────────────────────────
def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def process_requests() -> int:
    """كل طلب ← قائمة ملفات ← اللي تغيّر بصمته بيفوت الطابور. بيرجّع عدد الملفات الجديدة بالطابور."""
    added = 0
    with _db() as c:
        reqs = [r["target"] for r in c.execute("SELECT target FROM requests ORDER BY at")]
    for target in reqs:
        try:
            items = collect(target)
            err = ""
        except Exception as e:                          # noqa: BLE001
            items, err = [], f"ما قدرنا نجمع الملفات: {str(e)[:200]}"
        with _db() as c:
            c.execute("DELETE FROM requests WHERE target=?", (target,))
            folder = ""
            for it in items:
                folder = json.dumps(it["folder"][:3] if target.startswith("ad:") else it["folder"], ensure_ascii=False)
                size = it["path"].stat().st_size
                if size > MAX_FILE:
                    c.execute("INSERT OR REPLACE INTO outbox(key,target,local_path,folder,name,mime,convert,sha256,size,status,attempts,next_at,last_error,created_at)"
                              " VALUES(?,?,?,?,?,?,?,?,?,'skipped',0,0,?,?)",
                              (it["key"], target, str(it["path"]), json.dumps(it["folder"], ensure_ascii=False), it["name"], it["mime"],
                               it["convert"], "", size, "الملف أكبر من 2 غيغا — ما انبعت", _now()))
                    continue
                sha = _sha(it["path"])
                f = c.execute("SELECT sha256 FROM files WHERE key=?", (it["key"],)).fetchone()
                if f and f["sha256"] == sha:
                    c.execute("DELETE FROM outbox WHERE key=? AND status!='pending'", (it["key"],))
                    continue
                o = c.execute("SELECT sha256, status FROM outbox WHERE key=?", (it["key"],)).fetchone()
                if o and o["sha256"] == sha and o["status"] == "pending":
                    continue
                c.execute("INSERT OR REPLACE INTO outbox(key,target,local_path,folder,name,mime,convert,sha256,size,status,attempts,next_at,last_error,upload_url,created_at)"
                          " VALUES(?,?,?,?,?,?,?,?,?,'pending',0,0,NULL,NULL,?)",
                          (it["key"], target, str(it["path"]), json.dumps(it["folder"], ensure_ascii=False), it["name"], it["mime"],
                           it["convert"], sha, size, _now()))
                added += 1
            c.execute("INSERT INTO targets(target, folder, error) VALUES(?,?,?) ON CONFLICT(target) DO UPDATE SET "
                      "folder=COALESCE(NULLIF(excluded.folder,''), targets.folder), error=excluded.error", (target, folder, err))
    return added


# ── الرفع ───────────────────────────────────────────────────────────────
def ensure_folder(parts: list[str]) -> str:
    parent = None
    for i in range(len(parts)):
        path = "/".join(parts[:i + 1])
        with _db() as c:
            row = c.execute("SELECT drive_id FROM folders WHERE path=?", (path,)).fetchone()
        fid = row["drive_id"] if row else None
        if not fid:
            fid = gdrive.find_by_prop("vp_folder", path) or gdrive.create_folder(parts[i], parent, path)
            with _db() as c:
                c.execute("INSERT OR REPLACE INTO folders(path, drive_id) VALUES(?,?)", (path, fid))
        parent = fid
    return parent or ""


def _forget_folders(parts: list[str]) -> None:
    with _db() as c:
        for i in range(len(parts)):
            c.execute("DELETE FROM folders WHERE path=?", ("/".join(parts[:i + 1]),))


def _upload_row(row) -> str:
    parts = json.loads(row["folder"])
    p = Path(row["local_path"])
    with _db() as c:
        f = c.execute("SELECT drive_id FROM files WHERE key=?", (row["key"],)).fetchone()
    fid = f["drive_id"] if f else None
    if fid and not gdrive.exists(fid):                  # انمسح أو صار بالسلة (هو أو مجلده) ← ملف جديد بمكانه
        fid = None
        _forget_folders(parts)
    fid = fid or gdrive.find_by_prop("vp_key", row["key"])

    def keep_session(url):
        with _db() as c:
            c.execute("UPDATE outbox SET upload_url=? WHERE key=?", (url, row["key"]))

    for attempt in (1, 2):
        parent = ensure_folder(parts)
        try:
            return gdrive.upload(p, name=row["name"], parent=parent, key=row["key"], mime=row["mime"], convert_to=row["convert"],
                                 file_id=fid, session_url=row["upload_url"] if attempt == 1 else None, on_session=keep_session)
        except gdrive.DriveNotFound:
            if attempt == 2:
                raise
            if fid:                                     # الملف انمسح من درايف ← بنعمله من جديد
                fid = None
            else:                                       # المجلد انمسح ← بنعيد بناء المجلدات
                _forget_folders(parts)
    raise gdrive.DriveTransient("ما قدرنا نرفع الملف", "retry")


def _pause(e: gdrive.DriveError) -> None:
    gdrive.write_cfg(lambda c: c.update(paused=e.code, paused_msg=str(e)))


def process_outbox(budget_sec: float = RUN_BUDGET_SEC) -> dict:
    t0 = time.time()
    done = failed = 0
    while time.time() - t0 < budget_sec:
        with _db() as c:
            row = c.execute("SELECT * FROM outbox WHERE status='pending' AND next_at<=? ORDER BY created_at, key LIMIT 1",
                            (time.time(),)).fetchone()
        if not row:
            break
        p = Path(row["local_path"])
        if not p.is_file():
            with _db() as c:
                c.execute("DELETE FROM outbox WHERE key=?", (row["key"],))
            continue
        try:
            sha = _sha(p)
            fid = _upload_row(row)
        except gdrive.DriveFatal as e:
            if e.code == "bad_url":
                _fail(row, str(e), final=True)
                failed += 1
                continue
            _pause(e)
            return {"ok": False, "paused": e.code, "done": done}
        except gdrive.DriveTransient as e:
            _fail(row, str(e), clear_session=e.code == "session_gone")
            if e.code == "network":
                return {"ok": False, "offline": True, "done": done}
            failed += 1
            continue
        except (gdrive.DriveError, OSError) as e:
            _fail(row, str(e)[:200])
            failed += 1
            continue
        with _db() as c:
            c.execute("INSERT OR REPLACE INTO files(key, drive_id, sha256, size, at) VALUES(?,?,?,?,?)",
                      (row["key"], fid, sha, p.stat().st_size, _now()))
            c.execute("DELETE FROM outbox WHERE key=? AND sha256=?", (row["key"], row["sha256"]))
            c.execute("UPDATE outbox SET attempts=0, upload_url=NULL WHERE key=?", (row["key"],))   # انتسجّل نسخة أحدث بالنص
            c.execute("UPDATE targets SET last_ok=?, error='' WHERE target=?", (_now(), row["target"]))
        done += 1
    return {"ok": True, "done": done, "failed": failed}


def _fail(row, msg: str, clear_session: bool = False, final: bool = False) -> None:
    n = int(row["attempts"]) + 1
    gone = final or n >= MAX_ATTEMPTS
    with _db() as c:
        c.execute("UPDATE outbox SET attempts=?, next_at=?, last_error=?, status=?, upload_url=CASE WHEN ? THEN NULL ELSE upload_url END WHERE key=?",
                  (n, time.time() + BACKOFF[min(n - 1, len(BACKOFF) - 1)], msg[:300], "failed" if gone else "pending",
                   int(clear_session), row["key"]))


def tick(budget_sec: float = RUN_BUDGET_SEC) -> dict:
    """دورة وحدة: الطلبات ← الطابور ← الرفع. بلا ربط أو موقوف ← ما بيعمل شي."""
    if gdrive.disabled_env() or not gdrive.connected():
        return {"ok": True, "idle": True}
    paused = gdrive.status()["paused"]
    if paused:
        return {"ok": False, "paused": paused}
    daily_globals()
    added = process_requests()
    r = process_outbox(budget_sec)
    r["queued"] = added
    return r


# ── العامل ──────────────────────────────────────────────────────────────
def _loop() -> None:
    import oplock
    lock = Path(config.LIBRARY_DIR) / ".drive.lock"
    while not _stop.is_set():
        try:
            with oplock.file_lock(lock, stale_seconds=2 * 3600) as got:
                if got:
                    tick()
        except Exception:                               # noqa: BLE001 — العامل ما بيموت
            pass
        _wake.wait(POLL_SEC)
        _wake.clear()


def start() -> bool:
    """يشغّل العامل (idempotent). VIDPATTERN_NO_DRIVE=1 بيعطّله."""
    global _thread
    if gdrive.disabled_env() or (_thread is not None and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="vidpattern-drive", daemon=True)
    _thread.start()
    return True


def wake() -> None:
    _wake.set()


# ── للواجهة ─────────────────────────────────────────────────────────────
def _counts(c, where: str = "", args: tuple = ()) -> dict:
    q = "SELECT status, COUNT(*) n FROM outbox" + (f" WHERE {where}" if where else "") + " GROUP BY status"
    d = {r["status"]: r["n"] for r in c.execute(q, args)}
    return {"pending": d.get("pending", 0), "failed": d.get("failed", 0), "skipped": d.get("skipped", 0)}


def _link(c, path: str) -> str:
    r = c.execute("SELECT drive_id FROM folders WHERE path=?", (path,)).fetchone()
    return gdrive.folder_link(r["drive_id"]) if r and r["drive_id"] else ""


def status() -> dict:
    st = gdrive.status()
    st["paused_msg"] = str(gdrive.cfg().get("paused_msg") or "") if st["paused"] else ""
    st.update(pending=0, failed=0, skipped=0, requests=0, last_ok=None, last_error="", folder_url="")
    if not db_path().exists():
        return st
    with _db() as c:
        st.update(_counts(c))
        st["requests"] = c.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        st["last_ok"] = c.execute("SELECT MAX(at) FROM files").fetchone()[0]
        e = c.execute("SELECT last_error FROM outbox WHERE last_error IS NOT NULL AND last_error!='' ORDER BY next_at DESC LIMIT 1").fetchone()
        st["last_error"] = e[0] if e else ""
        st["folder_url"] = _link(c, ROOT)
    return st


def ad_status(stem: str) -> dict:
    target = f"ad:{stem}"
    out = {"connected": gdrive.connected(), "pending": 0, "failed": 0, "skipped": 0, "requested": False,
           "last_ok": None, "error": "", "folder_url": "", "paused": gdrive.status()["paused"]}
    if not db_path().exists():
        return out
    with _db() as c:
        out.update(_counts(c, "target=?", (target,)))
        out["requested"] = c.execute("SELECT 1 FROM requests WHERE target=?", (target,)).fetchone() is not None
        t = c.execute("SELECT folder, last_ok, error FROM targets WHERE target=?", (target,)).fetchone()
        if t:
            out["last_ok"], out["error"] = t["last_ok"], t["error"] or ""
            try:
                out["folder_url"] = _link(c, "/".join(json.loads(t["folder"] or "[]")))
            except json.JSONDecodeError:
                pass
        e = c.execute("SELECT last_error FROM outbox WHERE target=? AND last_error!='' ORDER BY next_at DESC LIMIT 1", (target,)).fetchone()
        if e and not out["error"]:
            out["error"] = e[0]
    return out


def sync_all() -> int:
    """«ابعت الإعلانات القديمة»: كل إعلان فيه شي معتمد + الأنماط + مكتبة الصوت. بيرجّع عدد الطلبات."""
    import studio_state
    n = 0
    for sp in sorted(Path(config.SCRIPTS_DIR).glob("*.json")):
        stem = sp.stem
        try:
            meta = (json.loads(sp.read_text(encoding="utf-8")).get("_meta") or {})
        except (OSError, json.JSONDecodeError):
            continue
        st = studio_state.load(stem)["stations"]
        if meta.get("mode") == "free" or meta.get("status") == "approved" or any(v.get("state") == "approved" for v in st.values()):
            n += int(request_ad(stem, manual=True))
    n += int(request("patterns", manual=True)) + int(request("sounds", manual=True))
    return n


def retry_now() -> None:
    with _db() as c:
        c.execute("UPDATE outbox SET status='pending', next_at=0, attempts=0 WHERE status='failed'")
        c.execute("UPDATE outbox SET next_at=0 WHERE status='pending'")
    gdrive.write_cfg(lambda d: [d.pop(k, None) for k in ("paused", "paused_msg")])
    _wake.set()


def daily_globals() -> bool:
    """مرة باليوم (من دورة العامل): الأنماط ومكتبة الصوت (بالبصمة — اللي ما تغيّر ما بينبعت). True إذا انطلبت هالمرة."""
    if not enabled_auto():
        return False
    today = datetime.now().date().isoformat()
    with _db() as c:
        r = c.execute("SELECT v FROM kv WHERE k='globals_day'").fetchone()
        if r and r["v"] == today:
            return False
        c.execute("INSERT OR REPLACE INTO kv(k, v) VALUES('globals_day', ?)", (today,))
    request("patterns")
    request("sounds")
    return True


def forget_all() -> None:
    """بعد الفصل: ذاكرة الملفات والمجلدات ما بتصلح لحساب تاني (الملفات نفسها بتضل بدرايف)."""
    if not db_path().exists():
        return
    with _db() as c:
        for t in ("files", "folders", "requests", "outbox", "targets", "kv"):
            c.execute(f"DELETE FROM {t}")
