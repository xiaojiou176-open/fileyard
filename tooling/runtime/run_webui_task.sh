#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

TASK="${1:-}"
SKIP_INSTALL=0
EXTRA_ARGS=()

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

usage() {
  cat <<'EOF' >&2
Usage: bash tooling/runtime/run_webui_task.sh <ci-install|build|test|lint|dev> [--skip-install] [-- <extra args>]
EOF
}

join_shell_command() {
  local joined=""
  local part=""
  for part in "$@"; do
    if [ -n "$joined" ]; then
      joined+=" "
    fi
    joined+="$(printf '%q' "$part")"
  done
  printf '%s' "$joined"
}

is_ci_context() {
  [ "${CI:-}" = "1" ] || [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]
}

if [ -z "$TASK" ]; then
  usage
  exit 2
fi
shift

while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --)
      shift
      EXTRA_ARGS=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

case "$TASK" in
  ci-install|build|test|lint|dev) ;;
  *)
    echo "❌ run_webui_task: unsupported task=$TASK" >&2
    usage
    exit 2
    ;;
esac

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ]; then
  cleanup_host_webui_mountpoint() {
    if [ ! -d "$REPO_ROOT/apps/webui/node_modules" ]; then
      return 0
    fi
    # Host-side cleanup is best-effort only. A containerized install can leave
    # files owned by another UID, and that should not masquerade as a repo-side
    # failure for ci-install/build/test/lint orchestration.
    shopt -s dotglob nullglob
    rm -rf "$REPO_ROOT/apps/webui/node_modules"/* 2>/dev/null || true
    shopt -u dotglob nullglob
    rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true
  }

  if [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
    if is_ci_context; then
      echo "❌ run_webui_task: FILEMAN_ALLOW_HOST_EXECUTION=1 is forbidden in CI" >&2
      exit 1
    fi
    echo "⚠️ run_webui_task: emergency host execution enabled; canonical webui task path stays containerized by default" >&2
  else
    if [ "$SKIP_INSTALL" = "1" ] && [ "$TASK" != "ci-install" ]; then
      CONTAINER_INSTALL_COMMAND="$(join_shell_command bash tooling/runtime/run_webui_task.sh ci-install)"
      CONTAINER_TASK_COMMAND=(bash tooling/runtime/run_webui_task.sh "$TASK" --skip-install)
      if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
        CONTAINER_TASK_COMMAND+=("${EXTRA_ARGS[@]}")
      fi
      CONTAINER_SKIP_INSTALL_COMMAND="$(join_shell_command "${CONTAINER_TASK_COMMAND[@]}")"
      env FILEMAN_COMPOSE_SERVICE=fileman-web-api bash "$ROOT/scripts/container_exec.sh" --label "webui-${TASK}" -- bash -lc "${CONTAINER_INSTALL_COMMAND} && ${CONTAINER_SKIP_INSTALL_COMMAND}"
    else
      CONTAINER_ARGS=(bash tooling/runtime/run_webui_task.sh "$TASK")
      if [ "$SKIP_INSTALL" = "1" ]; then
        CONTAINER_ARGS+=(--skip-install)
      fi
      if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
        CONTAINER_ARGS+=("${EXTRA_ARGS[@]}")
      fi
      env FILEMAN_COMPOSE_SERVICE=fileman-web-api bash "$ROOT/scripts/container_exec.sh" --label "webui-${TASK}" -- "${CONTAINER_ARGS[@]}"
    fi
    task_rc=$?
    cleanup_host_webui_mountpoint
    exit "$task_rc"
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ run_webui_task: npm not found in PATH" >&2
  exit 1
fi

if [ ! -f "$REPO_ROOT/apps/webui/package.json" ]; then
  echo "❌ run_webui_task: missing apps/webui/package.json" >&2
  exit 1
fi

WEBUI_HASH_FILE="$(governance_webui_lock_hash_path "$REPO_ROOT")"
NPM_CACHE_DIR="$(resolve_repo_path "$REPO_ROOT" "$GOVERNANCE_NPM_CACHE_DIR")"

clear_dir_contents() {
  local target="$1"
  mkdir -p "$target"
  shopt -s dotglob nullglob
  rm -rf "$target"/* 2>/dev/null || true
  shopt -u dotglob nullglob
}

install_webui_deps() {
  mkdir -p "$NPM_CACHE_DIR"
  mkdir -p "$REPO_ROOT/.runtime-cache/tmp"

  reset_webui_node_modules() {
    # Keep pre-push and quality_gate focused on the real npm failure, not stale node_modules residue.
    local target="$REPO_ROOT/apps/webui/node_modules"
    local quarantine="$REPO_ROOT/.runtime-cache/tmp/webui-node-modules-stale-$$"
    # Keep host-emergency recovery aligned with quality_gate and pre-push residue hygiene.
    if [ -d "$target" ]; then
      rm -rf "$quarantine" 2>/dev/null || true
      if mv "$target" "$quarantine" 2>/dev/null; then
        rm -rf "$quarantine" 2>/dev/null || true
      else
        find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
      fi
    fi
    mkdir -p "$target"
  }

  run_webui_install() {
    if [ -f "$REPO_ROOT/apps/webui/package-lock.json" ]; then
      npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ci
      return 0
    fi
    echo "❌ [webui-task] apps/webui/package-lock.json is required for deterministic installs" >&2
    return 1
  }

  webui_install_healthy() {
    [ -x "$REPO_ROOT/apps/webui/node_modules/.bin/vite" ] || return 1
    npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0 >/dev/null 2>&1 || return 1
    npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" exec vite -- --version >/dev/null 2>&1
  }

  clear_dir_contents "$REPO_ROOT/apps/webui/node_modules"
  if find "$REPO_ROOT/apps/webui/node_modules" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "⚠️ [webui-task] node_modules cleanup left residue; continuing with install retry path" >&2
  fi
  if ! run_webui_install || ! webui_install_healthy; then
    echo "⚠️ [webui-task] npm ci retrying after hard reset of node_modules" >&2
    reset_webui_node_modules
    run_webui_install
    webui_install_healthy
  fi
}

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

ensure_webui_deps() {
  if [ "$SKIP_INSTALL" = "1" ]; then
    return 0
  fi

  local deps_hash prev_hash webui_deps_ok
  deps_hash="$(compute_webui_deps_hash)"
  prev_hash=""
  if [ -f "$WEBUI_HASH_FILE" ]; then
    prev_hash="$(cat "$WEBUI_HASH_FILE" 2>/dev/null || true)"
  fi

  webui_deps_ok=1
  if [ -x "$REPO_ROOT/apps/webui/node_modules/.bin/vite" ]; then
    if ! npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0 >/dev/null 2>&1; then
      webui_deps_ok=0
    fi
  else
    webui_deps_ok=0
  fi

  if [ "$webui_deps_ok" = "1" ] && [ "$deps_hash" = "$prev_hash" ]; then
    return 0
  fi

  echo "==> [webui-task] phase=bootstrap action=install-deps task=${TASK}"
  install_webui_deps
  mkdir -p "$(dirname "$WEBUI_HASH_FILE")"
  printf '%s' "$deps_hash" > "$WEBUI_HASH_FILE"
}

ensure_webui_deps

exec_webui_npm_script() {
  local script_name="$1"
  shift || true
  if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    exec npm --prefix "$REPO_ROOT/apps/webui" run "$script_name" -- "${EXTRA_ARGS[@]}"
  fi
  exec npm --prefix "$REPO_ROOT/apps/webui" run "$script_name"
}

case "$TASK" in
  ci-install)
    echo "==> [webui-task] phase=done task=ci-install"
    ;;
  build)
    exec_webui_npm_script build
    ;;
  test)
    exec_webui_npm_script test
    ;;
  lint)
    exec_webui_npm_script lint
    ;;
  dev)
    exec_webui_npm_script dev
    ;;
esac
