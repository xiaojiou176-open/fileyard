# -*- coding: utf-8 -*-
from __future__ import annotations

import errno
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from packages.domain.pipeline_config import KEY_NEW_PATH, KEY_PATH, ErrorCode
from packages.domain.rollback_integrity import ROLLBACK_SIG_KEY


@dataclass
class RollbackStats:
    restored: int = 0
    failed: int = 0
    skipped_missing_src: int = 0
    skipped_existing_dst: int = 0
    skipped_invalid: int = 0
    rollback_candidates: int = 0
    strict_valid_candidates: int = 0
    manifest_run_id: str | None = None


RollbackDeps = dict[str, Callable[..., Any] | Any]


def resolve_allowed_roots(
    args: Any,
    *,
    logger: Any,
    run_id: str,
    deps: RollbackDeps,
) -> list[Path]:
    allowed_root_raw = str(getattr(args, "allowed_root", "") or "").strip()
    if not allowed_root_raw:
        deps["log_event"](
            logger,
            logging.ERROR,
            "rollback_allowed_root_required",
            "rollback requires --allowed-root (comma-separated roots are allowed)",
            run_id=run_id,
            error_code=ErrorCode.INPUT_ROOT_INVALID.value,
        )
        raise SystemExit("rollback requires --allowed-root")

    allowed_roots: list[Path] = []
    for part in [p.strip() for p in allowed_root_raw.split(",") if p.strip()]:
        try:
            root_path = Path(part).expanduser().resolve()
            if deps["is_filesystem_root"](root_path):
                deps["log_event"](
                    logger,
                    logging.ERROR,
                    "rollback_allowed_root_forbidden",
                    "rollback refuses to use the filesystem root as --allowed-root",
                    run_id=run_id,
                    allowed_root=str(root_path),
                    error_code=ErrorCode.INPUT_ROOT_INVALID.value,
                )
                raise SystemExit("rollback refuses to use the filesystem root as --allowed-root")
            allowed_roots.append(root_path)
        except SystemExit:
            raise
        except Exception as exc:
            deps["log_event"](
                logger,
                logging.ERROR,
                "rollback_allowed_root_invalid",
                f"Failed to resolve allowed_root: {exc}",
                run_id=run_id,
                error_code=ErrorCode.INPUT_ROOT_INVALID.value,
            )
            raise SystemExit(f"Failed to resolve allowed_root: {exc}") from exc

    if not allowed_roots:
        deps["log_event"](
            logger,
            logging.ERROR,
            "rollback_allowed_root_required",
            "rollback requires --allowed-root (comma-separated roots are allowed)",
            run_id=run_id,
            error_code=ErrorCode.INPUT_ROOT_INVALID.value,
        )
        raise SystemExit("rollback requires --allowed-root")
    return allowed_roots


def load_rollback_rows(
    manifest_path: Path,
    *,
    logger: Any,
    run_id: str,
    deps: RollbackDeps,
) -> Iterable[dict[str, Any]]:
    try:
        return deps["read_jsonl"](manifest_path, validate=True)
    except Exception as exc:
        deps["log_event"](
            logger,
            logging.ERROR,
            "manifest_read_fail",
            f"Failed to read manifest: {exc}",
            error_code=ErrorCode.MANIFEST_READ_FAIL.value,
            run_id=run_id,
        )
        raise SystemExit(f"Failed to read manifest: {exc}") from exc


def process_rollback_rows(
    rows: Iterable[dict[str, Any]],
    *,
    args: Any,
    logger: Any,
    run_id: str,
    allowed_roots: list[Path],
    strict_integrity: bool,
    deps: RollbackDeps,
) -> RollbackStats:
    stats = RollbackStats()
    for row in rows:
        _process_rollback_row(
            row,
            args=args,
            logger=logger,
            run_id=run_id,
            allowed_roots=allowed_roots,
            strict_integrity=strict_integrity,
            stats=stats,
            deps=deps,
        )
    return stats


