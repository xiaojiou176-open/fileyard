# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from packages.application.analyze_media_helpers import AnalyzeContext
from packages.domain.pipeline_config import (
    AI_CATEGORY,
    AI_CONFIDENCE,
    AI_KIND,
    AI_NOTES,
    AI_TAGS,
    AI_TITLE,
    CATEGORY_OTHER,
    KEY_AI,
    KEY_DURATION_S,
    KEY_ERROR,
    KEY_EXIF_DATETIME,
    KEY_GPS_LAT,
    KEY_GPS_LON,
    KEY_HEIGHT,
    KEY_MIME,
    KEY_TRANSCRIPT,
    KEY_TRANSCRIPT_CONF,
    KEY_TRANSCRIPT_LANG,
    KEY_TRANSCRIPT_SEGMENTS,
    KEY_WIDTH,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_DOCX,
    MEDIA_PDF,
    MEDIA_PPT,
    MEDIA_PPTX,
    ErrorCode,
    ImageKind,
)

AnalyzeHookMap = dict[str, Callable[..., Any] | Any]


def _append_warning(row: dict[str, Any], field: str, warnings: list[str]) -> None:
    if not warnings:
        return
    existing = str(row.get(field, "") or "")
    joined = "; ".join(warnings)
    row[field] = f"{existing}; {joined}".strip("; ").strip()


def _cleanup_temp_dir(temp_dir: Path | None, ctx: AnalyzeContext, hooks: AnalyzeHookMap) -> None:
    if temp_dir is None:
        return
    try:
        shutil.rmtree(temp_dir)
    except Exception as exc:
        hooks["log_event"](
            ctx.logger,
            logging.WARNING,
            "cleanup_fail",
            f"Temporary directory cleanup failed: {exc}",
            path=str(temp_dir),
        )


def _cleanup_upload(client: Any, upload_name: str | None, ctx: AnalyzeContext, hooks: AnalyzeHookMap) -> None:
    if not upload_name:
        return
    ok = hooks["safe_delete_file"](client, upload_name, ctx.logger, timeout_s=ctx.ai_timeout_s)
    if not ok:
        hooks["queue_failed_upload"](ctx, upload_name)


def handle_offline_row(path: Path, row: dict[str, Any], ctx: AnalyzeContext, media_type: str, hooks: AnalyzeHookMap) -> dict[str, Any]:
    if media_type == MEDIA_AUDIO:
        try:
            row.update(hooks["extract_audio_fields"](path))
        except Exception as exc:
            hooks["set_error"](row, ErrorCode.AUDIO_PREP_FAIL, f"Audio metadata error: {exc}")
            return row
        row[KEY_MIME] = hooks["guess_mime"](path)
    elif media_type in {MEDIA_PDF, MEDIA_DOCX, MEDIA_DOC, MEDIA_PPTX, MEDIA_PPT}:
        row[KEY_MIME] = hooks["guess_mime"](path)
    else:
        try:
            row.update(hooks["extract_exif_fields"](path))
        except Exception as exc:
            row.update(
                {
                    KEY_EXIF_DATETIME: "",
                    KEY_GPS_LAT: "",
                    KEY_GPS_LON: "",
                    KEY_WIDTH: "",
                    KEY_HEIGHT: "",
                }
            )
            hooks["log_event"](
                ctx.logger,
                logging.WARNING,
                "exif_fail",
                f"EXIF read failed for {path.name}: {exc}",
                path=str(path),
            )
    row[KEY_AI] = hooks["build_offline_ai"](path, media_type, ctx.categories)
    row["ai_warning"] = "Offline mode: local rules were used"
    return row


