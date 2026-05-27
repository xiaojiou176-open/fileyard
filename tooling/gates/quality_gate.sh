#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-30}"
QUALITY_GATE_MAX_STEP_SECONDS="${QUALITY_GATE_MAX_STEP_SECONDS:-0}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"
RUNTIME_ENV_FILE="$(governance_runtime_env_file_path "$REPO_ROOT")"

ARTIFACT_LOGS="$(governance_runtime_logs_path "$REPO_ROOT")/quality-gate"
RUNTIME_CI_DIR="$(governance_runtime_ci_path "$REPO_ROOT")"
GATE_NAME="quality-gate"
GATE_RUN_ID="${QUALITY_GATE_FORCED_RUN_ID:-${GATE_NAME}-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
GATE_STARTED_AT="${QUALITY_GATE_FORCED_STARTED_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
GATE_START_TS="${QUALITY_GATE_FORCED_START_TS:-$(date +%s)}"
ARTIFACT_LOGS_REL=".runtime-cache/logs/quality-gate"
RUN_ARTIFACT_REL_DIR="$ARTIFACT_LOGS_REL/runs/$GATE_RUN_ID"
RUN_ARTIFACT_DIR="$REPO_ROOT/$RUN_ARTIFACT_REL_DIR"
RUN_SUMMARY_REL_PATH="$RUN_ARTIFACT_REL_DIR/summary.json"
RUN_SUMMARY_PATH="$REPO_ROOT/$RUN_SUMMARY_REL_PATH"
RUN_STEP_SUMMARY_REL_PATH="$RUN_ARTIFACT_REL_DIR/.step-summary.jsonl"
RUN_STEP_SUMMARY_PATH="$REPO_ROOT/$RUN_STEP_SUMMARY_REL_PATH"

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
  GATE_EXECUTION_MODE="host-emergency"
  LATEST_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/host-summary.json"
  LATEST_STEP_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/.host-step-summary.jsonl"
  LATEST_LOG_PREFIX="host-"
  IS_CANONICAL_SIGNAL=0
else
  GATE_EXECUTION_MODE="canonical-container"
  LATEST_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/summary.json"
  LATEST_STEP_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/.step-summary.jsonl"
  LATEST_LOG_PREFIX=""
  IS_CANONICAL_SIGNAL=1
fi

LATEST_SUMMARY_PATH="$REPO_ROOT/$LATEST_SUMMARY_REL_PATH"
LATEST_STEP_SUMMARY_PATH="$REPO_ROOT/$LATEST_STEP_SUMMARY_REL_PATH"

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ quality_gate: venv python not found: $VENV/bin/python" >&2
  echo "Run: bash tooling/runtime/bootstrap_env.sh" >&2
  exit 1
fi

mkdir -p "$ARTIFACT_LOGS"
mkdir -p "$RUNTIME_CI_DIR"
mkdir -p "$RUN_ARTIFACT_DIR"
: > "$RUN_STEP_SUMMARY_PATH"
bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true
mkdir -p "${PLAYWRIGHT_BROWSERS_PATH:-}" "${NPM_CONFIG_CACHE:-}" "${PIP_CACHE_DIR:-}" "${XDG_CACHE_HOME:-}"

cleanup_coverage_artifacts() {
  # coverage.xml is the only gate truth source; remove ambiguous snapshot files.
  find "$RUNTIME_CI_DIR" -maxdepth 1 -type f -name "coverage-*.xml" \
    ! -name "coverage-debug-*.xml" -delete 2>/dev/null || true
  rm -f "$RUNTIME_CI_DIR/coverage.xml"
  rm -f "$REPO_ROOT/.runtime-cache/test/coverage/coverage.xml"
  find "$REPO_ROOT/.runtime-cache/test/coverage" -maxdepth 1 -type f -name '.coverage*' -delete 2>/dev/null || true
}

normalize_coverage_artifact() {
  if [ -f "$RUNTIME_CI_DIR/coverage.xml" ]; then
    return 0
  fi
  local fallback_coverage_xml="$REPO_ROOT/.runtime-cache/test/coverage/coverage.xml"
  if [ -f "$fallback_coverage_xml" ]; then
    cp "$fallback_coverage_xml" "$RUNTIME_CI_DIR/coverage.xml"
    return 0
  fi
  local fallback_coverage_dir="$REPO_ROOT/.runtime-cache/test/coverage"
  if find "$fallback_coverage_dir" -maxdepth 1 -type f -name '.coverage*' -print -quit | grep -q .; then
    (
      cd "$fallback_coverage_dir"
      COVERAGE_FILE="$fallback_coverage_dir/.coverage" "$VENV/bin/python" -m coverage combine "$fallback_coverage_dir" >/dev/null
      COVERAGE_FILE="$fallback_coverage_dir/.coverage" "$VENV/bin/python" -m coverage xml -o "$RUNTIME_CI_DIR/coverage.xml" >/dev/null
    ) && [ -f "$RUNTIME_CI_DIR/coverage.xml" ] && return 0
  fi
  return 1
}

run_post_mutation_cache_hygiene() {
  # Mutation canary intentionally edits source files. Clear repo/runtime bytecode
  # residue before the full suite so restored sources are re-imported cleanly.
  bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true
  bash "$ROOT/cleanup/prune_machine_cache.sh" --safe >/dev/null 2>&1 || true
  mkdir -p "$RUNTIME_CI_DIR"
}

run_mutation_canary_in_repo_snapshot() {
  local snapshot_root
  # Keep the mutation snapshot outside repo-local runtime roots so hygiene
  # cleanup cannot prune the snapshot while the canary subprocess is still
  # walking it.
  snapshot_root="$(mktemp -d "/tmp/fileman-mutation-snapshot.XXXXXX")"
  (
    cd "$REPO_ROOT"
    tar \
      --exclude=.git \
      --exclude=.runtime-cache \
      --exclude=.pytest_cache \
      --exclude=.mypy_cache \
      --exclude=.ruff_cache \
      --exclude=apps/webui/node_modules \
      -cf - .
  ) | (
    cd "$snapshot_root"
    tar -xf -
  )
  local rc=0
  (
    cd "$snapshot_root"
    "$VENV/bin/python" "$ROOT/scripts/check_mutation_canary.py" --repo-root "$snapshot_root"
  ) || rc=$?
  rm -rf "$snapshot_root"
  return "$rc"
}

