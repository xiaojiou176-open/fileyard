import warnings
from pathlib import Path
from typing import Any, cast

import pytest

from packages.infrastructure import gemini_client, image_processing


def _write_png(path: Path, size=(10, 10)):
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGB", size, color=(255, 0, 0))
    img.save(path, format="PNG")


def test_prepare_image_part_raw(tmp_path: Path):
    p = tmp_path / "a.png"
    _write_png(p)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"'_UnionGenericAlias' is deprecated and slated for removal in Python 3.17",
            category=DeprecationWarning,
        )
        part, mime, w, h, upload_name = image_processing.prepare_image_part(p, client=object(), inline_max_mb=10.0, resize_max_side=0)

    assert part is not None
    assert mime == "image/png"
    assert w is None and h is None
    assert upload_name is None


def test_prepare_image_part_converts_to_jpeg(tmp_path: Path):
    p = tmp_path / "a.bin"
    _write_png(p, size=(20, 10))

    part, mime, w, h, upload_name = image_processing.prepare_image_part(p, client=object(), inline_max_mb=10.0, resize_max_side=10)

    assert part is not None
    assert mime == "image/jpeg"
    assert w == 10
    assert h == 5
    assert upload_name is None


def test_extract_exif_fields_no_exif(tmp_path: Path):
    p = tmp_path / "a.png"
    _write_png(p, size=(12, 8))

    out = image_processing.extract_exif_fields(p)
    assert out["width"] == 12
    assert out["height"] == 8
    assert out["exif_datetime"] == ""


def test_prepare_image_part_upload_branch(tmp_path: Path, monkeypatch):
    p = tmp_path / "a.png"
    _write_png(p, size=(10, 10))

    class DummyFile:
        name = "files/123"

    class DummyFiles:
        def upload(self, file: str):
            return DummyFile()

    class DummyClient:
        files = DummyFiles()

    part, mime, w, h, upload_name = image_processing.prepare_image_part(p, client=DummyClient(), inline_max_mb=0.00001, resize_max_side=0)

    assert part is not None
    assert mime == "image/png"
    assert upload_name == "files/123"


def test_prepare_image_part_upload_timeout(tmp_path: Path, monkeypatch):
    p = tmp_path / "a.png"
    _write_png(p, size=(10, 10))

    class DummyFiles:
        def upload(self, file: str):
            return object()

    class DummyClient:
        files = DummyFiles()

    from packages.infrastructure import gemini_client

    monkeypatch.setattr(
        gemini_client,
        "_invoke_with_timeout_hints",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("operation timed out")),
    )
    with pytest.raises(RuntimeError, match="Gemini image upload timed out"):
        image_processing.prepare_image_part(p, client=DummyClient(), inline_max_mb=0.00001, resize_max_side=0, timeout_s=0.1)


def test_prepare_image_part_upload_uses_timeout_hints_first(tmp_path: Path, monkeypatch):
    p = tmp_path / "a.png"
    _write_png(p, size=(10, 10))

    class DummyFile:
        name = "files/456"

    class DummyFiles:
        def upload(self, file: str):
            return DummyFile()

    class DummyClient:
        files = DummyFiles()

    from packages.infrastructure import gemini_client

    captured = {}

    def fake_invoke_with_timeout_hints(func, kwargs, timeout_s):
        captured["timeout_s"] = timeout_s
        captured["kwargs"] = kwargs
        return func(**kwargs)

    monkeypatch.setattr(gemini_client, "_invoke_with_timeout_hints", fake_invoke_with_timeout_hints)

    part, mime, w, h, upload_name = image_processing.prepare_image_part(
        p,
        client=DummyClient(),
        inline_max_mb=0.00001,
        resize_max_side=0,
        timeout_s=7.5,
    )

    assert part is not None
    assert mime == "image/png"
    assert w is None and h is None
    assert upload_name == "files/456"
    assert captured["timeout_s"] == 7.5
    assert captured["kwargs"] == {"file": str(p)}


def test_try_register_heif_false():
    try:
        import pillow_heif  # type: ignore[import-not-found]  # noqa: F401

        expected = True
    except Exception:
        expected = False
    assert image_processing._try_register_heif() is expected


def test_get_exif_handles_open_error(monkeypatch, tmp_path: Path):
    class DummyImage:
        pass

    class DummyImageModule:
        @staticmethod
        def open(path):
            raise RuntimeError("open error")

    class DummyExifTags:
        TAGS: dict[int, str] = {}
        GPSTAGS: dict[int, str] = {}

    monkeypatch.setattr(image_processing, "_lazy_import_pillow", lambda: (DummyImageModule, DummyExifTags))

    p = tmp_path / "a.png"
    p.write_bytes(b"x")

    exif, exif_dt, lat, lon, w, h = image_processing._get_exif(p)
    assert exif == {}
    assert exif_dt is None
    assert lat is None and lon is None
    assert w is None and h is None


def test_get_exif_with_gps(monkeypatch, tmp_path: Path):
    class DummyImageObj:
        size = (100, 50)

        def getexif(self):
            return {
                36867: "2025:01:02 03:04:05",
                34853: {
                    1: "N",
                    2: ((47, 1), (0, 1), (0, 1)),
                    3: "W",
                    4: ((122, 1), (0, 1), (0, 1)),
                },
            }

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
        TAGS: dict[int, str] = {36867: "DateTimeOriginal", 34853: "GPSInfo"}
        GPSTAGS: dict[int, str] = {
            1: "GPSLatitudeRef",
            2: "GPSLatitude",
            3: "GPSLongitudeRef",
            4: "GPSLongitude",
        }

    monkeypatch.setattr(image_processing, "_lazy_import_pillow", lambda: (DummyImageModule, DummyExifTags))

    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")

    exif, exif_dt, lat, lon, w, h = image_processing._get_exif(p)
    assert isinstance(exif, dict)
    assert exif_dt is not None
    assert lat is not None and lon is not None
    assert round(lat, 3) == 47.0
    assert round(lon, 3) == -122.0
    assert w == 100 and h == 50


