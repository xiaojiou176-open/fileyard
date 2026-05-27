#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
FRONTEND_SCOPE_FILE="$REPO_ROOT/tooling/config/frontend-scope.yml"
SKIP_GEMINI_AUDIT="${LINT_FRONTEND_SKIP_GEMINI_AUDIT:-0}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

ARTIFACT_LOGS="$(governance_runtime_logs_path "$REPO_ROOT")/lint-frontend"
WEBUI_HASH_FILE="$(governance_webui_lock_hash_path "$REPO_ROOT")"
NPM_CACHE_DIR="$(resolve_repo_path "$REPO_ROOT" "$GOVERNANCE_NPM_CACHE_DIR")"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ]; then
  cleanup_host_webui_mountpoint() {
    if [ ! -d "$REPO_ROOT/apps/webui/node_modules" ]; then
      return 0
    fi
    find "$REPO_ROOT/apps/webui/node_modules" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true
  }

  if [ "${LINT_FRONTEND_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
    echo "⚠️ lint_frontend: explicit host execution enabled; canonical frontend verification stays containerized by default" >&2
  else
    env -u FILEORGANIZE_ALLOW_HOST_EXECUTION FILEORGANIZE_COMPOSE_SERVICE=fileorganize-web-api bash "$ROOT/scripts/container_exec.sh" --label lint-frontend -- bash tooling/gates/lint_frontend.sh "$@"
    rc=$?
    cleanup_host_webui_mountpoint
    exit "$rc"
  fi
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ lint_frontend: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

mkdir -p "$ARTIFACT_LOGS"

frontend_file_args=(
  -g '**/*.js'
  -g '**/*.jsx'
  -g '**/*.ts'
  -g '**/*.tsx'
  -g '**/*.css'
  -g '**/*.scss'
  -g '**/*.sass'
  -g '**/*.less'
  -g '**/*.html'
  -g '**/*.vue'
  -g '**/*.svelte'
  -g '**/*.astro'
)

frontend_ignore_args=(
  -g '!**/node_modules/**'
  -g '!**/.venv/**'
  -g '!**/.git/**'
  -g '!**/dist/**'
  -g '!**/build/**'
  -g '!**/artifacts/**'
  -g '!**/.runtime-cache/**'
  -g '!**/.mypy_cache/**'
  -g '!**/.pytest_cache/**'
)

frontend_files=()
if command -v rg >/dev/null 2>&1; then
  while IFS= read -r file; do
    frontend_files+=("$file")
  done < <(rg --files "$REPO_ROOT" "${frontend_file_args[@]}" "${frontend_ignore_args[@]}")
else
  while IFS= read -r file; do
    case "$file" in
      *.js|*.jsx|*.ts|*.tsx|*.css|*.scss|*.sass|*.less|*.html|*.vue|*.svelte|*.astro)
        frontend_files+=("$file")
        ;;
      *)
        ;;
    esac
  done < <(
    find "$REPO_ROOT" \
      -type d \( -name node_modules -o -name .venv -o -name .git -o -name dist -o -name build -o -name artifacts -o -name .runtime-cache -o -name .mypy_cache -o -name .pytest_cache \) -prune \
      -o -type f -print
  )
fi
frontend_count="${#frontend_files[@]}"

frontend_scope_mode() {
  if [ ! -f "$FRONTEND_SCOPE_FILE" ]; then
    echo ""
    return 0
  fi
  awk -F: '/^mode:/ {gsub(/[[:space:]]/, "", $2); print tolower($2); exit}' "$FRONTEND_SCOPE_FILE"
}

scope_mode="$(frontend_scope_mode)"

if [ "$frontend_count" -eq 0 ]; then
  if [ "$scope_mode" = "none" ]; then
    echo "ℹ️ lint_frontend: frontend scope explicitly declared as none via tooling/config/frontend-scope.yml"
    echo "✅ lint_frontend: checks passed (scope=none)"
    exit 0
  fi
  echo "❌ lint_frontend: no frontend files detected, but frontend scope is not explicitly declared." >&2
  echo "Create tooling/config/frontend-scope.yml with 'mode: none' (or add real frontend sources)." >&2
  exit 1
fi

