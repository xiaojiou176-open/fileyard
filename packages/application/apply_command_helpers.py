# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Sequence, Tuple

from packages.domain.normalization import (
    choose_timestamp,
    normalize_category,
    normalize_kind,
    safe_join,
    slugify,
)
from packages.domain.pipeline_config import (
    AI_CATEGORY,
    AI_KIND,
    AI_TITLE,
    KEY_HASH8,
    KEY_MEDIA_TYPE,
    KEY_PATH,
    MANIFEST_SCHEMA_VERSION,
    MAX_FILENAME_LENGTH,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_DOCX,
    MEDIA_PDF,
    MEDIA_PPT,
    MEDIA_PPTX,
    ErrorCode,
    ImageKind,
)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    partial = Path(str(path) + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    partial.replace(path)


def resolve_apply_crash_inject(
    args: Any,
    *,
    crash_points: set[str],
    is_test_hooks_enabled_fn: Callable[[], bool],
) -> str:
    test_mode = is_test_hooks_enabled_fn()
    raw = str(getattr(args, "crash_inject", "") or os.environ.get("FILEYARD_APPLY_CRASH_AT", "")).strip()
    crash = raw.lower().replace("-", "_")
    if not crash:
        return ""
    if not test_mode:
        raise SystemExit("crash_inject is available only in test mode")
    if crash not in crash_points:
        raise SystemExit(f"Unknown crash_inject: {crash}")
    return crash


def maybe_inject_crash(crash_point: str, expected: str) -> None:
    if crash_point != expected:
        return
    raise RuntimeError(f"Crash injected at {expected}")


def write_apply_wal(
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
    wal_payload = {
        "phase": phase,
        "run_id": run_id,
        "out_manifest": str(out_manifest),
        "partial_manifest": str(partial_manifest),
        "rollback_manifest": str(rollback_manifest) if rollback_manifest else "",
        "rollback_partial": str(rollback_partial) if rollback_partial else "",
        "moves": int(moves),
        "updated_at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
    }
    _atomic_write_json(wal_path, wal_payload)


def build_destination(
    row: Dict[str, Any],
    output_root: Path,
    categories: Sequence[str],
) -> Tuple[Path, str]:
    ai = row.get("ai", {}) or {}
    kind = normalize_kind(str(ai.get(AI_KIND, "")))
    category = normalize_category(str(ai.get(AI_CATEGORY, "")), categories)
    title = slugify(str(ai.get(AI_TITLE, "")))
    ts = choose_timestamp(row)
    media_type = row.get(KEY_MEDIA_TYPE, "")

    ext = Path(row[KEY_PATH]).suffix.lower() or ".jpg"
    if ext == ".jpeg":
        ext = ".jpg"

    filename = f"{ts:%Y%m%d_%H%M%S}__{kind}__{category}__{title}__{row.get(KEY_HASH8, '')}{ext}"
    if len(filename) > MAX_FILENAME_LENGTH:
        keep = max(1, MAX_FILENAME_LENGTH - len(ext))
        filename = f"{filename[:keep]}{ext}"
    if media_type == MEDIA_AUDIO or kind == ImageKind.AUDIO.value:
        folder = safe_join(output_root, "音频", category)
    elif media_type in {MEDIA_PDF, MEDIA_DOCX, MEDIA_DOC, MEDIA_PPTX, MEDIA_PPT} or kind == ImageKind.DOCUMENT.value:
        folder = safe_join(output_root, "文档", category)
    else:
        folder = safe_join(output_root, kind, category)
    return folder, filename


def recover_apply_wal(
    *,
    wal_marker: Path,
    partial_manifest: Path,
    rollback_partial: Path | None,
    rollback_manifest: Path | None,
    out_manifest: Path,
    logger: logging.Logger,
    run_id: str,
    generator_version: str,
    read_jsonl_fn: Callable[..., list[dict[str, Any]]],
    build_rollback_from_manifest_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    open_jsonl_writer_fn: Callable[[Path], Any],
    attach_manifest_metadata_fn: Callable[..., None],
    write_jsonl_line_fn: Callable[..., None],
    sign_rollback_record_fn: Callable[[dict[str, Any], str], str],
    rollback_sig_key: str,
    schema_version: int = MANIFEST_SCHEMA_VERSION,
    is_valid_jsonl_file_fn: Callable[[Path], bool] | None = None,
    preserve_crash_file_fn: Callable[[Path], Path] | None = None,
    log_event_fn: Callable[..., None] | None = None,
) -> None:
    if not wal_marker.exists():
        return
    is_valid_jsonl_file = is_valid_jsonl_file_fn
    preserve_crash_file = preserve_crash_file_fn
    log_event = log_event_fn
    if is_valid_jsonl_file is None or preserve_crash_file is None or log_event is None:
        raise ValueError("recover_apply_wal is missing a required callback")

    try:
        wal_payload = json.loads(wal_marker.read_text(encoding="utf-8"))
    except Exception as exc:
        wal_payload = {}
        log_event(
            logger,
            logging.WARNING,
            "apply_wal_parse_fail",
            "WAL file parsing failed; recovering with an empty state",
            path=str(wal_marker),
            error=str(exc),
            run_id=run_id,
        )
    wal_phase = str(wal_payload.get("phase", "") or "")
    recovered_manifest = False
    recovered_rollback = False
    try:
        if partial_manifest.exists():
            if wal_phase == "pre_manifest_commit" and is_valid_jsonl_file(partial_manifest):
                partial_manifest.replace(out_manifest)
                recovered_manifest = True
            else:
                preserved = preserve_crash_file(partial_manifest)
                log_event(
                    logger,
                    logging.WARNING,
                    "apply_wal_manifest_partial_ignored",
                    "Ignoring unsafe partial manifest and preserving crash evidence",
                    wal_phase=wal_phase,
                    path=str(preserved),
                    run_id=run_id,
                )
        if rollback_partial is not None and rollback_manifest is not None:
            if rollback_partial.exists():
                if wal_phase in {"pre_manifest_commit", "manifest_committed"} and is_valid_jsonl_file(rollback_partial):
                    rollback_partial.replace(rollback_manifest)
                    recovered_rollback = True
                else:
                    preserved = preserve_crash_file(rollback_partial)
                    log_event(
                        logger,
                        logging.WARNING,
                        "apply_wal_rollback_partial_ignored",
                        "Ignoring unsafe partial rollback and preserving crash evidence",
                        wal_phase=wal_phase,
                        path=str(preserved),
                        run_id=run_id,
                    )
            elif not rollback_manifest.exists() and out_manifest.exists() and wal_phase == "manifest_committed":
                rows = read_jsonl_fn(out_manifest, validate=True)
                rebuilt_rows = build_rollback_from_manifest_fn(rows)
                with open_jsonl_writer_fn(rollback_manifest) as rollback_fh:
                    for item in rebuilt_rows:
                        attach_manifest_metadata_fn(
                            item,
                            run_id=run_id,
                            generator_version=generator_version,
                            schema_version=schema_version,
                        )
                        item[rollback_sig_key] = sign_rollback_record_fn(item, run_id)
                        write_jsonl_line_fn(rollback_fh, item, fsync=False)
                recovered_rollback = True
        wal_marker.unlink(missing_ok=True)
        log_event(
            logger,
            logging.WARNING,
            "apply_wal_recovered",
            "Detected interrupted apply run and recovered manifests",
            wal_phase=wal_phase,
            recovered_manifest=recovered_manifest,
            recovered_rollback=recovered_rollback,
            run_id=run_id,
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "apply_wal_recovery_fail",
            f"WAL recovery failed: {exc}",
            error_code=ErrorCode.MANIFEST_UPDATE_FAIL.value,
            wal_phase=wal_phase,
            path=str(wal_marker),
            run_id=run_id,
        )
        raise SystemExit(f"WAL recovery failed: {exc}")


def fail_apply_run(
    *,
    logger: logging.Logger,
    start_ts: float,
    run_id: str,
    code: ErrorCode,
    event: str,
    message: str,
    partial_manifest: Path,
    rollback_partial: Path | None,
    preserve_crash_file_fn: Callable[[Path], Path],
    log_event_fn: Callable[..., None],
    fields: Dict[str, Any] | None = None,
) -> None:
    fields = fields or {}
    elapsed = round(time.monotonic() - start_ts, 3)
    log_event = log_event_fn
    if partial_manifest.exists():
        try:
            crash_path = preserve_crash_file_fn(partial_manifest)
            log_event(
                logger,
                logging.ERROR,
                "manifest_crash_preserved",
                "Preserved crash manifest",
                path=str(crash_path),
                run_id=run_id,
                error_type="ApplyFailure",
                error_code=code.value,
                error_message=message,
                error_retryable=False,
                error_cause="crash_manifest_preserved",
                error_stack="",
            )
        except Exception as preserve_exc:
            log_event(
                logger,
                logging.WARNING,
                "manifest_crash_preserve_fail",
                f"Failed to preserve crash manifest: {preserve_exc}",
                path=str(partial_manifest),
                run_id=run_id,
            )
    if rollback_partial is not None and rollback_partial.exists():
        try:
            crash_path = preserve_crash_file_fn(rollback_partial)
            log_event(
                logger,
                logging.ERROR,
                "rollback_crash_preserved",
                "Preserved crash rollback",
                path=str(crash_path),
                run_id=run_id,
                error_type="ApplyFailure",
                error_code=code.value,
                error_message=message,
                error_retryable=False,
                error_cause="crash_rollback_preserved",
                error_stack="",
            )
        except Exception as preserve_exc:
            log_event(
                logger,
                logging.WARNING,
                "rollback_crash_preserve_fail",
                f"Failed to preserve crash rollback: {preserve_exc}",
                path=str(rollback_partial),
                run_id=run_id,
            )
    log_event(
        logger,
        logging.ERROR,
        event,
        message,
        error_code=code.value,
        run_id=run_id,
        **fields,
    )
    log_event(
        logger,
        logging.ERROR,
        "run_failed",
        "Apply run failed",
        run_id=run_id,
        duration_s=elapsed,
        error_code=code.value,
    )
    raise SystemExit(message)
