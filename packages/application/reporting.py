# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from packages.domain.core_utils import new_run_id
from packages.domain.pipeline_config import (
    AI_CATEGORY,
    AI_KIND,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_LOG_JSON,
    DEFAULT_LOG_LEVEL,
    KEY_AI,
    KEY_ERROR,
    KEY_ERROR_CODE,
    KEY_MEDIA_TYPE,
    KEY_STATUS,
    ErrorCode,
)
from packages.infrastructure.manifest_store import iter_jsonl_chunks
from packages.observability.logging_utils import log_event, setup_logger


@dataclass
class Summary:
    total: int = 0
    with_error: int = 0
    by_media_type: Counter = field(default_factory=Counter)
    by_kind: Counter = field(default_factory=Counter)
    by_category: Counter = field(default_factory=Counter)
    by_status: Counter = field(default_factory=Counter)
    error_codes: Counter = field(default_factory=Counter)

    def update(self, row: Dict[str, Any]) -> None:
        self.total += 1
        if row.get(KEY_ERROR):
            self.with_error += 1
        media_type = row.get(KEY_MEDIA_TYPE, "") or "unknown"
        self.by_media_type[media_type] += 1

        ai = row.get(KEY_AI, {}) or {}
        if isinstance(ai, dict):
            kind = ai.get(AI_KIND, "") or ""
            category = ai.get(AI_CATEGORY, "") or ""
            if kind:
                self.by_kind[kind] += 1
            if category:
                self.by_category[category] += 1

        status = row.get(KEY_STATUS, "") or ""
        if status:
            self.by_status[status] += 1

        code = row.get(KEY_ERROR_CODE, "") or ""
        if code:
            self.error_codes[code] += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "with_error": self.with_error,
            "by_media_type": dict(self.by_media_type),
            "by_kind": dict(self.by_kind),
            "by_category": dict(self.by_category),
            "by_status": dict(self.by_status),
            "error_codes": dict(self.error_codes),
        }


def write_report(path: Path, summary: Summary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    try:
        partial.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        partial.replace(path)
    except Exception:
        if partial.exists():
            with suppress(OSError):
                stamp = int(time.time() * 1000)
                crash_path = Path(str(partial) + f".crash-{stamp}")
                os.replace(str(partial), str(crash_path))
        raise


def generate_report(
    manifest_path: Path,
    out_path: Path,
    *,
    validate: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Summary:
    summary = Summary()
    for chunk in iter_jsonl_chunks(manifest_path, validate=validate, chunk_size=chunk_size):
        for row in chunk:
            summary.update(row)
    write_report(out_path, summary)
    return summary


def cmd_report(args: argparse.Namespace) -> None:
    logger = setup_logger(getattr(args, "log_level", DEFAULT_LOG_LEVEL), getattr(args, "log_json", DEFAULT_LOG_JSON))
    start_ts = time.monotonic()
    run_id = getattr(args, "run_id", "") or new_run_id("report")
    manifest_path = Path(args.manifest).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    validate = bool(getattr(args, "validate", False))
    chunk_size = int(getattr(args, "chunk_size", DEFAULT_CHUNK_SIZE) or DEFAULT_CHUNK_SIZE)
    if chunk_size <= 0:
        chunk_size = DEFAULT_CHUNK_SIZE

    log_event(
        logger,
        logging.INFO,
        "run_start",
        "Report run start",
        run_id=run_id,
        manifest=str(manifest_path),
        out=str(out_path),
        validate=validate,
        chunk_size=chunk_size,
    )
    summary = Summary()
    try:
        for chunk in iter_jsonl_chunks(manifest_path, validate=validate, chunk_size=chunk_size):
            for row in chunk:
                summary.update(row)
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "manifest_read_fail",
            f"Failed to read manifest: {exc}",
            error_code=ErrorCode.MANIFEST_READ_FAIL.value,
            exception=exc,
            run_id=run_id,
        )
        raise SystemExit(f"Failed to read manifest: {exc}") from exc
    try:
        write_report(out_path, summary)
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "report_write_fail",
            f"Failed to write report: {exc}",
            error_code=ErrorCode.REPORT_WRITE_FAIL.value,
            exception=exc,
            run_id=run_id,
        )
        raise SystemExit(f"Failed to write report: {exc}") from exc
    log_event(
        logger,
        logging.INFO,
        "report_written",
        "Wrote report",
        path=str(out_path),
        total=summary.total,
        with_error=summary.with_error,
        run_id=run_id,
    )
    elapsed = round(time.monotonic() - start_ts, 3)
    log_event(
        logger,
        logging.INFO,
        "run_end",
        "Report run end",
        run_id=run_id,
        duration_s=elapsed,
        total=summary.total,
        with_error=summary.with_error,
        error_codes=dict(summary.error_codes),
    )