def handle_audio_row(
    path: Path,
    row: dict[str, Any],
    ctx: AnalyzeContext,
    client: Any,
    hooks: AnalyzeHookMap,
) -> dict[str, Any]:
    try:
        row.update(hooks["extract_audio_fields"](path))
    except Exception as exc:
        hooks["set_error"](row, ErrorCode.AUDIO_PREP_FAIL, f"Audio metadata error: {exc}")
        return row
    row[KEY_MIME] = hooks["guess_mime"](path)

    duration_val = row.get(KEY_DURATION_S)
    try:
        if duration_val is None or duration_val == "":
            duration_s = 0.0
        elif isinstance(duration_val, (str, int, float)):
            duration_s = float(duration_val)
        else:
            duration_s = 0.0
    except Exception:
        duration_s = 0.0

    segment_items: list[tuple[Path, float, float]] = []
    temp_dir: Path | None = None
    if duration_s >= ctx.audio_segment_threshold:
        plan = hooks["plan_audio_segments"](duration_s, ctx.audio_segment_seconds, ctx.audio_segment_count)
        try:
            segments, temp_dir = hooks["extract_audio_segments"](path, plan, timeout_s=ctx.subprocess_timeout_s)
        except Exception as exc:
            code = ErrorCode.AUDIO_PREP_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AUDIO_PREP_FAIL
            hooks["set_error"](row, code, f"Audio segmentation failed: {exc}")
            return row
        if segments:
            segment_items = segments
        else:
            row["audio_warning"] = "Segmentation failed or ffmpeg is unavailable; falling back to the full clip"
    if not segment_items:
        segment_items = [(path, 0.0, duration_s)]

    transcript_segments: list[dict[str, Any]] = []
    transcript_retry_total = 0

    for seg_path, start_s, length_s in segment_items:
        try:
            audio_part, _, upload_name = hooks["prepare_audio_part"](
                seg_path,
                client,
                ctx.inline_max_mb,
                timeout_s=ctx.ai_timeout_s,
            )
        except Exception as exc:
            code = ErrorCode.AUDIO_PREP_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AUDIO_PREP_FAIL
            hooks["set_error"](row, code, f"Audio preparation error: {exc}")
            break
        try:
            payload, retry_count = hooks["call_gemini_with_retry"](
                client=client,
                model=ctx.model,
                image_part=audio_part,
                prompt=ctx.audio_transcribe_prompt,
                max_retries=ctx.max_retries,
                retry_base_s=ctx.retry_base_s,
                retry_max_s=ctx.retry_max_s,
                timeout_s=ctx.ai_timeout_s,
            )
            transcript_retry_total += retry_count
        except Exception as exc:
            code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AUDIO_TRANSCRIBE_FAIL
            hooks["set_error"](row, code, f"Transcription error: {exc}")
        finally:
            _cleanup_upload(client, upload_name, ctx, hooks)
        if row.get(KEY_ERROR):
            break

        data = hooks["extract_transcript_payload"](payload)
        segment_conf_warnings: list[str] = []
        segment_conf = hooks["coerce_confidence"](
            data.get(KEY_TRANSCRIPT_CONF, 0.0),
            field_name="transcript_confidence",
            warnings=segment_conf_warnings,
        )
        _append_warning(row, "transcript_warning", segment_conf_warnings)
        transcript_segments.append(
            {
                "start_s": round(start_s, 3),
                "duration_s": round(length_s, 3),
                "text": data.get(KEY_TRANSCRIPT, ""),
                "language": data.get(KEY_TRANSCRIPT_LANG, ""),
                "confidence": segment_conf,
                "notes": data.get("transcript_notes", ""),
            }
        )

    _cleanup_temp_dir(temp_dir, ctx, hooks)

    if row.get(KEY_ERROR):
        return row

    transcript, lang, conf = hooks["merge_transcript_segments"](transcript_segments)
    row[KEY_TRANSCRIPT] = transcript
    row[KEY_TRANSCRIPT_SEGMENTS] = transcript_segments
    row[KEY_TRANSCRIPT_LANG] = lang
    merged_conf_warnings: list[str] = []
    merged_conf = hooks["coerce_confidence"](
        conf,
        field_name="merged_transcript_confidence",
        warnings=merged_conf_warnings,
    )
    row[KEY_TRANSCRIPT_CONF] = merged_conf
    _append_warning(row, "transcript_warning", merged_conf_warnings)
    if transcript_retry_total:
        row["transcript_retry"] = transcript_retry_total

    if transcript:
        classify_prompt = hooks["build_audio_classify_prompt"](
            ctx.categories,
            hooks["truncate_text"](transcript, ctx.audio_transcript_max_chars),
        )
        try:
            ai_raw, retry_count = hooks["call_gemini_text_with_retry"](
                client=client,
                model=ctx.model,
                prompt=classify_prompt,
                max_retries=ctx.max_retries,
                retry_base_s=ctx.retry_base_s,
                retry_max_s=ctx.retry_max_s,
                timeout_s=ctx.ai_timeout_s,
            )
            ai_sanitized, warnings = hooks["sanitize_ai"](ai_raw, ctx.categories)
            row[KEY_AI] = ai_sanitized
            if retry_count:
                row["ai_retry"] = retry_count
            if warnings:
                row["ai_warning"] = "; ".join(warnings)
        except Exception as exc:
            row[KEY_AI] = {}
            code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AI_FAIL
            hooks["set_error"](row, code, f"AI error: {exc}")
    else:
        row[KEY_AI] = {
            AI_KIND: ImageKind.AUDIO.value,
            AI_CATEGORY: CATEGORY_OTHER,
            AI_TITLE: "Untitled",
            AI_TAGS: [],
            AI_CONFIDENCE: 0,
            AI_NOTES: "Transcript empty",
        }
        row["ai_warning"] = "Transcript empty; classification skipped"
    return row


