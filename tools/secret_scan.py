"""
فحص أسرار قبل أي رفع على جيت هب. شغّله من جذر المشروع بعد `git add -A` وقبل `git commit`:

    python tools/secret_scan.py

بيقارن قيم settings.json (المفاتيح الحقيقية) ونمط المفاتيح المعروفة (Anthropic/OpenAI/GitHub/Google/Slack/AWS/مفاتيح خاصة)
مع كل الملفات المرحّلة. ما بيطبع أي قيمة سرّية: بس أسماء الملفات. exit 1 لو لقى شي (أوقف الرفع وراجع).
بيتجاهل أسماء الموديلات (claude-…) ومفاتيح الاختبار المزيّفة (اللي فيها FAKE/example/test).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "anthropic": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai-like": r"sk-[A-Za-z0-9]{32,}",
    "github": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "google": r"AIza[0-9A-Za-z_\-]{30,}",
    "slack": r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    "private-key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "aws": r"AKIA[0-9A-Z]{16}",
    "bearer": r"[Bb]earer [A-Za-z0-9_\-\.]{30,}",
}


MODEL_ID = re.compile(r"^(claude|gpt|o\d|gemini|grok|qwen|kimi|glm|deepseek|llama|mistral|eleven|sonnet|opus|haiku|moonshot|command)[\w.:/\-]*$", re.I)
FAKE = re.compile(r"fake|example|dummy|placeholder|test", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def _strings(o, out: list[str]) -> None:
    if isinstance(o, dict):
        for v in o.values():
            _strings(v, out)
    elif isinstance(o, list):
        for v in o:
            _strings(v, out)
    elif isinstance(o, str) and len(o) >= 16:
        out.append(o)


def main() -> int:
    values: list[str] = []
    try:
        _strings(json.loads((ROOT / "settings.json").read_text(encoding="utf-8")), values)
    except (OSError, ValueError):
        print("settings.json مش مقروء — فحص النمط بس")
    keys = sorted({v for v in values if re.fullmatch(r"[A-Za-z0-9_\-\.=+]{16,}", v) and re.search(r"\d", v) and re.search(r"[A-Za-z]", v)
                   and not MODEL_ID.match(v)})                      # أسماء الموديلات (claude-…) مش أسرار
    hits: dict[str, set[str]] = {}
    for k in keys:
        for f in git("grep", "-l", "-F", "--cached", "--", k).split("\n"):
            if f:
                hits.setdefault(f, set()).add("قيمة من settings.json")
    for name, rx in PATTERNS.items():
        for f in git("grep", "-l", "-E", "--cached", "--", rx).split("\n"):
            if not f:
                continue
            toks = [t for t in git("grep", "-h", "-o", "-E", "--cached", "--", rx, f).split("\n") if t]
            if toks and all(FAKE.search(t) for t in toks):          # مفاتيح الاختبار المزيّفة (sk-ant-FAKEKEY…)
                continue
            hits.setdefault(f, set()).add(name)
    tracked = [f for f in git("ls-files", "-z").split("\0") if f]
    if hits:
        print("تنبيه — ممكن أسرار بهالملفات (راجعها: غالباً أسماء موديلات أو مفاتيح اختبار مزيّفة):")
        for f, why in sorted(hits.items()):
            print("  ", f, sorted(why))
        return 1
    print(f"نظيف: ما في قيمة من settings.json ولا نمط مفتاح معروف بـ {len(tracked)} ملف مرحّل")
    return 0


if __name__ == "__main__":
    sys.exit(main())
