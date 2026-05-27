# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from packages.application.analyze_media_command import run_analyze_command
from packages.application.analyze_media_helpers import (
    AnalyzeContext,
    _build_offline_ai,
    _coerce_confidence,
    _file_size_mb,
    _is_timeout_error,
    _normalize_ai_kind_for_media_type,
    _queue_failed_upload,
    build_base_row,
    sanitize_ai,
)
from packages.application.analyze_media_hotspot import (
    handle_audio_row,
    handle_document_row,
    handle_offline_row,
    handle_visual_row,
)
from packages.application.reporting import Summary, write_report
from packages.domain.core_utils import new_run_id, truncate_text
from packages.domain.error_utils import ensure_status, set_error
from packages.domain.normalization import (
    normalize_categories,
)
from packages.domain.pipeline_config import (
    AI_CATEGORY,
    AI_KIND,
    AI_TITLE,
    APP_VERSION,
    DEFAULT_AI_TIMEOUT_S,
    DEFAULT_CATEGORIES,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DURABILITY,
    DEFAULT_LOG_JSON,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_FILE_MB,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_MB,
    DEFAULT_SUBPROCESS_TIMEOUT_S,
    DEFAULT_WORKERS,
    KEY_AI,
    KEY_ERROR,
    KEY_ERROR_CODE,
    KEY_INPUT_ROOT,
    KEY_MEDIA_TYPE,
    KEY_PATH,
    MANIFEST_SCHEMA_VERSION,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_DOCX,
    MEDIA_PDF,
    MEDIA_PPT,
    MEDIA_PPTX,
    ErrorCode,
    resolve_fsync_interval,
)
from packages.domain.prompt_templates import (
    build_audio_classify_prompt,
    build_audio_transcribe_prompt,
    build_prompt,
)
from packages.infrastructure.audio_processing import (
    extract_audio_fields,
    extract_audio_segments,
    extract_transcript_payload,
    merge_transcript_segments,
    plan_audio_segments,
    prepare_audio_part,
)
from packages.infrastructure.document_conversion import convert_to_pdf
from packages.infrastructure.gemini_client import (
    build_client,
    build_file_part,
    call_gemini_text_with_retry,
    call_gemini_with_retry,
    safe_delete_file,
)
from packages.infrastructure.image_processing import extract_exif_fields, prepare_image_part
from packages.infrastructure.manifest_store import (
    attach_manifest_metadata,
    open_jsonl_writer,
    write_csv_from_manifest,
    write_jsonl_line,
)
from packages.infrastructure.media_scanner import (
    count_media_files,
    detect_media_type,
    guess_mime,
    iter_media_files,
    scan_media_stats,
)
from packages.observability.logging_utils import log_event, setup_logger

# -----------------------------
# Analyze worker
# -----------------------------


