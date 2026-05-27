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

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label run-inbox-watch -- bash tooling/runtime/run_inbox_watch.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

source "$VENV/bin/activate"

"$VENV/bin/python" - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from packages.application.inbox_watch import scan_watch_sources_once
from packages.infrastructure.watch_source_store import load_watch_sources

workspace_root = Path(os.environ.get("FILEORGANIZE_WORKSPACE_ROOT", "~/.fileorganize/workspaces/default")).expanduser()
batches = [batch.to_dict() for batch in scan_watch_sources_once(load_watch_sources(workspace_root))]
print(json.dumps({"count": len(batches), "items": batches}, ensure_ascii=False, indent=2))
PY
