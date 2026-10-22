"""
ربط «سيرفر بواجهة OpenAI» (std): أي سيرفر بيحكي نفس شكل OpenAI للصور والصوت والتفريغ.

    POST {url}/images/generations   (صور من وصف، b64)         POST {url}/images/edits   (تعديل بصور مرجعية)
    POST {url}/audio/speech         (نص لصوت)                  POST {url}/audio/transcriptions (verbose_json بتوقيت الكلمات)
    GET  {url}/models               (فحص + قائمة الموديلات)

قواعد ثابتة:
  · الرابط بيمرّ على net_allow (http فقط، 127.x أو اسم docker، منفذ صريح، مسار /v1 بس) وكل نداء بيتلحم عبر net_allow.join.
  · بلا بروكسي من البيئة (trust_env=False)، وبلا تحويلات أبداً، وبسقوف حجم للرد.
  · التوكن بيجي من مخزن الأسرار باسم token_secret وبيروح بترويسة Authorization بس — ما بيتسجّل ولا بيظهر بأي رسالة.
  · رابط صورة بالرد (data[0].url) ما بنحمّله إلا من نفس المضيف والمنفذ.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import net_allow
from model_run import Ctx, RunError

CONNECT_TIMEOUT = 10
MAX_JSON_BYTES = 64 * 1024 * 1024                      # رد صورة base64 ممكن يكون كبير
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_AUDIO_BYTES = 200 * 1024 * 1024
MAX_MODELS = 2000
MAX_DETAIL_BYTES = 64 * 1024                           # رد خطأ: ما بنقرا أكتر من هيك
BODY_MAX_SEC = 300.0                                   # جسم رد واحد: لو طوّل أكتر من هيك بنقطعه (سيرفر بيقطّر البيانات)
_DETAIL_RX = re.compile(r"\s+")


def _token(model: dict) -> str | None:
    name = (model.get("std") or {}).get("token_secret")
    if not name:
        return None
    try:
        import secrets_store
        return secrets_store.get_secret(name) or None
    except Exception:                                  # noqa: BLE001 — مخزن غير متاح: منكمّل بلا توكن والسيرفر بيقرر
        return None


def session(token: str | None = None):
    import requests
    s = requests.Session()
    s.trust_env = False                                # ما نمرّر النداء عبر أي بروكسي من البيئة
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def _detail(resp) -> str:
    try:
        raw = b""
        for chunk in resp.iter_content(8192):          # بسقف: رد خطأ ضخم ما بيتحمّل كله بالذاكرة
            raw += chunk
            if len(raw) >= MAX_DETAIL_BYTES:
                break
        d = json.loads(raw.decode("utf-8", "replace"))
    except Exception:                                  # noqa: BLE001
        return f"رد {resp.status_code}"
    err = d.get("error") if isinstance(d, dict) else None
    msg = (err.get("message") if isinstance(err, dict) else err) or (d.get("detail") if isinstance(d, dict) else None)
    if isinstance(msg, (list, dict)):
        msg = json.dumps(msg, ensure_ascii=False)
    return _DETAIL_RX.sub(" ", str(msg or f"رد {resp.status_code}"))[:200]


def call(sess, method: str, url: str, ctx: Ctx | None = None, *, read_timeout: float | None = None, stream: bool = True, **kw):
    """نداء واحد: كل فشل بيتحوّل لـ RunError بسبب واضح. بلا تحويلات."""
    import requests
    if ctx is not None:
        ctx.check()
    budget = read_timeout if read_timeout is not None else (ctx.remaining() if ctx else 30)
    try:
        r = sess.request(method, url, timeout=(CONNECT_TIMEOUT, max(1.0, budget)), allow_redirects=False, stream=stream, **kw)
    except requests.exceptions.ConnectTimeout:
        raise RunError("السيرفر ما ردّ بوقت الاتصال", "connection") from None
    except requests.exceptions.ReadTimeout:
        raise RunError("السيرفر تأخر بالرد أكتر من المهلة", "timeout") from None
    except requests.exceptions.RequestException:
        raise RunError("ما قدرت أتصل بالسيرفر — واقف أو الرابط غلط", "connection") from None
    code = r.status_code
    if 300 <= code < 400:
        r.close()
        raise RunError("السيرفر حاول يحوّلنا لعنوان ثاني — التحويلات ممنوعة", "connection")
    if code in (401, 403):
        r.close()
        raise RunError("السيرفر رفض التوكن (غلط أو ناقص) — راجع توكن النموذج", "auth")
    if code == 404:
        r.close()
        raise RunError("السيرفر ما عنده هالمسار — تأكد إنه بواجهة OpenAI وإن الرابط بينتهي بـ /v1", "missing")
    if code == 429:
        r.close()
        raise RunError("السيرفر مشغول (طلبات كتير)", "busy")
    if code >= 400:
        msg = _detail(r)
        r.close()
        low = msg.lower()
        raise RunError(f"السيرفر رفض الطلب: {msg}", "oom" if "out of memory" in low or "cuda" in low and "memory" in low else ("rejected" if code < 500 else "model_failed"))
    return r


def _body(resp, cap: int) -> bytes:
    """جسم الرد بسقف حجم ووقت (بيقطع الاتصال لو تجاوز)."""
    chunks, got, t_end = [], 0, time.monotonic() + BODY_MAX_SEC
    try:
        for chunk in resp.iter_content(1 << 16):
            got += len(chunk)
            if got > cap:
                raise RunError("رد السيرفر أكبر من الحد المسموح", "bad_output")
            if time.monotonic() > t_end:
                raise RunError("رد السيرفر طوّل كتير (بيجي بالقطّارة)", "timeout")
            chunks.append(chunk)
    except RunError:
        raise
    except Exception:                                  # noqa: BLE001
        raise RunError("انقطع تنزيل الرد من السيرفر", "connection") from None
    finally:
        resp.close()
    return b"".join(chunks)


def _json(resp, cap: int = MAX_JSON_BYTES) -> dict:
    raw = _body(resp, cap)
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise RunError("رد السيرفر مش JSON مفهوم", "bad_output") from None
    if not isinstance(d, dict):
        raise RunError("رد السيرفر مش بالشكل المتوقع", "bad_output")
    return d


def _base(model: dict) -> str:
    try:
        return net_allow.validate((model.get("std") or {}).get("url"), subject="رابط الواجهة القياسية", example="http://127.0.0.1:8000/v1", allow_path=True)
    except net_allow.NetAllowError as e:
        raise RunError(str(e), "config") from None


def _url(base: str, path: str) -> str:
    try:
        return net_allow.join(base, path)
    except net_allow.NetAllowError as e:
        raise RunError(str(e), "config") from None


# ── فحص السيرفر ─────────────────────────────────────────────────────────
def probe(url: str, token: str | None = None, *, timeout: float = 10) -> dict:
    """GET /models: {ok, models[], reason, message}. ما بيرمي — بيرجّع السبب."""
    try:
        base = net_allow.validate(url, subject="رابط الواجهة القياسية", example="http://127.0.0.1:8000/v1", allow_path=True)
    except net_allow.NetAllowError as e:
        return {"ok": False, "reason": "config", "message": str(e), "models": []}
    sess = session(token)
    try:
        d = _json(call(sess, "GET", _url(base, "/models"), None, read_timeout=timeout), 4 * 1024 * 1024)
    except RunError as e:
        return {"ok": False, "reason": e.reason, "message": str(e), "models": []}
    finally:
        sess.close()
    items = d.get("data") if isinstance(d.get("data"), list) else d.get("models") if isinstance(d.get("models"), list) else []
    ids = []
    for it in items[:MAX_MODELS]:
        mid = it.get("id") if isinstance(it, dict) else it
        if isinstance(mid, str) and 0 < len(mid) <= 200:
            ids.append(mid)
    return {"ok": True, "reason": "", "message": f"السيرفر شغّال — {len(ids)} موديل", "models": ids}


# ── المهام ──────────────────────────────────────────────────────────────
def _size(cfg: dict, p: dict) -> str:
    if p.get("width") and p.get("height"):
        return f"{int(p['width'])}x{int(p['height'])}"
    return cfg.get("size") or "1024x1024"


def _read_file(path, cap: int, what: str) -> bytes:
    try:
        p = Path(path)
        if p.stat().st_size > cap:
            raise RunError(f"{what} أكبر من الحد المسموح", "config", False)
        return p.read_bytes()
    except OSError:
        raise RunError(f"ما قدرت أقرا {what}", "config", False) from None


def _image_result(d: dict, sess, base: str, ctx: Ctx) -> Path:
    items = d.get("data")
    first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
    if not first:
        raise RunError("رد السيرفر ما فيه صورة", "bad_output")
    out = ctx.tmp / "result.img"
    if first.get("b64_json"):
        try:
            raw = base64.b64decode(first["b64_json"], validate=False)
        except (ValueError, TypeError):
            raise RunError("الصورة بالرد تالفة (base64)", "bad_output") from None
        if len(raw) > MAX_IMAGE_BYTES:
            raise RunError("الصورة أكبر من الحد المسموح", "bad_output")
        out.write_bytes(raw)
        return out
    url = first.get("url")
    if isinstance(url, str) and url:
        if not net_allow.same_host(base, url) or "@" in urlsplit(url).netloc or re.search(r"[\s\\]", url):
            raise RunError("السيرفر رجّع رابط صورة غير آمن (مضيف تاني أو شكل غريب) — ما بنحمّل منه", "bad_output")
        r = call(sess, "GET", url, ctx, stream=True)
        out.write_bytes(_body(r, MAX_IMAGE_BYTES))
        return out
    raise RunError("رد السيرفر ما فيه صورة (لا b64_json ولا url)", "bad_output")


def _image(ctx: Ctx, sess, base: str) -> dict:
    m, cfg, p, req = ctx.model, ctx.model["std"], ctx.params, ctx.req
    prompt = req.prompt.strip()
    if not prompt:
        raise RunError("ما في وصف للصورة", "config", False)
    size = _size(cfg, p)
    refs = [Path(x) for x in ([req.image] if req.image else []) + list(req.refs or [])]
    fmt = cfg.get("response_format") if cfg.get("response_format") in ("b64_json", "url") else "b64_json"
    if refs:
        if not (m.get("caps") or {}).get("edit") and not (m.get("caps") or {}).get("refs"):
            raise RunError("هالنموذج ما بيقبل صور مرجعية", "unsupported", False)
        files = []
        for i, f in enumerate(refs[:4]):
            raw = _read_file(f, 30 * 1024 * 1024, "الصورة المرجعية")
            mime = mimetypes.guess_type(f.name)[0] or "image/png"
            files.append(("image[]" if len(refs) > 1 else "image", (f"ref{i}{f.suffix.lower() or '.png'}", raw, mime)))
        r = call(sess, "POST", _url(base, "/images/edits"), ctx, files=files,
                 data={"model": cfg["model"], "prompt": prompt, "n": "1", "size": size, "response_format": fmt})
    else:
        r = call(sess, "POST", _url(base, "/images/generations"), ctx,
                 json={"model": cfg["model"], "prompt": prompt, "n": 1, "size": size, "response_format": fmt})
    return {"file": _image_result(_json(r), sess, base, ctx), "data": {}}


def _voice(ctx: Ctx, sess, base: str) -> dict:
    cfg, p, req = ctx.model["std"], ctx.params, ctx.req
    text = req.text.strip()
    if not text:
        raise RunError("ما في نص للصوت", "config", False)
    body = {"model": cfg["model"], "input": text, "voice": p.get("voice") or "alloy", "response_format": cfg.get("response_format") or "mp3"}
    if p.get("speed") and float(p["speed"]) != 1.0:
        body["speed"] = float(p["speed"])
    if p.get("instructions"):
        body["instructions"] = p["instructions"]
    r = call(sess, "POST", _url(base, "/audio/speech"), ctx, json=body, stream=True)
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "json" in ctype or "text/" in ctype:
        msg = _detail_of_body(_body(r, 1024 * 1024))
        raise RunError(f"السيرفر رجّع خطأ بدل صوت: {msg}", "bad_output")
    out = ctx.tmp / "result.audio"
    out.write_bytes(_body(r, MAX_AUDIO_BYTES))
    return {"file": out, "data": {}}


def _detail_of_body(raw: bytes) -> str:
    try:
        d = json.loads(raw.decode("utf-8"))
        err = d.get("error") if isinstance(d, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or (d.get("detail") if isinstance(d, dict) else None) or d
        return _DETAIL_RX.sub(" ", str(msg))[:200]
    except Exception:                                  # noqa: BLE001
        return _DETAIL_RX.sub(" ", raw[:200].decode("utf-8", "replace"))


def normalize_transcript(d: dict) -> dict:
    """رد /audio/transcriptions ← {text, language, words[{text,start,end}], segments[{text,start,end}]} (كلمات بالثواني)."""
    def _f(v):
        try:
            return round(float(v), 3)
        except (TypeError, ValueError):
            return None
    words = []
    raw_words = d.get("words") if isinstance(d.get("words"), list) else []
    segs = d.get("segments") if isinstance(d.get("segments"), list) else []
    if not raw_words:                                  # بعض السيرفرات بتحط الكلمات داخل المقاطع
        raw_words = [w for s in segs if isinstance(s, dict) for w in (s.get("words") or []) if isinstance(w, dict)]
    for w in raw_words:
        if not isinstance(w, dict):
            continue
        text = str(w.get("word") if w.get("word") is not None else w.get("text") or "").strip()
        st, en = _f(w.get("start")), _f(w.get("end"))
        if text and st is not None and en is not None and en >= st:
            words.append({"text": text, "start": st, "end": en})
    out_segs = []
    for s in segs:
        if isinstance(s, dict):
            st, en = _f(s.get("start")), _f(s.get("end"))
            t = str(s.get("text") or "").strip()
            if t and st is not None and en is not None:
                out_segs.append({"text": t, "start": st, "end": en})
    text = str(d.get("text") or "").strip() or " ".join(s["text"] for s in out_segs)
    return {"text": text, "language": str(d.get("language") or "")[:12], "words": words, "segments": out_segs}


def _stt(ctx: Ctx, sess, base: str) -> dict:
    cfg, p, req = ctx.model["std"], ctx.params, ctx.req
    if not req.audio:
        raise RunError("ما في ملف صوت للتفريغ", "config", False)
    audio = Path(req.audio)
    try:
        size = audio.stat().st_size
    except OSError:
        raise RunError("ما قدرت أقرا ملف الصوت", "config", False) from None
    if size > MAX_AUDIO_BYTES:
        raise RunError("ملف الصوت أكبر من الحد المسموح", "config", False)
    data = {"model": cfg["model"], "response_format": "verbose_json", "timestamp_granularities[]": ["word", "segment"]}
    lang = req.language or p.get("language")
    if lang:
        data["language"] = str(lang)
    with audio.open("rb") as fh:
        r = call(sess, "POST", _url(base, "/audio/transcriptions"), ctx, files={"file": (f"audio{audio.suffix.lower() or '.mp3'}", fh, "application/octet-stream")}, data=data)
    return {"file": None, "data": normalize_transcript(_json(r))}


TASKS = {"image": _image, "voice": _voice, "stt": _stt}


def run(ctx: Ctx) -> dict:
    fn = TASKS.get(ctx.req.task)
    if fn is None:
        raise RunError("الواجهة القياسية بتخدم الصور والصوت والتفريغ بس", "unsupported", False)
    base = _base(ctx.model)
    sess = session(_token(ctx.model))
    try:
        return fn(ctx, sess, base)
    finally:
        sess.close()
