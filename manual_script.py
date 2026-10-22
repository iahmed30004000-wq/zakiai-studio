#!/usr/bin/env python3
"""
سيناريو بإيدك داخل المهمة الموجّهة (بدل ما يكتبه الكاتب بالذكاء): بنفس بنية الملفات اللي بيكتبها الكاتب، فبيدخل المراجعة والمحطات
متل أي سيناريو. القواعد ما بتتغيّر: 7 مشاهد بالضبط وكلام بكل مشهد، والمدة 45–50 ثانية، والمراجعة (بالذكاء، أو بالفحص الحسابي بس).

    create(...)      ← 7 مشاهد من نص أو Excel (بعد scene_import) ← ملف سيناريو مرتبط بالمنتج والنمط
    from_voice(...)  ← تسجيل صوتك ← تفريغ ← 7 مشاهد من جمل التسجيل ← موافقة حسابية ← صوتك مقصوص على المشاهد (محطة الصوت)

    python manual_script.py from-voice --product kama.json --pattern ad_109 --audio rec.m4a [--token T]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import ar_align
import config
import scene_import

MIN_SEC, MAX_SEC, N_SCENES = float(config.SCRIPT_MIN_SEC), float(config.SCRIPT_MAX_SEC), int(config.SCRIPT_SCENES)
TARGET_LOW, TARGET_HIGH = MIN_SEC + 0.5, MAX_SEC - 0.5          # لما المالك ما يحدد مدد: بنمدّد/بنقصّر لنص المدى الآمن


class ManualScriptError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def jobs_dir() -> Path:
    return Path(config.LIBRARY_DIR) / "uploads" / "manual_voice"


# ── القراءة ─────────────────────────────────────────────────────────────
def rows_from(text: str = "", xlsx: bytes | None = None, split_sentences: bool = False) -> tuple[list[dict], list[str]]:
    """(صفوف المشاهد، تنبيهات) من نص أو ملف Excel بنفس قواعد المشروع الحر (scene_import). بيرمي ManualScriptError."""
    try:
        if xlsx is not None:
            res = scene_import.parse_excel(xlsx)
        elif str(text or "").strip():
            res = scene_import.parse_text(text, split_sentences)
        else:
            raise ManualScriptError("الصق نص السيناريو أو اختار ملف Excel")
    except scene_import.SceneImportError as e:
        raise ManualScriptError(str(e))
    return res["scenes"], res["warnings"]


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!؟?!۔])\s+", str(text or "").strip()) if p.strip()]


def fit_durations(rows: list[dict]) -> list[float]:
    """مدد المشاهد. لو المالك حدّد مدداً (غير الافتراضية من عدد الكلمات) بتضل كما هي. وإلا بنمدّها أو بنقصّرها بنسبة وحدة لتصير
    المجموع ضمن 45–50 (بعيد عن الحدود شوي)، والمدة بتتبع عدد كلمات كل مشهد."""
    base = [float(r.get("duration_sec") or scene_import.default_duration(r.get("voiceover", ""))) for r in rows]
    explicit = any(abs(b - scene_import.default_duration(r.get("voiceover", ""))) > 0.05 for b, r in zip(base, rows))
    total = sum(base)
    if explicit or total <= 0:
        return [round(b, 1) for b in base]
    target = min(max(total, TARGET_LOW), TARGET_HIGH)
    return [round(b * target / total, 1) for b in base]


# ── الإنشاء ─────────────────────────────────────────────────────────────
def _product(product_file: str) -> tuple[Path, dict]:
    import brief as brief_mod
    p = Path(config.PRODUCTS_DIR) / Path(str(product_file or "")).name
    if not product_file or not p.exists():
        raise ManualScriptError("ملف المنتج غير موجود", 404)
    try:
        return p, brief_mod.load(p)
    except (json.JSONDecodeError, OSError):
        raise ManualScriptError("ملف المنتج تالف", 400)


def _pattern(pattern_id: str) -> dict:
    import pattern_store
    pat = pattern_store.load_any(str(pattern_id or "")) if pattern_id else None
    if not pat:
        raise ManualScriptError("النمط غير موجود — اختار نمط من «الفكرة» أول", 404)
    return pat


def create(product_file: str, pattern_id: str, rows: list[dict], *, title: str = "", by: str = "", label: str = "manual") -> Path:
    """سيناريو موجّه جديد من مشاهد المالك. 7 مشاهد بالضبط وكلام بكل مشهد (وإلا رسالة بتقترح المشروع الحر).
    بيرجّع مسار الملف؛ حالته draft — بعدها المراجعة (بالذكاء) أو «وافق بالفحص الحسابي»."""
    import brief as brief_mod
    import script_versions
    import stage3_generate as s3
    ppath, brief = _product(product_file)
    pat = _pattern(pattern_id)
    if len(rows) != N_SCENES:
        raise ManualScriptError(f"السيناريو الموجّه لازم {N_SCENES} مشاهد بالضبط وعندك {len(rows)} — لو بدك عدد مختلف ابدأ «مشروع حر»")
    for i, r in enumerate(rows, 1):
        if not str(r.get("voiceover") or "").strip():
            raise ManualScriptError(f"مشهد {i}: الكلام فاضي — كل مشهد بالسيناريو الموجّه لازم يكون فيه كلام")
    durs = fit_durations(rows)
    scenes = []
    for i, (r, d) in enumerate(zip(rows, durs), 1):
        vo = " ".join(str(r["voiceover"]).split())
        scenes.append({"scene_number": i, "duration_sec": d, "purpose": "", "shot_type": r.get("shot_type") or "medium",
                       "visual": str(r.get("visual") or ""), "voiceover": vo, "on_screen_text": str(r.get("on_screen_text") or ""),
                       "emotion": str(r.get("emotion") or ""), "word_count": len(vo.split())})
    first, last = _sentences(scenes[0]["voiceover"]), _sentences(scenes[-1]["voiceover"])
    hook = (first[0] if first else scenes[0]["voiceover"])[:160]
    script = {"title": (title or hook[:60]).strip(), "framework": str(pat.get("framework") or ""), "pattern_slot_mapping": [],
              "hook_line": hook, "core_angle": "", "pain_points_used": [], "total_duration_sec": round(sum(durs), 1), "scenes": scenes,
              "cta_line": (last[-1] if last else scenes[-1]["voiceover"])[:160], "production_notes": [], "self_check": {}}
    key = brief.get("product_name") or ppath.stem
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = s3._scripts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"__{label}" if label else ""
    name = f"{key}__{pattern_id}__{stamp}{suffix}"
    n = 2
    while (out_dir / f"{name}.json").exists():
        name = f"{key}__{pattern_id}__{stamp}{suffix}_{n}"
        n += 1
    number = s3._next_number(key)
    code = brief.get("product_code") or brief_mod.slug_code(key) or "product"
    script["_meta"] = {
        "product": key, "product_file": ppath.name, "product_code": code, "number": number, "version": 1,
        "script_id": script_versions.make_script_id(code, number, 1), "display_name": f"#{number} - {key}",
        "pattern_id": pattern_id, "generated_at": stamp, "hooks_requested": 1, "provider": "manual", "model": "manual",
        "label": label or "", "status": "draft", "source": "manual", "created_by": by,
        "content_hash": script_versions.content_hash(script),
    }
    path = out_dir / f"{name}.json"
    s3._write_files(path, script, brief, pattern_id)
    script_versions.save_version(path.stem, script)
    s3.update_registry(key, script)
    return path


# ── ابدأ من تسجيلك ──────────────────────────────────────────────────────
def from_voice(product_file: str, pattern_id: str, audio: Path, *, language: str | None = None, by: str = "", token: str = "", log=print) -> dict:
    """تسجيل صوتك ← تفريغ ← 7 مشاهد من جمله ← سيناريو ← موافقة بالفحص الحسابي (مدد التسجيل الفعلية، فبنتجاهل مانع سرعة الكلام) ←
    صوتك مقصوص على المشاهد بمحطة الصوت. بيرجّع {file, ok, reason, voice}. الملف بينكتب حتى لو الموافقة ما نجحت (بتكمّل منه يدوي).
    token: اسم ملف نتيجة بـ uploads/manual_voice/<token>.json عشان الواجهة تعرف اسم السيناريو بعد المهمة."""
    import review_loop
    import voice_upload as vu
    _product(product_file)
    _pattern(pattern_id)
    work = jobs_dir() / (token or uuid.uuid4().hex)
    asr, wav = vu.prepare_source(Path(audio), work, language, log)
    try:
        sents = ar_align.sentences(asr["words"])
        if len(sents) < N_SCENES:
            raise ManualScriptError(f"التسجيل فيه {len(sents)} جمل بس والسيناريو الموجّه لازم {N_SCENES} مشاهد — سجّل أكتر أو ابدأ «مشروع حر»")
        groups = ar_align.balanced(sents, N_SCENES)
        sp = [(sents[g[0]]["start"], sents[g[-1]]["end"]) for g in groups]
        cuts = ar_align.cut_points(sp, float(asr["duration"]))
        rows = [{"voiceover": " ".join(sents[i]["text"] for i in g).strip(), "visual": "", "on_screen_text": "",
                 "duration_sec": round(max(1.0, c[1] - c[0]), 1), "shot_type": None, "emotion": ""} for g, c in zip(groups, cuts)]
        path = create(product_file, pattern_id, rows, by=by, label="manual_voice")
        log(f"[✓] سيناريو من تسجيلك: {path.name}")
        result = {"file": path.name, "ok": False, "reason": "", "voice": None}
        try:
            review_loop.approve_local(path, by=by, from_recording=True)
        except review_loop.ApprovalError as e:
            result["reason"] = f"السيناريو انعمل بس الموافقة الحسابية ما نجحت: {e}"
            return result
        try:
            res = vu.ingest_guided(path, None, log=log, prepared=(asr, wav))
        except vu.VoiceUploadError as e:
            result["reason"] = f"السيناريو انوافق عليه بس تقسيم صوتك وقف: {e}"
            return result
        result.update(voice=res, ok=bool(res["ok"]), reason=res.get("reason") or "")
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="سيناريو بإيدك داخل المهمة الموجّهة")
    sub = ap.add_subparsers(dest="cmd", required=True)
    fv = sub.add_parser("from-voice")
    fv.add_argument("--product", required=True)
    fv.add_argument("--pattern", required=True)
    fv.add_argument("--audio", required=True)
    fv.add_argument("--language")
    fv.add_argument("--token", default="")
    a = ap.parse_args()
    log = lambda m: print(m, flush=True)             # noqa: E731
    result_file = (jobs_dir().parent / f"manual_voice_{a.token}.json") if a.token else None
    try:
        import voice_upload as vu
        res = from_voice(a.product, a.pattern, Path(a.audio), language=a.language, token=a.token, log=log)
    except (ManualScriptError, vu.VoiceUploadError) as e:
        if result_file:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(json.dumps({"file": None, "ok": False, "reason": str(e)}, ensure_ascii=False), encoding="utf-8")
        sys.exit(f"[!] {e}")
    if result_file:
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res["ok"]:
        sys.exit(f"[!] {res['reason']}")


if __name__ == "__main__":
    main()
