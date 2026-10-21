#!/usr/bin/env python3
"""
STAGE 2 — PATTERN MINER
يقرأ مخرج المرحلة 1 (extract.json + اللقطات) ويشرّح الفيديو إلى "بصمة نمط"
محفوظة كملف JSON مستقل داخل library/patterns/.

الاستخدام:
    python stage2_pattern.py library/raw/clarden_v3/extract.json
    python stage2_pattern.py --all
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# كونسول ويندوز افتراضياً cp1252 وبيفشل مع العربي
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import (
    RAW_DIR,
    PATTERNS_DIR,
    PROMPTS_DIR,
    MODEL_ANALYSIS,
    MAX_FRAMES_PER_VIDEO,
    MAX_OUTPUT_TOKENS,
)
from llm_errors import exit_on_api_error
import llm


def pick_frames(scenes: list, base: Path) -> list:
    """يختار لقطات موزّعة على طول الفيديو بحد أقصى MAX_FRAMES_PER_VIDEO."""
    frames = [(sc["index"], base / sc["frame"]) for sc in scenes if sc.get("frame")]
    frames = [(i, p) for i, p in frames if p.exists()]
    if len(frames) <= MAX_FRAMES_PER_VIDEO:
        return frames
    step = len(frames) / MAX_FRAMES_PER_VIDEO
    return [frames[int(i * step)] for i in range(MAX_FRAMES_PER_VIDEO)]


def build_content(data: dict, base: Path) -> list:
    scenes_brief = [
        {
            "scene": sc["index"],
            "start": sc["start"],
            "end": sc["end"],
            "duration": sc["duration"],
            "voiceover": sc.get("voiceover", ""),
            "on_screen_text": sc.get("on_screen_text", []),
        }
        for sc in data["scenes"]
    ]

    content = [{
        "type": "text",
        "text": (
            "## VIDEO DATA\n"
            f"video_id: {data['video_id']}\n"
            f"duration_sec: {data['meta'].get('duration_sec')}\n"
            f"aspect: {data['meta'].get('aspect')}\n"
            f"engagement: views={data['meta'].get('views')} likes={data['meta'].get('likes')} "
            f"comments={data['meta'].get('comments')}\n"
            f"caption: {(data['meta'].get('caption') or '')[:600]}\n"
            f"detected_language: {data['transcript'].get('language')}\n"
            f"scene_count: {data['scene_count']}\n\n"
            "## FULL TRANSCRIPT\n"
            f"{data['transcript']['full_text']}\n\n"
            "## SCENE-BY-SCENE DATA (JSON)\n"
            f"{json.dumps(scenes_brief, ensure_ascii=False)}\n\n"
            "## KEYFRAMES\n"
            "Each image below is the keyframe of the scene number stated before it."
        ),
    }]

    for idx, path in pick_frames(data["scenes"], base):
        content.append({"type": "text", "text": f"--- KEYFRAME OF SCENE {idx} ---"})
        # الشكل الموحّد لـ llm.py — هي بتترجمه لصيغة المزوّد
        content.append({
            "type": "image",
            "media_type": "image/jpeg",
            "data": base64.b64encode(path.read_bytes()).decode(),
        })

    return content


SKIP_DUPLICATES = False   # بتتظبط من سطر الأوامر


class MiningError(Exception):
    """فشل تحليل نمط فيديو واحد — ما بيوقف الدفعة."""


def mine(extract_path: Path) -> Path:
    data = json.loads(extract_path.read_text(encoding="utf-8"))
    base = extract_path.parent
    import taxonomy
    prompt = taxonomy.inject_vocab((Path(PROMPTS_DIR) / "pattern_miner.txt").read_text(encoding="utf-8"))

    cfg = llm.task_config("analysis")
    print(f"[…] تشريح: {data['video_id']}  ({cfg['provider']} · {cfg['model']})")
    try:
        pattern = llm.complete_json("analysis", prompt, build_content(data, base), MAX_OUTPUT_TOKENS)
    except llm.LLMError as e:
        raise MiningError(str(e)) from e

    pattern["_source"] = {
        "video_id": data["video_id"],
        "source": data["meta"].get("source"),
        "duration_sec": data["meta"].get("duration_sec"),
        "views": data["meta"].get("views"),
        "likes": data["meta"].get("likes"),
        "mined_at": datetime.now().isoformat(timespec="seconds"),
        "provider": cfg["provider"],
        "model": cfg["model"],
    }

    # تصنيف مغلق: القيمة اللي ما انطابقت بشكل قاطع بتروح لطابور المراجعة
    pattern, tax_issues = taxonomy.apply_to_pattern(pattern)

    # فحص التكرار قبل الحفظ — مجاني، بدون أي نداء API
    import pattern_dedupe
    matches = pattern_dedupe.find_duplicates(pattern, pattern_dedupe.load_library(PATTERNS_DIR))
    if matches:
        pattern["_similar_to"] = matches
        print(pattern_dedupe.describe(matches))
        if matches[0]["is_duplicate"] and SKIP_DUPLICATES:
            print("    [=] ما انحفظ (مكرر) — شيل --skip-duplicates إذا بدك تحفظه برضو")
            return None

    out = Path(PATTERNS_DIR) / f"{data['video_id']}.pattern.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pattern, ensure_ascii=False, indent=2), encoding="utf-8")
    import clusters, pattern_i18n, review_queue
    for i in tax_issues:
        review_queue.add(i["kind"], data["video_id"], i["raw"], i["candidates"], i["note"], i["applied"])
    pattern_i18n.translate_new(data["video_id"])          # عربي لحاله؛ لو فشل النمط محفوظ بالإنجليزي وزر المكتبة بيكمّل
    clusters.apply()
    print(f"[✓] النمط: {pattern.get('pattern_name', '—')}  →  {out}")
    if any(not i["applied"] for i in tax_issues):
        print(f"    [i] {sum(1 for i in tax_issues if not i['applied'])} قيمة تصنيف بانتظار مراجعتك")
    return out


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 2 — استخراج نمط الفيديو")
    ap.add_argument("extract", nargs="?", help="مسار extract.json")
    ap.add_argument("--all", action="store_true", help="عالج كل الفيديوهات غير المحلّلة")
    ap.add_argument("--limit", type=int, help="حد أقصى لعدد الفيديوهات بهالتشغيلة (للعينات)")
    ap.add_argument("--skip-duplicates", action="store_true",
                    help="لا تحفظ النمط إذا طلع مكرر لنمط موجود")
    args = ap.parse_args()

    global SKIP_DUPLICATES
    SKIP_DUPLICATES = args.skip_duplicates

    if args.all:
        done = {p.name.replace(".pattern.json", "") for p in Path(PATTERNS_DIR).glob("*.pattern.json")}
        todo = sorted(p for p in Path(RAW_DIR).glob("*/extract.json") if p.parent.name not in done)
        if not todo:
            print("[i] ما في جديد للتحليل.")
            return
        if args.limit:
            todo = todo[: args.limit]
        failures = []
        for i, p in enumerate(todo, 1):
            print(f"\n===== [{i}/{len(todo)}] =====", flush=True)
            try:
                mine(p)
            except Exception as e:
                print(f"[!] فشل {p.parent.name}: {e}", flush=True)
                failures.append(p.parent.name)
        ok = len(todo) - len(failures)
        print(f"\n[✓] انتهى: {ok} نجح، {len(failures)} فشل")
        if failures:
            print("    الفاشلة:", ", ".join(failures))
        # فشل كامل لازم يظهر كفشل للمشغّل، مش كنجاح
        if failures and ok == 0:
            sys.exit("[!] كل العناصر فشلت — شوف الأخطاء فوق")
    elif args.extract:
        try:
            mine(Path(args.extract))
        except MiningError as e:
            sys.exit(f"[!] {e}")
    else:
        ap.error("لازم تمرّر مسار extract.json أو --all")


if __name__ == "__main__":
    main()
