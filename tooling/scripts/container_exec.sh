#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
RESTORE_TREE_HELPER="$ROOT/scripts/restore_prebuilt_tree.py"
COMPOSE_FILE="${FILEORGANIZE_COMPOSE_FILE:-ops/compose/docker-compose.yml}"
COMPOSE_SERVICE="${FILEORGANIZE_COMPOSE_SERVICE:-fileorganize-ci}"
IMAGE_REF="${FILEORGANIZE_CI_IMAGE:-}"
LOCAL_FALLBACK_IMAGE="${CONTAINER_EXEC_LOCAL_IMAGE:-}"
LOCAL_FALLBACK_DOCKERFILE="${CONTAINER_EXEC_DOCKERFILE:-$REPO_ROOT/.devcontainer/Dockerfile}"
LABEL="container-exec"
SKIP_WEBUI_NODE_MODULES_MOUNT=0
COMPOSE_ARGS=()
COMPOSE_PROJECT_NAME_FALLBACK="${COMPOSE_PROJECT_NAME:-}"
COMPOSE_RUN_CONTAINER_NAME=""
COMPOSE_RUN_PID=""
DOCKER_READY_TIMEOUT_SECONDS="${CONTAINER_EXEC_DOCKER_TIMEOUT_SECONDS:-20}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
RUNTIME_ENV_FILE="$(governance_runtime_env_file_path "$REPO_ROOT")"

if [ -z "$LOCAL_FALLBACK_IMAGE" ]; then
  LOCAL_FALLBACK_IMAGE="$GOVERNANCE_DEFAULT_CI_IMAGE"
fi

while [ "$#" -gt 0 ]; do
  case "${1:-}" in
    --label)
      LABEL="${2:-container-exec}"
      shift 2
      ;;
    --skip-webui-node-modules-mount)
      SKIP_WEBUI_NODE_MODULES_MOUNT=1
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [ "$#" -eq 0 ]; then
  echo "Usage: bash tooling/scripts/container_exec.sh [--label <name>] -- <command...>" >&2
  exit 2
fi

is_inside_container() {
  if [ -f "/.dockerenv" ]; then
    return 0
  fi
  if [ -r "/proc/1/cgroup" ] && grep -Eq '(docker|containerd|kubepods|podman|lxc)' /proc/1/cgroup; then
    return 0
  fi
  return 1
}

if is_inside_container; then
  exec env FILEORGANIZE_IN_CONTAINER=1 FILEORGANIZE_ALLOW_HOST_EXECUTION=0 "$@"
fi

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" = "1" ]; then
  echo "❌ ${LABEL}: FILEORGANIZE_IN_CONTAINER=1 is set, but runtime is not inside a container" >&2
  echo "Do not set FILEORGANIZE_IN_CONTAINER manually on host; use container_exec.sh directly." >&2
  exit 1
fi

if [ -z "$IMAGE_REF" ] && [ ! -f "$REPO_ROOT/$COMPOSE_FILE" ]; then
  echo "❌ ${LABEL}: missing compose file: $REPO_ROOT/$COMPOSE_FILE" >&2
  exit 1
fi

if [ -f "$RUNTIME_ENV_FILE" ]; then
  COMPOSE_ARGS+=(--env-file "$RUNTIME_ENV_FILE")
fi
COMPOSE_ARGS+=(-f "$REPO_ROOT/$COMPOSE_FILE")

if [ -z "$COMPOSE_PROJECT_NAME_FALLBACK" ]; then
  COMPOSE_PROJECT_NAME_FALLBACK="$GOVERNANCE_COMPOSE_PROJECT_NAME_DEFAULT"
fi

