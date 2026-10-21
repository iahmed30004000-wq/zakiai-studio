"""كل ملفات الواجهة بتتحمّل بنفس النطاق العام: أي اسم const/let/class مكرّر بين ملفين = SyntaxError وبتنكسر الصفحة كلها.
node --check على كل ملف لحاله ما بيمسك هالتعارض، فنفحصه هون على مستوى كل السكربتات مجتمعة (بترتيب index.html)."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
DECL = re.compile(r"^(?:(?:const|let|class)\s+([A-Za-z_$][\w$]*)|(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*))", re.M)
IIFE_START = re.compile(r"^\(\s*(?:\(\)\s*=>|function)[^\n]*\{[ \t]*$", re.M)


def scripts_in_order():
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r'<script src="/([\w.-]+\.js)(?:\?v=\d+)?"></script>', idx) if (STATIC / m.group(1)).exists()]


def is_closed_scope(src: str) -> bool:
    """ملف كلو جوّا دالة مغلقة (مثل mission.js) ما بيلوّث النطاق العام."""
    return bool(IIFE_START.search(src)) and src.rstrip().endswith("})();")


def test_no_top_level_name_collisions_across_scripts():
    owner: dict[str, tuple[str, str]] = {}
    clashes = []
    for name in scripts_in_order():
        src = (STATIC / name).read_text(encoding="utf-8")
        if is_closed_scope(src):
            continue
        for m in DECL.finditer(src):
            ident, kind = (m.group(1), "lexical") if m.group(1) else (m.group(2), "function")
            if ident in owner:
                prev_file, prev_kind = owner[ident]
                if kind == "lexical" or prev_kind == "lexical":          # function+function بس مسموح (إعادة تعريف بدون خطأ)
                    clashes.append(f"{ident}: {prev_file} ({prev_kind}) و {name} ({kind})")
            else:
                owner[ident] = (name, kind)
    assert not clashes, clashes


def test_scripts_list_is_found_and_mission_is_a_closed_scope():
    names = scripts_in_order()
    assert "app.js" in names and "production.js" in names and "boot.js" in names and len(names) >= 12
    assert is_closed_scope((STATIC / "mission.js").read_text(encoding="utf-8"))


def test_the_check_really_catches_a_collision():
    """ضمان إن الفحص مش فاضي: نفس الاسم const بملفين لازم يتمسك."""
    a, b = "const PL = {};\n", "const PL = { x: 1 };\n"
    seen = {m.group(1) for m in DECL.finditer(a)}
    assert any(m.group(1) in seen for m in DECL.finditer(b))
