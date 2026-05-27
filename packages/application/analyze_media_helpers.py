# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from packages.domain.core_utils import safe_stat_mtime, sha1_file
from packages.domain.normalization import normalize_category, normalize_kind, sanitize_cn_tags, sanitize_cn_text
from packages.domain.pipeline_config import (
    AI_CATEGORY,
    AI_CONFIDENCE,
    AI_KIND,
    AI_NOTES,
    AI_TAGS,
    AI_TITLE,
    CATEGORY_OTHER,
    KEY_AI,
    KEY_ERROR,
    KEY_EXIF_DATETIME,
    KEY_FILE_MTIME,
    KEY_HASH8,
    KEY_PATH,
    KEY_SHA1,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_DOCX,
    MEDIA_IMAGE,
    MEDIA_PDF,
    MEDIA_PPT,
    MEDIA_PPTX,
    ImageKind,
)


def build_base_row(path: Path) -> Dict[str, Any]:
    sha1 = sha1_file(path)
    mtime = safe_stat_mtime(path)
    return {
        KEY_PATH: str(path),
        KEY_ERROR: "",
        KEY_SHA1: sha1,
        KEY_HASH8: sha1[:8],
        KEY_FILE_MTIME: mtime.isoformat(timespec="seconds"),
    }


def sanitize_ai(ai: Any, categories: Sequence[str]) -> tuple[Dict[str, Any], List[str]]:
    if not isinstance(ai, dict):
        return {}, ["AI output must be an object"]

    allowed_fields = {AI_KIND, AI_CATEGORY, AI_TITLE, AI_TAGS, AI_CONFIDENCE, AI_NOTES}
    warnings: List[str] = []
    sanitized: Dict[str, Any] = {}

    extra_fields = sorted(str(k) for k in ai.keys() if str(k) not in allowed_fields)
    if extra_fields:
        warnings.append(f"Dropped unsupported fields: {', '.join(extra_fields)}")

    raw_kind = str(ai.get(AI_KIND, "") or "")
    raw_category = str(ai.get(AI_CATEGORY, "") or "")
    raw_title = str(ai.get(AI_TITLE, "") or "")
    raw_tags = ai.get(AI_TAGS, [])
    raw_confidence = ai.get(AI_CONFIDENCE, 0.0)
    raw_notes = str(ai.get(AI_NOTES, "") or "")

    kind = normalize_kind(raw_kind)
    category = normalize_category(raw_category, categories)

    if kind != raw_kind:
        warnings.append(f"Normalized kind: {raw_kind} -> {kind}")
    if category != raw_category:
        warnings.append(f"Normalized category: {raw_category} -> {category}")

    sanitized[AI_KIND] = kind
    sanitized[AI_CATEGORY] = category
    title_clean = sanitize_cn_text(raw_title.strip(), "未命名")
    if title_clean != raw_title.strip():
        warnings.append("Normalized title: removed non-Chinese characters")
    sanitized[AI_TITLE] = title_clean

    if isinstance(raw_tags, list):
        tags_clean = sanitize_cn_tags([str(t).strip() for t in raw_tags if str(t).strip()])
        if tags_clean != [str(t).strip() for t in raw_tags if str(t).strip()]:
            warnings.append("Normalized tags: removed non-Chinese characters")
        sanitized[AI_TAGS] = tags_clean
    else:
        sanitized[AI_TAGS] = []
        warnings.append("Normalized tags: non-list input -> []")

    notes_clean = sanitize_cn_text(raw_notes.strip(), "")
    if notes_clean != raw_notes.strip():
        warnings.append("Normalized notes: removed non-Chinese characters")
    sanitized[AI_NOTES] = notes_clean

    confidence: float
    if isinstance(raw_confidence, bool):
        confidence = 0.0
        warnings.append("Invalid confidence type: bool -> 0.0")
    elif isinstance(raw_confidence, (int, float)):
        confidence = float(raw_confidence)
    elif isinstance(raw_confidence, str):
        text = raw_confidence.strip()
        try:
            confidence = float(text) if text else 0.0
            if text == "":
                warnings.append("Missing confidence: fell back to 0.0")
        except Exception:
            confidence = 0.0
            warnings.append("Invalid confidence type: non-numeric string -> 0.0")
    else:
        confidence = 0.0
        warnings.append("Invalid confidence type: non-numeric value -> 0.0")

    if not (0.0 <= confidence <= 1.0):
        warnings.append(f"Confidence out of range: {confidence} -> 0.0")
        confidence = 0.0
    sanitized[AI_CONFIDENCE] = confidence

    return sanitized, warnings


def _coerce_confidence(raw_value: Any, *, field_name: str, warnings: List[str], default_value: float = 0.0) -> float:
    value: float
    if isinstance(raw_value, bool):
        warnings.append(f"Invalid {field_name}: bool -> {default_value}")
        return default_value
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            warnings.append(f"Missing {field_name}: fell back to {default_value}")
            return default_value
        try:
            value = float(text)
        except Exception:
            warnings.append(f"Invalid {field_name}: non-numeric string -> {default_value}")
            return default_value
    else:
        warnings.append(f"Invalid {field_name}: non-numeric value -> {default_value}")
        return default_value
    if not (0.0 <= value <= 1.0):
        warnings.append(f"{field_name} out of range: {value} -> {default_value}")
        return default_value
    return value


