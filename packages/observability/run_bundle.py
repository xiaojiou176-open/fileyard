# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any


class _TeeStderr:
    def __init__(self, original, handle) -> None:
        self._original = original
        self._handle = handle

    def write(self, data: str) -> int:
        self._handle.write(data)
        self._handle.flush()
        return self._original.write(data)

    def flush(self) -> None:
        self._handle.flush()
        self._original.flush()


_STDERR_STATE: dict[str, Any] = {"original": None, "handle": None}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace_root() -> Path:
    return Path(os.environ.get("FILEYARD_WORKSPACE_ROOT", "~/.fileyard/workspaces/default")).expanduser()


def run_bundle_root() -> Path:
    raw = os.environ.get("FILEYARD_RUN_BUNDLE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _workspace_root() / ".fileyard" / "runs"


def run_bundle_dir(run_id: str) -> Path:
    return run_bundle_root() / run_id


def _gate_context(gate_run_id: str | None = None, gate_name: str | None = None) -> dict[str, str]:
    gate_run_id = str(gate_run_id or "").strip()
    gate_name = str(gate_name or "").strip()
    payload: dict[str, str] = {}
    if gate_run_id:
        payload["gate_run_id"] = gate_run_id
    if gate_name:
        payload["gate_name"] = gate_name
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_existing_summary(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _restore_stderr_tee() -> None:
    original = _STDERR_STATE.get("original")
    handle = _STDERR_STATE.get("handle")
    if original is not None:
        sys.stderr = original
    if handle is not None:
        handle.close()
    _STDERR_STATE["original"] = None
    _STDERR_STATE["handle"] = None


def _install_stderr_tee(stderr_path: Path) -> None:
    _restore_stderr_tee()
    original = sys.stderr
    handle = stderr_path.open("a", encoding="utf-8")
    _STDERR_STATE["original"] = original
    _STDERR_STATE["handle"] = handle
    sys.stderr = _TeeStderr(original, handle)


def initialize_run_bundle(run_id: str, command: str, *, gate_run_id: str | None = None, gate_name: str | None = None) -> dict[str, str]:
    bundle_dir = run_bundle_dir(run_id)
    evidence_dir = bundle_dir / "evidence"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    events_path = bundle_dir / "events.jsonl"
    stderr_path = bundle_dir / "stderr.log"
    summary_path = bundle_dir / "summary.json"
    evidence_index_path = evidence_dir / "index.json"

    summary_payload = {
        "run_id": run_id,
        "command": command,
        "status": "running",
        "started_at": _now_iso(),
        "finished_at": None,
        "paths": {
            "events": str(events_path),
            "stderr": str(stderr_path),
            "summary": str(summary_path),
            "evidence_index": str(evidence_index_path),
        },
    }
    summary_payload.update(_gate_context(gate_run_id=gate_run_id, gate_name=gate_name))
    _write_json(summary_path, summary_payload)
    evidence_payload = {
        "run_id": run_id,
        "command": command,
        "events": str(events_path),
        "stderr": str(stderr_path),
        "summary": str(summary_path),
    }
    evidence_payload.update(_gate_context(gate_run_id=gate_run_id, gate_name=gate_name))
    _write_json(evidence_index_path, evidence_payload)
    stderr_path.touch()

    os.environ["FILEYARD_RUN_DIR"] = str(bundle_dir)
    os.environ["FILEYARD_RUN_EVENTS_PATH"] = str(events_path)
    os.environ["FILEYARD_RUN_STDERR_PATH"] = str(stderr_path)
    os.environ["FILEYARD_RUN_SUMMARY_PATH"] = str(summary_path)
    os.environ["FILEYARD_RUN_EVIDENCE_INDEX_PATH"] = str(evidence_index_path)

    _install_stderr_tee(stderr_path)

    return {
        "run_dir": str(bundle_dir),
        "events": str(events_path),
        "stderr": str(stderr_path),
        "summary": str(summary_path),
        "evidence_index": str(evidence_index_path),
    }


def finalize_run_bundle(
    run_id: str,
    command: str,
    status: str,
    extra: dict[str, Any] | None = None,
    *,
    gate_run_id: str | None = None,
    gate_name: str | None = None,
) -> None:
    bundle_dir = run_bundle_dir(run_id)
    summary_path = bundle_dir / "summary.json"
    evidence_index_path = bundle_dir / "evidence" / "index.json"

    payload: dict[str, Any] = {
        "run_id": run_id,
        "command": command,
        "status": status,
        "started_at": _now_iso(),
        "finished_at": _now_iso(),
        "paths": {
            "events": str(bundle_dir / "events.jsonl"),
            "stderr": str(bundle_dir / "stderr.log"),
            "summary": str(summary_path),
            "evidence_index": str(evidence_index_path),
        },
    }
    if summary_path.exists():
        existing = _load_existing_summary(summary_path)
        if existing is not None:
            payload.update(existing)
            payload["status"] = status
            payload["finished_at"] = _now_iso()
    if extra:
        payload.update(extra)
    payload.update(_gate_context(gate_run_id=gate_run_id, gate_name=gate_name))
    _write_json(summary_path, payload)
    _restore_stderr_tee()
