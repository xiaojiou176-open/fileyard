import datetime as dt
from pathlib import Path

from packages.domain import core_utils


def test_sha1_file_and_mtime(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    sha1 = core_utils.sha1_file(p)
    assert sha1 == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
    mtime = core_utils.safe_stat_mtime(p)
    assert isinstance(mtime, dt.datetime)
    assert mtime.tzinfo == dt.timezone.utc


def test_truncate_text():
    text = "abcdef"
    assert core_utils.truncate_text(text, 10) == text
    assert core_utils.truncate_text(text, 3) == "..."
    assert core_utils.truncate_text(text, 4) == "a..."


def test_to_seattle_naive_dt():
    ts = dt.datetime(2025, 1, 1, 12, 0, 0)
    converted = core_utils.to_seattle(ts)
    assert converted.tzinfo is not None
