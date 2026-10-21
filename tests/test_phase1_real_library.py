"""المرحلة ١ — معايير القبول على المكتبة الحقيقية (قراءة فقط)."""
import json
import re
from pathlib import Path

import pytest

import config
import taxonomy

ABS_WIN = re.compile(r"[A-Za-z]:[\\/]")
PATTERNS = sorted(Path(config.PATTERNS_DIR).glob("*.pattern.json"))

pytestmark = pytest.mark.skipif(not PATTERNS, reason="no library")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_dialect_and_category_are_closed_values():
    for f in PATTERNS:
        p = _load(f)
        d, c = p.get("dialect_or_language"), p.get("product_category")
        assert d is None or d in taxonomy.DIALECTS, (f.name, d)
        assert c is None or c in taxonomy.CATEGORIES, (f.name, c)


def test_framework_is_single_closed_value():
    for f in PATTERNS:
        p = _load(f)
        fw = p.get("framework")
        assert fw is None or fw in taxonomy.FRAMEWORKS, (f.name, fw)
        assert not re.search(r"[|/]", str(fw or "")), f.name
        sec = p.get("framework_secondary")
        assert sec is None or sec in taxonomy.FRAMEWORKS


def test_every_pattern_migrated_and_legacy_kept():
    for f in PATTERNS:
        p = _load(f)
        assert "_taxonomy" in p and "_legacy" in p, f.name


def test_no_absolute_windows_paths_in_library():
    bad = []
    for sub in ("assets", "raw"):
        root = Path(config.LIBRARY_DIR) / sub
        if not root.exists():
            continue
        for f in root.rglob("*.json"):
            if ABS_WIN.search(f.read_text(encoding="utf-8", errors="ignore")):
                bad.append(str(f.name))
    assert not bad, bad[:5]


def test_products_template_is_empty_schema():
    import brief
    t = json.loads((Path(config.PRODUCTS_DIR) / "_template.json").read_text(encoding="utf-8"))
    for k, v in t.items():
        if k.startswith("_"):
            continue
        assert v in ("", [], False, None), (k, v)
    assert set(brief.FIELD_KEYS) <= set(t)
