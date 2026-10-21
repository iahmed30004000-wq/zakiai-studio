#!/usr/bin/env python3
"""
مرحلة التدقيق — بين التوليد والإنتاج.

بتدقّق السيناريو على: الحساب (المدد وإيقاع الكلام)، اللهجة والإملاء، سلامة
الادعاءات، الالتزام ببنية النمط، التماسك، وقابلية التصوير.

الفحوصات الحسابية بتنعمل **محلياً** قبل ما نسأل الموديل — لأن العدّ شغل آلة
مش شغل موديل لغوي، والنتيجة بتنبعتله كمرجع عشان ما يجادل بالأرقام.

    python review_script.py library/scripts/VARA__x__2026.json
    python review_script.py --all-pending
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import brief as brief_mod
import claims
import config
import pattern_store
import pattern_text
import script_hooks
import script_versions
from config import SCRIPT_SCENES, SCRIPT_MIN_SEC, SCRIPT_MAX_SEC, MAX_OUTPUT_TOKENS
from llm_errors import exit_on_api_error
import llm


def review_dir() -> Path:
    return Path(config.SCRIPTS_DIR).parent / "reviews"

WPS_MIN, WPS_MAX = 2.0, 2.7     # كلمات بالثانية — مدى النطق العربي الطبيعي


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def load_brief(script: dict) -> dict | None:
    """بريف المنتج: من `_meta.product_file`، وللسيناريوهات القديمة بالبحث باسم المنتج."""
    meta = script.get("_meta") or {}
    pdir = Path(config.PRODUCTS_DIR)
    pf = meta.get("product_file")
    if pf:
        path = pdir / Path(pf).name
        if path.exists():
            try:
                return brief_mod.load(path)
            except (json.JSONDecodeError, OSError):
                return None
        return None
    if meta.get("product"):
        for f in sorted(pdir.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if d.get("product_name") == meta["product"]:
                return brief_mod.load(f)
    return None


def local_checks(script: dict, brief: dict | None = None) -> list[dict]:
    """
    فحوصات قاطعة بالكود — ما بتحتاج موديل ولا بتحتمل خلاف: الحساب (المدد والإيقاع)
    وقواعد البريف (claims.scan_script). كل مخالفة قاعدة = blocker.
    """
    out = _arithmetic_checks(script)
    meta = script.get("_meta") or {}
    if brief is None:
        brief = load_brief(script)
        if brief is None and (meta.get("product_file") or meta.get("product")):
            out.append({
                "severity": "blocker", "scene": None, "field": "general", "axis": "claim_safety",
                "issue": "ما لقيت بريف المنتج — ما بقدر أتحقق من سلامة الادعاءات",
                "evidence": str(meta.get("product_file") or meta.get("product")),
                "fix": "تأكد إنو ملف المنتج موجود بمجلد products وإنو مربوط بالسيناريو",
            })
    if brief is not None:
        for f in claims.scan_script(script, brief):
            f.setdefault("axis", "claim_safety")
            out.append(f)
    # الهوكات البديلة: نفس قواعد البريف + مدى النطق + نص الشاشة. كل ملاحظة عليها hook_id وما بتمنع موافقة الأساسي.
    main = script_hooks.main_id(script)
    for hid, rows in script_hooks.check(script, brief).items():
        if hid != main:
            for f in rows:
                f.setdefault("axis", "claim_safety" if f.get("rule") else "shootability" if f.get("field") == "on_screen_text" else "arithmetic")
                out.append(f)
    return out


def is_hook_finding(f) -> bool:
    """ملاحظة على هوك بديل (مش على السيناريو الأساسي): ما بتدخل بعدّاد الموانع ولا بالحكم."""
    return isinstance(f, dict) and bool(f.get("hook_id"))


def count_main(findings: list, severity: str) -> int:
    return sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == severity and not is_hook_finding(f))


def _arithmetic_checks(script: dict) -> list[dict]:
    out = []
    scenes = script.get("scenes", [])

    if len(scenes) != SCRIPT_SCENES:
        out.append({
            "severity": "blocker", "scene": None, "field": "general",
            "issue": f"عدد المشاهد {len(scenes)} والمطلوب {SCRIPT_SCENES}",
            "evidence": f"{len(scenes)} مشاهد", "fix": "أعد التوليد بالعدد الصحيح",
        })

    total = sum(float(s.get("duration_sec") or 0) for s in scenes)
    declared = float(script.get("total_duration_sec") or 0)
    if abs(total - declared) > 0.5:
        out.append({
            "severity": "blocker", "scene": None, "field": "duration",
            "issue": "مجموع مدد المشاهد ما بيساوي المدة المعلنة",
            "evidence": f"المجموع {total:.1f}ث والمعلن {declared:.1f}ث",
            "fix": f"صحّح total_duration_sec إلى {total:.1f}",
        })
    if not (SCRIPT_MIN_SEC <= total <= SCRIPT_MAX_SEC):
        out.append({
            "severity": "blocker", "scene": None, "field": "duration",
            "issue": f"المدة الكلية برّا المدى المطلوب {SCRIPT_MIN_SEC}–{SCRIPT_MAX_SEC}ث",
            "evidence": f"{total:.1f}ث",
            "fix": "وزّع الفرق على المشاهد الأطول",
        })

    for s in scenes:
        dur = float(s.get("duration_sec") or 0)
        words = word_count(s.get("voiceover"))
        if dur <= 0:
            continue
        wps = words / dur
        if wps > WPS_MAX:
            needed = round(words / WPS_MAX, 1)
            out.append({
                "severity": "blocker", "scene": s.get("scene_number"), "field": "voiceover",
                "issue": f"الكلام أسرع من الممكن نطقه ({wps:.1f} كلمة/ث)",
                "evidence": f"{words} كلمة بـ{dur}ث",
                "fix": f"اختصر لـ{int(dur * WPS_MAX)} كلمة أو مدّد المشهد لـ{needed}ث",
            })
        elif wps < WPS_MIN and words > 0:
            out.append({
                "severity": "minor", "scene": s.get("scene_number"), "field": "voiceover",
                "issue": f"الكلام أبطأ من الطبيعي ({wps:.1f} كلمة/ث) — في وقت ميّت",
                "evidence": f"{words} كلمة بـ{dur}ث",
                "fix": f"زيد المحتوى لـ{int(dur * WPS_MIN)} كلمة أو قصّر المشهد",
            })

        ost = word_count(s.get("on_screen_text"))
        if ost > 5:
            out.append({
                "severity": "major", "scene": s.get("scene_number"), "field": "on_screen_text",
                "issue": f"نص الشاشة {ost} كلمات والحد 5",
                "evidence": s.get("on_screen_text", ""),
                "fix": "اختصره لأقصر جملة تنقري بلمحة",
            })
    for f in out:
        f.setdefault("axis", "shootability" if f.get("field") == "on_screen_text" else "arithmetic")
    return out


def load_context(script: dict) -> tuple[dict, dict]:
    meta = script.get("_meta") or {}
    product = load_brief(script) or {}

    pattern = {}
    pid = meta.get("pattern_id")
    if pid:
        try:
            pattern = pattern_text.for_model(pattern_store.load_any(str(pid)) or {})
        except json.JSONDecodeError:
            pass
    return product, pattern


def review(script_path: Path, rounds: int = 0) -> dict:
    """
    يدقّق سيناريو ويحفظ ملف المراجعة. بيرمي llm.LLMError لو الموديل فشل
    (الـCLI بيحوّله لرسالة، وحلقة المراجعة بتمسكه).
    `script_hash` = بصمة المحتوى وقت المراجعة — بوابة الصور/الصوت بتقارنها بالسيناريو الحالي.
    """
    script_path = Path(script_path)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    product, pattern = load_context(script)

    local = local_checks(script, product or None)
    print(f"[…] فحوصات بالكود: {len(local)} ملاحظة")

    cfg = llm.task_config("reviewer")
    print(f"[…] تدقيق عبر {cfg['provider']} · {cfg['model']}…")

    prompt = (Path(config.PROMPTS_DIR) / "script_reviewer.txt").read_text(encoding="utf-8")
    rules = claims.writer_rules(product) if product else {}
    clean_product = {k: v for k, v in product.items() if not k.startswith("_")}
    user = (
        f"## REQUIRED SPEC\nscenes: {SCRIPT_SCENES} | duration: "
        f"{SCRIPT_MIN_SEC}-{SCRIPT_MAX_SEC}s | pacing: {WPS_MIN}-{WPS_MAX} words/sec\n\n"
        f"## SCRIPT\n{json.dumps(script, ensure_ascii=False, indent=2)}\n\n"
        f"## PRODUCT BRIEF\n{json.dumps(clean_product, ensure_ascii=False, indent=2)}\n\n"
        f"## HARD RULES FROM BRIEF (a violation is a blocker on the claim_safety axis)\n"
        f"{json.dumps(rules, ensure_ascii=False, indent=2)}\n\n"
        f"## PATTERN IT SHOULD EXECUTE\n{json.dumps(pattern, ensure_ascii=False, indent=2)}\n\n"
        f"## CHECKS ALREADY VERIFIED BY CODE (arithmetic + brief rules; treat as ground truth)\n"
        f"{json.dumps(local, ensure_ascii=False, indent=2)}"
    )

    result = llm.complete_json("reviewer", prompt, [{"type": "text", "text": user}],
                               MAX_OUTPUT_TOKENS)
    if not isinstance(result, dict):
        raise llm.LLMError("رد المدقّق مش كائن JSON")

    # الفحوصات المحلية أولاً دايماً — هي قاطعة
    findings = local + [f for f in result.get("findings", []) if isinstance(f, dict)]
    order = {"blocker": 0, "major": 1, "minor": 2}
    findings.sort(key=lambda f: order.get(f.get("severity"), 3))

    blockers = count_main(findings, "blocker")
    verdict = result.get("verdict", "revise")
    if blockers and verdict == "approve":
        verdict = "revise"       # ما بينفع يعتمد وفي مانع قاطع

    result.update({
        "verdict": verdict,
        "findings": findings,
        "blockers": blockers,
        "major": count_main(findings, "major"),
        "minor": count_main(findings, "minor"),
        "hook_blockers": sum(1 for f in findings if is_hook_finding(f) and f.get("severity") == "blocker"),
        "script_hash": script_versions.content_hash(script),
        "rounds": rounds,
        "_meta": {
            "script": script_path.name,
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
            "provider": cfg["provider"], "model": cfg["model"],
        },
    })

    out_dir = review_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{script_path.stem}.review.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store_hooks_review(script_path, script, result)

    print(f"[✓] الحكم: {verdict} | مانع {blockers} · مهم {result['major']} · بسيط {result['minor']}")
    print(f"    {out}")
    return result


def store_hooks_review(script_path: Path, script: dict, result: dict) -> int:
    """حكم المراجع على كل هوك بديل (hooks_review) بيتخزّن بالسيناريو مع بصمة نص الهوك (لو انعدّل بعدين بيصير قديم)."""
    rows = result.get("hooks_review")
    if not isinstance(rows, list) or not script_hooks.has_alternatives(script):
        return 0
    by, main = {h["id"]: h for h in script_hooks.hooks_of(script)}, script_hooks.main_id(script)
    now = datetime.now().isoformat(timespec="seconds")
    fresh = {}
    for r in rows:
        hid = r.get("id") if isinstance(r, dict) else None
        if hid in by and hid != main:
            verdict = str(r.get("verdict") or "").strip().lower()
            fresh[hid] = {"verdict": verdict if verdict in ("ok", "fix", "reject") else "fix",
                          "note": str(r.get("note") or "").strip()[:300], "fp": script_hooks.fingerprint(by[hid]), "at": now}
    if not fresh:
        return 0
    cur = json.loads(Path(script_path).read_text(encoding="utf-8"))          # نقرا من جديد: ما منكتب فوق تعديل صار بين الحين والحين
    cur["hooks_review"] = {**(cur.get("hooks_review") or {}), **fresh}
    Path(script_path).write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(fresh)


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="تدقيق السيناريو")
    ap.add_argument("script", nargs="?", help="مسار ملف السيناريو")
    ap.add_argument("--all-pending", action="store_true", help="دقّق كل سيناريو ما انداق بعد")
    args = ap.parse_args()

    if args.all_pending:
        done = {p.stem.replace(".review", "") for p in review_dir().glob("*.review.json")}
        todo = [p for p in sorted(Path(config.SCRIPTS_DIR).glob("*.json")) if p.stem not in done]
        if not todo:
            print("[i] ما في سيناريوهات جديدة للتدقيق.")
            return
        for i, p in enumerate(todo, 1):
            print(f"\n===== [{i}/{len(todo)}] {p.name} =====")
            try:
                review(p)
            except SystemExit:
                raise
            except llm.LLMError as e:
                sys.exit(f"[!] {e}")
            except Exception as e:
                print(f"[!] فشل: {e}")
    elif args.script:
        path = Path(args.script)
        if not path.exists():
            sys.exit(f"[!] الملف غير موجود: {path}")
        try:
            review(path)
        except llm.LLMError as e:
            sys.exit(f"[!] {e}")
    else:
        ap.error("مرّر مسار سيناريو أو --all-pending")


if __name__ == "__main__":
    main()
