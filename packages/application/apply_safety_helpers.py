# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
from pathlib import Path

from packages.infrastructure.manifest_store import read_jsonl
from packages.observability.logging_utils import log_event


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path_norm = os.path.normcase(os.path.normpath(str(path.resolve())))
        root_norm = os.path.normcase(os.path.normpath(str(root.resolve())))
        return path_norm == root_norm or path_norm.startswith(root_norm + os.sep)
    except Exception as exc:
        # Fail-closed: if canonicalization fails, treat as outside the root.
        log_event(
            logging.getLogger("fileyard"),
            logging.WARNING,
            "path_boundary_check_failed",
            "Path boundary check failed during canonicalization",
            error_type=type(exc).__name__,
            error_message=str(exc),
            path_name=path.name,
            root_name=root.name,
        )
        return False


def _safe_move_with_verification(src: Path, dst: Path, src_resolved: Path) -> None:
    """Safely move a file with path verification to mitigate TOCTOU race conditions."""
    latest_src = src.resolve()
    if latest_src != src_resolved:
        raise RuntimeError("Source file path changed before execution")
    if not src_resolved.exists():
        raise RuntimeError("Source file disappeared before the move")
    if not src_resolved.is_file():
        raise RuntimeError("Source path is not a file")
    shutil.move(str(src_resolved), str(dst))


def _is_filesystem_root(path: Path) -> bool:
    return path.parent == path


def _next_overwrite_backup_path(path: Path) -> Path:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.overwrite-backup-{ts}")
    idx = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.overwrite-backup-{ts}-{idx}")
        idx += 1
    return candidate


def _preserve_crash_file(path: Path) -> Path:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.crash-{ts}")
    idx = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.crash-{ts}-{idx}")
        idx += 1
    path.replace(candidate)
    return candidate


def _is_valid_jsonl_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        for _ in read_jsonl(path, validate=True):
            pass
        return True
    except Exception:
        return False


def _resolve_if_exists(path_text: str) -> Path | None:
    candidate = Path(path_text).expanduser()
    try:
        resolved = candidate.resolve()
    except Exception:
        return None
    if not resolved.exists():
        return None
    return resolved
