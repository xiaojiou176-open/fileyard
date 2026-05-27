#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

MODE="local"
ACTION="up"
DETACH=0
API_HOST="${FILEMAN_WEB_API_HOST:-127.0.0.1}"
WEB_HOST="${FILEMAN_WEBUI_HOST:-127.0.0.1}"
API_PORT="${FILEMAN_WEB_API_PORT:-18080}"
WEB_PORT="${FILEMAN_WEBUI_PORT:-5173}"

COMPOSE_FILE="${FILEMAN_COMPOSE_FILE:-ops/compose/docker-compose.yml}"
COMPOSE_ARGS=()
COMPOSE_PROJECT_NAME_FALLBACK="${COMPOSE_PROJECT_NAME:-}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
RUNTIME_ENV_FILE="$(governance_runtime_env_file_path "$REPO_ROOT")"

usage() {
  cat <<'EOF' >&2
Usage:
  bash tooling/runtime/run_web_stack.sh [--mode local|compose] [--action up|down]
                                  [--api-host <ip>] [--web-host <ip>]
                                  [--api-port <port>] [--web-port <port>]
                                  [--detach]
EOF
}

detect_static_mount_gap() {
  local index_path="$REPO_ROOT/.runtime-cache/build/apps/webui/index.html"
  if [ ! -f "$index_path" ]; then
    return 0
  fi
  if grep -Fq '"/assets/' "$index_path" || grep -Fq "'/assets/" "$index_path"; then
    echo "WARN [web-stack] detected .runtime-cache/build/apps/webui absolute assets (/assets/*)." >&2
    echo "WARN [web-stack] backend currently serves /app/assets, so /app static hosting may drift." >&2
    echo "WARN [web-stack] startup will prioritize Vite dev URL: http://127.0.0.1:${WEB_PORT}" >&2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --action)
      ACTION="${2:-}"
      shift 2
      ;;
    --api-host)
      API_HOST="${2:-}"
      shift 2
      ;;
    --web-host)
      WEB_HOST="${2:-}"
      shift 2
      ;;
    --api-port)
      API_PORT="${2:-}"
      shift 2
      ;;
    --web-port)
      WEB_PORT="${2:-}"
      shift 2
      ;;
    --detach)
      DETACH=1
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "❌ run_web_stack: unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ "$MODE" != "local" ] && [ "$MODE" != "compose" ]; then
  echo "❌ run_web_stack: unsupported mode=${MODE}" >&2
  exit 2
fi

if [ "$ACTION" != "up" ] && [ "$ACTION" != "down" ]; then
  echo "❌ run_web_stack: unsupported action=${ACTION}" >&2
  exit 2
fi

if [ -f "$RUNTIME_ENV_FILE" ]; then
  COMPOSE_ARGS+=(--env-file "$RUNTIME_ENV_FILE")
fi
COMPOSE_ARGS+=(-f "$REPO_ROOT/$COMPOSE_FILE")

if [ -z "$COMPOSE_PROJECT_NAME_FALLBACK" ]; then
  COMPOSE_PROJECT_NAME_FALLBACK="$GOVERNANCE_COMPOSE_PROJECT_NAME_DEFAULT"
fi

cleanup_local_children() {
  if [ "${API_PID:-}" != "" ]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  if [ "${WEB_PID:-}" != "" ]; then
    kill "$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
  fi
}

run_compose() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ run_web_stack: docker is required for --mode compose" >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "❌ run_web_stack: docker compose plugin is required" >&2
    exit 1
  fi

  if [ "$ACTION" = "down" ]; then
    echo "==> [web-stack-compose] phase=down services=fileman-webui,fileman-web-api"
    env COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_FALLBACK" docker compose "${COMPOSE_ARGS[@]}" stop fileman-webui fileman-web-api >/dev/null 2>&1 || true
    env COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_FALLBACK" docker compose "${COMPOSE_ARGS[@]}" rm -f fileman-webui fileman-web-api >/dev/null 2>&1 || true
    echo "✅ [web-stack-compose] action=down finished"
    return 0
  fi

  detect_static_mount_gap
  local up_args=(up --build fileman-web-api fileman-webui)
  if [ "$DETACH" = "1" ]; then
    up_args=(up --build -d fileman-web-api fileman-webui)
  fi

  echo "==> [web-stack-compose] phase=up detach=${DETACH}"
  echo "==> [web-stack-compose] urls api=http://127.0.0.1:${API_PORT} webui=http://127.0.0.1:${WEB_PORT}"
  echo "==> [web-stack-compose] note=/app static hosting kept as secondary path while asset base mismatch exists"
  FILEMAN_WEB_API_HOST=0.0.0.0 \
  FILEMAN_WEBUI_HOST=0.0.0.0 \
  FILEMAN_WEB_API_PORT="$API_PORT" \
  FILEMAN_WEBUI_PORT="$WEB_PORT" \
    env COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_FALLBACK" docker compose "${COMPOSE_ARGS[@]}" "${up_args[@]}"
}

run_local() {
  if [ "$ACTION" = "down" ]; then
    echo "==> [web-stack-local] action=down is not supported (use Ctrl+C on running stack)" >&2
    exit 2
  fi

  trap cleanup_local_children EXIT INT TERM

  detect_static_mount_gap
  echo "==> [web-stack-local] phase=start api_host=${API_HOST} api_port=${API_PORT} web_host=${WEB_HOST} web_port=${WEB_PORT}"
  bash "$ROOT/runtime/run_web_api.sh" --host "$API_HOST" --port "$API_PORT" &
  API_PID="$!"
  bash "$ROOT/runtime/run_webui.sh" --host "$WEB_HOST" --port "$WEB_PORT" &
  WEB_PID="$!"

  echo "==> [web-stack-local] urls api=http://127.0.0.1:${API_PORT} webui=http://127.0.0.1:${WEB_PORT}"
  echo "==> [web-stack-local] note=/app static hosting kept as secondary path while asset base mismatch exists"

  local start_ts now_ts elapsed
  start_ts="$(date +%s)"
  while true; do
    sleep 5

    if ! kill -0 "$API_PID" 2>/dev/null; then
      wait "$API_PID" || true
      echo "❌ [web-stack-local] phase=watch reason=web-api-exited pid=${API_PID}" >&2
      return 1
    fi

    if ! kill -0 "$WEB_PID" 2>/dev/null; then
      wait "$WEB_PID" || true
      echo "❌ [web-stack-local] phase=watch reason=webui-exited pid=${WEB_PID}" >&2
      return 1
    fi

    now_ts="$(date +%s)"
    elapsed=$((now_ts - start_ts))
    if [ $((elapsed % 30)) -eq 0 ]; then
      echo "==> [web-stack-local] phase=heartbeat elapsed=${elapsed}s api_pid=${API_PID} web_pid=${WEB_PID}"
    fi
  done
}

if [ "$MODE" = "compose" ]; then
  run_compose
else
  run_local
fi
