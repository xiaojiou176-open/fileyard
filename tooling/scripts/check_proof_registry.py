#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml  # type: ignore[import-untyped]

PUBLIC_PROOF_CONTRACT = "contracts/proof/public_proof_contract.yaml"


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid proof registry: {path}")
    return payload


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FILEMAN_ALLOW_HOST_EXECUTION"] = "1"
    return subprocess.run(cmd, cwd=str(cwd), env=env, text=True, capture_output=True, check=False)


def _require_mapping(value: object, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a mapping")
    return value


def _require_doc_snippets(root: Path, issues: list[str], contract: dict) -> None:
    docs_section = _require_mapping(contract.get("docs", {}), label="public proof docs contract")
    for doc_id, doc_rule in docs_section.items():
        rule = _require_mapping(doc_rule, label=f"{doc_id} contract")
        doc_path = root / str(rule.get("path", ""))
        if not doc_path.exists():
            issues.append(f"missing proof doc: {doc_path.relative_to(root)}")
            continue
        content = doc_path.read_text(encoding="utf-8")
        for snippet in [str(item) for item in rule.get("required_snippets", [])]:
            if snippet not in content:
                issues.append(f"{doc_path.relative_to(root)} missing proof snippet: {snippet}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate proof registry semantics against docs and executable outputs")
    parser.add_argument("--root", default=".")
    parser.add_argument("--registry", default="contracts/proof/value_proof_registry.yaml")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    registry = _load_yaml(repo_root / args.registry)
    public_contract = _load_yaml(repo_root / PUBLIC_PROOF_CONTRACT)
    issues: list[str] = []

    value_proof = _require_mapping(registry.get("value_proof", {}), label="value_proof registry")
    ai_eval = _require_mapping(registry.get("ai_eval", {}), label="ai_eval registry")

    package_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
    _require_doc_snippets(repo_root, issues, public_contract)

    if scripts.get("proof:gate") != "bash tooling/gates/proof_gate.sh":
        issues.append("package.json must expose proof:gate")

    with tempfile.TemporaryDirectory(prefix="proof-registry-") as tmpdir:
        value_output = Path(tmpdir) / "value-proof.json"
        ai_output = Path(tmpdir) / "ai-eval.json"

        value_proc = _run(
            [
                sys.executable,
                str(repo_root / "tooling" / "scripts" / "generate_value_proof_report.py"),
                "--root",
                str(repo_root),
                "--output",
                str(value_output),
            ],
            repo_root,
        )
        if value_proc.returncode != 0:
            issues.append(f"value proof generator failed: {value_proc.stdout}{value_proc.stderr}")
        else:
            payload = json.loads(value_output.read_text(encoding="utf-8"))
            if payload["manual_baseline"]["status"] != value_proof.get("manual_baseline_status"):
                issues.append("value proof manual baseline status drifted from registry")
            if payload["dataset"]["source"] != value_proof.get("smoke_dataset"):
                issues.append("value proof smoke dataset drifted from registry")
            evidence_tiers = payload.get("evidence_tiers", {})
            if evidence_tiers.get("canonical_pack_tier") != value_proof.get("current_tier"):
                issues.append("value proof canonical tier drifted from registry")
            if evidence_tiers.get("attained_tier_this_run") != "smoke":
                issues.append("value proof current repo snapshot should still be smoke tier")
            if evidence_tiers.get("headline_public_allowed") is not value_proof.get("headline_public_allowed"):
                issues.append("value proof headline public policy drifted from registry")
            proof_boundaries = payload.get("proof_boundaries", {})
            if not proof_boundaries.get("does_not_prove"):
                issues.append("value proof summary must explain what it does not prove")
            if not proof_boundaries.get("remaining_gaps"):
                issues.append("value proof summary must keep explicit remaining gaps")
            newcomer_truth = payload.get("newcomer_truth", {})
            if newcomer_truth.get("first_command") != str(value_proof.get("canonical_command")):
                issues.append("value proof newcomer entrypoint drifted from canonical command")

        ai_proc = _run(
            [
                sys.executable,
                str(repo_root / "tooling" / "scripts" / "run_ai_eval.py"),
                "--root",
                str(repo_root),
                "--mode",
                "offline",
                "--output",
                str(ai_output),
            ],
            repo_root,
        )
        if ai_proc.returncode != 0:
            issues.append(f"ai eval runner failed: {ai_proc.stdout}{ai_proc.stderr}")
        else:
            payload = json.loads(ai_output.read_text(encoding="utf-8"))
            live_suite_id = str(ai_eval.get("live_suite_id"))
            live_suite = next((suite for suite in payload.get("suites", []) if suite.get("id") == live_suite_id), None)
            if live_suite is None:
                issues.append(f"ai eval output missing live suite: {live_suite_id}")
            elif live_suite.get("status") != ai_eval.get("live_suite_expected_status_without_credentials"):
                issues.append("ai eval live suite status drifted from registry")
            evidence_tiers = payload.get("evidence_tiers", {})
            if evidence_tiers.get("canonical_pack_tier") != ai_eval.get("current_tier"):
                issues.append("ai eval canonical tier drifted from registry")
            if evidence_tiers.get("attained_tier_this_run") != "smoke":
                issues.append("ai eval current repo snapshot should still be smoke tier without live receipt")
            proof_boundaries = payload.get("proof_boundaries", {})
            if not proof_boundaries.get("does_not_prove"):
                issues.append("ai eval summary must explain what it does not prove")
            privacy_truth = payload.get("privacy_truth", {})
            if privacy_truth.get("credential_values_stored") is not False:
                issues.append("ai eval privacy truth must explicitly state API keys are not stored in evidence")
            live_receipt = payload.get("live_receipt", {})
            if live_receipt.get("status") != ai_eval.get("live_suite_expected_status_without_credentials"):
                issues.append("ai eval live receipt summary drifted from live-suite expectation")
            newcomer_truth = payload.get("newcomer_truth", {})
            if newcomer_truth.get("first_command") != "bash tooling/gates/ai_eval_gate.sh --mode offline":
                issues.append("ai eval newcomer entrypoint should guide readers to the offline proof lane first")

    if issues:
        print("❌ proof-registry gate failed")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("✅ proof-registry gate passed")
    print(f"- value-proof tier: smoke ({value_proof.get('canonical_command')})")
    print(f"- ai-eval tier: smoke ({ai_eval.get('canonical_command')})")
    print("- docs: usage guide + open-source runbook are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
