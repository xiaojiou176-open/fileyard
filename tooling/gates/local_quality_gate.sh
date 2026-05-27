#!/usr/bin/env bash
set -euo pipefail

# Local quality gate: configurable local verification with incremental support.
# Design principle: "fast" mode should complete in <60s for typical changes.
#
# Modes:
#   fast (default): parallel incremental checks - doc drift, lint, unit tests
#   prepush-lite: minimal checks for quick validation
#   full: complete quality gate (same as CI)
#   all: fast + full (comprehensive local verification)
#
# Incremental behavior:
#   - Detects changed files since last push/merge-base
#   - Runs targeted checks on changed files only
#   - Falls back to full check if detection fails
#
# Summary-dependent receipt synthesis and gate-summary correlation belong to
# tooling/gates/quality_gate.sh after it has written the gate envelopes.
# Keeping them out of fast/prepush-lite preserves the advertised local-burn
# envelope and avoids false reds on clean local clones.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
MODE="${1:-fast}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

ARTIFACT_LOGS="$(governance_runtime_logs_path "$REPO_ROOT")/local-quality-gate"

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label local-quality-gate -- bash tooling/gates/local_quality_gate.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ local_quality_gate: venv python not found: $VENV/bin/python" >&2
  echo "Run: bash tooling/runtime/bootstrap_env.sh" >&2
  exit 1
fi

mkdir -p "$ARTIFACT_LOGS"
bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true

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

run_step() {
  local name="$1"
  shift
  local log_file="$ARTIFACT_LOGS/${name}.log"
  echo "=== [local_quality_gate] $name ==="
  if "$@" 2>&1 | tee "$log_file"; then
    echo "✅ [local_quality_gate] $name passed"
    return 0
  fi
  echo "❌ [local_quality_gate] $name failed (log: $log_file)" >&2
  return 1
}

PARALLEL_PIDS=()
PARALLEL_NAMES=()
PARALLEL_LOGS=()

run_parallel_step() {
  local name="$1"
  shift
  local log_file="$ARTIFACT_LOGS/${name}.log"
  ("$@" 2>&1 | tee "$log_file") &
  PARALLEL_PIDS+=("$!")
  PARALLEL_NAMES+=("$name")
  PARALLEL_LOGS+=("$log_file")
}

wait_parallel_steps() {
  local failed=0
  local i
  for i in "${!PARALLEL_PIDS[@]}"; do
    local pid name log_file
    pid="${PARALLEL_PIDS[$i]}"
    name="${PARALLEL_NAMES[$i]}"
    log_file="${PARALLEL_LOGS[$i]}"
    if wait "$pid"; then
      echo "✅ [local_quality_gate] $name passed"
    else
      echo "❌ [local_quality_gate] $name failed (log: $log_file)" >&2
      failed=1
    fi
  done
  return "$failed"
}

run_pytest_with_isolated_tmp() {
  local tmp_root="${XDG_CACHE_HOME:-$HOME/.cache}/pytest-runtime"
  mkdir -p "$tmp_root"
  local isolated_tmp
  isolated_tmp="$(mktemp -d "$tmp_root/run.XXXXXX")"
  local pytest_temp_root="$isolated_tmp/pytest-temp"
  mkdir -p "$pytest_temp_root"
  TMPDIR="$isolated_tmp" TMP="$isolated_tmp" TEMP="$isolated_tmp" PYTEST_DEBUG_TEMPROOT="$pytest_temp_root" "$@"
  local rc=$?
  rm -rf "$isolated_tmp"
  return "$rc"
}

cleanup_frontend_runtime_residue() {
  if [ ! -d "$REPO_ROOT/apps/webui/node_modules" ]; then
    return 0
  fi
  find "$REPO_ROOT/apps/webui/node_modules" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
  rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true
}

run_runtime_layout_with_frontend_cleanup() {
  local attempts=3
  local attempt=1
  while [ "$attempt" -le "$attempts" ]; do
    cleanup_frontend_runtime_residue
    if "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_layout.py" --root "$REPO_ROOT"; then
      return 0
    fi
    if [ "$attempt" -eq "$attempts" ]; then
      return 1
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
}

