"""
مزامنة المكتبة للأعلى — نسخة للقراءة فقط بترتفع للـ OMS عشان مركز الذكاء يقراها
والجهاز مطفي. الرفع بيصير بس لما يتغيّر المحتوى (hash).

اللي بيرتفع: الأنماط + خصائصها الأساسية + نتائج الأدلة (تجميعية).
اللي ما بيرتفع أبداً: نصوص الفيديوهات الخام (مخطط المشاهد فيه مقاطع تعليق صوتي
مشتقة)، اللقطات، الفيديوهات والأصول، أي بيانات زبائن، والأسرار. القائمة بيضاء
(allowlist): أي حقل جديد بالنمط ما بيرتفع إلا إذا انضاف هون عن قصد.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import config
import settings_io

LIBRARY_PATH = "/api/vidpattern/library"
SCHEMA_VERSION = 1

# حقول النمط المسموح ترفعها (مسطّحة)
PATTERN_FIELDS = (
    "pattern_name", "framework", "framework_secondary", "one_line_summary",
    "product_category", "target_audience", "dialect_or_language", "dialect_sub",
    "emotional_arc", "product_entry_sec", "product_entry_style", "proof_mechanism",
    "objection_handled", "cta", "pacing", "visual_language", "why_it_works",
    "weak_points", "production_complexity", "best_for", "avoid_for",
    "reusability_score", "cluster_id", "cluster_role",
)
HOOK_FIELDS = ("type", "duration_sec", "mechanism", "transferable_template")
SOURCE_FIELDS = ("duration_sec", "views", "likes")
EVIDENCE_FIELDS = ("evidence_level", "evidence_score", "delivered", "spend",
                   "cost_per_delivered", "scripts", "cost_vs_baseline", "reason", "as_of")
# سقف أي نص — حماية إضافية لو حقل مسموح انحشى فيه نص خام طويل
MAX_TEXT_CHARS = 700


def _clip(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXT_CHARS else v[:MAX_TEXT_CHARS] + "…"
    if isinstance(v, list):
        return [_clip(x) for x in v][:30]
    if isinstance(v, dict):
        return {k: _clip(x) for k, x in v.items()}
    return v


def summarize_pattern(pattern_id: str, p: dict, evidence: dict | None = None) -> dict:
    """الشكل العام للنمط (بدون أي نص خام). بيستخدمه رد الطابور كمان."""
    out: dict = {"pattern_id": pattern_id}
    for k in PATTERN_FIELDS:
        if k in p and p[k] is not None:
            out[k] = _clip(p[k])
    hook = p.get("hook")
    if isinstance(hook, dict):
        out["hook"] = {k: _clip(hook[k]) for k in HOOK_FIELDS if k in hook}
    src = p.get("_source")
    if isinstance(src, dict):
        out["source"] = {k: src[k] for k in SOURCE_FIELDS if k in src}
        if isinstance(src.get("source"), str) and src["source"].startswith(("http://", "https://")):
            out["source"]["url"] = src["source"]
    ev = dict(evidence or {})
    for k in ("evidence_level", "evidence_score"):
        if k not in ev and p.get(k) is not None:
            ev[k] = p[k]
    ev_clean = {k: ev[k] for k in EVIDENCE_FIELDS if k in ev and ev[k] is not None}
    if ev_clean:
        out["evidence"] = ev_clean
    return out


def _evidence() -> dict:
    try:
        import evidence
        data = evidence.pattern_evidence()
        return data if isinstance(data, dict) else {}
    except ImportError:
        return {}
    except Exception:
        return {}


def build_bundle() -> dict:
    ev = _evidence()
    patterns = []
    for f in sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(p, dict):
            continue
        pid = f.name.replace(".pattern.json", "")
        patterns.append(summarize_pattern(pid, p, ev.get(pid)))
    cats: dict[str, int] = {}
    for p in patterns:
        c = str(p.get("product_category") or "unknown")
        cats[c] = cats.get(c, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "pattern_count": len(patterns),
        "per_category": cats,
        "patterns": patterns,
    }


def bundle_hash(bundle: dict) -> str:
    canon = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ── الحالة والرفع ────────────────────────────────────────────────────────


def _state_path() -> Path:
    return Path(config.LIBRARY_DIR) / "library_sync_state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def status() -> dict:
    s = _load_state()
    return {"last_hash": s.get("hash"), "last_push_at": s.get("at"),
            "last_ok": s.get("ok"), "patterns": s.get("count"), "error": s.get("error")}


def push_if_changed(force: bool = False) -> dict:
    """يرفع الحزمة إذا تغيّرت عن آخر رفعة ناجحة. ما بيرمي — بيرجّع {ok, pushed, ...}."""
    try:
        import crm
    except ImportError:
        return {"ok": True, "pushed": False, "skipped": "وحدة الـ OMS مش جاهزة"}
    try:
        if not crm.is_configured():
            return {"ok": True, "pushed": False, "skipped": "الـ OMS غير مضبوط"}
    except Exception:
        return {"ok": True, "pushed": False, "skipped": "الـ OMS غير مضبوط"}

    bundle = build_bundle()
    digest = bundle_hash(bundle)
    state = _load_state()
    if not force and state.get("ok") and state.get("hash") == digest:
        return {"ok": True, "pushed": False, "changed": False, "patterns": bundle["pattern_count"]}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = {**bundle, "content_hash": digest, "generated_at": now}
    try:
        resp = crm.get_client().put(LIBRARY_PATH, json=body)
        code = getattr(resp, "status_code", 200)
        if isinstance(code, int) and code >= 400:
            raise RuntimeError(f"رد {code} من الـ OMS")
    except Exception as e:
        offline = type(e).__name__ == "CRMOffline"
        msg = "الـ OMS مش متصل" if offline else settings_io.redact(str(e))[:300]
        state.update({"ok": False, "error": msg, "attempt_at": now})
        _save_state(state)
        return {"ok": False, "pushed": False, "offline": offline, "error": msg}

    _save_state({"hash": digest, "at": now, "ok": True, "count": bundle["pattern_count"]})
    return {"ok": True, "pushed": True, "changed": True, "patterns": bundle["pattern_count"]}
