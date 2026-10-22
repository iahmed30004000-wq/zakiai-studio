"""حجز الكرت للاستوديو (gpu_lease): نفس قفل الصناديق، تسليم بروتوكول الصناديق، وما بيعمل شي بدون VP_GPU_LOCK_DIR."""

import os
import signal
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))

pytest.importorskip("filelock")

import gpu_lease  # noqa: E402
import job_signals  # noqa: E402
from services.engine.gpu import GpuLock, Handoff  # noqa: E402


@pytest.fixture
def lockdir(tmp_path, monkeypatch):
    monkeypatch.setenv(gpu_lease.ENV, str(tmp_path / "locks"))
    return tmp_path / "locks"


def test_disabled_or_cpu_models_do_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(gpu_lease.ENV, raising=False)
    assert not gpu_lease.enabled() and gpu_lease.busy() is None
    with gpu_lease.hold() as held:
        assert held is False
    monkeypatch.setenv(gpu_lease.ENV, str(tmp_path / "never_created"))
    with gpu_lease.hold(uses_gpu=False) as held:                               # نموذج ما بيستعمل الكرت
        assert held is False
    assert not (tmp_path / "never_created").exists()


def test_hold_takes_the_same_lock_the_boxes_use(lockdir):
    assert gpu_lease.busy() is False
    with gpu_lease.hold() as held:
        assert held is True and gpu_lease.busy() is True
        box = GpuLock(lockdir)                                                  # صندوق بنفس المجلد المشترك
        assert box.acquire(timeout=0.05) is False
    assert gpu_lease.busy() is False
    box = GpuLock(lockdir)
    assert box.acquire(timeout=0.5) is True
    box.release()


def _box_holds(lockdir, seconds):
    """صندوق (خيط تاني) ماسك الكرت لـ seconds — filelock بيربط القفل بالخيط اللي أخده، فالإفراج لازم من نفس الخيط."""
    got = threading.Event()

    def run():
        box = GpuLock(lockdir)
        assert box.acquire(timeout=2)
        got.set()
        time.sleep(seconds)
        box.release()
    t = threading.Thread(target=run)
    t.start()
    assert got.wait(3)
    return t


def test_hold_waits_for_a_box_then_goes(lockdir):
    t = _box_holds(lockdir, 0.4)
    t0 = time.monotonic()
    with gpu_lease.hold(wait_sec=5):
        waited = time.monotonic() - t0
    t.join()
    assert 0.15 < waited < 4


def test_busy_error_after_the_wait_and_cancel_while_waiting(lockdir):
    t = _box_holds(lockdir, 2.0)
    try:
        with pytest.raises(gpu_lease.GpuBusy, match="الكرت مشغول"):
            with gpu_lease.hold(wait_sec=0.3):
                pass
        ev = threading.Event()
        threading.Timer(0.3, ev.set).start()
        with pytest.raises(gpu_lease.GpuCancelled, match="انلغت"):
            with gpu_lease.hold(wait_sec=10, cancelled=ev.is_set):
                pass
    finally:
        t.join()


def test_the_lock_is_released_when_the_body_fails(lockdir):
    with pytest.raises(RuntimeError):
        with gpu_lease.hold():
            raise RuntimeError("boom")
    assert gpu_lease.busy() is False


