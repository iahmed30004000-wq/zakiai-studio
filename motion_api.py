"""
تحريك اللقطات عبر API مباشر (المزوّد: fal.ai) — طريقة «الأرخص» بدون سيرفر ولا كرت شاشة.

الفكرة: fal.ai بيستضيف أكتر من نموذج تحريك (Kling وHailuo وGrok وغيرهم) بمفتاح واحد وبالدفع حسب الثواني.
كل نموذج بيتسجّل بسجل الموديلات (motion.py) كـ `kind: "api"` مع:
    api = {provider: "fal", endpoint: "fal-ai/...", input: {قالب المدخلات}, durations: [5, 10], cost_per_sec: 0.07}

التدفق: إرسال الصورة+البرومبت (طابور fal) ← استنى النتيجة ← نزّل الفيديو. بعدها motion.fit_duration بيضبط المدة.

ثبات الشخصية (أسماء الحقول متحقَّق منها من صفحات fal الرسمية):
  · البرومبت السلبي: أي قالب فيه negative_prompt (Kling) بنضيف عليه ممنوعات الهوية (ملامح شرق آسيا، تغيّر الوجه…) بلا ما نبدّل اللي كاتبه المالك.
  · صورة النهاية: spec.end_image_field (Kling 2.6 وHailuo 02: end_image_url) — بنبعت صورة اللقطة المعتمدة نفسها فالوجه يرجع لحاله بآخر اللقطة.
  · النموذج المرجعي (Kling O1): {ref_front} {ref_three_quarter} {ref_side} بقالب المدخلات بتنبدّل بصور الشخصية (elements[].frontal_image_url
    وreference_image_urls) والبرومبت بيذكر @Image1 (أول لقطة) و@Element1 (الشخص). مرجع ناقص بينشال من الطلب؛ «أمام» ناقصة = خطأ واضح.
  · Hailuo: prompt_optimizer مطفي لأنو بيعيد كتابة البرومبت وبيضيّع بطاقة الهوية.

قواعد أمان:
  · المفتاح من مخزن الأسرار بس (إعدادات MOTION_API.fal.api_key)، وما بينكتب بأي سجل ولا رسالة خطأ.
  · الاتصال بعنوان fal الثابت بس. روابط الحالة/النتيجة/الإلغاء بتنقبل فقط لو بتبدأ بنفس العنوان (حماية SSRF)،
    وتنزيل الفيديو بس من نطاقات fal.media عبر https.
  · الصورة بتنبعت لـ fal.ai (برّا جهازك) — لهيك هالطريقة اختيارية ومعلَّمة بالواجهة.
  · الأسعار تقديرية من صفحات المزوّد وبتتغيّر: المالك بيعدّلها بسجل الموديلات، ومنطلع تقدير التكلفة قبل ما ننفّق.
"""

from __future__ import annotations

import base64
import io
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

QUEUE_BASE = "https://queue.fal.run"
ALLOWED_DOWNLOAD_SUFFIXES = (".fal.media", ".fal.run")            # + fal.media نفسه
ALLOWED_DOWNLOAD_EXACT = {"fal.media"}
ENDPOINT_RX = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*){1,4}$")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024
POLL_START, POLL_MAX = 2.0, 6.0
KEY_PATH = ("MOTION_API", "fal", "api_key")


class ApiMotionError(Exception):
    """رسالة عربية جاهزة للعرض (بلا مفاتيح ولا روابط حساسة)."""


