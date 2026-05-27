import datetime as dt
from pathlib import Path

import pytest

from packages.domain import normalization


def test_normalize_categories_adds_other():
    out = normalization.normalize_categories(["工作"])
    assert "工作" in out
    assert "其他" in out


def test_slugify_basic():
    val = normalization.slugify("  Hello 世界!!! ")
    assert val
    assert " " not in val
    assert "世界" in val


def test_safe_join_blocks_traversal(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        normalization.safe_join(root, "..", "evil")


def test_choose_timestamp_prefers_exif():
    row = {
        "exif_datetime": "2025-01-01T12:00:00",
        "file_mtime": "2024-01-01T12:00:00",
    }
    ts = normalization.choose_timestamp(row)
    assert isinstance(ts, dt.datetime)
    assert ts.year == 2025


def test_choose_timestamp_treats_naive_file_mtime_as_utc():
    row = {
        "exif_datetime": "",
        "file_mtime": "2025-01-01T12:00:00",
    }
    ts = normalization.choose_timestamp(row)
    expected = normalization.to_seattle(dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc))
    assert ts == expected