is_ci_context() {
  [ "${CI:-}" = "1" ] || [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  "$@" &
  local cmd_pid=$!
  local elapsed=0

  while kill -0 "$cmd_pid" 2>/dev/null; do
    if [ "$elapsed" -ge "$timeout_seconds" ]; then
      kill "$cmd_pid" 2>/dev/null || true
      sleep 1
      kill -s KILL "$cmd_pid" 2>/dev/null || true
      wait "$cmd_pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  wait "$cmd_pid"
}

docker_daemon_ready() {
  docker_probe_output "$DOCKER_READY_TIMEOUT_SECONDS" "$@" info
}

DOCKER_LAST_PROBE_RC=0
DOCKER_LAST_PROBE_STDOUT=""
DOCKER_LAST_PROBE_STDERR=""
DOCKER_LAST_PROBE_OUTPUT=""

docker_probe_output() {
  local timeout_seconds="$1"
  shift
  local stdout_file=""
  local stderr_file=""
  stdout_file="$(mktemp)"
  stderr_file="$(mktemp)"
  set +e
  run_with_timeout "$timeout_seconds" "$@" >"$stdout_file" 2>"$stderr_file"
  DOCKER_LAST_PROBE_RC=$?
  set -e
  DOCKER_LAST_PROBE_STDOUT="$(cat "$stdout_file")"
  DOCKER_LAST_PROBE_STDERR="$(cat "$stderr_file")"
  if [ -n "$DOCKER_LAST_PROBE_STDOUT" ] && [ -n "$DOCKER_LAST_PROBE_STDERR" ]; then
    DOCKER_LAST_PROBE_OUTPUT="${DOCKER_LAST_PROBE_STDOUT}
${DOCKER_LAST_PROBE_STDERR}"
  elif [ -n "$DOCKER_LAST_PROBE_STDOUT" ]; then
    DOCKER_LAST_PROBE_OUTPUT="$DOCKER_LAST_PROBE_STDOUT"
  else
    DOCKER_LAST_PROBE_OUTPUT="$DOCKER_LAST_PROBE_STDERR"
  fi
  rm -f "$stdout_file" "$stderr_file"
  return "$DOCKER_LAST_PROBE_RC"
}

docker_context_name() {
  if [ -n "${DOCKER_CONTEXT:-}" ]; then
    printf '%s\n' "$DOCKER_CONTEXT"
    return 0
  fi
  docker context show 2>/dev/null || true
}

docker_context_endpoint() {
  local context_name="$1"
  if [ -z "$context_name" ]; then
    return 0
  fi
  docker context inspect "$context_name" 2>/dev/null | sed -n 's/.*"Host":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1 || true
}

docker_socket_hint() {
  local endpoint="$1"
  case "$endpoint" in
    unix://*)
      printf '%s\n' "${endpoint#unix://}"
      ;;
    *)
      return 0
      ;;
  esac
}

sanitize_container_name_component() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_.-' '-'
}

cleanup_compose_run_container() {
  if [ -z "${COMPOSE_RUN_CONTAINER_NAME:-}" ]; then
    return 0
  fi
  docker rm -f "$COMPOSE_RUN_CONTAINER_NAME" >/dev/null 2>&1 || true
}

cleanup_compose_run_process() {
  if [ -z "${COMPOSE_RUN_PID:-}" ]; then
    return 0
  fi
  if kill -0 "$COMPOSE_RUN_PID" 2>/dev/null; then
    kill "$COMPOSE_RUN_PID" 2>/dev/null || true
    sleep 1
    kill -s KILL "$COMPOSE_RUN_PID" 2>/dev/null || true
  fi
  wait "$COMPOSE_RUN_PID" 2>/dev/null || true
}

handle_compose_run_signal() {
  local exit_code="$1"
  cleanup_compose_run_process
  cleanup_compose_run_container
  trap - EXIT INT TERM
  exit "$exit_code"
}

docker_probe_first_line() {
  printf '%s\n' "$DOCKER_LAST_PROBE_OUTPUT" | awk 'NF {print; exit}'
}

