#!/usr/bin/env bash
set -euo pipefail

# Pre-push gate: lightweight local verification before pushing to remote.
# Design principle: default mode should stay lightweight enough for routine push feedback.
#
# Layer responsibilities:
#   Pre-Commit (<15s): formatting, syntax, security (staged files only)
#   Pre-Push standard (<30s): minimal local burn + changed-only secret scan + commit governance
#   Pre-Push strict (<90s): local fast lane + mutation canary
#   CI (full): all checks, multi-version matrix, full security scan
#
# Modes:
#   standard (default): fast-lane + changed-only secret scan + commit governance (recommended for daily use)
#   strict: standard + mutation canary (for important branches)
#   full: strict + full quality gate (rarely needed locally)
#
# CI-matrix-smoke is REMOVED from pre-push - it belongs in CI only.
# Developers can bypass with --no-verify; CI provides full coverage as safety net.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
MODE="${1:-${FILEORGANIZE_PRE_PUSH_MODE:-standard}}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

ARTIFACT_LOGS="$(governance_runtime_logs_path "$REPO_ROOT")/pre-push-gate"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label pre-push-gate -- bash tooling/gates/pre_push_gate.sh "$@"
fi

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
  echo "⚠️ pre_push_gate: emergency host execution enabled (FILEORGANIZE_ALLOW_HOST_EXECUTION=1)." >&2
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ pre_push_gate: venv python not found: $VENV/bin/python" >&2
  echo "Run: bash tooling/runtime/bootstrap_env.sh" >&2
  exit 1
fi

mkdir -p "$ARTIFACT_LOGS"
RANGE_FLAGS=()
if [ "${FILEORGANIZE_REQUIRE_NON_EMPTY_RANGE:-0}" = "1" ]; then
  RANGE_FLAGS+=(--require-non-empty-range)
fi

check_tracked_tests_integrity() {
  if ! command -v git >/dev/null 2>&1; then
    echo "❌ pre_push_gate: git not found, cannot verify tracked tests integrity." >&2
    return 1
  fi

  local untracked
  untracked="$(
    cd "$REPO_ROOT" && {
      git ls-files --others --exclude-standard -- ':(glob)tests/**/test_*.py'
      git ls-files --others --exclude-standard -- ':(glob)tests/**/*_test.py'
    } | sed '/^[[:space:]]*$/d' | sort -u
  )"
  if [ -n "$untracked" ]; then
    echo "❌ Found untracked test files matching tests/**/test_*.py or tests/**/*_test.py:" >&2
    printf '%s\n' "$untracked" >&2
    echo "Hint: git add these tests (or remove them) before push to avoid false green." >&2
    return 1
  fi
}

step() {
  local name="$1"
  shift
  local log_file="$ARTIFACT_LOGS/${name}.log"
  echo "=== [pre_push_gate] $name ==="
  if "$@" 2>&1 | tee "$log_file"; then
    echo "✅ [pre_push_gate] $name passed"
    return 0
  fi
  echo "❌ [pre_push_gate] $name failed (log: $log_file)" >&2
  case "$name" in
    fast-lane)
      echo "Hint: fix fast lane first -> bash tooling/gates/local_quality_gate.sh fast" >&2
      ;;
    atomic-commit)
      echo "Hint: keep future pushes reviewable -> start from current main and replay work as smaller commits; inspect with $VENV/bin/python tooling/scripts/check_atomic_commits.py" >&2
      ;;
    commit-message)
      echo "Hint: use Conventional Commits -> $VENV/bin/python tooling/scripts/check_commit_message.py --pre-push-auto" >&2
      ;;
    secret-scan-changed)
      echo "Hint: run incremental secret scan -> bash tooling/gates/secret_scan.sh --changed-only ." >&2
      ;;
    sensitive-surface)
      echo "Hint: run tracked privacy/path scan -> bash tooling/gates/sensitive_surface_gate.sh --mode auto" >&2
      ;;
    feature-state-layout)
      echo "Hint: durable workbench state must stay under <workspace-root>/.fileorganize, not repo root or repo runtime cache." >&2
      ;;
    strategy-pack-registry)
      echo "Hint: repo-shipped strategy packs must stay valid under contracts/strategies." >&2
      ;;
    watch-sources-contract)
      echo "Hint: watch source state must remain a workspace-local preference surface." >&2
      ;;
    tracked-tests-integrity)
      echo "Hint: stage/add test files first -> git add tests/**/test_*.py tests/**/*_test.py" >&2
      ;;
    mutation-canary)
      echo "Hint: check mutation test coverage -> $VENV/bin/python tooling/scripts/check_mutation_canary.py --repo-root ." >&2
      ;;
    legacy-sweep)
      echo "Hint: remove old tree aliases, repo-root env/bootstrap leftovers, root mutation-cache alias, and legacy module strings from active surfaces." >&2
      ;;
    full-quality-gate)
      echo "Hint: run full local gate -> bash tooling/gates/quality_gate.sh" >&2
      ;;
  esac
  return 1
}