# Detect changed Python files for incremental checks
resolve_change_base_ref() {
  local base_ref=""

  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi

  # Try to find merge-base with origin/main or origin/master
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    base_ref="$(git merge-base HEAD origin/main 2>/dev/null || true)"
  elif git rev-parse --verify origin/master >/dev/null 2>&1; then
    base_ref="$(git merge-base HEAD origin/master 2>/dev/null || true)"
  fi

  if [ -z "$base_ref" ]; then
    # Fallback: use HEAD~10 or first commit (avoid pipefail+SIGPIPE with head)
    base_ref="$(git rev-parse HEAD~10 2>/dev/null || true)"
    if [ -z "$base_ref" ]; then
      local roots
      roots="$(git rev-list --max-parents=0 HEAD 2>/dev/null || true)"
      base_ref="${roots%%$'\n'*}"
    fi
  fi

  if [ -z "$base_ref" ]; then
    return 1
  fi

  printf '%s' "$base_ref"
}

detect_changed_py_files() {
  local changed_file="$ARTIFACT_LOGS/changed-py-files.txt"
  local base_ref=""
  mkdir -p "$ARTIFACT_LOGS"
  : > "$changed_file"

  if ! command -v git >/dev/null 2>&1; then
    echo "__FULL__"
    return
  fi

  if base_ref="$(resolve_change_base_ref)"; then
    # Get changed .py files (exclude deleted files for mypy/test mapping)
    git diff --name-only --diff-filter=ACMRT "$base_ref" HEAD 2>/dev/null \
      | grep -E '\.py$' \
      | grep -E '^(packages/application/|packages/domain/|packages/infrastructure/|packages/observability/|apps/api/|apps/cli/|tooling/scripts/)' \
      > "$changed_file" || true
  fi

  # Also include staged changes
  git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null \
    | grep -E '\.py$' \
    | grep -E '^(packages/application/|packages/domain/|packages/infrastructure/|packages/observability/|apps/api/|apps/cli/|tooling/scripts/)' \
    >> "$changed_file" || true

  # Deduplicate
  sort -u "$changed_file" -o "$changed_file"

  local count
  count="$(wc -l < "$changed_file" | tr -d ' ')"

  if [ "$count" -eq 0 ]; then
    echo "__NONE__"
  elif [ "$count" -gt 50 ]; then
    # Too many changes, fall back to full check
    echo "__FULL__"
  else
    # Return an incremental marker; concrete paths are consumed from changed-py-files.txt.
    echo "__INCREMENTAL__"
  fi
}

detect_changed_frontend_files() {
  local changed_file="$ARTIFACT_LOGS/changed-frontend-files.txt"
  local base_ref=""
  mkdir -p "$ARTIFACT_LOGS"
  : > "$changed_file"

  if ! command -v git >/dev/null 2>&1; then
    echo "1"
    return
  fi

  if base_ref="$(resolve_change_base_ref)"; then
    git diff --name-only --diff-filter=ACMRT "$base_ref" HEAD 2>/dev/null \
      | grep -E '^(apps/webui/|package\.json$|package-lock\.json$|tooling/config/frontend-scope\.yml$|tooling/config/biome\.json$|tooling/config/stylelintrc\.json$|tooling/gates/lint_frontend\.sh$|tooling/runtime/run_webui\.sh$|tooling/runtime/run_webui_task\.sh$|tooling/runtime/run_web_stack\.sh$)' \
      > "$changed_file" || true
  fi

  git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null \
    | grep -E '^(apps/webui/|package\.json$|package-lock\.json$|tooling/config/frontend-scope\.yml$|tooling/config/biome\.json$|tooling/config/stylelintrc\.json$|tooling/gates/lint_frontend\.sh$|tooling/runtime/run_webui\.sh$|tooling/runtime/run_webui_task\.sh$|tooling/runtime/run_web_stack\.sh$)' \
    >> "$changed_file" || true

  sort -u "$changed_file" -o "$changed_file"

  if [ -s "$changed_file" ]; then
    echo "1"
  else
    echo "0"
  fi
}

