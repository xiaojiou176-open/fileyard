from __future__ import annotations

import os
import sys
import types


def install_apply_changes_test_compat() -> None:
    from packages.application import apply_command as _apply_command
    from packages.application import apply_safety_helpers as _apply_safety
    from packages.application import rollback_command as _rollback_command
    from packages.application.reporting import write_report
    from packages.domain import rollback_integrity as _rollback_integrity
    from packages.infrastructure.manifest_store import iter_jsonl_chunks, read_jsonl, write_jsonl_line
    from packages.observability.logging_utils import log_event

    compat = types.ModuleType("packages.application.apply_changes")
    compat.logging = __import__("logging")
    compat._apply_command = _apply_command
    compat.Path = _apply_command.Path
    compat.dt = _apply_command.dt
    compat.log_event = log_event
    compat.sha1_file = _apply_command.sha1_file
    compat.read_jsonl = read_jsonl
    compat.iter_jsonl_chunks = iter_jsonl_chunks
    compat.write_jsonl_line = write_jsonl_line
    compat.write_report = write_report
    compat.safe_join = _apply_command.safe_join
    compat.resolve_fsync_interval = _apply_command.resolve_fsync_interval
    compat._CRASH_POINTS = _apply_command._CRASH_POINTS
    compat._is_test_hooks_enabled = _apply_command._is_test_hooks_enabled
    compat.build_destination = _apply_command.build_destination
    compat._safe_move_with_verification = _apply_safety._safe_move_with_verification
    compat._is_filesystem_root = _apply_safety._is_filesystem_root
    compat._next_overwrite_backup_path = _apply_safety._next_overwrite_backup_path
    compat._preserve_crash_file = _apply_safety._preserve_crash_file
    compat._is_valid_jsonl_file = _apply_safety._is_valid_jsonl_file
    compat._resolve_if_exists = _apply_safety._resolve_if_exists
    compat.shutil = _apply_safety.shutil
    compat._ROLLBACK_SIG_KEY = _rollback_integrity.ROLLBACK_SIG_KEY
    compat._build_rollback_from_manifest = _rollback_integrity._build_rollback_from_manifest
    compat._normalize_run_id = _rollback_integrity._normalize_run_id
    compat._has_strong_rollback_signing_key = _rollback_integrity._has_strong_rollback_signing_key
    compat._sign_rollback_record = _rollback_integrity._sign_rollback_record
    compat._verify_rollback_record = _rollback_integrity._verify_rollback_record

    def _is_within_root(path, root):
        try:
            path_norm = os.path.normcase(os.path.normpath(str(path.resolve())))
            root_norm = os.path.normcase(os.path.normpath(str(root.resolve())))
            return path_norm == root_norm or path_norm.startswith(root_norm + os.sep)
        except Exception as exc:  # pragma: no cover - tests-only compatibility
            compat.log_event(
                compat.logging.getLogger("fileyard"),
                compat.logging.WARNING,
                "path_boundary_check_failed",
                "Path boundary check failed during canonicalization",
                error_type=type(exc).__name__,
                error_message=str(exc),
                path_name=path.name,
                root_name=root.name,
            )
            return False

    def _resolve_apply_crash_inject(args):
        raw = str(getattr(args, "crash_inject", "") or os.environ.get("FILEYARD_APPLY_CRASH_AT", "")).strip()
        crash = raw.lower().replace("-", "_")
        if not crash:
            return ""
        if not compat._is_test_hooks_enabled():
            raise SystemExit("crash_inject is available only in test mode")
        if crash not in compat._CRASH_POINTS:
            raise SystemExit(f"Unknown crash_inject: {crash}")
        return crash

    def cmd_apply(args):
        _apply_command.log_event = compat.log_event
        _apply_command.sha1_file = compat.sha1_file
        _apply_command.read_jsonl = compat.read_jsonl
        _apply_command.iter_jsonl_chunks = compat.iter_jsonl_chunks
        _apply_command.write_jsonl_line = compat.write_jsonl_line
        _apply_command.write_report = compat.write_report
        _apply_command.safe_join = compat.safe_join
        _apply_command.build_destination = compat.build_destination
        _apply_command.resolve_fsync_interval = compat.resolve_fsync_interval
        _apply_command._is_test_hooks_enabled = compat._is_test_hooks_enabled
        _apply_command._preserve_crash_file = compat._preserve_crash_file
        _apply_safety.shutil = compat.shutil
        _apply_command.cmd_apply(args)

    def cmd_rollback(args):
        _rollback_command.log_event = compat.log_event
        _rollback_command.read_jsonl = compat.read_jsonl
        _rollback_command.cmd_rollback(args)

    compat._is_within_root = _is_within_root
    compat._resolve_apply_crash_inject = _resolve_apply_crash_inject
    compat.cmd_apply = cmd_apply
    compat.cmd_rollback = cmd_rollback

    import packages.application as application_pkg

    sys.modules["packages.application.apply_changes"] = compat
    application_pkg.apply_changes = compat
