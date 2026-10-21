"""
تحريك اللقطات عبر API مباشر (المزوّد: fal.ai) — طريقة «الأرخص» بدون سيرفر ولا كرت شاشة.

الفكرة: fal.ai بيستضيف أكتر من نموذج تحريك (Kling وHailuo وGrok وغيرهم) بمفتاح واحد وبالدفع حسب الثواني.
كل نموذج بيتسجّل بسجل الموديلات (motion.py) كـ `kind: "api"` مع:
    api = {provider: "fal", endpoint: "fal-ai/...", input: {قالب المدخلات}, durations: [5, 10], cost_per_sec: 0.07}

التدفق: إرسال الصورة+البرومبت (طابور fal) ← استنى النتيجة ← نزّل الفيديو. بعدها motion.fit_duration بيضبط المدة.

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
        "durations": [5, 10], "cost_per_sec": 0.07, "max_sec": 10,
        "strengths": ["product", "realism", "faces"],
        "note": "جودة عالية للناس والمنتجات. السعر التقديري 0.07$ للثانية بدون صوت.",
    },
    "hailuo02": {
        "name": "Hailuo 02 Standard (fal)", "provider": "fal",
        "endpoint": "fal-ai/minimax/hailuo-02/standard/image-to-video",
        "input": {"prompt": "{prompt}", "image_url": "{image}", "duration": "{duration_str}", "resolution": "768P",
                  "prompt_optimizer": True},
        "durations": [6, 10], "cost_per_sec": 0.045, "max_sec": 10,
        "strengths": ["product", "realism"],
        "note": "أرخص بشوي، حركة جيدة للمنتجات. السعر التقديري 0.045$ للثانية بدقة 768p.",
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
}


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
    return {"provider": "fal", "endpoint": ep, "input": inp, "durations": sorted({float(d) for d in durs}),
            "cost_per_sec": cost}


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


_PLACEHOLDER_RX = re.compile(r"\{(prompt|image|duration|duration_str|duration_int)\}")


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


def build_payload(spec: dict, image_uri: str, prompt: str, duration: float) -> dict:
    d = int(duration) if float(duration).is_integer() else duration
    vals = {"prompt": prompt[:2000], "image": image_uri, "duration": d, "duration_str": str(d)}
    return _fill(spec["input"], vals)


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
            log=print, cancel=None, sleep=time.sleep) -> dict:
    """يرسل المهمة، يستنى، ينزّل الفيديو لـ out. بيرجّع {request_id, billed_sec, cost_usd, took_sec}."""
    spec = validate_spec(spec)
    key = get_key()
    if not key:
        raise ApiMotionError("ما في مفتاح fal — حطّه من «المصنع» ثم «API»")
    duration = pick_duration(spec, seconds)
    payload = build_payload(spec, _image_data_uri(Path(image)), prompt, duration)
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
    log(f"    [fal] أُرسلت {ep.split('/')[1]} — {duration:g}ث")

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
