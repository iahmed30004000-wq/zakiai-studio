import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import backup
import config
import secrets_store
import settings_io
from tests.phase8_support import (ALL_FAKE, FAKE_KEY_A, isolated, make_library,
                                  sample_settings)

KEY_RE = re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}")


@pytest.fixture
def env(isolated, monkeypatch):
    make_library(isolated)
    settings_io.save(sample_settings())
    out = isolated.tmp / "external_drive"
    settings_io.update(lambda s: s.__setitem__("BACKUP", {"dir": str(out)}))
    isolated.out = out
    isolated.clock = {"now": datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(backup, "_now", lambda: isolated.clock["now"].astimezone())
    return isolated


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _restore(env, archive, name="restored"):
    dest = env.tmp / name
    return dest, backup.restore(archive, dest)


def test_backup_restores_into_new_folder_with_matching_files_and_sha(env):
    res = backup.run()
    assert res["ok"] and Path(res["path"]).exists() and Path(res["path"]).parent == env.out
    dest, r = _restore(env, res["path"])
    assert r["ok"] and r["mismatched"] == [] and r["missing"] == []
    restored = [f for f in dest.rglob("*") if f.is_file()]
    assert len(restored) == r["files_restored"] == r["files_manifest"] == res["files"]
    assert _sha(dest / "library/patterns/p1.pattern.json") == _sha(env.lib / "patterns/p1.pattern.json")
    assert _sha(dest / "products/kama.json") == _sha(env.products / "kama.json")
    assert _sha(dest / "prompts/script_writer.txt") == _sha(env.prompts / "script_writer.txt")
    assert _sha(dest / "library/raw/108/frames/f1.jpg") == _sha(env.lib / "raw/108/frames/f1.jpg")


def test_restore_never_writes_over_running_system(env):
    res = backup.run()
    live_before = {p: _sha(p) for p in env.lib.rglob("*") if p.is_file()}
    for bad in (env.lib, env.tmp, env.lib / "sub", env.products, env.prompts):
        with pytest.raises(backup.BackupError):
            backup.restore(res["path"], bad)
    busy = env.tmp / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(backup.BackupError, match="جديد"):
        backup.restore(res["path"], busy)
    assert (busy / "keep.txt").read_text(encoding="utf-8") == "x"
    assert {p: _sha(p) for p in env.lib.rglob("*") if p.is_file()} == live_before
    empty = env.tmp / "empty_ok"
    empty.mkdir()
    assert backup.restore(res["path"], empty)["ok"]


def test_exclusions_and_source_videos_option(env):
    res = backup.run()
    dest, _ = _restore(env, res["path"])
    rel = {f.relative_to(dest).as_posix() for f in dest.rglob("*") if f.is_file()}
    assert not any(r.startswith("library/_backups") for r in rel)
    assert not any(r.startswith("library/uploads") for r in rel)
    assert "library/raw/108/108.mp4" not in rel
    assert "library/raw/108/extract.json" in rel and "library/raw/108/frames/f1.jpg" in rel
    assert "settings.json" in rel and "manifest.json" not in rel

    res2 = backup.run(include_source_videos=True)
    dest2, _ = _restore(env, res2["path"], "restored2")
    assert (dest2 / "library/raw/108/108.mp4").exists()
    assert res2["files"] > res["files"]


def test_backup_contains_no_keys(env):
    # أسوأ حالة: مفتاح خام لقي طريقه لملف نصي بالمكتبة، وملف إعدادات قديم فيه مفاتيح خام
    (env.lib / "last_note.txt").write_text(f"جرّبت بمفتاح {FAKE_KEY_A} وما زبط", encoding="utf-8")
    env.settings.write_text(json.dumps({**sample_settings(), "BACKUP": {"dir": str(env.out)}}), encoding="utf-8")
    secrets_store.set_secret("crm_token", "crm-token-FAKE-zzzzzzzzzzzzzzzzzzzz")
    res = backup.run()
    assert "library/last_note.txt" in res["redacted"]
    dest, r = _restore(env, res["path"])
    assert r["ok"]
    files = [f for f in dest.rglob("*") if f.is_file()]
    assert files
    for f in files:
        blob = f.read_bytes()
        assert not KEY_RE.search(blob), f.name
        if f.suffix in (".json", ".txt", ".md", ".srt"):
            assert b"sk-" not in blob, f.name
        for k in ALL_FAKE + ["crm-token-FAKE-zzzzzzzzzzzzzzzzzzzz"]:
            assert k.encode() not in blob, f.name
    st = json.loads((dest / "settings.json").read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(st) and "secret:" not in json.dumps(st)
    assert st["CONNECTIONS"]["c_one"]["provider"] == "openai"
    assert secrets_store.get_secret("backup_key").encode() not in b"".join(f.read_bytes() for f in files)


def test_archive_is_encrypted_and_key_dependent(env):
    res = backup.run()
    blob = Path(res["path"]).read_bytes()
    assert blob.startswith(b"VPBK1")
    assert b"pattern_name" not in blob and b"PK\x03\x04" not in blob
    with pytest.raises(backup.BackupError, match="مفتاح"):
        backup.restore(res["path"], env.tmp / "wrongkey", key=backup.Fernet.generate_key().decode())


def test_tampered_or_truncated_archive_is_rejected(env):
    res = backup.run()
    p = Path(res["path"])
    data = bytearray(p.read_bytes())
    data[len(data) // 2] ^= 0xFF
    bad = env.tmp / "bad.vpbak"
    bad.write_bytes(bytes(data))
    with pytest.raises(backup.BackupError):
        backup.restore(bad, env.tmp / "r1")
    cut = env.tmp / "cut.vpbak"
    cut.write_bytes(p.read_bytes()[:-50])
    with pytest.raises(backup.BackupError):
        backup.restore(cut, env.tmp / "r2")


def test_key_export_once_and_restore_on_another_machine(env):
    res = backup.run()
    first = backup.export_key()
    assert first["ok"] and first["key"] == secrets_store.get_secret("backup_key")
    second = backup.export_key()
    assert second["ok"] is False and second["already_exported"] and "key" not in second
    assert first["key"] not in env.settings.read_text(encoding="utf-8")
    assert backup.export_key(force=True)["key"] == first["key"]
    secrets_store.delete_secret("backup_key")
    with pytest.raises(backup.BackupError, match="مفتاح"):
        backup.restore(res["path"], env.tmp / "nokey")
    dest = env.tmp / "other_machine"
    assert backup.restore(res["path"], dest, key=first["key"])["ok"]


def test_same_day_backups_never_overwrite(env):
    a, b, c = backup.run(), backup.run(), backup.run()
    names = sorted(Path(x["path"]).name for x in (a, b, c))
    assert names == ["vidpattern_backup_20260901.vpbak", "vidpattern_backup_20260901_2.vpbak",
                     "vidpattern_backup_20260901_3.vpbak"]
    assert all(Path(x["path"]).exists() for x in (a, b, c))


def test_retention_keeps_last_30(env):
    assert config.BACKUP_KEEP == 30
    for _ in range(33):
        backup.run()
        env.clock["now"] += timedelta(days=1)
    archives = backup.list_archives()
    assert len(archives) == 30
    assert archives[0].name == "vidpattern_backup_20260904.vpbak"
    assert archives[-1].name == "vidpattern_backup_20261003.vpbak"


def test_retention_only_touches_our_files(env):
    env.out.mkdir(parents=True, exist_ok=True)
    (env.out / "family_photos.zip").write_bytes(b"x")
    (env.out / "vidpattern_backup_notes.txt").write_text("x", encoding="utf-8")
    for _ in range(32):
        backup.run()
        env.clock["now"] += timedelta(days=1)
    assert (env.out / "family_photos.zip").exists() and (env.out / "vidpattern_backup_notes.txt").exists()


def test_alert_after_more_than_two_days(env):
    st = backup.status()
    assert st["alert"] is True and st["days_since"] is None
    backup.run()
    assert backup.status()["alert"] is False
    env.clock["now"] += timedelta(days=1, hours=23)
    st = backup.status()
    assert st["alert"] is False and 1.9 < st["days_since"] < 2.0
    env.clock["now"] += timedelta(hours=2)
    st = backup.status()
    assert st["alert"] is True and st["days_since"] > 2
    assert st["alert_reasons"]
    backup.run()
    assert backup.status()["alert"] is False


def test_status_shape_and_failure_recorded(env):
    backup.run()
    st = backup.status()
    assert set(st["last"]) >= {"at", "ok", "path", "files"} and st["last"]["ok"] is True
    assert st["configured"] and st["key_exported"] is False and st["keep"] == 30
    blocker = env.tmp / "afile"
    blocker.write_text("x", encoding="utf-8")
    settings_io.update(lambda s: s.__setitem__("BACKUP", {"dir": str(blocker / "sub")}))
    with pytest.raises(backup.BackupError):
        backup.run()
    st = backup.status()
    assert st["last"]["ok"] is False and st["last"]["error"]
    assert st["days_since"] is not None


def test_not_configured_is_clear_and_daily_skips(env):
    settings_io.update(lambda s: s.pop("BACKUP"))
    with pytest.raises(backup.BackupError, match="غير مضبوط"):
        backup.run()
    res = backup.run_daily_if_due()
    assert res["ok"] and res["skipped"]
    assert backup.status()["alert"] is True


def test_run_daily_if_due_once_per_day(env):
    first = backup.run_daily_if_due()
    assert first["ok"] and "path" in first
    again = backup.run_daily_if_due()
    assert again.get("skipped") and len(backup.list_archives()) == 1
    env.clock["now"] += timedelta(days=1)
    nxt = backup.run_daily_if_due()
    assert "path" in nxt and len(backup.list_archives()) == 2


def test_restore_test_reports_match(env):
    res = backup.restore_test()
    assert set(res) >= {"ok", "files_backup", "files_restored", "match"}
    assert res["ok"] is True and res["match"] is True
    assert res["files_backup"] == res["files_restored"] > 5
    assert not list(Path(env.tmp).glob("vp_restore_*"))


def test_restore_test_detects_corruption(env, monkeypatch):
    real = backup.restore

    def corrupt(archive, dest, key=None):
        r = real(archive, dest, key)
        return {**r, "ok": False, "mismatched": ["products/kama.json"]}
    monkeypatch.setattr(backup, "restore", corrupt)
    assert backup.restore_test()["match"] is False


def test_sqlite_db_snapshot_is_valid(env):
    res = backup.run()
    dest, _ = _restore(env, res["path"])
    conn = sqlite3.connect(dest / "library/usage.db")
    assert conn.execute("SELECT a FROM t").fetchone() == (1,)
    conn.close()


def test_backup_dir_inside_library_is_not_recursed(env):
    settings_io.update(lambda s: s.__setitem__("BACKUP", {"dir": str(env.lib / "out")}))
    backup.run()
    second = backup.run()
    dest, r = _restore(env, second["path"])
    assert r["ok"] and not any(".vpbak" in f.name for f in dest.rglob("*"))


def test_set_config_validates_writability(env):
    ok = backup.set_config(str(env.tmp / "new_dir"), True)
    assert ok["dir"].endswith("new_dir") and ok["include_source_videos"] is True
    (env.tmp / "afile2").write_text("x", encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.set_config(str(env.tmp / "afile2" / "sub"))
