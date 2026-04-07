import datetime as dt

from packages.domain.error_utils import clear_error, ensure_status, set_error, set_status
from packages.domain.pipeline_config import ErrorCode, RowStatus


def test_set_error_and_clear():
    row = {}
    set_error(row, ErrorCode.SOURCE_MISSING, "missing")
    assert row["error"] == "missing"
    assert row["error_code"] == ErrorCode.SOURCE_MISSING.value
    assert row["status"] == RowStatus.ERROR.value

    row = {}
    set_error(row, ErrorCode.SOURCE_MISSING, "missing", status_reason="why")
    assert row["status_reason"] == "why"

    clear_error(row)
    assert row.get("error") == ""
    assert "error_code" not in row


def test_set_status_applied():
    row = {}
    ensure_status(row)
    assert row["status"] == RowStatus.PENDING.value

    ts = dt.datetime(2025, 1, 1, 12, 0, 0)
    set_status(row, RowStatus.APPLIED, applied_at=ts)
    assert row["status"] == RowStatus.APPLIED.value
    assert row["applied_at"] == "2025-01-01T12:00:00"


def test_set_status_clears_error_and_status_reason():
    row = {"error": "boom", "error_code": "X", "status_reason": "old"}
    set_status(row, RowStatus.APPLIED, status_reason="done")
    assert row["error"] == ""
    assert "error_code" not in row
    assert row["status_reason"] == "done"

    set_status(row, RowStatus.PENDING)
    assert "status_reason" not in row