cleanup_bg_jobs() {
  local pids
  pids="$(jobs -pr 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return 0
  fi
  kill $pids 2>/dev/null || true
  sleep 1
  kill -s KILL $pids 2>/dev/null || true
  for pid in $pids; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup_bg_jobs EXIT INT TERM

resolve_receipt_python() {
  if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -V >/dev/null 2>&1; then
    printf '%s' "$VENV/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  echo "❌ quality_gate: no python available for receipt writing" >&2
  return 1
}

run_receipt_python() {
  local receipt_python
  receipt_python="$(resolve_receipt_python)"
  "$receipt_python" "$@"
}

record_step_summary() {
  local step_name="$1"
  local status="$2"
  local started_at="$3"
  local ended_at="$4"
  local duration_ms="$5"
  local artifact_log_path="$6"
  run_receipt_python - "$RUN_STEP_SUMMARY_PATH" "$step_name" "$status" "$started_at" "$ended_at" "$duration_ms" "$artifact_log_path" <<'PY'
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

write_gate_summary() {
  local status="$1"
  local ended_at
  local end_ts
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  end_ts="$(date +%s)"
  local duration_ms=$(( (end_ts - GATE_START_TS) * 1000 ))
  run_receipt_python - "$RUN_STEP_SUMMARY_PATH" "$RUN_SUMMARY_PATH" "$GATE_RUN_ID" "$GATE_NAME" "$status" "$GATE_STARTED_AT" "$ended_at" "$duration_ms" "$GATE_EXECUTION_MODE" "$RUN_ARTIFACT_REL_DIR" "$RUN_SUMMARY_REL_PATH" "$RUN_STEP_SUMMARY_REL_PATH" "$LATEST_SUMMARY_REL_PATH" "$LATEST_STEP_SUMMARY_REL_PATH" "$IS_CANONICAL_SIGNAL" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

steps_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
steps = []
if steps_path.exists():
    for line in steps_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            steps.append(json.loads(line))
payload = {
    "gate_run_id": sys.argv[3],
    "gate_name": sys.argv[4],
    "status": sys.argv[5],
    "started_at": sys.argv[6],
    "ended_at": sys.argv[7],
    "duration_ms": int(sys.argv[8]),
    "execution_mode": sys.argv[9],
    "receipt_dir": sys.argv[10],
    "summary_path": sys.argv[11],
    "step_summary_path": sys.argv[12],
    "latest_summary_path": sys.argv[13],
    "latest_step_summary_path": sys.argv[14],
    "is_canonical_signal": sys.argv[15] == "1",
    "steps": steps,
}
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  sync_receipt_alias "$RUN_SUMMARY_PATH" "$LATEST_SUMMARY_PATH"
  sync_receipt_alias "$RUN_STEP_SUMMARY_PATH" "$LATEST_STEP_SUMMARY_PATH"
}

read_runtime_env_value() {
  local name="$1"
  "$VENV/bin/python" - "$RUNTIME_ENV_FILE" "$name" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
name = sys.argv[2]
if not env_path.exists():
    raise SystemExit(0)
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != name:
        continue
    parsed = value.strip()
    if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {'"', "'"}:
        parsed = parsed[1:-1]
    print(parsed.strip())
    raise SystemExit(0)
PY
}

resolve_var_prefer_runtime_env() {
  local name="$1"
  local default="${2:-}"
  local value=""
  value="${!name:-}"
  if [ -z "$value" ]; then
    value="$(read_runtime_env_value "$name")"
  fi
  if [ -z "$value" ]; then
    value="$default"
  fi
  export "$name=$value"
}

resolve_var_prefer_env_then_runtime_env() {
  local name="$1"
  local default="${2:-}"
  local value="${!name:-}"
  if [ -z "$value" ]; then
    value="$(read_runtime_env_value "$name")"
  fi
  if [ -z "$value" ]; then
    value="$default"
  fi
  export "$name=$value"
}

sync_receipt_alias() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

step_run_log_rel_path() {
  local name="$1"
  printf '%s/%s.log' "$RUN_ARTIFACT_REL_DIR" "$name"
}

step_latest_log_rel_path() {
  local name="$1"
  printf '%s/%s%s.log' "$ARTIFACT_LOGS_REL" "$LATEST_LOG_PREFIX" "$name"
}

sync_step_receipts() {
  local name="$1"
  local run_log_path="$RUN_ARTIFACT_DIR/${name}.log"
  local latest_log_path="$REPO_ROOT/$(step_latest_log_rel_path "$name")"
  sync_receipt_alias "$run_log_path" "$latest_log_path"
  sync_receipt_alias "$RUN_STEP_SUMMARY_PATH" "$LATEST_STEP_SUMMARY_PATH"
}

run_canonical_container_wrapper() {
  local bootstrap_log="$RUN_ARTIFACT_DIR/container-bootstrap.log"
  local bootstrap_latest_log="$REPO_ROOT/$(step_latest_log_rel_path container-bootstrap)"
  set +e
  env QUALITY_GATE_CONTAINER_BOOTSTRAPPED=1 \
    QUALITY_GATE_FORCED_RUN_ID="$GATE_RUN_ID" \
    QUALITY_GATE_FORCED_STARTED_AT="$GATE_STARTED_AT" \
    QUALITY_GATE_FORCED_START_TS="$GATE_START_TS" \
    bash "$ROOT/scripts/container_exec.sh" --label quality-gate -- \
      env QUALITY_GATE_CONTAINER_BOOTSTRAPPED=1 \
      QUALITY_GATE_FORCED_RUN_ID="$GATE_RUN_ID" \
      QUALITY_GATE_FORCED_STARTED_AT="$GATE_STARTED_AT" \
      QUALITY_GATE_FORCED_START_TS="$GATE_START_TS" \
      bash tooling/gates/quality_gate.sh "$@" 2>&1 | tee "$bootstrap_log"
  local wrapper_rc=${PIPESTATUS[0]}
  set -e

  if [ -f "$RUN_SUMMARY_PATH" ]; then
    return "$wrapper_rc"
  fi

  local ended_at
  local end_ts
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  end_ts="$(date +%s)"
  record_step_summary "container-bootstrap" "fail" "$GATE_STARTED_AT" "$ended_at" $(( (end_ts - GATE_START_TS) * 1000 )) "$RUN_ARTIFACT_REL_DIR/container-bootstrap.log"
  sync_receipt_alias "$bootstrap_log" "$bootstrap_latest_log"
  sync_receipt_alias "$RUN_STEP_SUMMARY_PATH" "$LATEST_STEP_SUMMARY_PATH"
  write_gate_summary fail
  return "$wrapper_rc"
}

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ] && [ "${QUALITY_GATE_CONTAINER_BOOTSTRAPPED:-0}" != "1" ]; then
  run_canonical_container_wrapper "$@"
  exit $?
fi

run_step() {
  local name="$1"
  shift
  local log_path="$RUN_ARTIFACT_DIR/${name}.log"
  local log_rel_path
  log_rel_path="$(step_run_log_rel_path "$name")"
  local started_at
  local ended_at
  local start_ts
  local end_ts
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  start_ts="$(date +%s)"
  echo "=== [quality_gate] $name ==="
  if "$@" 2>&1 | tee "$log_path"; then
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    end_ts="$(date +%s)"
    record_step_summary "$name" "pass" "$started_at" "$ended_at" $(( (end_ts - start_ts) * 1000 )) "$log_rel_path"
    sync_step_receipts "$name"
    echo "✅ [quality_gate] $name passed"
    return 0
  fi
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  end_ts="$(date +%s)"
  record_step_summary "$name" "fail" "$started_at" "$ended_at" $(( (end_ts - start_ts) * 1000 )) "$log_rel_path"
  sync_step_receipts "$name"
  echo "❌ [quality_gate] $name failed"
  return 1
}

run_step_with_heartbeat() {
  local name="$1"
  shift
  local log_file="$RUN_ARTIFACT_DIR/${name}.log"
  local log_rel_path
  log_rel_path="$(step_run_log_rel_path "$name")"
  local start_ts
  local timed_out=0
  local last_progress=""
  local started_at
  local ended_at
  start_ts="$(date +%s)"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  echo "=== [quality_gate] $name ==="
  set +e
  (
    "$@"
  ) >"$log_file" 2>&1 &
  local step_pid=$!

  while kill -0 "$step_pid" 2>/dev/null; do
    sleep "$HEARTBEAT_INTERVAL_SECONDS"
    if kill -0 "$step_pid" 2>/dev/null; then
      local now_ts elapsed
      now_ts="$(date +%s)"
      elapsed=$((now_ts - start_ts))
      current_progress="$(tail -n 1 "$log_file" 2>/dev/null | tr -d '\r' || true)"
      if [ -z "$current_progress" ]; then
        current_progress="(no-output-yet)"
      fi
      if [ "$current_progress" != "$last_progress" ]; then
        last_progress="$current_progress"
      fi
      echo "[quality_gate][heartbeat] $name still running (${elapsed}s elapsed) progress=${last_progress}"

      if [ "$QUALITY_GATE_MAX_STEP_SECONDS" -gt 0 ] && [ "$elapsed" -ge "$QUALITY_GATE_MAX_STEP_SECONDS" ]; then
        echo "❌ [quality_gate] $name exceeded QUALITY_GATE_MAX_STEP_SECONDS=${QUALITY_GATE_MAX_STEP_SECONDS}, terminating pid=${step_pid}" >&2
        timed_out=1
        kill "$step_pid" 2>/dev/null || true
        sleep 1
        kill -s KILL "$step_pid" 2>/dev/null || true
        break
      fi
    fi
  done

  wait "$step_pid"
  local rc=$?
  set -e
  cat "$log_file"
  if [ "$timed_out" -eq 1 ]; then
    rc=124
  fi
  if [ "$rc" -eq 0 ]; then
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    record_step_summary "$name" "pass" "$started_at" "$ended_at" $(( ($(date +%s) - start_ts) * 1000 )) "$log_rel_path"
    sync_step_receipts "$name"
    echo "✅ [quality_gate] $name passed"
    return 0
  fi

  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  record_step_summary "$name" "fail" "$started_at" "$ended_at" $(( ($(date +%s) - start_ts) * 1000 )) "$log_rel_path"
  sync_step_receipts "$name"
  echo "❌ [quality_gate] $name failed"
  return 1
}

run_pytest_with_isolated_tmp() {
  local tmp_root="${XDG_CACHE_HOME:-$HOME/.cache}/pytest-runtime"
  mkdir -p "$tmp_root"
  local isolated_tmp
  isolated_tmp="$(mktemp -d "$tmp_root/run.XXXXXX")"
  local rc=0
  (
    export TMPDIR="$isolated_tmp"
    export TMP="$isolated_tmp"
    export TEMP="$isolated_tmp"
    "$@"
  )
  rc=$?
  rm -rf "$isolated_tmp"
  return "$rc"
}

run_parallel_short_checks() {
  local secret_log="$RUN_ARTIFACT_DIR/secret-scan.log"
  local docs_log="$RUN_ARTIFACT_DIR/docs-smoke.log"
  local secret_pid docs_pid
  local secret_code docs_code

  # Canonical remote short-check truth: downstream CI jobs should consume the
  # signal/artifacts from this gate instead of re-running secret_scan/docs_smoke.
  echo "=== [quality_gate] short-checks (parallel, canonical remote source) ==="
  set +e
  (bash "$ROOT/gates/secret_scan.sh" . 2>&1 | tee "$secret_log") &
  secret_pid=$!
  (bash "$ROOT/docs/docs_smoke.sh" --install-smoke 2>&1 | tee "$docs_log") &
  docs_pid=$!
  wait "$secret_pid"
  secret_code=$?
  wait "$docs_pid"
  docs_code=$?
  set -e

  if [ "$secret_code" -eq 0 ] && [ "$docs_code" -eq 0 ]; then
    echo "✅ [quality_gate] short-checks passed"
    return 0
  fi

  [ "$secret_code" -ne 0 ] && echo "❌ [quality_gate] secret-scan failed"
  [ "$docs_code" -ne 0 ] && echo "❌ [quality_gate] docs-smoke failed"
  return 1
}

run_parallel_preflight_checks() {
  local doc_log="$RUN_ARTIFACT_DIR/doc-drift.log"
  local docs_scope_log="$RUN_ARTIFACT_DIR/docs-scope.log"
  local docs_manual_facts_log="$RUN_ARTIFACT_DIR/docs-manual-facts.log"
  local docs_ssot_hash_log="$RUN_ARTIFACT_DIR/docs-ssot-hash.log"
  local lock_drift_log="$RUN_ARTIFACT_DIR/lock-drift.log"
  local no_logs_log="$RUN_ARTIFACT_DIR/no-logs-no-merge.log"
  local write_before_search_log="$RUN_ARTIFACT_DIR/write-before-search.log"
  local env_contract_log="$RUN_ARTIFACT_DIR/env-contract.log"
  local env_contract_report_log="$RUN_ARTIFACT_DIR/env-contract-report.log"
  local legacy_sweep_log="$RUN_ARTIFACT_DIR/active-legacy-sweep.log"
  local required_checks_log="$RUN_ARTIFACT_DIR/required-checks-matrix.log"
  local done_signal_log="$RUN_ARTIFACT_DIR/done-signal-claims.log"
  local positioning_claims_log="$RUN_ARTIFACT_DIR/positioning-claims.log"
  local render_state_log="$RUN_ARTIFACT_DIR/docs-render-state.log"
  local fragment_completeness_log="$RUN_ARTIFACT_DIR/docs-fragment-completeness.log"
  local snapshot_scope_labels_log="$RUN_ARTIFACT_DIR/snapshot-scope-labels.log"
  local root_layout_log="$RUN_ARTIFACT_DIR/root-layout.log"
  local root_clean_log="$RUN_ARTIFACT_DIR/root-clean-after-mainflows.log"
  local root_public_surface_log="$RUN_ARTIFACT_DIR/root-public-surface.log"
  local root_change_control_log="$RUN_ARTIFACT_DIR/root-change-control.log"
  local sensitive_surface_log="$RUN_ARTIFACT_DIR/sensitive-surface.log"
  local feature_state_layout_log="$RUN_ARTIFACT_DIR/feature-state-layout.log"
  local strategy_pack_registry_log="$RUN_ARTIFACT_DIR/strategy-pack-registry.log"
  local watch_sources_contract_log="$RUN_ARTIFACT_DIR/watch-sources-contract.log"
  local runtime_layout_log="$RUN_ARTIFACT_DIR/runtime-layout.log"
  local repo_runtime_residue_log="$RUN_ARTIFACT_DIR/repo-runtime-residue.log"
  local cache_size_log="$RUN_ARTIFACT_DIR/cache-size.log"
  local runtime_budget_log="$RUN_ARTIFACT_DIR/runtime-budget.log"
  local module_graph_log="$RUN_ARTIFACT_DIR/module-graph.log"
  local hotspot_budget_log="$RUN_ARTIFACT_DIR/hotspot-budget.log"
  local mcp_surface_log="$RUN_ARTIFACT_DIR/mcp-surface.log"
  local upstream_drift_log="$RUN_ARTIFACT_DIR/upstream-drift.log"
  local upstream_registry_log="$RUN_ARTIFACT_DIR/upstream-registry-completeness.log"
  local upstream_compat_log="$RUN_ARTIFACT_DIR/upstream-compat-matrix.log"
  local upstream_fetch_log="$RUN_ARTIFACT_DIR/upstream-fetch-surfaces.log"
  local private_upstream_coupling_log="$RUN_ARTIFACT_DIR/private-upstream-coupling.log"
  local dependency_boundaries_log="$RUN_ARTIFACT_DIR/dependency-boundaries.log"
  local logging_contract_log="$RUN_ARTIFACT_DIR/logging-contract.log"
  local run_bundle_contract_log="$RUN_ARTIFACT_DIR/run-bundle-contract.log"
  local test_quality_log="$RUN_ARTIFACT_DIR/test-quality.log"
  local doc_pid docs_scope_pid docs_manual_facts_pid docs_ssot_hash_pid lock_drift_pid no_logs_pid write_before_search_pid env_contract_pid env_contract_report_pid legacy_sweep_pid required_checks_pid done_signal_pid positioning_claims_pid render_state_pid fragment_completeness_pid snapshot_scope_labels_pid root_layout_pid root_clean_pid root_public_surface_pid root_change_control_pid sensitive_surface_pid feature_state_layout_pid strategy_pack_registry_pid watch_sources_contract_pid mcp_surface_pid module_graph_pid hotspot_budget_pid upstream_drift_pid upstream_registry_pid upstream_compat_pid upstream_fetch_pid private_upstream_coupling_pid dependency_boundaries_pid logging_contract_pid run_bundle_contract_pid test_quality_pid short_pid
  local doc_code docs_scope_code docs_manual_facts_code docs_ssot_hash_code lock_drift_code no_logs_code write_before_search_code env_contract_code env_contract_report_code legacy_sweep_code required_checks_code done_signal_code positioning_claims_code render_state_code fragment_completeness_code docs_truth_routes_code snapshot_scope_labels_code root_layout_code root_clean_code root_public_surface_code root_change_control_code sensitive_surface_code feature_state_layout_code strategy_pack_registry_code watch_sources_contract_code mcp_surface_code collaboration_surface_code runtime_language_boundary_code public_artifact_safety_code local_only_tracking_code runtime_layout_code repo_runtime_residue_code runtime_budget_code module_graph_code hotspot_budget_code upstream_drift_code upstream_registry_code upstream_compat_code upstream_host_capabilities_code upstream_fetch_code private_upstream_coupling_code dependency_boundaries_code logging_contract_code run_bundle_contract_code test_quality_code short_code

  echo "=== [quality_gate] preflight-checks (parallel: doc-drift/docs-scope/docs-manual-facts/docs-ssot-hash/lock-drift/no-logs-no-merge/write-before-search/env-contract/env-contract-report/active-legacy-sweep/required-checks/done-signal-claims/positioning-claims/docs-render-state/docs-fragment-completeness/snapshot-scope-labels/root-layout/root-clean/root-public-surface/root-change-control/sensitive-surface/strategy-pack/watch-sources/mcp-surface/module-graph/hotspot-budget/upstream-drift/upstream-registry/upstream-compat/upstream-fetch/private-upstream-coupling/dependency-boundaries/logging-contract/run-bundle-contract/test-quality/short-checks; runtime cleanliness and collaboration/english-canonical/local-only guards run after short-checks settle) ==="
  set +e
  ("$VENV/bin/python" "$ROOT/scripts/check_doc_drift.py" --mode auto 2>&1 | tee "$doc_log") &
  doc_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_docs_scope.py" --root "$REPO_ROOT" 2>&1 | tee "$docs_scope_log") &
  docs_scope_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_docs_manual_facts.py" --root "$REPO_ROOT" 2>&1 | tee "$docs_manual_facts_log") &
  docs_manual_facts_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_docs_ssot_hash.py" --root "$REPO_ROOT" 2>&1 | tee "$docs_ssot_hash_log") &
  docs_ssot_hash_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_lock_drift.py" --root "$REPO_ROOT" 2>&1 | tee "$lock_drift_log") &
  lock_drift_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_no_logs_no_merge.py" --root "$REPO_ROOT" --mode auto 2>&1 | tee "$no_logs_log") &
  no_logs_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_write_before_search.py" --root "$REPO_ROOT" --mode auto 2>&1 | tee "$write_before_search_log") &
  write_before_search_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_env_contract.py" --root "$REPO_ROOT" --mode auto --max-contract-size 59 2>&1 | tee "$env_contract_log") &
  env_contract_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/generate_env_contract_report.py" --root "$REPO_ROOT" 2>&1 | tee "$env_contract_report_log") &
  env_contract_report_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/generate_api_contract.py" --check 2>&1 | tee "$RUN_ARTIFACT_DIR/api-contract.log") &
  api_contract_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_active_legacy_sweep.py" --root "$REPO_ROOT" 2>&1 | tee "$legacy_sweep_log") &
  legacy_sweep_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_required_checks_matrix.py" 2>&1 | tee "$required_checks_log") &
  required_checks_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_done_signal_claims.py" --root "$REPO_ROOT" 2>&1 | tee "$done_signal_log") &
  done_signal_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_positioning_claims.py" --root "$REPO_ROOT" 2>&1 | tee "$positioning_claims_log") &
  positioning_claims_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_docs_render_state.py" --root "$REPO_ROOT" 2>&1 | tee "$render_state_log") &
  render_state_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_docs_fragment_completeness.py" --root "$REPO_ROOT" 2>&1 | tee "$fragment_completeness_log") &
  fragment_completeness_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_docs_truth_routes.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/docs-truth-routes.log") &
  docs_truth_routes_pid=$!
  ("$VENV/bin/python" "$ROOT/scripts/check_snapshot_scope_labels.py" --root "$REPO_ROOT" 2>&1 | tee "$snapshot_scope_labels_log") &
  snapshot_scope_labels_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_layout.py" --root "$REPO_ROOT" 2>&1 | tee "$root_layout_log") &
  root_layout_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_clean_after_mainflows.py" --root "$REPO_ROOT" 2>&1 | tee "$root_clean_log") &
  root_clean_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_public_surface.py" --root "$REPO_ROOT" 2>&1 | tee "$root_public_surface_log") &
  root_public_surface_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_change_control.py" --root "$REPO_ROOT" 2>&1 | tee "$root_change_control_log") &
  root_change_control_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_sensitive_surface.py" --root "$REPO_ROOT" --mode all 2>&1 | tee "$sensitive_surface_log") &
  sensitive_surface_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_feature_state_layout.py" --root "$REPO_ROOT" 2>&1 | tee "$feature_state_layout_log") &
  feature_state_layout_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_strategy_pack_registry.py" --root "$REPO_ROOT" 2>&1 | tee "$strategy_pack_registry_log") &
  strategy_pack_registry_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_watch_sources_contract.py" 2>&1 | tee "$watch_sources_contract_log") &
  watch_sources_contract_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_mcp_surface.py" 2>&1 | tee "$mcp_surface_log") &
  mcp_surface_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_module_graph.py" --root "$REPO_ROOT" 2>&1 | tee "$module_graph_log") &
  module_graph_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_hotspot_budget.py" --root "$REPO_ROOT" 2>&1 | tee "$hotspot_budget_log") &
  hotspot_budget_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_drift.py" --root "$REPO_ROOT" 2>&1 | tee "$upstream_drift_log") &
  upstream_drift_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_registry_completeness.py" --root "$REPO_ROOT" 2>&1 | tee "$upstream_registry_log") &
  upstream_registry_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_compat_matrix.py" --root "$REPO_ROOT" 2>&1 | tee "$upstream_compat_log") &
  upstream_compat_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_fetch_surfaces.py" --root "$REPO_ROOT" 2>&1 | tee "$upstream_fetch_log") &
  upstream_fetch_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_no_private_upstream_coupling.py" --root "$REPO_ROOT" 2>&1 | tee "$private_upstream_coupling_log") &
  private_upstream_coupling_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_dependency_boundaries.py" --root "$REPO_ROOT" 2>&1 | tee "$dependency_boundaries_log") &
  dependency_boundaries_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_logging_contract.py" --root "$REPO_ROOT" --gate-run-id "$GATE_RUN_ID" --gate-name "$GATE_NAME" 2>&1 | tee "$logging_contract_log") &
  logging_contract_pid=$!
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_run_bundle_contract.py" --root "$REPO_ROOT" 2>&1 | tee "$run_bundle_contract_log") &
  run_bundle_contract_pid=$!
  (bash "$ROOT/gates/test_quality_gate.sh" 2>&1 | tee "$test_quality_log") &
  test_quality_pid=$!
  run_parallel_short_checks &
  short_pid=$!

  wait "$doc_pid"
  doc_code=$?
  wait "$docs_scope_pid"
  docs_scope_code=$?
  wait "$docs_manual_facts_pid"
  docs_manual_facts_code=$?
  wait "$docs_ssot_hash_pid"
  docs_ssot_hash_code=$?
  wait "$lock_drift_pid"
  lock_drift_code=$?
  wait "$no_logs_pid"
  no_logs_code=$?
  wait "$write_before_search_pid"
  write_before_search_code=$?
  wait "$env_contract_pid"
  env_contract_code=$?
  wait "$env_contract_report_pid"
  env_contract_report_code=$?
  wait "$api_contract_pid"
  api_contract_code=$?
  wait "$legacy_sweep_pid"
  legacy_sweep_code=$?
  wait "$required_checks_pid"
  required_checks_code=$?
  wait "$done_signal_pid"
  done_signal_code=$?
  wait "$positioning_claims_pid"
  positioning_claims_code=$?
  wait "$render_state_pid"
  render_state_code=$?
  wait "$fragment_completeness_pid"
  fragment_completeness_code=$?
  wait "$docs_truth_routes_pid"
  docs_truth_routes_code=$?
  wait "$snapshot_scope_labels_pid"
  snapshot_scope_labels_code=$?
  wait "$root_layout_pid"
  root_layout_code=$?
  wait "$root_clean_pid"
  root_clean_code=$?
  wait "$root_public_surface_pid"
  root_public_surface_code=$?
  wait "$root_change_control_pid"
  root_change_control_code=$?
  wait "$sensitive_surface_pid"
  sensitive_surface_code=$?
  wait "$feature_state_layout_pid"
  feature_state_layout_code=$?
  wait "$strategy_pack_registry_pid"
  strategy_pack_registry_code=$?
  wait "$watch_sources_contract_pid"
  watch_sources_contract_code=$?
  wait "$mcp_surface_pid"
  mcp_surface_code=$?
  wait "$module_graph_pid"
  module_graph_code=$?
  wait "$hotspot_budget_pid"
  hotspot_budget_code=$?
  wait "$upstream_drift_pid"
  upstream_drift_code=$?
  wait "$upstream_registry_pid"
  upstream_registry_code=$?
  wait "$upstream_compat_pid"
  upstream_compat_code=$?
  wait "$upstream_fetch_pid"
  upstream_fetch_code=$?
  wait "$private_upstream_coupling_pid"
  private_upstream_coupling_code=$?
  wait "$dependency_boundaries_pid"
  dependency_boundaries_code=$?
  wait "$logging_contract_pid"
  logging_contract_code=$?
  wait "$run_bundle_contract_pid"
  run_bundle_contract_code=$?
  wait "$test_quality_pid"
  test_quality_code=$?
  wait "$short_pid"
  short_code=$?

  # Keep runtime cleanliness checks out of the parallel preflight fan-out.
  # Frontend/doc short-checks can transiently materialize `apps/webui/node_modules`
  # during npm install / cleanup, and residue gates should validate the settled
  # workspace, not race that transient window.
  bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_layout.py" --root "$REPO_ROOT" 2>&1 | tee "$runtime_layout_log")
  runtime_layout_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_repo_runtime_residue.py" --root "$REPO_ROOT" 2>&1 | tee "$repo_runtime_residue_log")
  repo_runtime_residue_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_cache_size.py" --root "$REPO_ROOT" 2>&1 | tee "$cache_size_log")
  cache_size_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_budget.py" --root "$REPO_ROOT" 2>&1 | tee "$runtime_budget_log")
  runtime_budget_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_collaboration_surface.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/collaboration-surface.log")
  collaboration_surface_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_english_canonical_surface.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/english-canonical-surface.log")
  english_canonical_surface_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_language_boundary.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/runtime-language-boundary.log")
  runtime_language_boundary_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_public_artifact_safety.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/public-artifact-safety.log")
  public_artifact_safety_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_local_only_tracking.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/local-only-tracking.log")
  local_only_tracking_code=$?
  ("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_host_capabilities.py" --root "$REPO_ROOT" 2>&1 | tee "$RUN_ARTIFACT_DIR/upstream-host-capabilities.log")
  upstream_host_capabilities_code=$?
  set -e

  [ "$doc_code" -eq 0 ] && echo "✅ [quality_gate] doc-drift passed" || echo "❌ [quality_gate] doc-drift failed"
  [ "$docs_scope_code" -eq 0 ] && echo "✅ [quality_gate] docs-scope passed" || echo "❌ [quality_gate] docs-scope failed"
  [ "$docs_manual_facts_code" -eq 0 ] && echo "✅ [quality_gate] docs-manual-facts passed" || echo "❌ [quality_gate] docs-manual-facts failed"
  [ "$docs_ssot_hash_code" -eq 0 ] && echo "✅ [quality_gate] docs-ssot-hash passed" || echo "❌ [quality_gate] docs-ssot-hash failed"
  [ "$lock_drift_code" -eq 0 ] && echo "✅ [quality_gate] lock-drift passed" || echo "❌ [quality_gate] lock-drift failed"
  [ "$no_logs_code" -eq 0 ] && echo "✅ [quality_gate] no-logs-no-merge passed" || echo "❌ [quality_gate] no-logs-no-merge failed"
  [ "$write_before_search_code" -eq 0 ] && echo "✅ [quality_gate] write-before-search passed" || echo "❌ [quality_gate] write-before-search failed"
  [ "$env_contract_code" -eq 0 ] && echo "✅ [quality_gate] env-contract passed" || echo "❌ [quality_gate] env-contract failed"
  [ "$env_contract_report_code" -eq 0 ] && echo "✅ [quality_gate] env-contract-report passed" || echo "❌ [quality_gate] env-contract-report failed"
  [ "$api_contract_code" -eq 0 ] && echo "✅ [quality_gate] api-contract passed" || echo "❌ [quality_gate] api-contract failed"
  [ "$legacy_sweep_code" -eq 0 ] && echo "✅ [quality_gate] active-legacy-sweep passed" || echo "❌ [quality_gate] active-legacy-sweep failed"
  [ "$required_checks_code" -eq 0 ] && echo "✅ [quality_gate] required-checks passed" || echo "❌ [quality_gate] required-checks failed"
  [ "$done_signal_code" -eq 0 ] && echo "✅ [quality_gate] done-signal-claims passed" || echo "❌ [quality_gate] done-signal-claims failed"
  [ "$positioning_claims_code" -eq 0 ] && echo "✅ [quality_gate] positioning-claims passed" || echo "❌ [quality_gate] positioning-claims failed"
  [ "$render_state_code" -eq 0 ] && echo "✅ [quality_gate] docs-render-state passed" || echo "❌ [quality_gate] docs-render-state failed"
  [ "$fragment_completeness_code" -eq 0 ] && echo "✅ [quality_gate] docs-fragment-completeness passed" || echo "❌ [quality_gate] docs-fragment-completeness failed"
  [ "$docs_truth_routes_code" -eq 0 ] && echo "✅ [quality_gate] docs-truth-routes passed" || echo "❌ [quality_gate] docs-truth-routes failed"
  [ "$snapshot_scope_labels_code" -eq 0 ] && echo "✅ [quality_gate] snapshot-scope-labels passed" || echo "❌ [quality_gate] snapshot-scope-labels failed"
  [ "$root_layout_code" -eq 0 ] && echo "✅ [quality_gate] root-layout passed" || echo "❌ [quality_gate] root-layout failed"
  [ "$root_clean_code" -eq 0 ] && echo "✅ [quality_gate] root-clean-after-mainflows passed" || echo "❌ [quality_gate] root-clean-after-mainflows failed"
  [ "$root_public_surface_code" -eq 0 ] && echo "✅ [quality_gate] root-public-surface passed" || echo "❌ [quality_gate] root-public-surface failed"
  [ "$root_change_control_code" -eq 0 ] && echo "✅ [quality_gate] root-change-control passed" || echo "❌ [quality_gate] root-change-control failed"
  [ "$sensitive_surface_code" -eq 0 ] && echo "✅ [quality_gate] sensitive-surface passed" || echo "❌ [quality_gate] sensitive-surface failed"
  [ "$feature_state_layout_code" -eq 0 ] && echo "✅ [quality_gate] feature-state-layout passed" || echo "❌ [quality_gate] feature-state-layout failed"
  [ "$strategy_pack_registry_code" -eq 0 ] && echo "✅ [quality_gate] strategy-pack-registry passed" || echo "❌ [quality_gate] strategy-pack-registry failed"
  [ "$watch_sources_contract_code" -eq 0 ] && echo "✅ [quality_gate] watch-sources-contract passed" || echo "❌ [quality_gate] watch-sources-contract failed"
  [ "$mcp_surface_code" -eq 0 ] && echo "✅ [quality_gate] mcp-surface passed" || echo "❌ [quality_gate] mcp-surface failed"
  [ "$collaboration_surface_code" -eq 0 ] && echo "✅ [quality_gate] collaboration-surface passed" || echo "❌ [quality_gate] collaboration-surface failed"
  [ "$english_canonical_surface_code" -eq 0 ] && echo "✅ [quality_gate] english-canonical-surface passed" || echo "❌ [quality_gate] english-canonical-surface failed"
  [ "$runtime_language_boundary_code" -eq 0 ] && echo "✅ [quality_gate] runtime-language-boundary passed" || echo "❌ [quality_gate] runtime-language-boundary failed"
  [ "$public_artifact_safety_code" -eq 0 ] && echo "✅ [quality_gate] public-artifact-safety passed" || echo "❌ [quality_gate] public-artifact-safety failed"
  [ "$local_only_tracking_code" -eq 0 ] && echo "✅ [quality_gate] local-only-tracking passed" || echo "❌ [quality_gate] local-only-tracking failed"
  [ "$runtime_layout_code" -eq 0 ] && echo "✅ [quality_gate] runtime-layout passed" || echo "❌ [quality_gate] runtime-layout failed"
  [ "$repo_runtime_residue_code" -eq 0 ] && echo "✅ [quality_gate] repo-runtime-residue passed" || echo "❌ [quality_gate] repo-runtime-residue failed"
  [ "$cache_size_code" -eq 0 ] && echo "✅ [quality_gate] cache-size passed" || echo "❌ [quality_gate] cache-size failed"
  [ "$runtime_budget_code" -eq 0 ] && echo "✅ [quality_gate] runtime-budget passed" || echo "❌ [quality_gate] runtime-budget failed"
  [ "$module_graph_code" -eq 0 ] && echo "✅ [quality_gate] module-graph passed" || echo "❌ [quality_gate] module-graph failed"
  [ "$hotspot_budget_code" -eq 0 ] && echo "✅ [quality_gate] hotspot-budget passed" || echo "❌ [quality_gate] hotspot-budget failed"
  [ "$upstream_drift_code" -eq 0 ] && echo "✅ [quality_gate] upstream-drift passed" || echo "❌ [quality_gate] upstream-drift failed"
  [ "$upstream_registry_code" -eq 0 ] && echo "✅ [quality_gate] upstream-registry-completeness passed" || echo "❌ [quality_gate] upstream-registry-completeness failed"
  [ "$upstream_compat_code" -eq 0 ] && echo "✅ [quality_gate] upstream-compat-matrix passed" || echo "❌ [quality_gate] upstream-compat-matrix failed"
  [ "$upstream_host_capabilities_code" -eq 0 ] && echo "✅ [quality_gate] upstream-host-capabilities passed" || echo "❌ [quality_gate] upstream-host-capabilities failed"
  [ "$upstream_fetch_code" -eq 0 ] && echo "✅ [quality_gate] upstream-fetch-surfaces passed" || echo "❌ [quality_gate] upstream-fetch-surfaces failed"
  [ "$private_upstream_coupling_code" -eq 0 ] && echo "✅ [quality_gate] private-upstream-coupling passed" || echo "❌ [quality_gate] private-upstream-coupling failed"
  [ "$dependency_boundaries_code" -eq 0 ] && echo "✅ [quality_gate] dependency-boundaries passed" || echo "❌ [quality_gate] dependency-boundaries failed"
  [ "$logging_contract_code" -eq 0 ] && echo "✅ [quality_gate] logging-contract passed" || echo "❌ [quality_gate] logging-contract failed"
  [ "$run_bundle_contract_code" -eq 0 ] && echo "✅ [quality_gate] run-bundle-contract passed" || echo "❌ [quality_gate] run-bundle-contract failed"
  [ "$test_quality_code" -eq 0 ] && echo "✅ [quality_gate] test-quality passed" || echo "❌ [quality_gate] test-quality failed"
  [ "$short_code" -eq 0 ] && echo "✅ [quality_gate] short-checks passed" || echo "❌ [quality_gate] short-checks failed"

  if [ "$doc_code" -eq 0 ] && [ "$docs_scope_code" -eq 0 ] && [ "$docs_manual_facts_code" -eq 0 ] && [ "$docs_ssot_hash_code" -eq 0 ] && [ "$lock_drift_code" -eq 0 ] && [ "$no_logs_code" -eq 0 ] && [ "$write_before_search_code" -eq 0 ] && [ "$env_contract_code" -eq 0 ] && [ "$env_contract_report_code" -eq 0 ] && [ "$api_contract_code" -eq 0 ] && [ "$legacy_sweep_code" -eq 0 ] && [ "$required_checks_code" -eq 0 ] && [ "$done_signal_code" -eq 0 ] && [ "$positioning_claims_code" -eq 0 ] && [ "$render_state_code" -eq 0 ] && [ "$fragment_completeness_code" -eq 0 ] && [ "$docs_truth_routes_code" -eq 0 ] && [ "$snapshot_scope_labels_code" -eq 0 ] && [ "$root_layout_code" -eq 0 ] && [ "$root_clean_code" -eq 0 ] && [ "$root_public_surface_code" -eq 0 ] && [ "$root_change_control_code" -eq 0 ] && [ "$sensitive_surface_code" -eq 0 ] && [ "$feature_state_layout_code" -eq 0 ] && [ "$strategy_pack_registry_code" -eq 0 ] && [ "$watch_sources_contract_code" -eq 0 ] && [ "$mcp_surface_code" -eq 0 ] && [ "$collaboration_surface_code" -eq 0 ] && [ "$english_canonical_surface_code" -eq 0 ] && [ "$runtime_language_boundary_code" -eq 0 ] && [ "$public_artifact_safety_code" -eq 0 ] && [ "$local_only_tracking_code" -eq 0 ] && [ "$runtime_layout_code" -eq 0 ] && [ "$repo_runtime_residue_code" -eq 0 ] && [ "$cache_size_code" -eq 0 ] && [ "$runtime_budget_code" -eq 0 ] && [ "$module_graph_code" -eq 0 ] && [ "$hotspot_budget_code" -eq 0 ] && [ "$upstream_drift_code" -eq 0 ] && [ "$upstream_registry_code" -eq 0 ] && [ "$upstream_compat_code" -eq 0 ] && [ "$upstream_host_capabilities_code" -eq 0 ] && [ "$upstream_fetch_code" -eq 0 ] && [ "$private_upstream_coupling_code" -eq 0 ] && [ "$dependency_boundaries_code" -eq 0 ] && [ "$logging_contract_code" -eq 0 ] && [ "$run_bundle_contract_code" -eq 0 ] && [ "$test_quality_code" -eq 0 ] && [ "$short_code" -eq 0 ]; then
    return 0
  fi
  return 1
}

run_pip_audit_gate() {
  local lock_log="$RUN_ARTIFACT_DIR/pip-audit-lock.log"
  local dev_log="$RUN_ARTIFACT_DIR/pip-audit-dev.log"
  local lock_fallback_log="$RUN_ARTIFACT_DIR/pip-audit-lock-fallback.log"
  local dev_fallback_log="$RUN_ARTIFACT_DIR/pip-audit-dev-fallback.log"
  local lock_code=0
  local dev_code=0
  local fallback_code=0

  echo "=== [quality_gate] pip-audit ==="
  if ! "$VENV/bin/python" -c "import pip_audit" >/dev/null 2>&1; then
    echo "❌ [quality_gate] pip-audit module missing in runtime venv" >&2
    echo "Install via lockfiles: $VENV/bin/python -m pip install --require-hashes -r tooling/requirements.lock.txt -r tooling/requirements-dev.lock.txt" >&2
    return 1
  fi

  local runtime_ignore_args=()
  local dev_ignore_args=()
  local ignored_vuln
  while IFS= read -r ignored_vuln; do
    [ -n "$ignored_vuln" ] || continue
    runtime_ignore_args+=(--ignore-vuln "$ignored_vuln")
  done < <(build_pip_audit_ignore_args runtime-lock)
  while IFS= read -r ignored_vuln; do
    [ -n "$ignored_vuln" ] || continue
    dev_ignore_args+=(--ignore-vuln "$ignored_vuln")
  done < <(build_pip_audit_ignore_args dev-lock-only)

  set +e
  "$VENV/bin/python" -m pip_audit --progress-spinner off "${runtime_ignore_args[@]}" -r tooling/requirements.lock.txt \
    2>&1 | tee "$lock_log"
  lock_code=${PIPESTATUS[0]}
  set -e

  if [ "$lock_code" -ne 0 ]; then
    if grep -Eq "Signals\\.SIGABRT|ensurepip|In --require-hashes mode|Failed to install packages|TLS CA certificate bundle" "$lock_log"; then
      echo "⚠️ [quality_gate] pip-audit runtime lock hit bootstrap/hash constraint, retrying strict no-deps fallback"
      set +e
      "$VENV/bin/python" -m pip_audit --progress-spinner off --strict --no-deps --disable-pip "${runtime_ignore_args[@]}" -r tooling/requirements.lock.txt \
        2>&1 | tee "$lock_fallback_log"
      fallback_code=${PIPESTATUS[0]}
      set -e
      if [ "$fallback_code" -ne 0 ]; then
        echo "❌ [quality_gate] pip-audit fallback failed for hash-locked requirements"
        return "$fallback_code"
      fi
    else
      echo "❌ [quality_gate] pip-audit failed for hash-locked requirements"
      return "$lock_code"
    fi
  fi

  set +e
  "$VENV/bin/python" -m pip_audit --progress-spinner off "${dev_ignore_args[@]}" -r tooling/requirements-dev.lock.txt \
    2>&1 | tee "$dev_log"
  dev_code=${PIPESTATUS[0]}
  set -e

  if [ "$dev_code" -ne 0 ]; then
    if grep -Eq "Signals\\.SIGABRT|ensurepip|In --require-hashes mode|Failed to install packages|TLS CA certificate bundle" "$dev_log"; then
      echo "⚠️ [quality_gate] pip-audit dev lock hit bootstrap/hash constraint, retrying strict no-deps fallback"
      set +e
      "$VENV/bin/python" -m pip_audit --progress-spinner off --strict --no-deps --disable-pip "${dev_ignore_args[@]}" -r tooling/requirements-dev.lock.txt \
        2>&1 | tee "$dev_fallback_log"
      fallback_code=${PIPESTATUS[0]}
      set -e
      if [ "$fallback_code" -ne 0 ]; then
        echo "❌ [quality_gate] pip-audit fallback failed for dev requirements"
        return "$fallback_code"
      fi
    else
      echo "❌ [quality_gate] pip-audit failed for dev requirements"
      return "$dev_code"
    fi
  fi

  echo "✅ [quality_gate] pip-audit passed"
  return 0
}

build_pip_audit_ignore_args() {
  local scope="$1"
  local allowlist_path="$REPO_ROOT/contracts/governance/pip_audit_allowlist.yaml"
  if [ ! -f "$allowlist_path" ]; then
    return 0
  fi

  "$VENV/bin/python" - "$allowlist_path" "$scope" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import yaml

policy_path = Path(sys.argv[1])
scope = sys.argv[2]
data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
entries = data.get("entries", [])
for entry in entries:
    if not isinstance(entry, dict):
        continue
    status = str(entry.get("status", "accepted")).strip().lower()
    if status not in {"accepted", "active"}:
        continue
    entry_scope = str(entry.get("scope", "all")).strip()
    if entry_scope not in {"all", scope}:
        continue
    vuln_id = str(entry.get("id", "")).strip()
    if vuln_id:
        print(vuln_id)
PY
}

run_postflight_runtime_hygiene() {
  # Frontend lint/install steps can transiently materialize apps/webui/node_modules.
  # Normalize repo-local runtime residue before the final hygiene scorecard so
  # postflight checks validate the settled workspace rather than a stale install lane.
  bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true
  "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_clean_after_mainflows.py" --root "$REPO_ROOT"
  "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_layout.py" --root "$REPO_ROOT"
  "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_repo_runtime_residue.py" --root "$REPO_ROOT"
}

run_post_summary_governance_checks() {
  local evidence_bundle="$RUNTIME_CI_DIR/evidence-bundle.json"
  "$VENV/bin/python" "$ROOT/scripts/generate_ci_evidence_bundle.py" \
    --artifacts-root "$REPO_ROOT/.runtime-cache" \
    --output "$evidence_bundle"
  bash "$ROOT/upstreams/refresh_receipts.sh" --bundle "$evidence_bundle"
  "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_receipts.py" --root "$REPO_ROOT"
  "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_verification_freshness.py" --root "$REPO_ROOT"
  "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_gate_log_correlation.py" \
    --root "$REPO_ROOT" \
    --gate "$GATE_NAME" \
    --summary-path "$RUN_SUMMARY_REL_PATH"
}

run_parallel_static_checks() {
  local ruff_log="$RUN_ARTIFACT_DIR/ruff.log"
  local mypy_log="$RUN_ARTIFACT_DIR/mypy.log"
  local bandit_log="$RUN_ARTIFACT_DIR/bandit.log"
  local lint_frontend_log="$RUN_ARTIFACT_DIR/lint-frontend.log"
  local ruff_pid mypy_pid bandit_pid lint_frontend_pid
  local ruff_code mypy_code bandit_code lint_frontend_code

  echo "=== [quality_gate] static-checks (parallel: ruff/mypy/bandit/lint-frontend) ==="
  set +e
  ("$VENV/bin/python" -m ruff check apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability tooling/scripts tests 2>&1 | tee "$ruff_log") &
  ruff_pid=$!
  ("$VENV/bin/python" -m mypy apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability 2>&1 | tee "$mypy_log") &
  mypy_pid=$!
  (
    set +e
    "$VENV/bin/python" -m bandit -r apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability --severity-level high --confidence-level high 2>&1 | tee "$bandit_log"
    local bandit_rc=${PIPESTATUS[0]}
    if [ "$bandit_rc" -eq 0 ] && grep -Eq "Bandit internal error|exception while scanning file|Files skipped \([1-9][0-9]*\)" "$bandit_log"; then
      echo "❌ [quality_gate] bandit reported internal scan errors/skipped files; treat as failed gate"
      exit 1
    fi
    exit "$bandit_rc"
  ) &
  bandit_pid=$!
  # Keep quality_gate aligned with CI's deterministic frontend gate; semantic Gemini audit
  # remains available via standalone lint_frontend / dedicated review flows.
  (LINT_FRONTEND_SKIP_GEMINI_AUDIT=1 bash "$ROOT/gates/lint_frontend.sh" 2>&1 | tee "$lint_frontend_log") &
  lint_frontend_pid=$!
  wait "$ruff_pid"
  ruff_code=$?
  wait "$mypy_pid"
  mypy_code=$?
  wait "$bandit_pid"
  bandit_code=$?
  wait "$lint_frontend_pid"
  lint_frontend_code=$?
  set -e

  [ "$ruff_code" -eq 0 ] && echo "✅ [quality_gate] ruff passed" || echo "❌ [quality_gate] ruff failed"
  [ "$mypy_code" -eq 0 ] && echo "✅ [quality_gate] mypy passed" || echo "❌ [quality_gate] mypy failed"
  [ "$bandit_code" -eq 0 ] && echo "✅ [quality_gate] bandit passed" || echo "❌ [quality_gate] bandit failed"
  [ "$lint_frontend_code" -eq 0 ] && echo "✅ [quality_gate] lint-frontend passed" || echo "❌ [quality_gate] lint-frontend failed"

  if [ "$ruff_code" -eq 0 ] && [ "$mypy_code" -eq 0 ] && [ "$bandit_code" -eq 0 ] && [ "$lint_frontend_code" -eq 0 ]; then
    return 0
  fi
  return 1
}

run_step preflight-checks run_parallel_preflight_checks || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after preflight-checks" >&2
  exit 1
}
cleanup_coverage_artifacts
run_step_with_heartbeat \
  pytest-fast \
  run_pytest_with_isolated_tmp \
  env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF \
  "$VENV/bin/python" -m pytest -q -o addopts= --maxfail=1 tests/unit \
  --strict-config \
  --strict-markers \
  --junitxml="$RUNTIME_CI_DIR/pytest-unit-junit.xml" || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after pytest-fast" >&2
  exit 1
}
run_step pre-mutation-cache-hygiene run_post_mutation_cache_hygiene || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after pre-mutation-cache-hygiene" >&2
  exit 1
}
run_step mutation-canary run_mutation_canary_in_repo_snapshot || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after mutation-canary" >&2
  exit 1
}
run_step post-mutation-cache-hygiene run_post_mutation_cache_hygiene || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after post-mutation-cache-hygiene" >&2
  exit 1
}
pytest_full_targets=(
  tests/unit
  tests/e2e
  tests/integration
)
run_step_with_heartbeat \
  pytest \
  run_pytest_with_isolated_tmp \
  env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF FILEMAN_RUN_LIVE_TESTS=0 \
  "$VENV/bin/python" -m pytest -q \
  -o addopts= \
  --strict-config \
  --strict-markers \
  -m "not live_llm and not live_browser" \
  --junitxml="$RUNTIME_CI_DIR/pytest-junit.xml" \
  --cov=packages/domain \
  --cov=packages/application \
  --cov=packages/infrastructure \
  --cov=packages/observability \
  --cov=apps/api \
  --cov=apps/cli \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml:"$RUNTIME_CI_DIR/coverage.xml" \
  "${pytest_full_targets[@]}" || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after pytest" >&2
  exit 1
}
normalize_coverage_artifact || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after pytest because coverage xml could not be normalized into $RUNTIME_CI_DIR/coverage.xml" >&2
  exit 1
}
run_step coverage-threshold "$VENV/bin/python" "$ROOT/scripts/check_coverage_thresholds.py" \
  --coverage-xml "$RUNTIME_CI_DIR/coverage.xml" --min-total 95 --min-branch 70 || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after coverage-threshold" >&2
  exit 1
}
run_step static-checks run_parallel_static_checks || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after static-checks" >&2
  exit 1
}
run_step pip-audit run_pip_audit_gate || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after pip-audit" >&2
  exit 1
}

