"""عكس ترتيب الاستيراد ما لازم يكسر config/settings_io (استيراد دائري)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code):
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)


def test_settings_io_first():
    r = _run("import settings_io, config; print('ok')")
    assert r.returncode == 0, r.stderr[-400:]


def test_config_first():
    r = _run("import config, settings_io; print('ok')")
    assert r.returncode == 0, r.stderr[-400:]
