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
ARTIFACT_DIR="$REPO_ROOT/.runtime-cache/logs/platform-alignment"
SUMMARY_PATH="$ARTIFACT_DIR/summary.json"
PUBLIC_LOG_REL=".runtime-cache/logs/platform-alignment/public-readiness-release.log"
REMOTE_LOG_REL=".runtime-cache/logs/platform-alignment/remote-required-checks.log"
REMOTE_JSON_REL=".runtime-cache/logs/platform-alignment/remote-required-checks.json"

mkdir -p "$ARTIFACT_DIR"
if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

GATE_NAME="platform-alignment"
GATE_RUN_ID="${GATE_NAME}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
GATE_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
GATE_START_TS="$(date +%s)"
STEP_JSONL="$ARTIFACT_DIR/.step-summary.jsonl"
: > "$STEP_JSONL"

record_step() {
  local step_name="$1"
  local status="$2"
  local started_at="$3"
  local ended_at="$4"
  local duration_ms="$5"
  local artifact_log_path="$6"
  "$VENV/bin/python" - "$STEP_JSONL" "$step_name" "$status" "$started_at" "$ended_at" "$duration_ms" "$artifact_log_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "step_name": sys.argv[2],
    "status": sys.argv[3],
    "started_at": sys.argv[4],
    "ended_at": sys.argv[5],
    "duration_ms": int(sys.argv[6]),
    "artifact_log_path": sys.argv[7],
}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
PY
}

write_summary() {
  local status="$1"
  local ended_at
  local end_ts
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  end_ts="$(date +%s)"
  local duration_ms=$(( (end_ts - GATE_START_TS) * 1000 ))
  "$VENV/bin/python" - "$STEP_JSONL" "$SUMMARY_PATH" "$GATE_RUN_ID" "$GATE_NAME" "$status" "$GATE_STARTED_AT" "$ended_at" "$duration_ms" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

step_file = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
steps = []
if step_file.exists():
    for line in step_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            steps.append(json.loads(line))
payload = {
    "gate_run_id": sys.argv[3],
    "gate_name": sys.argv[4],
    "status": sys.argv[5],
    "started_at": sys.argv[6],
    "ended_at": sys.argv[7],
    "duration_ms": int(sys.argv[8]),
    "steps": steps,
}
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

run_step() {
  local step_name="$1"
  local log_rel="$2"
  shift 2
  local log_path="$REPO_ROOT/$log_rel"
  local started_at
  local ended_at
  local start_ts
  local end_ts
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  start_ts="$(date +%s)"
  echo "=== [platform_alignment_gate] $step_name ==="
  if "$@" 2>&1 | tee "$log_path"; then
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    end_ts="$(date +%s)"
    record_step "$step_name" "pass" "$started_at" "$ended_at" $(( (end_ts - start_ts) * 1000 )) "$log_rel"
    echo "✅ [platform_alignment_gate] $step_name passed"
    return 0
  fi
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  end_ts="$(date +%s)"
  record_step "$step_name" "fail" "$started_at" "$ended_at" $(( (end_ts - start_ts) * 1000 )) "$log_rel"
  echo "❌ [platform_alignment_gate] $step_name failed"
  return 1
}

run_step public-readiness-release "$PUBLIC_LOG_REL" bash "$ROOT/gates/public_readiness_gate.sh" release || {
  write_summary fail
  exit 1
}

run_step remote-required-checks "$REMOTE_LOG_REL" "$VENV/bin/python" "$ROOT/scripts/check_remote_required_checks.py" \
  --root "$REPO_ROOT" \
  --json-out "$REMOTE_JSON_REL" || {
  write_summary fail
  exit 1
}

write_summary pass
echo "✅ platform_alignment_gate: passed"
