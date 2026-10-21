"""خلفيات صناديق النماذج. كل خلفية = نموذج واحد بإصدار واحد."""

from __future__ import annotations


class Backend:
    """الواجهة الموحّدة: تحميل، تفريغ، توليد. كل صندوق بيستخدم وحدة بس."""

    name = "base"
    tasks: tuple[str, ...] = ()

    def __init__(self, settings):
        self.settings = settings
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def generate(self, params: dict, image, out, cancel) -> None:  # pragma: no cover - interface
        raise NotImplementedError


def get_backend(name: str, settings) -> Backend:
    if name == "fake":
        from services.engine.backends.fake import FakeBackend
        return FakeBackend(settings)
    if name == "ltx":
        from services.engine.backends.ltx import LtxBackend
        return LtxBackend(settings)
    if name == "wan":
        from services.engine.backends.wan import WanBackend
        return WanBackend(settings)
    raise ValueError(f"خلفية غير معروفة: {name}")
