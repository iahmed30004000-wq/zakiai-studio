"""نقل مكتبة الأنماط بملف مضغوط: تصدير كامل، استيراد بيضيف الجديد بس، وحماية من الملفات الغلط."""

import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import clusters  # noqa: E402
import config  # noqa: E402
import pattern_store as ps  # noqa: E402
import review_queue  # noqa: E402


@pytest.fixture
def lib(tmp_path, monkeypatch):
    pdir = tmp_path / "library" / "patterns"
    pdir.mkdir(parents=True)
    monkeypatch.setattr(config, "PATTERNS_DIR", pdir)
    monkeypatch.setattr(config, "SCRIPTS_DIR", tmp_path / "library" / "scripts")
    monkeypatch.setattr(review_queue, "QUEUE_PATH", tmp_path / "rq.json")
    monkeypatch.setattr(clusters, "CLUSTERS_PATH", tmp_path / "library" / "clusters.json")
    return pdir


def put(pdir, pid, **extra):
    p = {"pattern_name": f"نمط {pid}", "framework": "PAS", "scenes": [{"n": 1, "voiceover": "مرحبا"}], **extra}
    (pdir / f"{pid}.pattern.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return p


def zip_of(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, (bytes, str)) else json.dumps(data, ensure_ascii=False))
    return buf.getvalue()


def test_export_then_import_moves_whole_patterns_and_keeps_existing_ones(lib, tmp_path, monkeypatch):
    a = put(lib, "ad_1", deep={"why": "تفصيل ما بيطلع بالفورم"})
    put(lib, "مكتبة_الإعلانات_101")
    (lib / "_archive").mkdir()
    (lib / "_archive" / "old.pattern.json").write_text("{}", encoding="utf-8")
    (lib.parent / "pattern_i18n_state.json").write_text('{"done": 2}', encoding="utf-8")
    data = ps.export_bundle()
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert sorted(names) == ["pattern_i18n_state.json", "patterns/ad_1.pattern.json", "patterns/مكتبة_الإعلانات_101.pattern.json"]

    # جهاز تاني: فاضي إلا نمط واحد بنفس الاسم (تعديل محلي ما لازم ينمسح)
    other = tmp_path / "other" / "library" / "patterns"
    other.mkdir(parents=True)
    monkeypatch.setattr(config, "PATTERNS_DIR", other)
    local = put(other, "مكتبة_الإعلانات_101", pattern_name="نسختي المعدّلة")
    r = ps.import_bundle(data, by="ahmad")
    assert r["added"] == ["ad_1"] and r["skipped"] == ["مكتبة_الإعلانات_101"] and r["bad"] == []
    got = json.loads((other / "ad_1.pattern.json").read_text(encoding="utf-8"))
    assert got["deep"] == a["deep"] and got["_edits"][-1]["action"] == "import_bundle"
    assert json.loads((other / "مكتبة_الإعلانات_101.pattern.json").read_text(encoding="utf-8"))["pattern_name"] == local["pattern_name"]
    assert json.loads((other.parent / "pattern_i18n_state.json").read_text(encoding="utf-8")) == {"done": 2}


@pytest.mark.parametrize("name", ["../evil.pattern.json", "patterns/a b.pattern.json", "patterns/x$.pattern.json"])
def test_import_refuses_bad_names_and_never_writes_outside(lib, name):
    r = ps.import_bundle(zip_of({name: {"pattern_name": "x"}}))
    assert r["added"] == [] and len(r["bad"]) == 1
    assert not (lib.parent / "evil.pattern.json").exists()


def test_import_rejects_non_json_and_non_zip(lib):
    r = ps.import_bundle(zip_of({"patterns/p1.pattern.json": "مش json", "notes.txt": "hi", "patterns/p2.pattern.json": {"pattern_name": "تمام"}}))
    assert r["added"] == ["p2"] and {b["name"] for b in r["bad"]} == {"p1.pattern.json", "notes.txt"}
    with pytest.raises(ps.PatternError, match="مش ملف مكتبة"):
        ps.import_bundle(b"not a zip")


def test_archived_pattern_is_not_brought_back(lib):
    (lib / "_archive").mkdir()
    (lib / "_archive" / "gone.pattern.json").write_text("{}", encoding="utf-8")
    r = ps.import_bundle(zip_of({"patterns/gone.pattern.json": {"pattern_name": "رجعت؟"}}))
    assert r["skipped"] == ["gone"] and not (lib / "gone.pattern.json").exists()


def test_bundle_routes(lib):
    from fastapi.testclient import TestClient
    import web.app as appmod
    put(lib, "ad_9")
    c = TestClient(appmod.app)
    got = c.get("/api/pattern-lib/bundle.zip")
    if got.status_code in (302, 303, 401):                 # بوابة الدخول شغّالة بهالبيئة: منجرّب الدوال مباشرة فوق
        pytest.skip("بوابة الدخول")
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
    (lib / "ad_9.pattern.json").unlink()
    r = c.post("/api/pattern-lib/bundle", files={"file": ("lib.zip", got.content, "application/zip")})
    assert r.status_code == 200 and r.json()["added"] == ["ad_9"]