emit_docker_daemon_diagnostic() {
  local probe_label="$1"
  local context_name=""
  local endpoint=""
  local socket_hint=""
  local first_line=""
  context_name="$(docker_context_name)"
  endpoint="$(docker_context_endpoint "$context_name")"
  if [ -z "$endpoint" ] && [ -n "${DOCKER_HOST:-}" ]; then
    endpoint="$DOCKER_HOST"
  fi
  if [ -z "$endpoint" ]; then
    endpoint="unix:///var/run/docker.sock"
  fi
  socket_hint="$(docker_socket_hint "$endpoint")"
  first_line="$(docker_probe_first_line)"

  if [ "$DOCKER_LAST_PROBE_RC" -eq 124 ]; then
    echo "❌ ${LABEL}: ${probe_label} timed out after ${DOCKER_READY_TIMEOUT_SECONDS}s" >&2
    [ -n "$context_name" ] && echo "Docker context: ${context_name}" >&2
    [ -n "${DOCKER_HOST:-}" ] && echo "DOCKER_HOST: ${DOCKER_HOST}" >&2
    [ -n "$endpoint" ] && echo "Docker endpoint: ${endpoint}" >&2
    echo "Next: Docker CLI hung before the daemon answered. Confirm Docker Desktop/daemon is fully started, then retry." >&2
    if [ -n "$socket_hint" ]; then
      echo "Docker socket path: ${socket_hint}" >&2
      if [ ! -e "$socket_hint" ]; then
        echo "Hint: socket path does not exist. Start Docker Desktop / docker daemon, or fix DOCKER_HOST/docker context." >&2
      elif [ ! -S "$socket_hint" ]; then
        echo "Hint: socket path exists but is not a unix socket. Fix DOCKER_HOST/docker context." >&2
      elif [ ! -r "$socket_hint" ] || [ ! -w "$socket_hint" ]; then
        echo "Hint: socket exists but current user lacks read/write access. Check Docker Desktop permissions or docker group membership." >&2
      fi
    fi
    return 0
  fi

  case "$DOCKER_LAST_PROBE_OUTPUT" in
    *"503 Service Unavailable"*|*"status code 503"*|*"_ping"*503*)
      echo "❌ ${LABEL}: docker daemon returned HTTP 503 during ${probe_label}" >&2
      ;;
    *"Current context"*not\ found*|*"context"*not\ found*|*"context"*does\ not\ exist*)
      echo "❌ ${LABEL}: docker context is invalid or missing during ${probe_label}" >&2
      ;;
    *"permission denied"*|*"Permission denied"*)
      echo "❌ ${LABEL}: docker socket access was denied during ${probe_label}" >&2
      ;;
    *"Cannot connect to the Docker daemon"*|*"Is the docker daemon running"*|*"No such file or directory"*|*"connection refused"*|*"dial unix"*|*"connect: no such file or directory"*)
      echo "❌ ${LABEL}: docker client could not reach the daemon during ${probe_label}" >&2
      ;;
    *)
      echo "❌ ${LABEL}: docker daemon check failed before container execution could start" >&2
      ;;
  esac

  if [ -n "$context_name" ]; then
    echo "Docker context: ${context_name}" >&2
  fi
  if [ -n "${DOCKER_HOST:-}" ]; then
    echo "DOCKER_HOST: ${DOCKER_HOST}" >&2
  fi
  if [ -n "$endpoint" ]; then
    echo "Docker endpoint: ${endpoint}" >&2
  fi
  if [ -n "$first_line" ]; then
    echo "Docker client said: ${first_line}" >&2
  fi
  case "$DOCKER_LAST_PROBE_OUTPUT" in
    *"503 Service Unavailable"*|*"status code 503"*|*"_ping"*503*)
      echo "Next: Docker Desktop is reachable but its engine API is not ready. Wait for Docker Desktop to finish starting or restart it, then retry." >&2
      ;;
    *"Current context"*not\ found*|*"context"*not\ found*|*"context"*does\ not\ exist*)
      echo "Next: run 'docker context ls', switch to a valid context with 'docker context use <name>', or unset DOCKER_CONTEXT." >&2
      ;;
    *"permission denied"*|*"Permission denied"*)
      echo "Next: check Docker Desktop permissions or docker group membership for the current user, then retry." >&2
      ;;
    *"Cannot connect to the Docker daemon"*|*"Is the docker daemon running"*|*"No such file or directory"*|*"connection refused"*|*"dial unix"*|*"connect: no such file or directory"*)
      echo "Next: start Docker Desktop/daemon, or fix the active DOCKER_HOST/docker context so it points at a live socket." >&2
      ;;
    *)
      echo "Next: run 'docker context ls' and 'docker info' manually to inspect the client/daemon mismatch, then retry." >&2
      ;;
  esac
  if [ -n "$socket_hint" ]; then
    echo "Docker socket path: ${socket_hint}" >&2
    if [ ! -e "$socket_hint" ]; then
      echo "Hint: socket path does not exist. Start Docker Desktop / docker daemon, or fix DOCKER_HOST/docker context." >&2
    elif [ ! -S "$socket_hint" ]; then
      echo "Hint: socket path exists but is not a unix socket. Fix DOCKER_HOST/docker context." >&2
    elif [ ! -r "$socket_hint" ] || [ ! -w "$socket_hint" ]; then
      echo "Hint: socket exists but current user lacks read/write access. Check Docker Desktop permissions or docker group membership." >&2
    fi
  fi
}

