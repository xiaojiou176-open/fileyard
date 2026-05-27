import datetime as dt

from packages.domain import time_naming


def test_format_output_timestamp_morning():
    ts = dt.datetime(2025, 1, 1, 0, 5, 6)
    text = time_naming.format_output_timestamp(ts)
    assert text == "2025-01-01_00-05-06"


def test_format_output_timestamp_afternoon():
    ts = dt.datetime(2025, 1, 1, 15, 4, 3)
    text = time_naming.format_cn_datetime(ts)
    assert text == "2025-01-01_15-04-03"


def test_now_seattle_tz():
    ts = time_naming.now_seattle()
    assert ts.tzinfo is not None


def test_default_output_root_prefix():
    root = time_naming.default_output_root()
    assert "organized-images-" in root


def test_now_seattle_fallback_when_zoneinfo_fails(monkeypatch):
    monkeypatch.setattr(time_naming, "ZoneInfo", lambda *_: (_ for _ in ()).throw(RuntimeError("bad tz")))
    ts = time_naming.now_seattle()
    assert ts.tzinfo is not None
