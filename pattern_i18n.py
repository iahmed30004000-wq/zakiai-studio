"""
ترجمة نصوص الأنماط للعربي — تلقائية وكاملة، والمالك ما بيعمل شي.

  · بتعبّي طبقة p["ar"] الناقصة بس. الأصل الإنجليزي بالحقول العليا ما بينلمس أبداً (كشف التكرار والعناقيد معايَرة عليه).
  · النص اللي إله عربي أصلاً (أو اللي المالك عدّله) ما بينترجم ولا بينكتب فوقه.
  · بدفعات ≤ BATCH_KEYS مفتاح بنداء واحد؛ المفتاح اللي رجع فاضي أو لسا إنجليزي بنعيد عليه مرة، وإلا بيضل ناقص.
  · الكتابة كلها من pattern_store (قفل + ذرّية) وبعد ما الموديل يرد، فالموديل البطيء ما بيحجز المكتبة.

التلقائي (ensure_running):
  · بيشتغل بخيط بالخلفية جوّا السيرفر (مش بطابور المهام: الترجمة شبكة بس، وما لازم تحجز التوليد/المونتاج).
  · بيبدأ لحاله: بعد تشغيل السيرفر، وأول ما المالك يفتح مكتبة الأنماط، وبعد أي نمط جديد نصه مش عربي.
  · بعد فشل (مفتاح مرفوض/انقطاع) بينتظر RETRY_AFTER_SEC قبل ما يحاول لحاله، وزر «أعد المحاولة» بيتخطّى الانتظار.
  · نمط ما اكتملت ترجمته بعد MAX_ATTEMPTS محاولات ما بيتعاد لحاله (حماية من حرق مصاري على نص بيفشل دايماً).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import config
import llm
import oplock
import pattern_store
import pattern_text as pt

TASK = "translate"
BATCH_KEYS = 50
MAX_TOKENS = 8000
RETRY_AFTER_SEC = 600
MAX_ATTEMPTS = 3
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")

_LOCK = threading.Lock()
_STATE = {"running": False, "done": 0, "total": 0, "started_at": None}
_THREAD: threading.Thread | None = None


class TranslateError(Exception):
    """فشل متوقع بالترجمة — رسالته عربية وجاهزة للعرض."""


def pending_keys(p: dict) -> list[str]:
    """مفاتيح النص اللي لسا ما إلها عربي."""
    return pt.missing_ar_keys(p)


def _context(p: dict) -> str:
    """سطر واحد بيحلّ الكلمات الملتبسة (ما بينترجم ولا بيرجع)."""
    parts = [str(p.get("pattern_name") or ""), str(p.get("one_line_summary") or "")]
    return " — ".join(x.strip() for x in parts if x and x.strip())[:400]


def _prompt() -> str:
    return (Path(config.PROMPTS_DIR) / "pattern_translator.txt").read_text(encoding="utf-8")


def _llm_ask(system: str, user: str) -> dict:
    try:
        return llm.complete_json(TASK, system, [{"type": "text", "text": user}], MAX_TOKENS)
    except llm.LLMError as e:
        raise TranslateError(str(e)) from e


def _usable(src: str, val) -> bool:
    """ترجمة صالحة: نص غير فاضي، وعربي إلا لو الأصل ما فيه كلمات لاتينية تنترجم (أرقام، رموز، [A]…)."""
    if not isinstance(val, str) or not val.strip():
        return False
    return pt.is_arabic(val) or not _LATIN_WORD.search(src)


def _chunks(items: dict, size: int):
    keys = list(items)
    for i in range(0, len(keys), size):
        yield {k: items[k] for k in keys[i:i + size]}


def translate_texts(p: dict, ask=None) -> dict[str, str]:
    """{مفتاح مسطّح: ترجمة} للنصوص الناقصة بالنمط. ask(system, user) -> dict بيجي من الموديل (أو مزيّف بالاختبارات)."""
    flat = pt.extract_texts(p)
    if not flat:
        return {}
    ask = ask or _llm_ask
    system, ctx = _prompt(), _context(p)
    out: dict[str, str] = {}
    for _round in range(2):                                   # الدورة التانية بس للناقص أو الغلط
        todo = {k: v for k, v in flat.items() if k not in out}
        if not todo:
            break
        for chunk in _chunks(todo, BATCH_KEYS):
            res = ask(system, json.dumps({"pattern_context": ctx, "texts": chunk}, ensure_ascii=False, indent=1))
            got = res.get("translations") if isinstance(res, dict) else None
            if not isinstance(got, dict):
                continue
            for k, v in got.items():
                if k in chunk and _usable(chunk[k], v):
                    out[k] = str(v).strip()
    return out


def translate_pattern(pid: str, *, ask=None, by: str = "ai") -> dict:
    """يترجم نمط واحد من المكتبة. بيرجّع {id, keys (كم نص كان ناقص), applied (كم انكتب), pending (كم بقي)}."""
    p = pattern_store.load(pid)
    if p is None:
        raise TranslateError(f"النمط {pid} مش بالمكتبة")
    need = len(pending_keys(p))
    if not need:
        return {"id": pid, "keys": 0, "applied": 0, "pending": 0}
    got = translate_texts(p, ask)
    applied = pattern_store.apply_translation(pid, got, by=by) if got else 0
    left = pattern_store.load(pid)
    return {"id": pid, "keys": need, "applied": applied, "pending": len(pending_keys(left)) if left else 0}


def pending_patterns() -> list[tuple[str, int]]:
    """[(pattern_id, عدد النصوص الناقصة)] لكل أنماط المكتبة اللي فيها ناقص."""
    out = []
    for pid in pattern_store.list_ids():
        p = pattern_store.load(pid)
        n = len(pending_keys(p)) if p else 0
        if n:
            out.append((pid, n))
    return out


def translate_new(pid: str) -> None:
    """للأنماط الجديدة (التشريح/الاستيراد): بيترجم وما بيفشّل شي — النمط محفوظ بالإنجليزي والترجمة التلقائية بتكمّل بعدين."""
    try:
        translate_pattern(pid)
    except Exception as e:                                   # noqa: BLE001 — الترجمة تحسين، مش شرط للحفظ
        print(f"    [!] ترجمة النمط للعربي تأجّلت (بتكمّل لحالها): {e}")


# ═════════════════ الحالة المحفوظة (انتظار بعد فشل + عدّاد المحاولات) ═════════════════
def auto_enabled() -> bool:
    """الترجمة التلقائية شغّالة؟ (متغيّر VP_AUTO_TRANSLATE=0 بيطفيها، والاختبارات بتطفيها)."""
    return os.environ.get("VP_AUTO_TRANSLATE", "1") != "0" and bool(getattr(config, "AUTO_TRANSLATE_PATTERNS", True))


def _state_file() -> Path:
    return Path(config.PATTERNS_DIR).parent / "pattern_i18n_state.json"


def _lock_file() -> Path:
    return Path(config.PATTERNS_DIR).parent / ".pattern_i18n.lock"


def load_state() -> dict:
    try:
        d = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {"failed_at": d.get("failed_at"), "error": str(d.get("error") or ""), "attempts": dict(d.get("attempts") or {})}


def _save_state(d: dict) -> None:
    pattern_store.write_atomic(_state_file(), d)


def record_failure(error: str) -> None:
    d = load_state()
    d["failed_at"], d["error"] = time.time(), str(error)[:300]
    _save_state(d)


def record_success() -> None:
    d = load_state()
    d["failed_at"], d["error"] = None, ""
    _save_state(d)


def record_attempt(pid: str, complete: bool) -> int:
    """عدّاد محاولات نمط: بيصفّر لما تكتمل ترجمته، وبيزيد لما بيضل فيه ناقص."""
    d = load_state()
    if complete:
        d["attempts"].pop(pid, None)
        n = 0
    else:
        n = d["attempts"][pid] = int(d["attempts"].get(pid, 0)) + 1
    _save_state(d)
    return n


def reset_attempts() -> None:
    d = load_state()
    d["attempts"] = {}
    _save_state(d)


def retry_in() -> int:
    """ثواني الانتظار الباقية بعد آخر فشل (0 = بتقدر تحاول هلّق)."""
    t = load_state().get("failed_at")
    if not t:
        return 0
    return max(0, int(RETRY_AFTER_SEC - (time.time() - float(t))))


def stuck_ids() -> list[str]:
    """أنماط وصلت حد المحاولات وما اكتملت (الترجمة التلقائية ما بتعيدها لحالها)."""
    att = load_state()["attempts"]
    return [pid for pid, n in att.items() if n >= MAX_ATTEMPTS]


def auto_todo() -> list[tuple[str, int]]:
    """الناقص اللي الترجمة التلقائية بتحاوله: بدون الأنماط اللي وصلت حد المحاولات."""
    stuck = set(stuck_ids())
    return [(pid, n) for pid, n in pending_patterns() if pid not in stuck]


# ═════════════════ التلقائي ═════════════════
def status() -> dict:
    """للواجهة: {patterns, pending_patterns, pending_keys, running, done, total, auto, error, retry_in, stuck}."""
    pend = pending_patterns()
    st = load_state()
    with _LOCK:
        live = dict(_STATE)
    stuck = [pid for pid in stuck_ids() if any(pid == p for p, _ in pend)]
    return {"patterns": len(pattern_store.list_ids()), "pending_patterns": len(pend), "pending_keys": sum(n for _, n in pend),
            "running": live["running"], "done": live["done"], "total": live["total"], "auto": auto_enabled(),
            "error": st["error"], "retry_in": retry_in(), "stuck": len(stuck)}


def ensure_running(*, force: bool = False, limit: int | None = None) -> dict:
    """
    يشغّل الترجمة بالخلفية إذا في ناقص ومش شغّالة. force (زر «أعد المحاولة»): بيتخطّى الانتظار بعد الفشل وحد المحاولات.
    بيرجّع status() + started (هل بدأ هلّق).
    """
    global _THREAD
    started = False
    if force or auto_enabled():
        if force:
            reset_attempts()
        todo = pending_patterns() if force else auto_todo()
        with _LOCK:
            if todo and not _STATE["running"] and (force or retry_in() == 0):
                _STATE.update(running=True, done=0, total=min(len(todo), limit) if limit else len(todo), started_at=time.time())
                _THREAD = threading.Thread(target=_worker, args=(limit,), name="pattern-i18n", daemon=True)
                _THREAD.start()
                started = True
    return {**status(), "started": started}


def kick() -> None:
    """بعد نمط جديد: ابدأ لو في ناقص (ما بيرمي ولا بينتظر)."""
    try:
        ensure_running()
    except Exception:                                        # noqa: BLE001
        pass


def schedule_startup(delay: float = 15.0) -> None:
    """بعد تشغيل السيرفر بلحظات: كمّل أي ناقص (بخيط تأجيل ما بيبطّئ الإقلاع)."""
    if not auto_enabled():
        return
    t = threading.Timer(delay, kick)
    t.daemon = True
    t.start()


def _worker(limit) -> None:
    import translate_patterns
    err, res = "", None
    try:
        with oplock.file_lock(_lock_file(), stale_seconds=3600) as got:
            if not got:                                      # عملية تانية (سكربت) عم تترجم: ما منزاحمها
                return

            def progress(done: int, total: int) -> None:
                with _LOCK:
                    _STATE.update(done=done, total=total)

            res = translate_patterns.run(limit=limit, on_progress=progress, auto=True)
        if res["failed"] and not res["done"]:
            err = res["failed"][0]["error"]
    except Exception as e:                                   # noqa: BLE001 — الخيط ما بيموت بصمت
        err = str(e) or type(e).__name__
    finally:
        try:
            if err:
                record_failure(err)
            elif res is not None:
                record_success()
        finally:
            with _LOCK:
                _STATE["running"] = False


def wait(timeout: float = 30.0) -> bool:
    """للاختبارات: ينتظر انتهاء الخيط. True إذا خلص."""
    t = _THREAD
    if t is not None:
        t.join(timeout)
        return not t.is_alive()
    return True
