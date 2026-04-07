#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 1 ]; then
  echo "Usage: bash tooling/ci/detect_change_scope.sh [changed-file-output]" >&2
  exit 2
fi

if [ -z "${GITHUB_OUTPUT:-}" ]; then
  echo "GITHUB_OUTPUT is required" >&2
  exit 2
fi

CHANGED_FILE="${1:-.github/.ci_changed_files.txt}"
EVENT_NAME="${CI_EVENT_NAME:-${GITHUB_EVENT_NAME:-}}"
BASE_REF_INPUT="${CI_BASE_REF:-${GITHUB_BASE_REF:-}}"
BEFORE_SHA="${CI_BEFORE_SHA:-}"
DEFAULT_BRANCH="${CI_DEFAULT_BRANCH:-}"

: > "$CHANGED_FILE"

if [ "$EVENT_NAME" = "schedule" ] || [ "$EVENT_NAME" = "workflow_dispatch" ]; then
  echo "schedule event: force heavy pipeline"
  echo "run-heavy=true" >> "$GITHUB_OUTPUT"
  echo "changed-count=scheduled" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ "$EVENT_NAME" = "pull_request" ]; then
  BASE_REF="origin/${BASE_REF_INPUT}"
  git fetch --no-tags --prune --depth=1 origin "${BASE_REF_INPUT}"
  if ! git diff --name-only --diff-filter=ACDMRT "$BASE_REF"...HEAD > "$CHANGED_FILE"; then
    echo "⚠️ no merge-base for $BASE_REF...HEAD; fallback to HEAD diff-tree"
    git diff-tree --no-commit-id --name-only -r HEAD > "$CHANGED_FILE"
  fi
elif [ "$EVENT_NAME" = "push" ]; then
  if [ -z "$BEFORE_SHA" ] || [ "$BEFORE_SHA" = "0000000000000000000000000000000000000000" ]; then
    git fetch --no-tags --prune --depth=200 origin "$DEFAULT_BRANCH"
    BASE_REF="$(git merge-base HEAD "origin/$DEFAULT_BRANCH" 2>/dev/null || true)"
    if [ -z "$BASE_REF" ]; then
      BASE_REF="$(git rev-parse HEAD^ 2>/dev/null || git rev-parse HEAD)"
    fi
    git diff --name-only --diff-filter=ACDMRT "$BASE_REF" HEAD > "$CHANGED_FILE"
  else
    git diff --name-only --diff-filter=ACDMRT "$BEFORE_SHA" HEAD > "$CHANGED_FILE"
  fi
else
  git diff-tree --no-commit-id --name-only -r HEAD > "$CHANGED_FILE"
fi

count="$(grep -c . "$CHANGED_FILE" || true)"
echo "changed-count=$count" >> "$GITHUB_OUTPUT"

if [ "$count" = "0" ]; then
  echo "run-heavy=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

python3 tooling/scripts/check_change_detection_scope.py --changed-file-list "$CHANGED_FILE" >> "$GITHUB_OUTPUT"
