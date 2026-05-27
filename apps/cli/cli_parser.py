# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Mapping

from packages.domain.pipeline_config import (
    DEFAULT_AI_TIMEOUT_S,
    DEFAULT_AUDIO_SEGMENT_COUNT,
    DEFAULT_AUDIO_SEGMENT_SECONDS,
    DEFAULT_AUDIO_SEGMENT_THRESHOLD_S,
    DEFAULT_AUDIO_TRANSCRIPT_MAX_CHARS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DOC_TEXT_MAX_CHARS,
    DEFAULT_DURABILITY,
    DEFAULT_INLINE_MAX_MB,
    DEFAULT_INPUT_DIR,
    DEFAULT_LOG_JSON,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MANIFEST_FSYNC_INTERVAL,
    DEFAULT_MAX_FILE_MB,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOTAL_MB,
    DEFAULT_RETRY_BASE_S,
    DEFAULT_RETRY_MAX_S,
    DEFAULT_SUBPROCESS_TIMEOUT_S,
    DEFAULT_WORKERS,
)
from packages.domain.time_naming import default_output_root

ConfigLookup = Callable[[str, str, Any], Any]
EnvResolver = Callable[[str, str], str]
PathResolver = Callable[[str], Path]


def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=argparse.SUPPRESS)
    parser.add_argument(
        "--log-level",
        default=argparse.SUPPRESS,
        help="Log level (DEBUG/INFO/WARNING/ERROR)",
    )
    parser.add_argument(
        "--log-json",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Enable JSON logs",
    )
    parser.add_argument(
        "--run-id",
        default=argparse.SUPPRESS,
        help="Override run id",
    )
    parser.add_argument(
        "--generator-version",
        default=argparse.SUPPRESS,
        help="Override generator version",
    )


