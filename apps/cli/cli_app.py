# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from apps.cli import cli_config_schema as _cli_config_schema
from apps.cli.cli_config_schema import _ALLOWED_CONFIG, _CONFIG_TYPE_RULES
from apps.cli.cli_parser import build_parser, collect_lock_targets
from packages.application.analyze_media import cmd_analyze
from packages.application.apply_command import cmd_apply
from packages.application.reporting import cmd_report
from packages.application.rollback_command import cmd_rollback
from packages.domain.core_utils import acquire_file_lock, new_run_id, release_file_lock
from packages.domain.normalization import normalize_categories
from packages.domain.pipeline_config import (
    DEFAULT_CATEGORIES,
    DEFAULT_LOG_JSON,
    DEFAULT_LOG_LEVEL,
    ErrorCode,
)
from packages.domain.strategy_pack_registry import strategy_pack_by_id
from packages.infrastructure.config_loader import get_config_value, load_config, validate_config
from packages.infrastructure.runtime_env_store import (
    read_runtime_env_value as _shared_read_runtime_env_value,
)
from packages.infrastructure.runtime_env_store import (
    resolve_env_prefer_runtime_env as _shared_resolve_env_prefer_runtime_env,
)
from packages.infrastructure.runtime_env_store import (
    runtime_env_file as _shared_runtime_env_file,
)
from packages.observability.logging_utils import log_event, set_log_context_defaults, setup_logger
from packages.observability.run_bundle import finalize_run_bundle, initialize_run_bundle

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPT_ROOT.parent
_CRASH_POINTS = {
    "after_move_before_manifest_commit",
    "after_manifest_before_rollback_commit",
    "after_rollback_before_finalize",
}

_is_bool = _cli_config_schema._is_bool
_is_int = _cli_config_schema._is_int
_is_number = _cli_config_schema._is_number
_is_str_or_str_list = _cli_config_schema._is_str_or_str_list


def _is_test_hooks_enabled() -> bool:
    return os.environ.get("FILEMAN_ENABLE_TEST_HOOKS", "") == "1" or bool(os.environ.get("PYTEST_CURRENT_TEST", ""))


def _default_report_out() -> str:
    workspace_root = Path(os.environ.get("FILEMAN_WORKSPACE_ROOT", "~/.fileman/workspaces/default")).expanduser()
    return str(workspace_root / ".fileman" / "artifacts" / "report" / "report_summary.json")


DEFAULT_REPORT_OUT = _default_report_out()


def _parse_categories(raw) -> list[str]:
    if not raw:
        return list(DEFAULT_CATEGORIES)
    if isinstance(raw, (list, tuple)):
        return normalize_categories(raw)
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    return normalize_categories(parts)


def _runtime_env_file() -> Path:
    return _shared_runtime_env_file()


def _read_runtime_env_value(name: str) -> str:
    return _shared_read_runtime_env_value(name)


def _resolve_env_prefer_runtime_env(name: str, default: str = "") -> str:
    return _shared_resolve_env_prefer_runtime_env(name, default)


def _argument_error(parser: argparse.ArgumentParser, message: str) -> None:
    parser.exit(2, f"Argument error: {message}\n")


def _require_non_empty_arg(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    cmd: str,
    arg_name: str,
) -> None:
    value = getattr(args, arg_name, "")
    if str(value or "").strip():
        return
    _argument_error(parser, f"{cmd} requires --{arg_name.replace('_', '-')}")


def _resolved_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _resolve_optional_path(value: str) -> Path | None:
    if not str(value or "").strip():
        return None
    return _resolved_path(value)


def _add_output_path(path_map: dict[str, str], parser: argparse.ArgumentParser, name: str, path: Path) -> None:
    existed = path_map.get(str(path))
    if existed is not None:
        _argument_error(
            parser,
            f"Output path conflict: {name} and {existed} resolve to the same path {path}",
        )
    path_map[str(path)] = name


