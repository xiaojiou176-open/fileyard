#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
export PYTHONDONTWRITEBYTECODE=1
VERIFY_GATE_RUN_ID="${VERIFY_REPO_FINAL_FORCED_RUN_ID:-verify-repo-final-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
GATE_LOG_ARGS=(--root "$REPO_ROOT" --allow-missing-gate platform-alignment)

echo "ℹ️ verify_repo_final: repo-side governance scorecard only; use bash tooling/gates/quality_gate.sh for delivery-complete truth"
bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
  GATE_LOG_ARGS+=(--gate quality-gate --summary-path ".runtime-cache/logs/quality-gate/host-summary.json")
fi

governance_python "$REPO_ROOT" "$ROOT/scripts/check_root_layout.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_root_clean_after_mainflows.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_root_public_surface.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_root_change_control.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_collaboration_surface.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_english_canonical_surface.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_runtime_language_boundary.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_public_artifact_safety.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_sensitive_surface.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_local_only_tracking.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_feature_state_layout.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/generate_api_contract.py" --check
governance_python "$REPO_ROOT" "$ROOT/scripts/check_mcp_surface.py"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_strategy_pack_registry.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_watch_sources_contract.py"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_module_graph.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_dependency_boundaries.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_runtime_layout.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_repo_runtime_residue.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_runtime_budget.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_logging_contract.py" --root "$REPO_ROOT" --gate-run-id "$VERIFY_GATE_RUN_ID" --gate-name "verify-repo-final"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_gate_log_correlation.py" "${GATE_LOG_ARGS[@]}"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_run_bundle_contract.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_registry_completeness.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_patch_registry_alignment.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_fetch_surfaces.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_compat_matrix.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_verification_freshness.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_receipts.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_host_capabilities.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_no_private_upstream_coupling.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_upstream_drift.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_docs_render_state.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_docs_fragment_completeness.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_docs_truth_routes.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_snapshot_scope_labels.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_cold_start_rebuild.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_done_signal_claims.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_positioning_claims.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/check_hotspot_budget.py" --root "$REPO_ROOT"
governance_python "$REPO_ROOT" "$ROOT/scripts/score_repo_governance.py" --root "$REPO_ROOT" --strict
