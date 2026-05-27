# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from packages.application.apply_safety_helpers import _is_filesystem_root, _is_within_root, _next_overwrite_backup_path
from packages.application.rollback_workflow import (
    load_rollback_rows,
    process_rollback_rows,
    resolve_allowed_roots,
)
from packages.domain.core_utils import new_run_id
from packages.domain.pipeline_config import DEFAULT_LOG_JSON, DEFAULT_LOG_LEVEL, ErrorCode
from packages.domain.rollback_integrity import (
    _has_strong_rollback_signing_key,
    _normalize_run_id,
    _verify_rollback_record,
)
from packages.infrastructure.manifest_store import read_jsonl
from packages.observability.logging_utils import log_event, setup_logger


def cmd_rollback(args: argparse.Namespace) -> None:
    logger = setup_logger(getattr(args, "log_level", DEFAULT_LOG_LEVEL), getattr(args, "log_json", DEFAULT_LOG_JSON))
    start_ts = time.monotonic()
    run_id = getattr(args, "run_id", "") or new_run_id("rollback")
    try:
        run_id = _normalize_run_id(run_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    deps = {
        "log_event": log_event,
        "is_filesystem_root": _is_filesystem_root,
        "is_within_root": _is_within_root,
        "read_jsonl": read_jsonl,
        "verify_rollback_record": _verify_rollback_record,
        "next_overwrite_backup_path": _next_overwrite_backup_path,
    }
    allowed_roots = resolve_allowed_roots(
        args,
        logger=logger,
        run_id=run_id,
        deps=deps,
    )

    manifest_path = Path(args.manifest).expanduser().resolve()
    rows = load_rollback_rows(
        manifest_path,
        logger=logger,
        run_id=run_id,
        deps=deps,
    )

    log_event(
        logger,
        logging.INFO,
        "run_start",
        "Rollback run start",
        run_id=run_id,
        manifest=str(manifest_path),
        dry_run=bool(getattr(args, "dry_run", False)),
        overwrite=bool(getattr(args, "overwrite", False)),
        allowed_root=",".join(str(p) for p in allowed_roots),
    )

    strict_integrity = bool(getattr(args, "strict_integrity", False))
    if strict_integrity and not _has_strong_rollback_signing_key():
        log_event(
            logger,
            logging.ERROR,
            "rollback_integrity_key_required",
            "strict_integrity=true requires FILEMAN_ROLLBACK_HMAC_KEY",
            run_id=run_id,
            error_code=ErrorCode.INPUT_ROOT_INVALID.value,
        )
        raise SystemExit("strict_integrity=true requires FILEMAN_ROLLBACK_HMAC_KEY")
    stats = process_rollback_rows(
        rows,
        args=args,
        logger=logger,
        run_id=run_id,
        allowed_roots=allowed_roots,
        strict_integrity=strict_integrity,
        deps=deps,
    )

    if strict_integrity and stats.rollback_candidates > 0 and stats.strict_valid_candidates == 0:
        log_event(
            logger,
            logging.ERROR,
            "rollback_strict_integrity_no_valid_candidate",
            "strict_integrity validation failed: rollback candidates exist but all are invalid",
            run_id=run_id,
            rollback_candidates=stats.rollback_candidates,
            strict_valid_candidates=stats.strict_valid_candidates,
            skipped_invalid=stats.skipped_invalid,
            error_code=ErrorCode.ROLLBACK_FAIL.value,
        )
        raise SystemExit("strict_integrity validation failed: rollback candidates exist but all are invalid")

    if not args.dry_run:
        log_event(logger, logging.INFO, "restored_files", "Restored files", count=stats.restored, run_id=run_id)
    if stats.skipped_missing_src or stats.skipped_existing_dst or stats.skipped_invalid:
        log_event(
            logger,
            logging.INFO,
            "rollback_skipped",
            "Rollback skipped rows",
            run_id=run_id,
            skipped_missing_src=stats.skipped_missing_src,
            skipped_existing_dst=stats.skipped_existing_dst,
            skipped_invalid=stats.skipped_invalid,
        )

    elapsed = round(time.monotonic() - start_ts, 3)
    log_event(
        logger,
        logging.INFO,
        "run_end",
        "Rollback run end",
        run_id=run_id,
        duration_s=elapsed,
        restored=stats.restored,
        failed=stats.failed,
        skipped_missing_src=stats.skipped_missing_src,
        skipped_existing_dst=stats.skipped_existing_dst,
        skipped_invalid=stats.skipped_invalid,
    )
