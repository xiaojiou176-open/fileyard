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

HOST="${MOVI_WEB_API_HOST:-127.0.0.1}"
PORT="${MOVI_WEB_API_PORT:-18080}"

usage() {
  echo "Usage: bash tooling/runtime/run_web_api.sh [--host <ip>] [--port <port>]" >&2
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "❌ run_web_api: unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> [web-api] phase=bootstrap action=create-venv path=${VENV}"
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

REQ_HASH="$(
  # Keep runtime bootstrap aligned with quality_gate and pre-push lockfile truth:
  # when either Python lockfile drifts, reinstall before web-api start.
  cat "$REPO_ROOT/tooling/requirements.lock.txt" "$REPO_ROOT/tooling/requirements-dev.lock.txt" \
    | shasum -a 256 \
    | awk '{print $1}'
)"
REQ_HASH_FILE="$VENV/.movi_req_hash"
PREV_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
  PREV_HASH="$(cat "$REQ_HASH_FILE" 2>/dev/null || true)"
fi

if [ "$REQ_HASH" != "$PREV_HASH" ] || ! "$VENV/bin/python" -c "import fastapi" >/dev/null 2>&1; then
  echo "==> [web-api] phase=bootstrap action=install-python-deps-lockfiles"
  bash "$ROOT/runtime/bootstrap_env.sh"
  printf "%s" "$REQ_HASH" > "$REQ_HASH_FILE"
fi

echo "==> [web-api] phase=bootstrap host=${HOST} port=${PORT}"
echo "==> [web-api] phase=start command=${VENV}/bin/python -m apps.api.server --host ${HOST} --port ${PORT}"
exec "$VENV/bin/python" -m apps.api.server --host "$HOST" --port "$PORT"
