#!/usr/bin/env python3
"""
استخراج أنماط جديدة من الأداء الفعلي (طلبات مُسلَّمة بتكلفة منخفضة من الـ OMS).

المرحلة 2 بتتعلّم من إعلانات غيرك، وهاي بتتعلّم من إعلاناتك إنت. الحكم على السيناريو مش
تعليم يدوي: هو `evidence.script_verdicts()` — winner مقابل loser بس، وبوابة MIN_DELIVERED
(بلا حكم تحت الحد). الأنماط الناتجة بتتوسم _source.type = "proven".

    python learn_patterns.py                      # كل المنتجات، الحين
    python learn_patterns.py --product VARA       # منتج واحد
    python learn_patterns.py --weekly             # فقط لو مرّ ≥7 أيام على آخر تشغيل ناجح
    python learn_patterns.py --dry-run
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config
from config import MAX_OUTPUT_TOKENS
from llm_errors import exit_on_api_error
import evidence
import llm

MIN_JUDGED = 2          # أقل عدد سيناريوهات محكوم عليها (ناجح/فاشل) قبل ما يستاهل نحلّل
WEEKLY_DAYS = 7


def slug(text: str) -> str:
    text = re.sub(r"[^\w؀-ۿ]+", "_", str(text).strip().lower())
    return re.sub(r"_+", "_", text).strip("_")[:50] or "pattern"


def _state_path() -> Path:
    return Path(config.LIBRARY_DIR) / "learning_state.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def last_run() -> dict:
    """للواجهة: آخر تشغيل (ناجح أو متخطّى أو فاشل)."""
    st = load_state()
    run = st.get("last_run") or {}
    return {"at": run.get("at"), "results": run.get("results", []),
            "skipped_reason": run.get("skipped_reason"), "error": run.get("error"),
            "last_success": st.get("last_success")}


def collect(product: str | None, today=None, verdicts: dict | None = None) -> tuple[list[dict], dict]:
    """يجمع السيناريوهات المحكوم عليها فعلياً (winner/loser فقط) مع أرقام الأداء."""
    verdicts = evidence.script_verdicts(today) if verdicts is None else verdicts
    scripts_dir = Path(config.SCRIPTS_DIR)
    items, tally = [], {"winner": 0, "ok": 0, "loser": 0}

    for script_file, v in verdicts.items():
        if v["verdict"] not in ("winner", "loser"):
            continue
        try:
            script = json.loads((scripts_dir / script_file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta = script.get("_meta") or {}
        if product and product not in (meta.get("product"), meta.get("product_code")):
            continue

        tally[v["verdict"]] += 1
        items.append({
            "script_file": script_file,
            "product": meta.get("product"),
            "pattern_used": meta.get("pattern_id"),
            "result": v["verdict"],
            "metrics": {
                "spend": v["spend"], "orders": v["orders"], "delivered": v["delivered"],
                "delivery_rate": v["delivery_rate"], "cost_per_delivered": v["cost_per_delivered"],
                "baseline_cost_per_delivered": v["baseline_cpd"],
                "cost_vs_baseline": v["cost_vs_baseline"],
            },
            "notes": v["reason"],
            "title": script.get("title"),
            "hook_line": script.get("hook_line"),
            "framework": script.get("framework"),
            "total_duration_sec": script.get("total_duration_sec"),
            "cta_line": script.get("cta_line"),
            "scenes": [
                {
                    "n": sc.get("scene_number"),
                    "duration_sec": sc.get("duration_sec"),
                    "purpose": sc.get("purpose"),
                    "shot_type": sc.get("shot_type"),
                    "voiceover": sc.get("voiceover"),
                    "on_screen_text": sc.get("on_screen_text"),
                    "emotion": sc.get("emotion"),
                }
                for sc in script.get("scenes", [])
            ],
        })
    return items, tally


def run(product: str | None = None, dry_run: bool = False, today=None, log=print) -> dict:
    """
    تشغيلة تعلّم وحدة. بيرجع:
      {ok, at, results:[{pattern_id,name,evidence_strength}], skipped_reason, error, called_llm, ...}
    ما بيرمي على أخطاء المزوّد — بيسجّلها بـ error (عشان الجدولة ما تنهار).
    """
    now = datetime.now().isoformat(timespec="seconds")
    res = {"ok": False, "at": now, "results": [], "skipped_reason": None, "error": None,
           "called_llm": False, "winners": 0, "losers": 0, "added": 0, "duplicates": 0}

    def finish() -> dict:
        if not dry_run:
            st = load_state()
            st["last_run"] = {k: res[k] for k in ("at", "ok", "results", "skipped_reason", "error")}
            if res["called_llm"] and res["ok"]:
                st["last_success"] = now
            _save_state(st)
        return res

    items, tally = collect(product, today)
    res["winners"], res["losers"] = tally["winner"], tally["loser"]
    judged = tally["winner"] + tally["loser"]
    log(f"[i] سيناريوهات محكوم عليها بأداء فعلي: {judged} (ناجح {tally['winner']} · فاشل {tally['loser']})")

    gate = f"الحكم بيلزمه ≥ {evidence.min_delivered()} طلب مُسلَّم للسيناريو وخط أساس لنفس المنتج والبلد."
    if judged < MIN_JUDGED:
        res["skipped_reason"] = (f"بدنا {MIN_JUDGED} سيناريوهات محكوم عليها (ناجح/فاشل) ع الأقل، "
                                 f"والحالي {judged}. " + gate)
        return finish()
    if tally["winner"] == 0:
        res["skipped_reason"] = "ما في ولا سيناريو ناجح فعلياً — ما في شي نتعلّم منه بعد. " + gate
        return finish()
    if tally["loser"] == 0:
        log("    [i] ما في سيناريوهات فاشلة للمقارنة — الاستنتاج رح يكون أضعف.")

    import taxonomy
    prompt = taxonomy.inject_vocab((Path(config.PROMPTS_DIR) / "pattern_learner.txt").read_text(encoding="utf-8"))
    payload = json.dumps(items, ensure_ascii=False, indent=2)

    try:
        cfg = llm.task_config("analysis")
        log(f"[…] تحليل الأداء ({cfg['provider']} · {cfg['model']})…")
        res["called_llm"] = True
        learned = llm.complete_json(
            "analysis", prompt,
            [{"type": "text", "text": f"## السيناريوهات ونتايجها\n{payload}"}],
            MAX_OUTPUT_TOKENS,
        )
    except Exception as e:  # LLMError أو أخطاء المزوّد — منسجّلها وما بننهار
        from llm_errors import friendly
        res["error"] = friendly(e) or str(e)
        return finish()

    if not isinstance(learned, list):
        learned = [learned]
    if not learned:
        log("[i] ما لقى فرق واضح بين الناجح والفاشل — ما في نمط جديد.")
        res["ok"] = True
        return finish()

    import pattern_dedupe
    import review_queue
    patterns_dir = Path(config.PATTERNS_DIR)
    library = pattern_dedupe.load_library(patterns_dir)

    for p in learned:
        if not isinstance(p, dict):
            continue
        name = str(p.get("pattern_name", "")).strip()
        if not name:
            continue
        p, tax_issues = taxonomy.apply_to_pattern(p)

        matches = pattern_dedupe.find_duplicates(p, library)
        if matches and matches[0]["is_duplicate"]:
            log(f"   = متخطّى (مكرر): {name}")
            log("     " + pattern_dedupe.describe(matches).replace("\n", "\n     "))
            res["duplicates"] += 1
            continue
        if matches:
            p["_similar_to"] = matches

        p["_source"] = {
            "type": "proven",        # مبني على أدائك الفعلي — أقوى من المستخرج والمكتوب
            "learned_at": now,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "evidence": {
                "winners": tally["winner"], "ok": 0, "losers": tally["loser"],
                "scripts": p.get("evidence_scripts", []),
                "basis": "delivered_cost_vs_baseline",
            },
        }
        out = patterns_dir / f"proven_{slug(name)}.pattern.json"
        pid = out.name.replace(".pattern.json", "")
        if not dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
            for i in tax_issues:
                review_queue.add(i["kind"], pid, i["raw"], i["candidates"], i["note"], i["applied"])
            import pattern_i18n
            pattern_i18n.translate_new(pid)                      # عربي لحاله؛ لو فشل بيضل إنجليزي وزر المكتبة بيكمّل
        p["_pattern_id"] = pid
        library.append(p)
        res["added"] += 1
        res["results"].append({"pattern_id": pid, "name": name,
                               "evidence_strength": p.get("evidence_strength", "؟")})
        log(f"   + {name}  (قوة الدليل: {p.get('evidence_strength', '؟')}) → {out.name}")

    if res["added"] and not dry_run:
        try:
            import clusters
            clusters.apply(patterns_dir)
        except Exception as e:
            log(f"    [i] تعذّر تحديث العناقيد: {e}")

    res["ok"] = True
    verb = "رح ينضاف" if dry_run else "انضاف"
    log(f"\n[✓] {verb}: {res['added']} نمط مثبَت | متخطّى كمكرر: {res['duplicates']}")
    return finish()


def run_weekly_if_due(now: datetime | None = None, force: bool = False, log=print) -> dict:
    """
    بيشتغل لو مرّ ≥7 أيام على آخر تشغيل ناجح — وإذا الجهاز كان مطفي بيشتغل أول ما يرجع.
    بيرجع {"ran": bool, "reason"?: str, ...نتيجة run}.
    """
    now = now or datetime.now()
    last = load_state().get("last_success")
    if last and not force:
        try:
            age = now - datetime.fromisoformat(last)
        except ValueError:
            age = timedelta(days=WEEKLY_DAYS)
        if age < timedelta(days=WEEKLY_DAYS):
            return {"ran": False, "reason": f"آخر تشغيل ناجح قبل {age.days} يوم — التالي بعد أسبوع من آخر نجاح"}
    return {"ran": True, **run(today=now.date(), log=log)}


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="استخراج أنماط من الأداء الفعلي")
    ap.add_argument("--product", help="اقتصر على منتج واحد")
    ap.add_argument("--dry-run", action="store_true", help="اعرض بدون حفظ")
    ap.add_argument("--weekly", action="store_true", help="شغّل فقط لو مرّ ≥7 أيام على آخر نجاح")
    args = ap.parse_args()

    if args.weekly:
        r = run_weekly_if_due()
        if not r["ran"]:
            print(f"[i] {r['reason']}")
            return
    else:
        r = run(args.product, args.dry_run)

    if r.get("error"):
        sys.exit(f"[!] {r['error']}")
    if r.get("skipped_reason"):
        if args.weekly:
            print(f"[i] {r['skipped_reason']}")
            return
        sys.exit(f"[!] {r['skipped_reason']}")


if __name__ == "__main__":
    main()