def build_parser(
    cfg_value: ConfigLookup,
    config_path: str,
    resolve_env_prefer_runtime_env: EnvResolver,
    handlers: Mapping[str, Any],
    default_report_out: str,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("fileyard")
    parser.add_argument("--config", default=config_path, help="Config file (.toml/.yaml/.json)")
    parser.add_argument(
        "--log-level",
        default=cfg_value("global", "log_level", DEFAULT_LOG_LEVEL),
        help="Log level (DEBUG/INFO/WARNING/ERROR)",
    )
    parser.add_argument(
        "--log-json",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("global", "log_json", DEFAULT_LOG_JSON),
        help="Enable JSON logs",
    )
    parser.add_argument(
        "--run-id",
        default=cfg_value("global", "run_id", ""),
        help="Override run id",
    )
    parser.add_argument(
        "--generator-version",
        default=cfg_value("global", "generator_version", ""),
        help="Override generator version",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyze", help="Analyze media and write manifest")
    _add_shared_args(pa)
    pa.add_argument(
        "--input",
        default=str(cfg_value("analyze", "input", DEFAULT_INPUT_DIR)),
        help="Input folder (default: ~/.fileyard/workspaces/default/data/raw)",
    )
    pa.add_argument("--manifest", default=cfg_value("analyze", "manifest", ""), help="Output manifest .jsonl")
    pa.add_argument("--csv", default=cfg_value("analyze", "csv", ""), help="Optional CSV output path")
    pa.add_argument("--report", default=cfg_value("analyze", "report", ""), help="Optional report JSON output path")
    pa.add_argument(
        "--model",
        default=cfg_value("analyze", "model", resolve_env_prefer_runtime_env("GEMINI_MODEL", "")),
        help="Gemini model name",
    )
    pa.add_argument(
        "--categories",
        default=cfg_value("analyze", "categories", ""),
        help="Comma-separated category enum (product values are preserved as-is)",
    )
    pa.add_argument(
        "--durability",
        default=cfg_value("analyze", "durability", DEFAULT_DURABILITY),
        choices=["none", "batch", "sync"],
        help="Durability mode (none/batch/sync)",
    )
    pa.add_argument(
        "--fsync-interval",
        type=int,
        default=cfg_value("analyze", "fsync_interval", DEFAULT_MANIFEST_FSYNC_INTERVAL),
        help="Manifest fsync interval (0 disables)",
    )
    pa.add_argument(
        "--inline-max-mb",
        type=float,
        default=cfg_value("analyze", "inline_max_mb", DEFAULT_INLINE_MAX_MB),
        help="Max inline payload size before switching to Files API",
    )
    pa.add_argument(
        "--resize-max-side",
        type=int,
        default=cfg_value("analyze", "resize_max_side", 0),
        help="Optional JPEG resize max side for oversized inline payloads (0 disables)",
    )
    pa.add_argument(
        "--max-retries",
        type=int,
        default=cfg_value("analyze", "max_retries", DEFAULT_MAX_RETRIES),
        help="Max retries for Gemini API calls",
    )
    pa.add_argument(
        "--retry-base-s",
        type=float,
        default=cfg_value("analyze", "retry_base_s", DEFAULT_RETRY_BASE_S),
        help="Base seconds for exponential backoff",
    )
    pa.add_argument(
        "--retry-max-s",
        type=float,
        default=cfg_value("analyze", "retry_max_s", DEFAULT_RETRY_MAX_S),
        help="Max seconds for retry backoff",
    )
    pa.add_argument(
        "--ai-timeout-s",
        type=float,
        default=cfg_value("analyze", "ai_timeout_s", DEFAULT_AI_TIMEOUT_S),
        help="Per-request timeout for Gemini calls (seconds)",
    )
    pa.add_argument(
        "--subprocess-timeout-s",
        type=float,
        default=cfg_value("analyze", "subprocess_timeout_s", DEFAULT_SUBPROCESS_TIMEOUT_S),
        help="Timeout for ffmpeg/libreoffice/unoconv subprocess calls (seconds)",
    )
    pa.add_argument(
        "--audio-segment-threshold",
        type=float,
        default=cfg_value("analyze", "audio_segment_threshold", DEFAULT_AUDIO_SEGMENT_THRESHOLD_S),
        help="Audio duration (s) above which segment sampling is applied",
    )
    pa.add_argument(
        "--audio-segment-seconds",
        type=float,
        default=cfg_value("analyze", "audio_segment_seconds", DEFAULT_AUDIO_SEGMENT_SECONDS),
        help="Audio segment length in seconds",
    )
    pa.add_argument(
        "--audio-segment-count",
        type=int,
        default=cfg_value("analyze", "audio_segment_count", DEFAULT_AUDIO_SEGMENT_COUNT),
        help="Audio segment count for sampling",
    )
    pa.add_argument(
        "--audio-transcript-max-chars",
        type=int,
        default=cfg_value("analyze", "audio_transcript_max_chars", DEFAULT_AUDIO_TRANSCRIPT_MAX_CHARS),
        help="Max transcript chars fed into classification prompt",
    )
    pa.add_argument(
        "--doc-text-max-chars",
        type=int,
        default=cfg_value("analyze", "doc_text_max_chars", DEFAULT_DOC_TEXT_MAX_CHARS),
        help="Max extracted doc chars fed into classification prompt",
    )
    pa.add_argument(
        "--max-file-mb",
        type=float,
        default=cfg_value("analyze", "max_file_mb", DEFAULT_MAX_FILE_MB),
        help="Max file size in MB (0 disables)",
    )
    pa.add_argument(
        "--max-files",
        type=int,
        default=cfg_value("analyze", "max_files", DEFAULT_MAX_FILES),
        help="Max number of files to process (0 disables)",
    )
    pa.add_argument(
        "--max-total-mb",
        type=float,
        default=cfg_value("analyze", "max_total_mb", DEFAULT_MAX_TOTAL_MB),
        help="Max total size in MB (0 disables)",
    )
    pa.add_argument(
        "--workers",
        type=int,
        default=cfg_value("analyze", "workers", DEFAULT_WORKERS),
        help="Concurrent workers for analyze",
    )
    pa.add_argument(
        "--offline",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("analyze", "offline", False),
        help="Offline mode without Gemini calls",
    )
    pa.add_argument(
        "--sleep",
        type=float,
        default=cfg_value("analyze", "sleep", 0.0),
        help="Sleep between calls",
    )
    pa.add_argument(
        "--chunk-size",
        type=int,
        default=cfg_value("analyze", "chunk_size", DEFAULT_CHUNK_SIZE),
        help="Chunk size for streaming outputs",
    )
    pa.set_defaults(func=handlers["analyze"])

    pp = sub.add_parser("apply", help="Rename/move based on manifest")
    _add_shared_args(pp)
    pp.add_argument("--manifest", default=cfg_value("apply", "manifest", ""), help="Input manifest .jsonl")
    pp.add_argument(
        "--output",
        default=cfg_value("apply", "output", default_output_root()),
        help="Output root folder (default: localized organized-images folder with Seattle timestamp)",
    )
    pp.add_argument(
        "--categories",
        default=cfg_value("apply", "categories", ""),
        help="Comma-separated category enum (product values are preserved as-is)",
    )
    pp.add_argument(
        "--input-root",
        default=cfg_value("apply", "input_root", ""),
        help="Optional input root to validate manifest paths",
    )
    pp.add_argument(
        "--trust-manifest-input-root",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("apply", "trust_manifest_input_root", False),
        help="Trust input_root from each manifest row when --input-root is not set",
    )
    pp.add_argument(
        "--manifest-input-root-allowlist",
        default=cfg_value("apply", "manifest_input_root_allowlist", ""),
        help="Comma-separated allowlist roots for manifest input_root when trust mode is enabled",
    )
    pp.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("apply", "dry_run", False),
        help="Do not move files",
    )
    pp.add_argument("--out-manifest", default=cfg_value("apply", "out_manifest", ""), help="Write updated manifest")
    pp.add_argument("--report", default=cfg_value("apply", "report", ""), help="Optional report JSON output path")
    pp.add_argument(
        "--rollback-manifest",
        default=cfg_value("apply", "rollback_manifest", ""),
        help="Optional rollback manifest path",
    )
    pp.add_argument(
        "--verify-sha1",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("apply", "verify_sha1", False),
        help="Recompute sha1 before move",
    )
    pp.add_argument(
        "--durability",
        default=cfg_value("apply", "durability", DEFAULT_DURABILITY),
        choices=["none", "batch", "sync"],
        help="Durability mode (none/batch/sync)",
    )
    pp.add_argument(
        "--fsync-interval",
        type=int,
        default=cfg_value("apply", "fsync_interval", DEFAULT_MANIFEST_FSYNC_INTERVAL),
        help="Manifest fsync interval (0 disables)",
    )
    pp.add_argument(
        "--dedupe",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("apply", "dedupe", True),
        help="Enable duplicate handling",
    )
    pp.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("apply", "resume", True),
        help="Resume from existing manifest",
    )
    pp.add_argument(
        "--retry-errors",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("apply", "retry_errors", False),
        help="Retry rows with error",
    )
    pp.add_argument(
        "--chunk-size",
        type=int,
        default=cfg_value("apply", "chunk_size", DEFAULT_CHUNK_SIZE),
        help="Chunk size for streaming manifest",
    )
    pp.add_argument(
        "--crash-inject",
        default=cfg_value("apply", "crash_inject", ""),
        help=(
            "Test-only crash injection point: "
            "after_move_before_manifest_commit | "
            "after_manifest_before_rollback_commit | "
            "after_rollback_before_finalize"
        ),
    )
    pp.set_defaults(func=handlers["apply"])

    pr = sub.add_parser("rollback", help="Rollback moves using manifest")
    _add_shared_args(pr)
    pr.add_argument("--manifest", default=cfg_value("rollback", "manifest", ""), help="Manifest with new_path")
    pr.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("rollback", "dry_run", False),
        help="Do not move files",
    )
    pr.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("rollback", "overwrite", False),
        help="Overwrite existing",
    )
    pr.add_argument(
        "--allowed-root",
        default=cfg_value("rollback", "allowed_root", ""),
        help="Rollback allowed roots (comma-separated); source and target must both be inside",
    )
    pr.add_argument(
        "--strict-integrity",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("rollback", "strict_integrity", True),
        help="Require run_id + rollback_sig integrity checks",
    )
    pr.set_defaults(func=handlers["rollback"])

    prp = sub.add_parser("report", help="Generate report from manifest")
    _add_shared_args(prp)
    prp.add_argument(
        "--manifest",
        default=cfg_value("report", "manifest", ""),
        help="Input manifest .jsonl",
    )
    prp.add_argument("--out", default=cfg_value("report", "out", default_report_out), help="Report output path")
    prp.add_argument(
        "--validate",
        action=argparse.BooleanOptionalAction,
        default=cfg_value("report", "validate", False),
        help="Validate manifest schema",
    )
    prp.add_argument(
        "--chunk-size",
        type=int,
        default=cfg_value("report", "chunk_size", DEFAULT_CHUNK_SIZE),
        help="Chunk size for streaming manifest",
    )
    prp.set_defaults(func=handlers["report"])
    return parser


def collect_lock_targets(args: argparse.Namespace, resolved_path: PathResolver) -> set[str]:
    lock_targets: set[str] = set()
    if args.cmd == "analyze":
        lock_targets.add(str(resolved_path(args.manifest)))
        if getattr(args, "csv", ""):
            lock_targets.add(str(resolved_path(args.csv)))
        if getattr(args, "report", ""):
            lock_targets.add(str(resolved_path(args.report)))
        return lock_targets

    if args.cmd == "apply":
        manifest_path = str(resolved_path(args.manifest))
        out_manifest_path = str(resolved_path(args.out_manifest)) if args.out_manifest else manifest_path
        lock_targets.add(manifest_path)
        lock_targets.add(out_manifest_path)
        if getattr(args, "report", ""):
            lock_targets.add(str(resolved_path(args.report)))
        if getattr(args, "rollback_manifest", ""):
            lock_targets.add(str(resolved_path(args.rollback_manifest)))
        return lock_targets

    if args.cmd in {"rollback", "report"}:
        lock_targets.add(str(resolved_path(args.manifest)))
        if args.cmd == "report":
            lock_targets.add(str(resolved_path(args.out)))
    return lock_targets
