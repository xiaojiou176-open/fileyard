# -*- coding: utf-8 -*-
from __future__ import annotations

import mimetypes
import os
import warnings
from pathlib import Path
from typing import Iterable, Tuple

from packages.domain.pipeline_config import (
    AUDIO_EXTS,
    AUDIO_MIME_ALLOWLIST,
    DOC_EXTS,
    DOC_MIME_ALLOWLIST,
    DOCX_EXTS,
    IMAGE_EXTS,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_DOCX,
    MEDIA_IMAGE,
    MEDIA_PDF,
    MEDIA_PPT,
    MEDIA_PPTX,
    PDF_EXTS,
    PPT_EXTS,
    PPTX_EXTS,
    RAW_MIME_ALLOWLIST,
)


def iter_media_files(root: Path) -> Iterable[Path]:
    # Deterministic ordering helps reproducibility across runs.
    def _on_walk_error(exc: OSError) -> None:
        warnings.warn(f"Directory traversal failed and was skipped: {exc}", RuntimeWarning, stacklevel=2)

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_walk_error):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            if path.suffix.lower() in (IMAGE_EXTS | AUDIO_EXTS | PDF_EXTS | DOCX_EXTS | DOC_EXTS | PPTX_EXTS | PPT_EXTS):
                yield path


def count_media_files(root: Path) -> int:
    total = 0
    for _ in iter_media_files(root):
        total += 1
    return total


def scan_media_stats(
    root: Path,
    *,
    max_files: int = 0,
    max_total_mb: float = 0.0,
) -> Tuple[int, float, bool]:
    total_files = 0
    total_bytes = 0
    exceeded = False
    for path in iter_media_files(root):
        total_files += 1
        if max_files > 0 and total_files > max_files:
            exceeded = True
            break
        if max_total_mb > 0:
            try:
                total_bytes += path.stat().st_size
            except OSError as exc:
                warnings.warn(
                    f"Failed to read file size; treating it as 0 bytes: {path} ({exc})",
                    RuntimeWarning,
                    stacklevel=2,
                )
                total_bytes += 0
            if (total_bytes / (1024 * 1024)) > max_total_mb:
                exceeded = True
                break
    return total_files, total_bytes / (1024 * 1024), exceeded


def guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in RAW_MIME_ALLOWLIST:
        return RAW_MIME_ALLOWLIST[ext]
    if ext in AUDIO_MIME_ALLOWLIST:
        return AUDIO_MIME_ALLOWLIST[ext]
    if ext in DOC_MIME_ALLOWLIST:
        return DOC_MIME_ALLOWLIST[ext]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def detect_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return MEDIA_IMAGE
    if ext in AUDIO_EXTS:
        return MEDIA_AUDIO
    if ext in PDF_EXTS:
        return MEDIA_PDF
    if ext in DOCX_EXTS:
        return MEDIA_DOCX
    if ext in DOC_EXTS:
        return MEDIA_DOC
    if ext in PPTX_EXTS:
        return MEDIA_PPTX
    if ext in PPT_EXTS:
        return MEDIA_PPT
    return ""
