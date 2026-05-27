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

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label history-secret-scan -- bash tooling/gates/history_secret_scan.sh "$@"
fi

OUTPUT_DIR="${REPO_ROOT}/.runtime-cache/logs/security"
OUTPUT_JSON="${OUTPUT_DIR}/gitleaks-history.json"
OUTPUT_LOG="${OUTPUT_DIR}/gitleaks-history.log"
mkdir -p "$OUTPUT_DIR"
rm -f "$REPO_ROOT/.runtime-cache/gitleaks-history.json"

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "❌ history_secret_scan: gitleaks binary not found in execution environment" >&2
  exit 1
fi

echo "==> history_secret_scan: writing history report to ${OUTPUT_JSON}"
set +e
gitleaks git "$REPO_ROOT" \
  --config "$REPO_ROOT/tooling/config/gitleaks.toml" \
  --no-banner \
  --redact \
  --report-format json \
  --report-path "$OUTPUT_JSON" >"$OUTPUT_LOG" 2>&1
STATUS=$?
set -e

if [ "$STATUS" -gt 1 ]; then
  echo "❌ history_secret_scan: gitleaks execution failed (exit ${STATUS})" >&2
  cat "$OUTPUT_LOG" >&2
  exit "$STATUS"
fi

if [ "$STATUS" -eq 1 ]; then
  echo "❌ history_secret_scan: findings detected (see ${OUTPUT_JSON})" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

echo "✅ history_secret_scan: no history secrets detected"
echo "   report=${OUTPUT_JSON}"
