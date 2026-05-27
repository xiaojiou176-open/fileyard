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

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label proof-gate -- bash tooling/gates/proof_gate.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

"$VENV/bin/python" "$ROOT/scripts/check_proof_registry.py" --root "$REPO_ROOT" "$@"
status=$?
if [ "$status" -eq 0 ]; then
  echo "proof-pack guide: read docs/usage.md first, then docs/open_source_runbook.md."
  echo "upgrade-pack entrypoint: bash tooling/gates/proof_upgrade_pack.sh"
fi
exit "$status"
