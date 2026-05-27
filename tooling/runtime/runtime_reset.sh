#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"

usage() {
  cat <<'EOF'
Usage: bash tooling/runtime/runtime_reset.sh --confirm-workspace-reset

Destructive workspace reset:
- prunes repo-local runtime residue
- clears workspace .fileman state via tooling/runtime/reset_workspace_state.sh

This is not a general cache cleanup command.
EOF
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if [ "${1:-}" != "--confirm-workspace-reset" ] || [ "$#" -ne 1 ]; then
  echo "❌ runtime_reset: refusing destructive workspace reset without --confirm-workspace-reset" >&2
  echo "This command will clear workspace .fileman state via tooling/runtime/reset_workspace_state.sh." >&2
  echo "Use repo-local cleanup or machine-cache cleanup for non-destructive disk maintenance." >&2
  usage >&2
  exit 2
fi

bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT"
bash "$ROOT/runtime/reset_workspace_state.sh"

echo "runtime reset complete"