def _analyze_one(path: Path, ctx: AnalyzeContext, get_client) -> Dict[str, Any]:
    row: Dict[str, Any] = {KEY_PATH: str(path), KEY_MEDIA_TYPE: ""}
    if not path.exists():
        set_error(row, ErrorCode.SOURCE_MOVED, "源文件在处理过程中消失")
        return row
    try:
        row.update(build_base_row(path))
    except Exception as exc:
        set_error(row, ErrorCode.HASH_FAIL, f"哈希/属性错误: {exc}")
        return row

    row[KEY_INPUT_ROOT] = str(ctx.input_dir)
    ensure_status(row)

    if ctx.max_file_mb > 0:
        try:
            size_mb = _file_size_mb(path)
        except Exception as exc:
            set_error(row, ErrorCode.FILE_STAT_FAIL, f"读取文件大小失败: {exc}")
            return row
        if size_mb > ctx.max_file_mb:
            set_error(
                row,
                ErrorCode.FILE_TOO_LARGE,
                f"文件超过上限({ctx.max_file_mb}MB): {size_mb:.2f}MB",
            )
            return row

    media_type = detect_media_type(path)
    row[KEY_MEDIA_TYPE] = media_type or ""

    hooks = {
        "build_offline_ai": _build_offline_ai,
        "coerce_confidence": _coerce_confidence,
        "is_timeout_error": _is_timeout_error,
        "queue_failed_upload": _queue_failed_upload,
        "normalize_ai_kind_for_media_type": _normalize_ai_kind_for_media_type,
        "sanitize_ai": sanitize_ai,
        "build_audio_classify_prompt": build_audio_classify_prompt,
        "truncate_text": truncate_text,
        "set_error": set_error,
        "log_event": log_event,
        "extract_audio_fields": extract_audio_fields,
        "extract_audio_segments": extract_audio_segments,
        "extract_transcript_payload": extract_transcript_payload,
        "merge_transcript_segments": merge_transcript_segments,
        "plan_audio_segments": plan_audio_segments,
        "prepare_audio_part": prepare_audio_part,
        "convert_to_pdf": convert_to_pdf,
        "build_file_part": build_file_part,
        "call_gemini_text_with_retry": call_gemini_text_with_retry,
        "call_gemini_with_retry": call_gemini_with_retry,
        "safe_delete_file": safe_delete_file,
        "extract_exif_fields": extract_exif_fields,
        "prepare_image_part": prepare_image_part,
        "guess_mime": guess_mime,
    }

    if ctx.offline:
        handle_offline_row(path, row, ctx, media_type, hooks)
        return row

    client = get_client()
    if media_type == MEDIA_AUDIO:
        handle_audio_row(path, row, ctx, client, hooks)
    elif media_type in {MEDIA_PDF, MEDIA_DOCX, MEDIA_DOC, MEDIA_PPTX, MEDIA_PPT}:
        handle_document_row(path, row, ctx, client, media_type, hooks)
    else:
        handle_visual_row(path, row, ctx, client, media_type, hooks)

    _normalize_ai_kind_for_media_type(row, media_type, path)
    if ctx.sleep_s > 0:
        time.sleep(ctx.sleep_s)
    return row


def _build_cmd_hooks() -> Dict[str, Any]:
    return {
        "setup_logger": setup_logger,
        "DEFAULT_LOG_LEVEL": DEFAULT_LOG_LEVEL,
        "DEFAULT_LOG_JSON": DEFAULT_LOG_JSON,
        "new_run_id": new_run_id,
        "DEFAULT_CHUNK_SIZE": DEFAULT_CHUNK_SIZE,
        "log_event": log_event,
        "ErrorCode": ErrorCode,
        "normalize_categories": normalize_categories,
        "DEFAULT_CATEGORIES": DEFAULT_CATEGORIES,
        "build_prompt": build_prompt,
        "build_audio_transcribe_prompt": build_audio_transcribe_prompt,
        "resolve_fsync_interval": resolve_fsync_interval,
        "DEFAULT_DURABILITY": DEFAULT_DURABILITY,
        "Summary": Summary,
        "DEFAULT_MAX_FILE_MB": DEFAULT_MAX_FILE_MB,
        "DEFAULT_MAX_FILES": DEFAULT_MAX_FILES,
        "DEFAULT_MAX_TOTAL_MB": DEFAULT_MAX_TOTAL_MB,
        "DEFAULT_WORKERS": DEFAULT_WORKERS,
        "DEFAULT_AI_TIMEOUT_S": DEFAULT_AI_TIMEOUT_S,
        "DEFAULT_SUBPROCESS_TIMEOUT_S": DEFAULT_SUBPROCESS_TIMEOUT_S,
        "scan_media_stats": scan_media_stats,
        "count_media_files": count_media_files,
        "build_client": build_client,
        "AnalyzeContext": AnalyzeContext,
        "APP_VERSION": APP_VERSION,
        "MANIFEST_SCHEMA_VERSION": MANIFEST_SCHEMA_VERSION,
        "iter_media_files": iter_media_files,
        "_analyze_one": _analyze_one,
        "open_jsonl_writer": open_jsonl_writer,
        "attach_manifest_metadata": attach_manifest_metadata,
        "write_jsonl_line": write_jsonl_line,
        "write_csv_from_manifest": write_csv_from_manifest,
        "write_report": write_report,
        "_retry_cleanup_queue": _retry_cleanup_queue,
        "KEY_ERROR": KEY_ERROR,
        "KEY_ERROR_CODE": KEY_ERROR_CODE,
        "KEY_PATH": KEY_PATH,
        "KEY_AI": KEY_AI,
        "AI_KIND": AI_KIND,
        "AI_CATEGORY": AI_CATEGORY,
        "AI_TITLE": AI_TITLE,
        "os": os,
        "threading": threading,
    }


