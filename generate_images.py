#!/usr/bin/env python3
"""
مرحلة الصور — مربوطة بالفويس أوفر.

المنطق: كل مشهد بياخد لقطة رئيسية. والمشهد اللي مدته الصوتية أطول من
SEC_PER_SHOT بياخد **لقطات دخيلة** إضافية تغطّي باقي الكلام — لأن اللقطة
الثابتة بتموت بصرياً بعد ثواني، فبتضل الكلمات بلا صورة تخدمها.

المدد بتنقرا من مانيفست الفويس أوفر لما يكون موجود (المدة الفعلية)، وإلا
من مدد السيناريو المخطّطة.

ممنوع أي كتابة داخل الصور — النص بينحط بالمونتاج.

    python generate_images.py library/scripts/VARA__x__2026.json
    python generate_images.py <script> --scene 3 --shot 2
"""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import LIBRARY_DIR, PROMPTS_DIR, MAX_OUTPUT_TOKENS
import imagegen
import llm
import review_loop

IMAGE_DIR = Path(LIBRARY_DIR) / "images"
VOICE_DIR = Path(LIBRARY_DIR) / "voice"

SEC_PER_SHOT = 3.5      # فوقها بيصير المشهد بدّه لقطة إضافية
MAX_SHOTS = 4           # سقف اللقطات بالمشهد الواحد


def actual_durations(script_stem: str) -> dict[int, float]:
    """المدد الفعلية من الفويس أوفر إذا اتولّد."""
    mf = VOICE_DIR / script_stem / "voice.json"
    if not mf.exists():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {s["scene"]: s["duration_sec"] for s in data.get("scenes", [])}


def shots_needed(duration: float) -> int:
    return max(1, min(MAX_SHOTS, math.ceil(duration / SEC_PER_SHOT)))


def fallback_shots(scene: dict, duration: float, count: int) -> list[dict]:
    """احتياط لما التخطيط يفشل — الوصف الأصلي بدل ما نوقف."""
    return [{"index": i + 1, "role": "hero" if i == 0 else "insert",
             "covers_vo": scene.get("voiceover", ""),
             "duration_sec": round(duration / count, 2),
             "prompt": scene.get("visual", "")} for i in range(count)]