# Check if we should run full tests or incremental
should_run_full_tests() {
  local changed_file="$ARTIFACT_LOGS/changed-py-files.txt"
  if [ ! -f "$changed_file" ]; then
    return 0  # Run full if no detection
  fi

  local count
  count="$(wc -l < "$changed_file" | tr -d ' ')"

  # Run full tests if:
  # - More than 20 files changed
  # - Core modules changed (pipeline/*.py)
  # - Test infrastructure changed
  if [ "$count" -gt 20 ]; then
    return 0
  fi

  if grep -qE '^(apps/api|apps/cli|packages/domain|packages/application|packages/infrastructure|packages/observability)/' "$changed_file" 2>/dev/null; then
    return 0
  fi

  if grep -qE '^tests/(conftest|fixtures)' "$changed_file" 2>/dev/null; then
    return 0
  fi

  return 1
}

run_mypy_incremental() {
  local changed_file="$ARTIFACT_LOGS/changed-py-files.txt"
  local mypy_targets=()

  if [ -f "$changed_file" ]; then
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      mypy_targets+=("$path")
    done < "$changed_file"
  fi

  if [ "${#mypy_targets[@]}" -eq 0 ]; then
    "$VENV/bin/mypy" apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability --ignore-missing-imports
    return
  fi

  "$VENV/bin/mypy" --ignore-missing-imports "${mypy_targets[@]}"
}

