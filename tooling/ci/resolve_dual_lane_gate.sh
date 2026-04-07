#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: bash tooling/ci/resolve_dual_lane_gate.sh <gate-name> <primary-result> <fallback-result>" >&2
  exit 2
fi

gate_name="$1"
primary_result="$2"
fallback_result="$3"

if [ "$primary_result" = "success" ]; then
  echo "✅ ${gate_name} passed on hosted primary lane."
  exit 0
fi

if [ "$fallback_result" = "success" ]; then
  echo "✅ ${gate_name} retry passed on hosted retry lane."
  exit 0
fi

echo "❌ ${gate_name} failed. No valid fallback success path."
exit 1
