#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = [
    REPO_ROOT / ".github" / "workflows" / "ci.yml",
    REPO_ROOT / ".github" / "workflows" / "pre-commit.yml",
    REPO_ROOT / ".github" / "workflows" / "live-integration.yml",
    REPO_ROOT / ".github" / "workflows" / "mutation-manual.yml",
    REPO_ROOT / ".github" / "workflows" / "reusable-build-runtime-image.yml",
]
PINNED_SHA = re.compile(r"@[0-9a-fA-F]{40}$")
DOCKER_DIGEST = re.compile(r"@sha256:[0-9a-fA-F]{64}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a nightly CI drift audit report.")
    parser.add_argument("--output", default=".runtime-cache/logs/drift-audit.json")
    return parser.parse_args()


def _workflow_on(data: dict[str, Any]) -> Any:
    if "on" in data:
        return data.get("on")
    for key, value in data.items():
        if key is True:
            return value
    return None


def _collect_workflow_drift() -> dict[str, Any]:
    results: dict[str, Any] = {"workflows": {}, "failures": []}
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        jobs = data.get("jobs", {}) if isinstance(data, dict) else {}
        pinned_actions = 0
        unpinned_actions: list[str] = []
        for raw_job in jobs.values() if isinstance(jobs, dict) else []:
            if not isinstance(raw_job, dict):
                continue
            if isinstance(raw_job.get("uses"), str):
                uses = str(raw_job["uses"])
                if uses.startswith("./"):
                    pass
                elif PINNED_SHA.search(uses):
                    pinned_actions += 1
                else:
                    unpinned_actions.append(uses)
            for step in raw_job.get("steps", []) or []:
                if not isinstance(step, dict):
                    continue
                step_uses = step.get("uses")
                if not isinstance(step_uses, str):
                    continue
                if step_uses.startswith("./"):
                    continue
                if PINNED_SHA.search(step_uses):
                    pinned_actions += 1
                else:
                    unpinned_actions.append(step_uses)

        merge_group_enabled = False
        if path.name == "ci.yml" and isinstance(data, dict):
            on_value = _workflow_on(data)
            if isinstance(on_value, dict):
                merge_group_enabled = "merge_group" in on_value

        results["workflows"][path.name] = {
            "jobs": len(jobs) if isinstance(jobs, dict) else 0,
            "pinned_actions": pinned_actions,
            "unpinned_actions": sorted(set(unpinned_actions)),
            "merge_group_enabled": merge_group_enabled if path.name == "ci.yml" else None,
            "uses_reusable_runtime_builder": "./.github/workflows/reusable-build-runtime-image.yml" in text,
        }
        if unpinned_actions:
            results["failures"].append(f"{path.name}: unpinned actions detected")

    return results


def _collect_runtime_drift() -> dict[str, Any]:
    dockerfile = (REPO_ROOT / ".devcontainer" / "Dockerfile").read_text(encoding="utf-8")
    governance_defaults = (REPO_ROOT / "contracts" / "governance" / "governance.defaults.env").read_text(encoding="utf-8")
    root_package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    webui_package = json.loads((REPO_ROOT / "apps" / "webui" / "package.json").read_text(encoding="utf-8"))

    return {
        "dockerfile_digest_pins": sorted(set(DOCKER_DIGEST.findall(dockerfile))),
        "governance_defaults_node_runtime": next(
            (line.split("=", 1)[1] for line in governance_defaults.splitlines() if line.startswith("GOVERNANCE_NODE_RUNTIME_IMAGE=")),
            None,
        ),
        "root_node_engine": root_package.get("engines", {}).get("node"),
        "webui_node_engine": webui_package.get("engines", {}).get("node"),
    }


def _collect_contract_drift() -> dict[str, Any]:
    required_checks = (REPO_ROOT / "docs" / "required_checks_matrix.md").read_text(encoding="utf-8")
    runner_contract = (REPO_ROOT / "docs" / "runner_contract.md").read_text(encoding="utf-8")
    return {
        "required_checks_count": required_checks.count("| `.github/workflows/ci.yml` |"),
        "documents_merge_queue": "merge queue" in required_checks.lower(),
        "documents_runner_contract": "Golden Runner / Capability Contract" in runner_contract,
    }


def main() -> int:
    args = _parse_args()
    workflow_drift = _collect_workflow_drift()
    report = {
        "schema_version": "1.0",
        "workflow_drift": workflow_drift,
        "runtime_drift": _collect_runtime_drift(),
        "contract_drift": _collect_contract_drift(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ drift_audit: wrote {output}")
    if workflow_drift["failures"]:
        for failure in workflow_drift["failures"]:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
