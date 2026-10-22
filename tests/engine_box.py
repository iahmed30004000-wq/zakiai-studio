"""صندوق حقيقي للاختبارات: خدمة المحرك (services/engine) على uvicorn بخيط على 127.0.0.1 — بخلفية تجريبية، بلا كرت ولا Docker ولا إنترنت.

    from engine_box import box_factory, png            # fixture + مساعد
    def test_x(box_factory):
        box = box_factory()                             # الخلفية الافتراضية fake-images (الصندوق العام v2)
        box.url, box.token, box.app.state.engine["jobs"]
"""

from __future__ import annotations

import io
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def png(size=(64, 96), color=(200, 60, 60)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


@dataclass
class Box:
    url: str
    token: str | None
    app: object
    srv: object
    thread: threading.Thread

    @property
    def engine(self) -> dict:
        return self.app.state.engine

    @property
    def jobs(self) -> dict:
        return self.app.state.engine["jobs"]

    def stop(self) -> None:
        self.srv.should_exit = True
        self.thread.join(10)


def start_box(tmp_path: Path, *, backend: str = "fake-images", token: str | None = None, name: str | None = None, backend_obj=None, **over) -> Box:
    import uvicorn

    from services.engine.app import Settings, create_app
    port = free_port()
    s = Settings(backend=backend, name=name or f"t{port}", outputs=tmp_path / f"box_{port}" / "out", lock_dir=tmp_path / "locks",
                 weights_dir=tmp_path / "weights", token=token, lock_poll_sec=0.05, **over)
    app = create_app(s, backend=backend_obj)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    end = time.time() + 15
    while not srv.started and time.time() < end:
        time.sleep(0.02)
    assert srv.started, "الصندوق ما قام"
    return Box(f"http://127.0.0.1:{port}", token, app, srv, th)


@pytest.fixture
def box_factory(tmp_path):
    made: list[Box] = []

    def make(**kw) -> Box:
        b = start_box(tmp_path, **kw)
        made.append(b)
        return b

    yield make
    for b in made:
        b.stop()
