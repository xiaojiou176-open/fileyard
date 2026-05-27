#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

cd "$REPO_ROOT"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

mkdir -p .runtime-cache/logs
export PYTHONDONTWRITEBYTECODE=1

bash tooling/runtime/bootstrap_env.sh
bash tooling/cleanup/prune_repo_runtime.sh
governance_python "$REPO_ROOT" tooling/scripts/generate_api_contract.py
if ! bash tooling/scripts/check_runner_capabilities.sh; then
  echo "❌ ci_local: environment blocked before repo-side checks; fix runner capabilities first." >&2
  exit 1
fi
governance_python "$REPO_ROOT" tooling/scripts/check_runner_inventory.py --mock
bash tooling/runtime/run_webui_task.sh ci-install
FILEMAN_ALLOW_HOST_EXECUTION=1 LINT_FRONTEND_SKIP_GEMINI_AUDIT=1 bash tooling/gates/lint_frontend.sh
bash tooling/runtime/run_webui_task.sh test
bash tooling/runtime/run_webui_task.sh build
bash tooling/gates/local_ci_matrix_gate.sh
FILEMAN_ALLOW_HOST_EXECUTION=1 bash tooling/gates/functional_gate.sh
bash tooling/docs/docs_smoke.sh --install-smoke
bash tooling/cleanup/prune_repo_runtime.sh
governance_python "$REPO_ROOT" tooling/scripts/check_ci_workflow_hardening.py --workflow .github/workflows/ci.yml | tee .runtime-cache/logs/ci-hardening.local.log
governance_python "$REPO_ROOT" tooling/scripts/collect_ci_run_metrics.py --output .runtime-cache/logs/ci-run-metrics.local.json
governance_python "$REPO_ROOT" tooling/scripts/generate_ci_evidence_bundle.py --artifacts-root .runtime-cache --output .runtime-cache/logs/evidence-bundle.local.json
bash tooling/upstreams/refresh_receipts.sh --bundle .runtime-cache/logs/evidence-bundle.local.json
cp .runtime-cache/logs/evidence-bundle.local.json .runtime-cache/ci/evidence-bundle.json
governance_python "$REPO_ROOT" tooling/scripts/check_upstream_verification_freshness.py --root .
bash tooling/gates/verify_repo_final.sh
bash tooling/cleanup/prune_repo_runtime.sh
governance_python "$REPO_ROOT" tooling/scripts/check_repo_runtime_residue.py --root .
