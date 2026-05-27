# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from packages.domain.pipeline_config import (
    KEY_EXIF_DATETIME,
    KEY_GPS_LAT,
    KEY_GPS_LON,
    KEY_HEIGHT,
    KEY_WIDTH,
    RAW_MIME_ALLOWLIST,
)
from packages.infrastructure.gemini_client import _lazy_import_gemini
from packages.infrastructure.media_scanner import guess_mime


def _lazy_import_pillow():
    try:
        from PIL import ExifTags, Image  # type: ignore
    except Exception as exc:  # pragma: no cover - import error path
        raise RuntimeError("Missing dependency: Pillow. Install it with `pip install pillow`.") from exc
    return Image, ExifTags


def _try_register_heif() -> bool:
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
        return True
    except (ImportError, RuntimeError):
        return False


def _get_exif(
    path: Path,
) -> Tuple[
    Dict[str, Any],
    Optional[dt.datetime],
    Optional[float],
    Optional[float],
    Optional[int],
    Optional[int],
]:
    Image, ExifTags = _lazy_import_pillow()

    if path.suffix.lower() in {".heic", ".heif"}:
        _try_register_heif()

    exif: Dict[str, Any] = {}
    exif_dt: Optional[dt.datetime] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None

    try:
        with Image.open(path) as img:
            raw = img.getexif()
            if raw:
                for tag_id, val in raw.items():
                    tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                    exif[tag] = val
            try:
                width, height = img.size
            except (AttributeError, ValueError):
                width, height = None, None
    except (OSError, RuntimeError):
        return exif, exif_dt, lat, lon, width, height

    for key in ("DateTimeOriginal", "DateTime"):
        value = exif.get(key)
        if value is None:
            continue
        try:
            parsed_dt = dt.datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
        except (TypeError, ValueError):
            parsed_dt = None
        if parsed_dt is not None:
            exif_dt = parsed_dt
            break

    gps = exif.get("GPSInfo")
    if isinstance(gps, dict):
        gps_tags: Dict[str, Any] = {}
        for k, v in gps.items():
            tag = ExifTags.GPSTAGS.get(k, str(k))
            gps_tags[tag] = v

        def _gps_to_deg(val: Any) -> Optional[float]:
            try:
                d = val[0][0] / val[0][1]
                m = val[1][0] / val[1][1]
                s = val[2][0] / val[2][1]
                return d + (m / 60.0) + (s / 3600.0)
            except (IndexError, TypeError, ZeroDivisionError):
                return None

        lat = _gps_to_deg(gps_tags.get("GPSLatitude"))
        lon = _gps_to_deg(gps_tags.get("GPSLongitude"))
        lat_ref = gps_tags.get("GPSLatitudeRef")
        lon_ref = gps_tags.get("GPSLongitudeRef")
        if lat is not None and str(lat_ref).upper() == "S":
            lat = -lat
        if lon is not None and str(lon_ref).upper() == "W":
            lon = -lon

    return exif, exif_dt, lat, lon, width, height


def _load_image_as_jpeg_bytes(path: Path, max_side: Optional[int]) -> Tuple[bytes, str, int, int]:
    Image, _ = _lazy_import_pillow()

    with Image.open(path) as img:
        if img.mode == "RGBA":
            # JPEG 不支持 alpha，先在白底上合成，避免保存时报错。
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        elif img.mode not in ("RGB",):
            img = img.convert("RGB")
        w, h = img.size
        if max_side and max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            w, h = int(w * scale), int(h * scale)
            img = img.resize((w, h))
        from io import BytesIO

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg", w, h


def extract_exif_fields(path: Path) -> Dict[str, Any]:
    _, exif_dt, lat, lon, w, h = _get_exif(path)
    return {
        KEY_EXIF_DATETIME: exif_dt.isoformat(timespec="seconds") if exif_dt else "",
        KEY_GPS_LAT: lat if lat is not None else "",
        KEY_GPS_LON: lon if lon is not None else "",
        KEY_WIDTH: w if w is not None else "",
        KEY_HEIGHT: h if h is not None else "",
    }


def prepare_image_part(
    path: Path,
    client,
    inline_max_mb: float,
    resize_max_side: int,
    *,
    timeout_s: float | None = 60.0,
) -> Tuple[Any, str, Optional[int], Optional[int], Optional[str]]:
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError as exc:
        raise RuntimeError(f"Failed to read image file metadata: {path}") from exc
    _, types = _lazy_import_gemini()
    max_side = resize_max_side if resize_max_side > 0 else None

    if size_mb <= inline_max_mb and path.suffix.lower() in RAW_MIME_ALLOWLIST:
        mime = RAW_MIME_ALLOWLIST[path.suffix.lower()]
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Failed to read image file bytes: {path}") from exc
        image_part = types.Part.from_bytes(data=data, mime_type=mime)
        return image_part, mime, None, None, None

    if size_mb <= inline_max_mb:
        data, mime, w, h = _load_image_as_jpeg_bytes(path, max_side)
        image_part = types.Part.from_bytes(data=data, mime_type=mime)
        return image_part, mime, w, h, None

    from packages.infrastructure.gemini_client import _invoke_with_timeout_hints

    try:
        safe_timeout_s = float(timeout_s) if timeout_s is not None else 60.0
    except (TypeError, ValueError):
        safe_timeout_s = 60.0
    if safe_timeout_s <= 0:
        safe_timeout_s = 60.0
    try:
        # Prefer SDK-native timeout hints first to avoid occupying the shared
        # timeout executor unless the SDK lacks timeout parameters.
        file_ref = _invoke_with_timeout_hints(client.files.upload, {"file": str(path)}, safe_timeout_s)
    except TimeoutError as exc:
        raise RuntimeError(f"Gemini image upload timed out: {exc}") from exc
    upload_name = getattr(file_ref, "name", None)
    return file_ref, guess_mime(path), None, None, upload_name
