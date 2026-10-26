"""مزامنة النواتج مع درايف (drive_sync.py): الجمع والطابور وعدم التكرار والإعادة — على خادم Google وهمي (tests/fake_drive.py)."""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from a_helpers import env  # noqa: E402,F401
from fake_drive import RT, connect, drive  # noqa: E402,F401

import config  # noqa: E402
import drive_sync  # noqa: E402
import gdrive  # noqa: E402
import studio_state  # noqa: E402

STEM = "testp__p1__20261026_1000"
REAL_DAILY = drive_sync.daily_globals


@pytest.fixture(autouse=True)
def _no_daily(monkeypatch):
    """الأنماط ومكتبة الصوت (مرة باليوم) بنختبرها لحالها — باقي الاختبارات بتشوف الإعلان بس."""
    monkeypatch.setattr(drive_sync, "daily_globals", lambda: False)


def _w(p: Path, data: bytes | str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def make_mission(env, stem=STEM, status="approved", script_id="VP-testp-1-v2"):
    """مهمة موجّهة جاهزة بكل نواتجها (ملفات صغيرة) — المحطات بتتعتمد بالاختبار نفسه."""
    lib = Path(config.LIBRARY_DIR)
    script = {"title": "كريم للبشرة", "hook_line": "شو السر؟", "cta_line": "اطلب هلق",
              "hooks": [{"id": "h1", "type": "question", "spoken": "شو السر؟", "on_screen_text": "السر", "visual": "", "why": ""},
                        {"id": "h2", "type": "shock", "spoken": "ما حدا قلك!", "on_screen_text": "", "visual": "", "why": ""}],
              "hook_main": "h2",
              "scenes": [{"scene_number": 1, "duration_sec": 6, "purpose": "هوك", "voiceover": "شو السر؟", "on_screen_text": "السر", "visual": "بنت"},
                         {"scene_number": 2, "duration_sec": 7, "purpose": "حل", "voiceover": "جربي الكريم", "on_screen_text": "", "visual": "علبة"}],
              "_meta": {"product": "كريم التفتيح", "product_code": "testp", "number": 1, "version": 2, "script_id": script_id, "status": status}}
    _w(lib / "scripts" / f"{stem}.json", json.dumps(script, ensure_ascii=False))
    tdir = lib / "timelines" / stem
    _w(tdir / "img" / "s1c1_1_1080.png", b"IMG-1")
    _w(tdir / "img" / "s1c1_1_comp.png", b"IMG-1-COMP")
    _w(tdir / "img" / "s2c1_1_1080.png", b"IMG-2")
    _w(tdir / "clips" / "s1c1_a.mp4", b"CLIP-1")
    _w(tdir / "clips" / "s2c1_a.mp4", b"CLIP-2")
    _w(lib / "voice" / stem / "full.mp3", b"VOICE-FULL")
    _w(lib / "voice" / stem / "scene_01.mp3", b"V1")
    _w(lib / "voice" / stem / "scene_02.mp3", b"V2")
    _w(lib / "voice" / stem / "voice.json", json.dumps({"scenes": [{"scene": 1, "path": f"voice/{stem}/scene_01.mp3"},
                                                                   {"scene": 2, "path": f"voice/{stem}/scene_02.mp3"}],
                                                        "combined": {"path": f"voice/{stem}/full.mp3"}}))
    _w(lib / "exports" / f"{script_id}.mp4", b"FINAL")
    _w(lib / "ahat" / "ah_001" / "audio.mp3", b"MUSIC")
    _w(lib / "ahat" / "ah_001" / "track.json", json.dumps({"id": "ah_001", "name": "هادية", "mood": "calm", "audio": "audio.mp3", "approved": True}))
    _w(lib / "ahat" / "ah_002" / "audio.mp3", b"NOT-APPROVED")
    _w(lib / "ahat" / "ah_002" / "track.json", json.dumps({"id": "ah_002", "name": "غير", "mood": "calm", "audio": "audio.mp3", "approved": False}))
    tl = {"script_id": script_id, "voice": {"audio": f"voice/{stem}/full.mp3"},
          "scenes": [{"n": 1, "shots": [{"id": "s1c1", "image": {"chosen": "img/s1c1_1_1080.png", "composite": "img/s1c1_1_comp.png"},
                                         "motion": {"clip": "clips/s1c1_a.mp4"}}]},
                     {"n": 2, "shots": [{"id": "s2c1", "image": {"chosen": "img/s2c1_1_1080.png"}, "motion": {"clip": "clips/s2c1_a.mp4"}}]}],
          "ambience": {"track_id": "ah_001"}, "sfx": [{"track_id": "ah_002"}],
          "render": {"final": {"file": f"exports/{script_id}.mp4"}}}
    _w(tdir / "timeline.json", json.dumps(tl, ensure_ascii=False))
    return lib


def approve_all(stem=STEM):
    for n in (4, 7, 9, 10):
        studio_state.set_state(stem, n, "approved")


def paths(fd) -> set[str]:
    return {fd.path_of(f["id"]) for f in fd.files.values() if f["mimeType"] != "application/vnd.google-apps.folder"}


def run(n=3):
    out = None
    for _ in range(n):
        out = drive_sync.tick()
    return out


AD = "Zakiai/كريم التفتيح/VP-testp-1"


# ── بلا ربط ما في شي ────────────────────────────────────────────────────
def test_disabled_env_is_noop(env, monkeypatch):
    monkeypatch.setenv("VIDPATTERN_NO_DRIVE", "1")
    make_mission(env)
    approve_all()
    assert not drive_sync.db_path().exists()
    assert drive_sync.tick()["idle"]


def test_not_connected_is_noop(drive, env):
    make_mission(env)
    approve_all()
    assert drive_sync.request_ad(STEM) is False
    assert not drive_sync.db_path().exists()
    assert drive_sync.request_ad(STEM, manual=True) is False      # حتى الزر اليدوي بلا ربط


def test_auto_off_only_manual(drive, env):
    connect(drive)
    gdrive.write_cfg(lambda c: c.update(auto=False))
    make_mission(env)
    approve_all()
    assert drive_sync.status()["requests"] == 0
    assert drive_sync.request_ad(STEM, manual=True)
    assert drive_sync.status()["requests"] == 1


# ── الرحلة الكاملة ───────────────────────────────────────────────────────
def test_full_mission_layout(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()                                         # لحظات الموافقة بتسجّل الطلب لحالها
    assert drive_sync.status()["requests"] == 1
    r = run()
    assert r["ok"]
    got = paths(drive)
    assert got == {f"{AD}/1-نص/النص والهوكات", f"{AD}/2-صور/مشهد-01-لقطة-1.png", f"{AD}/2-صور/مشهد-02-لقطة-1.png",
                   f"{AD}/3-صوت/الصوت-كامل.mp3", f"{AD}/3-صوت/مشهد-01.mp3", f"{AD}/3-صوت/مشهد-02.mp3",
                   f"{AD}/4-تحريك/مشهد-01-لقطة-1.mp4", f"{AD}/4-تحريك/مشهد-02-لقطة-1.mp4",
                   f"{AD}/5-موسيقى/هادية.mp3", f"{AD}/6-نهائي/VP-testp-1-v2.mp4"}
    img1 = next(f for f in drive.files.values() if drive.path_of(f["id"]) == f"{AD}/2-صور/مشهد-01-لقطة-1.png")
    assert img1["content"] == b"IMG-1-COMP"                     # المركّبة قبل المختارة
    doc = next(f for f in drive.files.values() if f["name"] == "النص والهوكات")
    assert doc["mimeType"] == gdrive.DOC_MIME
    text = doc["content"].decode("utf-8")
    assert 'dir="rtl"' in text and "ما حدا قلك!" in text and "⭐" in text and "جربي الكريم" in text
    st = drive_sync.status()
    assert st["pending"] == 0 and st["last_ok"] and st["folder_url"].startswith("https://drive.google.com/drive/folders/")
    ad = drive_sync.ad_status(STEM)
    assert ad["pending"] == 0 and ad["last_ok"] and ad["folder_url"]


def test_only_approved_stations(drive, env):
    connect(drive)
    make_mission(env, status="draft")
    studio_state.set_state(STEM, 4, "approved")                # الصوت بس
    run()
    got = paths(drive)
    assert got == {f"{AD}/3-صوت/الصوت-كامل.mp3", f"{AD}/3-صوت/مشهد-01.mp3", f"{AD}/3-صوت/مشهد-02.mp3", f"{AD}/5-موسيقى/هادية.mp3"}


def test_no_duplicates_and_update_in_place(drive, env):
    connect(drive)
    lib = make_mission(env)
    approve_all()
    run()
    n_up = len(drive.uploads())
    n_files = len(drive.files)
    drive_sync.request_ad(STEM, manual=True)
    run()
    assert len(drive.uploads()) == n_up and len(drive.files) == n_files     # نفس البصمة: ما انبعت شي
    _w(lib / "timelines" / STEM / "img" / "s2c1_1_1080.png", b"IMG-2-NEW")
    studio_state.set_state(STEM, 7, "approved")
    run()
    f = next(f for f in drive.files.values() if drive.path_of(f["id"]) == f"{AD}/2-صور/مشهد-02-لقطة-1.png")
    assert f["content"] == b"IMG-2-NEW" and f["revisions"] == 2 and len(drive.files) == n_files
    assert len(drive.uploads()) == n_up + 1


def test_rewrite_version_keeps_same_ad_folder(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()
    run()
    make_mission(env, script_id="VP-testp-1-v3")                # إعادة كتابة: v2 ← v3
    studio_state.set_state(STEM, 10, "approved")
    run()
    finals = {p for p in paths(drive) if "/6-نهائي/" in p}
    assert finals == {f"{AD}/6-نهائي/VP-testp-1-v2.mp4", f"{AD}/6-نهائي/VP-testp-1-v3.mp4"}
    assert len([f for f in drive.files.values() if f["name"] == "VP-testp-1"]) == 1


def test_lost_local_db_does_not_duplicate(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()
    run()
    n_files = len(drive.files)
    drive_sync.db_path().unlink()
    for x in Path(config.LIBRARY_DIR).glob("drive.db*"):
        x.unlink()
    drive_sync.request_ad(STEM, manual=True)
    run()
    assert len(drive.files) == n_files                          # لقيناهم بالمفتاح المكتوب عالملف (appProperties)


def test_folder_deleted_on_drive_is_recreated(drive, env):
    connect(drive)
    lib = make_mission(env)
    approve_all()
    run()
    imgs = next(f for f in drive.files.values() if f["name"] == "2-صور")
    imgs["trashed"] = True
    _w(lib / "timelines" / STEM / "img" / "s2c1_1_1080.png", b"IMG-2-NEW")
    drive_sync.request_ad(STEM, manual=True)
    run()
    live = [f for f in drive.files.values() if f["name"] == "2-صور" and not f["trashed"]]
    assert len(live) == 1


# ── الأعطال والطابور ────────────────────────────────────────────────────
def test_transient_error_retries_later(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()
    drive.modes["upload"] = "500"
    r = drive_sync.tick()
    assert r["failed"] >= 1
    st = drive_sync.status()
    assert st["pending"] == 10 and "Google" in st["last_error"]
    assert drive_sync.tick()["done"] == 0                        # لسا ما إجا وقت الإعادة
    drive.modes["upload"] = ""
    drive_sync.retry_now()
    run()
    assert drive_sync.status()["pending"] == 0 and len(paths(drive)) == 10


def test_offline_stops_and_resumes(drive, env, monkeypatch):
    connect(drive)
    make_mission(env)
    approve_all()
    real = gdrive._send

    def no_net(*a, **k):
        raise gdrive.DriveTransient("تعذّر الاتصال بـ Google (الإنترنت؟)", "network")
    monkeypatch.setattr(gdrive, "_send", no_net)
    r = drive_sync.tick()
    assert r.get("offline") and r["done"] == 0
    assert drive_sync.status()["pending"] == 10
    monkeypatch.setattr(gdrive, "_send", real)
    drive_sync.retry_now()
    run()
    assert len(paths(drive)) == 10


def test_quota_pauses_queue(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()
    drive.modes["upload"] = "quota"
    r = drive_sync.tick()
    assert r["paused"] == "full"
    st = drive_sync.status()
    assert st["paused"] == "full" and "مليان" in st["paused_msg"]
    assert drive_sync.tick()["paused"] == "full"
    drive.modes["upload"] = ""
    drive_sync.retry_now()
    run()
    assert len(paths(drive)) == 10 and not drive_sync.status()["paused"]


def test_revoked_access_pauses_with_auth(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()
    gdrive.forget_token()
    drive.revoked = True
    assert drive_sync.tick()["paused"] == "auth"
    assert "اربط من جديد" in drive_sync.status()["paused_msg"]


def test_big_file_skipped(drive, env, monkeypatch):
    connect(drive)
    make_mission(env)
    monkeypatch.setattr(drive_sync, "MAX_FILE", 6)
    studio_state.set_state(STEM, 10, "approved")
    run()
    st = drive_sync.ad_status(STEM)
    assert st["skipped"] >= 1


def test_resumable_session_survives_restart(drive, env, monkeypatch):
    connect(drive)
    lib = make_mission(env)
    monkeypatch.setattr(gdrive, "SIMPLE_MAX", 10)
    monkeypatch.setattr(gdrive, "CHUNK", 256 * 1024)
    big = os.urandom(256 * 1024 * 3)
    _w(lib / "exports" / "VP-testp-1-v2.mp4", big)
    drive.modes["resumable"] = "drop"
    studio_state.set_state(STEM, 10, "approved")
    drive_sync.tick()
    with sqlite3.connect(drive_sync.db_path()) as c:
        url = c.execute("SELECT upload_url FROM outbox WHERE name='VP-testp-1-v2.mp4'").fetchone()[0]
    assert url and url.startswith(drive.base)
    drive_sync.retry_now()
    run()
    f = next(f for f in drive.files.values() if f["name"] == "VP-testp-1-v2.mp4")
    assert f["content"] == big
    with sqlite3.connect(drive_sync.db_path()) as c:
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0] == 0


def test_no_secrets_in_db_or_status(drive, env):
    connect(drive)
    make_mission(env)
    approve_all()
    run()
    raw = b"".join(p.read_bytes() for p in Path(config.LIBRARY_DIR).glob("drive.db*"))
    assert RT.encode() not in raw and b"at-" not in raw
    assert RT not in json.dumps(drive_sync.status())


# ── المشروع الحر والأنماط والأصوات ─────────────────────────────────────
def test_free_project(drive, env):
    connect(drive)
    lib = Path(config.LIBRARY_DIR)
    stem = "free__20261026__تجربة"
    _w(lib / "scripts" / f"{stem}.json", json.dumps({"title": "تجربة", "scenes": [], "_meta": {"mode": "free", "script_id": "FREE-20261026-ab12"}}))
    tdir = lib / "timelines" / stem
    _w(tdir / "img" / "s1c1_up.png", b"P")
    _w(tdir / "voice" / "1.wav", b"W")
    _w(lib / "exports" / "FREE-20261026-ab12.mp4", b"F")
    _w(tdir / "timeline.json", json.dumps({"mode": "free", "scenes": [{"n": 1, "voice": {"audio": f"timelines/{stem}/voice/1.wav"},
                                                                       "shots": [{"id": "s1c1", "image": {"chosen": "img/s1c1_up.png"}}]}],
                                           "render": {"final": {"file": "exports/FREE-20261026-ab12.mp4"}}}))
    assert drive_sync.request_ad(stem)
    run()
    base = "Zakiai/مشاريع حرة/FREE-20261026-ab12"
    assert paths(drive) == {f"{base}/1-نص/النص والهوكات", f"{base}/2-صور/مشهد-01-لقطة-1.png",
                            f"{base}/3-صوت/مشهد-01.wav", f"{base}/6-نهائي/FREE-20261026-ab12.mp4"}


def test_patterns_and_sounds(drive, env):
    connect(drive)
    make_mission(env)
    env.pattern("p_one", name="نمط السؤال")
    assert REAL_DAILY() and not REAL_DAILY()                                   # مرة باليوم
    run()
    got = paths(drive)
    assert "Zakiai/الأنماط/نمط السؤال (p_one)" in got
    assert "Zakiai/مكتبة الصوت/ah_001 - هادية.mp3" in got
    assert not any("ah_002" in p for p in got)                                 # غير المعتمد ما بينبعت
    n_up = len(drive.uploads())
    drive_sync.request("patterns", manual=True)
    run()
    assert len(drive.uploads()) == n_up


def test_ahat_approve_requests_sounds(drive, env):
    import ahat
    connect(drive)
    make_mission(env)
    ahat.approve("ah_002", heard=True)
    with sqlite3.connect(drive_sync.db_path()) as c:
        assert c.execute("SELECT COUNT(*) FROM requests WHERE target='sounds'").fetchone()[0] == 1


def test_script_approve_requests_ad(drive, env, monkeypatch):
    import review_loop
    connect(drive)
    make_mission(env, status="draft")
    monkeypatch.setattr(review_loop, "_set_meta", lambda path, **kw: {})
    review_loop._finish(Path(config.SCRIPTS_DIR) / f"{STEM}.json", "approved", "", 1, [], None)
    with sqlite3.connect(drive_sync.db_path()) as c:
        assert c.execute("SELECT COUNT(*) FROM requests WHERE target=?", (f"ad:{STEM}",)).fetchone()[0] == 1


def test_sync_all_and_forget(drive, env):
    connect(drive)
    make_mission(env)
    studio_state.set_state(STEM, 4, "approved")
    with sqlite3.connect(drive_sync.db_path()) as c:
        c.execute("DELETE FROM requests")
    assert drive_sync.sync_all() == 3                          # الإعلان + الأنماط + الأصوات
    run()
    drive_sync.forget_all()
    assert drive_sync.status()["last_ok"] is None


@pytest.mark.parametrize("sid,want", [("VP-kama-2-v3", "VP-kama-2"), ("VP-kama-2-v1-h2", "VP-kama-2-h2"), ("FREE-1-ab", "FREE-1-ab")])
def test_stable_id(sid, want):
    assert drive_sync.stable_id({"_meta": {"script_id": sid}}, "x") == want


def test_stable_id_old_scripts():
    assert drive_sync.stable_id({"_meta": {"product": "kama", "number": 2}}, "x") == "VP-kama-2"
    assert drive_sync.stable_id({}, "kama__p__1") == "kama__p__1"
    assert drive_sync.clean_name("a/b\\c") == "a-b-c"