case "$MODE" in
  standard)
    echo "🚦 pre-push policy(mode=standard): prepush-lite lane + changed-only secret scan + commit governance."
    echo "   Expected time: <30s for typical changes."
    step prepush-lite bash "$ROOT/gates/local_quality_gate.sh" prepush-lite
    step legacy-sweep "$VENV/bin/python" "$ROOT/scripts/check_active_legacy_sweep.py" --root "$REPO_ROOT"
    step secret-scan-changed bash "$ROOT/gates/secret_scan.sh" --changed-only "$REPO_ROOT"
    step tracked-tests-integrity check_tracked_tests_integrity
    step atomic-commit "$VENV/bin/python" "$ROOT/scripts/check_atomic_commits.py" --pre-push-auto ${RANGE_FLAGS[@]+"${RANGE_FLAGS[@]}"}
    step commit-message "$VENV/bin/python" "$ROOT/scripts/check_commit_message.py" --pre-push-auto ${RANGE_FLAGS[@]+"${RANGE_FLAGS[@]}"}
    ;;
  strict)
    echo "🚦 pre-push policy(mode=strict): fast lane + changed-only secret scan + commit governance + mutation canary."
    echo "   Expected time: <90s for typical changes."
    step fast-lane bash "$ROOT/gates/local_quality_gate.sh" fast
    step legacy-sweep "$VENV/bin/python" "$ROOT/scripts/check_active_legacy_sweep.py" --root "$REPO_ROOT"
    step secret-scan-changed bash "$ROOT/gates/secret_scan.sh" --changed-only "$REPO_ROOT"
    step tracked-tests-integrity check_tracked_tests_integrity
    step atomic-commit "$VENV/bin/python" "$ROOT/scripts/check_atomic_commits.py" --pre-push-auto ${RANGE_FLAGS[@]+"${RANGE_FLAGS[@]}"}
    step commit-message "$VENV/bin/python" "$ROOT/scripts/check_commit_message.py" --pre-push-auto ${RANGE_FLAGS[@]+"${RANGE_FLAGS[@]}"}
    step mutation-canary "$VENV/bin/python" "$ROOT/scripts/check_mutation_canary.py" --repo-root "$REPO_ROOT"
    ;;
  full)
    echo "🚦 pre-push policy(mode=full): strict + full quality gate."
    echo "   Expected time: 5-15min (use sparingly)."
    step fast-lane bash "$ROOT/gates/local_quality_gate.sh" fast
    step legacy-sweep "$VENV/bin/python" "$ROOT/scripts/check_active_legacy_sweep.py" --root "$REPO_ROOT"
    step secret-scan-changed bash "$ROOT/gates/secret_scan.sh" --changed-only "$REPO_ROOT"
    step tracked-tests-integrity check_tracked_tests_integrity
    step atomic-commit "$VENV/bin/python" "$ROOT/scripts/check_atomic_commits.py" --pre-push-auto ${RANGE_FLAGS[@]+"${RANGE_FLAGS[@]}"}
    step commit-message "$VENV/bin/python" "$ROOT/scripts/check_commit_message.py" --pre-push-auto ${RANGE_FLAGS[@]+"${RANGE_FLAGS[@]}"}
    step mutation-canary "$VENV/bin/python" "$ROOT/scripts/check_mutation_canary.py" --repo-root "$REPO_ROOT"
    step full-quality-gate bash "$ROOT/gates/quality_gate.sh"
    ;;
  *)
    echo "Usage: bash tooling/gates/pre_push_gate.sh [standard|strict|full]" >&2
    echo "" >&2
    echo "Modes:" >&2
    echo "  standard (default): prepush-lite lane + changed-only secret scan + commit governance (<30s)" >&2
    echo "  strict: fast lane + changed-only secret scan + commit governance + mutation canary (<90s)" >&2
    echo "  full: strict + full quality gate (5-15min)" >&2
    echo "" >&2
    echo "Set FILEORGANIZE_PRE_PUSH_MODE env var to change default." >&2
    exit 2
    ;;
esac

echo "✅ pre_push_gate: mode=$MODE passed, safe to push."
echo ""
echo "Note: CI will run full checks including:"
echo "  - Multi-version Python matrix (3.10/3.11/3.12)"
echo "  - Full security scan (gitleaks + detect-secrets)"
echo "  - Full test suite with coverage"
echo "  - Supply chain audit (pip-audit)"
