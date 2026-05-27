#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
RESTORE_TREE_HELPER="$ROOT/scripts/restore_prebuilt_tree.py"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"

load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

VENV_PATH="$(governance_runtime_venv_path "$REPO_ROOT")"
PYTHON_BIN="$VENV_PATH/bin/python"
REQ_HASH_FILE="$VENV_PATH/.fileorganize_req_hash"

bootstrap_setuptools_from_dev_lock() {
  local py_bin="$1"
  local bootstrap_req=""

  if "$py_bin" -c "import setuptools" >/dev/null 2>&1; then
    return 0
  fi

  bootstrap_req="$(mktemp)"
  awk '
    BEGIN {emit=0}
    /^setuptools==/ {emit=1}
    emit {print}
    emit && /^    # via/ {exit}
  ' "$REPO_ROOT/tooling/requirements-dev.lock.txt" > "$bootstrap_req"

  if [ ! -s "$bootstrap_req" ]; then
    echo "❌ bootstrap_env: tooling/requirements-dev.lock.txt is missing a setuptools pin" >&2
    rm -f "$bootstrap_req"
    exit 1
  fi

  "$py_bin" -m pip install --require-hashes -r "$bootstrap_req"
  rm -f "$bootstrap_req"
}

restore_prebuilt_venv_if_available() {
  local req_hash="$1"
  local prebuilt_dir="${FILEORGANIZE_PREBUILT_VENV_DIR:-}"
  local prebuilt_hash=""

  if [ -z "$prebuilt_dir" ] || [ ! -x "$prebuilt_dir/bin/python" ] || [ ! -f "$prebuilt_dir/.fileorganize_req_hash" ]; then
    return 1
  fi

  prebuilt_hash="$(cat "$prebuilt_dir/.fileorganize_req_hash" 2>/dev/null || true)"
  if [ "$prebuilt_hash" != "$req_hash" ]; then
    return 1
  fi

  echo "==> [bootstrap_env] restoring prebuilt python dependencies from $prebuilt_dir"
  python3 "$RESTORE_TREE_HELPER" --src "$prebuilt_dir" --dst "$VENV_PATH"
  printf '%s' "$req_hash" > "$REQ_HASH_FILE"
  return 0
}

recreate_runtime_venv() {
  local target="$1"
  mkdir -p "$target"
  find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  python3 -m venv "$target"
}

req_hash="$(
  cat "$REPO_ROOT/tooling/requirements.lock.txt" "$REPO_ROOT/tooling/requirements-dev.lock.txt" \
    | shasum -a 256 | awk '{print $1}'
)"
prev_hash=""
if [ -f "$REQ_HASH_FILE" ]; then
  prev_hash="$(cat "$REQ_HASH_FILE" 2>/dev/null || true)"
fi

python_ready=0
if [ -x "$PYTHON_BIN" ] && "$PYTHON_BIN" -V >/dev/null 2>&1; then
  python_ready=1
fi

needs_bootstrap=0
if [ "$req_hash" != "$prev_hash" ] || [ "$python_ready" != "1" ]; then
  needs_bootstrap=1
elif ! "$PYTHON_BIN" -c "import pytest" >/dev/null 2>&1; then
  needs_bootstrap=1
fi

if [ "$needs_bootstrap" = "1" ]; then
  if ! restore_prebuilt_venv_if_available "$req_hash"; then
    # Recreate the runtime venv for any non-prebuilt bootstrap path so stale
    # pip/setuptools state or half-cleared site-packages trees cannot survive
    # into a reinstall attempt.
    recreate_runtime_venv "$VENV_PATH"
    echo "==> [bootstrap_env] installing hash-locked python dependencies"
    "$PYTHON_BIN" -m pip install --disable-pip-version-check --require-hashes -r "$REPO_ROOT/tooling/requirements-pip.lock.txt"
    "$PYTHON_BIN" -m pip install --require-hashes -r "$REPO_ROOT/tooling/requirements.lock.txt"
    bootstrap_setuptools_from_dev_lock "$PYTHON_BIN"
    "$PYTHON_BIN" -m pip install --require-hashes -r "$REPO_ROOT/tooling/requirements-dev.lock.txt"
    printf '%s' "$req_hash" > "$REQ_HASH_FILE"
  fi
fi

echo "✅ bootstrap_env: python=$PYTHON_BIN"
