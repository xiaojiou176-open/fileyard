#!/usr/bin/env bash
set -euo pipefail

# Keep GitHub Actions secrets aligned with live/pre-push gate expectations.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
RUNTIME_ENV_FILE="$(governance_runtime_env_file_path "$REPO_ROOT")"

if ! command -v gh >/dev/null 2>&1; then
  echo "❌ gh CLI not found. Install GitHub CLI first." >&2
  exit 1
fi

if [ ! -f "$RUNTIME_ENV_FILE" ]; then
  echo "❌ runtime env file not found at $RUNTIME_ENV_FILE" >&2
  exit 1
fi

resolve_target_repo() {
  local explicit_repo="${1:-}"
  if [ -n "$explicit_repo" ]; then
    printf '%s' "$explicit_repo"
    return 0
  fi
  if gh repo view --json nameWithOwner -q .nameWithOwner >/dev/null 2>&1; then
    gh repo view --json nameWithOwner -q .nameWithOwner
    return 0
  fi
  echo "❌ unable to determine current GitHub repository; pass <owner/repo> explicitly" >&2
  exit 1
}

TARGET_REPO="$(resolve_target_repo "${1:-}")"

read_runtime_env() {
  local key="$1"
  python3 - "$RUNTIME_ENV_FILE" "$key" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k.strip() != key:
        continue
    value = v.strip().strip('"').strip("'")
    print(value)
    break
PY
}

set_required_secret() {
  local key="$1"
  local value
  value="${!key:-}"
  if [ -z "$value" ]; then
    value="$(read_runtime_env "$key")"
  fi
  if [ -z "$value" ]; then
    echo "❌ required secret $key is missing in workspace runtime env file or current shell env" >&2
    exit 1
  fi
  printf '%s' "$value" | gh secret set "$key" --repo "$TARGET_REPO" --body-file - >/dev/null
  echo "✅ secret synced: $key"
}

set_optional_secret() {
  local key="$1"
  local value
  value="${!key:-}"
  if [ -z "$value" ]; then
    value="$(read_runtime_env "$key")"
  fi
  if [ -z "$value" ]; then
    echo "ℹ️ optional secret skipped: $key"
    return 0
  fi
  printf '%s' "$value" | gh secret set "$key" --repo "$TARGET_REPO" --body-file - >/dev/null
  echo "✅ optional secret synced: $key"
}

set_required_secret "GEMINI_API_KEY"
set_required_secret "GEMINI_MODEL"
set_required_secret "MOVI_LIVE_TEST_URL"
set_optional_secret "MOVI_ROLLBACK_HMAC_KEY"

model_value="${GEMINI_UI_AUDIT_MODEL:-}"
if [ -z "$model_value" ]; then
  model_value="$(read_runtime_env GEMINI_UI_AUDIT_MODEL)"
fi
if [ -z "$model_value" ]; then
  model_value="gemini-3-flash-preview"
fi
gh variable set GEMINI_UI_AUDIT_MODEL --repo "$TARGET_REPO" --body "$model_value" >/dev/null
echo "✅ variable synced: GEMINI_UI_AUDIT_MODEL=${model_value}"
echo "✅ sync_github_actions_secrets complete for ${TARGET_REPO}"
