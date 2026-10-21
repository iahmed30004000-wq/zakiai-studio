"""
مكتبة الادعاءات الممنوعة + فحص النصوص.

قاعدتين:
  1. المكتبة حسب الفئة بتنطبق تلقائياً. التاجر بيضيف فوقها ما بيحذف منها.
  2. الفحص بالكود (regex) مش بالموديل — قاطع وقابل للاختبار. الموديل بيكمّل بس.

ما بنغطي كل الصياغات الممكنة: الفحص بيمسك الصيغ الشائعة، والمراجِع بالموديل
بيمسك الباقي. لكن اللي بيمسكه الكود بيمسكه دايماً.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import config
import taxonomy

# ── الأنماط ─────────────────────────────────────────────────────────────
_AR_NUM = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

HEALTH_RULES = [
    ("شفاء", r"(?:ال)?شفاء|ي?شفي|بيشفي|تشفي|شفى|شافي"),
    ("علاج", r"علاج|يعالج|بيعالج|تعالج|علاجي"),
    ("بديل عن الطبيب", r"بديل\s+(?:عن|ل)\s*(?:ال)?(?:طبيب|دكتور)|بدل\s+(?:ال)?(?:طبيب|دكتور)|"
                        r"بلا\s+(?:ال)?(?:طبيب|دكتور)|ما\s+(?:بتحتاج|تحتاج)\s+(?:ل)?(?:ال)?(?:طبيب|دكتور)"),
    ("نتيجة مضمونة", r"نتيج[ةه]\s+مضمون|مضمون(?:ة)?\s*(?:100|١٠٠)|(?:100|١٠٠)\s*%?\s*مضمون|ضمان\s+(?:ال)?نتيج"),
]
BEAUTY_RULES = [
    ("بدون تهيّج لكل البشرات", r"بدون\s+(?:أي|اي)\s+تهيّ?ج|لكل\s+(?:أنواع\s+)?(?:ال)?بشر|كل\s+(?:ال)?بشرات|"
                               r"ما\s+(?:بيسبب|يسبب)\s+(?:أي\s+)?تهيّ?ج"),
    ("نتيجة نهائية", r"نهائي|نهائياً|نهائيا|للأبد|للابد|بدون\s+رجعة|ما\s+بيرجع|لن\s+يعود|إزالة\s+دائمة"),
]

HEALTH_CATEGORIES = {"eye_care", "ear_care", "oral_care", "supplements", "joint_pain", "wellness_device"}
BEAUTY_CLAIM_CATEGORIES = {"hair_removal", "skincare", "hair_care"}

# ندرة — بس مسموحة إذا في وقت انتهاء أو مخزون حقيقي
SCARCITY_RX = (r"(?:ال)?كمي[ةه]\s+محدود|لفتر[ةه]\s+محدود|آخر\s+(?:ال)?(?:قطع|علب)|قطع\s+محدود|"
               r"عرض\s+محدود|(?:ال)?عرض\s+لفتر|ينتهي|ينتهى|ما\s+ضل\s+غير|فقط\s+\d+\s+(?:قطع|علب)|"
               r"(?:ال)?مخزون\s+(?:ينفد|محدود)|قبل\s+ما\s+(?:يخلص|ينتهي|تخلص)|الحق(?:وا)?\s+(?:ال)?عرض|"
               r"(?:اليوم|الليلة)\s+بس|آخر\s+فرصة")

# كلمات عرض — ممنوعة إذا التاجر أكّد «لا يوجد عرض»
OFFER_RX = r"عرض|خصم|تخفيض|مجاناً|مجانا|هدية|اثنين\s+بسعر|قطعتين\s+بسعر|1\s*\+\s*1|2\s*\+\s*1|وفّر|وفر"

# اتهام منتجات السوق بعيب محدد
ACCUSATION_RX = r"ملوّ?ث|تلوّ?ث|سام(?:ة)?\b|مسرطن|مغشوش|مضرّ?(?:ة)?\b|ضرر\b"
_NEGATION_BEFORE = r"(?:بدون|خالي|خالٍ|ما\s+فيه|لا\s+يحتوي|ما\s+بيحتوي|لا\s+ضرر|بلا)\s+\S{0,15}$"

# نسبة/مضاعف بلا سند
QUANT_RX = r"(\d+(?:[.,]\d+)?)\s*(?:%|٪|ضعف|أضعاف|مرات\s+أ)"


def _norm(s: str) -> str:
    return str(s or "").translate(_AR_NUM)


# ── مكتبة الادعاءات القابلة للتعديل ─────────────────────────────────────
# القيم الافتراضية بالكود (فوق). المالك بيقدر يعدّل/يحذف/يضيف من الواجهة؛ تعديلاته بتنحفظ بملف
# library/claims_rules.json مع سجل بكل تغيير، وزر «استرجاع الافتراضي» بيرجّع الأصل.
GROUP_LABELS = {"health": "فئات الصحة", "beauty": "فئات التجميل", "all": "كل الفئات"}
MAX_PATTERNS, MAX_PATTERN_LEN, MAX_LABEL_LEN, MAX_LOG = 20, 200, 60, 500


class ClaimsError(Exception):
    """رسالة عربية جاهزة للعرض."""


def _split_alts(rx: str) -> list[str]:
    """بيقسّم النمط عند | بالمستوى الأول بس (مش جوّا الأقواس)."""
    out, depth, cur, esc = [], 0, "", False
    for ch in rx:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == "\\":
            cur += ch
            esc = True
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "|" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [a for a in out if a]


def _defaults() -> dict:
    def mk(prefix, rules):
        return [{"id": f"{prefix}_{i + 1}", "label": label, "patterns": _split_alts(rx), "builtin": True}
                for i, (label, rx) in enumerate(rules)]
    return {
        "health": {"label": GROUP_LABELS["health"], "categories": sorted(HEALTH_CATEGORIES), "rules": mk("health", HEALTH_RULES)},
        "beauty": {"label": GROUP_LABELS["beauty"], "categories": sorted(BEAUTY_CLAIM_CATEGORIES), "rules": mk("beauty", BEAUTY_RULES)},
        "all": {"label": GROUP_LABELS["all"], "categories": ["*"], "rules": []},
    }


def _rules_path() -> Path:
    return Path(config.LIBRARY_DIR) / "claims_rules.json"


def _load_store() -> dict:
    p = _rules_path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_store(d: dict) -> None:
    p = _rules_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def rules_state() -> dict:
    """الحالة الكاملة: المجموعات (الافتراضي مع تعديلات المالك) + آخر التغييرات."""
    store = _load_store()
    groups = _defaults()
    for g, over in (store.get("groups") or {}).items():
        if g in groups and isinstance(over, dict) and isinstance(over.get("rules"), list):
            groups[g]["rules"] = over["rules"]
    return {"groups": groups, "log": (store.get("log") or [])[-60:][::-1],
            "customized": sorted((store.get("groups") or {}).keys())}


def category_rules(category: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for g in rules_state()["groups"].values():
        cats = g.get("categories") or []
        if "*" in cats or category in cats:
            out += [(r["label"], "|".join(r["patterns"])) for r in g["rules"]
                    if r.get("enabled", True) and r.get("patterns")]
    return out


def _phrase_to_pattern(phrase: str) -> str:
    words = [w for w in re.split(r"\s+", _norm(phrase).strip()) if w]
    return r"\s+".join(re.escape(w) for w in words)


_PROBE = (
    "import re,sys\n"
    "rx=re.compile(sys.argv[1], re.I)\n"
    "if rx.search(''): sys.exit(3)\n"
    "for t in ('ا'*40+'!', ' '*30+'a'*40+'!', 'ab'*30+'!'): rx.search(t)\n"
)
PROBE_TIMEOUT_SEC = 1.5


def _check_pattern(p: str) -> None:
    """بيتحقق من الصيغة: صالحة، ما بتطابق الفاضي، وما بتعلّق الفحص.
    تجربة التعليق بتتم بعملية منفصلة بمهلة — لأن re ما بينقطع من جوّا نفس العملية (الصيغة الخبيثة بتعلّق الخادم)."""
    import subprocess
    import sys
    if not p or len(p) > MAX_PATTERN_LEN:
        raise ClaimsError(f"الصيغة فاضية أو أطول من {MAX_PATTERN_LEN} حرف")
    try:
        re.compile(p, re.I)
    except re.error as e:
        raise ClaimsError(f"الصيغة «{p[:40]}» مش صالحة: {e}")
    try:
        r = subprocess.run([sys.executable, "-I", "-c", _PROBE, p], capture_output=True, timeout=PROBE_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise ClaimsError(f"الصيغة «{p[:40]}» ثقيلة كتير على الفحص (بتعلّق) — بسّطها")
    if r.returncode == 3:
        raise ClaimsError(f"الصيغة «{p[:40]}» بتطابق أي نص (بتمنع كل شي) — عدّلها")
    if r.returncode != 0:
        raise ClaimsError(f"الصيغة «{p[:40]}» مش صالحة")


def _clean_rule(label, patterns, phrase) -> tuple[str, list[str]]:
    label = " ".join(str(label or "").split())
    if not label or len(label) > MAX_LABEL_LEN:
        raise ClaimsError(f"اسم الادعاء مطلوب (حتى {MAX_LABEL_LEN} حرف)")
    pats = [str(x).strip() for x in (patterns or []) if str(x).strip()]
    if phrase and str(phrase).strip():
        pats.append(_phrase_to_pattern(str(phrase)))
    pats = list(dict.fromkeys(pats))
    if not pats or len(pats) > MAX_PATTERNS:
        raise ClaimsError(f"لازم صيغة وحدة على الأقل (وحتى {MAX_PATTERNS})")
    for x in pats:
        _check_pattern(x)
    return label, pats


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mutate(group: str, fn, action: str, rule_id: str, label: str, before, after) -> dict:
    if group not in GROUP_LABELS:
        raise ClaimsError("مجموعة غير معروفة")
    store = _load_store()
    cur = rules_state()["groups"][group]["rules"]
    rules = fn([dict(r) for r in cur])
    store.setdefault("groups", {})[group] = {"rules": rules}
    store.setdefault("log", []).append({"at": _now_iso(), "by": "owner", "action": action, "group": group,
                                         "rule_id": rule_id, "label": label, "before": before, "after": after})
    store["log"] = store["log"][-MAX_LOG:]
    _save_store(store)
    return rules_state()


def _find(group: str, rule_id: str) -> dict:
    groups = rules_state()["groups"]
    if group not in groups:
        raise ClaimsError("مجموعة غير معروفة")
    cur = next((r for r in groups[group]["rules"] if r["id"] == rule_id), None)
    if not cur:
        raise ClaimsError("الادعاء غير موجود")
    return cur


def add_rule(group: str, label, patterns=None, phrase=None) -> dict:
    label, pats = _clean_rule(label, patterns, phrase)
    rid = f"{group}_u{int(time.time() * 1000)}"
    return _mutate(group, lambda rs: rs + [{"id": rid, "label": label, "patterns": pats, "builtin": False}],
                   "add", rid, label, None, pats)


def edit_rule(group: str, rule_id: str, label=None, patterns=None, phrase=None, enabled=None) -> dict:
    cur = _find(group, rule_id)
    new_label, new_pats = _clean_rule(label if label is not None else cur["label"],
                                      patterns if patterns is not None else cur["patterns"], phrase)

    def fn(rs):
        for r in rs:
            if r["id"] == rule_id:
                r.update(label=new_label, patterns=new_pats)
                if enabled is not None:
                    r["enabled"] = bool(enabled)
        return rs
    return _mutate(group, fn, "edit", rule_id, new_label, {"label": cur["label"], "patterns": cur["patterns"]},
                   {"label": new_label, "patterns": new_pats})


def delete_rule(group: str, rule_id: str) -> dict:
    cur = _find(group, rule_id)
    return _mutate(group, lambda rs: [r for r in rs if r["id"] != rule_id], "delete", rule_id, cur["label"],
                   {"label": cur["label"], "patterns": cur["patterns"]}, None)


def reset_group(group: str) -> dict:
    if group not in GROUP_LABELS:
        raise ClaimsError("مجموعة غير معروفة")
    store = _load_store()
    (store.get("groups") or {}).pop(group, None)
    store.setdefault("log", []).append({"at": _now_iso(), "by": "owner", "action": "reset", "group": group,
                                         "rule_id": "", "label": GROUP_LABELS[group], "before": None, "after": None})
    _save_store(store)
    return rules_state()


def try_text(text: str, category: str | None) -> list[dict]:
    """جرّب نص: شو بتمنع المكتبة الحالية فيه (بدون ما نحفظ شي)."""
    brief = {"category": category, "no_offer": False, "offer": "x"}
    found = scan_script({"scenes": [{"scene_number": 1, "voiceover": str(text or "")[:2000]}]}, brief)
    return [f for f in found if str(f.get("issue", "")).startswith("ادعاء ممنوع")]


def library_labels(category: str | None) -> list[str]:
    """أسماء الممنوع للعرض/للكاتب."""
    return [label for label, _ in category_rules(category)]


def effective_forbidden(brief: dict) -> list[str]:
    """المكتبة (حسب الفئة) + إضافات التاجر — التاجر ما بيقدر يحذف من المكتبة."""
    merged = library_labels(brief.get("category"))
    merged += [c for c in (brief.get("forbidden_claims") or []) if c and c not in merged]
    return merged


# ── الندرة ──────────────────────────────────────────────────────────────
def scarcity_allowed(brief: dict, today: date | None = None) -> tuple[bool, str]:
    """الندرة مسموحة بس بوقت انتهاء مستقبلي أو مخزون حقيقي مسجّل."""
    today = today or date.today()
    dl = str(brief.get("scarcity_deadline") or "").strip()
    if dl:
        try:
            if datetime.strptime(dl[:10], "%Y-%m-%d").date() >= today:
                return True, f"ينتهي العرض {dl[:10]}"
        except ValueError:
            pass
    try:
        stock = int(brief.get("stock_units") or 0)
    except (TypeError, ValueError):
        stock = 0
    if stock > 0:
        return True, f"المخزون المسجّل {stock} قطعة"
    return False, ""


def writer_rules(brief: dict) -> dict:
    """القواعد اللي بتنحقن للكاتب بجانب البريف."""
    ok, basis = scarcity_allowed(brief)
    no_offer = bool(brief.get("no_offer")) or not str(brief.get("offer") or "").strip()
    return {
        "forbidden_claims_effective": effective_forbidden(brief),
        "scarcity_allowed": ok,
        "scarcity_basis": basis,
        "offer_allowed_in_cta": not no_offer,
        "market_accusations_allowed": bool(brief.get("market_claims_evidence")),
    }


# ── الفحص ───────────────────────────────────────────────────────────────
def _brief_support_text(brief: dict) -> str:
    keys = ("core_promise", "what_it_does", "features", "proof_assets", "offer",
            "differentiator", "guarantee", "market_claims_evidence")
    out = []
    for k in keys:
        v = brief.get(k)
        out.append(" ".join(v) if isinstance(v, list) else str(v or ""))
    return _norm(" ".join(out))


def _fields_of(script: dict) -> list[tuple[str, int | None, str]]:
    """(الحقل، رقم المشهد، النص) لكل نص مقروء بالسيناريو."""
    out = [("hook_line", None, script.get("hook_line", "")),
           ("cta_line", None, script.get("cta_line", "")),
           ("title", None, script.get("title", ""))]
    for sc in script.get("scenes", []):
        n = sc.get("scene_number")
        out += [("voiceover", n, sc.get("voiceover", "")),
                ("on_screen_text", n, sc.get("on_screen_text", ""))]
    return [(f, n, str(t)) for f, n, t in out if t]


def scan_script(script: dict, brief: dict) -> list[dict]:
    """
    بيفحص كل نصوص السيناريو مقابل قواعد البريف. بيرجّع ملاحظات بنفس شكل المراجِع
    (severity/scene/field/issue/evidence/fix) — كلها blocker لأنها قواعد قاطعة.
    """
    findings: list[dict] = []
    rules = category_rules(brief.get("category"))
    rules += [(c, re.escape(c)) for c in (brief.get("forbidden_claims") or []) if c]
    ok_scarcity, _ = scarcity_allowed(brief)
    no_offer = bool(brief.get("no_offer")) or not str(brief.get("offer") or "").strip()
    support = _brief_support_text(brief)
    has_evidence = bool(brief.get("market_claims_evidence"))

    def add(field, scene, issue, evidence, fix):
        findings.append({"severity": "blocker", "scene": scene, "field": field,
                         "issue": issue, "evidence": evidence, "fix": fix, "rule": True})

    for field, scene, text in _fields_of(script):
        t = _norm(text)

        for label, rx in rules:
            m = re.search(rx, t, re.I)
            if m:
                add(field, scene, f"ادعاء ممنوع: «{label}»", m.group(0),
                    "شيل الادعاء أو استبدله بصياغة وصفية بدون وعد علاجي/مطلق")

        if not ok_scarcity:
            m = re.search(SCARCITY_RX, t)
            if m:
                add(field, scene, "ندرة بدون سند (ما في وقت انتهاء ولا مخزون مسجّل بالبريف)",
                    m.group(0), "شيل عبارة الندرة أو سجّل وقت الانتهاء/المخزون الحقيقي بالبريف")

        if no_offer and field in ("cta_line", "voiceover", "hook_line"):
            m = re.search(OFFER_RX, t)
            if m:
                add(field, scene, "ذكر عرض والبريف مؤكّد إنو ما في عرض", m.group(0),
                    "شيل كلمة العرض/الخصم — الدعوة للفعل بدون عرض")

        if not has_evidence:
            for m in re.finditer(ACCUSATION_RX, t):
                before = t[max(0, m.start() - 24):m.start() + 1]
                if not re.search(_NEGATION_BEFORE, before):
                    add(field, scene, "اتهام منتجات السوق بعيب محدد بلا سند", m.group(0),
                        "شيل الاتهام أو سجّل السند بحقل «سند ادعاءات السوق» بالبريف")
                    break

        if brief.get("category") in HEALTH_CATEGORIES:
            for m in re.finditer(QUANT_RX, t):
                if m.group(1) not in support:
                    add(field, scene, "مقارنة/نسبة كمية بلا سند ببيانات المنتج", m.group(0),
                        "شيل الرقم أو أضف مصدره لحقل الإثبات بالبريف")
    return findings
