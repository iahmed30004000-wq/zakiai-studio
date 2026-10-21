#!/usr/bin/env python3
"""
استيراد أنماط من مستندات نصية (برومبتات، أدلة كتابة، مكتبات أطر).

مكمّل للمرحلة 2: هديك بتستخرج الأنماط من فيديوهات حقيقية، وهاي بتستخرجها
من معرفة مكتوبة. الأنماط المستوردة بتتعلّم بـ _source.type = "authored"
عشان يضل واضح مين مبني على إعلان ناجح فعلي ومين مكتوب يدوياً.

    python import_patterns.py "C:/path/doc.txt"
    python import_patterns.py doc1.txt doc2.txt --dry-run
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import PATTERNS_DIR, PROMPTS_DIR, MODEL_ANALYSIS, MAX_OUTPUT_TOKENS
from llm_errors import exit_on_api_error
import llm
import taxonomy


def client():
    try:
        import anthropic
    except ImportError:
        sys.exit("[!] ثبّت anthropic:  pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("[!] حدّد المفتاح:  setx ANTHROPIC_API_KEY sk-...")
    return anthropic.Anthropic()


def slug(text: str) -> str:
    text = re.sub(r"[^\w\u0600-\u06FF]+", "_", str(text).strip().lower())
    return re.sub(r"_+", "_", text).strip("_")[:50] or "pattern"




def extract(doc_text: str, doc_name: str) -> list[dict]:
    import taxonomy
    prompt = taxonomy.inject_vocab((Path(PROMPTS_DIR) / "pattern_importer.txt").read_text(encoding="utf-8"))
    blocks = [{"type": "text", "text": f"## المستند: {doc_name}\n\n{doc_text}"}]
    try:
        data = llm.complete_json("importer", prompt, blocks, MAX_OUTPUT_TOKENS)
    except llm.LLMError as exc:
        sys.exit(f"[!] {exc}")
    return data if isinstance(data, list) else [data]


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="استيراد أنماط من مستندات نصية")
    ap.add_argument("docs", nargs="+", help="مسارات المستندات")
    ap.add_argument("--dry-run", action="store_true", help="اعرض بدون حفظ")
    args = ap.parse_args()

    import pattern_dedupe
    library = pattern_dedupe.load_library(PATTERNS_DIR)
    print(f"[i] المكتبة فيها {len(library)} نمط حالياً\n")
    added = skipped = 0

    for doc_path in args.docs:
        path = Path(doc_path)
        if not path.exists():
            print(f"[!] غير موجود: {path}")
            continue

        print(f"── {path.name} ──")
        patterns = extract(path.read_text(encoding="utf-8", errors="replace"), path.name)
        if not patterns:
            print("   ما في أنماط قابلة للاستخراج\n")
            continue

        for p in patterns:
            name = str(p.get("pattern_name", "")).strip()
            if not name:
                continue

            matches = pattern_dedupe.find_duplicates(p, library)
            if matches and matches[0]["is_duplicate"]:
                print(f"   = متخطّى (مكرر): {name}")
                print("     " + pattern_dedupe.describe(matches).replace("\n", "\n     "))
                skipped += 1
                continue
            if matches:
                p["_similar_to"] = matches
                print(f"   ! قريب من موجود بس مش مكرر: {name}")
                print("     " + pattern_dedupe.describe(matches).replace("\n", "\n     "))

            p, tax_issues = taxonomy.apply_to_pattern(p)
            p["_source"] = {
                "type": "authored",          # مقابل الأنماط المستخرجة من فيديو
                "document": path.name,
                "imported_at": datetime.now().isoformat(timespec="seconds"),
                "model": MODEL_ANALYSIS,
            }
            out = Path(PATTERNS_DIR) / f"doc_{slug(name)}.pattern.json"
            if not args.dry_run:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
            # ضيفه للمكتبة بالذاكرة عشان الأنماط الجاية بنفس المستند تتقارن معه
            p["_pattern_id"] = out.name.replace(".pattern.json", "")
            if not args.dry_run:
                import pattern_i18n
                import review_queue
                for i in tax_issues:
                    review_queue.add(i["kind"], p["_pattern_id"], i["raw"], i["candidates"], i["note"], i["applied"])
                pattern_i18n.translate_new(p["_pattern_id"])      # عربي لحاله؛ لو فشل بيضل إنجليزي وزر المكتبة بيكمّل
            library.append(p)
            added += 1
            print(f"   + {name}  ({p.get('framework')}) → {out.name}")
        print()

    if added and not args.dry_run:
        import clusters
        clusters.apply()
    verb = "رح ينضاف" if args.dry_run else "انضاف"
    print(f"[✓] {verb}: {added} نمط | متخطّى كمكرر: {skipped}")
    if args.dry_run:
        print("    (تشغيل تجريبي — ما انحفظ شي)")


if __name__ == "__main__":
    main()