emit_local_image_build_failure_diagnostic() {
  local build_log="$1"
  local build_rc="$2"
  local first_line=""
  local build_output=""

  build_output="$(cat "$build_log")"
  first_line="$(printf '%s\n' "$build_output" | awk 'NF {print; exit}')"

  echo "❌ ${LABEL}: failed to build local fallback image ${LOCAL_FALLBACK_IMAGE} (exit ${build_rc})" >&2
  echo "Dockerfile: ${LOCAL_FALLBACK_DOCKERFILE}" >&2
  if [ -n "$first_line" ]; then
    echo "Docker build said: ${first_line}" >&2
  fi

  case "$build_output" in
    *"Temporary failure resolving"*|*"Could not resolve"*|*"could not resolve"*|*"no such host"*|*"lookup "*|*"deb.debian.org"*|*"failed to fetch"*|*"Could not connect to"*|*"Network is unreachable"*)
      echo "Likely cause: DNS/network failure while building the local CI image." >&2
      echo "This gate can only run offline if ${LOCAL_FALLBACK_IMAGE} already exists locally." >&2
      echo "Next: retry on a healthy network, or prebuild/pull ${LOCAL_FALLBACK_IMAGE} (or set FILEORGANIZE_CI_IMAGE to a reachable prebuilt image) before rerunning." >&2
      ;;
    *)
      echo "Next: inspect the docker build output below, fix the local image build blocker, then rerun." >&2
      ;;
  esac

  cat "$build_log" >&2
}

runtime_volume_name() {
  local kind="$1"
  local suffix=""
  local seed="${IMAGE_REF:-compose}:${COMPOSE_SERVICE}"
  if command -v shasum >/dev/null 2>&1; then
    suffix="$(printf '%s' "$seed" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    suffix="$(printf '%s' "$seed" | sha256sum | awk '{print substr($1, 1, 12)}')"
  else
    suffix="$(printf '%s' "$seed" | cksum | awk '{print $1}')"
  fi
  printf 'fileorganize-%s-%s' "$kind" "$suffix"
}

if is_ci_context && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
  echo "❌ ${LABEL}: FILEORGANIZE_ALLOW_HOST_EXECUTION=1 is forbidden in CI" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "❌ ${LABEL}: docker is required when FILEORGANIZE_ALLOW_HOST_EXECUTION!=1" >&2
  echo "Set FILEORGANIZE_ALLOW_HOST_EXECUTION=1 only for emergency host execution." >&2
  exit 1
fi

