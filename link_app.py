"""
ربط «برنامج نموذج» (app): أغلب النماذج المفتوحة بتجي مع برنامج ويب Gradio. هون عميل REST خاص فينا (بـ requests) بيحكي معه — بلا gradio_client.

ليش مش gradio_client؟ لأنو بيبني الروابط من إعدادات البرنامج نفسه وبينزّل ملفات لحاله (يعني برنامج خبيث ممكن يحوّلنا لأي عنوان).
هون: العنوان من قائمة السماح (net_allow: 127.x أو اسم docker + منفذ)، بلا تحويلات، وروابط التنزيل بنبنيها إحنا من path الملف (مش من رابط البرنامج).

البروتوكول (انفحص على Gradio 4.44.1 و6.30.0 الحقيقيين):
    GET  {base}/config                              ← version, api_prefix ("/gradio_api" بـ 5+، فاضي بـ 4), dependencies[{id, api_name}]
    GET  {base}{prefix}/info                        ← named_endpoints{"/name": {parameters[], returns[]}}
    POST {base}{prefix}/upload  (files=…)           ← ["مسار على السيرفر", …]
    POST {base}{prefix}/call/{name}  {data:[…]}      ← {event_id}   (بلا session_hash: Gradio 4 بيضيّع الحدث لو بعتناه)
    GET  {base}{prefix}/call/{name}/{event_id}      ← SSE: event: complete|error|generating|heartbeat, data: JSON
    GET  {base}{prefix}/file={path مشفّر}           ← الملف الناتج
    POST {base}{prefix}/cancel {session_hash=event_id, fn_index, event_id}   ← بيوقف الانتظار (الدالة الشغّالة بتكمّل لحد ما تخلص: Gradio ما بيقتلها)
Gradio 3 وبرامج كلمة السر: مرفوضين برسالة واضحة.

الربط بالمكتبة: model["app"] = {url, api_name, inputs: [{param, from|const}], output: {index}, schema_hash}.
بيتحقق وقت التشغيل إن شكل النقطة ما اتغيّر (schema_hash) — برنامج اتحدّث = رسالة «أعد الربط» بدل ما يبعت مدخلات غلط بصمت.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import net_allow
from model_run import Ctx, RunError

CONNECT_TIMEOUT = 10
CALL_TIMEOUT = 30                                   # مهلة نداء عادي (config/info/upload/call/cancel)
MAX_CONFIG_BYTES = 16 * 1024 * 1024                 # /config بيكبر مع برامج كبيرة (ACE-Step…)
MAX_INFO_BYTES = 16 * 1024 * 1024
MAX_EVENT_BYTES = 8 * 1024 * 1024                   # سقف رد حدث SSE واحد
MAX_UPLOAD_JSON = 1024 * 1024
MAX_DETAIL_BYTES = 64 * 1024                        # رد خطأ: ما بنقرا أكتر من هيك
BODY_MAX_SEC = 120.0                                # جسم رد JSON واحد: لو طوّل أكتر من هيك بنقطعه
MAX_DOWNLOAD = {"image": 64 * 1024 * 1024, "audio": 200 * 1024 * 1024, "video": 1024 * 1024 * 1024}
INFO_TTL_SEC = 60.0
SOURCES = ("prompt", "negative", "text", "image", "refs", "audio", "video", "seconds", "width", "height", "language", "voice", "scale", "seed", "steps")
FILE_SOURCES = {"image": "image", "refs": "image", "audio": "audio", "video": "video"}
OUT_KIND = {"image": "image", "upscale": "image", "bgremove": "image", "voice": "audio", "music": "audio", "sfx": "audio", "lipsync": "video", "stt": None}
FILE_COMPONENTS = {"Image": "image", "ImageEditor": "image", "ImageMask": "image", "Sketchpad": "image", "Paint": "image", "Audio": "audio", "Microphone": "audio",
                   "Video": "video", "File": "file", "UploadButton": "file", "Gallery": "images", "Files": "file"}
NUMBER_COMPONENTS = {"Number", "Slider"}
CHOICE_COMPONENTS = {"Dropdown", "Radio", "CheckboxGroup"}
API_NAME_RX = re.compile(r"/?[A-Za-z0-9_\-]{1,80}")
EVENT_ID_RX = re.compile(r"[A-Za-z0-9_\-]{1,80}")
_DETAIL_RX = re.compile(r"\s+")

_info_cache: dict = {}                              # {base: (monotonic, bundle)}
_info_lock = threading.Lock()


# ── اتصال ────────────────────────────────────────────────────────────────
def session():
    import requests
    s = requests.Session()
    s.trust_env = False                              # بلا بروكسي من البيئة
    return s


def _url(base: str, path: str) -> str:
    try:
        return net_allow.join(base, path)
    except net_allow.NetAllowError:
        raise RunError("مسار النداء للبرنامج غير آمن", "config", False) from None


def _req(sess, method: str, url: str, ctx: Ctx | None = None, *, timeout: float | None = None, stream: bool = True, **kw):
    """نداء واحد: كل فشل بيتحوّل لـ RunError بسبب واضح. بلا تحويلات أبداً."""
    import requests
    if ctx is not None:
        ctx.check()
    try:
        r = sess.request(method, url, timeout=(CONNECT_TIMEOUT, max(1.0, timeout or CALL_TIMEOUT)), allow_redirects=False, stream=stream, **kw)
    except requests.exceptions.ConnectTimeout:
        raise RunError("البرنامج ما ردّ بوقت الاتصال", "connection") from None
    except requests.exceptions.ReadTimeout:
        raise RunError("البرنامج تأخر بالرد أكتر من المهلة", "timeout") from None
    except requests.exceptions.RequestException:
        raise RunError("ما قدرت أتصل بالبرنامج — واقف أو الرابط غلط", "connection") from None
    code = r.status_code
    if 300 <= code < 400:
        r.close()
        raise RunError("البرنامج حاول يحوّلنا لعنوان ثاني — التحويلات ممنوعة", "connection")
    if code in (401, 403):
        r.close()
        raise RunError("البرنامج محمي بكلمة سر (تسجيل دخول) — ما بنقدر نربطه", "auth")
    if code == 404:
        r.close()
        raise RunError("هالمسار مش موجود بالبرنامج — تأكد إنه Gradio 4 أو أحدث وإن الرابط صح", "missing")
    if code in (429, 503):
        r.close()
        raise RunError("البرنامج مشغول أو الطابور ممتلئ", "busy")
    if code >= 400:
        msg = _detail(r)
        r.close()
        low = msg.lower()
        raise RunError(f"البرنامج رفض الطلب: {msg}", "oom" if "out of memory" in low else ("rejected" if code < 500 else "model_failed"))
    return r


def _detail(resp) -> str:
    try:
        raw = b""
        for chunk in resp.iter_content(8192):        # بسقف: رد خطأ ضخم ما بيتحمّل كله بالذاكرة
            raw += chunk
            if len(raw) >= MAX_DETAIL_BYTES:
                break
        d = json.loads(raw.decode("utf-8", "replace"))
        msg = d.get("detail") if isinstance(d, dict) else None
        if isinstance(msg, (list, dict)):
            msg = json.dumps(msg, ensure_ascii=False)
        if msg:
            return _DETAIL_RX.sub(" ", str(msg))[:200]
    except Exception:                                # noqa: BLE001
        pass
    return f"رد {resp.status_code}"


def _body(resp, cap: int) -> bytes:
    chunks, got, t_end = [], 0, time.monotonic() + BODY_MAX_SEC
    try:
        for chunk in resp.iter_content(1 << 16):
            got += len(chunk)
            if got > cap:
                raise RunError("رد البرنامج أكبر من الحد المسموح", "bad_output")
            if time.monotonic() > t_end:
                raise RunError("رد البرنامج طوّل كتير (بيجي بالقطّارة)", "timeout")
            chunks.append(chunk)
    except RunError:
        raise
    except Exception:                                # noqa: BLE001
        raise RunError("انقطع تنزيل الرد من البرنامج", "connection") from None
    finally:
        resp.close()
    return b"".join(chunks)


def _json(resp, cap: int):
    try:
        return json.loads(_body(resp, cap).decode("utf-8"))
    except ValueError:
        raise RunError("رد البرنامج مش JSON مفهوم — هل هو برنامج Gradio؟", "bad_output") from None


def _prefix(cfg: dict) -> str:
    p = cfg.get("api_prefix")
    if not isinstance(p, str) or not p.strip("/"):
        return ""
    p = "/" + p.strip("/")
    return p if re.fullmatch(r"/[A-Za-z0-9_\-]{1,40}", p) else ""


def _major(version: str) -> int:
    m = re.match(r"(\d+)\.", str(version or ""))
    return int(m.group(1)) if m else 0


# ── شكل النقاط ───────────────────────────────────────────────────────────
def kind_of(component: str | None) -> str:
    """نوع الخانة من اسم مكوّن Gradio: image|audio|video|file|images|number|bool|choice|text."""
    c = str(component or "")
    if c in FILE_COMPONENTS:
        return FILE_COMPONENTS[c]
    if c in NUMBER_COMPONENTS:
        return "number"
    if c == "Checkbox":
        return "bool"
    if c in CHOICE_COMPONENTS:
        return "choice"
    return "text"


def api_name_of(name) -> str:
    n = str(name or "").strip()
    if not API_NAME_RX.fullmatch(n):
        raise RunError("اسم نقطة البرنامج غير صالح", "config", False)
    return n if n.startswith("/") else "/" + n


def schema_hash(ep: dict) -> str:
    """بصمة شكل النقطة (أسماء المعاملات وأنواعها وأنواع المخرجات): بتتغيّر لما البرنامج يتحدّث بشكل مختلف."""
    params = [[str(p.get("parameter_name") or p.get("label") or ""), str(p.get("component") or ""), bool(p.get("parameter_has_default"))] for p in (ep.get("parameters") or [])]
    rets = [str(r.get("component") or "") for r in (ep.get("returns") or [])]
    return hashlib.sha256(json.dumps([params, rets], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def param_public(p: dict) -> dict:
    return {"name": str(p.get("parameter_name") or ""), "label": str(p.get("label") or ""), "component": str(p.get("component") or ""),
            "kind": kind_of(p.get("component")), "required": not p.get("parameter_has_default"),
            "default": p.get("parameter_default") if p.get("parameter_has_default") else None}


def _text(p: dict) -> str:
    return f"{p.get('parameter_name') or ''} {p.get('label') or ''}".lower()


_RX = {
    "negative": re.compile(r"neg"),
    "prompt": re.compile(r"prompt|caption|description|instruction|query|وصف"),
    "text": re.compile(r"\btext\b|sentence|script|transcript|content|utterance|نص"),
    "seed": re.compile(r"seed"),
    "seconds": re.compile(r"duration|seconds|length|\bsecs?\b|مدة"),
    "width": re.compile(r"\bwidth\b|عرض"),
    "height": re.compile(r"\bheight\b|ارتفاع"),
    "steps": re.compile(r"steps|inference"),
    "scale": re.compile(r"scale|factor|zoom"),
    "language": re.compile(r"lang"),
    "voice": re.compile(r"voice|speaker"),
}
_GUIDANCE_RX = re.compile(r"guidance|cfg")
TASK_NAME_RX = {                                     # اسم النقطة بيلمّح للمهمة: بيرجّح لما أكتر من نقطة بتنفع (مثلاً برنامج فيه توليد صوت وموسيقى)
    "image": re.compile(r"image|img|generate|txt2img|draw|paint|picture"), "voice": re.compile(r"speak|tts|speech|voice|say|synth"),
    "stt": re.compile(r"transcri|stt|asr|recogn|whisper"), "upscale": re.compile(r"upscal|enhance|esrgan|super|restor"),
    "bgremove": re.compile(r"remove|background|matting|rembg|mask|cutout"), "lipsync": re.compile(r"lip|sync|talk|s2v|animate|dub"),
    "music": re.compile(r"music|song|compos|melod"), "sfx": re.compile(r"sfx|sound|effect|foley|audio"),
}
NEEDS = {"image": (("prompt",),), "voice": (("text",),), "stt": (("audio",),), "upscale": (("image",),), "bgremove": (("image",),),
         "lipsync": (("video", "image"), ("audio",)), "music": (("prompt",),), "sfx": (("prompt",),)}


def suggest(task: str, params: list[dict]) -> list[dict]:
    """اقتراح ربط المعاملات بمدخلات الطلب من أسمائها وأنواعها: [{param, from}]. المالك بيأكّد ويعدّل."""
    out: list[dict] = []
    used_src: set[str] = set()
    used_par: set[str] = set()

    def give(p: dict, src: str) -> None:
        name = p.get("parameter_name")
        if name and src not in used_src and name not in used_par:
            used_src.add(src)
            used_par.add(name)
            out.append({"param": name, "from": src})

    plist = list(params or [])
    for p in plist:                                                    # ملفات
        k = kind_of(p.get("component"))
        if k in ("image", "audio", "video"):
            give(p, k)
        elif k == "images" and task == "image":
            give(p, "refs")
    texts = [p for p in plist if kind_of(p.get("component")) == "text"]
    main = "text" if task == "voice" else ("prompt" if task in ("image", "music", "sfx") else None)
    if main:
        hints = ("text", "prompt") if main == "text" else ("prompt",)
        pick = next((p for p in texts if not _RX["negative"].search(_text(p)) and any(_RX[k].search(_text(p)) for k in hints)), None)
        if pick is None:
            pick = next((p for p in texts if not p.get("parameter_has_default") and not _RX["negative"].search(_text(p))), None)
        if pick:
            give(pick, main)
    for p in texts:
        t = _text(p)
        if _RX["negative"].search(t):
            give(p, "negative")
        elif task == "voice" and _RX["voice"].search(t):
            give(p, "voice")
        elif _RX["language"].search(t):
            give(p, "language")
    for p in plist:
        k, t = kind_of(p.get("component")), _text(p)
        if k == "number":
            if _RX["seed"].search(t):
                give(p, "seed")
            elif _RX["seconds"].search(t):
                give(p, "seconds")
            elif _RX["width"].search(t):
                give(p, "width")
            elif _RX["height"].search(t):
                give(p, "height")
            elif _RX["steps"].search(t) and not _GUIDANCE_RX.search(t):
                give(p, "steps")
            elif task == "upscale" and _RX["scale"].search(t) and not _GUIDANCE_RX.search(t):
                give(p, "scale")
        elif k == "choice" and task == "upscale" and _RX["scale"].search(t):
            give(p, "scale")
    return out


def endpoint_public(name: str, ep: dict, task: str | None = None) -> dict:
    params = ep.get("parameters") or []
    rets = ep.get("returns") or []
    pub = {"api_name": name if name.startswith("/") else "/" + name, "hash": schema_hash(ep), "params": [param_public(p) for p in params],
           "returns": [{"label": str(r.get("label") or ""), "component": str(r.get("component") or ""), "kind": kind_of(r.get("component"))} for r in rets]}
    if task:
        sug = suggest(task, params)
        have = {s["from"] for s in sug}
        needs_ok = all(any(x in have for x in group) for group in NEEDS.get(task, ()))
        want = OUT_KIND.get(task)
        kinds = {r["kind"] for r in pub["returns"]}
        out_ok = ("text" in kinds) if want is None else bool(kinds & ({want, "file"} | ({"images"} if want == "image" else set())))
        named = bool(TASK_NAME_RX[task].search(pub["api_name"].lower())) if task in TASK_NAME_RX else False
        pub.update(suggest=sug, fits=bool(needs_ok and out_ok), score=len(sug) + (5 if out_ok else 0) + (5 if needs_ok else 0) + (4 if named else 0))
    return pub


# ── فحص برنامج ───────────────────────────────────────────────────────────
def _fail(reason: str, message: str, **extra) -> dict:
    return {"ok": False, "reason": reason, "message": message, "endpoints": [], "version": None, "prefix": "", "suggested": None, **extra}


def fetch_bundle(base: str, sess=None, *, timeout: float = 10.0, ctx: Ctx | None = None) -> dict:
    """{version, prefix, endpoints{name: ep}, deps{api_name: id}} من /config و/info. بيرمي RunError."""
    own = sess is None
    sess = sess or session()
    try:
        cfg = _json(_req(sess, "GET", _url(base, "/config"), ctx, timeout=timeout), MAX_CONFIG_BYTES)
        if not isinstance(cfg, dict):
            raise RunError("رد البرنامج مش بالشكل المتوقع — هل هو برنامج Gradio؟", "bad_output")
        ver = str(cfg.get("version") or "")
        if _major(ver) < 4:
            raise RunError(f"برنامج Gradio {ver or 'قديم'} مش مدعوم — بنشتغل مع Gradio 4 وأحدث", "unsupported", False)
        prefix = _prefix(cfg)
        info = _json(_req(sess, "GET", _url(base, prefix + "/info"), ctx, timeout=timeout), MAX_INFO_BYTES)
        eps = info.get("named_endpoints") if isinstance(info, dict) else None
        if not isinstance(eps, dict):
            raise RunError("رد /info مش بالشكل المتوقع", "bad_output")
        deps = {}
        for d in cfg.get("dependencies") or []:
            if isinstance(d, dict) and isinstance(d.get("id"), int) and d.get("api_name"):
                deps[str(d["api_name"]).lstrip("/")] = d["id"]
        return {"version": ver, "prefix": prefix, "endpoints": {str(k): v for k, v in eps.items() if isinstance(v, dict)}, "deps": deps}
    finally:
        if own:
            sess.close()


def inspect(url, task: str | None = None, *, timeout: float = 10.0) -> dict:
    """يفحص برنامج Gradio: {ok, reason, message, version, prefix, url, endpoints[{api_name, hash, params[], returns[], (suggest, fits, score)}], suggested}. ما بيرمي."""
    try:
        base = net_allow.validate(url, subject="رابط البرنامج", example="http://127.0.0.1:7860")
    except net_allow.NetAllowError as e:
        return _fail("config", str(e), url=None)
    try:
        b = fetch_bundle(base, timeout=timeout)
    except RunError as e:
        return _fail(e.reason, str(e), url=base)
    eps = [endpoint_public(n, ep, task) for n, ep in b["endpoints"].items()]
    if task:
        eps.sort(key=lambda e: (-int(e["fits"]), -e["score"]))
    best = next((e["api_name"] for e in eps if e.get("fits")), None) if task else None
    return {"ok": True, "reason": "", "message": f"برنامج Gradio {b['version']} — {len(eps)} نقطة", "url": base, "version": b["version"], "prefix": b["prefix"],
            "endpoints": eps, "suggested": best}


def _cached_bundle(base: str, sess, ctx: Ctx) -> dict:
    now = time.monotonic()
    with _info_lock:
        hit = _info_cache.get(base)
        if hit and now - hit[0] < INFO_TTL_SEC:
            return hit[1]
    b = fetch_bundle(base, sess, ctx=ctx, timeout=min(CALL_TIMEOUT, max(5.0, ctx.remaining())))
    with _info_lock:
        _info_cache[base] = (now, b)
    return b


def clear_cache() -> None:
    with _info_lock:
        _info_cache.clear()


# ── مدخلات الطلب ─────────────────────────────────────────────────────────
def _upload(sess, base: str, prefix: str, path: Path, ctx: Ctx, kind: str) -> dict:
    """يرفع ملف لبرنامج Gradio وبيرجّع FileData. بنرفع ملفاتنا بس."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        raise RunError("ما قدرت أقرا الملف اللي بدي أرفعه", "config", False) from None
    if size > MAX_DOWNLOAD.get(kind, MAX_DOWNLOAD["image"]):
        raise RunError("الملف أكبر من الحد المسموح للرفع", "config", False)
    with open(path, "rb") as fh:
        r = _req(sess, "POST", _url(base, prefix + "/upload"), ctx, files={"files": (Path(path).name or "file", fh, "application/octet-stream")})
    got = _json(r, MAX_UPLOAD_JSON)
    if not (isinstance(got, list) and got and isinstance(got[0], str) and got[0]):
        raise RunError("البرنامج ما رجّع مسار الملف المرفوع", "bad_output")
    return {"path": got[0], "meta": {"_type": "gradio.FileData"}}