if [ "$scope_mode" = "none" ]; then
  echo "❌ lint_frontend: frontend files detected but tooling/config/frontend-scope.yml declares mode=none" >&2
  exit 1
fi

echo "ℹ️ lint_frontend: detected frontend sources: $frontend_count file(s)"

run_step() {
  local name="$1"
  shift
  echo "=== [lint_frontend] $name ==="
  if "$@" 2>&1 | tee "$ARTIFACT_LOGS/lint-frontend-${name}.log"; then
    echo "✅ [lint_frontend] $name passed"
    return 0
  fi
  echo "❌ [lint_frontend] $name failed"
  return 1
}

ensure_node_dependencies() {
  if [ ! -f "$REPO_ROOT/apps/webui/package.json" ]; then
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    return 1
  fi
  mkdir -p "$NPM_CACHE_DIR"

  compute_webui_deps_hash() {
    if command -v shasum >/dev/null 2>&1; then
      cat "$REPO_ROOT/apps/webui/package.json" "$REPO_ROOT/apps/webui/package-lock.json" | shasum -a 256 | awk '{print $1}'
      return 0
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      cat "$REPO_ROOT/apps/webui/package.json" "$REPO_ROOT/apps/webui/package-lock.json" | sha256sum | awk '{print $1}'
      return 0
    fi
    cat "$REPO_ROOT/apps/webui/package.json" "$REPO_ROOT/apps/webui/package-lock.json" | cksum | awk '{print $1}'
  }

  webui_deps_hash="$(compute_webui_deps_hash)"
  prev_webui_deps_hash=""
  if [ -f "$WEBUI_HASH_FILE" ]; then
    prev_webui_deps_hash="$(cat "$WEBUI_HASH_FILE" 2>/dev/null || true)"
  fi

  webui_deps_ok=1
  if [ -x "$REPO_ROOT/apps/webui/node_modules/.bin/eslint" ]; then
    if ! npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0 >/dev/null 2>&1; then
      webui_deps_ok=0
    fi
  else
    webui_deps_ok=0
  fi

  if [ "$webui_deps_ok" = "1" ] && [ "$webui_deps_hash" = "$prev_webui_deps_hash" ]; then
    return 0
  fi

  echo "=== [lint_frontend] npm-install-webui ==="
  _reset_webui_node_modules() {
    mkdir -p "$REPO_ROOT/apps/webui/node_modules"
    find "$REPO_ROOT/apps/webui/node_modules" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
  }

  _run_webui_install() {
    if [ -f "$REPO_ROOT/apps/webui/package-lock.json" ]; then
      npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ci
      return 0
    fi
    echo "❌ [lint_frontend] apps/webui/package-lock.json is required for deterministic installs" >&2
    return 1
  }

  _webui_install_healthy() {
    [ -x "$REPO_ROOT/apps/webui/node_modules/.bin/eslint" ] || return 1
    npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0 >/dev/null 2>&1 || return 1
    npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" exec eslint -- --version >/dev/null 2>&1
  }

  _reset_webui_node_modules
  if ! _run_webui_install 2>&1 | tee "$ARTIFACT_LOGS/lint-frontend-npm-install-webui.log" || ! _webui_install_healthy; then
    echo "⚠️ [lint_frontend] npm-ci-webui retrying after hard reset of node_modules" | tee -a "$ARTIFACT_LOGS/lint-frontend-npm-install-webui.log"
    _reset_webui_node_modules
    _run_webui_install 2>&1 | tee -a "$ARTIFACT_LOGS/lint-frontend-npm-install-webui.log"
    _webui_install_healthy
  fi
  mkdir -p "$(dirname "$WEBUI_HASH_FILE")"
  printf '%s' "$webui_deps_hash" > "$WEBUI_HASH_FILE"
}

cleanup_webui_node_modules() {
  # Keep quality_gate focused on real frontend lint failures, not transient
  # volume-release timing during post-run cleanup.
  find "$REPO_ROOT/apps/webui/node_modules" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
  rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true
}

trap cleanup_webui_node_modules EXIT INT TERM

is_ci_context() {
  [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]
}

