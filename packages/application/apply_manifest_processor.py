# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from packages.domain.pipeline_config import (
    KEY_ERROR,
    KEY_HASH8,
    KEY_INPUT_ROOT,
    KEY_MEDIA_TYPE,
    KEY_NEW_PATH,
    KEY_PATH,
    KEY_SHA1,
    KEY_STATUS_REASON,
    ErrorCode,
    RowStatus,
)


@dataclass
class ApplyPathPolicy:
    input_root: Path | None
    trust_manifest_input_root: bool
    manifest_root_allowlist: list[Path]


@dataclass
class ApplyRuntime:
    args: Any
    logger: Any
    output_root: Path
    categories: list[str]
    path_policy: ApplyPathPolicy


@dataclass
class ApplyProcessingState:
    seen_sha1: dict[str, Path] = field(default_factory=dict)
    moves: int = 0


ApplyDeps = dict[str, Callable[..., Any] | Any]


def resolve_apply_path_policy(
    args: Any,
    *,
    fail_fn: Callable[..., None],
    is_filesystem_root_fn: Callable[[Path], bool],
) -> ApplyPathPolicy:
    input_root = None
    trust_manifest_input_root = bool(getattr(args, "trust_manifest_input_root", False))
    manifest_root_allowlist: list[Path] = []
    manifest_root_allowlist_raw = str(getattr(args, "manifest_input_root_allowlist", "") or "").strip()

    if args.input_root:
        try:
            input_root = Path(args.input_root).expanduser().resolve()
            if is_filesystem_root_fn(input_root):
                fail_fn(
                    ErrorCode.INPUT_ROOT_INVALID,
                    "input_root_too_broad",
                    "Input root must not be the filesystem root",
                    path=str(input_root),
                )
        except Exception as exc:
            fail_fn(
                ErrorCode.INPUT_ROOT_INVALID,
                "input_root_invalid",
                f"Failed to resolve input root: {exc}",
                path=str(args.input_root),
            )

    if manifest_root_allowlist_raw:
        for part in [p.strip() for p in manifest_root_allowlist_raw.split(",") if p.strip()]:
            try:
                resolved = Path(part).expanduser().resolve()
            except Exception as exc:
                fail_fn(
                    ErrorCode.INPUT_ROOT_INVALID,
                    "manifest_root_allowlist_invalid",
                    f"Failed to resolve manifest input-root allowlist: {exc}",
                    path=part,
                )
            if is_filesystem_root_fn(resolved):
                fail_fn(
                    ErrorCode.INPUT_ROOT_INVALID,
                    "manifest_root_allowlist_too_broad",
                    "Manifest input-root allowlist must not include the filesystem root",
                    path=str(resolved),
                )
            manifest_root_allowlist.append(resolved)

    if input_root is None and not trust_manifest_input_root:
        fail_fn(
            ErrorCode.INPUT_ROOT_INVALID,
            "input_root_required",
            "apply requires --input-root; to trust manifest input_root values, explicitly set --trust-manifest-input-root",
        )
    if input_root is None and trust_manifest_input_root and not manifest_root_allowlist:
        fail_fn(
            ErrorCode.INPUT_ROOT_INVALID,
            "manifest_input_root_allowlist_required",
            "--trust-manifest-input-root requires --manifest-input-root-allowlist",
        )

    return ApplyPathPolicy(
        input_root=input_root,
        trust_manifest_input_root=trust_manifest_input_root,
        manifest_root_allowlist=manifest_root_allowlist,
    )


def process_manifest_rows(
    manifest_path: Path,
    *,
    chunk_size: int,
    runtime: ApplyRuntime,
    state: ApplyProcessingState,
    emit_row: Callable[[dict[str, Any]], None],
    emit_rollback: Callable[[Path, Path, RowStatus, str], None],
    deps: ApplyDeps,
) -> None:
    for chunk in deps["iter_jsonl_chunks"](manifest_path, validate=True, chunk_size=chunk_size):
        for row in chunk:
            _process_manifest_row(
                row,
                runtime=runtime,
                state=state,
                emit_row=emit_row,
                emit_rollback=emit_rollback,
                deps=deps,
            )