if [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
  echo "⚠️ ${LABEL}: emergency host execution enabled (FILEORGANIZE_ALLOW_HOST_EXECUTION=1)"
  exec "$@"
fi

RUNTIME_VENV_VOLUME="$(runtime_volume_name venv)"
RUNTIME_PLAYWRIGHT_VOLUME="$(runtime_volume_name playwright)"
RUNTIME_WEBUI_NODE_MODULES_VOLUME="$(runtime_volume_name node-modules)"
CONTAINER_VENV_DIR="/root/.cache/fileorganize/venv/default"
CONTAINER_XDG_CACHE_HOME="/root/.cache/fileorganize/xdg"
CONTAINER_PIP_CACHE_DIR="/root/.cache/fileorganize/pip"
CONTAINER_PLAYWRIGHT_CACHE_DIR="/root/.cache/fileorganize/playwright"

ci_passthrough_args=()
for passthrough_var in \
  CI \
  GITHUB_ACTIONS \
  GITHUB_EVENT_NAME \
  GITHUB_REF \
  GITHUB_REF_NAME \
  GITHUB_SHA \
  GITHUB_RUN_ID \
  GITHUB_RUN_ATTEMPT \
  GITHUB_WORKSPACE \
  RUNNER_TEMP \
  BASE_REF \
  BEFORE_SHA \
  CI_NEEDS_JSON \
  LINT_FRONTEND_SKIP_GEMINI_AUDIT \
  GEMINI_UI_AUDIT_MODEL \
  GEMINI_UI_AUDIT_TIMEOUT_MS
do
  ci_passthrough_args+=(-e "$passthrough_var")
done

container_entrypoint='
set -euo pipefail
cd /workspace
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /workspace >/dev/null 2>&1 || true
fi
venv_dir="${FILEORGANIZE_VENV_DIR:-'"$CONTAINER_VENV_DIR"'}"
prebuilt_venv_dir="${FILEORGANIZE_PREBUILT_VENV_DIR:-/opt/fileorganize-ci-venv}"
RESTORE_TREE_HELPER="${RESTORE_TREE_HELPER:-/workspace/tooling/scripts/restore_prebuilt_tree.py}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-'"$CONTAINER_XDG_CACHE_HOME"'}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-'"$CONTAINER_PIP_CACHE_DIR"'}"
# Inside the container, the persistent Playwright browser cache is backed by a
# dedicated volume mounted at /root/.cache/fileorganize/playwright. Keep the
# runtime env aligned with that mount so browser installs and browser launches
# resolve the same path.
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-'"$CONTAINER_PLAYWRIGHT_CACHE_DIR"'}"
export MYPY_CACHE_DIR="${MYPY_CACHE_DIR:-/workspace/'"$GOVERNANCE_RUNTIME_CACHE_ROOT"'/build/tooling/mypy}"
mkdir -p "$venv_dir" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$PLAYWRIGHT_BROWSERS_PATH" "$MYPY_CACHE_DIR"
bootstrap_setuptools_from_dev_lock() {
  local py_bin="$1"
  local bootstrap_req=""
  if "$py_bin" -c "import setuptools" >/dev/null 2>&1; then
    return 0
  fi
  bootstrap_req="$(mktemp)"
  awk "
    BEGIN {emit=0}
    /^setuptools==/ {emit=1}
    emit {print}
    emit && /^    # via/ {exit}
  " tooling/requirements-dev.lock.txt > "$bootstrap_req"
  if [ ! -s "$bootstrap_req" ]; then
    echo "❌ [bootstrap] tooling/requirements-dev.lock.txt is missing a setuptools pin" >&2
    rm -f "$bootstrap_req"
    exit 1
  fi
  "$py_bin" -m pip install --require-hashes -r "$bootstrap_req"
  rm -f "$bootstrap_req"
}

recreate_runtime_venv() {
  local target="$1"
  mkdir -p "$target"
  find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  python -m venv "$target"
}
req_hash="$(cat tooling/requirements.lock.txt tooling/requirements-dev.lock.txt | sha256sum | awk "{print \$1}")"
hash_file="$venv_dir/.fileorganize_req_hash"
prev_hash=""
if [ -f "$hash_file" ]; then
  prev_hash="$(cat "$hash_file" 2>/dev/null || true)"
fi
python_ready=0
if [ -x "$venv_dir/bin/python" ] && "$venv_dir/bin/python" -V >/dev/null 2>&1; then
  python_ready=1
fi
needs_bootstrap=0
if [ "$req_hash" != "$prev_hash" ] || [ "$python_ready" != "1" ]; then
  needs_bootstrap=1
elif ! "$venv_dir/bin/python" -c "import pytest" >/dev/null 2>&1; then
  needs_bootstrap=1
