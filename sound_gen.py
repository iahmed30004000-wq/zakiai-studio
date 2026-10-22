#!/usr/bin/env python3
"""
توليد موسيقى ومؤثرات صوتية بنماذج «مكتبة النماذج» — الناتج بينزل لمكتبة الأصوات «غير معتمد» (بينتظر سمعك) متل اللي بيرجع من الإضافة.

    python sound_gen.py request <السيناريو.json> <رقم_الطلب> [--model lib:ml_001]
        طلب معلّق بسيناريو (موسيقى أو آهة/مؤثر): بنولّده بنموذج المكتبة وبيتقفل الطلب بالنتيجة.
    python sound_gen.py free --kind music|ahat --prompt "…" [--seconds 30] [--name …] [--mood calm] [--model lib:ml_001]
        بلا سيناريو: مقطع جديد للمكتبة مباشرة.

قواعد ثابتة:
  · الموسيقى «بلا غناء ولا كلام» دايماً (الشرط بينضاف لوصفك لحاله) والمؤثر «نظيف بلا موسيقى».
  · بلا رجوع تلقائي لطريقة تانية: لو ما في نموذج مربوط أو وقع النموذج، الرسالة بتطلع (الصوت ما بيتبدّل بصمت).
  · ما بيدخل أي فيديو إلا بعد ما تسمعه وتعتمده بنفسك (نفس مسار الإضافة).
  · آهة/مؤثر = مهمة «المؤثرات» بمكتبة النماذج، والموسيقى = مهمة «الموسيقى».
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
from pathlib import Path

import model_library
import model_run
from ahat import MOODS

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TASK_OF = {"music": "music", "ahat": "sfx"}                       # نوع الطلب ← مهمة مكتبة النماذج
SUFFIX = {"music": "instrumental, no vocals, no lyrics", "ahat": "clean, isolated sound effect, no music"}
LABEL = {"music": "موسيقى", "ahat": "آهة/مؤثر"}
SECONDS_RANGE = {"ahat": (0.5, 30.0), "music": (5.0, 300.0)}       # نفس حدود طلبات الإضافة (ext_tasks.SECONDS_RANGE)
SECONDS_DEFAULT = {"ahat": 2.0, "music": 30.0}
MAX_PROMPT = 1000
BEAT_SEC = 30.0                                                    # نبضة طلب السيناريو «local» طول التوليد (ext_tasks.LOCAL_STALE_SEC بيعتبر المولّد واقع بدونها)


class SoundGenError(Exception):
    """رسالة عربية جاهزة للعرض."""


def check(kind, prompt, seconds=None, name="", mood="any", model=None) -> dict:
    """يتحقق من المدخلات ويرجّعها منظّفة. بيرمي SoundGenError."""
    if kind not in TASK_OF:
        raise SoundGenError("النوع: music (موسيقى) أو ahat (آهة/مؤثر)")
    prompt = str(prompt or "").strip()
    if not prompt:
        raise SoundGenError("اكتب وصف المطلوب")
    if len(prompt) > MAX_PROMPT:
        raise SoundGenError(f"الوصف أطول من {MAX_PROMPT} حرف")
    mood = mood or "any"
    if mood not in MOODS:
        raise SoundGenError("مزاج غير معروف: " + " أو ".join(MOODS))
    lo, hi = SECONDS_RANGE[kind]
    if seconds in (None, ""):
        seconds = SECONDS_DEFAULT[kind]
    try:
        seconds = round(float(seconds), 1)
    except (TypeError, ValueError):
        raise SoundGenError("المدة لازم رقم بالثواني") from None
    if not lo <= seconds <= hi:
        raise SoundGenError(f"المدة لهالنوع بين {lo:g} و{hi:g} ثانية")
    model = (model or "").strip() or None
    if model and not model.startswith(model_library.LIB_PREFIX):
        raise SoundGenError("النموذج: lib:ml_001 (من مكتبة النماذج) أو فاضي للافتراضي")
    return {"kind": kind, "prompt": prompt, "seconds": seconds, "name": str(name or "").strip()[:80] or prompt[:40], "mood": mood, "model": model}


def preflight(kind: str, model: str | None = None, seconds: float | None = None) -> dict:
    """هل في نموذج جاهز لهالنوع؟ بيرمي SoundGenError برسالة تقول شو ينعمل. بيرجّع النموذج المختار.
    seconds (اختياري): لو النموذج معلّن أقصى مدة (caps.max_sec، متل Stable Audio ≈ 47 ثانية) وطلبك أطول بنرفض هلأ برسالة واضحة بدل ما يرفض الصندوق."""
    task = TASK_OF[kind]
    try:
        pk = model_library.pick(task, model)
    except model_library.ModelLibraryError as e:
        raise SoundGenError(str(e)) from None
    if pk.model is None:
        why = f" ({pk.reason})" if pk.reason else ""
        raise SoundGenError(f"ما في نموذج «{model_library.TASK_LABELS[task]}» جاهز بمكتبة النماذج{why} — اربط واحد من «المصنع ← مكتبة النماذج» وفعّله واجعله الافتراضي")
    cap = (pk.model.get("caps") or {}).get("max_sec")
    if seconds is not None and cap and float(seconds) > float(cap) + 1e-9:
        raise SoundGenError(f"«{pk.model['name']}» أقصى مدة عنده {float(cap):g} ثانية — اطلب مدة أقصر أو اختار نموذج تاني")
    return pk.model


class _Hold:
    """طلب السيناريو بيصير status=local طول ما النموذج عم يولّد (الإضافة ما بتاخده): رمز بيمنع تقفيله لو اتعدّل/انحذف أثناء التوليد، ونبضة كل BEAT_SEC
    (لو المولّد انقتل — ويندوز بيقتل المهمة مباشرة — النبضة بتوقف والطلب بيرجع ينتظر لحاله بعد ext_tasks.LOCAL_STALE_SEC)."""

    def __init__(self, stem: str, request_id: str) -> None:
        import ext_tasks
        try:
            row = ext_tasks.mark_local(stem, request_id)
        except ext_tasks.ExtError as e:
            raise SoundGenError(str(e)) from None
        self.stem, self.rid, self.token = stem, row["id"], row["local_id"]
        self._stop = threading.Event()
        threading.Thread(target=self._beat, daemon=True, name="sound-gen-beat").start()

    def _beat(self) -> None:
        import ext_tasks
        while not self._stop.wait(BEAT_SEC):
            try:
                if not ext_tasks.touch_local(self.stem, self.rid, self.token):
                    return
            except Exception:                                      # noqa: BLE001 — نبضة بقدر الإمكان (الملف مقفول لحظياً)
                pass

    def stop(self) -> None:
        self._stop.set()

    def release(self) -> None:
        self.stop()
        import ext_tasks
        try:
            ext_tasks.release_local(self.stem, self.rid, self.token)
        except Exception:                                          # noqa: BLE001 — ما بنخفي الخطأ الأصلي
            pass


def _hold(stem, request_id) -> "_Hold | None":
    return _Hold(stem, request_id) if (stem and request_id) else None


def _make(c: dict, task: str, kind: str, stem, request_id, log) -> tuple[dict, object]:
    """النموذج بيولّد، والمقطع بيدخل مكتبة الأصوات غير معتمد. بيرجّع (المقطع، نتيجة النموذج)."""
    with tempfile.TemporaryDirectory(prefix="soundgen_") as td:
        out = Path(td) / "gen.mp3"
        req = model_run.RunRequest(task=task, out=out, prompt=f"{c['prompt']}. {SUFFIX[kind]}", seconds=c["seconds"], script_stem=stem, shot_id=request_id, log=log)
        try:
            res, _note = model_run.run_via_library(task, req, c["model"], error_cls=SoundGenError)
        except SoundGenError:
            raise
        if res is None:                                            # (ما بيصير: preflight تأكد) احتياط
            raise SoundGenError(f"ما في نموذج «{model_library.TASK_LABELS[task]}» جاهز بمكتبة النماذج")
        blob = out.read_bytes()
    import ahat
    try:
        t = ahat.add(c["name"], c["mood"], "gen.mp3", blob)
    except ahat.AhatError as e:
        raise SoundGenError(str(e)) from None
    t.update(source=f"model:{res.model_id}", kind=kind, from_script=stem, request_id=request_id, model_name=res.model_name)
    ahat._write(t)                                                 # غير معتمد: بينتظر سمع المالك
    return t, res


def generate(kind, prompt, seconds=None, name="", mood="any", *, model=None, stem=None, request_id=None, log=print) -> dict:
    """يولّد مقطع ويدخله مكتبة الأصوات غير معتمد. لو stem+request_id: الطلب بيصير «local» طول التوليد وبيتقفل بالنتيجة (ولو فشل بيرجع ينتظر).
    بيرجّع {track_id, model, seconds_taken, ...}."""
    c = check(kind, prompt, seconds, name, mood, model)
    task = TASK_OF[kind]
    preflight(kind, c["model"], c["seconds"])
    held = _hold(stem, request_id)
    finished = False
    try:
        t, res = _make(c, task, kind, stem, request_id, log)
        if held:
            import ext_tasks
            try:
                ext_tasks.complete_request(stem, request_id, t["id"], f"model:{res.model_name}", hold=held.token)
            except ext_tasks.ExtError as e:                        # الطلب انحذف أو اتعدّل أثناء التوليد: المقطع بالمكتبة بأي حال
                log(f"[!] {e}")
        finished = True
    finally:                                                       # فشل أو إلغاء (SystemExit) أو خطأ كتابة: الطلب بيرجع ينتظر مش عالق «local»
        if held:
            held.stop()
            if not finished:
                held.release()
    return {"track_id": t["id"], "model": res.model_name, "model_id": res.model_id, "seconds_taken": res.seconds, "duration_sec": t["duration_sec"], "approved": False}


def generate_for_request(stem: str, request_id: str, *, model=None, log=print) -> dict:
    import ext_tasks
    rows = ext_tasks.list_requests(stem)
    rid = ext_tasks._norm_id(request_id)
    r = next((x for x in rows if x.get("id") == rid and x.get("kind") in ext_tasks.REQUEST_KINDS), None)
    if r is None:
        raise SoundGenError("الطلب غير موجود")
    if r.get("status") == "local":
        raise SoundGenError("هالطلب عم يتولّد بنموذج المكتبة هلأ — استنى يخلص")
    if r.get("status") != "pending":
        raise SoundGenError("هالطلب خلص من قبل — اطلب نسخة جديدة إذا بدك")
    return generate(r["kind"], r["prompt"], r.get("seconds"), r.get("name") or "", r.get("mood") or "any", model=model, stem=stem, request_id=rid, log=log)


def main() -> None:
    import job_signals
    job_signals.install()                                          # إلغاء المهمة = إيقاف نظيف (بيوصل للنموذج عبر model_run)
    ap = argparse.ArgumentParser(description="توليد موسيقى/مؤثرات بنموذج من مكتبة النماذج")
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("request")
    r.add_argument("script")
    r.add_argument("request_id")
    r.add_argument("--model")
    f = sub.add_parser("free")
    f.add_argument("--kind", required=True, choices=sorted(TASK_OF))
    f.add_argument("--prompt", required=True)
    f.add_argument("--seconds")
    f.add_argument("--name", default="")
    f.add_argument("--mood", default="any")
    f.add_argument("--model")
    a = ap.parse_args()
    try:
        if a.mode == "request":
            out = generate_for_request(Path(a.script).stem, a.request_id, model=a.model)
        else:
            out = generate(a.kind, a.prompt, a.seconds, a.name, a.mood, model=a.model)
    except SoundGenError as e:
        print(f"[!] {e}", flush=True)
        sys.exit(1)
    print(f"[✓] المقطع {out['track_id']} ({out['duration_sec']}ث) بنموذج «{out['model']}» — دخل مكتبة الأصوات غير معتمد: اسمعه واعتمده بنفسك", flush=True)


if __name__ == "__main__":
    main()