def cmd_analyze(args: argparse.Namespace) -> None:
    run_analyze_command(args, hooks=_build_cmd_hooks())


def _cleanup_orphaned_queues(
    queue_root: Path,
    max_age_hours: float = 24,
    *,
    logger: logging.Logger | None = None,
    run_id: str = "",
) -> None:
    """Clean up cleanup queue files older than max_age_hours.

    Prevents infinite accumulation of orphaned cleanup queues when
    analyze operations are interrupted or fail to complete cleanup.

    Args:
        max_age_hours: Maximum age in hours before a queue is considered orphaned
    """
    try:
        queue_root = queue_root.resolve()
        if not queue_root.exists():
            return

        current_timestamp = time.time()
        for queue_file in queue_root.rglob("*.cleanup_uploads.jsonl"):
            try:
                # Guard cleanup to queue_root scope only.
                scoped_queue_file = queue_file.absolute()
                scoped_queue_file.relative_to(queue_root)
                if not (scoped_queue_file.exists() or scoped_queue_file.is_symlink()):
                    continue
                if scoped_queue_file.is_dir():
                    continue
                file_age = current_timestamp - scoped_queue_file.stat(follow_symlinks=False).st_mtime
                if file_age > (max_age_hours * 3600):
                    # Delete queue entry itself. Never unlink resolved target.
                    scoped_queue_file.unlink(missing_ok=True)
            except Exception as exc:
                if logger:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "cleanup_orphan_queue_fail",
                        "Failed to clean expired queue file; skipping",
                        run_id=run_id,
                        path=str(queue_file),
                        error=str(exc),
                    )
    except Exception as exc:
        if logger:
            log_event(
                logger,
                logging.WARNING,
                "cleanup_orphan_scan_fail",
                "Failed to scan expired queue files; skipping",
                run_id=run_id,
                path=str(queue_root),
                error=str(exc),
            )


def _retry_cleanup_queue(
    *,
    cleanup_queue_path: Path,
    offline: bool,
    get_client,
    logger: logging.Logger,
    timeout_s: float,
    run_id: str,
) -> tuple[int, int]:
    cleanup_pending = 0
    cleanup_recovered = 0

    # Always scan orphaned queues to avoid unbounded accumulation from
    # interrupted/offline runs.
    _cleanup_orphaned_queues(cleanup_queue_path.parent, logger=logger, run_id=run_id)
    if not cleanup_queue_path.exists() or offline:
        return cleanup_pending, cleanup_recovered

    try:
        pending_names: List[str] = []
        invalid_json_lines = 0
        with cleanup_queue_path.open("r", encoding="utf-8") as queue_fh:
            for line_no, line in enumerate(queue_fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception as exc:
                    invalid_json_lines += 1
                    if invalid_json_lines == 1:
                        log_event(
                            logger,
                            logging.DEBUG,
                            "cleanup_queue_invalid_line",
                            "Cleanup queue contains an invalid JSON line; skipping",
                            run_id=run_id,
                            path=str(cleanup_queue_path),
                            line_no=line_no,
                            error=str(exc),
                        )
                    continue
                name = str(payload.get("name", "") or "").strip()
                if name:
                    pending_names.append(name)
        if invalid_json_lines > 1:
            log_event(
                logger,
                logging.DEBUG,
                "cleanup_queue_invalid_lines_summary",
                "Cleanup queue contains multiple invalid JSON lines; skipping",
                run_id=run_id,
                path=str(cleanup_queue_path),
                invalid_lines=invalid_json_lines,
            )
        if not pending_names:
            return cleanup_pending, cleanup_recovered

        cleanup_pending = len(pending_names)
        remaining: List[str] = []
        client = get_client()
        for name in pending_names:
            ok = safe_delete_file(client, name, logger, timeout_s=timeout_s)
            if ok:
                cleanup_recovered += 1
            else:
                remaining.append(name)
        if remaining:
            cleanup_queue_path.write_text(
                "".join(json.dumps({"name": item}, ensure_ascii=False) + "\n" for item in remaining),
                encoding="utf-8",
            )
        else:
            cleanup_queue_path.unlink(missing_ok=True)
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "cleanup_queue_retry_fail",
            "Upload cleanup retry failed",
            run_id=run_id,
            error=str(exc),
            path=str(cleanup_queue_path),
        )
    return cleanup_pending, cleanup_recovered
