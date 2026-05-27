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
CLI_ENTRYPOINT="$REPO_ROOT/apps/cli/fileorganize.py"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label run-rollback -- bash tooling/runtime/run_rollback.sh "$@"
fi

if [ ! -f "$VENV/bin/activate" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

DEFAULT_ALLOWED_ROOT="$(governance_workspace_input_root_path "$REPO_ROOT"),$(governance_workspace_output_root_path "$REPO_ROOT")"
HAS_ALLOWED_ROOT=0
for arg in "$@"; do
  case "$arg" in
    --allowed-root|--allowed-root=*)
      HAS_ALLOWED_ROOT=1
      break
      ;;
  esac
done

if [ "$#" -gt 0 ]; then
  if [ "$HAS_ALLOWED_ROOT" -eq 1 ]; then
    "$VENV/bin/python" "$CLI_ENTRYPOINT" rollback "$@"
  else
    "$VENV/bin/python" "$CLI_ENTRYPOINT" rollback \
      --allowed-root "$DEFAULT_ALLOWED_ROOT" \
      "$@"
  fi
else
  MANIFEST_ROOT="$(governance_manifest_root_path "$REPO_ROOT")"
  "$VENV/bin/python" "$CLI_ENTRYPOINT" rollback \
    --manifest "$MANIFEST_ROOT/manifest.jsonl" \
    --allowed-root "$DEFAULT_ALLOWED_ROOT" \
    --dry-run
fi