@dataclass(frozen=True)
class AnalyzeContext:
    input_dir: Path
    categories: Sequence[str]
    run_id: str
    generator_version: str
    schema_version: int
    fsync_interval: int
    inline_max_mb: float
    resize_max_side: int
    max_retries: int
    retry_base_s: float
    retry_max_s: float
    ai_timeout_s: float
    subprocess_timeout_s: float
    audio_segment_threshold: float
    audio_segment_seconds: float
    audio_segment_count: int
    audio_transcript_max_chars: int
    doc_text_max_chars: int
    sleep_s: float
    offline: bool
    model: str
    api_key: str
    max_file_mb: float
    image_prompt: str
    doc_prompt: str
    audio_transcribe_prompt: str
    logger: logging.Logger
    cleanup_queue_path: Path
    cleanup_queue_lock: threading.Lock


def _normalize_ai_kind_for_media_type(
    row: Dict[str, Any],
    media_type: str,
    path: Path,
) -> None:
    """Normalize AI kind field based on media type.

    Ensures the AI-assigned kind matches the actual media type, adding
    a warning if normalization was needed.
    """
    if not row.get(KEY_AI):
        return

    raw_kind = (row.get(KEY_AI, {}) or {}).get(AI_KIND, "")

    def _add_warning(msg: str) -> None:
        if row.get("ai_warning"):
            row["ai_warning"] = f"{row['ai_warning']}; {msg}"
        else:
            row["ai_warning"] = msg

    if media_type == MEDIA_AUDIO:
        if raw_kind != ImageKind.AUDIO.value:
            row[KEY_AI][AI_KIND] = ImageKind.AUDIO.value
            _add_warning(f"Normalized kind: {raw_kind} -> {ImageKind.AUDIO.value}")
    elif media_type in {MEDIA_PDF, MEDIA_DOCX, MEDIA_DOC, MEDIA_PPTX, MEDIA_PPT}:
        if raw_kind != ImageKind.DOCUMENT.value:
            row[KEY_AI][AI_KIND] = ImageKind.DOCUMENT.value
            _add_warning(f"Normalized kind: {raw_kind} -> {ImageKind.DOCUMENT.value}")
    elif media_type == MEDIA_IMAGE:
        if raw_kind not in {ImageKind.SCREENSHOT.value, ImageKind.PHOTO.value}:
            name_lower = path.name.lower()
            if row.get(KEY_EXIF_DATETIME):
                forced_kind = ImageKind.PHOTO.value
            elif "screenshot" in name_lower or "screen shot" in name_lower or "截屏" in path.name or "截图" in path.name:
                forced_kind = ImageKind.SCREENSHOT.value
            else:
                forced_kind = ImageKind.PHOTO.value
            row[KEY_AI][AI_KIND] = forced_kind
            _add_warning(f"Normalized kind: {raw_kind} -> {forced_kind}")


def _build_offline_ai(path: Path, media_type: str, categories: Sequence[str]) -> Dict[str, Any]:
    name_lower = path.name.lower()
    if media_type == MEDIA_AUDIO:
        kind = ImageKind.AUDIO.value
    elif media_type in {MEDIA_PDF, MEDIA_DOCX, MEDIA_DOC, MEDIA_PPTX, MEDIA_PPT}:
        kind = ImageKind.DOCUMENT.value
    else:
        if "screenshot" in name_lower or "screen shot" in name_lower or "截屏" in path.name or "截图" in path.name:
            kind = ImageKind.SCREENSHOT.value
        else:
            kind = ImageKind.PHOTO.value
    title = sanitize_cn_text(path.stem, "未命名")
    return {
        AI_KIND: kind,
        AI_CATEGORY: normalize_category(CATEGORY_OTHER, categories),
        AI_TITLE: title,
        AI_TAGS: [],
        AI_CONFIDENCE: 0,
        AI_NOTES: "offline",
    }


def _file_size_mb(path: Path) -> float:
    size = path.stat().st_size
    return size / (1024 * 1024)


def _is_timeout_error(exc: Exception) -> bool:
    """Check if an exception indicates a timeout error.

    Uses type checking first, then falls back to string matching for
    various timeout indicators across different locales and libraries.
    """
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 110:
        return True
    if hasattr(exc, "__class__"):
        exc_class_name = exc.__class__.__name__.lower()
        if "timeout" in exc_class_name:
            return True
    status_values: list[Any] = [getattr(exc, "status_code", None), getattr(exc, "code", None)]
    response = getattr(exc, "response", None)
    if response is not None:
        status_values.append(getattr(response, "status_code", None))
    for raw_status in status_values:
        try:
            status_code = int(raw_status)
        except (TypeError, ValueError):
            continue
        if status_code in {408, 504}:
            return True
    text = str(exc).lower()
    timeout_indicators = (
        "timed out",
        "timeout",
        "超时",
        "deadline exceeded",
        "request timeout",
        "connection timed out",
        "read timed out",
        "write timed out",
    )
    return any(indicator in text for indicator in timeout_indicators)


def _queue_failed_upload(ctx: AnalyzeContext, upload_name: str) -> None:
    if not upload_name:
        return
    with ctx.cleanup_queue_lock:
        ctx.cleanup_queue_path.parent.mkdir(parents=True, exist_ok=True)
        with ctx.cleanup_queue_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"name": upload_name}, ensure_ascii=False) + "\n")
