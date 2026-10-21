"""
يكتب هوك بديل واحد (جديد، أو بدل هوك موجود) لسيناريو جاهز، بنفس قواعد البريف.

الموديل بيرجّع هوك واحد؛ الكود بيفحصه فوراً (script_hooks.check: النطق، نص الشاشة، الادعاءات الممنوعة)، وإذا فيه مانع
بيعيد المحاولة مرة وحدة مع الملاحظات. اللي بيرجع مفحوص بالكود، والمراجع بالذكاء بيعطي رأيه لاحقاً بتدقيق السيناريو.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import config
import script_hooks as sh

ATTEMPTS = 2


class HookWriterError(Exception):
    """فشل متوقع — رسالته عربية وجاهزة للعرض."""


def _ask(system: str, user: str) -> dict:
    import stage3_generate
    return stage3_generate.ask("writer", system, user)


def _next_id(script: dict) -> str:
    n = max((int(h["id"][1:]) for h in sh.hooks_of(script) if str(h["id"])[1:].isdigit()), default=0)
    return sh.hook_id(n + 1)


def _request_message(script: dict, brief: dict, *, replace_id, want_type, feedback) -> str:
    import stage3_generate
    meta = script.get("_meta") or {}
    s1 = sh._scene1(script)
    scenes = script.get("scenes") or []
    nxt = scenes[1] if len(scenes) > 1 and isinstance(scenes[1], dict) else {}
    main = sh.get(script, sh.main_id(script)) or {}
    others = [{"id": h["id"], "type": h["type"], "spoken": h["spoken"]} for h in sh.hooks_of(script) if h["id"] != replace_id]
    used = stage3_generate.used_for(meta.get("product") or brief.get("product_name") or "", exclude_script=script)
    line, _rest = sh.split_scene1(script)
    request = {"replace": replace_id, "type": want_type or "any type that none of the other hooks uses",
               "target_words": max(3, sh._words(main.get("spoken") or line)), "max_on_screen_words": sh.MAX_OSTEXT_WORDS}
    if feedback:
        request["feedback"] = feedback
    import claims
    return (
        "## PRODUCT BRIEF\n" + json.dumps(stage3_generate.brief_for_model(brief), ensure_ascii=False, indent=2) + "\n\n"
        "## HARD RULES FROM BRIEF\n" + json.dumps(claims.writer_rules(brief), ensure_ascii=False, indent=2) + "\n\n"
        "## THE AD SO FAR\n" + json.dumps({"title": script.get("title"), "main_hook": main.get("spoken") or line,
                                            "scene_1": {k: s1.get(k) for k in ("duration_sec", "purpose", "voiceover", "on_screen_text", "visual")},
                                            "scene_2_voiceover": nxt.get("voiceover")},
                                           ensure_ascii=False, indent=2) + "\n\n"
        "## OTHER HOOKS IN THIS SCRIPT (do not repeat)\n" + json.dumps(others, ensure_ascii=False, indent=2) + "\n\n"
        "## ALREADY USED — DO NOT REPEAT ANY OF THESE\n" + json.dumps(used, ensure_ascii=False, indent=2) + "\n\n"
        "## REQUEST\n" + json.dumps(request, ensure_ascii=False, indent=2))


def propose(script: dict, brief: dict | None, *, replace_id: str | None = None, want_type: str | None = None, ask=None) -> dict:
    """
    بيرجّع {hook: الصف الجاهز، findings: ملاحظات الفحص الفوري له، attempts}. لا بيكتب بالملف (الاستدعاء بيقرّر).
    replace_id: هوك بديل موجود بدنا نبدّله (الأساسي ما بينبدّل بهالطريقة)؛ None = هوك جديد.
    """
    if brief is None:
        raise HookWriterError("ما لقيت بريف المنتج — ما بقدر أكتب هوك بلا قواعده")
    if replace_id is not None:
        if sh.get(script, replace_id) is None:
            raise HookWriterError("الهوك غير موجود")
        if replace_id == sh.main_id(script):
            raise HookWriterError("الهوك الأساسي ما بينبدّل هيك: اختر هوك تاني كأساسي أول، أو عدّله بإيدك")
    elif len(sh.hooks_of(script)) >= int(getattr(config, "HOOKS_MAX", 5)):
        raise HookWriterError(f"وصلت للحد الأقصى ({config.HOOKS_MAX} هوكات) — احذف هوك أول")
    if want_type and want_type not in sh.TYPES:
        want_type = None
    system = (Path(config.PROMPTS_DIR) / "hook_writer.txt").read_text(encoding="utf-8")
    ask = ask or _ask
    hid = replace_id or _next_id(script)
    feedback, row, findings = None, None, []
    for attempt in range(1, ATTEMPTS + 1):
        res = ask(system, _request_message(script, brief, replace_id=replace_id, want_type=want_type, feedback=feedback))
        raw = res.get("hook") if isinstance(res, dict) else None
        if not isinstance(raw, dict) or not str(raw.get("spoken") or "").strip():
            feedback = ["الرد ما فيه هوك صالح (لازم hook.spoken)"]
            continue
        row = sh._hook_row(hid, str(raw.get("type") or "").strip(), raw.get("spoken"), raw.get("on_screen_text"), raw.get("visual"), raw.get("why"))
        findings = candidate_findings(script, brief, row, replace_id)
        blockers = [f for f in findings if f.get("severity") == "blocker"]
        if not blockers:
            return {"hook": row, "findings": findings, "attempts": attempt}
        feedback = [f"{f['issue']} — {f.get('evidence', '')}" for f in blockers]
    if row is None:
        raise HookWriterError("الموديل ما رجّع هوك صالح — جرّب مرة تانية")
    return {"hook": row, "findings": findings, "attempts": ATTEMPTS}


def candidate_findings(script: dict, brief: dict | None, row: dict, replace_id: str | None) -> list[dict]:
    """ملاحظات الفحص الفوري على هوك مرشّح (قبل ما ينحفظ): بنحطّه مكان القديم (أو بآخر القائمة) ونفحص."""
    trial = copy.deepcopy(script)
    current = sh.hooks_of(script)
    trial["hooks"] = current + [row] if replace_id is None else [row if h["id"] == replace_id else h for h in current]
    trial["hook_main"] = sh.main_id(script)
    return sh.check(trial, brief).get(row["id"], [])