fi
if [ "$needs_bootstrap" = "1" ]; then
  prebuilt_hash=""
  if [ -x "$prebuilt_venv_dir/bin/python" ] && [ -f "$prebuilt_venv_dir/.fileorganize_req_hash" ]; then
    prebuilt_hash="$(cat "$prebuilt_venv_dir/.fileorganize_req_hash" 2>/dev/null || true)"
  fi
  if [ "$prebuilt_hash" = "$req_hash" ]; then
    echo "==> [bootstrap] restoring prebuilt python dependencies from $prebuilt_venv_dir"
    python3 "$RESTORE_TREE_HELPER" --src "$prebuilt_venv_dir" --dst "$venv_dir"
    printf "%s" "$req_hash" > "$hash_file"
  else
    # Recreate the runtime venv for any non-prebuilt bootstrap path so stale
    # pip/setuptools state or half-cleared site-packages trees cannot survive
    # into a reinstall attempt.
    recreate_runtime_venv "$venv_dir"
    echo "==> [bootstrap] installing python dependencies from hash-locked files"
    "$venv_dir/bin/python" -m pip install --disable-pip-version-check --require-hashes -r tooling/requirements-pip.lock.txt
    "$venv_dir/bin/python" -m pip install --require-hashes -r tooling/requirements.lock.txt
    bootstrap_setuptools_from_dev_lock "$venv_dir/bin/python"
    "$venv_dir/bin/python" -m pip install --require-hashes -r tooling/requirements-dev.lock.txt
    printf "%s" "$req_hash" > "$hash_file"
  fi
fi
"$@"
'

if [ -n "$IMAGE_REF" ]; then
  DOCKER_BIN=(docker)
  if ! docker_daemon_ready "${DOCKER_BIN[@]}" && command -v sudo >/dev/null 2>&1; then
    DOCKER_BIN=(sudo docker)
  fi
  if ! docker_daemon_ready "${DOCKER_BIN[@]}"; then
    emit_docker_daemon_diagnostic "docker daemon readiness check"
    exit 1
  fi
  runtime_volume_args=(
    -v "$RUNTIME_VENV_VOLUME:$CONTAINER_VENV_DIR"
    -v "$RUNTIME_PLAYWRIGHT_VOLUME:$CONTAINER_PLAYWRIGHT_CACHE_DIR"
  )
  if [ "$SKIP_WEBUI_NODE_MODULES_MOUNT" != "1" ]; then
    runtime_volume_args+=(-v "$RUNTIME_WEBUI_NODE_MODULES_VOLUME:/workspace/apps/webui/node_modules")
  fi
  echo "==> [${LABEL}] running in container image=${IMAGE_REF}"
  exec "${DOCKER_BIN[@]}" run --rm \
    -v "$REPO_ROOT:/workspace" \
    "${runtime_volume_args[@]}" \
    -w /workspace \
    "${ci_passthrough_args[@]}" \
    -e FILEORGANIZE_IN_CONTAINER=1 \
    -e FILEORGANIZE_ALLOW_HOST_EXECUTION=0 \
    -e FILEORGANIZE_VENV_DIR="$CONTAINER_VENV_DIR" \
    -e GEMINI_API_KEY \
    -e GEMINI_MODEL \
    -e FILEORGANIZE_LIVE_TEST_URL \
    -e FILEORGANIZE_ROLLBACK_HMAC_KEY \
    -e FILEORGANIZE_TRACE_ID \
    -e FILEORGANIZE_SESSION_ID \
    -e FILEORGANIZE_REQUEST_ID \
    -e FILEORGANIZE_USER_ID \
    -e FILEORGANIZE_RUN_LIVE_TESTS \
    -e FILEORGANIZE_ALLOW_EXTERNAL \
    -e LIVE_HEARTBEAT_INTERVAL_SECONDS \
    -e LIVE_MAX_DURATION_SECONDS \
    -e LIVE_MAX_RETRIES \
    "$IMAGE_REF" bash -lc "$container_entrypoint" _ "$@"
fi

