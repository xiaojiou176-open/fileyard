#!/usr/bin/env bash
set -euo pipefail

STAGE="post-checkout"
NORMALIZE_OWNERSHIP=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --stage)
      STAGE="${2:-}"
      shift 2
      ;;
    --normalize-ownership)
      NORMALIZE_OWNERSHIP=1
      shift
      ;;
    *)
      echo "Usage: $0 [--stage pre-checkout|post-checkout] [--normalize-ownership]" >&2
      exit 2
      ;;
  esac
done

WORKSPACE="${GITHUB_WORKSPACE:-}"
RUNNER_TEMP_DIR="${RUNNER_TEMP:-}"

if [ -z "$WORKSPACE" ]; then
  echo "❌ [gha-self-hosted-hygiene] GITHUB_WORKSPACE is required" >&2
  exit 1
fi

if [ ! -d "$WORKSPACE" ]; then
  echo "❌ [gha-self-hosted-hygiene] workspace not found: $WORKSPACE" >&2
  exit 1
fi

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

log() {
  printf '[gha-self-hosted-hygiene] ts=%s stage=%s %s\n' "$(timestamp)" "$STAGE" "$*"
}

warn() {
  printf '[gha-self-hosted-hygiene] ts=%s stage=%s WARN %s\n' "$(timestamp)" "$STAGE" "$*" >&2
}

log "start workspace=$WORKSPACE runner_temp=${RUNNER_TEMP_DIR:-unset}"

case "$STAGE" in
  pre-checkout|post-checkout) ;;
  *)
    echo "❌ [gha-self-hosted-hygiene] unsupported stage: $STAGE" >&2
    exit 2
    ;;
esac

if [ "$NORMALIZE_OWNERSHIP" = "1" ]; then
  if command -v sudo >/dev/null 2>&1; then
    log "normalizing workspace ownership with sudo"
    sudo chown -R "$(id -u):$(id -g)" "$WORKSPACE" || warn "sudo chown failed; continuing"
  else
    warn "sudo not available; skip ownership normalization"
  fi
  log "ensuring workspace is user-writable"
  chmod -R u+rwX "$WORKSPACE" || warn "chmod failed; continuing"
else
  log "ownership normalization disabled"
fi

if [ "$STAGE" = "pre-checkout" ]; then
  stale_paths=(
    ".git"
    ".pytest_cache"
    ".mypy_cache"
    ".ruff_cache"
    ".runtime-cache"
    "artifacts"
  )
  for rel in "${stale_paths[@]}"; do
    target="$WORKSPACE/$rel"
    if [ -e "$target" ]; then
      log "clearing stale path before checkout: $target"
      rm -rf "$target"
    fi
  done
fi

if [ -n "$RUNNER_TEMP_DIR" ]; then
  mkdir -p "$RUNNER_TEMP_DIR/movi-hygiene"
  log "runner temp ready at $RUNNER_TEMP_DIR/movi-hygiene"
else
  warn "RUNNER_TEMP is unset; skip temp preparation"
fi

log "done"
