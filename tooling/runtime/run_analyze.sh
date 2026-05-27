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
CLI_ENTRYPOINT="$REPO_ROOT/apps/cli/fileyard.py"

if [ "${MOVI_IN_CONTAINER:-0}" != "1" ] && [ "${MOVI_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label run-analyze -- bash tooling/runtime/run_analyze.sh "$@"
fi

if [ ! -f "$VENV/bin/activate" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "WARN: ffmpeg not found; audio segment sampling disabled." >&2
fi

if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1 \
  && [ ! -x "/Applications/LibreOffice.app/Contents/MacOS/soffice" ]; then
  echo "WARN: LibreOffice not found; DOCX/PPTX conversion may fail." >&2
fi

source "$VENV/bin/activate"

if [ "$#" -gt 0 ]; then
  "$VENV/bin/python" "$CLI_ENTRYPOINT" analyze "$@"
else
  MANIFEST_ROOT="$(governance_manifest_root_path "$REPO_ROOT")"
  "$VENV/bin/python" "$CLI_ENTRYPOINT" analyze \
    --input "$(governance_workspace_input_root_path "$REPO_ROOT")" \
    --manifest "$MANIFEST_ROOT/manifest.jsonl"
fi