def _process_rollback_row(
    row: dict[str, Any],
    *,
    args: Any,
    logger: Any,
    run_id: str,
    allowed_roots: list[Path],
    strict_integrity: bool,
    stats: RollbackStats,
    deps: RollbackDeps,
) -> None:
    src = row.get(KEY_NEW_PATH, "")
    dst = row.get(KEY_PATH, "")
    if src and dst:
        stats.rollback_candidates += 1

    if strict_integrity:
        row_run_id = str(row.get("run_id", "") or "")
        row_sig = str(row.get(ROLLBACK_SIG_KEY, "") or "").strip().lower()
        if not row_run_id:
            stats.skipped_invalid += 1
            deps["log_event"](logger, logging.INFO, "rollback_skip_invalid_row", "Skip rollback row: missing run_id", run_id=run_id)
            return
        if not row_sig:
            stats.skipped_invalid += 1
            deps["log_event"](
                logger,
                logging.INFO,
                "rollback_skip_invalid_row",
                "Skip rollback row: missing integrity signature",
                run_id=run_id,
                row_run_id=row_run_id,
            )
            return
        if stats.manifest_run_id is None:
            stats.manifest_run_id = row_run_id
        elif row_run_id != stats.manifest_run_id:
            stats.skipped_invalid += 1
            deps["log_event"](
                logger,
                logging.INFO,
                "rollback_skip_invalid_row",
                "Skip rollback row: run_id mismatch",
                run_id=run_id,
                row_run_id=row_run_id,
                expected_run_id=stats.manifest_run_id,
            )
            return
        if stats.manifest_run_id is not None and not deps["verify_rollback_record"](row, stats.manifest_run_id):
            stats.skipped_invalid += 1
            deps["log_event"](
                logger,
                logging.INFO,
                "rollback_skip_invalid_row",
                "Skip rollback row: integrity signature invalid",
                run_id=run_id,
                row_run_id=row_run_id,
            )
            return

    if not src or not dst:
        stats.skipped_invalid += 1
        deps["log_event"](
            logger,
            logging.INFO,
            "rollback_skip_invalid_row",
            "Skip rollback row: missing path/new_path",
            run_id=run_id,
        )
        return

    if strict_integrity:
        stats.strict_valid_candidates += 1

    src_path = Path(src).expanduser()
    dst_path = Path(dst).expanduser()
    try:
        src_resolved = src_path.resolve()
        dst_resolved = dst_path.resolve()
    except Exception as exc:
        stats.skipped_invalid += 1
        deps["log_event"](
            logger,
            logging.INFO,
            "rollback_skip_invalid_row",
            f"Skip rollback row: path resolve failed: {exc}",
            src=str(src_path),
            dst=str(dst_path),
            run_id=run_id,
        )
        return

    src_in_allowed = any(deps["is_within_root"](src_resolved, root) for root in allowed_roots)
    dst_in_allowed = any(deps["is_within_root"](dst_resolved, root) for root in allowed_roots)
    if not src_in_allowed or not dst_in_allowed:
        deps["log_event"](
            logger,
            logging.INFO,
            "rollback_skip_outside_allowed_root",
            "Skip rollback row: source or target is outside allowed_root",
            src=str(src_resolved),
            dst=str(dst_resolved),
            allowed_root=",".join(str(p) for p in allowed_roots),
            run_id=run_id,
        )
        stats.skipped_invalid += 1
        return

    if not src_resolved.exists():
        stats.skipped_missing_src += 1
        deps["log_event"](
            logger,
            logging.INFO,
            "rollback_skip_missing_source",
            "Skip rollback row: source missing",
            path=str(src_resolved),
            run_id=run_id,
        )
        return

    if dst_resolved.exists() and not args.overwrite:
        stats.skipped_existing_dst += 1
        deps["log_event"](
            logger,
            logging.INFO,
            "rollback_skip_target_exists",
            "Skip rollback row: target exists and overwrite is false",
            path=str(dst_resolved),
            run_id=run_id,
        )
        return

    _execute_rollback_move(
        src_path=src_path,
        dst_path=dst_path,
        src_resolved=src_resolved,
        dst_resolved=dst_resolved,
        args=args,
        logger=logger,
        run_id=run_id,
        stats=stats,
        deps=deps,
    )


def _execute_rollback_move(
    *,
    src_path: Path,
    dst_path: Path,
    src_resolved: Path,
    dst_resolved: Path,
    args: Any,
    logger: Any,
    run_id: str,
    stats: RollbackStats,
    deps: RollbackDeps,
) -> None:
    move_target = dst_resolved
    backup_path: Path | None = None
    try:
        if args.dry_run:
            deps["log_event"](logger, logging.INFO, "dry_run", f"DRY  {src_resolved} -> {move_target}")
        else:
            latest_src = src_path.resolve()
            latest_dst = dst_path.resolve()
            if latest_src != src_resolved or latest_dst != dst_resolved:
                raise RuntimeError("Rollback paths changed before execution")
            move_target.parent.mkdir(parents=True, exist_ok=True)
            if dst_resolved.exists() and args.overwrite:
                backup_path = deps["next_overwrite_backup_path"](dst_resolved)
                dst_resolved.replace(backup_path)
            try:
                src_resolved.replace(move_target)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                shutil.move(str(src_resolved), str(move_target))
            stats.restored += 1
            deps["log_event"](logger, logging.INFO, "move", f"MOVE {src_resolved} -> {move_target}")
            if backup_path is not None and backup_path.exists():
                try:
                    if backup_path.is_dir():
                        shutil.rmtree(backup_path)
                    else:
                        backup_path.unlink()
                except Exception as cleanup_exc:
                    deps["log_event"](
                        logger,
                        logging.WARNING,
                        "rollback_overwrite_backup_preserved",
                        f"Overwrite backup preserved: {cleanup_exc}",
                        path=str(backup_path),
                        run_id=run_id,
                    )
    except Exception as exc:
        if not args.dry_run and backup_path is not None and backup_path.exists() and not move_target.exists():
            try:
                backup_path.replace(move_target)
            except Exception as restore_exc:
                deps["log_event"](
                    logger,
                    logging.WARNING,
                    "rollback_overwrite_restore_fail",
                    f"Failed to restore original destination after overwrite failure: {restore_exc}",
                    path=str(move_target),
                    backup=str(backup_path),
                    run_id=run_id,
                )
        stats.failed += 1
        deps["log_event"](
            logger,
            logging.ERROR,
            "rollback_fail",
            f"Rollback failed: {exc}",
            path=str(src_resolved),
            error_code=ErrorCode.ROLLBACK_FAIL.value,
            exception=exc,
            run_id=run_id,
        )
