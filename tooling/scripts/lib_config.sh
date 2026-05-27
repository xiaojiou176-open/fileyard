#!/usr/bin/env bash
set -euo pipefail

GOVERNANCE_DEFAULTS_REL="contracts/governance/governance.defaults.env"

trim_spaces() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

read_dotenv_value() {
  local dotenv_path="$1"
  local name="$2"
  local raw_line line key value
  if [ ! -f "$dotenv_path" ]; then
    return 0
  fi

  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    line="$(trim_spaces "$raw_line")"
    if [ -z "$line" ] || [[ "$line" == \#* ]] || [[ "$line" != *=* ]]; then
      continue
    fi

    key="${line%%=*}"
    key="$(trim_spaces "$key")"
    if [ "$key" != "$name" ]; then
      continue
    fi

    value="${line#*=}"
    value="$(trim_spaces "$value")"
    if [ "${#value}" -ge 2 ]; then
      if [[ "$value" == \"*\" ]] && [[ "$value" == *\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" == \'*\' ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    printf '%s' "$value"
    return 0
  done < "$dotenv_path"
  return 0
}

resolve_var_prefer_dotenv_with_source() {
  local name="$1"
  local default_value="${2:-}"
  local dotenv_path="$3"
  local value source
  value="$(read_dotenv_value "$dotenv_path" "$name")"
  if [ -n "$value" ]; then
    source="$dotenv_path"
  elif [ -n "${!name:-}" ]; then
    value="${!name}"
    source="env"
  else
    value="$default_value"
    source="config"
  fi
  export "$name=$value"
  printf '%s|%s' "$value" "$source"
}

resolve_var_prefer_dotenv() {
  local name="$1"
  local default_value="${2:-}"
  local dotenv_path="$3"
  resolve_var_prefer_dotenv_with_source "$name" "$default_value" "$dotenv_path" >/dev/null
}

normalize_flag_01() {
  local raw="$1"
  case "$raw" in
    1) printf '1' ;;
    *) printf '0' ;;
  esac
}

resolve_allow_external_with_source() {
  local default_value="${1:-0}"
  local raw source normalized

  if [ -n "${FILEMAN_ALLOW_EXTERNAL:-}" ]; then
    raw="${FILEMAN_ALLOW_EXTERNAL}"
    source="env(FILEMAN_ALLOW_EXTERNAL)"
  else
    raw="$default_value"
    source="config"
  fi
  normalized="$(normalize_flag_01 "$raw")"
  printf '%s|%s' "$normalized" "$source"
}

load_governance_defaults() {
  local repo_root="$1"
  local defaults_file="${repo_root}/${GOVERNANCE_DEFAULTS_REL}"
  if [ "${_GOVERNANCE_DEFAULTS_LOADED:-0}" = "1" ]; then
    return 0
  fi
  if [ ! -f "$defaults_file" ]; then
    echo "❌ governance defaults missing: $defaults_file" >&2
    return 1
  fi
  # shellcheck disable=SC1090
  . "$defaults_file"
  _GOVERNANCE_DEFAULTS_LOADED=1
}

resolve_repo_path() {
  local repo_root="$1"
  local raw_path="$2"
  case "$raw_path" in
    "~")
      printf '%s' "$HOME"
      ;;
    "~/"*)
      printf '%s/%s' "$HOME" "${raw_path#~/}"
      ;;
    /*)
      printf '%s' "$raw_path"
      ;;
    *)
      printf '%s/%s' "$repo_root" "$raw_path"
      ;;
  esac
}

governance_runtime_cache_root_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_CACHE_ROOT"
}

governance_machine_cache_root_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_MACHINE_CACHE_ROOT"
}

governance_runtime_temp_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_TEMP_DIR"
}

governance_runtime_logs_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_LOG_DIR"
}

governance_runtime_ci_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_CI_DIR"
}

governance_runtime_test_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_TEST_DIR"
}

governance_runtime_build_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_BUILD_DIR"
}

governance_runtime_codegen_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_CODEGEN_DIR"
}

governance_runtime_ci_contract_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_CI_CONTRACT_DIR"
}

governance_runtime_venv_path() {
  local repo_root="$1"
  local venv_rel="${FILEMAN_VENV_DIR:-$GOVERNANCE_RUNTIME_VENV_DIR}"
  resolve_repo_path "$repo_root" "$venv_rel"
}

governance_workspace_root_path() {
  local repo_root="$1"
  local workspace_rel="${FILEMAN_WORKSPACE_ROOT:-$GOVERNANCE_WORKSPACE_ROOT}"
  resolve_repo_path "$repo_root" "$workspace_rel"
}

governance_workspace_input_root_path() {
  local repo_root="$1"
  local input_rel="${FILEMAN_INPUT_ROOT:-$GOVERNANCE_WORKSPACE_INPUT_DIR}"
  resolve_repo_path "$repo_root" "$input_rel"
}

governance_workspace_output_root_path() {
  local repo_root="$1"
  local output_rel="${FILEMAN_OUTPUT_ROOT:-$GOVERNANCE_WORKSPACE_OUTPUT_DIR}"
  resolve_repo_path "$repo_root" "$output_rel"
}

governance_manifest_root_path() {
  local repo_root="$1"
  local manifest_rel="${FILEMAN_MANIFEST_ROOT:-$GOVERNANCE_MANIFEST_ROOT}"
  resolve_repo_path "$repo_root" "$manifest_rel"
}

governance_artifact_root_path() {
  local repo_root="$1"
  local artifact_rel="${FILEMAN_ARTIFACT_ROOT:-$GOVERNANCE_PERSISTENT_ARTIFACTS_DIR}"
  resolve_repo_path "$repo_root" "$artifact_rel"
}

governance_evidence_bundle_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "${FILEMAN_EVIDENCE_BUNDLE_PATH:-$GOVERNANCE_EVIDENCE_BUNDLE_PATH}"
}

governance_run_bundle_root_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "${FILEMAN_RUN_BUNDLE_ROOT:-$GOVERNANCE_RUN_BUNDLE_ROOT}"
}

governance_run_bundle_dir() {
  local repo_root="$1"
  local run_id="$2"
  local run_root
  run_root="$(governance_run_bundle_root_path "$repo_root")"
  printf '%s/%s' "$run_root" "$run_id"
}

governance_runtime_env_file_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_ENV_FILE"
}

governance_mutmut_cache_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_MUTMUT_CACHE_FILE"
}

governance_webui_lock_hash_path() {
  local repo_root="$1"
  resolve_repo_path "$repo_root" "$GOVERNANCE_WEBUI_LOCK_HASH_FILE"
}

governance_tool_config_path() {
  local repo_root="$1"
  local relative_config="$2"
  printf '%s/tooling/config/%s' "$repo_root" "$relative_config"
}

ensure_runtime_layout() {
  local repo_root="$1"
  load_governance_defaults "$repo_root"

  mkdir -p \
    "$(governance_machine_cache_root_path "$repo_root")" \
    "$(governance_runtime_cache_root_path "$repo_root")" \
    "$(governance_runtime_temp_path "$repo_root")" \
    "$(governance_runtime_logs_path "$repo_root")" \
    "$(governance_runtime_ci_path "$repo_root")" \
    "$(governance_runtime_test_path "$repo_root")" \
    "$(governance_runtime_build_path "$repo_root")" \
    "$(governance_runtime_codegen_path "$repo_root")" \
    "$(dirname "$(governance_runtime_venv_path "$repo_root")")" \
    "$(dirname "$(governance_mutmut_cache_path "$repo_root")")" \
    "$(dirname "$(governance_webui_lock_hash_path "$repo_root")")" \
    "$(governance_workspace_root_path "$repo_root")" \
    "$(governance_workspace_input_root_path "$repo_root")" \
    "$(governance_workspace_output_root_path "$repo_root")" \
    "$(governance_manifest_root_path "$repo_root")" \
    "$(governance_artifact_root_path "$repo_root")" \
    "$(governance_run_bundle_root_path "$repo_root")" \
    "$(dirname "$(governance_runtime_env_file_path "$repo_root")")" \
    "$(dirname "$(governance_evidence_bundle_path "$repo_root")")"

  if [ -L "$repo_root/.mutmut-cache" ] || [ -e "$repo_root/.mutmut-cache" ]; then
    rm -rf "$repo_root/.mutmut-cache"
  fi

  # Hard-cut legacy repo-side Ruff cache. The final runtime contract only
  # allows tooling caches under .runtime-cache/build/tooling or machine cache.
  if [ -d "$repo_root/.runtime-cache/ruff" ]; then
    rm -rf "$repo_root/.runtime-cache/ruff"
  fi
}

apply_runtime_env_defaults() {
  local repo_root="$1"
  load_governance_defaults "$repo_root"
  ensure_runtime_layout "$repo_root"

  export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$(resolve_repo_path "$repo_root" "$GOVERNANCE_XDG_CACHE_DIR")}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$(resolve_repo_path "$repo_root" "$GOVERNANCE_PIP_CACHE_DIR")}"
  export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-$(resolve_repo_path "$repo_root" "$GOVERNANCE_NPM_CACHE_DIR")}"
  export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$(resolve_repo_path "$repo_root" "$GOVERNANCE_PLAYWRIGHT_CACHE_DIR")}"
  export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$(resolve_repo_path "$repo_root" "$GOVERNANCE_MACHINE_CACHE_ROOT")/pycache}"
  export MYPY_CACHE_DIR="${MYPY_CACHE_DIR:-$(resolve_repo_path "$repo_root" "$GOVERNANCE_RUNTIME_CACHE_ROOT")/build/tooling/mypy}"
  export TMPDIR="${TMPDIR:-$(governance_runtime_temp_path "$repo_root")}"
  export TMP="${TMP:-$TMPDIR}"
  export TEMP="${TEMP:-$TMPDIR}"
  export FILEMAN_WORKSPACE_ROOT="${FILEMAN_WORKSPACE_ROOT:-$(governance_workspace_root_path "$repo_root")}"
  export FILEMAN_INPUT_ROOT="${FILEMAN_INPUT_ROOT:-$(governance_workspace_input_root_path "$repo_root")}"
  export FILEMAN_OUTPUT_ROOT="${FILEMAN_OUTPUT_ROOT:-$(governance_workspace_output_root_path "$repo_root")}"
  export FILEMAN_MANIFEST_ROOT="${FILEMAN_MANIFEST_ROOT:-$(governance_manifest_root_path "$repo_root")}"
  export FILEMAN_ARTIFACT_ROOT="${FILEMAN_ARTIFACT_ROOT:-$(governance_artifact_root_path "$repo_root")}"
  export FILEMAN_EVIDENCE_BUNDLE_PATH="${FILEMAN_EVIDENCE_BUNDLE_PATH:-$(governance_evidence_bundle_path "$repo_root")}"
  export FILEMAN_RUN_BUNDLE_ROOT="${FILEMAN_RUN_BUNDLE_ROOT:-$(governance_run_bundle_root_path "$repo_root")}"

  mkdir -p \
    "$XDG_CACHE_HOME" \
    "$PIP_CACHE_DIR" \
    "$NPM_CONFIG_CACHE" \
    "$PLAYWRIGHT_BROWSERS_PATH" \
    "$PYTHONPYCACHEPREFIX" \
    "$MYPY_CACHE_DIR" \
    "$TMPDIR" \
    "$FILEMAN_WORKSPACE_ROOT" \
    "$FILEMAN_INPUT_ROOT" \
    "$FILEMAN_OUTPUT_ROOT" \
    "$FILEMAN_MANIFEST_ROOT" \
    "$FILEMAN_ARTIFACT_ROOT" \
    "$FILEMAN_RUN_BUNDLE_ROOT" \
    "$(dirname "$FILEMAN_EVIDENCE_BUNDLE_PATH")"
}

governance_python() {
  local repo_root="$1"
  shift

  load_governance_defaults "$repo_root"
  apply_runtime_env_defaults "$repo_root"

  local governed_pythonpath="${repo_root}/tooling/scripts:${repo_root}"
  if [ -n "${PYTHONPATH:-}" ]; then
    PYTHONPATH="${governed_pythonpath}:${PYTHONPATH}" python3 "$@"
    return
  fi

  PYTHONPATH="${governed_pythonpath}" python3 "$@"
}
