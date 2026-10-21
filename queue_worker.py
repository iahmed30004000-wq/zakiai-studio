"""
طابور الطلبات من الـ OMS — سحب مش دفع.

الـ OMS ما بينادي VidPattern (الجهاز ممكن يكون مطفي ووراه جدار). بيترك الطلبات
بطابور بالسيرفر، والجهاز بيلتقطها كل ما يشتغل:

    GET  /api/vidpattern/queue?status=pending
    POST /api/vidpattern/queue/{id}/claim
    POST /api/vidpattern/queue/{id}/result   {"status":"draft","draft":{...}}
                                             {"status":"failed","reason":"..."}

كل الردود مسودات — ما في شي بينشر إعلان ولا بيصرف فلوس. تفاصيل العقد: CRM_CONTRACT_QUEUE.md

سياسة الفشل (قرار موثّق):
  • دائم (نوع غير مدعوم، منتج مش موجود، رابط غير صالح، بيانات ناقصة)
    ← POST result بحالة failed مع السبب. إعادة المحاولة ما بتفيد.
  • مؤقت (خطأ مزوّد الموديل، انقطاع الـ OMS، فشل تحميل، عطل غير متوقّع)
    ← ما في result؛ الطلب بيضل «بانتظار الجهاز» وبتنعاد المحاولة بالدورة الجاية.
    بعد QUEUE_MAX_ATTEMPTS محاولات فاشلة بيتحوّل لـ failed مع آخر سبب (عشان ما
    نحرق فلوس على طلب معطوب للأبد).
  • حد الإنفاق: مؤقت بدون عدّ محاولات، وبيوقف بقية الطلبات بالدورة (كلها رح تنمنع).
  • المسودة المحسوبة بتنحفظ محلياً قبل الإرسال؛ لو فشل الإرسال بنعيده بالدورة الجاية
    بدون ما نعيد الحساب (ما بندفع مرتين). ما بنحذف شي محلي قبل نجاح result.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import config
import oplock
import settings_io

QUEUE_PATH = "/api/vidpattern/queue"
SUPPORTED_TYPES = ("new_script", "extract_ad_features", "best_patterns")
_poll_lock = threading.Lock()


class PermanentError(Exception):
    """فشل ما بيتحسّن بإعادة المحاولة — بيتبلّغ للـ OMS كـ failed."""


class TransientError(Exception):
    """فشل مؤقت — الطلب بيضل pending."""


class SpendLimit(TransientError):
    """حد الإنفاق — مؤقت وما بينعدّ كمحاولة."""


def _max_per_poll() -> int:
    return int(getattr(config, "QUEUE_MAX_PER_POLL", 5))


def _max_attempts() -> int:
    return int(getattr(config, "QUEUE_MAX_ATTEMPTS", 3))


def _lease_seconds() -> int:
    return int(getattr(config, "QUEUE_LEASE_SECONDS", 3600))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── الحالة المحلية ───────────────────────────────────────────────────────


def _state_path() -> Path:
    return Path(config.LIBRARY_DIR) / "queue_state.json"


def _stash_dir() -> Path:
    return Path(config.LIBRARY_DIR) / "queue_results"


def _load_state() -> dict:
    try:
        s = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        s = {}
    s.setdefault("items", {})
    s.setdefault("last_poll", {})
    return s


def _save_state(s: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _safe_id(item_id: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(item_id))[:80] or "item"


def _stash_path(item_id: str) -> Path:
    return _stash_dir() / f"{_safe_id(item_id)}.json"


# ── اتصال الـ OMS ───────────────────────────────────────────────────────


def _crm():
    """(وحدة crm، None) أو (None، سبب التخطّي)."""
    try:
        import crm
    except ImportError:
        return None, "وحدة الـ OMS مش جاهزة"
    try:
        if not crm.is_configured():
            return None, "الـ OMS غير مضبوط (العنوان أو التوكن)"
    except Exception:
        return None, "الـ OMS غير مضبوط"
    return crm, None


_HTTP_CODE_RE = re.compile(r"HTTP\s*(\d{3})")


def _status_of(exc: BaseException):
    """كود HTTP من استثناء الـ OMS: خاصية status_code أو «HTTP 409» بالرسالة."""
    for attr in ("status_code", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    m = _HTTP_CODE_RE.search(str(exc))
    return int(m.group(1)) if m else None


def _req(client, method: str, path: str, **kw):
    """
    (بيانات، كود). عميل الـ OMS الحقيقي بيرمي CRMError على 4xx (كود بالرسالة) وCRMOffline على 5xx
    وانقطاع؛ منحوّل 4xx لكود عشان نميّز 409/404، والباقي بيطلع لفوق.
    """
    try:
        resp = getattr(client, method)(path, **kw)
    except Exception as e:                                       # noqa: BLE001
        code = _status_of(e)
        if code is not None and 400 <= code < 500 and type(e).__name__ != "CRMOffline":
            return None, code
        raise
    return _body(resp)


def _body(resp):
    """يقبل requests.Response أو dict/list جاهز (عميل B1 بيرجّع JSON مباشرة)."""
    if isinstance(resp, (dict, list)):
        return resp, 200
    code = getattr(resp, "status_code", 200)
    if isinstance(code, int) and code >= 400:
        return None, code
    try:
        return resp.json(), code
    except Exception:
        return {}, code


def _http_error(code: int, what: str) -> Exception:
    return TransientError(f"{what}: رد {code} من الـ OMS")


def _items_of(body) -> list[dict]:
    if isinstance(body, dict):
        body = body.get("items") or body.get("data") or body.get("queue") or []
    return [b for b in body if isinstance(b, dict) and b.get("id") is not None]


# ── المعالجات ───────────────────────────────────────────────────────────

_CODE_RE = re.compile(r"^[\w\-.؀-ۿ]+$")


def _find_product(payload: dict) -> tuple[Path, dict]:
    prods = Path(config.PRODUCTS_DIR)
    fname = str(payload.get("product_file") or "").strip()
    code = str(payload.get("product_code") or payload.get("product") or "").strip()
    if fname:
        if not _CODE_RE.match(fname) or not fname.endswith(".json"):
            raise PermanentError("اسم ملف المنتج غير صالح")
        path = prods / fname
        if path.is_file():
            return path, json.loads(path.read_text(encoding="utf-8"))
        raise PermanentError(f"المنتج '{fname}' مش موجود محلياً")
    if not code:
        raise PermanentError("الطلب ما فيه منتج (product_code أو product_file)")
    for f in sorted(prods.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        keys = {f.stem.lower(), str(data.get("product_code") or "").lower(),
                str(data.get("product_name") or "").lower()}
        if code.lower() in keys:
            return f, data
    raise PermanentError(f"المنتج '{code}' مش موجود محلياً")


def _script_draft(path: Path) -> dict:
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    meta = s.get("_meta") or {}
    return {
        "kind": "script",
        "script_file": Path(path).name,
        "script_id": meta.get("script_id"),
        "status": meta.get("status") or "draft",
        "product_code": meta.get("product_code") or meta.get("product"),
        "pattern_id": meta.get("pattern_id"),
        "title": s.get("title"),
        "hook_line": s.get("hook_line"),
        "cta_line": s.get("cta_line"),
        "total_duration_sec": s.get("total_duration_sec"),
        "scenes": [
            {k: sc.get(k) for k in ("scene_number", "duration_sec", "visual", "voiceover", "on_screen_text")}
            for sc in s.get("scenes", [])
        ],
    }


def _h_new_script(payload: dict) -> dict:
    import stage3_generate
    prod_path, _ = _find_product(payload)
    pattern_id = payload.get("pattern_id") or None
    out = stage3_generate.write_for_product(prod_path, pattern_id)
    return _script_draft(Path(out))


def _h_best_patterns(payload: dict) -> dict:
    import stage3_generate
    prod_path, prod = _find_product(payload)
    res = stage3_generate.match_for_product(prod_path) or {}
    ranked = res.get("ranked_patterns") or res.get("patterns") or []
    top = []
    for r in ranked[:3]:
        top.append({k: r.get(k) for k in (
            "pattern_id", "pattern_name", "fit_score", "reason", "required_adaptation",
            "category_distance", "transfer_justification") if k in r})
    return {"kind": "best_patterns",
            "product_code": prod.get("product_code") or prod_path.stem,
            "patterns": top, "warnings": res.get("warnings") or []}


def _check_url(url: str) -> str:
    u = urlparse(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise PermanentError("رابط الإعلان غير صالح")
    host = u.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise PermanentError("رابط محلي مرفوض")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise PermanentError("رابط لعنوان داخلي مرفوض")
    except ValueError:
        pass
    return u.geturl()


def _h_extract(payload: dict, item_id: str) -> dict:
    url = _check_url(payload.get("url") or payload.get("ad_url"))
    video_id = "crm_" + _safe_id(item_id)
    import stage1_extract
    import stage2_pattern
    try:
        extract_path = stage1_extract.process(url, video_id)
        pattern_path = stage2_pattern.mine(Path(extract_path))
    except SystemExit as e:
        raise TransientError(f"فشل الاستخراج: {e.code}") from None
    if pattern_path is None:
        return {"kind": "ad_features", "url": url, "duplicate": True,
                "note": "النمط مكرر لنمط موجود بالمكتبة"}
    pattern_path = Path(pattern_path)
    p = json.loads(pattern_path.read_text(encoding="utf-8"))
    import library_sync
    return {"kind": "ad_features", "url": url,
            "pattern": library_sync.summarize_pattern(pattern_path.name.replace(".pattern.json", ""), p)}


def _run_handler(item: dict) -> dict:
    typ, payload = item.get("type"), item.get("payload") or {}
    if not isinstance(payload, dict):
        raise PermanentError("حمولة الطلب غير صالحة")
    if typ == "new_script":
        return _h_new_script(payload)
    if typ == "best_patterns":
        return _h_best_patterns(payload)
    if typ == "extract_ad_features":
        return _h_extract(payload, str(item["id"]))
    raise PermanentError(f"نوع الطلب غير مدعوم: {typ}")


def _classify(exc: BaseException) -> Exception:
    """بيحوّل أي استثناء لدائم/مؤقت حسب السياسة الموثّقة فوق."""
    if isinstance(exc, (PermanentError, TransientError)):
        return exc
    msg = settings_io.redact(str(exc))[:300] or type(exc).__name__
    try:
        import llm
        import usage
        if isinstance(exc, usage.SpendLimitReached):
            return SpendLimit(msg)
        if isinstance(exc, llm.LLMError) and "حد الإنفاق" in msg:
            return SpendLimit(msg)
        if isinstance(exc, llm.LLMError):
            return TransientError(msg)
    except ImportError:
        pass
    return TransientError(msg)


# ── دورة واحدة ───────────────────────────────────────────────────────────


def _post(client, path: str, body: dict):
    return _req(client, "post", path, json=body)


def _report(client, item_id: str, body: dict) -> bool:
    _, code = _post(client, f"{QUEUE_PATH}/{quote(str(item_id), safe='')}/result", body)
    if isinstance(code, int) and code in (404, 409, 410):
        return True      # الطلب انحسم/انحذف من طرف تاني — ما في شي نعيده
    if isinstance(code, int) and code >= 400:
        return False
    return True


def _process(client, item: dict, state: dict) -> dict:
    item_id = str(item["id"])
    rec = state["items"].setdefault(item_id, {"type": item.get("type"), "attempts": 0})
    rec["type"] = item.get("type")

    if rec.get("status") in ("done", "failed_reported"):
        return {"id": item_id, "outcome": "skipped", "reason": "منجز محلياً"}

    stash = _stash_path(item_id)
    if stash.exists():
        body = json.loads(stash.read_text(encoding="utf-8"))
        if _report(client, item_id, body):
            rec.update(status="done", at=_now(), last_error=None)
            return {"id": item_id, "outcome": "reported", "status": body.get("status")}
        rec["last_error"] = "تعذّر إرسال المسودة المحفوظة — رح نعيد"
        return {"id": item_id, "outcome": "retry", "reason": rec["last_error"]}

    if item.get("type") not in SUPPORTED_TYPES:
        return _finish_failed(client, item_id, rec, f"نوع الطلب غير مدعوم: {item.get('type')}")

    _, code = _post(client, f"{QUEUE_PATH}/{quote(item_id, safe='')}/claim",
                    {"lease_seconds": _lease_seconds()})
    if code == 409:
        return {"id": item_id, "outcome": "skipped", "reason": "طلب ماخوذ من جهاز تاني"}
    if code in (404, 410):
        rec.update(status="done", at=_now(), last_error="الطلب انحذف من السيرفر")
        return {"id": item_id, "outcome": "skipped", "reason": "الطلب مش موجود"}
    if isinstance(code, int) and code >= 400:
        raise _http_error(code, "claim")

    rec["status"] = "claimed"
    try:
        draft = _run_handler(item)
    except BaseException as exc:                      # noqa: BLE001 — بنصنّف كل شي
        if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
            raise
        err = _classify(exc)
        msg = settings_io.redact(str(err))[:300]
        rec["last_error"] = msg
        if isinstance(err, PermanentError):
            return _finish_failed(client, item_id, rec, msg)
        if isinstance(err, SpendLimit):
            rec["status"] = "retry"
            return {"id": item_id, "outcome": "spend_limit", "reason": msg}
        rec["attempts"] = int(rec.get("attempts", 0)) + 1
        if rec["attempts"] >= _max_attempts():
            return _finish_failed(client, item_id, rec,
                                  f"فشل بعد {rec['attempts']} محاولات: {msg}")
        rec["status"] = "retry"
        return {"id": item_id, "outcome": "retry", "reason": msg, "attempts": rec["attempts"]}

    body = {"status": "draft", "draft": draft}
    _stash_dir().mkdir(parents=True, exist_ok=True)
    stash.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    if _report(client, item_id, body):
        rec.update(status="done", at=_now(), last_error=None)
        return {"id": item_id, "outcome": "drafted", "type": item.get("type")}
    rec["status"] = "computed"
    rec["last_error"] = "تعذّر إرسال المسودة — رح نعيد بدون إعادة الحساب"
    return {"id": item_id, "outcome": "retry", "reason": rec["last_error"]}


def _finish_failed(client, item_id: str, rec: dict, reason: str) -> dict:
    ok = _report(client, item_id, {"status": "failed", "reason": reason})
    if ok:
        rec.update(status="failed_reported", at=_now(), last_error=reason)
        return {"id": item_id, "outcome": "failed", "reason": reason}
    rec["last_error"] = reason
    return {"id": item_id, "outcome": "retry", "reason": "تعذّر إبلاغ الفشل للـ OMS"}


def poll_once() -> dict:
    """يلتقط الطلبات المعلّقة وينفّذها. آمن للتكرار (idempotent) وما بيرمي."""
    if not _poll_lock.acquire(blocking=False):
        return {"ok": True, "busy": True}
    try:
        with oplock.file_lock(Path(config.LIBRARY_DIR) / ".queue.lock") as got:
            if not got:
                return {"ok": True, "busy": True}
            return _poll()
    finally:
        _poll_lock.release()


def _poll() -> dict:
    state = _load_state()
    crm, reason = _crm()
    if crm is None:
        state["last_poll"] = {"at": _now(), "ok": True, "skipped": reason}
        _save_state(state)
        return {"ok": True, "skipped": reason, "processed": []}

    offline_types = tuple(t for t in (getattr(crm, "CRMOffline", None),) if t)
    processed: list[dict] = []
    try:
        client = crm.get_client()
        body, code = _req(client, "get", QUEUE_PATH, params={"status": "pending"})
        if body is None:
            raise _http_error(code, "قراءة الطابور")
        items = _items_of(body)
    except offline_types:
        state["last_poll"] = {"at": _now(), "ok": False, "offline": True,
                              "pending": state["last_poll"].get("pending", 0)}
        _save_state(state)
        return {"ok": False, "offline": True, "error": "الـ OMS مش متصل — رح نعيد لاحقاً", "processed": []}
    except Exception as e:                                     # noqa: BLE001
        msg = settings_io.redact(str(e))[:300]
        state["last_poll"] = {"at": _now(), "ok": False, "error": msg,
                              "pending": state["last_poll"].get("pending", 0)}
        _save_state(state)
        return {"ok": False, "error": msg, "processed": []}

    todo = [i for i in items if state["items"].get(str(i["id"]), {}).get("status")
            not in ("done", "failed_reported")]
    stop_all = False
    went_offline = False
    for item in todo[:_max_per_poll()]:
        if stop_all:
            break
        try:
            res = _process(client, item, state)
        except offline_types:
            processed.append({"id": str(item["id"]), "outcome": "offline"})
            went_offline = True
            break
        except Exception as e:                                 # noqa: BLE001
            res = {"id": str(item["id"]), "outcome": "retry",
                   "reason": settings_io.redact(str(e))[:200]}
        processed.append(res)
        if res.get("outcome") == "spend_limit":
            stop_all = True
        _save_state(state)

    still = [i for i in todo if state["items"].get(str(i["id"]), {}).get("status")
             not in ("done", "failed_reported")]
    state["last_poll"] = {"at": _now(), "ok": not went_offline, "fetched": len(items),
                          "pending": len(still), **({"offline": True} if went_offline else {})}
    _save_state(state)
    counts: dict[str, int] = {}
    for r in processed:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    out = {"ok": not went_offline, "fetched": len(items), "pending": len(still),
           "processed": processed, "counts": counts}
    if went_offline:
        out.update(offline=True, error="انقطع الاتصال بالـ OMS أثناء المعالجة — رح نكمّل لاحقاً")
    return out


def pending_count() -> int:
    """آخر عدد معروف للطلبات بانتظار الجهاز (من آخر دورة)."""
    return int(_load_state()["last_poll"].get("pending", 0) or 0)


def local_view(limit: int = 50) -> dict:
    s = _load_state()
    items = [
        {"id": k, "type": v.get("type"), "status": v.get("status") or "pending",
         "attempts": v.get("attempts", 0), "at": v.get("at"), "last_error": v.get("last_error")}
        for k, v in s["items"].items()
    ]
    items.sort(key=lambda r: r.get("at") or "", reverse=True)
    return {"pending_count": int(s["last_poll"].get("pending", 0) or 0),
            "last_poll": s["last_poll"], "items": items[:limit]}
