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

PYTHON_BIN="$(governance_runtime_venv_path "$REPO_ROOT")/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh" >/dev/null
fi
PYTHON_BIN="$(governance_runtime_venv_path "$REPO_ROOT")/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

"$PYTHON_BIN" "$ROOT/scripts/check_sensitive_surface.py" --root "$REPO_ROOT" "$@"

echo "✅ sensitive_surface_gate: passed"