if [ "${FILEMAN_RUN_LIVE_TESTS:-0}" = "1" ]; then
  resolve_var_prefer_dotenv GEMINI_API_KEY ""
  if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "❌ quality_gate: FILEMAN_RUN_LIVE_TESTS=1 but GEMINI_API_KEY is missing" >&2
    exit 1
  fi
  resolve_var_prefer_env_then_runtime_env GEMINI_MODEL "gemini-3-flash-preview"
  : "${FILEMAN_LIVE_TEST_URL:=https://docs.github.com/en}"
  resolve_var_prefer_env_then_runtime_env FILEMAN_LIVE_TEST_URL "https://docs.github.com/en"
  if ! run_step live-tests bash "$ROOT/scripts/run_live_tests.sh"; then
    live_log="$RUN_ARTIFACT_DIR/live-tests.log"
    allow_network_timeout="${QUALITY_GATE_ALLOW_LIVE_NETWORK_TIMEOUT:-0}"
    if [ "$allow_network_timeout" = "1" ] && grep -Eqi "class=network-timeout|class=network-jitter|LIVE_ERROR_CLASS=network-timeout|LIVE_ERROR_CLASS=network-jitter" "$live_log"; then
      echo "⚠️ [quality_gate] live-tests failed with retryable network class; continue due to QUALITY_GATE_ALLOW_LIVE_NETWORK_TIMEOUT=1 (explicit override)" >&2
    else
      write_gate_summary fail
      echo "❌ quality_gate: fail-fast after live-tests" >&2
      exit 1
    fi
  fi
fi

run_step postflight-runtime-hygiene run_postflight_runtime_hygiene || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after postflight-runtime-hygiene" >&2
  exit 1
}

write_gate_summary pass
run_step post-summary-governance run_post_summary_governance_checks || {
  write_gate_summary fail
  echo "❌ quality_gate: fail-fast after post-summary-governance" >&2
  exit 1
}

write_gate_summary pass
echo "✅ quality_gate: all checks passed"
