#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect CI governance regressions.")
    parser.add_argument("--root", default=".")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.root).resolve()
    failures: list[str] = []

    # Structural ci.yml topology belongs in check_ci_workflow_hardening.py.
    # Keep this script focused on cross-file governance alignment.
    nightly = (repo_root / ".github" / "workflows" / "nightly-drift-audit.yml").read_text(encoding="utf-8")
    reusable = (repo_root / ".github" / "workflows" / "reusable-build-runtime-image.yml").read_text(encoding="utf-8")
    verify = (repo_root / "tooling" / "gates" / "verify_repo_final.sh").read_text(encoding="utf-8")
    local_quality = (repo_root / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    quality = (repo_root / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    lint_frontend = (repo_root / "tooling" / "gates" / "lint_frontend.sh").read_text(encoding="utf-8")
    functional_gate = (repo_root / "tooling" / "gates" / "functional_gate.sh").read_text(encoding="utf-8")
    dual_lane_resolver = (repo_root / "tooling" / "ci" / "resolve_dual_lane_gate.sh").read_text(encoding="utf-8")
    change_detection_helper = (repo_root / "tooling" / "ci" / "detect_change_scope.sh").read_text(encoding="utf-8")
    change_detection_resolver = (repo_root / "tooling" / "ci" / "resolve_change_detection_gate.sh").read_text(encoding="utf-8")
    package_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    webui_package = json.loads((repo_root / "apps" / "webui" / "package.json").read_text(encoding="utf-8"))

    if "check_drift_audit.py" not in nightly or "check_ci_governance_regressions.py" not in nightly:
        failures.append("nightly-drift-audit.yml must keep drift + governance audit steps")
    if "actions/attest-build-provenance@" not in reusable:
        failures.append("reusable-build-runtime-image.yml must keep build provenance attestation")
    if "WEBUI_HASH_FILE" not in lint_frontend or 'npm --prefix "$REPO_ROOT/apps/webui" ci' not in lint_frontend:
        failures.append("lint_frontend.sh must keep lock-hash aware npm ci bootstrap")
    if "functional-full" in functional_gate:
        failures.append("functional_gate.sh must stay critical-smoke-only")
    if "ci:local" not in package_json.get("scripts", {}):
        failures.append("package.json must keep ci:local entrypoint")
    if "test" not in webui_package.get("scripts", {}) or "build" not in webui_package.get("scripts", {}):
        failures.append("apps/webui/package.json must keep test/build scripts")
    required_policy = (repo_root / "contracts" / "governance" / "required_checks_policy.yaml").read_text(encoding="utf-8")
    done_signal_policy = (repo_root / "contracts" / "governance" / "done_signal_policy.yaml").read_text(encoding="utf-8")
    project_positioning = (repo_root / "contracts" / "governance" / "project_positioning.yaml").read_text(encoding="utf-8")
    public_claims = (repo_root / "contracts" / "governance" / "public_claims_policy.yaml").read_text(encoding="utf-8")
    hotspot_budget = (repo_root / "contracts" / "governance" / "hotspot_budget.yaml").read_text(encoding="utf-8")
    if "failure_domain_policy:" not in required_policy or "failure_domain_reason:" not in required_policy:
        failures.append("required_checks_policy.yaml must declare failure-domain policy metadata")
    if "shared-pool-only-accepted" in required_policy:
        failures.append("required_checks_policy.yaml must not keep shared-pool-only-accepted for repo-side required jobs")
    if "hosted-primary-plus-shared-pool-fallback" in required_policy:
        failures.append("required_checks_policy.yaml must not keep shared-pool fallback as the current required-checks worldview")
    if "hosted-primary-plus-hosted-retry" not in required_policy:
        failures.append("required_checks_policy.yaml must declare hosted-primary-plus-hosted-retry for current dual-lane gates")
    if "canonical_delivery_gate:" not in done_signal_policy or "governance_scorecard_gate:" not in done_signal_policy:
        failures.append("done_signal_policy.yaml must declare canonical delivery gate and governance scorecard gate")
    if "claim_surfaces:" not in project_positioning:
        failures.append("project_positioning.yaml must declare claim_surfaces")
    if "forbidden_phrases:" not in public_claims:
        failures.append("public_claims_policy.yaml must declare forbidden_phrases")
    if "shim_guards:" not in hotspot_budget:
        failures.append("hotspot_budget.yaml must declare shim_guards")
    if "check_done_signal_claims.py" not in verify:
        failures.append("verify_repo_final.sh must keep done signal claims gate")
    if "check_positioning_claims.py" not in verify:
        failures.append("verify_repo_final.sh must keep positioning claims gate")
    if "check_docs_fragment_completeness.py" not in verify:
        failures.append("verify_repo_final.sh must keep docs fragment completeness gate")
    if "check_snapshot_scope_labels.py" not in verify:
        failures.append("verify_repo_final.sh must keep snapshot scope labels gate")
    if "check_gate_log_correlation.py" not in verify:
        failures.append("verify_repo_final.sh must keep gate log correlation gate")
    if "check_hotspot_budget.py" not in verify:
        failures.append("verify_repo_final.sh must keep hotspot budget gate")
    if "check_mcp_surface.py" not in verify:
        failures.append("verify_repo_final.sh must keep MCP surface gate")
    if "check_done_signal_claims.py" not in local_quality:
        failures.append("local_quality_gate.sh must keep done signal claims gate")
    if "check_positioning_claims.py" not in local_quality:
        failures.append("local_quality_gate.sh must keep positioning claims gate")
    if "check_docs_fragment_completeness.py" not in local_quality:
        failures.append("local_quality_gate.sh must keep docs fragment completeness gate")
    if "check_snapshot_scope_labels.py" not in local_quality:
        failures.append("local_quality_gate.sh must keep snapshot scope labels gate")
    if "check_hotspot_budget.py" not in local_quality:
        failures.append("local_quality_gate.sh must keep hotspot budget gate")
    if "check_mcp_surface.py" not in local_quality:
        failures.append("local_quality_gate.sh must keep MCP surface gate")
    if "check_done_signal_claims.py" not in quality:
        failures.append("quality_gate.sh must keep done signal claims gate")
    if "check_positioning_claims.py" not in quality:
        failures.append("quality_gate.sh must keep positioning claims gate")
    if "check_docs_fragment_completeness.py" not in quality:
        failures.append("quality_gate.sh must keep docs fragment completeness gate")
    if "check_snapshot_scope_labels.py" not in quality:
        failures.append("quality_gate.sh must keep snapshot scope labels gate")
    if "check_gate_log_correlation.py" not in quality:
        failures.append("quality_gate.sh must keep gate log correlation gate")
    if "check_hotspot_budget.py" not in quality:
        failures.append("quality_gate.sh must keep hotspot budget gate")
    if "check_mcp_surface.py" not in quality:
        failures.append("quality_gate.sh must keep MCP surface gate")
    if package_json.get("scripts", {}).get("platform:align") != "bash tooling/gates/platform_alignment_gate.sh":
        failures.append("package.json must keep platform:align entrypoint")
    if "passed on hosted primary lane" not in dual_lane_resolver or "retry passed on hosted retry lane" not in dual_lane_resolver:
        failures.append("resolve_dual_lane_gate.sh must preserve hosted primary / hosted retry success semantics")
    if "check_change_detection_scope.py" not in change_detection_helper:
        failures.append("detect_change_scope.sh must keep delegated change-detection scope evaluation")
    if "run-heavy=${primary_heavy}" not in change_detection_resolver:
        failures.append("resolve_change_detection_gate.sh must keep primary heavy output propagation")
    if "changed-count=${fallback_count}" not in change_detection_resolver:
        failures.append("resolve_change_detection_gate.sh must keep fallback changed-count propagation")

    if failures:
        print("❌ ci_governance_regressions: failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("✅ ci_governance_regressions: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