run_gemini_audit_with_timeout() {
  local log_file="$1"
  shift
  local timeout_seconds="${LINT_FRONTEND_LOCAL_GEMINI_TIMEOUT_SECONDS:-60}"
  if is_ci_context; then
    "$@" 2>&1 | tee "$log_file"
    return "${PIPESTATUS[0]}"
  fi

  set +e
  "$@" >"$log_file" 2>&1 &
  local audit_pid=$!
  local elapsed=0
  while kill -0 "$audit_pid" 2>/dev/null; do
    if [ "$elapsed" -ge "$timeout_seconds" ]; then
      echo "⚠️ [lint_frontend] gemini-ui-ux-audit exceeded ${timeout_seconds}s in local mode; terminating" >>"$log_file"
      kill "$audit_pid" 2>/dev/null || true
      sleep 1
      kill -s KILL "$audit_pid" 2>/dev/null || true
      wait "$audit_pid" 2>/dev/null || true
      printf '%s\n' "GEMINI_UI_AUDIT_LOCAL_TIMEOUT"
      cat "$log_file"
      set -e
      return 124
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  wait "$audit_pid"
  local audit_rc=$?
  cat "$log_file"
  set -e
  return "$audit_rc"
}

is_local_skippable_gemini_error() {
  local log_file="$1"
  grep -Eqi "API_KEY_SERVICE_BLOCKED|PERMISSION_DENIED|SERVICE_DISABLED|status=403|HTTP 403|DEADLINE_EXCEEDED|CANCELLED|status=499|operation was cancelled|GEMINI_UI_AUDIT_LOCAL_TIMEOUT|exceeded [0-9]+s in local mode" "$log_file"
}

run_step "a11y-static" "$VENV/bin/python" "$ROOT/scripts/check_frontend_a11y.py" "${frontend_files[@]}"
if [ "$SKIP_GEMINI_AUDIT" = "1" ]; then
  echo "⚠️ [lint_frontend] gemini-ui-ux-audit skipped: delegated to outer gate"
else
  echo "=== [lint_frontend] gemini-ui-ux-audit ==="
  gemini_log="$ARTIFACT_LOGS/lint-frontend-gemini-ui-ux-audit.log"
  if [ -z "${GEMINI_API_KEY:-}" ]; then
    if is_ci_context; then
      echo "❌ [lint_frontend] gemini-ui-ux-audit failed: GEMINI_API_KEY is required in CI when frontend sources exist" >&2
      exit 1
    fi
    echo "⚠️ [lint_frontend] gemini-ui-ux-audit skipped: GEMINI_API_KEY missing in local mode"
    printf '%s\n' "gemini-ui-ux-audit skipped: local mode without GEMINI_API_KEY" >"$gemini_log"
  else
    set +e
    run_gemini_audit_with_timeout "$gemini_log" "$VENV/bin/python" "$ROOT/scripts/gemini_ui_ux_audit.py" --model "${GEMINI_UI_AUDIT_MODEL:-gemini-3-flash-preview}" "${frontend_files[@]}"
    gemini_rc=$?
    set -e

    if [ "$gemini_rc" -eq 0 ]; then
      echo "✅ [lint_frontend] gemini-ui-ux-audit passed"
    elif is_ci_context; then
      echo "❌ [lint_frontend] gemini-ui-ux-audit failed in CI" >&2
      exit 1
    elif is_local_skippable_gemini_error "$gemini_log"; then
      echo "⚠️ [lint_frontend] gemini-ui-ux-audit skipped: transient/provider issue in local mode"
    else
      echo "❌ [lint_frontend] gemini-ui-ux-audit failed in local mode (non-skippable error)" >&2
      exit 1
    fi
  fi
fi

pkg_manager=""
if [ -f "$REPO_ROOT/pnpm-lock.yaml" ]; then
  pkg_manager="pnpm"
elif [ -f "$REPO_ROOT/yarn.lock" ]; then
  pkg_manager="yarn"
elif [ -f "$REPO_ROOT/package-lock.json" ]; then
  pkg_manager="npm"
fi

