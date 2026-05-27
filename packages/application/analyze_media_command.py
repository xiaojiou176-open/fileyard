# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import concurrent.futures
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping


def run_analyze_command(args: argparse.Namespace, hooks: Mapping[str, Any]) -> None:
    logger = hooks["setup_logger"](
        getattr(args, "log_level", hooks["DEFAULT_LOG_LEVEL"]),
        getattr(args, "log_json", hooks["DEFAULT_LOG_JSON"]),
    )
    start_ts = time.monotonic()
    run_id = getattr(args, "run_id", "") or hooks["new_run_id"]("analyze")

    input_dir = Path(args.input).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    partial_manifest = Path(str(manifest_path) + ".partial")
    csv_path = Path(args.csv).expanduser().resolve() if args.csv else None
    report_raw = getattr(args, "report", "")
    report_path = Path(report_raw).expanduser().resolve() if report_raw else None
    chunk_size = int(getattr(args, "chunk_size", hooks["DEFAULT_CHUNK_SIZE"]) or hooks["DEFAULT_CHUNK_SIZE"])
    if chunk_size <= 0:
        chunk_size = hooks["DEFAULT_CHUNK_SIZE"]

    hooks["log_event"](
        logger,
        logging.INFO,
        "run_start",
        "Analyze run start",
        run_id=run_id,
        input=str(input_dir),
        manifest=str(manifest_path),
        csv=str(csv_path) if csv_path else "",
        report=str(report_path) if report_path else "",
        chunk_size=chunk_size,
    )

    def _fail(code, event: str, message: str, **fields: Any) -> None:
        elapsed = round(time.monotonic() - start_ts, 3)
        hooks["log_event"](
            logger,
            logging.ERROR,
            event,
            message,
            error_code=code.value,
            run_id=run_id,
            **fields,
        )
        hooks["log_event"](
            logger,
            logging.ERROR,
            "run_failed",
            "Analyze run failed",
            run_id=run_id,
            duration_s=elapsed,
            error_code=code.value,
        )
        raise SystemExit(message)

    error_code = hooks["ErrorCode"]
    if not input_dir.exists():
        _fail(
            error_code.INPUT_DIR_MISSING,
            "input_dir_missing",
            f"Input directory does not exist: {input_dir}",
            input=str(input_dir),
        )

    offline = bool(getattr(args, "offline", False))
    api_key = getattr(args, "api_key", "")
    model = str(getattr(args, "model", "") or "").strip()
    if not offline:
        if not api_key:
            _fail(error_code.PROVIDER_CREDENTIAL_MISSING, "provider_credential_missing", "Missing GEMINI_API_KEY environment variable.")
        if not model:
            _fail(
                error_code.MODEL_MISSING,
                "model_missing",
                "Missing model name. Set --model or GEMINI_MODEL.",
            )
        if not model.lower().startswith("gemini-"):
            _fail(
                error_code.MODEL_MISSING,
                "model_invalid",
                "Model name must start with gemini- (Gemini-only policy).",
                model=model,
            )

    categories = hooks["normalize_categories"](args.categories or hooks["DEFAULT_CATEGORIES"])

    image_prompt = hooks["build_prompt"](categories, "image") if not offline else ""
    doc_prompt = hooks["build_prompt"](categories, "pdf") if not offline else ""
    audio_transcribe_prompt = hooks["build_audio_transcribe_prompt"]() if not offline else ""

    fsync_interval = hooks["resolve_fsync_interval"](
        getattr(args, "durability", hooks["DEFAULT_DURABILITY"]),
        getattr(args, "fsync_interval", 0),
    )
    if fsync_interval < 0:
        fsync_interval = 0

    summary = hooks["Summary"]()
    max_file_raw = getattr(args, "max_file_mb", hooks["DEFAULT_MAX_FILE_MB"])
    max_files_raw = getattr(args, "max_files", hooks["DEFAULT_MAX_FILES"])
    max_total_raw = getattr(args, "max_total_mb", hooks["DEFAULT_MAX_TOTAL_MB"])
    max_file_mb = float(hooks["DEFAULT_MAX_FILE_MB"] if max_file_raw is None else max_file_raw)
    max_files = int(hooks["DEFAULT_MAX_FILES"] if max_files_raw is None else max_files_raw)
    max_total_mb = float(hooks["DEFAULT_MAX_TOTAL_MB"] if max_total_raw is None else max_total_raw)
    if max_files < 0:
        max_files = 0
    if max_total_mb < 0:
        max_total_mb = 0.0
    workers = int(getattr(args, "workers", hooks["DEFAULT_WORKERS"]) or hooks["DEFAULT_WORKERS"])
    if workers <= 0:
        workers = 1
    ai_timeout_s = float(getattr(args, "ai_timeout_s", hooks["DEFAULT_AI_TIMEOUT_S"]) or hooks["DEFAULT_AI_TIMEOUT_S"])
    if ai_timeout_s <= 0:
        ai_timeout_s = hooks["DEFAULT_AI_TIMEOUT_S"]
    subprocess_timeout_s = float(
        getattr(args, "subprocess_timeout_s", hooks["DEFAULT_SUBPROCESS_TIMEOUT_S"]) or hooks["DEFAULT_SUBPROCESS_TIMEOUT_S"]
    )
    if subprocess_timeout_s <= 0:
        subprocess_timeout_s = hooks["DEFAULT_SUBPROCESS_TIMEOUT_S"]
    cleanup_queue_path = Path(str(manifest_path) + ".cleanup_uploads.jsonl")

    ctx = hooks["AnalyzeContext"](
        input_dir=input_dir,
        categories=categories,
        run_id=run_id,
        generator_version=getattr(args, "generator_version", "") or hooks["APP_VERSION"],
        schema_version=hooks["MANIFEST_SCHEMA_VERSION"],
        fsync_interval=fsync_interval,
        inline_max_mb=args.inline_max_mb,
        resize_max_side=args.resize_max_side,
        max_retries=args.max_retries,
        retry_base_s=args.retry_base_s,
        retry_max_s=args.retry_max_s,
        ai_timeout_s=ai_timeout_s,
        subprocess_timeout_s=subprocess_timeout_s,
        audio_segment_threshold=args.audio_segment_threshold,
        audio_segment_seconds=args.audio_segment_seconds,
        audio_segment_count=args.audio_segment_count,
        audio_transcript_max_chars=args.audio_transcript_max_chars,
        doc_text_max_chars=args.doc_text_max_chars,
        sleep_s=args.sleep,
        offline=offline,
        model=model,
        api_key=api_key,
        max_file_mb=max_file_mb,
        image_prompt=image_prompt,
        doc_prompt=doc_prompt,
        audio_transcribe_prompt=audio_transcribe_prompt,
        logger=logger,
        cleanup_queue_path=cleanup_queue_path,
        cleanup_queue_lock=threading.Lock(),
    )
    total = 0
    total_mb = 0.0
    exceeded = False
    if max_files > 0 or max_total_mb > 0:
        try:
            total, total_mb, exceeded = hooks["scan_media_stats"](
                input_dir,
                max_files=max_files,
                max_total_mb=max_total_mb,
            )
        except Exception as exc:
            _fail(
                error_code.PREFLIGHT_LIMIT,
                "preflight_fail",
                f"Preflight failed: {exc}",
                input=str(input_dir),
            )
        if exceeded:
            _fail(
                error_code.PREFLIGHT_LIMIT,
                "preflight_limit",
                "Preflight limit exceeded",
                input=str(input_dir),
                max_files=max_files,
                max_total_mb=max_total_mb,
                total_files=total,
                total_mb=round(total_mb, 2),
            )
    else:
        total = hooks["count_media_files"](input_dir)
    if total <= 0:
        hooks["log_event"](
            logger,
            logging.INFO,
            "scan_empty",
            "No media files found.",
            input=str(input_dir),
            run_id=run_id,
        )
        elapsed = round(time.monotonic() - start_ts, 3)
        hooks["log_event"](
            logger,
            logging.INFO,
            "run_end",
            "Analyze run end",
            run_id=run_id,
            duration_s=elapsed,
            total=0,
            with_error=0,
        )
        return

    thread_local = threading.local()
    thread_clients: list[Any] = []
    thread_clients_lock = threading.Lock()

    def _get_client():
        if ctx.offline:
            return None
        client = getattr(thread_local, "client", None)
        if client is None:
            client = hooks["build_client"](ctx.api_key)
            thread_local.client = client
            with thread_clients_lock:
                thread_clients.append(client)
        return client

    def _cleanup_clients() -> None:
        """Clean up thread-local clients to prevent resource leaks."""
        with thread_clients_lock:
            for client in thread_clients:
                try:
                    if hasattr(client, "close"):
                        client.close()
                except Exception as exc:
                    hooks["log_event"](
                        logger,
                        logging.DEBUG,
                        "client_close_fail",
                        "Thread client shutdown failed",
                        run_id=run_id,
                        client_type=type(client).__name__,
                        error=str(exc),
                    )
            thread_clients.clear()

    cleanup_pending = 0
    cleanup_recovered = 0
    line_count = 0
    key_error = hooks["KEY_ERROR"]
    key_error_code = hooks["KEY_ERROR_CODE"]
    key_path = hooks["KEY_PATH"]
    key_ai = hooks["KEY_AI"]
    ai_kind = hooks["AI_KIND"]
    ai_category = hooks["AI_CATEGORY"]
    ai_title = hooks["AI_TITLE"]

    try:
        try:
            with hooks["open_jsonl_writer"](partial_manifest) as fh:

                def _emit_row(item: Dict[str, Any]) -> None:
                    nonlocal line_count
                    hooks["attach_manifest_metadata"](
                        item,
                        run_id=ctx.run_id,
                        generator_version=ctx.generator_version,
                        schema_version=ctx.schema_version,
                    )
                    line_count += 1
                    err_msg = item.get(key_error, "") or ""
                    err_code = item.get(key_error_code, "") or ""
                    if err_msg or err_code:
                        err_exc = RuntimeError(err_msg or f"analyze error ({err_code})")
                        hooks["log_event"](
                            ctx.logger,
                            logging.ERROR,
                            "analyze_error",
                            err_msg or "analyze error",
                            path=str(item.get(key_path, "")),
                            error_code=err_code,
                            exception=err_exc,
                        )
                    hooks["write_jsonl_line"](
                        fh,
                        item,
                        fsync=ctx.fsync_interval > 0 and line_count % ctx.fsync_interval == 0,
                    )
                    summary.update(item)

                if workers == 1:
                    for idx, path in enumerate(hooks["iter_media_files"](input_dir), 1):
                        row = hooks["_analyze_one"](path, ctx, _get_client)
                        _emit_row(row)
                        kind = (row.get(key_ai, {}) or {}).get(ai_kind, "")
                        category = (row.get(key_ai, {}) or {}).get(ai_category, "")
                        title = (row.get(key_ai, {}) or {}).get(ai_title, "")
                        hooks["log_event"](
                            logger,
                            logging.INFO,
                            "progress",
                            f"[{idx}/{total}] {path.name} -> {kind} / {category} / {title}",
                            index=idx,
                            total=total,
                            file=path.name,
                            kind=kind,
                            category=category,
                        )
                else:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                        it = enumerate(hooks["iter_media_files"](input_dir), start=1)
                        inflight: dict[concurrent.futures.Future, int] = {}
                        max_inflight = max(workers * 4, workers)
                        for _ in range(max_inflight):
                            try:
                                order_idx, path = next(it)
                            except StopIteration:
                                break
                            inflight[executor.submit(hooks["_analyze_one"], path, ctx, _get_client)] = order_idx

                        next_emit_idx = 1
                        buffered_rows: dict[int, Dict[str, Any]] = {}
                        while inflight:
                            done, _ = concurrent.futures.wait(
                                set(inflight),
                                return_when=concurrent.futures.FIRST_COMPLETED,
                            )
                            for future in done:
                                order_idx = inflight.pop(future)
                                buffered_rows[order_idx] = future.result()
                                try:
                                    new_order_idx, path = next(it)
                                except StopIteration:
                                    pass
                                else:
                                    inflight[executor.submit(hooks["_analyze_one"], path, ctx, _get_client)] = new_order_idx
                            while next_emit_idx in buffered_rows:
                                row = buffered_rows.pop(next_emit_idx)
                                _emit_row(row)
                                path_val = row.get(key_path, "")
                                name = Path(path_val).name if path_val else ""
                                kind = (row.get(key_ai, {}) or {}).get(ai_kind, "")
                                category = (row.get(key_ai, {}) or {}).get(ai_category, "")
                                title = (row.get(key_ai, {}) or {}).get(ai_title, "")
                                hooks["log_event"](
                                    logger,
                                    logging.INFO,
                                    "progress",
                                    f"[{next_emit_idx}/{total}] {name} -> {kind} / {category} / {title}",
                                    index=next_emit_idx,
                                    total=total,
                                    file=name,
                                    kind=kind,
                                    category=category,
                                )
                                next_emit_idx += 1

                if ctx.fsync_interval > 0 and line_count % ctx.fsync_interval != 0:
                    fh.flush()
                    hooks["os"].fsync(fh.fileno())
        except Exception as exc:
            if partial_manifest.exists():
                try:
                    partial_manifest.unlink()
                except Exception as cleanup_exc:
                    hooks["log_event"](
                        logger,
                        logging.WARNING,
                        "manifest_cleanup_fail",
                        f"Failed to clean temporary manifest: {cleanup_exc}",
                        path=str(partial_manifest),
                        run_id=run_id,
                    )
            _fail(
                error_code.MANIFEST_WRITE_FAIL,
                "manifest_write_fail",
                f"Failed to write manifest: {exc}",
                path=str(manifest_path),
            )

        try:
            partial_manifest.replace(manifest_path)
        except Exception as exc:
            _fail(
                error_code.MANIFEST_UPDATE_FAIL,
                "manifest_update_fail",
                f"Failed to update manifest: {exc}",
                path=str(manifest_path),
            )
        hooks["log_event"](
            logger,
            logging.INFO,
            "manifest_written",
            "Wrote manifest",
            path=str(manifest_path),
            run_id=run_id,
        )

        if csv_path:
            try:
                hooks["write_csv_from_manifest"](manifest_path, csv_path, validate=False, chunk_size=chunk_size)
            except Exception as exc:
                _fail(
                    error_code.CSV_WRITE_FAIL,
                    "csv_write_fail",
                    f"Failed to write CSV: {exc}",
                    path=str(csv_path),
                )
            hooks["log_event"](logger, logging.INFO, "csv_written", "Wrote CSV", path=str(csv_path), run_id=run_id)

        if report_path:
            try:
                hooks["write_report"](report_path, summary)
            except Exception as exc:
                _fail(
                    error_code.REPORT_WRITE_FAIL,
                    "report_write_fail",
                    f"Failed to write report: {exc}",
                    path=str(report_path),
                )
            hooks["log_event"](
                logger,
                logging.INFO,
                "report_written",
                "Wrote report",
                path=str(report_path),
                run_id=run_id,
            )

        cleanup_pending, cleanup_recovered = hooks["_retry_cleanup_queue"](
            cleanup_queue_path=cleanup_queue_path,
            offline=offline,
            get_client=_get_client,
            logger=logger,
            timeout_s=ctx.ai_timeout_s,
            run_id=run_id,
        )

        elapsed = round(time.monotonic() - start_ts, 3)
        hooks["log_event"](
            logger,
            logging.INFO,
            "run_end",
            "Analyze run end",
            run_id=run_id,
            duration_s=elapsed,
            total=summary.total,
            with_error=summary.with_error,
            error_codes=dict(summary.error_codes),
            cleanup_pending=cleanup_pending,
            cleanup_recovered=cleanup_recovered,
        )
    finally:
        _cleanup_clients()