# ── قوالب جاهزة (المدخلات مأخوذة من صفحات الـ API الرسمية على fal.ai) ─────
# cost_per_sec: تقديري من صفحات المزوّد وقت الكتابة وبيتغيّر — تأكّد من صفحة الأسعار. generate_audio=false عشان الصوت
# عنا مفصول (الفويس أوفر)، والصوت المدمج بيضاعف السعر.
PRESETS = {
    "kling26": {
        "name": "Kling 2.6 Pro (fal)", "provider": "fal",
        "endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video",
        "input": {"prompt": "{prompt}", "start_image_url": "{image}", "duration": "{duration_str}", "generate_audio": False,
                  "negative_prompt": "blur, distort, low quality, text, watermark, extra fingers"},
        "end_image_field": "end_image_url",
        "durations": [5, 10], "cost_per_sec": 0.07, "max_sec": 10,
        "strengths": ["product", "realism", "faces"],
        "note": "جودة عالية للناس والمنتجات. بياخد صورة نهاية (نفس صورة اللقطة) وبرومبت سلبي ضد تغيّر الوجه. السعر التقديري 0.07$ للثانية بدون صوت.",
    },
    "hailuo02": {
        "name": "Hailuo 02 Standard (fal)", "provider": "fal",
        "endpoint": "fal-ai/minimax/hailuo-02/standard/image-to-video",
        "input": {"prompt": "{prompt}", "image_url": "{image}", "duration": "{duration_str}", "resolution": "768P",
                  "prompt_optimizer": False},
        "end_image_field": "end_image_url",
        "durations": [6, 10], "cost_per_sec": 0.045, "max_sec": 10,
        "strengths": ["product", "realism"],
        "note": "أرخص بشوي، حركة جيدة للمنتجات. محسّن البرومبت مطفي (بيعيد كتابة كلامنا) وبياخد صورة نهاية. السعر التقديري 0.045$ للثانية بدقة 768p.",
    },
    "grok": {
        "name": "Grok Imagine Video (fal)", "provider": "fal",
        "endpoint": "xai/grok-imagine-video/image-to-video",
        "input": {"prompt": "{prompt}", "image_url": "{image}", "duration": "{duration_int}", "resolution": "720p",
                  "aspect_ratio": "9:16"},
        "durations": [6], "cost_per_sec": 0.07, "max_sec": 6,
        "strengths": ["product"],
        "note": "سعره قريب من Kling. السعر التقديري 0.07$ للثانية بدقة 720p.",
    },
    "klingo1": {
        "name": "Kling O1 — من المراجع (fal)", "provider": "fal",
        "endpoint": "fal-ai/kling-video/o1/standard/reference-to-video",
        "input": {"prompt": "Start from @Image1 as the first frame. The person is @Element1: keep exactly the same face, skin tone, hair "
                            "and outfit in every frame. {prompt}",
                  "image_urls": ["{image}"],
                  "elements": [{"frontal_image_url": "{ref_front}", "reference_image_urls": ["{ref_three_quarter}", "{ref_side}"]}],
                  "duration": "{duration_str}", "aspect_ratio": "9:16"},
        "durations": [3, 4, 5, 6, 7, 8, 9, 10], "cost_per_sec": 0.112, "max_sec": 10,
        "strengths": ["faces", "realism"],
        "note": "للقطات الوجه القريبة: بياخد صور الشخصية (أمام + ثلاثة أرباع + جانب) كمرجع هوية، فالوجه أثبت من أي موديل بصورة وحدة. "
                "السعر التقديري 0.112$ للثانية من مصادر خارجية (مش مؤكَّد من صفحة fal) — تأكّد منه وعدّله. الدقة 720p (نسخة Pro بتطلع 1080p بسعر أعلى).",
    },
}
REF_VIEWS = ("front", "three_quarter", "side")                    # صور الشخصية اللي بتنبعت للموديل المرجعي (بالترتيب)
END_FIELD_RX = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_REF_RX = re.compile(r"\{ref_(front|three_quarter|side)\}")
MAX_NEGATIVE = 2500


# ── التحقق من إعداد النموذج ─────────────────────────────────────────────
def validate_spec(spec: dict) -> dict:
    """يتحقق من حقل api بسجل الموديل ويرجّع نسخة منظّفة. الرسائل عربية."""
    if not isinstance(spec, dict):
        raise ApiMotionError("إعدادات الـ API ناقصة")
    if spec.get("provider", "fal") != "fal":
        raise ApiMotionError("المزوّد المدعوم حالياً: fal فقط")
    ep = str(spec.get("endpoint") or "").strip().strip("/")
    if not ENDPOINT_RX.match(ep):
        raise ApiMotionError("اسم النموذج (endpoint) غير صالح — مثال: fal-ai/kling-video/v2.6/pro/image-to-video")
    inp = spec.get("input")
    if not isinstance(inp, dict) or not inp:
        raise ApiMotionError("قالب المدخلات (input) لازم يكون كائن غير فاضي")
    flat = repr(inp)
    if "{prompt}" not in flat or "{image}" not in flat:
        raise ApiMotionError("قالب المدخلات لازم يحتوي {prompt} و{image}")
    if len(flat) > 4000:
        raise ApiMotionError("قالب المدخلات كبير كتير")
    durs = spec.get("durations")
    if not isinstance(durs, list) or not durs or not all(isinstance(x, (int, float)) and 0 < x <= 60 for x in durs):
        raise ApiMotionError("المدد المسموحة (durations) لازم تكون أرقام بالثواني، مثلاً [5, 10]")
    cost = spec.get("cost_per_sec")
    if cost is not None:
        try:
            cost = float(cost)
        except (TypeError, ValueError):
            raise ApiMotionError("سعر الثانية لازم يكون رقم")
        if not 0 <= cost <= 5:
            raise ApiMotionError("سعر الثانية خارج المعقول (0 إلى 5 دولار)")
    out = {"provider": "fal", "endpoint": ep, "input": inp, "durations": sorted({float(d) for d in durs}), "cost_per_sec": cost}
    ef = spec.get("end_image_field")
    if ef not in (None, ""):
        if not isinstance(ef, str) or not END_FIELD_RX.match(ef):
            raise ApiMotionError("اسم حقل صورة النهاية غير صالح — مثال: end_image_url")
        out["end_image_field"] = ef
    return out


