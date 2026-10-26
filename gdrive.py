"""
ربط Google Drive (عميل HTTP صغير بـ requests، بلا مكتبات Google).

الفكرة: المالك بيعمل مشروع بـ Google Cloud مرة وحدة (Client ID وClient secret من نوع «TVs and Limited Input devices»)
ويحطهم بالإعدادات، وبعدين «اربط درايف» ← بيطلعلو رمز قصير ← بيكتبه بـ google.com/device. هي طريقة «الرمز» (device flow):
ما في عنوان رجوع (redirect URI)، فبتشتغل متل بعض على جهاز ويندوز وعلى السيرفر بالدومين.

قواعد أمان (ما بتنكسر):
  · الصلاحية الوحيدة drive.file: الاستوديو بيشوف وبيعدّل الملفات اللي هو عملها بس. ما منمسح شي من درايف أبداً.
  · Client secret والـ refresh token بمخزن الأسرار (settings_io بينقلهم لحالو لأن أسماءهم بتنتهي بـ secret/token).
    التوكن القصير (access token) بالذاكرة بس. ولا سر بيرجع بأي ردّ ولا بيتسجّل ولا بيطلع برسالة خطأ.
  · النداءات لعناوين Google الثابتة هون بس (net_allow.fixed_base): https، بلا تحويلات (redirect)، بلا proxy من البيئة.
    رابط الرفع بالقطع اللي بترجّعه Google لازم يكون على نفس عنوان الـ API.
  · الأخطاء صنفين: DriveTransient (نت، 429، 5xx، ضغط) بيعيد المحاولة لاحقاً، وDriveFatal (انقطع الإذن، درايف مليان،
    الواجهة مش مفعّلة) بيوقّف الطابور لحد ما المالك يصلّح.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import requests

import net_allow

OAUTH_BASE = "https://oauth2.googleapis.com"
API_BASE = "https://www.googleapis.com"
SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
HTTP_TIMEOUT = 60
SIMPLE_MAX = 5 * 1024 * 1024          # لحد هيك: رفع بطلب واحد (multipart)، وفوقها رفع بالقطع (resumable)
CHUNK = 8 * 1024 * 1024               # لازم مضاعف 256 كيلو (شرط Google)
CFG_KEY = "DRIVE"

_tok: dict = {"value": "", "exp": 0.0}
_tok_lock = threading.Lock()
_device: dict = {}                    # جلسة الربط الحالية (device_code بالذاكرة بس، ما بيطلع للواجهة)
_dev_lock = threading.Lock()


class DriveError(Exception):
    """رسالة عربية جاهزة للعرض (بلا مفاتيح ولا توكنات)."""

    def __init__(self, message: str, code: str = "drive_error"):
        super().__init__(message)
        self.code = code


class DriveTransient(DriveError):
    """مؤقت: بنعيد المحاولة بعدين (نت، ضغط، Google مش متاحة)."""


class DriveFatal(DriveError):
    """بيوقّف الطابور لحد ما المالك يتصرّف: auth (انقطع الإذن) · full (مليان) · api_disabled · forbidden · not_configured."""


class DriveNotFound(DriveError):
    """الملف أو المجلد مش موجود بدرايف (انمسح من هناك)."""


# ── الإعدادات والأسرار ──────────────────────────────────────────────────
def cfg() -> dict:
    try:
        import settings_io
        return dict(settings_io.load().get(CFG_KEY) or {})
    except Exception:                                   # noqa: BLE001
        return {}


def write_cfg(mutator) -> None:
    import settings_io
    data = settings_io.load()
    d = data.setdefault(CFG_KEY, {})
    mutator(d)
    settings_io.save(data)


def client_id() -> str:
    return str(cfg().get("client_id") or "").strip()


def _client_secret() -> str:
    return str(cfg().get("client_secret") or "").strip()


def _refresh_token() -> str:
    return str(cfg().get("refresh_token") or "").strip()


def configured() -> bool:
    return bool(client_id() and _client_secret())


def connected() -> bool:
    return bool(configured() and _refresh_token())


def set_app(client_id_value, client_secret_value) -> None:
    cid, sec = str(client_id_value or "").strip(), str(client_secret_value or "").strip()
    if not cid.endswith(".apps.googleusercontent.com") or len(cid) > 160 or any(c.isspace() for c in cid):
        raise DriveError("Client ID لازم ينتهي بـ .apps.googleusercontent.com — انسخو كامل من Google Cloud ← Clients", "bad_client_id")
    if not 10 <= len(sec) <= 120 or any(c.isspace() for c in sec):
        raise DriveError("Client secret غير صالح — انسخو كامل بدون مسافات", "bad_secret")

    def m(d):
        if d.get("client_id") != cid:                  # تطبيق تاني ← الربط القديم ما بيصلح
            for k in ("refresh_token", "email", "name", "connected_at", "paused"):
                d.pop(k, None)
        d["client_id"], d["client_secret"] = cid, sec
    write_cfg(m)
    forget_token()


def forget_token() -> None:
    with _tok_lock:
        _tok.update(value="", exp=0.0)


# ── الشبكة ──────────────────────────────────────────────────────────────
def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False                                 # بلا proxy ولا netrc من البيئة
    return s


def _check(url: str) -> str:
    try:
        return net_allow.fixed_base(url, (OAUTH_BASE, API_BASE))
    except net_allow.NetAllowError:
        raise DriveFatal("رابط مش من عناوين Google المسموحة — أوقفنا النداء", "bad_url") from None


def _send(method: str, url: str, **kw) -> requests.Response:
    _check(url)
    kw.setdefault("timeout", HTTP_TIMEOUT)
    try:
        with _session() as s:
            return s.request(method, url, allow_redirects=False, **kw)
    except requests.RequestException:
        raise DriveTransient("تعذّر الاتصال بـ Google (الإنترنت؟)", "network") from None


def _reason(r: requests.Response) -> str:
    try:
        e = (r.json() or {}).get("error")
    except ValueError:
        return ""
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        errs = e.get("errors") or []
        if errs and isinstance(errs[0], dict) and errs[0].get("reason"):
            return str(errs[0]["reason"])
        return str(e.get("status") or "")
    return ""


def _map(r: requests.Response) -> DriveError:
    why = _reason(r)
    if r.status_code == 401 or why == "invalid_grant":
        return DriveFatal("انقطع الربط مع درايف — اربط من جديد من الإعدادات", "auth")
    if why == "storageQuotaExceeded":
        return DriveFatal("درايف مليان — فضّي مكان أو كبّر المساحة، وبعدين «جرّب هلق»", "full")
    if why in ("accessNotConfigured", "SERVICE_DISABLED"):
        return DriveFatal("واجهة Google Drive API مش مفعّلة بمشروعك — فعّلها من Google Cloud", "api_disabled")
    if why == "invalid_client":
        return DriveFatal("Client ID أو Client secret غلط — راجعهم بالإعدادات", "not_configured")
    if r.status_code == 429 or why in ("rateLimitExceeded", "userRateLimitExceeded"):
        return DriveTransient("Google بتقلنا: طلبات كتير — منكمّل بعد شوي", "rate_limit")
    if r.status_code >= 500:
        return DriveTransient("Google مش متاحة هلأ — منعيد المحاولة", "google_down")
    if r.status_code == 404:
        return DriveNotFound("الملف مش موجود بدرايف", "not_found")
    if r.status_code == 403:
        return DriveFatal("Google رفضت الطلب (صلاحية) — اربط من جديد", "forbidden")
    return DriveError(f"Google رفضت الطلب (رمز {r.status_code})", "bad_request")


def _json(r: requests.Response) -> dict:
    try:
        d = r.json()
    except ValueError:
        raise DriveTransient("رد Google غير مفهوم", "bad_response") from None
    return d if isinstance(d, dict) else {}


# ── الربط بالرمز (device flow) ─────────────────────────────────────────
def device_start() -> dict:
    """بيطلب رمز من Google. بيرجّع للواجهة: user_code ورابط الصفحة والمهلة (device_code بيضل بالذاكرة)."""
    if not configured():
        raise DriveError("حط Client ID وClient secret أول", "not_configured")
    r = _send("POST", f"{OAUTH_BASE}/device/code", data={"client_id": client_id(), "scope": SCOPE})
    if r.status_code >= 300:
        raise _map(r)
    d = _json(r)
    if not d.get("device_code") or not d.get("user_code"):
        raise DriveTransient("Google ما رجّعت رمز", "bad_response")
    ttl = int(d.get("expires_in") or 1800)
    with _dev_lock:
        _device.clear()
        _device.update(device_code=str(d["device_code"]), user_code=str(d["user_code"]), exp=time.time() + ttl,
                       interval=max(2, int(d.get("interval") or 5)), next_at=0.0)
    return {"user_code": str(d["user_code"]), "verification_url": str(d.get("verification_url") or "https://www.google.com/device"),
            "expires_in": ttl, "interval": _device["interval"]}


def device_poll() -> dict:
    """نداء وحدة لـ Google: هل المالك خلّص؟ {state: pending|connected|denied|expired|idle}."""
    with _dev_lock:
        dev = dict(_device)
    if not dev:
        return {"state": "idle"}
    if time.time() > dev["exp"]:
        with _dev_lock:
            _device.clear()
        return {"state": "expired"}
    if time.time() < dev.get("next_at", 0):
        return {"state": "pending", "interval": dev["interval"]}
    r = _send("POST", f"{OAUTH_BASE}/token", data={"client_id": client_id(), "client_secret": _client_secret(),
                                                     "device_code": dev["device_code"], "grant_type": DEVICE_GRANT})
    why = _reason(r) if r.status_code >= 300 else ""
    if why in ("authorization_pending", "slow_down"):
        with _dev_lock:
            if why == "slow_down":
                _device["interval"] = _device.get("interval", 5) + 5
            _device["next_at"] = time.time() + _device.get("interval", 5)
        return {"state": "pending", "interval": _device.get("interval", 5)}
    if why == "access_denied":
        with _dev_lock:
            _device.clear()
        return {"state": "denied"}
    if why in ("expired_token", "invalid_grant"):
        with _dev_lock:
            _device.clear()
        return {"state": "expired"}
    if r.status_code >= 300:
        raise _map(r)
    d = _json(r)
    rt = str(d.get("refresh_token") or "")
    if not rt:
        raise DriveError("Google ما رجّعت إذن دائم — جرّب «اربط درايف» من جديد", "no_token")
    with _dev_lock:
        _device.clear()
    with _tok_lock:
        _tok.update(value=str(d.get("access_token") or ""), exp=time.time() + int(d.get("expires_in") or 3000))
    from datetime import datetime, timezone
    write_cfg(lambda c: (c.update(refresh_token=rt, connected_at=datetime.now(timezone.utc).isoformat(timespec="seconds")), c.pop("paused", None)))
    try:
        u = (about().get("user") or {})
        write_cfg(lambda c: c.update(email=str(u.get("emailAddress") or "")[:120], name=str(u.get("displayName") or "")[:80]))
    except DriveError:
        pass                                            # الإيميل للعرض بس
    return {"state": "connected"}


def access_token() -> str:
    with _tok_lock:
        if _tok["value"] and _tok["exp"] > time.time() + 60:
            return _tok["value"]
    if not connected():
        raise DriveFatal("درايف مش مربوط", "not_connected")
    r = _send("POST", f"{OAUTH_BASE}/token", data={"client_id": client_id(), "client_secret": _client_secret(),
                                                     "refresh_token": _refresh_token(), "grant_type": "refresh_token"})
    if r.status_code >= 300:
        raise _map(r)
    d = _json(r)
    tok = str(d.get("access_token") or "")
    if not tok:
        raise DriveTransient("Google ما رجّعت توكن", "bad_response")
    with _tok_lock:
        _tok.update(value=tok, exp=time.time() + int(d.get("expires_in") or 3000))
    return tok


def disconnect() -> None:
    """بنسحب الإذن عند Google (محاولة وحدة، الفشل ما بيوقفنا) وبنمسح الـ refresh token."""
    rt = _refresh_token()
    if rt:
        try:
            _send("POST", f"{OAUTH_BASE}/revoke", data={"token": rt}, timeout=10)
        except DriveError:
            pass
    forget_token()
    write_cfg(lambda c: [c.pop(k, None) for k in ("refresh_token", "email", "name", "connected_at", "paused")])


# ── نداءات Drive ────────────────────────────────────────────────────────
def _api(method: str, path: str, *, params=None, js=None, data=None, headers=None, url=None) -> requests.Response:
    """نداء مع التوكن. 401 مرة وحدة ← توكن جديد وإعادة."""
    for attempt in (1, 2):
        h = {"Authorization": f"Bearer {access_token()}", **(headers or {})}
        r = _send(method, url or f"{API_BASE}{path}", params=params, json=js, data=data, headers=h)
        if r.status_code == 401 and attempt == 1:
            forget_token()
            continue
        return r
    return r


def _ok(r: requests.Response) -> dict:
    if r.status_code >= 300:
        raise _map(r)
    return _json(r)


def about() -> dict:
    return _ok(_api("GET", "/drive/v3/about", params={"fields": "user(emailAddress,displayName),storageQuota(limit,usage)"}))


def _q(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def find_by_prop(prop: str, value: str) -> str | None:
    """أول ملف (مش بالسلة) عليه appProperties {prop: value}. drive.file بيدوّر بملفات الاستوديو بس."""
    q = f"appProperties has {{ key='{prop}' and value='{_q(value)}' }} and trashed = false"
    d = _ok(_api("GET", "/drive/v3/files", params={"q": q, "fields": "files(id)", "pageSize": 2, "spaces": "drive"}))
    files = d.get("files") or []
    return str(files[0]["id"]) if files and files[0].get("id") else None


def exists(file_id: str) -> bool:
    try:
        d = _ok(_api("GET", f"/drive/v3/files/{file_id}", params={"fields": "id,trashed"}))
    except DriveNotFound:
        return False
    return not d.get("trashed")


def create_folder(name: str, parent: str | None, key: str) -> str:
    meta = {"name": name, "mimeType": FOLDER_MIME, "appProperties": {"vp_folder": key}}
    if parent:
        meta["parents"] = [parent]
    d = _ok(_api("POST", "/drive/v3/files", params={"fields": "id"}, js=meta))
    return str(d["id"])


def rename(file_id: str, name: str) -> None:
    _ok(_api("PATCH", f"/drive/v3/files/{file_id}", params={"fields": "id"}, js={"name": name}))


def folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _multipart(meta: dict, body: bytes, mime: str) -> tuple[bytes, str]:
    b = "vp" + uuid.uuid4().hex
    head = (f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta, ensure_ascii=False)}\r\n"
            f"--{b}\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8")
    return head + body + f"\r\n--{b}--\r\n".encode(), f"multipart/related; boundary={b}"


def upload(path: Path, *, name: str, parent: str, key: str, mime: str, convert_to: str | None = None,
           file_id: str | None = None, session_url: str | None = None, on_session=None) -> str:
    """بيرفع ملف محلي: file_id موجود ← تحديث نفس الملف (درايف بيحتفظ بالنسخة القديمة بسجل النسخ)، وإلا ملف جديد.
    الكبير بالقطع: on_session(url) بيحفظ رابط الجلسة لحتى نكمّل من وين وقفنا لو انقطع النت. بيرجّع id الملف."""
    p = Path(path)
    size = p.stat().st_size
    meta: dict = {"name": name, "appProperties": {"vp_key": key}}
    if convert_to:
        meta["mimeType"] = convert_to
    if not file_id:
        meta["parents"] = [parent]
    method = "PATCH" if file_id else "POST"
    base = f"/upload/drive/v3/files/{file_id}" if file_id else "/upload/drive/v3/files"
    if size <= SIMPLE_MAX and not session_url:
        body, ctype = _multipart(meta, p.read_bytes(), mime)
        d = _ok(_api(method, base, params={"uploadType": "multipart", "fields": "id"}, data=body, headers={"Content-Type": ctype}))
        return str(d["id"])
    url, start = None, 0
    if session_url:
        try:
            url = _check(session_url)
            start = _resume_offset(url, size)
            if start is None:                                # الجلسة خلصت وانرفع الملف كامل
                return _finished_id(url, size)
        except DriveNotFound:
            url, start = None, 0                             # الجلسة انتهت ← بنبلّش من جديد
    if not url:
        r = _api(method, base, params={"uploadType": "resumable", "fields": "id"}, js=meta,
                 headers={"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)})
        if r.status_code >= 300:
            raise _map(r)
        url = r.headers.get("Location") or ""
        _check(url)                                          # رابط الجلسة لازم يكون على عنوان Google نفسه
        if on_session:
            on_session(url)
    with p.open("rb") as f:
        while True:
            f.seek(start)
            chunk = f.read(CHUNK)
            end = start + len(chunk) - 1
            r = _api("PUT", "", url=url, data=chunk, headers={"Content-Range": f"bytes {start}-{end}/{size}" if chunk else f"bytes */{size}"})
            if r.status_code in (200, 201):
                return str(_json(r)["id"])
            if r.status_code == 308:
                start = _range_end(r)
                continue
            if r.status_code in (404, 410):
                raise DriveTransient("جلسة الرفع انتهت — منبلّش الملف من جديد", "session_gone")
            raise _map(r)


def _range_end(r: requests.Response) -> int:
    rg = r.headers.get("Range") or ""                         # "bytes=0-1234"
    try:
        return int(rg.rsplit("-", 1)[1]) + 1
    except (IndexError, ValueError):
        return 0


def _resume_offset(url: str, size: int) -> int | None:
    r = _api("PUT", "", url=url, data=b"", headers={"Content-Range": f"bytes */{size}"})
    if r.status_code in (200, 201):
        return None
    if r.status_code == 308:
        return _range_end(r)
    if r.status_code in (404, 410):
        raise DriveNotFound("جلسة الرفع انتهت", "session_gone")
    raise _map(r)


def _finished_id(url: str, size: int) -> str:
    r = _api("PUT", "", url=url, data=b"", headers={"Content-Range": f"bytes */{size}"})
    return str(_ok(r)["id"])


def status() -> dict:
    """حالة الربط — بدون أي سر."""
    c = cfg()
    return {"configured": configured(), "connected": connected(), "client_id": client_id(),
            "email": str(c.get("email") or ""), "name": str(c.get("name") or ""), "connected_at": c.get("connected_at"),
            "auto": c.get("auto", True) is not False, "paused": str(c.get("paused") or ""),
            "connecting": bool(_device) and time.time() < _device.get("exp", 0)}


def disabled_env() -> bool:
    return os.environ.get("VIDPATTERN_NO_DRIVE") == "1"
