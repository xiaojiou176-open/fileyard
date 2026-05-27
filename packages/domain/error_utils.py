# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

from packages.domain.pipeline_config import (
    KEY_APPLIED_AT,
    KEY_ERROR,
    KEY_ERROR_CODE,
    KEY_STATUS,
    KEY_STATUS_REASON,
    ErrorCode,
    RowStatus,
)

# -----------------------------
# Error + status helpers
# -----------------------------


def set_error(
    row: Dict[str, Any],
    code: ErrorCode,
    message: str,
    *,
    status_reason: str = "",
) -> None:
    row[KEY_ERROR] = message
    row[KEY_ERROR_CODE] = code.value
    row[KEY_STATUS] = RowStatus.ERROR.value
    if status_reason:
        row[KEY_STATUS_REASON] = status_reason


def clear_error(row: Dict[str, Any]) -> None:
    row[KEY_ERROR] = ""
    row.pop(KEY_ERROR_CODE, None)


def set_status(
    row: Dict[str, Any],
    status: RowStatus,
    *,
    applied_at: Optional[dt.datetime] = None,
    status_reason: str = "",
) -> None:
    row[KEY_STATUS] = status.value
    if status != RowStatus.ERROR:
        row[KEY_ERROR] = ""
        row.pop(KEY_ERROR_CODE, None)
    if status_reason:
        row[KEY_STATUS_REASON] = status_reason
    else:
        row.pop(KEY_STATUS_REASON, None)
    if applied_at is not None:
        row[KEY_APPLIED_AT] = applied_at.isoformat(timespec="seconds")


def ensure_status(row: Dict[str, Any]) -> None:
    if KEY_STATUS not in row:
        row[KEY_STATUS] = RowStatus.PENDING.value
