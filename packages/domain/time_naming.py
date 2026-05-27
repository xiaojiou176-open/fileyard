# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from packages.domain.pipeline_config import DEFAULT_OUTPUT_PARENT


def now_seattle() -> dt.datetime:
    try:
        return dt.datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        # Fall back to a fixed UTC-8 timezone if the tz database is unavailable.
        emergency_tz = dt.timezone(dt.timedelta(hours=-8), name="PST")
        return dt.datetime.now(emergency_tz)


def format_output_timestamp(ts: dt.datetime) -> str:
    return ts.strftime("%Y-%m-%d_%H-%M-%S")


def format_cn_datetime(ts: dt.datetime) -> str:
    # Default output naming stays predictable and globally readable.
    # Keep the legacy helper name as a read-compat alias while the canonical
    # output directory naming moves to an English-first timestamp.
    return format_output_timestamp(ts)


def default_output_root() -> str:
    current = now_seattle()
    return str(DEFAULT_OUTPUT_PARENT / f"organized-images-{format_output_timestamp(current)}")