def _validate_output_path_conflicts(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.cmd == "analyze":
        path_map: dict[str, str] = {}
        manifest_path = _resolved_path(args.manifest)
        _add_output_path(path_map, parser, "manifest", manifest_path)
        csv_path = _resolve_optional_path(getattr(args, "csv", ""))
        if csv_path is not None:
            _add_output_path(path_map, parser, "csv", csv_path)
        report_path = _resolve_optional_path(getattr(args, "report", ""))
        if report_path is not None:
            _add_output_path(path_map, parser, "report", report_path)
        return

    if args.cmd == "apply":
        manifest_path = _resolved_path(args.manifest)
        out_manifest_path = _resolve_optional_path(getattr(args, "out_manifest", "")) or manifest_path
        report_path = _resolve_optional_path(getattr(args, "report", ""))
        rollback_manifest = _resolve_optional_path(getattr(args, "rollback_manifest", ""))
        apply_path_map: dict[str, str] = {str(manifest_path): "manifest"}
        if str(out_manifest_path) != str(manifest_path):
            _add_output_path(apply_path_map, parser, "out_manifest", out_manifest_path)
        if report_path is not None:
            _add_output_path(apply_path_map, parser, "report", report_path)
        if rollback_manifest is not None:
            _add_output_path(apply_path_map, parser, "rollback_manifest", rollback_manifest)
        return

    if args.cmd == "report":
        manifest_path = _resolved_path(args.manifest)
        out_path = _resolved_path(args.out)
        if manifest_path == out_path:
            _argument_error(parser, f"Output path conflict: out must not match manifest ({out_path})")


def main() -> None:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default="")
    pre_args, _ = pre_parser.parse_known_args()

    config = {}
    if pre_args.config:
        try:
            config = load_config(Path(pre_args.config).expanduser())
        except Exception as exc:
            logger = setup_logger(DEFAULT_LOG_LEVEL, DEFAULT_LOG_JSON)
            log_event(
                logger,
                logging.ERROR,
                "config_load_fail",
                f"Failed to load config: {exc}",
                error_code=ErrorCode.CONFIG_INVALID.value,
            )
            raise SystemExit(f"Failed to load config: {exc}") from exc

    def _cfg(section: str, key: str, default):
        value = get_config_value(config, section, key, default)
        active_pack_id = str(get_config_value(config, "global", "active_strategy_pack_id", "") or "").strip()
        active_pack = strategy_pack_by_id(REPO_ROOT, active_pack_id) if active_pack_id else None
        if section == "analyze" and active_pack is not None:
            if key == "model" and (value == "" or value == default):
                return active_pack.model or value
            if key == "categories" and (value == "" or value == default):
                return list(active_pack.categories) if active_pack.categories else value
            if key == "workers" and value == default:
                return active_pack.workers or value
        return value

    parser = build_parser(
        _cfg,
        pre_args.config,
        _resolve_env_prefer_runtime_env,
        {
            "analyze": cmd_analyze,
            "apply": cmd_apply,
            "rollback": cmd_rollback,
            "report": cmd_report,
        },
        DEFAULT_REPORT_OUT,
    )

    args = parser.parse_args()
    run_bundle_active = False
    run_bundle_command = str(getattr(args, "cmd", "") or "")

    logger = setup_logger(args.log_level, args.log_json)
    set_log_context_defaults(
        trace_id=_cfg("global", "trace_id", ""),
        request_id=_cfg("global", "request_id", ""),
        session_id=_cfg("global", "session_id", ""),
        user_id=_cfg("global", "user_id", ""),
    )
    warnings, errors = validate_config(
        config,
        _ALLOWED_CONFIG,
        _CONFIG_TYPE_RULES,
        strict_unknown=True,
    )
    for warning in warnings:
        log_event(
            logger,
            logging.WARNING,
            "config_warning",
            warning,
            error_code=ErrorCode.CONFIG_UNKNOWN_KEY.value,
        )
    if errors:
        for err in errors:
            normalized_err = err
            err_code = ErrorCode.CONFIG_INVALID.value
            if err.startswith("未知配置分组"):
                err_code = ErrorCode.CONFIG_UNKNOWN_KEY.value
                normalized_err = err.replace("未知配置分组", "Unknown config section", 1)
            elif err.startswith("未知配置项"):
                err_code = ErrorCode.CONFIG_UNKNOWN_KEY.value
                normalized_err = err.replace("未知配置项", "Unknown config key", 1)
            elif err.startswith("Unknown config section") or err.startswith("Unknown config key"):
                err_code = ErrorCode.CONFIG_UNKNOWN_KEY.value
            elif err.startswith("配置项类型非法"):
                err_code = ErrorCode.CONFIG_TYPE_INVALID.value
                normalized_err = err.replace("配置项类型非法", "Invalid config value type", 1)
            elif err.startswith("Invalid config value type"):
                err_code = ErrorCode.CONFIG_TYPE_INVALID.value
            log_event(
                logger,
                logging.ERROR,
                "config_error",
                normalized_err,
                error_code=err_code,
            )
        raise SystemExit("Config validation failed")
    if args.cmd in {"analyze", "apply", "rollback", "report"}:
        if not str(getattr(args, "run_id", "") or "").strip():
            setattr(args, "run_id", new_run_id(args.cmd))
        initialize_run_bundle(str(args.run_id), args.cmd)
        run_bundle_active = True
        _require_non_empty_arg(parser, args, args.cmd, "manifest")
    _validate_output_path_conflicts(parser, args)
    if args.cmd == "apply":
        crash_inject = str(getattr(args, "crash_inject", "") or "").strip().lower().replace("-", "_")
        if crash_inject:
            if crash_inject not in _CRASH_POINTS:
                _argument_error(parser, f"Unknown --crash-inject value: {crash_inject}")
            if not _is_test_hooks_enabled():
                _argument_error(parser, "--crash-inject is only available in test mode")

    if args.cmd in {"analyze", "apply"}:
        args.categories = _parse_categories(args.categories)

    args.api_key = _resolve_env_prefer_runtime_env("GEMINI_API_KEY", "")

    lock_targets = collect_lock_targets(args, _resolved_path)

    lock_records: list[tuple[Path, int | None]] = []
    for target in sorted(lock_targets):
        lock_path = Path(target + ".lock")
        try:
            lock_fd = acquire_file_lock(lock_path)
            lock_records.append((lock_path, lock_fd))
        except Exception as exc:
            for acquired_path, acquired_fd in reversed(lock_records):
                release_file_lock(acquired_path, acquired_fd)
            log_event(
                logger,
                logging.ERROR,
                "manifest_lock_fail",
                f"Failed to acquire task lock: {exc}",
                error_code=ErrorCode.MANIFEST_UPDATE_FAIL.value,
                path=str(lock_path),
            )
            raise SystemExit(f"Failed to acquire task lock: {exc}") from exc

    try:
        args.func(args)
        if run_bundle_active:
            finalize_run_bundle(str(args.run_id), run_bundle_command, "success")
    except BaseException:
        if run_bundle_active:
            finalize_run_bundle(str(args.run_id), run_bundle_command, "fail")
        raise
    finally:
        for lock_path, release_fd in reversed(lock_records):
            release_file_lock(lock_path, release_fd)