def _scalar(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _value(spec: dict, p: dict, ctx: Ctx, sess, base: str, prefix: str):
    """قيمة معامل واحد حسب ربطه (من الطلب أو ثابت)."""
    kind = kind_of(p.get("component"))
    if "const" in spec:
        return spec["const"]
    src = spec["from"]
    req, params = ctx.req, ctx.params
    if src in FILE_SOURCES:
        if src == "refs":
            files = [Path(x) for x in ([req.image] if req.image else []) + list(req.refs or [])]
        else:
            f = {"image": req.image, "audio": req.audio, "video": req.video}[src]
            files = [Path(f)] if f else []
        if not files:
            raise RunError(f"المعامل «{spec['param']}» بدّه {src} وما انبعت", "config", False)
        fds = [_upload(sess, base, prefix, f, ctx, FILE_SOURCES[src]) for f in files[:4]]
        return [{"image": fd, "caption": None} for fd in fds] if kind == "images" else fds[0]
    if src in ("prompt", "text", "negative"):
        v = {"prompt": req.prompt, "text": req.text, "negative": req.negative or params.get("negative") or ""}[src]
        return str(v or "")
    if src == "seconds":
        v = req.seconds if req.seconds is not None else params.get("seconds")
    elif src == "language":
        v = req.language or params.get("language")
    else:
        v = params.get(src)
    if v in (None, ""):
        if p.get("parameter_has_default"):
            return p.get("parameter_default")
        raise RunError(f"المعامل «{spec['param']}» مربوط بـ {src} وما في قيمة إله بالطلب ولا بإعدادات النموذج", "config", False)
    return _scalar(v) if kind in ("number", "choice") else (str(v) if kind == "text" else v)


def build_data(ctx: Ctx, sess, base: str, prefix: str, ep: dict) -> list:
    """قائمة data بترتيب معاملات النقطة الحالي: المربوط من الطلب، والباقي قيمته الجاهزة."""
    app = ctx.model["app"]
    by_param = {s["param"]: s for s in app.get("inputs") or []}
    params = ep.get("parameters") or []
    names = {str(p.get("parameter_name")) for p in params}
    gone = [n for n in by_param if n not in names]
    if gone:
        raise RunError(f"المعامل «{gone[0]}» ما عاد موجود بالبرنامج — أعد ربط النموذج (عدّل ← اقرا البرنامج)", "config", False)
    data = []
    for p in params:
        spec = by_param.get(str(p.get("parameter_name")))
        if spec is not None:
            data.append(_value(spec, p, ctx, sess, base, prefix))
        elif p.get("parameter_has_default"):
            data.append(p.get("parameter_default"))
        else:
            raise RunError(f"المعامل «{p.get('parameter_name')}» مطلوب وغير مربوط — أعد ربط النموذج", "config", False)
    return data


# ── النداء والانتظار ─────────────────────────────────────────────────────
def _events(resp, ctx: Ctx, abort=None):
    """مولّد أحداث SSE (event, data). القراءة بخيط عشان الإلغاء ما يستنى بيانات، وبوابة الإلغاء/المهلة (ctx.check) بكل دورة —
    حتى لو الأحداث ماشية أسرع من نص ثانية (بث خطوات). سطر بلا نهاية بيتقطع بسقف ذاكرة.
    abort(): بينندهى لما نطلع قبل حدث ختامي (إلغاء/مهلة/SIGTERM/انقطاع) وقبل إغلاق الاتصال: إغلاقه أول بيعلق لحد ما الخيط القارئ يرجع (لحد ما البرنامج يخلص)."""
    q: queue.Queue = queue.Queue()
    limit = MAX_EVENT_BYTES + 4096

    def reader() -> None:
        buf = bytearray()
        ev = None
        try:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                buf.extend(chunk)
                while True:
                    i = buf.find(b"\n")
                    if i < 0:
                        break
                    line = bytes(buf[:i]).rstrip(b"\r").decode("utf-8", "replace")
                    del buf[:i + 1]
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        q.put(("evt", ev or "message", line[5:].strip()))
                        ev = None
                if len(buf) > limit:                 # سطر ما بينتهي: ما في سقف ذاكرة بغير هيك
                    q.put(("end", "TooLong", None))
                    return
        except Exception as e:                       # noqa: BLE001 — إغلاق متعمّد بعد الإلغاء بيطلع هون كمان
            q.put(("end", type(e).__name__, None))
            return
        q.put(("end", None, None))

    threading.Thread(target=reader, daemon=True, name="link-app-sse").start()
    done = False
    try:
        while True:
            try:
                kind, a, b = q.get(timeout=0.5)
            except queue.Empty:
                kind = a = b = None
            ctx.check()                              # مهلة/إلغاء بكل دورة، مش بس لما ما يجي شي
            if kind is None:
                continue
            if kind == "end":
                if a == "TooLong":
                    raise RunError("رد البرنامج أكبر من الحد المسموح", "bad_output")
                if a:
                    raise RunError("انقطع الاتصال بالبرنامج قبل ما يخلص", "connection")
                done = True
                return
            if len(b or "") > MAX_EVENT_BYTES:
                raise RunError("رد البرنامج أكبر من الحد المسموح", "bad_output")
            if a in ("complete", "error"):
                done = True
            yield a, b
    finally:
        if not done and abort is not None:
            abort()
        resp.close()


def _cancel(sess, base: str, prefix: str, dep_id: int | None, event_id: str) -> None:
    """بيطلب من البرنامج يوقف الحدث (بقدر الإمكان). الحدث اللي بلا session_hash بتاعنا بيحمل رقمه كـ session_hash. الدالة الشغّالة ممكن تكمّل لحد ما تخلص."""
    if dep_id is None:
        return
    try:
        _req(sess, "POST", _url(base, prefix + "/cancel"), None, timeout=5, json={"session_hash": event_id, "fn_index": dep_id, "event_id": event_id}).close()
    except Exception:                                # noqa: BLE001 — إلغاء بقدر الإمكان
        pass


def _error_text(data) -> str:
    """نص خطأ البرنامج (Gradio 6 بيرجّع {error}, و4 بيرجّع null أو نص قصير)."""
    try:
        d = json.loads(data) if data else None
    except ValueError:
        d = data
    msg = d.get("error") if isinstance(d, dict) else d
    if not isinstance(msg, str) or not msg.strip():
        return "بلا تفاصيل (شوف سجل البرنامج)"
    return _DETAIL_RX.sub(" ", msg.split("\n")[0])[:200]


def call(sess, base: str, prefix: str, api: str, data: list, ctx: Ctx, dep_id: int | None) -> list:
    """POST /call ← SSE ← قائمة المخرجات. أي فشل = RunError."""
    name = api.lstrip("/")
    r = _req(sess, "POST", _url(base, f"{prefix}/call/{name}"), ctx, json={"data": data})
    ev = _json(r, 64 * 1024)
    eid = ev.get("event_id") if isinstance(ev, dict) else None
    if not isinstance(eid, str) or not EVENT_ID_RX.fullmatch(eid):
        raise RunError("رد البرنامج غير مفهوم (ما في رقم حدث)", "bad_output")
    def abort() -> None:                             # إلغاء أو مهلة أو SIGTERM (SystemExit) أو انقطاع: ما نخلّي الحدث شغّال عند البرنامج
        _cancel(sess, base, prefix, dep_id, eid)
    try:
        stream = _req(sess, "GET", _url(base, f"{prefix}/call/{name}/{eid}"), ctx, timeout=max(5.0, min(3600.0, ctx.remaining())), stream=True)
    except BaseException:                            # الحدث انطلب وما قدرنا نتابعه
        abort()
        raise
    ctx.log(f"[البرنامج] {base} ({api})")
    result = None
    for event, payload in _events(stream, ctx, abort):
        if event == "complete":
            if payload in (None, "", "null"):
                raise RunError("انلغت الشغلة عند البرنامج", "cancelled", False)
            try:
                result = json.loads(payload)
            except ValueError:
                raise RunError("ناتج البرنامج مش JSON مفهوم", "bad_output") from None
            break
        if event == "error":
            text = _error_text(payload)
            low = text.lower()
            raise RunError(f"البرنامج فشل: {text}", "oom" if "out of memory" in low or ("cuda" in low and "memory" in low) else "model_failed")
    if not isinstance(result, list):
        raise RunError("البرنامج خلّص بلا ناتج", "bad_output")
    return result


# ── المخرجات ─────────────────────────────────────────────────────────────
def _is_file(v) -> bool:
    return isinstance(v, dict) and isinstance(v.get("path") or v.get("url"), str) and ("meta" in v or "orig_name" in v or "path" in v)


def _unwrap(v):
    """Gallery (مكوّن معرض): قائمة عناصر ({image|video|audio: ملف، caption} أو ملف أو [ملف، caption]) ← أول ملف فيها. غير هيك بيرجّع القيمة نفسها."""
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, (list, tuple)) and first:
            first = first[0]
        if isinstance(first, dict):
            for k in ("image", "video", "audio"):
                if _is_file(first.get(k)):
                    return first[k]
            if _is_file(first):
                return first
    return v