def plan_all_shots(scenes: list[dict], durations: dict[int, float],
                   counts: dict[int, int]) -> dict[int, list[dict]]:
    """
    يخطّط كل المشاهد **بنداء واحد**.

    نداء لكل مشهد كان بياخد 7 جولات ذهاب وإياب للسيناريو الواحد، وكمان
    بيمنع الموديل من رؤية باقي المشاهد — فبيكرّر نفس اللقطة بمشهدين.
    """
    # المشاهد اللي بدها لقطة وحدة ما بتحتاج موديل أصلاً
    need_plan = [s for s in scenes if counts[s["scene_number"]] > 1]
    out = {s["scene_number"]: fallback_shots(s, durations[s["scene_number"]], 1)
           for s in scenes if counts[s["scene_number"]] == 1}
    if not need_plan:
        return out

    prompt = (Path(PROMPTS_DIR) / "shot_planner.txt").read_text(encoding="utf-8")
    payload = [{
        "scene_number": s["scene_number"],
        "visual": s.get("visual"),
        "voiceover": s.get("voiceover"),
        "shot_type": s.get("shot_type"),
        "emotion": s.get("emotion"),
        "duration_sec": durations[s["scene_number"]],
        "shots_required": counts[s["scene_number"]],
    } for s in need_plan]

    cfg = llm.task_config("shotplan")
    print(f"[…] تخطيط {len(need_plan)} مشهد بنداء واحد ({cfg['provider']} · {cfg['model']})…",
          flush=True)
    try:
        result = llm.complete_json(
            "shotplan", prompt,
            [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            MAX_OUTPUT_TOKENS,
        )
        planned = {int(sc.get("scene_number", 0)): sc.get("shots") or []
                   for sc in (result.get("scenes") or [])}
    except (llm.LLMError, ValueError, TypeError) as e:
        print(f"    [!] فشل التخطيط ({e}) — بستخدم الأوصاف الأصلية")
        planned = {}

    for s in need_plan:
        n = s["scene_number"]
        shots = planned.get(n) or []
        # عدد غلط = خطة مكسورة، الاحتياط أأمن من لقطات ناقصة
        if len(shots) != counts[n]:
            if shots:
                print(f"    [!] مشهد {n}: رجّع {len(shots)} لقطة والمطلوب {counts[n]} — احتياط")
            shots = fallback_shots(s, durations[n], counts[n])
        out[n] = shots
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="توليد صور المشاهد")
    ap.add_argument("script")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--size")
    ap.add_argument("--scene", type=int, help="مشهد واحد بس")
    ap.add_argument("--shot", type=int, help="لقطة وحدة بس (مع --scene)")
    ap.add_argument("--plan-only", action="store_true", help="خطّط بدون ما تولّد صور")
    ap.add_argument("--character", help="معرّف مرجع الشخصية")
    ap.add_argument("--product-ref", help="معرّف مرجع المنتج")
    ap.add_argument("--no-refs", action="store_true", help="ولّد بدون أي مرجع")
    ap.add_argument("--keep-plan", action="store_true",
                    help="استخدم الخطة المحفوظة بدل ما تعيد التخطيط")
    args = ap.parse_args()

    path = Path(args.script)
    if not path.exists():
        sys.exit(f"[!] السيناريو غير موجود: {path}")
    _ok, _why = review_loop.is_cleared(path)
    if not _ok:
        sys.exit(f"[!] ما بيشتغل: {_why}. الإنتاج بيبدأ بعد مراجعة بعوائق = 0 وبمحتوى ما انعدّل بعدها.")
    import voice_studio
    _vok, _vwhy = voice_studio.voice_is_approved(path)
    if not _vok:       # الصوت هو الساعة: ولا صورة قبل فويس أوفر معتمد بمدة ٤٥–٥٠ ثانية
        sys.exit(f"[!] ما في صورة قبل فويس أوفر معتمد: {_vwhy}. اعتمده من شاشة «الإنتاج» (محطة 4).")
    script = json.loads(path.read_text(encoding="utf-8"))

    overrides = {k: v for k, v in {"provider": args.provider, "model": args.model,
                                   "size": args.size}.items() if v}
    cfg = imagegen.image_config(overrides)
    print(f"[i] {cfg['provider']} · {cfg['model']} · {cfg['size']}")

    actual = actual_durations(path.stem)
    print(f"[i] مدد الصوت الفعلية: {'موجودة' if actual else 'غير متوفرة — بستخدم المخطّطة'}")

    # المراجع: الشخصية أولاً ثم المنتج — ثبات الوجه أصعب فبياخد الإشارة الأقوى
    ref_paths, ref_info = [], []
    if not args.no_refs:
        import assets
        product_name = (script.get("_meta") or {}).get("product", "")
        for a in assets.refs_for(product_name, args.character or "", args.product_ref or ""):
            p = assets.path_of(a["id"])
            if p:
                ref_paths.append(p)
                ref_info.append({"id": a["id"], "kind": a["kind"], "label": a.get("label")})
    if ref_info:
        print("[i] المراجع: " + " ← ".join(f"{r['kind']}:{r['label']}" for r in ref_info))
    else:
        print("[i] بدون مراجع — الشكل ممكن يتغيّر بين اللقطات")

    # خطة محفوظة (لإعادة توليد لقطة بنفس وصفها بالضبط)
    saved_plan = {}
    if args.keep_plan:
        pf = IMAGE_DIR / path.stem / "images.json"
        if pf.exists():
            try:
                for s in json.loads(pf.read_text(encoding="utf-8")).get("scenes", []):
                    saved_plan[s["scene"]] = s.get("shots", [])
            except json.JSONDecodeError:
                pass

    out_dir = IMAGE_DIR / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes = script.get("scenes", [])
    if args.scene:
        scenes = [s for s in scenes if s.get("scene_number") == args.scene]
        if not scenes:
            sys.exit(f"[!] ما في مشهد رقم {args.scene}")

    # احسب المدد والأعداد أولاً، ثم خطّط الكل بنداء واحد
    durations = {sc["scene_number"]: (actual.get(sc["scene_number"])
                                      or float(sc.get("duration_sec") or 0)) for sc in scenes}
    counts = {n: shots_needed(d) for n, d in durations.items()}
    to_plan = [sc for sc in scenes if sc["scene_number"] not in saved_plan]
    plans = plan_all_shots(to_plan, durations, counts) if to_plan else {}

    manifest_scenes, failures = [], 0
    for sc in scenes:
        n = sc.get("scene_number")
        dur, count = durations[n], counts[n]
        extra = count - 1
        print(f"\n  مشهد {n} — {dur}ث → {count} لقطة"
              + (f" (منها {extra} دخيلة)" if extra else ""))

        shots = saved_plan.get(n) or plans.get(n) or fallback_shots(sc, dur, count)
        entries = []
        for shot in shots:
            i = shot.get("index", 1)
            if args.shot and i != args.shot:
                entries.append(shot)          # خلّي الباقي متل ما هو
                continue
            entry = {k: v for k, v in shot.items() if k not in ("error",)}
            entry["scene"] = n
            if not args.plan_only:
                # رقم نسخة عشان إعادة التوليد ما تدهس القديمة
                ver = int(shot.get("version", 0)) + 1
                target = out_dir / f"scene_{n:02d}_shot_{i:02d}_v{ver}.png"
                print(f"    [{shot.get('role','shot')}] لقطة {i} (نسخة {ver})…", flush=True)
                try:
                    r = imagegen.generate(shot["prompt"], target, overrides, refs=ref_paths)
                    entry.update({"file": target.name, "version": ver,
                                  "final_prompt": r["prompt"], "refs_used": r["refs_used"]})
                except imagegen.ImageError as e:
                    print(f"       [!] {e}")
                    entry["error"] = str(e)
                    failures += 1
            entries.append(entry)
        manifest_scenes.append({"scene": n, "duration_sec": dur,
                                "shot_count": len(entries), "shots": entries})

    mf = out_dir / "images.json"
    old = {}
    if mf.exists():
        try:
            old = json.loads(mf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}

    if args.scene and old.get("scenes"):
        by = {s["scene"]: s for s in old["scenes"]}
        by.update({s["scene"]: s for s in manifest_scenes})
        manifest_scenes = sorted(by.values(), key=lambda s: s["scene"])

    total_shots = sum(s["shot_count"] for s in manifest_scenes)
    mf.write_text(json.dumps({
        "script": path.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": cfg["provider"], "model": cfg["model"], "size": cfg["size"],
        "durations_from": "voice" if actual else "script",
        "refs": ref_info,
        "total_shots": total_shots,
        "scenes": manifest_scenes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[✓] {total_shots} لقطة" + (f" · {failures} فشلت" if failures else ""))
    print(f"    {out_dir}")
    if failures and failures == total_shots:
        sys.exit("[!] كل اللقطات فشلت")


if __name__ == "__main__":
    main()