def test_load_image_as_jpeg_bytes_handles_rgba(tmp_path: Path):
    Image = pytest.importorskip("PIL.Image")
    p = tmp_path / "alpha.png"
    img = Image.new("RGBA", (8, 6), color=(255, 0, 0, 128))
    img.save(p, format="PNG")

    data, mime, w, h = image_processing._load_image_as_jpeg_bytes(p, max_side=None)
    assert len(data) > 0
    assert mime == "image/jpeg"
    assert (w, h) == (8, 6)


def test_prepare_image_part_stat_error(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.png"
    _write_png(p)
    real_stat = Path.stat

    def fake_stat(self):
        if self == p:
            raise OSError("stat failed")
        return real_stat(self)

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(RuntimeError):
        image_processing.prepare_image_part(p, client=object(), inline_max_mb=10.0, resize_max_side=0)


def test_get_exif_heic_branch_and_invalid_datetime(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.heic"
    p.write_bytes(b"x")
    calls = {"registered": 0}

    class DummyCtx:
        size = (12, 8)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getexif(self):
            return {
                306: "bad-datetime",
                34853: {
                    1: "S",
                    2: ((1, 1), (30, 1), (0, 1)),
                    3: "W",
                    4: ((2, 1), (0, 1), (0, 1)),
                },
            }

    class DummyImageModule:
        @staticmethod
        def open(_path):
            return DummyCtx()

    class DummyExifTags:
        TAGS = {306: "DateTime", 34853: "GPSInfo"}
        GPSTAGS = {1: "GPSLatitudeRef", 2: "GPSLatitude", 3: "GPSLongitudeRef", 4: "GPSLongitude"}

    def register_heif() -> bool:
        calls["registered"] += 1
        return True

    monkeypatch.setattr(image_processing, "_lazy_import_pillow", lambda: (DummyImageModule, DummyExifTags))
    monkeypatch.setattr(image_processing, "_try_register_heif", register_heif)

    _exif, exif_dt, lat, lon, w, h = image_processing._get_exif(p)
    assert calls["registered"] == 1
    assert exif_dt is None
    assert lat == -1.5
    assert lon == -2.0
    assert (w, h) == (12, 8)


def test_get_exif_preserves_positive_longitude(monkeypatch, tmp_path: Path):
    p = tmp_path / "b.jpg"
    p.write_bytes(b"x")

    class DummyCtx:
        size = (10, 10)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getexif(self):
            return {
                34853: {
                    1: "N",
                    2: ((1, 1), (0, 1), (0, 1)),
                    3: "E",
                    4: ((2, 1), (0, 1), (0, 1)),
                },
            }

    class DummyImageModule:
        @staticmethod
        def open(_path):
            return DummyCtx()

    class DummyExifTags:
        TAGS = {34853: "GPSInfo"}
        GPSTAGS = {1: "GPSLatitudeRef", 2: "GPSLatitude", 3: "GPSLongitudeRef", 4: "GPSLongitude"}

    monkeypatch.setattr(image_processing, "_lazy_import_pillow", lambda: (DummyImageModule, DummyExifTags))
    _exif, _exif_dt, lat, lon, _w, _h = image_processing._get_exif(p)
    assert lat == 1.0
    assert lon == 2.0


def test_prepare_image_part_timeout_branch(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.png"
    _write_png(p)

    class DummyClient:
        class Files:
            @staticmethod
            def upload(*, file: str):
                return file

        files = Files()

    monkeypatch.setattr(image_processing, "guess_mime", lambda _path: "image/png")
    monkeypatch.setattr(
        gemini_client,
        "_invoke_with_timeout_hints",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("late")),
    )
    with pytest.raises(RuntimeError):
        image_processing.prepare_image_part(
            p,
            client=DummyClient(),
            inline_max_mb=0,
            resize_max_side=0,
            timeout_s=cast(Any, "bad"),
        )


def test_prepare_image_part_zero_timeout_and_rgb_inline_branch(monkeypatch, tmp_path: Path):
    p = tmp_path / "rgb.bmp"
    _write_png(p)

    class DummyCtx:
        mode = "RGB"
        size = (20, 10)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def save(self, buf, format: str, quality: int):
            buf.write(b"jpeg")

    class DummyImageModule:
        @staticmethod
        def open(_path):
            return DummyCtx()

    monkeypatch.setattr(image_processing, "_lazy_import_pillow", lambda: (DummyImageModule, object()))
    data, mime, width, height = image_processing._load_image_as_jpeg_bytes(p, max_side=None)
    assert data == b"jpeg"
    assert mime == "image/jpeg"
    assert (width, height) == (20, 10)

    class DummyClient:
        class Files:
            @staticmethod
            def upload(*, file: str):
                return object()

        files = Files()

    monkeypatch.setattr(image_processing, "guess_mime", lambda _path: "image/png")
    monkeypatch.setattr(gemini_client, "_invoke_with_timeout_hints", lambda *_args, **_kwargs: object())
    part, mime, inline_width, inline_height, upload_name = image_processing.prepare_image_part(
        p,
        client=DummyClient(),
        inline_max_mb=0,
        resize_max_side=0,
        timeout_s=0,
    )
    assert part is not None
    assert mime == "image/png"
    assert inline_width is None and inline_height is None and upload_name is None