def _file_kind(v: dict) -> str | None:
    name = str(v.get("orig_name") or v.get("path") or v.get("url") or "").lower().rsplit(".", 1)
    ext = name[-1] if len(name) > 1 else ""
    if ext in ("png", "jpg", "jpeg", "webp", "gif", "bmp", "avif"):
        return "image"
    if ext in ("wav", "mp3", "m4a", "ogg", "opus", "flac", "aac"):
        return "audio"
    if ext in ("mp4", "webm", "mov", "mkv", "m4v"):
        return "video"
    return None


def pick_output(outputs: list, task: str, index: int | None):
    """المخرج المناسب للمهمة: بالرقم لو المالك حدّده، وإلا أول ملف من النوع المطلوب (أو أول نص للتفريغ)."""
    outputs = [_unwrap(v) for v in outputs]
    if index is not None:
        if not 0 <= index < len(outputs):
            raise RunError("رقم المخرج اللي ربطته ما عاد موجود بالبرنامج — أعد الربط", "config", False)
        return outputs[index]
    want = OUT_KIND[task]
    for v in outputs:
        if want and _is_file(v) and _file_kind(v) in (want, None):
            return v
        if want is None and ((isinstance(v, str) and v.strip()) or (isinstance(v, dict) and not _is_file(v))):
            return v
    for v in outputs:
        if want and _is_file(v):
            return v
    raise RunError("ما لقيت بمخرجات البرنامج ناتج من النوع المطلوب", "bad_output")


