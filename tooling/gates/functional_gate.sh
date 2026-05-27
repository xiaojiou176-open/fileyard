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
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

ARTIFACT_LOGS="$(governance_runtime_logs_path "$REPO_ROOT")/functional-gate"
RUNTIME_CI_DIR="$(governance_runtime_ci_path "$REPO_ROOT")"

# Functional gate is a targeted critical-smoke sibling to quality_gate/pre-push.
# Full non-live e2e/integration truth lives in quality_gate; this script keeps a
# smaller, high-signal regression set with heartbeat-friendly logs.
if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label functional-gate -- bash tooling/gates/functional_gate.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ functional_gate: venv python not found: $VENV/bin/python" >&2
  echo "Run: bash tooling/scripts/bootstrap_env.sh" >&2
  exit 1
fi

mkdir -p "$ARTIFACT_LOGS"

run_step() {
  local name="$1"
  shift
  local log_file="$ARTIFACT_LOGS/${name}.log"
  echo "=== [functional_gate] $name ==="
  if "$@" 2>&1 | tee "$log_file"; then
    echo "✅ [functional_gate] $name passed"
    return 0
  fi
  echo "❌ [functional_gate] $name failed (log: $log_file)" >&2
  return 1
}

STRICT_WARNINGS=(
  "-W" "error"
  "-W" "ignore:.*_UnionGenericAlias.*:DeprecationWarning:google.genai.types"
)

CRITICAL_TESTS=(
  "tests/e2e/test_full_pipeline_offline.py"
  "tests/e2e/test_apply_rollback_manifest.py"
  "tests/e2e/test_apply_wal_crash_recovery_cli.py"
  "tests/e2e/test_cli_e2e.py"
  "tests/integration/test_offline_analyze_apply_flow.py"
  "tests/integration/test_apply_rollback_resilience.py"
)

for test_path in "${CRITICAL_TESTS[@]}"; do
  if [ ! -f "$REPO_ROOT/$test_path" ]; then
    echo "❌ functional_gate: missing critical test file: $test_path" >&2
    exit 1
  fi
done

run_step functional-critical \
  env PYTEST_HEARTBEAT_NAME=functional-critical \
  bash "$ROOT/scripts/run_pytest_with_heartbeat.sh" "$VENV/bin/python" -m pytest -q -o addopts= --maxfail=1 --strict-config --strict-markers \
  "${STRICT_WARNINGS[@]}" \
  --junitxml="$RUNTIME_CI_DIR/pytest-functional-critical-junit.xml" \
  "${CRITICAL_TESTS[@]}"

echo "✅ functional_gate: critical smoke checks passed"
