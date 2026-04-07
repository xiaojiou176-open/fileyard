import builtins

import pytest

from packages.infrastructure import image_processing


def test_lazy_import_pillow_error(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL":
            raise ImportError("no pillow")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError):
        image_processing._lazy_import_pillow()


def test_get_exif_heic_triggers_register(monkeypatch, tmp_path):
    called = {"n": 0}

    class DummyImageObj:
        size = (10, 10)

        def getexif(self):
            return {}

    class DummyCtx:
        def __enter__(self):
            return DummyImageObj()

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyImageModule:
        @staticmethod
        def open(path):
            return DummyCtx()

    class DummyExifTags:
        TAGS = {}
        GPSTAGS = {}

    monkeypatch.setattr(image_processing, "_lazy_import_pillow", lambda: (DummyImageModule, DummyExifTags))
    monkeypatch.setattr(
        image_processing,
        "_try_register_heif",
        lambda: called.__setitem__("n", called["n"] + 1) or True,
    )

    p = tmp_path / "a.heic"
    p.write_bytes(b"x")

    image_processing._get_exif(p)
    assert called["n"] == 1