def download(sess, base: str, prefix: str, fd: dict, ctx: Ctx, kind: str) -> Path:
    """بينزّل ملف ناتج: الرابط من path (مش من رابط البرنامج: Gradio 4 أحياناً بيرجّع رابط مبتور). رابط خارجي = رفض."""
    path = fd.get("path")
    if isinstance(path, str) and path:
        if ".." in path.replace("\\", "/").split("/") or "\x00" in path:
            raise RunError("البرنامج رجّع مسار ملف غير آمن", "bad_output")
        url = _url(base, f"{prefix}/file={quote(path, safe='/')}")
    else:
        u = str(fd.get("url") or "")
        if not net_allow.same_host(base, u) or "@" in urlsplit(u).netloc or re.search(r"[\s\\]", u):
            raise RunError("البرنامج رجّع رابط خارجي — ما بنحمّل منه", "bad_output")
        url = u
    try:
        r = _req(sess, "GET", url, ctx, stream=True, timeout=max(CALL_TIMEOUT, min(600.0, ctx.remaining())))
    except RunError as e:
        if e.reason == "missing":
            raise RunError("ما لقيت ملف الناتج عند البرنامج", "bad_output") from None
        raise
    ext = Path(str(fd.get("orig_name") or path or "")).suffix.lower()
    out = ctx.tmp / ("result" + (ext if 1 < len(ext) <= 6 else ""))
    cap, got = MAX_DOWNLOAD[kind], 0
    try:
        with open(out, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                got += len(chunk)
                if got > cap:
                    raise RunError("ناتج البرنامج أكبر من الحد المسموح", "bad_output")
                f.write(chunk)
    except RunError:
        raise
    except Exception:                                # noqa: BLE001
        raise RunError("انقطع تنزيل الناتج من البرنامج", "connection") from None
    finally:
        r.close()
    if got == 0:
        raise RunError("البرنامج رجّع ملف فاضي", "bad_output")
    return out


def _transcript(v) -> dict:
    """مخرج نصي (تفريغ): نص، أو JSON بشكل Whisper ({text, words, segments})."""
    import link_std
    if isinstance(v, str):
        try:
            d = json.loads(v)
            v = d if isinstance(d, dict) else v
        except ValueError:
            pass
    if isinstance(v, dict):
        return link_std.normalize_transcript(v)
    return {"text": str(v).strip(), "language": "", "words": [], "segments": []}


def run(ctx: Ctx) -> dict:
    app = ctx.model.get("app") or {}
    task = ctx.req.task
    if task not in OUT_KIND:
        raise RunError("مهمة غير مدعومة ببرنامج النموذج", "unsupported", False)
    try:
        base = net_allow.validate(app.get("url"), subject="رابط البرنامج", example="http://127.0.0.1:7860")
    except net_allow.NetAllowError as e:
        raise RunError(str(e), "config", False) from None
    api = api_name_of(app.get("api_name"))
    sess = session()
    try:
        b = _cached_bundle(base, sess, ctx)
        ep = b["endpoints"].get(api)
        if ep is None:
            raise RunError(f"نقطة «{api}» ما عادت موجودة بالبرنامج — أعد ربط النموذج (عدّل ← اقرا البرنامج)", "config", False)
        want = app.get("schema_hash")
        if want and schema_hash(ep) != want:
            raise RunError(f"البرنامج اتغيّر بعد ما ربطته (شكل نقطة «{api}» تبدّل، غالباً تحديث) — أعد الربط من «عدّل» ثم «اقرا البرنامج»", "config", False)
        data = build_data(ctx, sess, base, b["prefix"], ep)
        outputs = call(sess, base, b["prefix"], api, data, ctx, b["deps"].get(api.lstrip("/")))
        out = pick_output(outputs, task, (app.get("output") or {}).get("index"))
        kind = OUT_KIND[task]
        if kind is None:
            return {"file": None, "data": _transcript(out)}
        if not _is_file(out):
            raise RunError("مخرج البرنامج مش ملف", "bad_output")
        return {"file": download(sess, base, b["prefix"], out, ctx, kind), "data": {}}
    finally:
        sess.close()