if [ -f "$REPO_ROOT/package.json" ]; then
  ensure_node_dependencies
  if [ -z "$pkg_manager" ]; then
    pkg_manager="npm"
  fi

  if [ "$pkg_manager" = "pnpm" ] && command -v pnpm >/dev/null 2>&1; then
    if run_step "pnpm-lint-frontend" pnpm run -r lint:frontend; then
      echo "✅ lint_frontend: checks passed"
      exit 0
    fi
    if run_step "pnpm-lint" pnpm run -r lint; then
      echo "✅ lint_frontend: checks passed"
      exit 0
    fi
    echo "❌ lint_frontend: package.json exists, but pnpm lint commands failed" >&2
    exit 1
  fi

  if [ "$pkg_manager" = "yarn" ] && command -v yarn >/dev/null 2>&1; then
    if run_step "yarn-lint-frontend" yarn lint:frontend; then
      echo "✅ lint_frontend: checks passed"
      exit 0
    fi
    if run_step "yarn-lint" yarn lint; then
      echo "✅ lint_frontend: checks passed"
      exit 0
    fi
    echo "❌ lint_frontend: package.json exists, but yarn lint commands failed" >&2
    exit 1
  fi

  if [ "$pkg_manager" = "npm" ] && command -v npm >/dev/null 2>&1; then
    if [ -f "$REPO_ROOT/apps/webui/package.json" ]; then
      if run_step "npm-lint-webui" npm --prefix "$REPO_ROOT/apps/webui" run lint; then
        echo "✅ lint_frontend: checks passed"
        exit 0
      fi
      echo "❌ lint_frontend: package.json exists, but webui npm lint command failed" >&2
      exit 1
    fi
    if run_step "npm-lint" npm run lint; then
      echo "✅ lint_frontend: checks passed"
      exit 0
    fi
    echo "❌ lint_frontend: package.json exists, but npm lint command failed" >&2
    exit 1
  fi

  echo "❌ lint_frontend: package.json exists but required package manager '$pkg_manager' is missing" >&2
  echo "Install it and dependencies, then rerun: $pkg_manager install && $pkg_manager run lint" >&2
  exit 1
fi

if [ -f "$REPO_ROOT/tooling/config/biome.json" ] || [ -f "$REPO_ROOT/tooling/config/biome.jsonc" ]; then
  if command -v biome >/dev/null 2>&1; then
    run_step "biome-check" biome check --config-path "$REPO_ROOT/tooling/config/biome.json" "${frontend_files[@]}"
    echo "✅ lint_frontend: checks passed"
    exit 0
  fi
  if [ -x "$REPO_ROOT/node_modules/.bin/biome" ]; then
    run_step "biome-check" "$REPO_ROOT/node_modules/.bin/biome" check --config-path "$REPO_ROOT/tooling/config/biome.json" "${frontend_files[@]}"
    echo "✅ lint_frontend: checks passed"
    exit 0
  fi
  echo "❌ lint_frontend: biome config detected but biome is not installed" >&2
  echo "Install with: npm install --save-dev @biomejs/biome" >&2
  exit 1
fi

if [ -f "$REPO_ROOT/eslint.config.js" ] || [ -f "$REPO_ROOT/eslint.config.mjs" ] || [ -f "$REPO_ROOT/.eslintrc" ] || [ -f "$REPO_ROOT/.eslintrc.js" ] || [ -f "$REPO_ROOT/.eslintrc.cjs" ] || [ -f "$REPO_ROOT/.eslintrc.json" ] || [ -f "$REPO_ROOT/.eslintrc.yaml" ] || [ -f "$REPO_ROOT/.eslintrc.yml" ]; then
  if command -v eslint >/dev/null 2>&1; then
    run_step "eslint" eslint --max-warnings=0 "${frontend_files[@]}"
    echo "✅ lint_frontend: checks passed"
    exit 0
  fi
  if [ -x "$REPO_ROOT/node_modules/.bin/eslint" ]; then
    run_step "eslint" "$REPO_ROOT/node_modules/.bin/eslint" --max-warnings=0 "${frontend_files[@]}"
    echo "✅ lint_frontend: checks passed"
    exit 0
  fi
  echo "❌ lint_frontend: ESLint config detected but eslint is not installed" >&2
  echo "Install with: npm install --save-dev eslint" >&2
  exit 1
fi

echo "❌ lint_frontend: found frontend sources ($frontend_count files) but no lint tool/config was detected" >&2
echo "Expected one of: package.json lint script, biome config, or ESLint config." >&2
echo "Suggested setup: npm init -y && npm install --save-dev eslint && npx eslint --init" >&2
exit 1