run_fast() {
  echo "=== [local_quality_gate] fast checks (parallel, incremental) ==="
  echo "    Detecting changed files..."

  local changed_files
  local frontend_changed
  changed_files="$(detect_changed_py_files)"
  frontend_changed="$(detect_changed_frontend_files)"
  echo "    Changed scope: ${changed_files:0:100}..."
  echo "    Frontend scope changed: ${frontend_changed}"

  PARALLEL_PIDS=()
  PARALLEL_NAMES=()
  PARALLEL_LOGS=()

  # Lightweight governance checks (always run)
  run_parallel_step doc-drift "$VENV/bin/python" "$ROOT/scripts/check_doc_drift.py" --mode auto
  run_parallel_step docs-scope "$VENV/bin/python" "$ROOT/scripts/check_docs_scope.py" --root "$REPO_ROOT"
  run_parallel_step docs-manual-facts "$VENV/bin/python" "$ROOT/scripts/check_docs_manual_facts.py" --root "$REPO_ROOT"
  run_parallel_step docs-ssot-hash "$VENV/bin/python" "$ROOT/scripts/check_docs_ssot_hash.py" --root "$REPO_ROOT"
  run_parallel_step lock-drift "$VENV/bin/python" "$ROOT/scripts/check_lock_drift.py" --root "$REPO_ROOT"
  run_parallel_step no-logs-no-merge "$VENV/bin/python" "$ROOT/scripts/check_no_logs_no_merge.py" --root "$REPO_ROOT" --mode auto
  run_parallel_step write-before-search "$VENV/bin/python" "$ROOT/scripts/check_write_before_search.py" --root "$REPO_ROOT" --mode auto
  run_parallel_step env-contract "$VENV/bin/python" "$ROOT/scripts/check_env_contract.py" --root "$REPO_ROOT" --mode auto --max-contract-size 59
  run_parallel_step env-contract-report "$VENV/bin/python" "$ROOT/scripts/generate_env_contract_report.py" --root "$REPO_ROOT"
  run_parallel_step api-contract "$VENV/bin/python" "$ROOT/scripts/generate_api_contract.py" --check
  run_parallel_step required-checks "$VENV/bin/python" "$ROOT/scripts/check_required_checks_matrix.py"
  run_parallel_step done-signal-claims "$VENV/bin/python" "$ROOT/scripts/check_done_signal_claims.py" --root "$REPO_ROOT"
  run_parallel_step positioning-claims "$VENV/bin/python" "$ROOT/scripts/check_positioning_claims.py" --root "$REPO_ROOT"
  run_parallel_step docs-render-state "$VENV/bin/python" "$ROOT/scripts/check_docs_render_state.py" --root "$REPO_ROOT"
  run_parallel_step docs-fragment-completeness "$VENV/bin/python" "$ROOT/scripts/check_docs_fragment_completeness.py" --root "$REPO_ROOT"
  run_parallel_step docs-truth-routes "$VENV/bin/python" "$ROOT/scripts/check_docs_truth_routes.py" --root "$REPO_ROOT"
  run_parallel_step snapshot-scope-labels "$VENV/bin/python" "$ROOT/scripts/check_snapshot_scope_labels.py" --root "$REPO_ROOT"
  run_parallel_step root-layout "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_layout.py" --root "$REPO_ROOT"
  run_parallel_step root-clean-after-mainflows "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_clean_after_mainflows.py" --root "$REPO_ROOT"
  run_parallel_step root-public-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_public_surface.py" --root "$REPO_ROOT"
  run_parallel_step root-change-control "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_change_control.py" --root "$REPO_ROOT"
  run_parallel_step collaboration-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_collaboration_surface.py" --root "$REPO_ROOT"
  run_parallel_step runtime-language-boundary "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_language_boundary.py" --root "$REPO_ROOT"
  run_parallel_step public-artifact-safety "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_public_artifact_safety.py" --root "$REPO_ROOT"
  run_parallel_step sensitive-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_sensitive_surface.py" --root "$REPO_ROOT" --mode auto
  run_parallel_step local-only-tracking "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_local_only_tracking.py" --root "$REPO_ROOT"
  run_parallel_step feature-state-layout "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_feature_state_layout.py" --root "$REPO_ROOT"
  run_parallel_step mcp-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_mcp_surface.py"
  run_parallel_step strategy-pack-registry "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_strategy_pack_registry.py" --root "$REPO_ROOT"
  run_parallel_step watch-sources-contract "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_watch_sources_contract.py"
  run_parallel_step module-graph "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_module_graph.py" --root "$REPO_ROOT"
  run_parallel_step hotspot-budget "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_hotspot_budget.py" --root "$REPO_ROOT"
  run_parallel_step upstream-drift "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_drift.py" --root "$REPO_ROOT"
  run_parallel_step upstream-registry "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_registry_completeness.py" --root "$REPO_ROOT"
  run_parallel_step upstream-compat "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_compat_matrix.py" --root "$REPO_ROOT"
  run_parallel_step upstream-host-capabilities "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_host_capabilities.py" --root "$REPO_ROOT"
  run_parallel_step upstream-fetch "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_fetch_surfaces.py" --root "$REPO_ROOT"
  run_parallel_step private-upstream-coupling "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_no_private_upstream_coupling.py" --root "$REPO_ROOT"
  run_parallel_step dependency-boundaries "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_dependency_boundaries.py" --root "$REPO_ROOT"
  run_parallel_step logging-contract "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_logging_contract.py" --root "$REPO_ROOT"
  run_parallel_step run-bundle-contract "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_run_bundle_contract.py" --root "$REPO_ROOT"
  run_parallel_step test-quality bash "$ROOT/gates/test_quality_gate.sh"

  # Lint checks (incremental where possible)
  # Note: ruff is already run in pre-commit, so we skip it here to avoid duplication
  # Only run mypy incrementally since it's not in pre-commit
  if [ "$changed_files" = "__FULL__" ]; then
    # Full lint - only mypy (ruff already done in pre-commit)
    run_parallel_step mypy-full "$VENV/bin/mypy" apps/api apps/cli packages/domain packages/application packages/infrastructure packages/observability --ignore-missing-imports
  elif [ "$changed_files" = "__NONE__" ]; then
    echo "    No changed Python files detected; skip mypy."
  else
    # Incremental mypy: bash array is BSD-compatible and avoids unsafe word splitting.
    run_parallel_step mypy-incremental run_mypy_incremental
  fi

  # Unit tests
  if [ "$changed_files" = "__NONE__" ]; then
    echo "    No changed Python files detected; skip pytest."
  elif should_run_full_tests; then
    run_parallel_step pytest-fast run_pytest_with_isolated_tmp env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF "$VENV/bin/python" -m pytest -q -o addopts= --strict-config --strict-markers tests/unit --maxfail=3
  else
    # Run only tests related to changed files
    # Map changed source files to their test files
    local test_files=""
    local mapping_miss=0
    local changed_file="$ARTIFACT_LOGS/changed-py-files.txt"
    if [ -f "$changed_file" ]; then
      while IFS= read -r src; do
        # Extract module name from path like packages/application/analyze_media.py -> analyze_media
        local module_name
        module_name="$(basename "$src" .py)"
        local matched_for_module=0
        # Support both naming styles:
        # - test_<module>*.py
        # - <module>_test.py / *_<module>_test.py
        while IFS= read -r tf; do
          [ -n "$tf" ] || continue
          matched_for_module=1
          test_files="$test_files $tf"
        done < <(
          find tests/unit -type f \
            \( -name "test_${module_name}*.py" -o -name "${module_name}_test.py" -o -name "*_${module_name}_test.py" \) \
            2>/dev/null
        )
        if [ "$matched_for_module" -eq 0 ]; then
          mapping_miss=1
        fi
      done < "$changed_file"
    fi

    if [ -n "$test_files" ] && [ "$mapping_miss" -eq 0 ]; then
      # Run only related tests (deduplicated)
      test_files="$(echo "$test_files" | tr ' ' '\n' | sort -u | tr '\n' ' ')"
      run_parallel_step pytest-incremental run_pytest_with_isolated_tmp env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF "$VENV/bin/python" -m pytest -q -o addopts= --strict-config --strict-markers $test_files --maxfail=3
    else
      # Mapping miss fallback: run full unit suite to avoid false-green from
      # single-file smoke checks when changed modules cannot be mapped.
      run_parallel_step pytest-fallback-full run_pytest_with_isolated_tmp env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF "$VENV/bin/python" -m pytest -q -o addopts= --strict-config --strict-markers tests/unit --maxfail=3
    fi
  fi

  wait_parallel_steps

  if [ "$frontend_changed" = "1" ]; then
    # Frontend lint mutates apps/webui/node_modules during install/cleanup.
    # Run it after the parallel repo scans settle to avoid transient ENOENT/ENOTEMPTY races.
    run_step lint-frontend env LINT_FRONTEND_SKIP_GEMINI_AUDIT=1 bash "$ROOT/gates/lint_frontend.sh"
  else
    echo "=== [local_quality_gate] lint-frontend skipped (no frontend changes detected) ==="
  fi
  cleanup_frontend_runtime_residue
  bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true

  # Runtime cleanliness checks must run after frontend tooling settles, otherwise
  # transient node_modules writes during npm ci can be mistaken for durable residue.
  run_step runtime-layout run_runtime_layout_with_frontend_cleanup
  run_step repo-runtime-residue "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_repo_runtime_residue.py" --root "$REPO_ROOT"
  run_step cache-size "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_cache_size.py" --root "$REPO_ROOT"
  run_step runtime-budget "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_budget.py" --root "$REPO_ROOT"
}

