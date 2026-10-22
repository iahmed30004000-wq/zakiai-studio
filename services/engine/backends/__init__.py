"""خلفيات صناديق النماذج. كل خلفية = نموذج واحد بإصدار واحد."""

from __future__ import annotations


class Backend:
    """الواجهة الموحّدة: تحميل، تفريغ، توليد. كل صندوق بيستخدم وحدة بس."""

    name = "base"
    tasks: tuple[str, ...] = ()
    loaded_model: str | None = None            # النموذج المحمّل هلأ (الصندوق العام)؛ الصناديق القديمة نموذجها ثابت

    def __init__(self, settings):
        self.settings = settings
        self.loaded = False

    def validate_params(self, p: dict) -> dict:
        """فحص إضافي للطلب قبل ما المهمة تنقبل (الصندوق العام: النموذج والنمط). ValueError بسبب عربي ← 400."""
        return p

    def list_models(self, refresh: bool = False) -> list[dict]:
        """GET /models. الصناديق القديمة: نموذج ثابت وحيد."""
        return [{"name": self.name, "kind": "video", "pipeline": "", "family": self.name, "tasks": list(self.tasks), "size_gb": None,
                 "licence": {"id": "غير معروفة", "commercial": "unknown"}, "ok": True, "reason": "", "note": "صندوق بنموذج ثابت"}]

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
    if name == "fake-images":
        from services.engine.backends.fake import FakeImagesBackend
        return FakeImagesBackend(settings)
    if name == "ltx":
        from services.engine.backends.ltx import LtxBackend
        return LtxBackend(settings)
    if name == "wan":
        from services.engine.backends.wan import WanBackend
        return WanBackend(settings)
    if name == "diffusers":
        from services.engine.backends.diffusers_any import DiffusersAnyBackend
        return DiffusersAnyBackend(settings)
    raise ValueError(f"خلفية غير معروفة: {name}")
