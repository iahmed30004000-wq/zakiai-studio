#!/usr/bin/env python3
"""
حلقة المراجعة وإعادة الكتابة.

سيناريو مكتوب ← مراجعة (بالكود + موديل) ← إذا الحكم «عدّل» ← إعادة كتابة تلقائية
بملاحظات المراجِع ← مراجعة جديدة، بحد أقصى config.SCRIPT_MAX_REVIEW_ROUNDS دورات.

الحالات (`_meta.status`): draft ← reviewing ← approved | needs_owner
العوائق (blockers) لازم تكون صفر قبل ما السيناريو يروح لتخطيط اللقطات أو الإنتاج.
بعد آخر دورة وما زال فيه عائق: needs_owner + سبب واضح، ووقف لحد قرار المالك.

بوابة الإنتاج: is_cleared() — مراجعة موجودة، عوائقها صفر، وبصمة محتواها تطابق
السيناريو الحالي (تعديل بعد المراجعة = مراجعة قديمة).

    python review_loop.py library/scripts/<file>.json
    python review_loop.py library/scripts/<file>.json --status
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config
import llm
import script_versions
from llm_errors import exit_on_api_error

STATUSES = ("draft", "reviewing", "approved", "needs_owner")


class ApprovalError(Exception):
    """رفض موافقة يدوية — الرسالة عربية."""


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def review_path(script_path) -> Path:
    import review_script
    return review_script.review_dir() / f"{Path(script_path).stem}.review.json"


def load_review(script_path) -> dict | None:
    rp = review_path(script_path)
    if not rp.exists():
        return None
    try:
        return _read(rp)
    except json.JSONDecodeError:
        return None


def _blockers(review: dict) -> int:
    n = review.get("blockers")
    n = n if isinstance(n, int) else 0
    findings = review.get("findings")
    if isinstance(findings, list):
        n = max(n, sum(1 for f in findings      # ملاحظات الهوكات البديلة (hook_id) ما بتمنع موافقة السيناريو الأساسي
                       if isinstance(f, dict) and f.get("severity") == "blocker" and not f.get("hook_id")))
    return n


def _set_meta(path: Path, **updates) -> dict:
    """يعدّل `_meta` بس — المحتوى (وبصمته) ما بيتغيّر."""
    script = _read(path)
    script.setdefault("_meta", {}).update(updates)
    Path(path).write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script


def is_cleared(script_path) -> tuple[bool, str]:
    """
    هل يجوز يروح السيناريو لتخطيط اللقطات/الصور/الصوت؟ بيرجّع (نعم/لا، السبب بالعربي).
    """
    path = Path(script_path)
    if not path.exists():
        return False, "السيناريو غير موجود"
    try:
        script = _read(path)
    except json.JSONDecodeError:
        return False, "ملف السيناريو تالف"
    meta = script.get("_meta") or {}

    review = load_review(path)
    if review is None:
        return False, "السيناريو ما انراجع — شغّل حلقة المراجعة (أو التدقيق) قبل الإنتاج"
    rh = review.get("script_hash")
    if not rh:
        return False, "مراجعة قديمة بلا بصمة محتوى — أعد مراجعة السيناريو"
    if rh != script_versions.content_hash(script):
        return False, "السيناريو انعدّل بعد آخر مراجعة — أعد المراجعة قبل الإنتاج"
    n = _blockers(review)
    if n:
        return False, f"المراجعة فيها {n} عائق (blocker) لازم تنحل قبل الإنتاج"
    if meta.get("status") == "needs_owner":
        return False, "السيناريو مرفوع للمالك — لازم موافقة يدوية قبل الإنتاج"
    return True, "مراجعة بعوائق = 0 ومطابقة للمحتوى الحالي"


def status(script_path) -> dict:
    """{status, blockers, rounds, approved, reason, ...} لواجهة المتابعة."""
    path = Path(script_path)
    script = _read(path)
    meta = script.get("_meta") or {}
    review = load_review(path)
    cleared, reason = is_cleared(path)

    st = meta.get("status") or "draft"
    if st not in STATUSES:
        st = "draft"
    if st == "approved" and not cleared:
        st = "draft"          # اعتُمد وبعدين انعدّل
    if st == "needs_owner" and meta.get("status_reason"):
        reason = meta["status_reason"]

    rounds = (review or {}).get("rounds")
    if not isinstance(rounds, int):
        rounds = meta.get("review_rounds") or 0
    return {
        "status": st,
        "blockers": _blockers(review) if review else None,
        "major": (review or {}).get("major"),
        "rounds": rounds,
        "max_rounds": config.SCRIPT_MAX_REVIEW_ROUNDS,
        "approved": cleared,
        "reviewed": review is not None,
        "verdict": (review or {}).get("verdict"),
        "reason": reason,
        "script_id": meta.get("script_id"),
        "version": meta.get("version"),
    }


def approve(script_path, by: str = "owner") -> dict:
    """موافقة مالك يدوية — بس لو المراجعة الحالية بعوائق = 0 ومطابقة للمحتوى."""
    path = Path(script_path)
    if not path.exists():
        raise ApprovalError("السيناريو غير موجود")
    script = _read(path)
    review = load_review(path)
    if review is None:
        raise ApprovalError("ما في مراجعة — راجع السيناريو أولاً")
    if review.get("script_hash") != script_versions.content_hash(script):
        raise ApprovalError("المراجعة قديمة (السيناريو انعدّل بعدها) — أعد المراجعة")
    n = _blockers(review)
    if n:
        raise ApprovalError(f"ما بتنفع الموافقة: فيه {n} عائق (blocker) — عالجه وأعد المراجعة")
    _set_meta(path, status="approved", status_reason="",
              approved_at=datetime.now().isoformat(timespec="seconds"), approved_by=by)
    import drive_sync
    drive_sync.request_ad(path.stem)                 # النص والهوكات لدرايف (بلا ربط ما بيعمل شي)
    return status(path)


class ConfirmNeeded(ApprovalError):
    """الموافقة بالفحص الحسابي بدها تأكيد من المالك (فيه مراجعة ذكاء حالية فيها موانع)."""


LOCAL_PROVIDER = "local"
_PACE_ISSUE = "الكلام أسرع من الممكن"


def approve_local(script_path, by: str = "owner", confirm: bool = False, from_recording: bool = False) -> dict:
    """موافقة المالك بالفحص الحسابي والادعاءات بس (بلا مراجعة ذكاء) — لما المراجعة بالذكاء مش متاحة (مفتاح مرفوض مثلاً).
    الفحص بالكود: 7 مشاهد، المدة، إيقاع الكلام، وقواعد البريف والادعاءات الممنوعة. أي مانع بيوقف الموافقة (ما في تجاوز).
    from_recording: السيناريو طالع من تسجيل المالك فمدده هي مدد كلامه الفعلي — بنتجاهل بس مانع «الكلام أسرع من الممكن».
    إذا في مراجعة ذكاء حالية (لنفس المحتوى) فيها موانع: بيطلب confirm=True (الذكاء ممكن يشوف شي الكود ما بيشوفه).
    بيكتب مراجعة provider=local بنفس بصمة المحتوى، وبعدها approve() العادية — فبوابة الإنتاج (is_cleared) ما بتتغيّر."""
    import review_script
    path = Path(script_path)
    if not path.exists():
        raise ApprovalError("السيناريو غير موجود")
    script = _read(path)
    findings = review_script.local_checks(script)
    if from_recording:
        findings = [f for f in findings if not str(f.get("issue", "")).startswith(_PACE_ISSUE)]
    order = {"blocker": 0, "major": 1, "minor": 2}
    findings.sort(key=lambda f: order.get(f.get("severity"), 3))
    blockers = review_script.count_main(findings, "blocker")
    if blockers:
        first = next(f for f in findings if f.get("severity") == "blocker" and not review_script.is_hook_finding(f))
        ev = f" ({first.get('evidence')})" if first.get("evidence") else ""
        raise ApprovalError(f"ما بتنفع الموافقة: الفحص بالكود لقى {blockers} مانع — مثلاً: {first.get('issue')}{ev}")
    h = script_versions.content_hash(script)
    prev = load_review(path)
    if (prev and prev.get("script_hash") == h and (prev.get("_meta") or {}).get("provider") != LOCAL_PROVIDER
            and _blockers(prev) and not confirm):
        raise ConfirmNeeded(f"مراجعة الذكاء الحالية لقت {_blockers(prev)} مانع، والموافقة بالفحص الحسابي بتتجاهلها — متأكد؟")
    now = datetime.now().isoformat(timespec="seconds")
    review = {
        "verdict": "approve", "findings": findings, "blockers": 0,
        "major": review_script.count_main(findings, "major"), "minor": review_script.count_main(findings, "minor"),
        "hook_blockers": 0, "rounds": 0, "script_hash": h, "local_only": True,
        "summary": "فحص حسابي وادعاءات بالكود بس — بلا مراجعة ذكاء. وافق عليه المالك بنفسه.",
        "_meta": {"script": path.name, "reviewed_at": now, "provider": LOCAL_PROVIDER, "model": "local-checks", "approved_by": by},
    }
    out = review_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_meta(path, approval_mode="local")
    return approve(path, by=by)


def _annotate_review(path: Path, rounds: int, history: list[dict]) -> None:
    rp = review_path(path)
    if not rp.exists():
        return
    data = _read(rp)
    data["rounds"] = rounds
    data["history"] = history
    rp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _finish(path: Path, st: str, reason: str, rounds: int, history: list[dict],
            result: dict | None) -> dict:
    updates = {"status": st, "status_reason": reason, "review_rounds": rounds}
    if st == "approved":
        updates.update(approved_at=datetime.now().isoformat(timespec="seconds"), approved_by="auto")
    script = _set_meta(path, **updates)
    _annotate_review(path, rounds, history)
    if st == "approved":
        import drive_sync
        drive_sync.request_ad(path.stem)
    out = {
        "status": st, "reason": reason, "rounds": rounds,
        "blockers": (result or {}).get("blockers"), "major": (result or {}).get("major"),
        "verdict": (result or {}).get("verdict"),
        "script_id": (script.get("_meta") or {}).get("script_id"),
        "approved": st == "approved",
    }
    return out


def run(script_path, *, max_rounds: int | None = None) -> dict:
    """
    يشغّل الحلقة على سيناريو موجود. بيرجّع {status, reason, rounds, blockers, ...}.
    ما بيرمي عند فشل الموديل — بيترك الحالة draft مع السبب.
    """
    import review_script
    import stage3_generate

    path = Path(script_path)
    limit = config.SCRIPT_MAX_REVIEW_ROUNDS if max_rounds is None else max_rounds
    _set_meta(path, status="reviewing", status_reason="")

    history: list[dict] = []
    rounds = 0
    while True:
        print(f"\n[حلقة المراجعة] مراجعة رقم {rounds + 1} (إعادات الكتابة حتى الآن: {rounds}/{limit})")
        try:
            result = review_script.review(path, rounds=rounds)
        except llm.LLMError as e:
            reason = f"فشلت المراجعة: {e}"
            _set_meta(path, status="draft", status_reason=reason)
            print(f"[!] {reason}")
            return {"status": "draft", "reason": reason, "rounds": rounds, "blockers": None,
                    "approved": False}

        blockers, verdict = result["blockers"], result["verdict"]
        history.append({
            "round": rounds, "verdict": verdict, "blockers": blockers,
            "major": result.get("major"), "minor": result.get("minor"),
            "script_hash": result.get("script_hash"),
            "reviewed_at": (result.get("_meta") or {}).get("reviewed_at"),
        })

        if blockers == 0 and verdict == "approve":
            return _finish(path, "approved", "المراجعة نظيفة", rounds, history, result)

        if rounds >= limit:
            if blockers == 0 and verdict != "reject":
                note = (f"اعتُمد بعد {rounds} إعادة كتابة، وبقيت {result.get('major', 0)} "
                        "ملاحظة مهمة بلا عوائق")
                return _finish(path, "approved", note, rounds, history, result)
            why = (f"بعد {rounds} دورات إعادة كتابة ما زال فيه {blockers} عائق (blocker)"
                   if blockers else f"المراجع رفض السيناريو بعد {rounds} دورات إعادة كتابة")
            first = next((f for f in result.get("findings", [])
                          if f.get("severity") == "blocker"), None)
            if first:
                why += f" — مثلاً: {first.get('issue')}"
            print(f"[!] يحتاج قرار المالك: {why}")
            return _finish(path, "needs_owner", why, rounds, history, result)

        print(f"    الحكم {verdict} · عوائق {blockers} — إعادة كتابة بملاحظات المراجِع…")
        try:
            stage3_generate.rewrite_from_review(path, result)
        except Exception as e:                      # فشل الكتابة = رفع للمالك مش انهيار
            why = f"تعذّرت إعادة الكتابة التلقائية: {e}"
            print(f"[!] {why}")
            return _finish(path, "needs_owner", why, rounds, history, result)
        rounds += 1
        _set_meta(path, status="reviewing", review_rounds=rounds)


@exit_on_api_error
def main() -> None:
    ap = argparse.ArgumentParser(description="حلقة المراجعة وإعادة الكتابة")
    ap.add_argument("script", help="مسار ملف السيناريو")
    ap.add_argument("--status", action="store_true", help="اعرض الحالة فقط")
    args = ap.parse_args()

    path = Path(args.script)
    if not path.exists():
        sys.exit(f"[!] الملف غير موجود: {path}")
    if args.status:
        print(json.dumps(status(path), ensure_ascii=False, indent=2))
        return

    out = run(path)
    label = {"approved": "معتمد", "needs_owner": "يحتاج المالك", "draft": "مسودة"}[out["status"]]
    print(f"\n[✓] الحالة: {label} — {out['reason']}")
    if out["status"] == "needs_owner":
        sys.exit(f"[!] السيناريو ما بيروح للإنتاج قبل قرار المالك: {out['reason']}")
    if out["status"] == "draft":
        sys.exit(f"[!] {out['reason']}")


if __name__ == "__main__":
    main()
