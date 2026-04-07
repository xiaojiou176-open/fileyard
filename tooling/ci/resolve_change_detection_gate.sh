#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "Usage: bash tooling/ci/resolve_change_detection_gate.sh <primary-result> <primary-run-heavy> <primary-count> <fallback-result> <fallback-run-heavy> <fallback-count>" >&2
  exit 2
fi

if [ -z "${GITHUB_OUTPUT:-}" ]; then
  echo "GITHUB_OUTPUT is required" >&2
  exit 2
fi

primary_result="$1"
primary_heavy="$2"
primary_count="$3"
fallback_result="$4"
fallback_heavy="$5"
fallback_count="$6"

if [ "$primary_result" = "success" ]; then
  echo "run-heavy=${primary_heavy}" >> "$GITHUB_OUTPUT"
  echo "changed-count=${primary_count}" >> "$GITHUB_OUTPUT"
  echo "✅ change-detection passed on hosted primary lane."
  exit 0
fi

if [ "$fallback_result" = "success" ]; then
  echo "run-heavy=${fallback_heavy}" >> "$GITHUB_OUTPUT"
  echo "changed-count=${fallback_count}" >> "$GITHUB_OUTPUT"
  echo "✅ change-detection retry passed on hosted retry lane."
  exit 0
fi

echo "❌ change-detection failed. No valid fallback success path."
exit 1
