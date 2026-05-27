#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

HOST="${FILEORGANIZE_WEBUI_HOST:-127.0.0.1}"
PORT="${FILEORGANIZE_WEBUI_PORT:-5173}"
SKIP_INSTALL=0

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ]; then
  if [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
    echo "❌ run_webui: host execution is forbidden by the final-form runtime policy" >&2
    echo "Use the default containerized path; do not install WebUI dependencies into the repo tree." >&2
    exit 1
  fi
  env FILEORGANIZE_COMPOSE_SERVICE=fileorganize-webui bash "$ROOT/scripts/container_exec.sh" --label run-webui -- bash tooling/runtime/run_webui.sh "$@"
  run_rc=$?
  if [ -d "$REPO_ROOT/apps/webui/node_modules" ] && [ -z "$(ls -A "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true)" ]; then
    rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true
  fi
  exit "$run_rc"
fi

WEBUI_HASH_FILE="$(governance_webui_lock_hash_path "$REPO_ROOT")"
NPM_CACHE_DIR="$(resolve_repo_path "$REPO_ROOT" "$GOVERNANCE_NPM_CACHE_DIR")"

usage() {
  echo "Usage: bash tooling/runtime/run_webui.sh [--host <ip>] [--port <port>] [--skip-install]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      HOST="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "❌ run_webui: unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ run_webui: npm not found in PATH" >&2
  exit 1
fi

if [ ! -f "$REPO_ROOT/apps/webui/package.json" ]; then
  echo "❌ run_webui: missing apps/webui/package.json" >&2
  exit 1
fi

install_webui_deps() {
  mkdir -p "$NPM_CACHE_DIR"
  if [ -f "$REPO_ROOT/apps/webui/package-lock.json" ]; then
    npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ci
    return 0
  fi
  echo "❌ run_webui: apps/webui/package-lock.json is required for reproducible installs" >&2
  return 1
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

webui_deps_hash="$(compute_webui_deps_hash)"
prev_webui_deps_hash=""
if [ -f "$WEBUI_HASH_FILE" ]; then
  prev_webui_deps_hash="$(cat "$WEBUI_HASH_FILE" 2>/dev/null || true)"
fi

webui_deps_ok=1
if [ -x "$REPO_ROOT/apps/webui/node_modules/.bin/vite" ]; then
  if ! npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0 >/dev/null 2>&1; then
    webui_deps_ok=0
  fi
else
  webui_deps_ok=0
fi

if [ "$SKIP_INSTALL" != "1" ] && { [ "$webui_deps_ok" != "1" ] || [ "$webui_deps_hash" != "$prev_webui_deps_hash" ]; }; then
  echo "==> [webui] phase=bootstrap action=install-deps"
  install_webui_deps
  mkdir -p "$(dirname "$WEBUI_HASH_FILE")"
  printf "%s" "$webui_deps_hash" > "$WEBUI_HASH_FILE"
fi

echo "==> [webui] phase=start host=${HOST} port=${PORT}"
echo "==> [webui] phase=start command=npm --prefix apps/webui run dev -- --host ${HOST} --port ${PORT} --strictPort"
exec npm --prefix "$REPO_ROOT/apps/webui" run dev -- --host "$HOST" --port "$PORT" --strictPort