def _handle_pdf_row(path: Path, row: dict[str, Any], ctx: AnalyzeContext, client: Any, hooks: AnalyzeHookMap) -> dict[str, Any]:
    try:
        doc_part, mime, upload_name = hooks["build_file_part"](path, client, ctx.inline_max_mb, timeout_s=ctx.ai_timeout_s)
        row[KEY_MIME] = mime
    except Exception as exc:
        code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.DOC_PREP_FAIL
        hooks["set_error"](row, code, f"Document preparation error: {exc}")
        return row

    try:
        ai_raw, retry_count = hooks["call_gemini_with_retry"](
            client=client,
            model=ctx.model,
            image_part=doc_part,
            prompt=ctx.doc_prompt,
            max_retries=ctx.max_retries,
            retry_base_s=ctx.retry_base_s,
            retry_max_s=ctx.retry_max_s,
            timeout_s=ctx.ai_timeout_s,
        )
        ai_sanitized, warnings = hooks["sanitize_ai"](ai_raw, ctx.categories)
        row[KEY_AI] = ai_sanitized
        if retry_count:
            row["ai_retry"] = retry_count
        if warnings:
            row["ai_warning"] = "; ".join(warnings)
    except Exception as exc:
        row[KEY_AI] = {}
        code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AI_FAIL
        hooks["set_error"](row, code, f"AI error: {exc}")
    finally:
        _cleanup_upload(client, upload_name, ctx, hooks)
    return row


def _handle_convertible_document_row(
    path: Path,
    row: dict[str, Any],
    ctx: AnalyzeContext,
    client: Any,
    hooks: AnalyzeHookMap,
) -> dict[str, Any]:
    temp_dir: Path | None = None
    try:
        pdf_path, temp_dir, conv_tool = hooks["convert_to_pdf"](path, timeout_s=ctx.subprocess_timeout_s)
    except Exception as exc:
        code = ErrorCode.DOC_CONVERT_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.DOC_CONVERT_FAIL
        hooks["set_error"](row, code, f"Document-to-PDF conversion failed: {exc}")
        return row

    upload_name = None
    try:
        doc_part, mime, upload_name = hooks["build_file_part"](
            pdf_path,
            client,
            ctx.inline_max_mb,
            timeout_s=ctx.ai_timeout_s,
        )
        row[KEY_MIME] = mime
        row["doc_convert"] = conv_tool
    except Exception as exc:
        code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.DOC_PREP_FAIL
        hooks["set_error"](row, code, f"Document preparation error: {exc}")
        _cleanup_temp_dir(temp_dir, ctx, hooks)
        return row

    try:
        ai_raw, retry_count = hooks["call_gemini_with_retry"](
            client=client,
            model=ctx.model,
            image_part=doc_part,
            prompt=ctx.doc_prompt,
            max_retries=ctx.max_retries,
            retry_base_s=ctx.retry_base_s,
            retry_max_s=ctx.retry_max_s,
            timeout_s=ctx.ai_timeout_s,
        )
        ai_sanitized, warnings = hooks["sanitize_ai"](ai_raw, ctx.categories)
        row[KEY_AI] = ai_sanitized
        if retry_count:
            row["ai_retry"] = retry_count
        if warnings:
            row["ai_warning"] = "; ".join(warnings)
    except Exception as exc:
        row[KEY_AI] = {}
        code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AI_FAIL
        hooks["set_error"](row, code, f"AI error: {exc}")
    finally:
        _cleanup_upload(client, upload_name, ctx, hooks)
        _cleanup_temp_dir(temp_dir, ctx, hooks)
    return row


