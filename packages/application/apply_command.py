# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import time
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any, Dict, List, TextIO

from packages.application import apply_command_helpers as _apply_helpers
from packages.application import apply_safety_helpers as _apply_safety
from packages.application.apply_manifest_processor import (
    ApplyProcessingState,
    ApplyRuntime,
    process_manifest_rows,
    resolve_apply_path_policy,
)
from packages.application.reporting import Summary, write_report
from packages.application.rollback_command import cmd_rollback as _cmd_rollback
from packages.domain import rollback_integrity as _rollback_integrity
from packages.domain.core_utils import new_run_id, sha1_file
from packages.domain.error_utils import clear_error, ensure_status, set_error, set_status
from packages.domain.normalization import safe_join, unique_path
from packages.domain.pipeline_config import (
    APP_VERSION,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DURABILITY,
    DEFAULT_LOG_JSON,
    DEFAULT_LOG_LEVEL,
    KEY_APPLIED_AT,
    KEY_ERROR,
    KEY_ERROR_CODE,
    KEY_MEDIA_TYPE,
    KEY_NEW_PATH,
    KEY_PATH,
    KEY_RUN_ID,
    KEY_SCHEMA_VERSION,
    KEY_SHA1,
    KEY_STATUS,
    MANIFEST_SCHEMA_VERSION,
    ErrorCode,
    RowStatus,
    resolve_fsync_interval,
)
from packages.infrastructure.manifest_store import (
    attach_manifest_metadata,
    iter_jsonl_chunks,
    open_jsonl_writer,
    read_jsonl,
    write_jsonl_line,
)
from packages.observability.logging_utils import log_event, setup_logger

_CRASH_POINTS = {
    "after_move_before_manifest_commit",
    "after_manifest_before_rollback_commit",
    "after_rollback_before_finalize",
}

# Backward-compatible re-exports for existing tests/imports.
_is_within_root = _apply_safety._is_within_root
_safe_move_with_verification = _apply_safety._safe_move_with_verification
_is_filesystem_root = _apply_safety._is_filesystem_root
_next_overwrite_backup_path = _apply_safety._next_overwrite_backup_path
_preserve_crash_file = _apply_safety._preserve_crash_file
_is_valid_jsonl_file = _apply_safety._is_valid_jsonl_file
_resolve_if_exists = _apply_safety._resolve_if_exists
shutil = _apply_safety.shutil

_ROLLBACK_SIG_KEY = _rollback_integrity.ROLLBACK_SIG_KEY
_build_rollback_from_manifest = _rollback_integrity._build_rollback_from_manifest
_normalize_run_id = _rollback_integrity._normalize_run_id
_has_strong_rollback_signing_key = _rollback_integrity._has_strong_rollback_signing_key
_sign_rollback_record = _rollback_integrity._sign_rollback_record
_verify_rollback_record = _rollback_integrity._verify_rollback_record


def _is_test_hooks_enabled() -> bool:
    return os.environ.get("FILEORGANIZE_ENABLE_TEST_HOOKS", "") == "1" or bool(os.environ.get("PYTEST_CURRENT_TEST", ""))


def _resolve_apply_crash_inject(args) -> str:
    return _apply_helpers.resolve_apply_crash_inject(
        args,
        crash_points=_CRASH_POINTS,
        is_test_hooks_enabled_fn=_is_test_hooks_enabled,
    )


def _maybe_inject_crash(crash_point: str, expected: str) -> None:
    _apply_helpers.maybe_inject_crash(crash_point, expected)


def _write_apply_wal(
    wal_path: Path,
    *,
    phase: str,
    run_id: str,
    out_manifest: Path,
    partial_manifest: Path,
    rollback_manifest: Path | None,
    rollback_partial: Path | None,
    moves: int,
) -> None:
    _apply_helpers.write_apply_wal(
        wal_path,
        phase=phase,
        run_id=run_id,
        out_manifest=out_manifest,
        partial_manifest=partial_manifest,
        rollback_manifest=rollback_manifest,
        rollback_partial=rollback_partial,
        moves=moves,
    )


build_destination = _apply_helpers.build_destination