def pick_duration(spec: dict, seconds: float) -> float:
    """أصغر مدة مسموحة ≥ مدة اللقطة (بنقصّ الزايد بعدين). لو أطول من أكبر مدة ← خطأ."""
    for d in sorted(spec["durations"]):
        if d + 1e-9 >= seconds:
            return float(d)
    raise ApiMotionError(f"اللقطة {seconds:.1f}ث أطول من أكبر مدة بيعملها هالنموذج ({max(spec['durations']):g}ث)")


def estimate_cost(spec: dict, seconds: float) -> float | None:
    """تقدير تكلفة لقطة بالدولار (بحسب المدة المحسوبة فعلاً، مش مدة اللقطة)."""
    if spec.get("cost_per_sec") is None:
        return None
    try:
        return round(pick_duration(spec, seconds) * float(spec["cost_per_sec"]), 4)
    except ApiMotionError:
        return None


# ── المفتاح ─────────────────────────────────────────────────────────────
def get_key() -> str | None:
    try:
        import settings_io
        cur = settings_io.load()
        for k in KEY_PATH:
            cur = (cur or {}).get(k)
        return str(cur).strip() or None if cur else None
    except Exception:
        return None


def has_key() -> bool:
    return bool(get_key())


def set_key(value: str) -> None:
    """بيحفظ المفتاح عبر settings_io (بينتقل لمخزن أسرار ويندوز وما بيكتب بأي ملف)."""
    import settings_io
    value = str(value or "").strip()
    if not value or len(value) > 400 or any(c.isspace() for c in value):
        raise ApiMotionError("المفتاح غير صالح")
    data = settings_io.load()
    data.setdefault("MOTION_API", {}).setdefault("fal", {})["api_key"] = value
    settings_io.save(data)


# ── أدوات داخلية ────────────────────────────────────────────────────────
def _headers(key: str) -> dict:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}


def _trusted(url: str) -> str:
    """روابط الحالة/النتيجة/الإلغاء لازم تبدأ بعنوان الطابور الثابت — غير هيك ما بنرسل المفتاح."""
    if not isinstance(url, str) or not url.startswith(QUEUE_BASE + "/"):
        raise ApiMotionError("المزوّد رجّع رابط غير متوقّع — أوقفنا الطلب")
    return url


