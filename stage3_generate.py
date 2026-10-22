#!/usr/bin/env python3
"""
STAGE 3 — MATCHER + WRITER
يقارن بريف المنتج مع أنماط المكتبة، يرتّب أفضل 3 أنماط (مع مراعاة بُعد الفئة)،
ثم يولّد سيناريو من 7 مشاهد بمدة 45–50 ثانية على النمط المختار، ويمرّره على
حلقة المراجعة (مراجعة ← إعادة كتابة تلقائية ← مراجعة).

بوابة البريف: الكاتب ما بيشتغل على بريف ناقص — ولا في تجاوز.
سجل التكرار (library/used_registry.json) بيمنع تكرار الهوكات والمشاهد ونقاط الألم
بين السيناريوهات لنفس المنتج (ونسخ السيناريو نفسه ما بتمنع بعضها).

الاستخدام:
    python stage3_generate.py products/vara.json --match-only
    python stage3_generate.py products/vara.json
    python stage3_generate.py products/vara.json --pattern clarden_v3
    python stage3_generate.py products/vara.json --category fragrance --no-review
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# كونسول ويندوز افتراضياً cp1252 وبيفشل مع العربي
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import brief as brief_mod
import claims
import clusters
import config
import hooks_bank
import pattern_store
import pattern_text
import script_hooks
import script_versions
import taxonomy
from config import SCRIPT_SCENES, SCRIPT_MIN_SEC, SCRIPT_MAX_SEC, MAX_OUTPUT_TOKENS
from llm_errors import exit_on_api_error
import llm

REGISTRY_KEYS = ("hooks", "visuals", "pain_points", "patterns", "titles")
MATCH_TOP_N = 3


class PipelineError(Exception):
    """فشل متوقع بخط الكتابة — رسالته عربية وجاهزة للعرض."""


# ─────────────────────────── أدوات عامة ───────────────────────────


def ask(task: str, system: str, user: str, max_tokens: int = MAX_OUTPUT_TOKENS) -> dict:
    """نداء موديل — بيرمي llm.LLMError عند الفشل (الـCLI بيحوّله لرسالة)."""
    result = llm.complete_json(task, system, [{"type": "text", "text": user}], max_tokens)
    if not isinstance(result, dict):
        raise llm.LLMError(f"رد مهمة '{task}' مش كائن JSON")
    return result


def load_patterns() -> list:
    files = sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json"))
    if not files:
        raise PipelineError(f"مكتبة الأنماط فاضية: {config.PATTERNS_DIR} — شغّل المرحلة 2 أولاً.")
    out = []
    for f in files:
        p = json.loads(f.read_text(encoding="utf-8"))
        p["_pattern_id"] = f.name.replace(".pattern.json", "")
        out.append(p)
    return out


def brief_for_model(b: dict) -> dict:
    """البريف للموديل: بدون الحقول الداخلية، ومع تسميات عربية للقيم المغلقة."""
    out = {k: v for k, v in b.items() if not k.startswith("_")}
    out["category_label"] = taxonomy.CATEGORY_LABELS.get(b.get("category") or "", "")
    out["dialect_label"] = taxonomy.DIALECTS.get(b.get("dialect") or "", "")
    out["country_label"] = taxonomy.COUNTRIES.get(b.get("country") or "", "")
    return out


def _scripts_dir() -> Path:
    return Path(config.SCRIPTS_DIR)


# ─────────────────────────── ملخص النمط والمطابقة ───────────────────────────


def summarize(p: dict, board: dict | None = None, product_category: str | None = None,
              cluster_sizes: dict | None = None) -> dict:
    """ملخص خفيف للمطابقة — بدون تحميل النمط كامل. القيم المغلقة slugs مع تسميات."""
    src = p.get("_source") or {}
    pid = p["_pattern_id"]
    lp = pattern_text.localized(p)          # نصوص النمط بالعربي (الأصل الإنجليزي بيضل للبصمة بس)
    fw, dl, cat = p.get("framework"), p.get("dialect_or_language"), p.get("product_category")
    out = {
        "pattern_id": pid,
        "pattern_name": pattern_text.display_name(p),
        "framework": fw,
        "framework_label": taxonomy.FRAMEWORKS.get(fw or "", ""),
        "dialect": dl,
        "dialect_label": taxonomy.DIALECTS.get(dl or "", ""),
        "hook_type": (lp.get("hook") or {}).get("type"),
        "product_category": cat,
        "category_label": taxonomy.CATEGORY_LABELS.get(cat or "", ""),
        "category_distance": taxonomy.category_distance(product_category, cat),
        "audience": lp.get("target_audience"),
        "emotional_arc": lp.get("emotional_arc"),
        "proof_type": lp.get("proof_mechanism"),
        "why_it_works": lp.get("why_it_works"),
        "production_cost": p.get("production_complexity"),
        "best_for": lp.get("best_for"),
        "engagement": {"views": src.get("views"), "likes": src.get("likes")},
        # من وين إجا النمط: mined (من إعلان ناجح) · authored (مكتوب) · proven (من نتايجك)
        "origin": src.get("type", "mined"),
    }
    if cluster_sizes is not None and pid in cluster_sizes:
        out["cluster_copies"] = cluster_sizes[pid]     # عدد النسخ المدموجة بهالنمط الأساسي
    for k in ("evidence_level", "evidence_score"):
        if p.get(k) is not None:
            out[k] = p[k]
    if src.get("type") == "proven":
        out["proven_evidence"] = src.get("evidence")
        out["evidence_strength"] = p.get("evidence_strength")

    # أداء هذا النمط الفعلي عندك — أقوى إشارة للمطابقة
    if board and pid in board:
        b = board[pid]
        out["your_results"] = {
            "winners": b["winner"], "ok": b["ok"], "losers": b["loser"],
            "win_rate": b["win_rate"], "roas": b["roas"],
        }
    return out


def match_pool(patterns: list) -> tuple[list, dict]:
    """
    الأنماط اللي بتدخل المطابقة: الأساسية لما فهرس العناقيد موجود (+ أي نمط لسا ما انفهرس)،
    مع عدد النسخ لكل عنقود. بدون فهرس = كل الأنماط.
    """
    prim = clusters.primaries()
    if not prim:
        return list(patterns), {}
    cl = clusters.load()
    assigned = set(prim) | {v["pattern_id"] for c in cl for v in c.get("variants", [])}
    sizes = {c["primary"]: c.get("size", 1) for c in cl}
    pool = [p for p in patterns if p["_pattern_id"] in prim or p["_pattern_id"] not in assigned]
    return pool, sizes


def filter_by_category(patterns: list, wanted: str) -> list:
    """فلتر --category: slug (أو اسم عربي/نص بيتحوّل لslug)؛ الفشل برسالة فيها الـslugs المتاحة."""
    slug = taxonomy.normalize_category(wanted).value
    if slug:
        hits = [p for p in patterns if p.get("product_category") == slug]
    else:
        needle = str(wanted).casefold()
        hits = [p for p in patterns if needle in str(p.get("product_category") or "").casefold()]
    if not hits:
        cats = sorted({str(p.get("product_category") or "—") for p in patterns})
        raise PipelineError(
            f"ما في نمط بفئة '{wanted}'. الفئات المتاحة (slugs):\n    " + "\n    ".join(cats[:20])
        )
    return hits


def _scoreboard() -> dict:
    try:
        import performance
        return performance.pattern_scoreboard()
    except Exception:
        return {}


def match(product: dict, patterns: list, cluster_sizes: dict | None = None) -> dict:
    """نداء الموديل للمطابقة (بدون معالجة الفئة — refine_match بتكمّل)."""
    prompt = (Path(config.PROMPTS_DIR) / "pattern_matcher.txt").read_text(encoding="utf-8")
    board = _scoreboard()
    cat = product.get("category")
    user = (
        "## PRODUCT BRIEF\n"
        f"{json.dumps(brief_for_model(product), ensure_ascii=False, indent=2)}\n\n"
        "## PATTERN LIBRARY\n"
        f"{json.dumps([summarize(p, board, cat, cluster_sizes) for p in patterns], ensure_ascii=False, indent=2)}"
    )
    return ask("match", prompt, user)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def refine_match(result: dict, by_id: dict, product_category: str | None,
                 top_n: int = MATCH_TOP_N) -> dict:
    """
    قواعد الفئة بالكود بعد رجوع الموديل:
      · نمط بفئة بعيدة بلا transfer_justification ← يُستبعد.
      · خصم FAR/ADJACENT_CATEGORY_PENALTY من fit_score وإعادة ترتيب أفضل top_n.
      · أي pattern_id مش موجود بالمكتبة ← يُستبعد.
    """
    far_pen = getattr(config, "FAR_CATEGORY_PENALTY", 25)
    adj_pen = getattr(config, "ADJACENT_CATEGORY_PENALTY", 5)
    kept, excluded = [], list(result.get("excluded_patterns") or [])
    for r in result.get("ranked_patterns") or []:
        if not isinstance(r, dict):
            continue
        pid = r.get("pattern_id")
        p = by_id.get(pid)
        if p is None:
            excluded.append({"pattern_id": pid, "why": "نمط غير موجود بمكتبة المطابقة"})
            continue
        r["pattern_name"] = pattern_text.display_name(p) or r.get("pattern_name")      # من المكتبة مش من نسخ الموديل
        dist = taxonomy.category_distance(product_category, p.get("product_category"))
        just = str(r.get("transfer_justification") or "").strip()
        if dist == "far" and not just:
            excluded.append({"pattern_id": pid,
                             "why": "فئة بعيدة عن المنتج وبلا مبرر نقل مكتوب"})
            continue
        penalty = far_pen if dist == "far" else adj_pen if dist == "adjacent" else 0
        raw = _num(r.get("fit_score"))
        r["fit_score_raw"] = raw
        r["category_distance"] = dist
        r["category_penalty"] = penalty
        r["transfer_justification"] = just
        r["fit_score"] = round(max(0.0, raw - penalty), 1)
        kept.append(r)
    kept.sort(key=lambda r: -r["fit_score"])      # ترتيب مستقر: التعادل بيحافظ على رتبة الموديل
    kept = kept[:top_n]
    for i, r in enumerate(kept, 1):
        r["rank"] = i
    result["ranked_patterns"] = kept
    result["excluded_patterns"] = excluded
    return result


def coverage_warnings(pool: list, product_category: str | None) -> list[str]:
    """تحذير صريح لما أنماط فئة المنتج تحت الحصة الدنيا."""
    quota = getattr(config, "LIBRARY_QUOTA", 10)
    if not product_category:
        return ["فئة المنتج غير محددة بالبريف — بُعد الفئة ما انحسب"]
    n = sum(1 for p in pool if p.get("product_category") == product_category)
    if n < quota:
        label = taxonomy.CATEGORY_LABELS.get(product_category, product_category)
        return [f"خيارات محدودة: {n} من {quota} أنماط بفئة «{label}» — المطابقة أقل موثوقية "
                f"لحد ما تكتمل الحصة"]
    return []


def match_for_product(product_path, category: str | None = None, *, save: bool = True) -> dict:
    """
    مطابقة منتج مع المكتبة. بيرجّع ranked_patterns (3 بالكتير) بعد قواعد الفئة،
    مع category_distance / transfer_justification / fit_score بعد الخصم، و warnings.
    """
    product_path = Path(product_path)
    b = brief_mod.load(product_path)
    patterns = load_patterns()
    pool, sizes = match_pool(patterns)
    cat = b.get("category") or None
    warnings = coverage_warnings(pool, cat)
    if not brief_mod.completeness(b)["ready"]:
        warnings.append("البريف ناقص — المطابقة تقريبية، والكتابة ما رح تشتغل قبل ما يكتمل")

    considered = pool
    if category:
        considered = filter_by_category(pool, category)
        print(f"[i] فلترة الفئة '{category}': {len(considered)} من {len(pool)} نمط")

    result = match(b, considered, sizes)
    result = refine_match(result, {p["_pattern_id"]: p for p in considered}, cat)
    if len(result["ranked_patterns"]) < MATCH_TOP_N:
        warnings.append(f"بقي {len(result['ranked_patterns'])} أنماط صالحة فقط بعد استبعاد "
                        "البعيد بلا مبرر")
    result["warnings"] = warnings
    result["_meta"] = {
        "product": b.get("product_name") or product_path.stem,
        "product_file": product_path.name,
        "matched_at": datetime.now().isoformat(timespec="seconds"),
        "patterns_considered": len(considered),
        "library_patterns": len(patterns),
        "pool_uses_clusters": bool(sizes),
        "product_category": cat,
    }
    if save:
        matches_dir = _scripts_dir().parent / "matches"
        matches_dir.mkdir(parents=True, exist_ok=True)
        (matches_dir / f"{product_path.stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ─────────────────────────── سجل منع التكرار ───────────────────────────


def registry() -> dict:
    path = Path(config.REGISTRY_PATH)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_registry(reg: dict) -> None:
    Path(config.REGISTRY_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(config.REGISTRY_PATH).write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                                          encoding="utf-8")


def _own_values(script: dict) -> dict:
    """اللي سيناريو واحد بيساهم فيه بسجل المستخدَم."""
    return {
        "hooks": [h.strip() for h in script_hooks.hook_values(script)] or [(script.get("hook_line") or "").strip()],
        "titles": [script.get("title") or ""],
        "patterns": [(script.get("_meta") or {}).get("pattern_id") or ""],
        "pain_points": list(script.get("pain_points_used") or []),
        "visuals": [(sc.get("visual") or "")[:90] for sc in script.get("scenes", [])
                    if sc.get("visual")],
    }


def used_from_scripts(product_key: str, exclude_stem: str | None = None) -> tuple[dict, list[str]]:
    """
    يبني سجل المستخدَم من ملفات السيناريوهات نفسها — هي مصدر الحقيقة،
    والسجل مجرد نسخة مسرّعة. هيك لو السجل انحذف أو صار قديم، منظل نمنع التكرار.
    `exclude_stem`: سيناريو بنعيد كتابته — نسخته السابقة ما بتمنع الجديدة.

    بيرجع: (المستخدَم لهذا المنتج، هوكات كل المنتجات التانية)
    """
    mine = {k: [] for k in REGISTRY_KEYS}
    other_hooks = []

    for f in sorted(_scripts_dir().glob("*.json")):
        if exclude_stem and f.stem == exclude_stem:
            continue
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if (s.get("_meta") or {}).get("mode") == "free":          # المشروع الحر ما بيمنع تكرار شي على الكاتب
            continue
        owner = (s.get("_meta") or {}).get("product")
        hook = (s.get("hook_line") or "").strip()

        if owner != product_key:
            if hook:
                other_hooks.append(hook)
            continue

        own = _own_values(s)
        for k in REGISTRY_KEYS:
            mine[k] += own[k]

    for k in mine:
        mine[k] = [v for v in dict.fromkeys(mine[k]) if v]
    return mine, list(dict.fromkeys(other_hooks))


def used_for(product_key: str, exclude_script: dict | None = None,
             exclude_stem: str | None = None) -> dict:
    """المستخدَم كامل للكاتب: الملفات + السجل المخزّن (بدون مساهمة السيناريو المُعاد كتابته)."""
    from_files, other_hooks = used_from_scripts(product_key, exclude_stem)
    cached = registry().get(product_key, {})
    if exclude_script is not None:
        own = _own_values(exclude_script)
        cached = {k: [v for v in cached.get(k, []) if v not in own.get(k, [])]
                  for k in REGISTRY_KEYS}
    used = {k: list(dict.fromkeys(from_files.get(k, []) + cached.get(k, [])))
            for k in REGISTRY_KEYS}
    used["hooks_used_on_other_products"] = other_hooks
    return used


def update_registry(product_key: str, new_script: dict, old_script: dict | None = None) -> None:
    reg = registry()
    cached = reg.get(product_key, {})
    if old_script is not None:
        own = _own_values(old_script)
        cached = {k: [v for v in cached.get(k, []) if v not in own.get(k, [])]
                  for k in REGISTRY_KEYS}
    own_new = _own_values(new_script)
    reg[product_key] = {
        k: [v for v in dict.fromkeys(cached.get(k, []) + own_new[k]) if v] for k in REGISTRY_KEYS
    }
    save_registry(reg)


# ─────────────────────────── الكتابة ───────────────────────────


def _actionable(review: dict) -> list[dict]:
    keep = ("severity", "scene", "field", "issue", "evidence", "fix")
    return [{k: f.get(k) for k in keep} for f in review.get("findings", [])
            if isinstance(f, dict) and f.get("severity") in ("blocker", "major", "minor")]


def _hook_examples(product: dict) -> str:
    """كتلة «هوكات نجحت» من بنك الهوكات (⭐ أو رابحة بالنتايج). فاضية لو ما في، وما بتكسر الكتابة لو فشل شي."""
    try:
        return hooks_bank.writer_block(hooks_bank.writer_examples((product or {}).get("category")))
    except Exception:                                        # noqa: BLE001 — الأمثلة تحسين مش شرط
        return ""


def write_script(product: dict, pattern: dict, used: dict, *, previous: dict | None = None,
                 review: dict | None = None, hooks=None) -> dict:
    """hooks: عدد الافتتاحيات المطلوب (الأساسي + بدائل)؛ الافتراضي config.HOOKS_DEFAULT. الرد بيتعاير بـ script_hooks.normalize."""
    n_hooks = script_hooks.clean_requested(hooks)
    prompt = (Path(config.PROMPTS_DIR) / "script_writer.txt").read_text(encoding="utf-8")
    prompt = (
        prompt.replace("{{SCENES}}", str(SCRIPT_SCENES))
        .replace("{{MIN_SEC}}", str(SCRIPT_MIN_SEC))
        .replace("{{MAX_SEC}}", str(SCRIPT_MAX_SEC))
        .replace("{{HOOKS}}", str(n_hooks))
    )
    user = (
        "## PRODUCT BRIEF\n"
        f"{json.dumps(brief_for_model(product), ensure_ascii=False, indent=2)}\n\n"
        "## HARD RULES FROM BRIEF\n"
        "These override the pattern and everything else. Any violation fails the script.\n"
        f"{json.dumps(claims.writer_rules(product), ensure_ascii=False, indent=2)}\n\n"
        "## PATTERN TO APPLY (full blueprint)\n"
        f"{json.dumps(pattern_text.for_model(pattern), ensure_ascii=False, indent=2)}\n\n"
        f"{_hook_examples(product)}"
        "## ALREADY USED — DO NOT REPEAT ANY OF THESE\n"
        f"{json.dumps(used, ensure_ascii=False, indent=2)}"
    )
    if previous is not None:
        draft = {k: v for k, v in previous.items() if k != "_meta"}
        feedback = {
            "verdict": (review or {}).get("verdict"),
            "summary": (review or {}).get("summary"),
            "findings": _actionable(review or {}),
        }
        user += (
            "\n\n## PREVIOUS DRAFT AND REVIEWER FEEDBACK\n"
            "This is a REWRITE of the draft below. Fix EVERY finding with severity blocker or "
            "major. Keep what already works (structure, strong lines, scene timing that passed) "
            "- change only what the findings require. Return the full script JSON again, "
            "still obeying every constraint and the hard rules above.\n\n"
            "### PREVIOUS DRAFT\n"
            f"{json.dumps(draft, ensure_ascii=False, indent=2)}\n\n"
            "### REVIEWER FEEDBACK\n"
            f"{json.dumps(feedback, ensure_ascii=False, indent=2)}"
        )
    return script_hooks.normalize(ask("writer", prompt, user), n_hooks)


def to_markdown(script: dict, product: dict, pattern_id: str) -> str:
    country = taxonomy.COUNTRIES.get(product.get("country") or "", product.get("country") or "")
    dialect = taxonomy.DIALECTS.get(product.get("dialect") or "", product.get("dialect") or "")
    lines = [
        f"# {script.get('_meta', {}).get('display_name', '')} — {script.get('title', '')}".strip(" —"),
        "",
        f"**المنتج:** {product.get('product_name')}  ",
        f"**السوق / اللهجة:** {country} — {dialect}  ",
        f"**النمط المستخدم:** `{pattern_id}` — {script.get('framework', '')}  ",
        f"**المدة الكلية:** {script.get('total_duration_sec')} ثانية  ",
        f"**الهوك:** {script.get('hook_line', '')}",
        "",
        "---",
        "",
    ]
    for sc in script.get("scenes", []):
        lines += [
            f"### مشهد {sc.get('scene_number')} — {sc.get('duration_sec')} ثانية · {sc.get('purpose', '')}",
            f"- **نوع اللقطة:** {sc.get('shot_type', '')}",
            f"- **الوصف البصري:** {sc.get('visual', '')}",
            f"- **الفويس أوفر:** {sc.get('voiceover', '')}",
            f"- **نص على الشاشة:** {sc.get('on_screen_text', '')}",
            f"- **الإحساس:** {sc.get('emotion', '')}",
            "",
        ]
    if script.get("production_notes"):
        lines += ["---", "", "## ملاحظات تنفيذية", ""]
        lines += [f"- {n}" for n in script["production_notes"]]
    return "\n".join(lines)


def _next_number(key: str) -> int:
    """ترقيم تسلسلي لكل منتج — أعلى رقم موجود + 1، فالحذف ما بيسبّب تكرار."""
    used_numbers = []
    for f in _scripts_dir().glob("*.json"):
        try:
            prev = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        pm = prev.get("_meta") or {}
        if pm.get("product") == key and isinstance(pm.get("number"), int):
            used_numbers.append(pm["number"])
    return (max(used_numbers) + 1) if used_numbers else 1


def _write_files(path: Path, script: dict, product: dict, pattern_id: str) -> None:
    path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    path.with_suffix(".md").write_text(to_markdown(script, product, pattern_id), encoding="utf-8")


def write_for_product(product_path, pattern_id: str | None = None, *, review: bool = True,
                      label: str | None = None, category: str | None = None, hooks=None) -> Path:
    """
    يكتب سيناريو جديد لمنتج: بوابة البريف ← (مطابقة إذا ما انحدد نمط) ← كتابة ← حلقة المراجعة.
    بيرمي brief.BriefIncomplete (قبل أي نداء موديل) لو البريف ناقص، وPipelineError/LLMError
    للباقي. بيرجّع مسار ملف السيناريو.
    """
    product_path = Path(product_path)
    b = brief_mod.load(product_path)
    brief_mod.require_complete(b)              # لا تجاوز — قبل أي نداء موديل

    patterns = load_patterns()
    if category:
        patterns = filter_by_category(patterns, category)
    key = b.get("product_name") or product_path.stem

    if pattern_id:
        chosen = next((p for p in patterns if p["_pattern_id"] == pattern_id), None)
        if not chosen:
            raise PipelineError(f"ما لقيت النمط: {pattern_id}")
        print(f"[i] نمط مفروض يدوياً: {pattern_text.display_name(chosen)}")
    else:
        print("[1/2] مطابقة المنتج مع أنماط المكتبة…")
        result = match_for_product(product_path, category=category)
        print_match(result)
        ranked = result.get("ranked_patterns") or []
        if not ranked:
            raise PipelineError("ما بقي نمط صالح بعد قواعد الفئة — أضف أنماط للفئة أو اختر نمطاً يدوياً")
        top = ranked[0]["pattern_id"]
        chosen = next(p for p in load_patterns() if p["_pattern_id"] == top)

    print("\n[2/2] كتابة السيناريو…")
    used = used_for(key)
    print(
        f"      منع التكرار: {len(used['hooks'])} هوك و{len(used['visuals'])} لقطة "
        f"سابقة لهذا المنتج، و{len(used['hooks_used_on_other_products'])} هوك من منتجات تانية"
    )
    n_hooks = script_hooks.clean_requested(hooks)
    script = write_script(b, chosen, used, hooks=n_hooks)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = _scripts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    wcfg = llm.task_config("writer")
    suffix = f"__{label}" if label else ""
    name = f"{key}__{chosen['_pattern_id']}__{stamp}{suffix}"
    n = 2
    while (out_dir / f"{name}.json").exists():       # نفس الدقيقة ونفس النمط
        name = f"{key}__{chosen['_pattern_id']}__{stamp}{suffix}_{n}"
        n += 1

    number = _next_number(key)
    code = b.get("product_code") or brief_mod.slug_code(key) or "product"
    script["_meta"] = {
        "product": key, "product_file": product_path.name, "product_code": code,
        "number": number, "version": 1,
        "script_id": script_versions.make_script_id(code, number, 1),
        "display_name": f"#{number} - {key}",
        "pattern_id": chosen["_pattern_id"], "generated_at": stamp, "hooks_requested": n_hooks,
        # الموديل المستخدم — بدونه المقارنة بين توليدتين ما إلها معنى
        "provider": wcfg["provider"], "model": wcfg["model"],
        "label": label or "",
        "status": "draft",
        "content_hash": script_versions.content_hash(script),
    }
    path = out_dir / f"{name}.json"
    _write_files(path, script, b, chosen["_pattern_id"])
    script_versions.save_version(path.stem, script)
    update_registry(key, script)

    total = sum(sc.get("duration_sec", 0) for sc in script.get("scenes", []))
    flag = "✓" if SCRIPT_MIN_SEC <= total <= SCRIPT_MAX_SEC else "!"
    print(f"[{flag}] #{number} - {key} | المشاهد: {len(script.get('scenes', []))} | المدة: {total} ثانية")
    print(f"[✓] {path.with_suffix('.md')}")

    if review:
        import review_loop
        review_loop.run(path)
    return path


def rewrite_from_review(script_path, review_result: dict) -> Path:
    """
    إعادة كتابة تلقائية بملاحظات المراجِع. نفس الملف (الاسم ما بيتغيّر)، النسخة +1،
    والنسخة السابقة بتنحفظ بـ versions/. بيرمي PipelineError/LLMError عند الفشل.
    """
    import review_script
    path = Path(script_path)
    old = json.loads(path.read_text(encoding="utf-8"))
    meta = dict(old.get("_meta") or {})

    b = review_script.load_brief(old)
    if b is None:
        raise PipelineError("ما لقيت بريف المنتج لإعادة الكتابة")
    pid = meta.get("pattern_id")
    pattern = pattern_store.load_any(str(pid)) if pid else None
    if not pattern:
        raise PipelineError(f"ما لقيت نمط السيناريو ({pid}) لإعادة الكتابة")
    pattern["_pattern_id"] = pid

    key = meta.get("product") or b.get("product_name")
    script_versions.save_version(path.stem, old)          # ضمان حفظ النسخة الحالية قبل الكتابة فوقها
    used = used_for(key, exclude_script=old, exclude_stem=path.stem)
    had = meta.get("hooks_requested") or len(script_hooks.hooks_of(old))       # القديم (هوك واحد) بيضل هوك واحد
    new = write_script(b, pattern, used, previous=old, review=review_result, hooks=had)

    version = script_versions.version_of(old) + 1
    number = meta.get("number")
    code = meta.get("product_code") or b.get("product_code") or brief_mod.slug_code(key) or "product"
    wcfg = llm.task_config("writer")
    new["_meta"] = {
        **meta,
        "product_code": code, "version": version,
        "script_id": script_versions.make_script_id(code, number, version),
        "rewritten_at": datetime.now().isoformat(timespec="seconds"),
        "provider": wcfg["provider"], "model": wcfg["model"],
        "status": "reviewing",
        "content_hash": script_versions.content_hash(new),
    }
    new["_meta"].pop("edited_at", None)
    _write_files(path, new, b, pid)
    script_versions.save_version(path.stem, new)
    update_registry(key, new, old_script=old)
    print(f"[✓] أُعيدت الكتابة → {new['_meta']['script_id']}")
    return path


def print_match(result: dict) -> None:
    for c in result.get("ranked_patterns", []):
        print(f"\n  #{c.get('rank')}  {c.get('pattern_id')} — {c.get('pattern_name')}")
        pen = f" (بعد خصم الفئة {c['category_penalty']})" if c.get("category_penalty") else ""
        print(f"      التوافق: {c.get('fit_score')}/100{pen} · بُعد الفئة: {c.get('category_distance')}")
        print(f"      السبب: {c.get('reason')}")
        print(f"      التعديل المطلوب: {c.get('required_adaptation')}")
        if c.get("transfer_justification"):
            print(f"      مبرر النقل: {c['transfer_justification']}")
    for e in result.get("excluded_patterns", []):
        print(f"  ✗ استُبعد {e.get('pattern_id')}: {e.get('why')}")
    for w in result.get("warnings", []):
        print(f"  [!] {w}")


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 3 — مطابقة وتوليد السيناريو")
    ap.add_argument("product", help="مسار ملف المنتج JSON")
    ap.add_argument("--pattern", help="فرض نمط محدد بالـ pattern_id")
    ap.add_argument("--match-only", action="store_true", help="اعرض الأنماط المرشّحة فقط")
    ap.add_argument("--connection", help="تجاوز الاتصال لهالتشغيلة")
    ap.add_argument("--model", help="تجاوز الموديل لهالتشغيلة")
    ap.add_argument("--label", help="وسم يميّز هالتوليدة (للمقارنة)")
    ap.add_argument("--category", help="طابق ضمن فئة معيّنة فقط (slug مثل fragrance، أو اسمها بالعربي)")
    ap.add_argument("--no-review", action="store_true", help="اكتب بدون حلقة المراجعة")
    ap.add_argument("--hooks", type=int, help=f"عدد الهوكات (الافتراضي {config.HOOKS_DEFAULT}، الأقصى {config.HOOKS_MAX})")
    args = ap.parse_args()

    # التجاوز بينطبق على الكتابة والمطابقة سوا
    if args.connection or args.model:
        for t_ in ("writer", "match"):
            llm.set_override(t_, args.connection or "", args.model or "")

    try:
        if args.match_only:
            print_match(match_for_product(args.product, category=args.category))
            return
        write_for_product(args.product, args.pattern, review=not args.no_review,
                          label=args.label, category=args.category, hooks=args.hooks)
    except brief_mod.BriefIncomplete as e:
        sys.exit(f"[!] {e}\n    كمّل الحقول الناقصة بالبريف وأعد التشغيل — الكتابة ما بتشتغل على بريف ناقص.")
    except PipelineError as e:
        sys.exit(f"[!] {e}")
    except llm.LLMError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