run_prepush_lite() {
  echo "=== [local_quality_gate] prepush-lite checks (minimal local burn) ==="
  PARALLEL_PIDS=()
  PARALLEL_NAMES=()
  PARALLEL_LOGS=()
  run_parallel_step doc-drift "$VENV/bin/python" "$ROOT/scripts/check_doc_drift.py" --mode auto
  run_parallel_step docs-scope "$VENV/bin/python" "$ROOT/scripts/check_docs_scope.py" --root "$REPO_ROOT"
  run_parallel_step docs-manual-facts "$VENV/bin/python" "$ROOT/scripts/check_docs_manual_facts.py" --root "$REPO_ROOT"
  run_parallel_step docs-ssot-hash "$VENV/bin/python" "$ROOT/scripts/check_docs_ssot_hash.py" --root "$REPO_ROOT"
  run_parallel_step lock-drift "$VENV/bin/python" "$ROOT/scripts/check_lock_drift.py" --root "$REPO_ROOT"
  run_parallel_step env-contract "$VENV/bin/python" "$ROOT/scripts/check_env_contract.py" --root "$REPO_ROOT" --mode auto --max-contract-size 59
  run_parallel_step env-contract-report "$VENV/bin/python" "$ROOT/scripts/generate_env_contract_report.py" --root "$REPO_ROOT"
  run_parallel_step api-contract "$VENV/bin/python" "$ROOT/scripts/generate_api_contract.py" --check
  run_parallel_step required-checks "$VENV/bin/python" "$ROOT/scripts/check_required_checks_matrix.py"
  run_parallel_step done-signal-claims "$VENV/bin/python" "$ROOT/scripts/check_done_signal_claims.py" --root "$REPO_ROOT"
  run_parallel_step positioning-claims "$VENV/bin/python" "$ROOT/scripts/check_positioning_claims.py" --root "$REPO_ROOT"
  run_parallel_step docs-render-state "$VENV/bin/python" "$ROOT/scripts/check_docs_render_state.py" --root "$REPO_ROOT"
  run_parallel_step docs-fragment-completeness "$VENV/bin/python" "$ROOT/scripts/check_docs_fragment_completeness.py" --root "$REPO_ROOT"
  run_parallel_step docs-truth-routes "$VENV/bin/python" "$ROOT/scripts/check_docs_truth_routes.py" --root "$REPO_ROOT"
  run_parallel_step snapshot-scope-labels "$VENV/bin/python" "$ROOT/scripts/check_snapshot_scope_labels.py" --root "$REPO_ROOT"
  run_parallel_step root-layout "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_layout.py" --root "$REPO_ROOT"
  run_parallel_step root-clean-after-mainflows "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_clean_after_mainflows.py" --root "$REPO_ROOT"
  run_parallel_step root-public-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_public_surface.py" --root "$REPO_ROOT"
  run_parallel_step root-change-control "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_change_control.py" --root "$REPO_ROOT"
  run_parallel_step collaboration-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_collaboration_surface.py" --root "$REPO_ROOT"
  run_parallel_step runtime-language-boundary "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_language_boundary.py" --root "$REPO_ROOT"
  run_parallel_step public-artifact-safety "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_public_artifact_safety.py" --root "$REPO_ROOT"
  run_parallel_step sensitive-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_sensitive_surface.py" --root "$REPO_ROOT" --mode auto
  run_parallel_step local-only-tracking "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_local_only_tracking.py" --root "$REPO_ROOT"
  run_parallel_step feature-state-layout "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_feature_state_layout.py" --root "$REPO_ROOT"
  run_parallel_step mcp-surface "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_mcp_surface.py"
  run_parallel_step strategy-pack-registry "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_strategy_pack_registry.py" --root "$REPO_ROOT"
  run_parallel_step watch-sources-contract "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_watch_sources_contract.py"
  run_parallel_step module-graph "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_module_graph.py" --root "$REPO_ROOT"
  run_parallel_step hotspot-budget "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_hotspot_budget.py" --root "$REPO_ROOT"
  run_parallel_step upstream-drift "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_drift.py" --root "$REPO_ROOT"
  run_parallel_step upstream-registry "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_registry_completeness.py" --root "$REPO_ROOT"
  run_parallel_step upstream-compat "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_compat_matrix.py" --root "$REPO_ROOT"
  run_parallel_step upstream-host-capabilities "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_host_capabilities.py" --root "$REPO_ROOT"
  run_parallel_step upstream-fetch "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_upstream_fetch_surfaces.py" --root "$REPO_ROOT"
  run_parallel_step private-upstream-coupling "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_no_private_upstream_coupling.py" --root "$REPO_ROOT"
  run_parallel_step dependency-boundaries "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_dependency_boundaries.py" --root "$REPO_ROOT"
  run_parallel_step logging-contract "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_logging_contract.py" --root "$REPO_ROOT"
  run_parallel_step run-bundle-contract "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_run_bundle_contract.py" --root "$REPO_ROOT"
  wait_parallel_steps
  run_step runtime-layout "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_layout.py" --root "$REPO_ROOT"
  run_step repo-runtime-residue "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_repo_runtime_residue.py" --root "$REPO_ROOT"
  run_step cache-size "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_cache_size.py" --root "$REPO_ROOT"
  run_step runtime-budget "$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_budget.py" --root "$REPO_ROOT"
}

run_full() {
  echo "=== [local_quality_gate] full checks ==="
  run_step quality-gate bash "$ROOT/gates/quality_gate.sh"
}

case "$MODE" in
  prepush-lite)
    run_prepush_lite
    ;;
  fast)
    run_fast
    ;;
  full)
    run_full
    ;;
  all)
    run_fast
    run_full
    ;;
  *)
    echo "Usage: bash tooling/gates/local_quality_gate.sh [prepush-lite|fast|full|all]" >&2
    echo "" >&2
    echo "Modes:" >&2
    echo "  fast (default): parallel incremental checks (<60s)" >&2
    echo "  prepush-lite: minimal validation (<15s)" >&2
    echo "  full: complete quality gate (5-15min)" >&2
    echo "  all: fast + full" >&2
    exit 2
    ;;
esac

echo "✅ local_quality_gate: mode=$MODE passed"
