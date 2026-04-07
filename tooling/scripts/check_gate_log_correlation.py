#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid gate log schema contract: {path}")
    return payload


def _load_json_lines(path: Path) -> list[dict]:
    payloads: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate gate summary envelopes and step log correlation")
    parser.add_argument("--root", default=".")
    parser.add_argument("--contract", default="contracts/runtime/gate_log_schema.yaml")
    parser.add_argument("--gate", action="append", default=[], help="Only validate the named gate(s) from the contract")
    parser.add_argument(
        "--allow-missing-gate",
        action="append",
        default=[],
        help="Gate name(s) that may be skipped when their summary file does not exist",
    )
    parser.add_argument("--summary-path", help="Override the summary path when validating a single gate")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = _load_yaml(root / args.contract)
    gates = contract.get("required_gates", [])
    top_level_fields = contract.get("required_top_level_fields", [])
    step_fields = contract.get("required_step_fields", [])
    if not isinstance(gates, list) or not isinstance(top_level_fields, list) or not isinstance(step_fields, list):
        raise SystemExit("invalid gate log schema contract")

    selected_gates = {item.strip() for item in args.gate if item and item.strip()}
    if selected_gates:
        gates = [gate for gate in gates if isinstance(gate, dict) and str(gate.get("gate_name", "")).strip() in selected_gates]
        missing = selected_gates.difference(str(gate.get("gate_name", "")).strip() for gate in gates if isinstance(gate, dict))
        if missing:
            raise SystemExit(f"unknown gate(s) requested: {', '.join(sorted(missing))}")
    allow_missing_gates = {item.strip() for item in args.allow_missing_gate if item and item.strip()}
    if args.summary_path and len(gates) != 1:
        raise SystemExit("--summary-path requires exactly one selected gate")

    issues: list[str] = []
    for gate in gates:
        if not isinstance(gate, dict):
            issues.append("required_gates contains a non-object entry")
            continue
        gate_name = str(gate.get("gate_name", "")).strip()
        summary_rel = args.summary_path or str(gate.get("summary_path", "")).strip()
        summary_path = root / summary_rel
        if not gate_name or not summary_path.name:
            issues.append(f"invalid required_gates entry: {gate!r}")
            continue
        if not summary_path.exists():
            if gate_name in allow_missing_gates:
                continue
            issues.append(f"{gate_name}: missing summary file: {summary_path.relative_to(root)}")
            continue
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"{gate_name}: invalid summary json: {exc}")
            continue
        if not isinstance(payload, dict):
            issues.append(f"{gate_name}: summary payload must be an object")
            continue
        for field in top_level_fields:
            if field not in payload:
                issues.append(f"{gate_name}: missing top-level field: {field}")
        if payload.get("gate_name") != gate_name:
            issues.append(f"{gate_name}: summary gate_name mismatch: {payload.get('gate_name')!r}")
        payload_summary_rel = str(payload.get("summary_path", "")).strip()
        payload_latest_summary_rel = str(payload.get("latest_summary_path", "")).strip()
        if payload_summary_rel or payload_latest_summary_rel:
            if summary_rel not in {item for item in (payload_summary_rel, payload_latest_summary_rel) if item}:
                issues.append(f"{gate_name}: loaded summary path {summary_rel!r} does not match payload summary/latest summary")
        receipt_dir_rel = str(payload.get("receipt_dir", "")).strip()
        if receipt_dir_rel:
            receipt_dir = root / receipt_dir_rel
            if not receipt_dir.exists():
                issues.append(f"{gate_name}: receipt_dir missing: {receipt_dir_rel}")
        step_summary_rel = str(payload.get("step_summary_path", "")).strip()
        if step_summary_rel:
            step_summary_path = root / step_summary_rel
            if not step_summary_path.exists():
                issues.append(f"{gate_name}: step summary missing: {step_summary_rel}")
        latest_step_summary_rel = str(payload.get("latest_step_summary_path", "")).strip()
        if latest_step_summary_rel:
            latest_step_summary_path = root / latest_step_summary_rel
            if not latest_step_summary_path.exists():
                issues.append(f"{gate_name}: latest step summary missing: {latest_step_summary_rel}")
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            issues.append(f"{gate_name}: steps must be a non-empty list")
            continue
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                issues.append(f"{gate_name}: step #{idx} must be an object")
                continue
            for field in step_fields:
                if field not in step:
                    issues.append(f"{gate_name}: step #{idx} missing field: {field}")
            artifact_rel = str(step.get("artifact_log_path", "")).strip()
            if artifact_rel:
                artifact_path = root / artifact_rel
                if not artifact_path.exists():
                    issues.append(f"{gate_name}: step #{idx} artifact log missing: {artifact_rel}")
        bridge_step_name = str(gate.get("bridge_log_step_name", "")).strip()
        bridge_required_fields = [str(field).strip() for field in gate.get("bridge_required_event_fields", []) if str(field).strip()]
        if bridge_step_name and bridge_required_fields:
            bridge_step = next(
                (step for step in steps if isinstance(step, dict) and str(step.get("step_name", "")).strip() == bridge_step_name),
                None,
            )
            if bridge_step is None:
                continue
            bridge_artifact_rel = str(bridge_step.get("artifact_log_path", "")).strip()
            if not bridge_artifact_rel:
                issues.append(f"{gate_name}: bridge step missing artifact_log_path: {bridge_step_name}")
                continue
            bridge_artifact_path = root / bridge_artifact_rel
            if not bridge_artifact_path.exists():
                issues.append(f"{gate_name}: bridge log missing: {bridge_artifact_rel}")
                continue
            bridge_events = _load_json_lines(bridge_artifact_path)
            if not bridge_events:
                issues.append(f"{gate_name}: bridge log does not contain json events: {bridge_artifact_rel}")
                continue
            matched = False
            for event_payload in bridge_events:
                if all(
                    str(event_payload.get(field, "")).strip() == str(payload.get(field, "")).strip() for field in bridge_required_fields
                ):
                    matched = True
                    break
            if not matched:
                issues.append(
                    f"{gate_name}: bridge log missing event correlated by {', '.join(bridge_required_fields)}: {bridge_artifact_rel}"
                )

    if issues:
        print("❌ gate-log-correlation gate failed")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("gate-log-correlation gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
