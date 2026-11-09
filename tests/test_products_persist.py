"""المنتجات لازم تعيش بالحجم الدائم (library/) مش داخل الصورة، وبتنسخ لها القوالب القديمة بدون كتابة فوق شي."""
import json

import config


def test_products_dir_is_inside_library_volume():
    assert config.PRODUCTS_DIR.parent == config.LIBRARY_DIR


def test_ensure_copies_missing_legacy_files_without_overwriting(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    live = tmp_path / "library" / "products"
    legacy.mkdir()
    (legacy / "_template.json").write_text('{"t":1}', encoding="utf-8")
    (legacy / "old.json").write_text('{"v":"legacy"}', encoding="utf-8")
    live.mkdir(parents=True)
    (live / "old.json").write_text('{"v":"edited"}', encoding="utf-8")   # تعديل المالك لازم يضل
    monkeypatch.setattr(config, "_LEGACY_PRODUCTS_DIR", legacy)
    monkeypatch.setattr(config, "PRODUCTS_DIR", live)
    config.ensure_products_dir()
    assert json.loads((live / "_template.json").read_text(encoding="utf-8")) == {"t": 1}
    assert json.loads((live / "old.json").read_text(encoding="utf-8")) == {"v": "edited"}
