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
PYTHON_BIN="${HOST_CAPABILITY_PREFLIGHT_PYTHON:-$VENV/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

exec "$PYTHON_BIN" "$ROOT/scripts/check_upstream_host_capabilities.py" --root "$REPO_ROOT" "$@"
