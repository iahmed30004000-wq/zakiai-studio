"""
المحطة ١١: الإطلاق — VidPattern ↔ العمليات (عقد vp-ops.v1).

الجهاز هو اللي بيبدأ الاتصال (سحب/رفع من الجهاز؛ السيرفر ما بينادي الجهاز أبداً).
توكنين بأقل صلاحية بمخزن أسرار ويندوز:
    crm_token          (vp:read)    حالة الطلب
    crm_token_launch   (vp:launch)  إنشاء الطلب وإلغاؤه قبل الموافقة — بس
ولا توكن بيقدر يوافق على فلوس. الموافقة على أي ميزانية بموقع العمليات فقط.

قواعد:
  · سؤال واحد: «منتج شغّال» (active) أو «تست» (test). طلب واحد. ما بيتكرر لنفس (vp_id, mode).
  · ما في بيانات زبائن شخصية بأي اتجاه (السيناريو، الترجمة، صورة مصغّرة، بيانات مجمّعة بس).
  · أخطاء برموز ثابتة ورسائل عربية.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

import config
import pattern_store
import studio_state
import timeline

MODES = {"active": "منتج شغّال", "test": "تست"}
_DONE = ("rejected", "failed", "cancelled")
_CANCELLABLE = ("received", "preparing", "awaiting_approval")
STATUS_LABEL = {"received": "استُلم", "preparing": "قيد التجهيز", "awaiting_approval": "بانتظار موافقتك",
                "launched": "انطلق", "rejected": "مرفوض", "failed": "فشل", "cancelled": "أُلغي"}
_STATE_OF = {"received": "running", "preparing": "running", "awaiting_approval": "awaiting_choice",
             "launched": "approved", "rejected": "failed", "failed": "failed", "cancelled": "failed"}
LAUNCH_REQUIRED = ["ops_product_id", "ops_store_id", "product_code", "country", "landing_page"]
CONNECT_TIMEOUT, READ_TIMEOUT, UPLOAD_TIMEOUT = 10, 30, 600
V = "/api/v1/vp"


class LaunchError(Exception):
    """رسالة عربية جاهزة للعرض. `.code` رمز ثابت."""

    def __init__(self, message: str, code: str = "launch_error", http: int | None = None):
        super().__init__(message)
        self.code, self.http = code, http


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── التوكن والعميل ──────────────────────────────────────────────────────
def _secret(name: str) -> str | None:
    try:
        import secrets_store
        return secrets_store.get_secret(name) or None
    except Exception:
        return None


def launch_token() -> str | None:
    return _secret("crm_token_launch")


def read_token() -> str | None:
    return _secret("crm_token")


def _base() -> str:
    import crm
    return crm.validate_base_url(crm.base_url() or "")


def _call(method: str, path: str, token: str | None, need: str, **kw):
    if not token:
        raise LaunchError(f"ما في توكن {need} — حطّه بالإعدادات (OMS)", "no_token")
    try:
        base = _base()
    except Exception as e:
        raise LaunchError(str(e) or "عنوان الـ OMS غير مضبوط", "not_configured")
    try:
        r = requests.request(method, base + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                             timeout=kw.pop("timeout", (CONNECT_TIMEOUT, READ_TIMEOUT)), allow_redirects=False, **kw)
    except requests.exceptions.SSLError:
        raise LaunchError("شهادة HTTPS للعمليات غير صالحة", "tls")
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        raise LaunchError("تعذّر الوصول للعمليات (شبكة أو السيرفر مطفي) — الفيديو ما انبعت", "offline")
    if 300 <= r.status_code < 400:
        raise LaunchError("العمليات حوّلت الطلب — تحقق من العنوان", "redirect", r.status_code)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        msg = body.get("message") or {401: "العمليات رفضت التوكن", 403: "التوكن ما إله صلاحية لهالعملية",
                                      404: "الطلب غير موجود"}.get(r.status_code, f"العمليات رفضت الطلب (HTTP {r.status_code})")
        raise LaunchError(msg, body.get("code") or f"http_{r.status_code}", r.status_code)
    return body


# ── التسجيل المحلي (منع التكرار + آخر حالة) ─────────────────────────────
def record_path(vp_id: str) -> Path:
    return Path(config.LIBRARY_DIR) / "launches" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', vp_id)}.json"


def records(vp_id: str) -> dict:
    p = record_path(vp_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_record(vp_id: str, mode: str, rec: dict) -> None:
    all_ = records(vp_id)
    all_[mode] = rec
    p = record_path(vp_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(all_, ensure_ascii=False, indent=2), encoding="utf-8")


# ── بناء الطلب ──────────────────────────────────────────────────────────
def _brief(script: dict) -> dict:
    import review_script
    return review_script.load_brief(script) or {}


def missing_fields(brief: dict) -> list[str]:
    import brief as brief_mod
    labels = {k: l for k, l, _t, _g in brief_mod.FIELDS}
    return [labels.get(k, k) for k in LAUNCH_REQUIRED if not str(brief.get(k) or "").strip()]


def to_srt(cues: list[dict]) -> str:
    def ts(ms):
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{ts(c['start_ms'])} --> {ts(c['end_ms'])}\n{c['text']}\n" for i, c in enumerate(cues, 1))


def final_file(stem: str, tl: dict) -> Path:
    rec = (tl.get("render") or {}).get("final")
    p = (Path(config.LIBRARY_DIR) / rec["file"]) if rec else None
    if not p or not p.exists():
        raise LaunchError("ما في تصدير نهائي — صدّر الفيديو أولاً (محطة 10)", "no_export")
    return p


def thumbnail_b64(video: Path) -> str:
    r = subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise LaunchError("تعذّر استخراج الصورة المصغّرة", "thumbnail")
    return base64.b64encode(r.stdout).decode()


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hook_meta(script: dict, vp_id: str) -> dict:
    """حقلان اختياريان بعقد الـ OMS لنسخ الهوك: hook_group (معرّف الإعلان الأساسي) وhook_index (رقم الهوك).
    الأساسي اللي إله بدائل بيحمل نفس المجموعة برقم هوكه؛ السيناريو العادي بلا حقول."""
    import script_hooks
    hi = (script.get("_meta") or {}).get("hook_of") or {}
    if hi.get("hook_id"):
        return {"hook_group": hi.get("base_script_id") or "", "hook_index": int(str(hi["hook_id"]).lstrip("hH") or 0)}
    if script_hooks.has_alternatives(script):
        return {"hook_group": vp_id, "hook_index": int(script_hooks.main_id(script).lstrip("h") or 1)}
    return {}


def build_meta(script_path, mode: str, *, with_thumbnail: bool = True) -> tuple[dict, Path]:
    import characters
    import montage
    path = Path(script_path)
    stem = path.stem
    if mode not in MODES:
        raise LaunchError("الوضع: active أو test", "invalid_meta")
    tl = timeline.load(stem)
    if not tl:
        raise LaunchError("ما في خط زمني", "no_timeline")
    script = json.loads(path.read_text(encoding="utf-8"))
    meta_s = script.get("_meta") or {}
    vp_id = tl.get("script_id") or meta_s.get("script_id")
    if not vp_id:
        raise LaunchError("السيناريو بلا معرّف VP", "invalid_meta")
    b = _brief(script)
    miss = missing_fields(b)
    if miss:
        raise LaunchError("بريف المنتج ناقص للإطلاق: " + "، ".join(miss), "invalid_meta")
    video = final_file(stem, tl)
    info = montage.probe(video)
    if (info.get("width"), info.get("height")) != montage.FINAL_SIZE:
        raise LaunchError(f"الفيديو {info.get('width')}x{info.get('height')} — لازم 1080x1920", "video_invalid")
    dur = tl["voice"]["duration_ms"] / 1000
    if not config.SCRIPT_MIN_SEC <= dur <= config.SCRIPT_MAX_SEC:
        raise LaunchError(f"المدة {dur:.1f}ث خارج {config.SCRIPT_MIN_SEC}–{config.SCRIPT_MAX_SEC}", "video_invalid")
    max_mb = int(getattr(config, "LAUNCH_MAX_MB", 500))
    if video.stat().st_size > max_mb * 1024 * 1024:
        raise LaunchError(f"الفيديو أكبر من {max_mb}MB", "video_too_large")

    pat = pattern_store.load_any(str(meta_s.get("pattern_id") or "")) or {}
    cur = characters.chosen(stem)
    meta = {
        "vp_id": vp_id, "product_id": str(b["ops_product_id"]).strip(), "store_id": str(b["ops_store_id"]).strip(),
        "country": b["country"], "mode": mode, "framework": pat.get("framework") or "",
        "pattern_id": meta_s.get("pattern_id") or "", "hook_line": script.get("hook_line") or "",
        "dialect": b.get("dialect") or "", "duration_sec": round(dur, 2),
        "character_id": (cur or {}).get("character_id"),
        "script_text": "\n".join((s.get("voiceover") or "").strip() for s in script.get("scenes", []) if (s.get("voiceover") or "").strip()),
        "captions_srt": to_srt(montage.build_cues(tl)),
        "checksum_sha256": _sha256(video),
    }
    meta.update(hook_meta(script, vp_id))
    if with_thumbnail:
        meta["thumbnail"] = thumbnail_b64(video)
    for k in ("framework", "pattern_id", "hook_line", "dialect", "script_text", "captions_srt"):
        if not str(meta[k]).strip():
            raise LaunchError(f"حقل الطلب «{k}» فاضي — ما بينبعت ناقص", "invalid_meta")
    return meta, video


# ── الإرسال والحالة والإلغاء ────────────────────────────────────────────
def _sync_state(stem: str, status: str, note: str) -> None:
    st = _STATE_OF.get(status)
    if st:
        studio_state.set_state(stem, 11, st, note)


def send(script_path, mode: str, *, confirm: bool = False) -> dict:
    """يبعت طلب إطلاق واحد. ما بيتكرر لنفس (vp_id, mode)."""
    path = Path(script_path)
    stem = path.stem
    if not confirm:
        raise LaunchError("أكّد الإطلاق صراحةً", "confirm_required")
    ok, why = studio_state.can_start(stem, 11)
    if not ok:
        raise LaunchError(why, "station_blocked")
    meta, video = build_meta(path, mode)
    prev = records(meta["vp_id"]).get(mode)
    if prev and prev.get("status") not in _DONE:
        raise LaunchError(f"هالفيديو انبعت أصلاً بوضع «{MODES[mode]}» (الحالة: {STATUS_LABEL.get(prev.get('status'), prev.get('status'))}) — ما بينبعت مرتين",
                          "duplicate_request")
    with video.open("rb") as vf:
        r = _call("POST", f"{V}/launch-requests", launch_token(), "vp:launch",
                  files={"video": (f"{meta['vp_id']}.mp4", vf, "video/mp4")}, data={"meta": json.dumps(meta, ensure_ascii=False)},
                  timeout=(CONNECT_TIMEOUT, UPLOAD_TIMEOUT))
    rid, status = r.get("request_id"), r.get("status")
    if not rid or status not in STATUS_LABEL:
        raise LaunchError("رد العمليات غير مفهوم (بلا request_id/status)", "bad_response")
    _save_record(meta["vp_id"], mode, {"request_id": rid, "status": status, "sent_at": _now(), "checksum": meta["checksum_sha256"],
                                       "ops_url": r.get("ops_url"), "reason": r.get("reason")})
    _sync_state(stem, status, f"{MODES[mode]}: {STATUS_LABEL[status]}")
    return {"mode": mode, "request_id": rid, "status": status, "label": STATUS_LABEL[status]}


def refresh(script_path, mode: str) -> dict:
    stem = Path(script_path).stem
    tl = timeline.load(stem) or {}
    vp_id = tl.get("script_id") or ""
    rec = records(vp_id).get(mode)
    if not rec:
        raise LaunchError("ما في طلب مرسل بهالوضع", "not_found")
    r = _call("GET", f"{V}/launch-requests/{rec['request_id']}", read_token(), "vp:read")
    status = r.get("status")
    if status not in STATUS_LABEL:
        raise LaunchError("حالة غير معروفة من العمليات", "bad_response")
    rec.update(status=status, reason=r.get("reason"), error_code=r.get("error_code"), ops_url=r.get("ops_url") or rec.get("ops_url"),
               campaign_id=r.get("campaign_id"), adset_id=r.get("adset_id"), ad_id=r.get("ad_id"),
               landing_page_id=r.get("landing_page_id"), checked_at=_now())
    _save_record(vp_id, mode, rec)
    _sync_state(stem, status, f"{MODES[mode]}: {STATUS_LABEL[status]}" + (f" — {r['reason']}" if r.get("reason") else ""))
    return rec


def cancel(script_path, mode: str) -> dict:
    stem = Path(script_path).stem
    tl = timeline.load(stem) or {}
    vp_id = tl.get("script_id") or ""
    rec = records(vp_id).get(mode)
    if not rec:
        raise LaunchError("ما في طلب مرسل بهالوضع", "not_found")
    if rec.get("status") not in _CANCELLABLE:
        raise LaunchError(f"ما بينلغى بحالة «{STATUS_LABEL.get(rec.get('status'), rec.get('status'))}» — الإلغاء قبل الموافقة بس", "cannot_cancel")
    _call("POST", f"{V}/launch-requests/{rec['request_id']}/cancel", launch_token(), "vp:launch")
    rec.update(status="cancelled", checked_at=_now())
    _save_record(vp_id, mode, rec)
    _sync_state(stem, "cancelled", f"{MODES[mode]}: أُلغي")
    return rec


def info(script_path) -> dict:
    """جاهزية الإطلاق + طلبات سابقة — بلا إرسال."""
    path = Path(script_path)
    stem = path.stem
    tl = timeline.load(stem) or {}
    script = json.loads(path.read_text(encoding="utf-8"))
    b = _brief(script)
    problems = []
    rf = (tl.get("render") or {}).get("final")
    if not rf or not (Path(config.LIBRARY_DIR) / rf["file"]).exists():
        problems.append("ما في تصدير نهائي (محطة 10)")
    problems += [f"بريف المنتج ناقص: {m}" for m in missing_fields(b)]
    if not launch_token():
        problems.append("ما في توكن vp:launch بالإعدادات")
    try:
        _base()
    except Exception:
        problems.append("عنوان العمليات غير مضبوط")
    vp_id = tl.get("script_id") or (script.get("_meta") or {}).get("script_id") or ""
    return {"vp_id": vp_id, "modes": MODES, "status_labels": STATUS_LABEL, "problems": problems,
            "records": records(vp_id) if vp_id else {}, "export": rf, "read_token_set": bool(read_token()),
            "launch_token_set": bool(launch_token()), "cancellable": list(_CANCELLABLE)}