def test_two_studio_jobs_never_hold_it_together(lockdir):
    inside, peak, lock = [0], [0], threading.Lock()

    def job():
        with gpu_lease.hold(wait_sec=10):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            time.sleep(0.15)
            with lock:
                inside[0] -= 1
    ts = [threading.Thread(target=job) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1 and inside[0] == 0


def test_it_asks_the_last_box_to_unload_and_goes_once_it_answers(lockdir):
    lockdir.mkdir(parents=True)
    (lockdir / "last_user").write_text("engine", encoding="utf-8")
    box = Handoff(lockdir, "engine")
    seen = []

    def box_side():
        for _ in range(100):
            if box.requested():
                seen.append("asked")
                box.done()
                return
            time.sleep(0.02)
    t = threading.Thread(target=box_side)
    t.start()
    t0 = time.monotonic()
    with gpu_lease.hold():
        pass
    t.join()
    assert seen == ["asked"] and not box.requested() and time.monotonic() - t0 < 10


def test_a_box_that_never_answers_does_not_block_us_forever(lockdir, monkeypatch):
    lockdir.mkdir(parents=True)
    (lockdir / "last_user").write_text("engine", encoding="utf-8")
    monkeypatch.setattr(gpu_lease, "HANDOFF_WAIT_SEC", 0.2)
    with gpu_lease.hold():
        pass
    assert not Handoff(lockdir, "engine").requested()                           # سحبنا الطلب اللي ما انردّ عليه


def test_we_do_not_ask_ourselves(lockdir):
    lockdir.mkdir(parents=True)
    (lockdir / "last_user").write_text(gpu_lease.WHO, encoding="utf-8")
    with gpu_lease.hold():
        assert not Handoff(lockdir, gpu_lease.WHO).requested()


def test_an_unusable_lock_dir_is_an_arabic_error_not_a_crash(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv(gpu_lease.ENV, str(blocker / "sub"))
    with pytest.raises(gpu_lease.GpuBusy, match="قفل الكرت مش متاح"):
        with gpu_lease.hold():
            pass


def test_engine_still_exports_the_classes_it_moved():
    from services.engine import app as engine_app
    from services.engine import gpu
    assert engine_app.GpuLock is gpu.GpuLock and engine_app.Handoff is gpu.Handoff


# ── SIGTERM ───────────────────────────────────────────────────────────────

def test_sigterm_becomes_a_clean_exit_on_posix_and_is_skipped_on_windows():
    if os.name == "nt":
        assert job_signals.install() is False
        return
    prev = signal.getsignal(signal.SIGTERM)
    try:
        assert job_signals.install() is True
        with pytest.raises(SystemExit) as e:
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.2)
        assert e.value.code == job_signals.EXIT_CODE
    finally:
        signal.signal(signal.SIGTERM, prev)


def test_install_is_a_noop_off_the_main_thread():
    out = []
    t = threading.Thread(target=lambda: out.append(job_signals.install()))
    t.start()
    t.join()
    assert out == [False]


def test_job_entry_points_install_the_handler():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in ("motion.py", "generate_voice.py", "image_studio.py", "voice_upload.py"):
        src = (root / name).read_text(encoding="utf-8")
        m = re.search(r"def main\(\) -> None:\n(.*?)\n\n\nif __name__", src, re.S)
        assert m and "job_signals.install()" in m.group(1).split("ap = argparse")[0], name


@pytest.mark.skipif(os.name == "nt", reason="صلاحيات الملفات (POSIX) — على ويندوز ما بتنطبق")
def test_shared_lock_dir_files_are_open_to_every_user_and_a_foreign_unwritable_file_is_replaced(tmp_path):
    """الصناديق (uid 10001) والاستوديو (مستخدم تاني) بيتشاركوا المجلد: ملف القفل وملفات التسليم لازم تنفتح للكل."""
    from services.engine.gpu import GpuLock, Handoff, SHARED_MODE
    d = tmp_path / "locks"
    lock = GpuLock(d)
    assert (d / "gpu.lock").stat().st_mode & 0o777 == SHARED_MODE == 0o666
    h = Handoff(d, "engine")
    h.mark_used()
    h.request_unload("studio")
    assert (d / "last_user").stat().st_mode & 0o777 == 0o666 and (d / "unload_studio.req").stat().st_mode & 0o777 == 0o666
    os.chmod(d / "last_user", 0o444)                                   # ملف لمستخدم تاني بلا صلاحية كتابة
    Handoff(d, "studio").mark_used()
    assert (d / "last_user").read_text(encoding="utf-8") == "studio"   # حذفه وأعاد كتابته (المجلد مفتوح للكل)
    lock.release()


def test_put_replaces_a_handoff_file_it_cannot_write_and_gives_up_quietly_otherwise(tmp_path, monkeypatch):
    """ملف تسليم لمستخدم تاني (ما بنقدر نكتب عليه): بنحذفه ونعيد كتابته. وإذا ما زبط ولا هيك، الكتابة بتفشل بصمت (التسليم تحسين مش شرط)."""
    from pathlib import Path
    import services.engine.gpu as g
    f = tmp_path / "last_user"
    f.write_text("old", encoding="utf-8")
    real = Path.write_text
    seen = {"n": 0}

    def flaky(self, *a, **k):
        if self == f and seen["n"] == 0:
            seen["n"] += 1
            raise PermissionError("denied")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", flaky)
    g._put(f, "studio")
    assert f.read_text(encoding="utf-8") == "studio" and seen["n"] == 1
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("always")))
    h = g.Handoff(tmp_path, "engine")
    h.mark_used()                                                      # بيبلع الخطأ (OSError)
    h.request_unload("studio")
