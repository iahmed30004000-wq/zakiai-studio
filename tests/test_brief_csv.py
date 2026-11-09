"""تنزيل البريف CSV: الأعمدة، العربي، والحماية من حقن الصيغ."""
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

import brief
from routes_pipeline import _csv_cell, brief_to_csv


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_csv_has_every_field_plus_forbidden_row():
    b = brief.empty_brief()
    b.update(product_name="كريم", features=["ترطيب", "لمعان"], no_offer=True,
             _provenance={"price": {"source": "crm"}}, price="10$")
    rows = _rows(brief_to_csv(b))
    assert rows[0][0] == "الحقل" and len(rows) == len(brief.FIELDS) + 2
    by_key = {r[1]: r for r in rows[1:]}
    assert by_key["features"][5] == "ترطيب\nلمعان"
    assert by_key["no_offer"][5] == "نعم"
    assert by_key["price"][6] == "الـ OMS"
    assert by_key["offer"][4] == "نعم"   # العرض مكتمل بتأكيد «لا يوجد عرض»


def test_csv_cell_blocks_formula_injection():
    assert _csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _csv_cell("+9 قطع") == "'+9 قطع"
    assert _csv_cell("عادي") == "عادي"