ensure_local_compose_image() {
  local inspect_rc=0
  local build_log=""
  local build_rc=0
  if run_with_timeout "$DOCKER_READY_TIMEOUT_SECONDS" docker image inspect "$LOCAL_FALLBACK_IMAGE" >/dev/null 2>&1; then
    return 0
  fi
  inspect_rc=$?
  if [ "$inspect_rc" -eq 124 ]; then
    echo "❌ ${LABEL}: docker daemon timed out while inspecting image ${LOCAL_FALLBACK_IMAGE}" >&2
    exit 1
  fi
  if [ ! -f "$LOCAL_FALLBACK_DOCKERFILE" ]; then
    echo "❌ ${LABEL}: missing local fallback Dockerfile: $LOCAL_FALLBACK_DOCKERFILE" >&2
    exit 1
  fi
  echo "==> [${LABEL}] building local fallback image=${LOCAL_FALLBACK_IMAGE}"
  build_log="$(mktemp)"
  set +e
  docker build \
    --file "$LOCAL_FALLBACK_DOCKERFILE" \
    --build-arg "NODE_RUNTIME_IMAGE=$GOVERNANCE_NODE_RUNTIME_IMAGE" \
    --tag "$LOCAL_FALLBACK_IMAGE" \
    "$REPO_ROOT" >"$build_log" 2>&1
  build_rc=$?
  set -e
  if [ "$build_rc" -ne 0 ]; then
    if grep -q 'already exists' "$build_log" && run_with_timeout "$DOCKER_READY_TIMEOUT_SECONDS" docker image inspect "$LOCAL_FALLBACK_IMAGE" >/dev/null 2>&1; then
      rm -f "$build_log"
      return 0
    fi
    emit_local_image_build_failure_diagnostic "$build_log" "$build_rc"
    rm -f "$build_log"
    exit "$build_rc"
  fi
  rm -f "$build_log"
}

if ! docker compose version >/dev/null 2>&1; then
  echo "❌ ${LABEL}: docker compose plugin is required" >&2
  exit 1
fi

if ! docker_daemon_ready docker; then
  emit_docker_daemon_diagnostic "docker daemon readiness check"
  exit 1
fi

ensure_local_compose_image

# Keep pre-commit/pre-push gates aligned across host and container execution paths.
echo "==> [${LABEL}] running in container service=${COMPOSE_SERVICE}"
COMPOSE_RUN_CONTAINER_NAME="$(sanitize_container_name_component "${COMPOSE_PROJECT_NAME_FALLBACK}-${LABEL}-$$")"
trap 'handle_compose_run_signal 130' INT
trap 'handle_compose_run_signal 143' TERM
trap 'cleanup_compose_run_process; cleanup_compose_run_container' EXIT
set +e
env COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_FALLBACK" docker compose "${COMPOSE_ARGS[@]}" run --name "$COMPOSE_RUN_CONTAINER_NAME" --rm -T \
  "${ci_passthrough_args[@]}" \
  -e FILEORGANIZE_IN_CONTAINER=1 \
  -e FILEORGANIZE_ALLOW_HOST_EXECUTION=0 \
  -e FILEORGANIZE_VENV_DIR \
  -e GEMINI_API_KEY \
  -e GEMINI_MODEL \
  -e FILEORGANIZE_LIVE_TEST_URL \
  -e FILEORGANIZE_ROLLBACK_HMAC_KEY \
  -e FILEORGANIZE_TRACE_ID \
  -e FILEORGANIZE_SESSION_ID \
  -e FILEORGANIZE_REQUEST_ID \
  -e FILEORGANIZE_USER_ID \
  -e FILEORGANIZE_RUN_LIVE_TESTS \
  -e FILEORGANIZE_ALLOW_EXTERNAL \
  -e LIVE_HEARTBEAT_INTERVAL_SECONDS \
  -e LIVE_MAX_DURATION_SECONDS \
  -e LIVE_MAX_RETRIES \
  "$COMPOSE_SERVICE" bash -lc "$container_entrypoint" _ "$@" &
COMPOSE_RUN_PID=$!
wait "$COMPOSE_RUN_PID"
compose_rc=$?
set -e
COMPOSE_RUN_PID=""
cleanup_compose_run_container
trap - EXIT INT TERM
exit "$compose_rc"
