#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ABSOLUTE_PRIVATE_PATH_RE = re.compile(
    r"/" + r"(?:Users|home)" + r"/[A-Za-z0-9._-]+/" + r"|" + r"[A-Za-z]:\\\\Users\\\\[A-Za-z0-9._-]+\\\\",
    re.IGNORECASE,
)


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"invalid yaml: {path}")
    return data


def _validate_runtime_behavior(root: Path, schema: dict, gate_run_id: str, gate_name: str) -> list[str]:
    temp_root = Path(tempfile.mkdtemp(prefix="fileorganize-logging-contract-"))
    os.environ["FILEORGANIZE_RUN_BUNDLE_ROOT"] = str(temp_root / "runs")
    from packages.observability.logging_utils import log_event, setup_logger
    from packages.observability.run_bundle import finalize_run_bundle, initialize_run_bundle

    bundle = initialize_run_bundle("logging_contract_smoke", "report", gate_run_id=gate_run_id, gate_name=gate_name)
    logger = setup_logger("INFO", True)
    log_event(
        logger,
        logging.INFO,
        "report.generate.start",
        "begin",
        run_id="logging_contract_smoke",
        gate_run_id=gate_run_id,
        gate_name=gate_name,
        workspace_id="default",
        duration_ms=1,
    )
    log_event(
        logger,
        logging.ERROR,
        "report.generate.fail",
        "boom",
        run_id="logging_contract_smoke",
        gate_run_id=gate_run_id,
        gate_name=gate_name,
        workspace_id="default",
        duration_ms=1,
        error_type="RuntimeError",
        error_code="boom",
        error_message="boom",
        error_retryable=False,
    )
    finalize_run_bundle("logging_contract_smoke", "report", "fail", gate_run_id=gate_run_id, gate_name=gate_name)

    issues: list[str] = []
    events_path = Path(bundle["events"])
    summary_path = Path(bundle["summary"])
    evidence_path = Path(bundle["evidence_index"])
    stderr_path = Path(bundle["stderr"])
    for path in (events_path, summary_path, evidence_path, stderr_path):
        if not path.exists():
            issues.append(f"missing logging artifact: {path}")
    if issues:
        return issues

    lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 2:
        issues.append("events.jsonl must contain at least start + fail events")
        return issues
    required_fields = [str(item) for item in schema.get("required_fields", [])]
    for payload in lines:
        missing = [field for field in required_fields if field not in payload]
        if missing:
            issues.append(f"event missing required fields: {', '.join(missing)}")
    for payload in lines:
        if payload.get("gate_run_id") != gate_run_id:
            issues.append("event missing gate_run_id bridge")
        if payload.get("gate_name") != gate_name:
            issues.append("event missing gate_name bridge")
    error_payload = lines[-1].get("error")
    if not isinstance(error_payload, dict):
        issues.append("failure event missing structured error payload")
    else:
        for key in ("type", "code", "message", "retryable"):
            if key not in error_payload:
                issues.append(f"structured error payload missing key: {key}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("gate_run_id") != gate_run_id:
        issues.append("summary.json missing gate_run_id bridge")
    if summary.get("gate_name") != gate_name:
        issues.append("summary.json missing gate_name bridge")
    if summary.get("paths", {}).get("events") != str(events_path):
        issues.append("summary.json events path does not match bundle events file")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("gate_run_id") != gate_run_id:
        issues.append("evidence index missing gate_run_id bridge")
    if evidence.get("gate_name") != gate_name:
        issues.append("evidence index missing gate_name bridge")
    if evidence.get("events") != str(events_path):
        issues.append("evidence index events path does not match bundle events file")
    if any(ABSOLUTE_PRIVATE_PATH_RE.search(json.dumps(payload, ensure_ascii=False)) for payload in lines):
        issues.append("events.jsonl leaked absolute user path")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate logging contract files and runtime behavior")
    parser.add_argument("--root", default=".")
    parser.add_argument("--gate-run-id", default="quality-gate-logging-contract-smoke")
    parser.add_argument("--gate-name", default="quality-gate")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    event_schema_path = root / "contracts/runtime/event_schema.yaml"
    docs_path = root / "docs/logging_observability.md"
    cli_path = root / "apps/cli/cli_app.py"
    api_path = root / "apps/api/web_api.py"
    required = [event_schema_path, docs_path, cli_path, api_path]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        sys.stderr.write("logging-contract gate failed\n")
        for item in missing:
            sys.stderr.write(f"- missing {item}\n")
        return 1

    cli_text = cli_path.read_text(encoding="utf-8")
    api_text = api_path.read_text(encoding="utf-8")
    issues: list[str] = []
    if "initialize_run_bundle" not in cli_text or "finalize_run_bundle" not in cli_text:
        issues.append("apps/cli/cli_app.py must initialize and finalize run bundles")
    if "run_id=record.id" not in api_text:
        issues.append("apps/api/web_api.py must bind API jobs to CLI run_id=record.id")
    issues.extend(_validate_runtime_behavior(root, _load_yaml(event_schema_path), str(args.gate_run_id), str(args.gate_name)))

    if issues:
        sys.stderr.write("logging-contract gate failed\n")
        for item in issues:
            sys.stderr.write(f"- {item}\n")
        return 1
    print("logging-contract gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