def _process_manifest_row(
    row: dict[str, Any],
    *,
    runtime: ApplyRuntime,
    state: ApplyProcessingState,
    emit_row: Callable[[dict[str, Any]], None],
    emit_rollback: Callable[[Path, Path, RowStatus, str], None],
    deps: ApplyDeps,
) -> None:
    args = runtime.args
    logger = runtime.logger
    output_root = runtime.output_root
    categories = runtime.categories
    path_policy = runtime.path_policy

    deps["ensure_status"](row)
    raw_path = str(row.get(KEY_PATH, "") or "")
    if not raw_path:
        deps["log_event"](
            logger,
            logging.WARNING,
            "manifest_row_invalid",
            "manifest row is missing the path field",
        )
        deps["set_error"](row, ErrorCode.MANIFEST_ROW_INVALID, "manifest row is missing the path field")
        emit_row(row)
        return

    sha1 = str(row.get(KEY_SHA1, "") or "")
    if row.get(KEY_ERROR):
        if bool(getattr(args, "retry_errors", False)):
            deps["clear_error"](row)
            row.pop(KEY_STATUS_REASON, None)
        else:
            deps["set_status"](row, RowStatus.ERROR, status_reason="existing_error")
            emit_row(row)
            return

    if bool(getattr(args, "resume", True)):
        new_path = str(row.get(KEY_NEW_PATH, "") or "")
        if new_path:
            resume_dst_path = deps["resolve_if_exists"](new_path)
            if resume_dst_path is not None:
                if not deps["is_within_root"](resume_dst_path, output_root):
                    deps["set_error"](row, ErrorCode.INPUT_ROOT_MISMATCH, "resume target is outside the output root")
                    emit_row(row)
                    return
                if getattr(args, "verify_sha1", False) and sha1:
                    try:
                        actual_dst_sha1 = deps["sha1_file"](resume_dst_path)
                    except Exception as exc:
                        deps["set_error"](row, ErrorCode.HASH_FAIL, f"resume digest verification failed: {exc}")
                        emit_row(row)
                        return
                    if actual_dst_sha1 != sha1:
                        deps["set_error"](row, ErrorCode.HASH_MISMATCH, f"resume digest mismatch: {sha1} != {actual_dst_sha1}")
                        emit_row(row)
                        return
                status = RowStatus.DUPLICATE if row.get("dedupe_of") else RowStatus.APPLIED
                deps["set_status"](row, status, status_reason="resume_skip")
                emit_row(row)
                return

    src = Path(raw_path)
    try:
        src_resolved = src.resolve()
    except Exception:
        src_resolved = src
    if not src_resolved.exists():
        deps["set_error"](row, ErrorCode.SOURCE_MISSING, "source file does not exist")
        emit_row(row)
        return

    root_for_row = path_policy.input_root
    if root_for_row is None:
        raw_root = str(row.get(KEY_INPUT_ROOT, "") or "")
        if raw_root:
            root_for_row = Path(raw_root).expanduser()
        elif path_policy.trust_manifest_input_root:
            deps["set_error"](row, ErrorCode.INPUT_ROOT_INVALID, "manifest row is missing input_root; path boundaries cannot be verified")
            emit_row(row)
            return

    if root_for_row is not None:
        try:
            root_resolved = root_for_row.resolve()
            if deps["is_filesystem_root"](root_resolved):
                deps["set_error"](row, ErrorCode.INPUT_ROOT_INVALID, "Input root must not be the filesystem root")
                emit_row(row)
                return
            if path_policy.input_root is None and path_policy.trust_manifest_input_root:
                if not any(deps["is_within_root"](root_resolved, allowed) for allowed in path_policy.manifest_root_allowlist):
                    deps["set_error"](row, ErrorCode.INPUT_ROOT_INVALID, "manifest input_root is outside the allowlist")
                    emit_row(row)
                    return
            if not deps["is_within_root"](src_resolved, root_resolved):
                deps["set_error"](row, ErrorCode.INPUT_ROOT_MISMATCH, "source file is outside the input root")
                emit_row(row)
                return
        except Exception as exc:
            deps["set_error"](row, ErrorCode.INPUT_ROOT_INVALID, f"input root validation failed: {exc}")
            emit_row(row)
            return

    if getattr(args, "verify_sha1", False):
        if not sha1:
            deps["set_error"](row, ErrorCode.HASH_MISSING, "missing sha1; verification is unavailable")
            emit_row(row)
            return
        try:
            actual_sha1 = deps["sha1_file"](src_resolved)
        except Exception as exc:
            deps["set_error"](row, ErrorCode.HASH_FAIL, f"sha1 verification failed: {exc}")
            emit_row(row)
            return
        if actual_sha1 != sha1:
            deps["set_error"](row, ErrorCode.HASH_MISMATCH, f"sha1 mismatch: {sha1} != {actual_sha1}")
            emit_row(row)
            return

    if getattr(args, "dedupe", False) and sha1 and sha1 in state.seen_sha1:
        try:
            dup_folder = deps["safe_join"](output_root, "duplicates", row.get(KEY_HASH8, sha1[:8]))
            dup_folder.mkdir(parents=True, exist_ok=True)
            dst = deps["unique_path"](dup_folder / src_resolved.name)
        except Exception as exc:
            deps["set_error"](row, ErrorCode.DEDUPE_PATH_FAIL, f"dedupe path error: {exc}")
            emit_row(row)
            return

        try:
            if getattr(args, "dry_run", False):
                deps["log_event"](
                    logger,
                    logging.INFO,
                    "dry_run",
                    "Dry-run duplicate move",
                    src=str(src_resolved),
                    dst=str(dst),
                )
                deps["set_status"](row, RowStatus.SKIPPED, status_reason="dry_run_dedupe")
            else:
                deps["safe_move_with_verification"](src, dst, src_resolved)
                state.moves += 1
                deps["log_event"](
                    logger,
                    logging.INFO,
                    "move",
                    "File moved",
                    src=str(src_resolved),
                    dst=str(dst),
                )
                deps["set_status"](
                    row,
                    RowStatus.DUPLICATE,
                    applied_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
                )
                emit_rollback(src_resolved, dst, RowStatus.DUPLICATE, str(row.get(KEY_MEDIA_TYPE, "")))
            row[KEY_NEW_PATH] = str(dst)
            row["dedupe_of"] = str(state.seen_sha1[sha1])
        except Exception as exc:
            deps["set_error"](row, ErrorCode.DEDUPE_MOVE_FAIL, f"dedupe move error: {exc}")
        emit_row(row)
        return

    try:
        requested_new_path = str(row.get(KEY_NEW_PATH, "") or "").strip()
        if requested_new_path:
            candidate = Path(requested_new_path).expanduser()
            if candidate.is_absolute():
                dst = candidate.resolve()
                if not deps["is_within_root"](dst, output_root):
                    raise ValueError("requested destination is outside the output root")
            else:
                dst = deps["safe_join"](output_root, requested_new_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
        else:
            folder, filename = deps["build_destination"](row, output_root, categories)
            folder.mkdir(parents=True, exist_ok=True)
            dst = deps["unique_path"](folder / filename)
    except Exception as exc:
        deps["set_error"](row, ErrorCode.BUILD_DEST_FAIL, f"destination path error: {exc}")
        emit_row(row)
        return

    try:
        if getattr(args, "dry_run", False):
            deps["log_event"](
                logger,
                logging.INFO,
                "dry_run",
                "Dry-run move",
                src=str(src_resolved),
                dst=str(dst),
            )
            deps["set_status"](row, RowStatus.SKIPPED, status_reason="dry_run")
        else:
            deps["safe_move_with_verification"](src, dst, src_resolved)
            state.moves += 1
            deps["log_event"](
                logger,
                logging.INFO,
                "move",
                "File moved",
                src=str(src_resolved),
                dst=str(dst),
            )
            deps["set_status"](
                row,
                RowStatus.APPLIED,
                applied_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
            )
            emit_rollback(src_resolved, dst, RowStatus.APPLIED, str(row.get(KEY_MEDIA_TYPE, "")))
        row[KEY_NEW_PATH] = str(dst)
        if sha1:
            state.seen_sha1[sha1] = Path(row[KEY_NEW_PATH])
    except Exception as exc:
        deps["set_error"](row, ErrorCode.MOVE_FAIL, f"move error: {exc}")

    emit_row(row)
