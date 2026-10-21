"""
تسجيل الدخول بفيسبوك وسحب الحسابات والإعلانات (Meta Marketing API) — قراءة فقط.

الفكرة: المالك بيعمل «تطبيق» مرة وحدة عند ميتا (App ID وApp Secret) ويحطهم بالواجهة، وبعدين بيضغط «سجّل دخول بفيسبوك».
بنسحب حساباته الإعلانية وإعلاناتها (ميتا بتعطينا مستوى الإعلان نفسه: اسمه ورقمه وحملته وصرفه)، وبنسجّل المطابق منها
بتسجيل الإعلانات (placements.py) تلقائياً — بدون ما نخمّن سيناريو إعلان.

قواعد أمان (ما بتنكسر):
  · الصلاحية الوحيدة: ads_read (قراءة). ما بنطلب ads_management: ما بنقدر ننشئ ولا نوقف ولا نصرف.
  · App Secret والتوكن بمخزن الأسرار بس (settings_io بينقلهم لمخزن أسرار الجهاز). ما بيرجعوا بأي ردّ ولا بيتسجّلوا ولا بيظهروا برسالة خطأ.
  · التوكن بترويسة Authorization (مش بالرابط). الاتصال بعناوين ميتا الثابتة بس (https).
  · حالة الدخول (state): موقّعة HMAC + رقم لمرة وحدة بالذاكرة + صلاحية 10 دقايق. بدونها الـ callback بينرفض
    (بيمنع إن حدا يرسل code تبع حسابه لجهازك).
  · رابط الإرجاع (redirect_uri) دايماً http://localhost:<المنفذ الفعلي> (مش من أي ترويسة طلب). النفق ملغى: بيفتح الاستوديو للإنترنت.
  · تطبيقات ميتا من نوع Business بتستعمل Facebook Login for Business: config_id بدل scope. وإذا ميتا رفضت، بنقبل لصق توكن (بنفس الفحوصات).
  · التوكن طويل المدى حوالي 60 يوم؛ بنعرض الأيام الباقية وبننبّه، ولما يخلص لازم تسجّل دخول من جديد.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

import config

GRAPH_VERSION = "v26.0"
AUTH_BASE = "https://www.facebook.com"
GRAPH_BASE = "https://graph.facebook.com"
SCOPES = "ads_read"
STATE_TTL_SEC = 600
HTTP_TIMEOUT = 30
PAGE_LIMIT = 200
MAX_ADS = 600
CALLBACK_PATH = "/api/ads/meta/callback"
_pending: dict[str, float] = {}                     # nonce ← وقت الانتهاء (بالذاكرة: callback واحد لكل start)
_lock = threading.Lock()

ACCOUNT_STATUS = {1: "شغّال", 2: "معطّل", 3: "عليه مستحقات غير مدفوعة", 7: "قيد مراجعة المخاطر", 8: "قيد التسوية",
                  9: "فترة سماح", 100: "قيد الإغلاق", 101: "مغلق", 201: "نشط", 202: "مغلق"}
AD_STATUS_TO_PLACEMENT = {"ACTIVE": "published", "PAUSED": "paused", "CAMPAIGN_PAUSED": "paused", "ADSET_PAUSED": "paused",
                          "ARCHIVED": "ended", "DELETED": "ended"}


class MetaError(Exception):
    """رسالة عربية جاهزة للعرض (بلا مفاتيح ولا توكنات)."""

    def __init__(self, message: str, code: str = "meta_error"):
        super().__init__(message)
        self.code = code


# ── الإعدادات والأسرار ──────────────────────────────────────────────────
def _cfg() -> dict:
    try:
        import settings_io
        return ((settings_io.load().get("ADS") or {}).get("META") or {})
    except Exception:
        return {}


def _write(mutator) -> None:
    import settings_io
    data = settings_io.load()
    ads = data.setdefault("ADS", {}).setdefault("META", {})
    mutator(ads)
    settings_io.save(data)


def app_id() -> str:
    return str(_cfg().get("app_id") or "").strip()


def _app_secret() -> str:
    return str(_cfg().get("app_secret") or "").strip()


def _token() -> str:
    return str(_cfg().get("access_token") or "").strip()


def configured() -> bool:
    return bool(app_id() and _app_secret())


def set_app(app_id_value: str, app_secret_value: str, config_id: str | None = None) -> None:
    """config_id: رقم «الإعداد» من Facebook Login for Business (تطبيقات Business بتحتاجه بدل scope). None = ما نلمسه، "" = نمسحه."""
    a, s = str(app_id_value or "").strip(), str(app_secret_value or "").strip()
    if not a.isdigit() or not 8 <= len(a) <= 24:
        raise MetaError("App ID أرقام بس (حوالي 15 رقم) — خدو من لوحة تطبيقك عند ميتا", "bad_app_id")
    if not s or len(s) > 128 or any(c.isspace() for c in s):
        raise MetaError("App Secret غير صالح — انسخو من إعدادات التطبيق الأساسية بدون مسافات", "bad_secret")
    cfg_id = None if config_id is None else str(config_id).strip()
    if cfg_id and (not cfg_id.isdigit() or len(cfg_id) > 24):
        raise MetaError("Configuration ID أرقام بس — خدو من Facebook Login for Business ← Configurations", "bad_config_id")

    def m(ads):
        if ads.get("app_id") != a:                   # تطبيق مختلف ← الدخول القديم ما بيصلح
            for k in ("access_token", "token_expires_at", "never_expires", "user_id", "user_name", "config_id"):
                ads.pop(k, None)
        ads["app_id"], ads["app_secret"] = a, s
        if cfg_id is not None:
            if cfg_id:
                ads["config_id"] = cfg_id
            else:
                ads.pop("config_id", None)
    _write(m)


def config_id() -> str:
    return str(_cfg().get("config_id") or "").strip()


def redirect_base() -> str:
    """بس localhost على المنفذ الفعلي (VP_PORT بيحطه run_web.py). النفق ملغى: بيفتح الاستوديو للإنترنت (راجع web/guard.py)."""
    port = os.environ.get("VP_PORT", "")
    return f"http://localhost:{port if port.isdigit() else 8000}"


def redirect_uri() -> str:
    return redirect_base() + CALLBACK_PATH


# ── حالة الدخول (state) ─────────────────────────────────────────────────
def _state_key() -> bytes:
    import secrets_store
    k = secrets_store.get_secret("ads_meta_state_key")
    if not k:
        k = secrets.token_urlsafe(32)
        secrets_store.set_secret("ads_meta_state_key", k)
    return k.encode()


def make_state(now: float | None = None) -> str:
    nonce = secrets.token_urlsafe(16)
    t = int(now if now is not None else time.time())
    body = f"{nonce}.{t}"
    sig = hmac.new(_state_key(), body.encode(), hashlib.sha256).hexdigest()[:32]
    with _lock:
        for k in [k for k, exp in _pending.items() if exp < time.time()]:
            _pending.pop(k, None)
        _pending[nonce] = t + STATE_TTL_SEC
    return f"{body}.{sig}"


def check_state(state: str, now: float | None = None) -> None:
    """يتحقق من التوقيع والصلاحية، ويستهلك الرقم (مرة وحدة). بيرمي MetaError برمز ثابت."""
    try:
        nonce, t, sig = str(state or "").split(".")
        t_i = int(t)
    except ValueError:
        raise MetaError("حالة الدخول غير صالحة", "state_invalid") from None
    good = hmac.new(_state_key(), f"{nonce}.{t}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, good):
        raise MetaError("حالة الدخول مزوّرة أو انتهت صلاحيتها", "state_invalid")
    cur = now if now is not None else time.time()
    if cur - t_i > STATE_TTL_SEC:
        raise MetaError("انتهت مهلة تسجيل الدخول (10 دقايق) — جرّب من جديد", "state_expired")
    with _lock:
        exp = _pending.pop(nonce, None)
    if exp is None:
        raise MetaError("طلب الدخول هاد ما بدأ من هون أو انستعمل قبل (ما في إعادة استخدام)", "state_unknown")


def authorize_url() -> str:
    if not configured():
        raise MetaError("حط App ID وApp Secret أول", "not_configured")
    q = {"client_id": app_id(), "redirect_uri": redirect_uri(), "state": make_state(), "response_type": "code"}
    if config_id():                                          # Facebook Login for Business: config_id بيحلّ محل scope
        q.update(config_id=config_id(), override_default_response_type="true")
    else:
        q["scope"] = SCOPES
    return f"{AUTH_BASE}/{GRAPH_VERSION}/dialog/oauth?{urlencode(q)}"


# ── نداءات Graph ────────────────────────────────────────────────────────
def _map_error(r: requests.Response) -> MetaError:
    try:
        e = (r.json() or {}).get("error") or {}
    except Exception:
        e = {}
    code, sub = e.get("code"), e.get("error_subcode")
    if code in (190, 102) or sub in (458, 460, 463, 467):
        return MetaError("دخولك بفيسبوك انتهى أو انلغى — سجّل دخول من جديد", "token_expired")
    if code in (10,) or (isinstance(code, int) and 200 <= code <= 299):
        return MetaError("ميتا ما أعطتنا صلاحية قراءة الإعلانات — تأكد إنك أعطيت ads_read وإن عندك دور بالتطبيق", "permission")
    if code in (4, 17, 32, 613, 80000, 80003, 80004):
        return MetaError("ميتا بتقلنا: طلبات كتير — جرّب بعد دقايق", "rate_limit")
    if code == 100:
        return MetaError("ميتا رفضت الطلب (مدخل غير صالح) — تأكد من الحساب", "bad_request")
    if r.status_code >= 500:
        return MetaError("ميتا مش متاحة هلأ — جرّب بعدين", "meta_down")
    return MetaError(f"ميتا رفضت الطلب (رمز {code if code is not None else r.status_code})", "meta_error")


def _graph(method: str, path: str, params: dict | None = None, *, token: str | None = None, timeout: int = HTTP_TIMEOUT):
    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.request(method, url, params=params or {}, headers=headers, timeout=timeout)
    except requests.RequestException:
        raise MetaError("تعذّر الاتصال بميتا (الإنترنت؟)", "network") from None
    if r.status_code >= 300:
        raise _map_error(r)
    try:
        return r.json()
    except ValueError:
        raise MetaError("رد ميتا غير مفهوم", "bad_response") from None


def _paged(path: str, params: dict, token: str, limit: int = MAX_ADS) -> list[dict]:
    out: list[dict] = []
    p = {**params, "limit": PAGE_LIMIT}
    data = _graph("GET", path, p, token=token)
    while True:
        out += [x for x in (data.get("data") or []) if isinstance(x, dict)]
        nxt = ((data.get("paging") or {}).get("next") or "")
        if not nxt or len(out) >= limit:
            break
        if not nxt.startswith(GRAPH_BASE + "/"):                 # ما نتبع رابط مش من ميتا (ومعو التوكن)
            break
        try:
            r = requests.get(nxt, headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)
        except requests.RequestException:
            raise MetaError("تعذّر الاتصال بميتا (الإنترنت؟)", "network") from None
        if r.status_code >= 300:
            raise _map_error(r)
        data = r.json()
    return out[:limit]


# ── الدخول وتبديل الكود بتوكن ───────────────────────────────────────────
UPGRADE_BELOW_DAYS = 30                       # توكن أقصر من هيك بنحاول نطوّله (fb_exchange_token)


def _exchange_code(code: str) -> str:
    d = _graph("GET", "oauth/access_token", {"client_id": app_id(), "redirect_uri": redirect_uri(),
                                              "client_secret": _app_secret(), "code": code})
    tok = str(d.get("access_token") or "")
    if not tok:
        raise MetaError("ميتا ما رجّعت توكن", "no_token")
    return tok


def _has_ads_read(dbg: dict) -> bool:
    if "ads_read" in (dbg.get("scopes") or []):
        return True
    return any((g or {}).get("scope") == "ads_read" for g in (dbg.get("granular_scopes") or []))


def _finalize(token: str) -> dict:
    """يتحقق من التوكن (تطبيقنا + صالح + ads_read)، يطوّله إذا قصير، يقرا اسم المستخدم، ويحفظه بمخزن الأسرار.
    توكن System User (expires_at=0) ما بينتهي: بيتخزّن كما هو وبتبقى never_expires."""
    dbg = (_graph("GET", "debug_token", {"input_token": token}, token=f"{app_id()}|{_app_secret()}").get("data") or {})
    if str(dbg.get("app_id")) != app_id() or not dbg.get("is_valid"):
        raise MetaError("التوكن مش من تطبيقك أو مش صالح — أوقفنا الدخول", "token_mismatch")
    if not _has_ads_read(dbg):
        raise MetaError("التوكن ما فيه صلاحية ads_read — تأكد من إعداد Facebook Login for Business (أو من صلاحيات التوكن) وجرّب من جديد", "no_scope")
    try:
        exp_at = int(dbg.get("expires_at") or 0)
    except (TypeError, ValueError):
        exp_at = 0
    ttl = None if exp_at == 0 else max(0, exp_at - int(time.time()))
    if ttl is not None and ttl < UPGRADE_BELOW_DAYS * 86400:
        try:
            long_ = _graph("GET", "oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": app_id(),
                                                          "client_secret": _app_secret(), "fb_exchange_token": token})
            ltok = str(long_.get("access_token") or "")
            if ltok:
                token, ttl = ltok, int(long_.get("expires_in") or 60 * 86400)
        except MetaError:
            pass                                      # نظل على التوكن الأصلي (بدون تطويل) — الأيام الباقية بتنعرض صح
    try:
        me = _graph("GET", "me", {"fields": "id,name"}, token=token)
    except MetaError as e:
        if e.code in ("token_expired", "network"):
            raise
        me = {}                                       # بعض أنواع التوكن ما بتقرا /me: الاسم اختياري
    exp = None if ttl is None else (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(timespec="seconds")

    def m(ads):
        ads.update(access_token=token, user_id=str(me.get("id") or ""), user_name=str(me.get("name") or "")[:80])
        if exp is None:
            ads.pop("token_expires_at", None)
            ads["never_expires"] = True
        else:
            ads["token_expires_at"] = exp
            ads.pop("never_expires", None)
    _write(m)
    return status()


def complete_login(code: str, state: str) -> dict:
    """نهاية الدخول: تحقق حالة ← تبديل الكود ← تحقق التوكن وحفظه."""
    check_state(state)
    if not configured():
        raise MetaError("حط App ID وApp Secret أول", "not_configured")
    if not code:
        raise MetaError("ما وصل code من ميتا", "no_code")
    return _finalize(_exchange_code(code))


def set_token(token: str) -> dict:
    """طريق بديل: لصق توكن جاهز (من أداة ميتا للتوكنات أو System User من إعدادات البزنس). نفس الفحوصات."""
    t = str(token or "").strip()
    if not configured():
        raise MetaError("حط App ID وApp Secret أول", "not_configured")
    if not 20 <= len(t) <= 600 or any(c.isspace() for c in t) or "|" in t:
        raise MetaError("التوكن غير صالح — انسخو كامل بدون مسافات", "bad_token")
    return _finalize(t)


def disconnect() -> None:
    tok = _token()
    if tok:
        try:                                              # بنسحب صلاحية التطبيق عند ميتا (محاولة وحدة، الفشل ما بيوقفنا)
            requests.delete(f"{GRAPH_BASE}/{GRAPH_VERSION}/me/permissions", headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        except requests.RequestException:
            pass
    _write(lambda ads: [ads.pop(k, None) for k in ("access_token", "token_expires_at", "never_expires", "user_id", "user_name")])


def clear_app() -> None:
    disconnect()
    _write(lambda ads: [ads.pop(k, None) for k in ("app_id", "app_secret", "config_id")])


def status() -> dict:
    """حالة الربط — بدون أي سر. days_left بيتحسب من تاريخ انتهاء التوكن."""
    c = _cfg()
    exp = str(c.get("token_expires_at") or "")
    days = None
    if exp:
        try:
            days = (datetime.fromisoformat(exp) - datetime.now(timezone.utc)).total_seconds() / 86400
        except ValueError:
            days = None
    never = bool(c.get("never_expires"))
    connected = bool(_token()) and (never or days is None or days > 0)
    return {"configured": configured(), "app_id": app_id(), "config_id": config_id(), "redirect_uri": redirect_uri(), "connected": connected,
            "never_expires": never and bool(_token()),
            "user_name": str(c.get("user_name") or ""), "expires_at": exp or None,
            "days_left": None if days is None else max(0, int(days)), "expired": bool(_token()) and not never and days is not None and days <= 0,
            "expiring_soon": connected and not never and days is not None and days < 7, "scope": SCOPES, "graph_version": GRAPH_VERSION}


def _need_token() -> str:
    t = _token()
    if not t:
        raise MetaError("لسا ما سجّلت دخول بفيسبوك", "not_connected")
    s = status()
    if s["expired"]:
        raise MetaError("دخولك بفيسبوك انتهى (60 يوم) — سجّل دخول من جديد", "token_expired")
    return t


# ── الحسابات والإعلانات ─────────────────────────────────────────────────
def accounts() -> list[dict]:
    rows = _paged("me/adaccounts", {"fields": "id,account_id,name,account_status,currency"}, _need_token(), limit=100)
    return [{"id": str(r.get("id") or ""), "account_id": str(r.get("account_id") or ""), "name": str(r.get("name") or "")[:80],
             "currency": str(r.get("currency") or "")[:8],
             "status_code": r.get("account_status"), "status": ACCOUNT_STATUS.get(r.get("account_status"), "غير معروف")}
            for r in rows if str(r.get("id") or "").startswith("act_")]


def ads(account: str, days: int = 30) -> list[dict]:
    """إعلانات الحساب (آخر days يوم) مع الصرف. الصرف من insights على مستوى الإعلان."""
    import re
    if not re.fullmatch(r"act_\d{5,25}", str(account or "")):
        raise MetaError("رقم الحساب الإعلاني غير صالح (act_…)", "bad_account")
    days = max(1, min(int(days), 90))
    tok = _need_token()
    since = int(time.time()) - days * 86400
    rows = _paged(f"{account}/ads", {"fields": "id,name,effective_status,created_time,updated_time,campaign{id,name},adset{id,name}",
                                     "filtering": json.dumps([{"field": "updated_time", "operator": "GREATER_THAN", "value": since}])}, tok)
    spend: dict[str, float] = {}
    try:
        ins = _paged(f"{account}/insights", {"level": "ad", "fields": "ad_id,spend", "date_preset": "last_90d" if days > 30 else "last_30d"}, tok, limit=1000)
        for r in ins:
            try:
                spend[str(r.get("ad_id"))] = round(float(r.get("spend") or 0), 2)
            except (TypeError, ValueError):
                continue
    except MetaError as e:
        if e.code in ("token_expired", "not_connected"):
            raise                                           # الصرف اختياري: غيره من الأخطاء ما بيوقف السحب
    out = []
    for r in rows:
        aid = str(r.get("id") or "")
        camp, adset = (r.get("campaign") or {}), (r.get("adset") or {})
        out.append({"ad_id": aid, "ad_name": str(r.get("name") or "")[:200], "effective_status": str(r.get("effective_status") or ""),
                    "created": str(r.get("created_time") or "")[:10], "campaign_id": str(camp.get("id") or ""),
                    "campaign_name": str(camp.get("name") or "")[:120], "adset_name": str(adset.get("name") or "")[:120],
                    "spend": spend.get(aid)})
    return out


def ad_url(account: str, ad_id: str) -> str:
    num = str(account).removeprefix("act_")
    return f"https://adsmanager.facebook.com/adsmanager/manage/ads?act={num}&selected_ad_ids={ad_id}"


# ── المزامنة مع تسجيل الإعلانات ─────────────────────────────────────────
def _entry_from_ad(account: dict, a: dict) -> dict:
    return {"platform": "meta", "source": "facebook", "status": AD_STATUS_TO_PLACEMENT.get(a["effective_status"], "published"),
            "ad_account_id": account["id"], "ad_account_name": account.get("name", ""), "currency": account.get("currency", ""),
            "campaign_name": a["campaign_name"], "campaign_id": a["campaign_id"], "adset_name": a["adset_name"],
            "ad_name": a["ad_name"], "ad_id": a["ad_id"], "ad_url": ad_url(account["id"], a["ad_id"]), "published_at": a["created"]}


def match_script(ad_name: str) -> str | None:
    """script_id من اسم الإعلان (الخانة الخامسة VP-…) أو من تسجيل سابق بنفس الاسم. ما بنخمّن أبداً."""
    import adname
    import placements
    return adname.parse(ad_name)["script_id"] or placements.script_for(ad_name)


def preview(account: str, days: int = 30) -> dict:
    """الإعلانات مع علامة «مطابق لسيناريو» — بدون كتابة أي شي."""
    rows = ads(account, days)
    for r in rows:
        r["script_id"] = match_script(r["ad_name"])
    return {"account": account, "ads": rows, "matched": sum(1 for r in rows if r["script_id"]), "total": len(rows)}


def sync(account: str, days: int = 30) -> dict:
    """يسجّل الإعلانات المطابقة لسيناريو بتسجيل الإعلانات (مصدر facebook). بالمكرر: بيحدّث الحالة والصرف بس ما بيلمس ملاحظاتك."""
    import placements
    acc = next((a for a in accounts() if a["id"] == account), None) or {"id": account, "name": "", "currency": ""}
    added = updated = unmatched = skipped = 0
    for a in ads(account, days):
        sid = match_script(a["ad_name"])
        if not sid:
            unmatched += 1
            continue
        entry = _entry_from_ad(acc, a)
        try:
            cur = next((e for e in placements.list_for(sid) if e.get("platform") == "meta" and e.get("ad_id") == a["ad_id"]), None)
            if cur:
                placements.update(sid, cur["id"], {k: entry[k] for k in ("status", "campaign_name", "adset_name", "ad_name", "ad_url")})
                updated += 1
            else:
                placements.add(sid, entry)
                added += 1
        except placements.PlacementError:
            skipped += 1
    return {"added": added, "updated": updated, "unmatched": unmatched, "skipped": skipped}
