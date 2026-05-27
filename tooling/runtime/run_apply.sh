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
CLI_ENTRYPOINT="$REPO_ROOT/apps/cli/fileman.py"

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label run-apply -- bash tooling/runtime/run_apply.sh "$@"
fi

if [ ! -f "$VENV/bin/activate" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

source "$VENV/bin/activate"

if [ "$#" -gt 0 ]; then
  "$VENV/bin/python" "$CLI_ENTRYPOINT" apply "$@"
else
  MANIFEST_ROOT="$(governance_manifest_root_path "$REPO_ROOT")"
  "$VENV/bin/python" "$CLI_ENTRYPOINT" apply \
    --manifest "$MANIFEST_ROOT/manifest.jsonl" \
    --input-root "$(governance_workspace_input_root_path "$REPO_ROOT")" \
    --verify-sha1 \
    --dry-run
fi
