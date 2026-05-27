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

ARTIFACT_LOGS="$(governance_runtime_logs_path "$REPO_ROOT")/lint-backend"

MODE="serial"
if [ "${1:-}" = "--parallel" ]; then
  MODE="parallel"
fi

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label lint-backend -- bash tooling/gates/lint_backend.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ lint_backend: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

mkdir -p "$ARTIFACT_LOGS"

cleanup_bg_jobs() {
  local pids
  pids="$(jobs -pr 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return 0
  fi
  kill $pids 2>/dev/null || true
  sleep 1
  kill -s KILL $pids 2>/dev/null || true
  for pid in $pids; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup_bg_jobs EXIT INT TERM

run_step() {
  local name="$1"
  shift
  echo "=== [lint_backend] $name ==="
  if "$@" 2>&1 | tee "$ARTIFACT_LOGS/${name}.log"; then
    echo "✅ [lint_backend] $name passed"
    return 0
  fi
  echo "❌ [lint_backend] $name failed"
  return 1
}

failed_steps=()

if [ "$MODE" = "parallel" ]; then
  echo "=== [lint_backend] parallel mode ==="

  pids=()
  names=()
  names+=("ruff")
  (
    set +e
    "$VENV/bin/python" -m ruff check apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability tooling/scripts tests 2>&1 | tee "$ARTIFACT_LOGS/ruff.log"
    exit ${PIPESTATUS[0]}
  ) &
  pids+=("$!")

  names+=("mypy")
  (
    set +e
    "$VENV/bin/python" -m mypy apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability 2>&1 | tee "$ARTIFACT_LOGS/mypy.log"
    exit ${PIPESTATUS[0]}
  ) &
  pids+=("$!")

  names+=("bandit")
  (
    set +e
    "$VENV/bin/python" -m bandit -r apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability --severity-level high --confidence-level high 2>&1 | tee "$ARTIFACT_LOGS/bandit.log"
    bandit_rc=${PIPESTATUS[0]}
    if [ "$bandit_rc" -eq 0 ] && grep -Eq "Bandit internal error|exception while scanning file|Files skipped \([1-9][0-9]*\)" "$ARTIFACT_LOGS/bandit.log"; then
      echo "❌ [lint_backend] bandit reported internal scan errors/skipped files; treat as failed gate"
      exit 1
    fi
    exit "$bandit_rc"
  ) &
  pids+=("$!")

  for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
      echo "✅ [lint_backend] ${names[$i]} passed"
    else
      echo "❌ [lint_backend] ${names[$i]} failed"
      failed_steps+=("${names[$i]}")
    fi
  done
else
  run_step ruff "$VENV/bin/python" -m ruff check apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability tooling/scripts tests || failed_steps+=("ruff")
  run_step mypy "$VENV/bin/python" -m mypy apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability || failed_steps+=("mypy")
  echo "=== [lint_backend] bandit ==="
  set +e
  "$VENV/bin/python" -m bandit -r apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability --severity-level high --confidence-level high 2>&1 | tee "$ARTIFACT_LOGS/bandit.log"
  bandit_rc=${PIPESTATUS[0]}
  set -e
  if [ "$bandit_rc" -eq 0 ] && grep -Eq "Bandit internal error|exception while scanning file|Files skipped \([1-9][0-9]*\)" "$ARTIFACT_LOGS/bandit.log"; then
    echo "❌ [lint_backend] bandit reported internal scan errors/skipped files; treat as failed gate"
    bandit_rc=1
  fi
  if [ "$bandit_rc" -eq 0 ]; then
    echo "✅ [lint_backend] bandit passed"
  else
    echo "❌ [lint_backend] bandit failed"
    failed_steps+=("bandit")
  fi
fi

if [ "${#failed_steps[@]}" -gt 0 ]; then
  echo "❌ lint_backend: failed steps: ${failed_steps[*]}" >&2
  exit 1
fi

echo "✅ lint_backend: all checks passed"
