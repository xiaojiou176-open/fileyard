#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

BLOCKER_CHECKS = {
    "architecture": [
        "tooling/scripts/generate_api_contract.py --check",
        "tooling/scripts/check_strategy_pack_registry.py",
        "tooling/scripts/check_watch_sources_contract.py",
        "tooling/scripts/check_module_graph.py",
        "tooling/scripts/check_dependency_boundaries.py",
        "tooling/scripts/check_docs_fragment_completeness.py",
        "tooling/scripts/check_docs_truth_routes.py",
        "tooling/scripts/check_snapshot_scope_labels.py",
        "tooling/scripts/check_done_signal_claims.py",
        "tooling/scripts/check_positioning_claims.py",
        "tooling/scripts/check_hotspot_budget.py",
    ],
    "cache": [
        "tooling/scripts/check_runtime_layout.py",
        "tooling/scripts/check_repo_runtime_residue.py",
        "tooling/scripts/check_runtime_budget.py",
        "tooling/scripts/check_cold_start_rebuild.py",
    ],
    "logging": [
        "tooling/scripts/check_no_logs_no_merge.py",
        "tooling/scripts/check_logging_contract.py",
        "tooling/scripts/check_runtime_language_boundary.py",
        "tooling/scripts/check_gate_log_correlation.py",
        "tooling/scripts/check_run_bundle_contract.py",
    ],
    "root": [
        "tooling/scripts/check_root_layout.py",
        "tooling/scripts/check_root_clean_after_mainflows.py",
        "tooling/scripts/check_root_public_surface.py",
        "tooling/scripts/check_root_change_control.py",
        "tooling/scripts/check_collaboration_surface.py",
        "tooling/scripts/check_public_artifact_safety.py",
        "tooling/scripts/check_sensitive_surface.py",
        "tooling/scripts/check_local_only_tracking.py",
        "tooling/scripts/check_feature_state_layout.py",
    ],
    "upstreams": [
        "tooling/scripts/check_upstream_drift.py",
        "tooling/scripts/check_upstream_registry_completeness.py",
        "tooling/scripts/check_upstream_fetch_surfaces.py",
        "tooling/scripts/check_upstream_compat_matrix.py",
        "tooling/scripts/check_upstream_verification_freshness.py",
        "tooling/scripts/check_upstream_receipts.py",
        "tooling/scripts/check_upstream_host_capabilities.py",
        "tooling/scripts/check_no_private_upstream_coupling.py",
    ],
}

MATURITY_CHECKS = {
    "architecture": [
        "tooling/scripts/check_active_legacy_sweep.py",
        "tooling/scripts/check_strategy_pack_registry.py",
        "tooling/scripts/check_watch_sources_contract.py",
        "tooling/scripts/check_docs_render_state.py",
        "tooling/scripts/check_docs_fragment_completeness.py",
        "tooling/scripts/check_docs_truth_routes.py",
        "tooling/scripts/check_snapshot_scope_labels.py",
        "tooling/scripts/check_done_signal_claims.py",
        "tooling/scripts/check_positioning_claims.py",
        "tooling/scripts/check_hotspot_budget.py",
    ],
    "cache": [
        "tooling/scripts/check_runtime_layout.py",
        "tooling/scripts/check_repo_runtime_residue.py",
        "tooling/scripts/check_runtime_budget.py",
        "tooling/scripts/check_cold_start_rebuild.py",
    ],
    "logging": [
        "tooling/scripts/check_logging_contract.py",
        "tooling/scripts/check_runtime_language_boundary.py",
        "tooling/scripts/check_gate_log_correlation.py",
        "tooling/scripts/check_run_bundle_contract.py",
    ],
    "root": [
        "tooling/scripts/check_root_layout.py",
        "tooling/scripts/check_root_clean_after_mainflows.py",
        "tooling/scripts/check_root_public_surface.py",
        "tooling/scripts/check_root_change_control.py",
        "tooling/scripts/check_collaboration_surface.py",
        "tooling/scripts/check_public_artifact_safety.py",
        "tooling/scripts/check_sensitive_surface.py",
        "tooling/scripts/check_local_only_tracking.py",
        "tooling/scripts/check_feature_state_layout.py",
    ],
    "upstreams": [
        "tooling/scripts/check_upstream_compat_matrix.py",
        "tooling/scripts/check_upstream_verification_freshness.py",
        "tooling/scripts/check_upstream_receipts.py",
        "tooling/scripts/check_upstream_host_capabilities.py",
        "tooling/scripts/check_no_private_upstream_coupling.py",
    ],
}

WEIGHTS = {"architecture": 30, "cache": 20, "logging": 20, "root": 10, "upstreams": 20}


def _governance_python_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    pycache_prefix = str(Path(env.get("PYTHONPYCACHEPREFIX", "~/.cache/fileman/pycache")).expanduser())
    Path(pycache_prefix).mkdir(parents=True, exist_ok=True)
    env.setdefault("PYTHONPYCACHEPREFIX", pycache_prefix)
    return env


def _cleanup_local_script_pycache() -> None:
    shutil.rmtree(Path(__file__).resolve().parent / "__pycache__", ignore_errors=True)


def _run(repo_root: Path, command: str) -> bool:
    tokens = shlex.split(command)
    env = _governance_python_env()
    _cleanup_local_script_pycache()
    proc = subprocess.run(["python3", *tokens, "--root", str(repo_root)], cwd=str(repo_root), env=env, check=False)
    return proc.returncode == 0


def _score(repo_root: Path, checks: dict[str, list[str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    total = 0
    for area, commands in checks.items():
        passed = sum(1 for command in commands if _run(repo_root, command))
        score = int(round((passed / len(commands)) * WEIGHTS[area]))
        result[area] = score
        total += score
    result["total"] = total
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Score repo governance with separate blocker and maturity lenses")
    parser.add_argument("--root", default=".")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    _cleanup_local_script_pycache()

    blocker_score = _score(root, BLOCKER_CHECKS)
    maturity_score = _score(root, MATURITY_CHECKS)
    payload = {
        "blocker_score": blocker_score,
        "maturity_score": maturity_score,
        "total": {
            "blocker": blocker_score["total"],
            "maturity": maturity_score["total"],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.strict:
        blocker_green = all(blocker_score[area] == WEIGHTS[area] for area in WEIGHTS)
        maturity_green = all(maturity_score[area] == WEIGHTS[area] for area in WEIGHTS)
        return 0 if blocker_green and maturity_green else 1
    return 0 if blocker_score["total"] == sum(WEIGHTS.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