def cmd_apply(args: argparse.Namespace) -> None:
    logger = setup_logger(getattr(args, "log_level", DEFAULT_LOG_LEVEL), getattr(args, "log_json", DEFAULT_LOG_JSON))
    start_ts = time.monotonic()
    run_id = getattr(args, "run_id", "") or new_run_id("apply")
    try:
        run_id = _normalize_run_id(run_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    generator_version = getattr(args, "generator_version", "") or APP_VERSION
    manifest_path = Path(args.manifest).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()
    out_manifest = Path(args.out_manifest).expanduser().resolve() if args.out_manifest else manifest_path
    partial_manifest = Path(str(out_manifest) + ".partial")
    wal_marker = Path(str(out_manifest) + ".apply.wal.json")
    crash_inject = _resolve_apply_crash_inject(args)

    rollback_manifest = None
    rollback_partial = None
    if not getattr(args, "dry_run", False):
        raw_rollback = getattr(args, "rollback_manifest", "")
        rollback_manifest = Path(raw_rollback).expanduser().resolve() if raw_rollback else Path(str(out_manifest) + ".rollback.jsonl")
        rollback_partial = Path(str(rollback_manifest) + ".partial")

    _apply_helpers.recover_apply_wal(
        wal_marker=wal_marker,
        partial_manifest=partial_manifest,
        rollback_partial=rollback_partial,
        rollback_manifest=rollback_manifest,
        out_manifest=out_manifest,
        logger=logger,
        run_id=run_id,
        generator_version=generator_version,
        read_jsonl_fn=lambda path, validate=True: list(read_jsonl(path, validate=validate)),
        build_rollback_from_manifest_fn=_build_rollback_from_manifest,
        open_jsonl_writer_fn=open_jsonl_writer,
        attach_manifest_metadata_fn=attach_manifest_metadata,
        write_jsonl_line_fn=write_jsonl_line,
        sign_rollback_record_fn=_sign_rollback_record,
        rollback_sig_key=_ROLLBACK_SIG_KEY,
        schema_version=MANIFEST_SCHEMA_VERSION,
        is_valid_jsonl_file_fn=_is_valid_jsonl_file,
        preserve_crash_file_fn=_preserve_crash_file,
        log_event_fn=log_event,
    )

    chunk_size = int(getattr(args, "chunk_size", DEFAULT_CHUNK_SIZE) or DEFAULT_CHUNK_SIZE)
    if chunk_size <= 0:
        chunk_size = DEFAULT_CHUNK_SIZE

    log_event(
        logger,
        logging.INFO,
        "run_start",
        "Apply run start",
        run_id=run_id,
        manifest=str(manifest_path),
        output=str(output_root),
        out_manifest=str(out_manifest),
        rollback_manifest=str(rollback_manifest) if rollback_manifest else "",
        dry_run=bool(getattr(args, "dry_run", False)),
        chunk_size=chunk_size,
    )

    def _fail(code: ErrorCode, event: str, message: str, **fields: Any) -> None:
        _apply_helpers.fail_apply_run(
            logger=logger,
            start_ts=start_ts,
            run_id=run_id,
            code=code,
            event=event,
            message=message,
            partial_manifest=partial_manifest,
            rollback_partial=rollback_partial,
            preserve_crash_file_fn=_preserve_crash_file,
            log_event_fn=log_event,
            fields=fields,
        )

    resume = bool(getattr(args, "resume", True))

    versions: List[int] = []
    seen_sha1: Dict[str, Path] = {}
    try:
        version_set = set()
        for chunk in iter_jsonl_chunks(manifest_path, validate=True, chunk_size=chunk_size):
            for row in chunk:
                val = row.get(KEY_SCHEMA_VERSION)
                if isinstance(val, int):
                    version_set.add(val)
                elif isinstance(val, str) and val.isdigit():
                    version_set.add(int(val))
                if resume:
                    sha1 = str(row.get(KEY_SHA1, "") or "")
                    new_path = str(row.get(KEY_NEW_PATH, "") or "")
                    status = str(row.get(KEY_STATUS, "") or "")
                    if not sha1 or not new_path:
                        continue
                    dst_path = Path(new_path)
                    if not dst_path.exists():
                        continue
                    if not status or status in {RowStatus.APPLIED.value, RowStatus.DUPLICATE.value}:
                        seen_sha1[sha1] = dst_path
        versions = sorted(version_set)
    except Exception as exc:
        _fail(
            ErrorCode.MANIFEST_READ_FAIL,
            "manifest_read_fail",
            f"Failed to read manifest: {exc}",
            path=str(manifest_path),
        )

    if versions:
        if max(versions) > MANIFEST_SCHEMA_VERSION:
            log_event(
                logger,
                logging.WARNING,
                "schema_newer",
                "Manifest schema_version is newer than the current version; upgrade the tool before running again",
                versions=versions,
                run_id=run_id,
            )
        if min(versions) < MANIFEST_SCHEMA_VERSION:
            _fail(
                ErrorCode.MANIFEST_ROW_INVALID,
                "schema_older",
                (
                    "Manifest schema_version is older than the current version; "
                    "compatibility mode is not supported. Upgrade the manifest first"
                ),
                versions=versions,
                current_schema_version=MANIFEST_SCHEMA_VERSION,
            )

    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _fail(
            ErrorCode.OUTPUT_CREATE_FAIL,
            "output_create_fail",
            f"Failed to create output directory: {exc}",
            path=str(output_root),
        )

    categories = args.categories
    path_policy = resolve_apply_path_policy(
        args,
        fail_fn=_fail,
        is_filesystem_root_fn=_is_filesystem_root,
    )

    fsync_interval = resolve_fsync_interval(getattr(args, "durability", DEFAULT_DURABILITY), getattr(args, "fsync_interval", 0))
    if fsync_interval < 0:
        fsync_interval = 0

    report_path = Path(args.report).expanduser().resolve() if getattr(args, "report", "") else None

    moves = 0
    lines_written = 0
    rollback_written = 0
    summary = Summary()

    try:
        rollback_cm: AbstractContextManager[TextIO | None]
        if rollback_partial:
            try:
                rollback_cm = open_jsonl_writer(rollback_partial)
            except Exception as exc:
                _fail(
                    ErrorCode.ROLLBACK_FAIL,
                    "rollback_manifest_open_fail",
                    f"Failed to open rollback manifest: {exc}",
                    path=str(rollback_partial),
                )
        else:
            rollback_cm = nullcontext(None)
        with open_jsonl_writer(partial_manifest) as fh, rollback_cm as rollback_fh:
            _write_apply_wal(
                wal_marker,
                phase="fileorganizeng",
                run_id=run_id,
                out_manifest=out_manifest,
                partial_manifest=partial_manifest,
                rollback_manifest=rollback_manifest,
                rollback_partial=rollback_partial,
                moves=0,
            )

            def _emit_row(item: Dict[str, Any]) -> None:
                nonlocal lines_written
                # Apply outputs must bind to the current apply run_id to avoid reusing analyze run_id.
                item[KEY_RUN_ID] = run_id
                attach_manifest_metadata(
                    item,
                    run_id=run_id,
                    generator_version=generator_version,
                    schema_version=MANIFEST_SCHEMA_VERSION,
                )
                status_val = str(item.get(KEY_STATUS, "") or "")
                if status_val in {RowStatus.APPLIED.value, RowStatus.DUPLICATE.value}:
                    item[_ROLLBACK_SIG_KEY] = _sign_rollback_record(item, run_id)
                err_msg = item.get(KEY_ERROR, "") or ""
                err_code = item.get(KEY_ERROR_CODE, "") or ""
                if err_msg or err_code:
                    err_exc = RuntimeError(err_msg or f"apply error ({err_code})")
                    log_event(
                        logger,
                        logging.ERROR,
                        "apply_error",
                        err_msg or "apply error",
                        path=str(item.get(KEY_PATH, "")),
                        error_code=err_code,
                        exception=err_exc,
                    )
                lines_written += 1
                write_jsonl_line(
                    fh,
                    item,
                    fsync=fsync_interval > 0 and lines_written % fsync_interval == 0,
                )
                summary.update(item)

            def _emit_rollback(src_path: Path, dst_path: Path, status: RowStatus, media_type: str) -> None:
                nonlocal rollback_written
                if rollback_fh is None or rollback_manifest is None:
                    return
                record = {
                    KEY_PATH: str(src_path),
                    KEY_NEW_PATH: str(dst_path),
                    KEY_MEDIA_TYPE: media_type,
                    KEY_STATUS: status.value,
                    KEY_APPLIED_AT: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
                }
                attach_manifest_metadata(
                    record,
                    run_id=run_id,
                    generator_version=generator_version,
                    schema_version=MANIFEST_SCHEMA_VERSION,
                )
                record[_ROLLBACK_SIG_KEY] = _sign_rollback_record(record, run_id)
                rollback_written += 1
                try:
                    write_jsonl_line(
                        rollback_fh,
                        record,
                        fsync=fsync_interval > 0 and rollback_written % fsync_interval == 0,
                    )
                except Exception as exc:
                    _fail(
                        ErrorCode.ROLLBACK_FAIL,
                        "rollback_manifest_write_fail",
                        f"Failed to write rollback manifest: {exc}",
                        path=str(rollback_manifest),
                    )

            processing_state = ApplyProcessingState(seen_sha1=seen_sha1, moves=moves)
            process_manifest_rows(
                manifest_path,
                chunk_size=chunk_size,
                runtime=ApplyRuntime(
                    args=args,
                    logger=logger,
                    output_root=output_root,
                    categories=categories,
                    path_policy=path_policy,
                ),
                state=processing_state,
                emit_row=_emit_row,
                emit_rollback=_emit_rollback,
                deps={
                    "iter_jsonl_chunks": iter_jsonl_chunks,
                    "ensure_status": ensure_status,
                    "clear_error": clear_error,
                    "set_error": set_error,
                    "set_status": set_status,
                    "resolve_if_exists": _resolve_if_exists,
                    "is_within_root": _is_within_root,
                    "is_filesystem_root": _is_filesystem_root,
                    "sha1_file": sha1_file,
                    "safe_join": safe_join,
                    "unique_path": unique_path,
                    "safe_move_with_verification": _safe_move_with_verification,
                    "build_destination": build_destination,
                    "log_event": log_event,
                },
            )
            seen_sha1 = processing_state.seen_sha1
            moves = processing_state.moves

            if fsync_interval > 0 and lines_written % fsync_interval != 0:
                fh.flush()
                os.fsync(fh.fileno())
            if rollback_fh is not None and fsync_interval > 0 and rollback_written % fsync_interval != 0:
                rollback_fh.flush()
                os.fsync(rollback_fh.fileno())
    except Exception as exc:
        _fail(
            ErrorCode.MANIFEST_WRITE_FAIL,
            "manifest_write_fail",
            f"Failed to write updated manifest: {exc}",
            path=str(out_manifest),
        )

    _write_apply_wal(
        wal_marker,
        phase="pre_manifest_commit",
        run_id=run_id,
        out_manifest=out_manifest,
        partial_manifest=partial_manifest,
        rollback_manifest=rollback_manifest,
        rollback_partial=rollback_partial,
        moves=moves,
    )
    _maybe_inject_crash(crash_inject, "after_move_before_manifest_commit")
    try:
        partial_manifest.replace(out_manifest)
    except Exception as exc:
        _fail(
            ErrorCode.MANIFEST_UPDATE_FAIL,
            "manifest_update_fail",
            f"Failed to update manifest: {exc}",
            path=str(out_manifest),
        )
    _write_apply_wal(
        wal_marker,
        phase="manifest_committed",
        run_id=run_id,
        out_manifest=out_manifest,
        partial_manifest=partial_manifest,
        rollback_manifest=rollback_manifest,
        rollback_partial=rollback_partial,
        moves=moves,
    )
    _maybe_inject_crash(crash_inject, "after_manifest_before_rollback_commit")

    log_event(
        logger,
        logging.INFO,
        "manifest_updated",
        "Updated manifest",
        path=str(out_manifest),
        run_id=run_id,
    )

    if rollback_partial is not None and rollback_manifest is not None:
        try:
            rollback_partial.replace(rollback_manifest)
        except Exception as exc:
            _fail(
                ErrorCode.ROLLBACK_FAIL,
                "rollback_manifest_update_fail",
                f"Failed to update rollback manifest: {exc}",
                path=str(rollback_manifest),
            )
        _write_apply_wal(
            wal_marker,
            phase="rollback_committed",
            run_id=run_id,
            out_manifest=out_manifest,
            partial_manifest=partial_manifest,
            rollback_manifest=rollback_manifest,
            rollback_partial=rollback_partial,
            moves=moves,
        )
        _maybe_inject_crash(crash_inject, "after_rollback_before_finalize")
        log_event(
            logger,
            logging.INFO,
            "rollback_manifest_written",
            "Wrote rollback manifest",
            path=str(rollback_manifest),
            run_id=run_id,
        )
    if not args.dry_run:
        log_event(logger, logging.INFO, "moved_files", "Moved files", count=moves, run_id=run_id)

    if report_path:
        try:
            write_report(report_path, summary)
        except Exception as exc:
            _fail(
                ErrorCode.REPORT_WRITE_FAIL,
                "report_write_fail",
                f"Failed to write report: {exc}",
                path=str(report_path),
            )
        log_event(
            logger,
            logging.INFO,
            "report_written",
            "Wrote report",
            path=str(report_path),
            run_id=run_id,
        )

    elapsed = round(time.monotonic() - start_ts, 3)
    wal_marker.unlink(missing_ok=True)
    log_event(
        logger,
        logging.INFO,
        "run_end",
        "Apply run end",
        run_id=run_id,
        duration_s=elapsed,
        total=summary.total,
        with_error=summary.with_error,
        error_codes=dict(summary.error_codes),
        moves=moves,
        rollback_written=rollback_written,
    )


def cmd_rollback(args: argparse.Namespace) -> None:
    _cmd_rollback(args)
