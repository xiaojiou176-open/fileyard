#!/usr/bin/env python3
"""Runtime governance receipt writer for quality_gate / pre-push observability."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_impl_log_event: Callable[..., None] | None = None
_impl_set_log_context_defaults: Callable[..., None] | None = None
_impl_setup_logger: Callable[[str, bool], logging.Logger] | None = None

try:
    from packages.observability.logging_utils import (
        log_event as _impl_log_event,
    )
    from packages.observability.logging_utils import (
        set_log_context_defaults as _impl_set_log_context_defaults,
    )
    from packages.observability.logging_utils import (
        setup_logger as _impl_setup_logger,
    )
except ImportError:  # pragma: no cover - fixture-style script tests use fallback mode
    pass


RUNTIME_GOVERNANCE_ROOT = Path(".runtime-cache/logs/runtime-governance")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _rel(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fallback_setup_logger(level: str, json_mode: bool) -> logging.Logger:
    logger = logging.getLogger("runtime_governance_report_fallback")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    return logger


def _fallback_set_log_context_defaults(**kwargs: Any) -> None:
    return None


def _fallback_log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    *,
    redact_paths: bool = True,
    **fields: Any,
) -> None:
    events_path = Path(os.environ["FILEMAN_RUN_EVENTS_PATH"])
    events_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": _utc_now(),
        "event": event,
        "message": message,
        "fields": fields,
    }
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


SETUP_LOGGER: Callable[[str, bool], logging.Logger]
SET_LOG_CONTEXT_DEFAULTS: Callable[..., None]
LOG_EVENT: Callable[..., None]
if _impl_setup_logger is None or _impl_set_log_context_defaults is None or _impl_log_event is None:
    SETUP_LOGGER = _fallback_setup_logger
    SET_LOG_CONTEXT_DEFAULTS = _fallback_set_log_context_defaults
    LOG_EVENT = _fallback_log_event
else:
    SETUP_LOGGER = _impl_setup_logger
    SET_LOG_CONTEXT_DEFAULTS = _impl_set_log_context_defaults
    LOG_EVENT = _impl_log_event


def _event_prefix(action_kind: str, bucket: str) -> str:
    if action_kind == "retention-prune":
        return "receipt.retention.prune"
    if action_kind == "audit":
        return "docker.runtime.audit" if bucket == "docker_runtime" else "runtime.audit"
    return "docker.runtime.prune" if bucket == "docker_runtime" else "cleanup.prune"


def _event_level(status: str) -> int:
    return logging.ERROR if status == "fail" else logging.INFO


def _run_paths(repo_root: Path, run_id: str) -> dict[str, Path]:
    log_root = repo_root / RUNTIME_GOVERNANCE_ROOT
    run_dir = log_root / "runs" / run_id
    return {
        "log_root": log_root,
        "run_dir": run_dir,
        "events_path": run_dir / "events.jsonl",
        "summary_path": run_dir / "summary.json",
        "latest_summary_path": log_root / "summary.json",
    }


def _prepare_logger(events_path: Path, run_id: str) -> logging.Logger:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["FILEMAN_RUN_EVENTS_PATH"] = str(events_path)
    logger = SETUP_LOGGER("INFO", True)
    logger.handlers = [handler for handler in logger.handlers if isinstance(handler, logging.FileHandler)]
    SET_LOG_CONTEXT_DEFAULTS(
        trace_id=run_id,
        request_id=run_id,
        session_id=run_id,
        user_id="runtime_governance",
        service="fileman",
        component="runtime_governance",
    )
    return logger


def record_runtime_governance(
    *,
    repo_root: Path,
    command: str,
    action_kind: str,
    bucket: str,
    target: str,
    dry_run: bool,
    run_id: str,
    started_at: str,
    start_ts: int,
    status: str,
    message: str,
    ownership_class: str | None = None,
    reclaim_class: str | None = None,
    size_before_kib: int | None = None,
    size_after_kib: int | None = None,
    reclaimed_kib: int | None = None,
    entries: list[dict[str, Any]] | None = None,
    totals: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = _run_paths(repo_root, run_id)
    logger = _prepare_logger(paths["events_path"], run_id)
    event = f"{_event_prefix(action_kind, bucket)}.{status}"
    fields: dict[str, Any] = {
        "bucket": bucket,
        "target": target,
        "dry_run": dry_run,
        "ownership_class": ownership_class or "",
        "reclaim_class": reclaim_class or "",
        "size_before_kib": size_before_kib,
        "size_after_kib": size_after_kib,
        "reclaimed_kib": reclaimed_kib,
        "module": "tooling.scripts.runtime_governance_report",
        "action": f"{action_kind}:{command}",
        "failure_domain": "runtime_governance",
    }
    if extra:
        fields["details"] = extra
    LOG_EVENT(logger, _event_level(status), event, message, **fields)

    ended_at = _utc_now()
    duration_ms = max(0, int(round((time.time() - start_ts) * 1000)))
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "command": command,
        "action_kind": action_kind,
        "bucket": bucket,
        "target": target,
        "status": status,
        "dry_run": dry_run,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "summary_path": _rel(repo_root, paths["summary_path"]),
        "latest_summary_path": _rel(repo_root, paths["latest_summary_path"]),
        "events_path": _rel(repo_root, paths["events_path"]),
        "ownership_class": ownership_class,
        "reclaim_class": reclaim_class,
        "entries": entries or [],
        "totals": totals or {},
        "extra": extra or {},
    }
    if status == "start":
        return payload

    paths["summary_path"].write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["latest_summary_path"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["summary_path"], paths["latest_summary_path"])
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Write structured runtime governance events and summary receipts")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--action-kind", required=True, choices=("audit", "prune", "retention-prune"))
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--dry-run", default="0")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--start-ts", required=True, type=int)
    parser.add_argument("--status", required=True, choices=("start", "success", "fail"))
    parser.add_argument("--message", default="")
    parser.add_argument("--ownership-class", default="")
    parser.add_argument("--reclaim-class", default="")
    parser.add_argument("--size-before-kib", type=int, default=None)
    parser.add_argument("--size-after-kib", type=int, default=None)
    parser.add_argument("--reclaimed-kib", type=int, default=None)
    parser.add_argument("--entries-json", default="")
    parser.add_argument("--totals-json", default="")
    parser.add_argument("--extra-json", default="")
    args = parser.parse_args()

    entries = _load_json(Path(args.entries_json)) if args.entries_json else None
    totals = _load_json(Path(args.totals_json)) if args.totals_json else None
    extra = _load_json(Path(args.extra_json)) if args.extra_json else None

    payload = record_runtime_governance(
        repo_root=Path(args.repo_root).resolve(),
        command=args.command,
        action_kind=args.action_kind,
        bucket=args.bucket,
        target=args.target,
        dry_run=args.dry_run == "1",
        run_id=args.run_id,
        started_at=args.started_at,
        start_ts=args.start_ts,
        status=args.status,
        message=args.message,
        ownership_class=args.ownership_class or None,
        reclaim_class=args.reclaim_class or None,
        size_before_kib=args.size_before_kib,
        size_after_kib=args.size_after_kib,
        reclaimed_kib=args.reclaimed_kib,
        entries=entries if isinstance(entries, list) else None,
        totals=totals if isinstance(totals, dict) else None,
        extra=extra if isinstance(extra, dict) else None,
    )
    if args.status != "start":
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
