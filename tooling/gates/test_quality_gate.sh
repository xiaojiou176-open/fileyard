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

if [ "${MOVI_IN_CONTAINER:-0}" != "1" ] && [ "${MOVI_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label test-quality-gate -- bash tooling/gates/test_quality_gate.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ test_quality_gate: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

"$VENV/bin/python" "$ROOT/scripts/check_test_quality.py" --root "$REPO_ROOT"
"$VENV/bin/python" "$ROOT/scripts/check_write_before_search.py" --root "$REPO_ROOT" --mode auto
"$VENV/bin/python" "$ROOT/scripts/check_no_logs_no_merge.py" --root "$REPO_ROOT" --mode auto