def _download_ok(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme == "https" and (host in ALLOWED_DOWNLOAD_EXACT or host.endswith(ALLOWED_DOWNLOAD_SUFFIXES)):
        return True
    return host in _EXTRA_HOSTS and p.scheme in ("http", "https")      # للاختبارات فقط (بتنضاف بـ allow_test_host)


_EXTRA_HOSTS: set[str] = set()


def allow_test_host(host: str) -> None:
    _EXTRA_HOSTS.add(host)


def _image_data_uri(path: Path) -> str:
    """JPEG مضغوط (حجم أقل بكتير من PNG) كـ data URI — fal بيقبل data URI للصور."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=92, optimize=True)
    except Exception:
        raise ApiMotionError("تعذّرت قراءة صورة اللقطة")
    data = buf.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiMotionError("صورة اللقطة كبيرة كتير للرفع")
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _fill(node, vals: dict):
    """بيبدّل {prompt} {image} {duration_str} {duration_int} بمرور واحد (القيمة المبدّلة ما بتنفحص من جديد)."""
    if isinstance(node, str):
        if node == "{duration_int}":
            return int(vals["duration"])
        return _PLACEHOLDER_RX.sub(lambda m: str(vals.get(m.group(1), m.group(0))), node)
    if isinstance(node, dict):
        return {k: _fill(v, vals) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, vals) for v in node]
    return node


_PLACEHOLDER_RX = re.compile(r"\{(prompt|image|duration|duration_str|duration_int|ref_front|ref_three_quarter|ref_side)\}")
_DROP = object()
_REQUIRED_KEYS = ("frontal_image_url",)                           # عنصر مرجعي بلا صورة أمام ما بينفع: بيروح كله


def _prune(node, avail: set):
    """بيشيل من القالب كل شي بيطلب صورة شخصية مش موجودة ({ref_x}): نص ← خانة، عنصر قائمة، وحقل. بيرجّع _DROP لو كله راح.
    بيشتغل على القالب قبل التعبئة (فنص البرومبت ما بينفحص)."""
    if isinstance(node, str):
        return _DROP if any(v not in avail for v in _REF_RX.findall(node)) else node
    if isinstance(node, dict):
        out = {k: v for k, v in ((k, _prune(v, avail)) for k, v in node.items()) if v is not _DROP}
        if any(k in node and k not in out for k in _REQUIRED_KEYS):
            return _DROP
        return out if out or not node else _DROP
    if isinstance(node, list):
        out = [v for v in (_prune(v, avail) for v in node) if v is not _DROP]
        return out if out or not node else _DROP
    return node


def _merge_negative(base: str, extra: str) -> str:
    """ممنوعات الهوية بتنضاف لسلبي المالك (بلا تكرار، بنفس الترتيب)."""
    have = [t.strip() for t in str(base or "").split(",") if t.strip()]
    low = {t.lower() for t in have}
    for t in (x.strip() for x in str(extra or "").split(",")):
        if t and t.lower() not in low:
            have.append(t)
            low.add(t.lower())
    return ", ".join(have)[:MAX_NEGATIVE]


def needs_refs(spec: dict) -> set[str]:
    """وضعيات الشخصية اللي القالب بيطلبها ({ref_front}…)."""
    return set(_REF_RX.findall(repr(spec.get("input"))))


def build_payload(spec: dict, image_uri: str, prompt: str, duration: float, *, end_uri: str | None = None,
                  refs: dict | None = None, negative: str = "") -> dict:
    """refs: {front|three_quarter|side: data-uri}. end_uri: صورة النهاية (لو النموذج إله end_image_field). negative: ممنوعات إضافية."""
    d = int(duration) if float(duration).is_integer() else duration
    vals = {"prompt": prompt[:2000], "image": image_uri, "duration": d, "duration_str": str(d)}
    avail = set()
    for view, uri in (refs or {}).items():
        if view in REF_VIEWS and uri:
            vals[f"ref_{view}"] = uri
            avail.add(view)
    tpl = _prune(spec["input"], avail)
    payload = _fill(tpl, vals) if isinstance(tpl, dict) else {}
    if end_uri and spec.get("end_image_field"):
        payload[spec["end_image_field"]] = end_uri
    if negative and isinstance(payload.get("negative_prompt"), str):
        payload["negative_prompt"] = _merge_negative(payload["negative_prompt"], negative)
    return payload


def _err(r: requests.Response, what: str) -> ApiMotionError:
    code = r.status_code
    if code in (401, 403):
        return ApiMotionError("مفتاح fal مرفوض — تأكد منه بالإعدادات")
    if code == 402:
        return ApiMotionError("رصيد fal خلص — اشحن الحساب")
    if code == 422:
        try:
            msg = str(r.json().get("detail"))[:160]
        except Exception:
            msg = ""
        return ApiMotionError(f"fal رفض المدخلات ({what}) {msg}".strip())
    if code == 429:
        return ApiMotionError("fal بيقلّك: طلبات كتير — جرّب بعد شوي")
    return ApiMotionError(f"{what}: رد fal بخطأ {code}")


# ── التشغيل ─────────────────────────────────────────────────────────────
def run_job(spec: dict, image: Path, prompt: str, seconds: float, out: Path, timeout_sec: int = 900,
            log=print, cancel=None, sleep=time.sleep, *, end_image: Path | None = None, refs: dict | None = None,
            negative: str = "") -> dict:
    """يرسل المهمة، يستنى، ينزّل الفيديو لـ out. بيرجّع {request_id, billed_sec, cost_usd, took_sec}.
    end_image: صورة النهاية (بتنبعت بس لو النموذج بياخدها). refs: {وضعية: ملف} لصور الشخصية (للموديل المرجعي). negative: ممنوعات الهوية."""
    spec = validate_spec(spec)
    key = get_key()
    if not key:
        raise ApiMotionError("ما في مفتاح fal — حطّه من «المصنع» ثم «API»")
    duration = pick_duration(spec, seconds)
    wanted = needs_refs(spec)
    if "front" in wanted and not (refs or {}).get("front"):
        raise ApiMotionError("هالنموذج بياخد صور الشخصية كمرجع وما لقينا صورة «أمام» — اختار شخصية للسيناريو أو موديل تاني")
    ref_uris = {v: _image_data_uri(Path(p)) for v, p in (refs or {}).items() if v in wanted and p}
    end_uri = _image_data_uri(Path(end_image)) if end_image and spec.get("end_image_field") else None
    payload = build_payload(spec, _image_data_uri(Path(image)), prompt, duration, end_uri=end_uri, refs=ref_uris, negative=negative)
    ep = spec["endpoint"]
    t0 = time.time()
    try:
        r = requests.post(f"{QUEUE_BASE}/{ep}", json=payload, headers=_headers(key), timeout=60)
    except requests.RequestException:
        raise ApiMotionError("تعذّر الاتصال بـ fal (الإنترنت؟)")
    if r.status_code >= 300:
        raise _err(r, "إرسال المهمة")
    sub = r.json()
    rid = str(sub.get("request_id") or "")
    if not rid:
        raise ApiMotionError("fal ما رجّع رقم طلب")
    status_url, result_url, cancel_url = (_trusted(sub.get(k)) for k in ("status_url", "response_url", "cancel_url"))
    log(f"    [fal] أُرسلت {ep.split('/')[1]} — {duration:g}ث" + (" + صورة نهاية" if end_uri else "") + (" + مراجع الشخصية" if ref_uris else ""))

    def abort(reason: str):
        try:
            requests.put(cancel_url, headers=_headers(key), timeout=20)
        except requests.RequestException:
            pass
        raise ApiMotionError(reason)

    wait = POLL_START
    while True:
        if cancel is not None and cancel():
            abort("المالك ألغى التحريك")
        if time.time() - t0 > timeout_sec:
            abort(f"fal تأخّر أكتر من {timeout_sec // 60} دقيقة — ألغينا الطلب")
        sleep(wait)
        wait = min(wait * 1.3, POLL_MAX)
        try:
            s = requests.get(status_url, headers=_headers(key), timeout=30)
        except requests.RequestException:
            continue                                         # انقطاع مؤقت: منعيد المحاولة لحد المهلة
        if s.status_code >= 300:
            raise _err(s, "قراءة الحالة")
        st = s.json()
        if st.get("status") == "COMPLETED":
            if st.get("error"):
                raise ApiMotionError(f"fal فشل بالتوليد: {str(st.get('error'))[:200]}")
            break
    try:
        res = requests.get(result_url, headers=_headers(key), timeout=60)
    except requests.RequestException:
        raise ApiMotionError("تعذّر جلب نتيجة fal")
    if res.status_code >= 300:
        raise _err(res, "جلب النتيجة")
    video = (res.json().get("video") or {})
    url = str(video.get("url") or "")
    if not url:
        raise ApiMotionError("fal ما رجّع فيديو (غالباً رفض المحتوى) — جرّب برومبت أو صورة تانية")
    if not _download_ok(url):
        raise ApiMotionError("رابط الفيديو من مصدر غير متوقّع — ما نزّلناه")
    out.parent.mkdir(parents=True, exist_ok=True)
    got = 0
    try:
        with requests.get(url, stream=True, timeout=120) as dl:        # بلا المفتاح: الرابط عام موقّع
            if dl.status_code >= 300:
                raise ApiMotionError(f"تعذّر تنزيل الفيديو ({dl.status_code})")
            with out.open("wb") as f:
                for chunk in dl.iter_content(1 << 20):
                    got += len(chunk)
                    if got > MAX_VIDEO_BYTES:
                        raise ApiMotionError("الفيديو أكبر من المسموح")
                    f.write(chunk)
    except requests.RequestException:
        out.unlink(missing_ok=True)
        raise ApiMotionError("انقطع تنزيل الفيديو")
    except ApiMotionError:
        out.unlink(missing_ok=True)
        raise
    if got < 1000:
        out.unlink(missing_ok=True)
        raise ApiMotionError("الفيديو النازل فاضي أو تالف")
    cost = round(duration * spec["cost_per_sec"], 4) if spec.get("cost_per_sec") is not None else None
    return {"request_id": rid, "billed_sec": duration, "cost_usd": cost, "took_sec": round(time.time() - t0, 1)}