def handle_document_row(
    path: Path,
    row: dict[str, Any],
    ctx: AnalyzeContext,
    client: Any,
    media_type: str,
    hooks: AnalyzeHookMap,
) -> dict[str, Any]:
    row[KEY_MIME] = hooks["guess_mime"](path)
    if media_type == MEDIA_PDF:
        return _handle_pdf_row(path, row, ctx, client, hooks)
    if media_type in {MEDIA_DOCX, MEDIA_DOC, MEDIA_PPTX, MEDIA_PPT}:
        return _handle_convertible_document_row(path, row, ctx, client, hooks)
    hooks["set_error"](
        row,
        ErrorCode.DOC_CONVERT_FAIL,
        "Unsupported document format. Convert it to PDF, DOCX, PPTX, DOC, or PPT first.",
    )
    return row


def handle_visual_row(
    path: Path,
    row: dict[str, Any],
    ctx: AnalyzeContext,
    client: Any,
    media_type: str,
    hooks: AnalyzeHookMap,
) -> dict[str, Any]:
    try:
        row.update(hooks["extract_exif_fields"](path))
    except Exception as exc:
        row.update(
            {
                KEY_EXIF_DATETIME: "",
                KEY_GPS_LAT: "",
                KEY_GPS_LON: "",
                KEY_WIDTH: "",
                KEY_HEIGHT: "",
            }
        )
        hooks["log_event"](
            ctx.logger,
            logging.WARNING,
            "exif_fail",
            f"EXIF read failed for {path.name}: {exc}",
            path=str(path),
        )

    try:
        image_part, mime, w, h, upload_name = hooks["prepare_image_part"](
            path,
            client,
            ctx.inline_max_mb,
            ctx.resize_max_side,
            timeout_s=ctx.ai_timeout_s,
        )
        row[KEY_MIME] = mime
        if w is not None:
            row[KEY_WIDTH] = w
        if h is not None:
            row[KEY_HEIGHT] = h
    except Exception as exc:
        code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.IMAGE_PREP_FAIL
        hooks["set_error"](row, code, f"Image preparation error: {exc}")
        return row

    try:
        ai_raw, retry_count = hooks["call_gemini_with_retry"](
            client=client,
            model=ctx.model,
            image_part=image_part,
            prompt=ctx.image_prompt,
            max_retries=ctx.max_retries,
            retry_base_s=ctx.retry_base_s,
            retry_max_s=ctx.retry_max_s,
            timeout_s=ctx.ai_timeout_s,
        )
        ai_sanitized, warnings = hooks["sanitize_ai"](ai_raw, ctx.categories)
        row[KEY_AI] = ai_sanitized
        if retry_count:
            row["ai_retry"] = retry_count
        if warnings:
            row["ai_warning"] = "; ".join(warnings)
    except Exception as exc:
        row[KEY_AI] = {}
        code = ErrorCode.AI_TIMEOUT if hooks["is_timeout_error"](exc) else ErrorCode.AI_FAIL
        hooks["set_error"](row, code, f"AI error: {exc}")
    finally:
        _cleanup_upload(client, upload_name, ctx, hooks)

    return row
