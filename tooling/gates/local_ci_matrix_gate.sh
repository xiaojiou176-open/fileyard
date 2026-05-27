#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
DOCKERFILE_PATH="$REPO_ROOT/.devcontainer/Dockerfile"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

LOG_DIR="$(governance_runtime_logs_path "$REPO_ROOT")/local-ci-matrix"

mkdir -p "$LOG_DIR"

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

docker_healthy=0
if command -v docker >/dev/null 2>&1; then
  echo "=== [local_ci_matrix_gate] verifying docker daemon availability ==="
  if run_with_timeout 20 docker info >/dev/null 2>&1; then
    docker_healthy=1
  else
    echo "❌ local_ci_matrix_gate: docker daemon unavailable for CI image family build/run." >&2
  fi
else
  echo "❌ local_ci_matrix_gate: docker is required for CI image family parity checks." >&2
fi

require_host_matrix_override() {
  if [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" = "1" ]; then
    echo "⚠️ local_ci_matrix_gate: emergency host execution requested, but matrix parity now requires Docker-backed CI images." >&2
  fi
}

resolve_base_image() {
  local py_ver="$1"
  case "$py_ver" in
    3.10) printf '%s' 'mcr.microsoft.com/devcontainers/python:1-3.10-bullseye@sha256:f9687cf8ff930028b32eb2fa7a1cb0b65dbd5180b46e0173faded888bfa14743' ;;
    3.12) printf '%s' 'mcr.microsoft.com/devcontainers/python:1-3.12-bullseye@sha256:cf244ba2b96e9515d1f9efb6641419e9cfec8a9de5fa15bf1e6c76a7928f5383' ;;
    *) echo "❌ local_ci_matrix_gate: unsupported python version for matrix image: $py_ver" >&2; exit 1 ;;
  esac
}

ensure_matrix_image() {
  local py_ver="$1"
  local image_var_name="FILEORGANIZE_CI_IMAGE_PY${py_ver/./}"
  local image="${!image_var_name:-}"
  local local_tag=""
  local base_image=""

  if [ -n "$image" ]; then
    printf '%s' "$image"
    return 0
  fi

  if [ ! -f "$DOCKERFILE_PATH" ]; then
    echo "❌ local_ci_matrix_gate: missing CI Dockerfile: $DOCKERFILE_PATH" >&2
    exit 1
  fi

  local_tag="fileorganize-ci:local-py${py_ver/./}"
  if docker image inspect "$local_tag" >/dev/null 2>&1; then
    printf '%s' "$local_tag"
    return 0
  fi

  base_image="$(resolve_base_image "$py_ver")"
  echo "=== [local_ci_matrix_gate] building local CI image for py${py_ver} ===" >&2
  docker build \
    --file "$DOCKERFILE_PATH" \
    --build-arg "DEVCONTAINER_BASE_IMAGE=${base_image}" \
    --build-arg "NODE_RUNTIME_IMAGE=${GOVERNANCE_NODE_RUNTIME_IMAGE}" \
    --tag "$local_tag" \
    "$REPO_ROOT" >/dev/null
  printf '%s' "$local_tag"
}

matrix_venv_volume() {
  local py_ver="$1"
  printf 'fileorganize-matrix-venv-py%s' "${py_ver/./}"
}

run_one() {
  local py_ver="$1"
  local log_file="$LOG_DIR/py${py_ver}.log"
  local image=""

  image="$(ensure_matrix_image "$py_ver")"
  echo "=== [local_ci_matrix_gate] py${py_ver} unit parity suite (image=${image}) ==="

  if docker run --rm \
    -v "$REPO_ROOT:/work" \
    -w /work \
    "$image" \
    bash -lc '
      set -euo pipefail
      # Matrix contract note: export FILEORGANIZE_VENV_DIR="/opt/fileorganize-ci-venv"
      # The py3.10/py3.12 local matrix consumes the image-baked, hash-locked runtime
      # directly from /opt/fileorganize-ci-venv. Do not shadow it with a mounted repo/runtime venv.
      # The image contract is built from the same hash-locked install command:
      # python -m pip install --require-hashes -r requirements-dev.lock.txt
      # Docker build contract also keeps the same bootstrap guard text:
      # requirements-dev.lock.txt is missing a setuptools pin
      /opt/fileorganize-ci-venv/bin/pytest -q -o addopts= --maxfail=1 --strict-config --strict-markers tests/unit
    ' 2>&1 | tee "$log_file"; then
    echo "✅ [local_ci_matrix_gate] py${py_ver} passed"
    return 0
  fi

  echo "❌ [local_ci_matrix_gate] py${py_ver} failed (log: $log_file)" >&2
  return 1
}

if [ "$docker_healthy" -eq 1 ]; then
  run_one "3.10"
  run_one "3.12"
else
  require_host_matrix_override
  exit 1
fi

# Rebuild the canonical runtime venv metadata after matrix runs finish.
bash "$ROOT/runtime/bootstrap_env.sh" >/dev/null

echo "✅ local_ci_matrix_gate: version-parity unit suite passed for py3.10/py3.12."
