#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
SCRIPT_REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
MODE="repo"
TARGET_ROOT="${PUBLIC_READINESS_REPO_ROOT:-}"
POLICY_PATH="${PUBLIC_READINESS_POLICY:-}"
POLICY_ARG=""

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$SCRIPT_REPO_ROOT"
apply_runtime_env_defaults "$SCRIPT_REPO_ROOT"
GATE_VENV="$(governance_runtime_venv_path "$SCRIPT_REPO_ROOT")"
PYTHON_BIN="${PUBLIC_READINESS_PYTHON:-$GATE_VENV/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

usage() {
  cat <<'EOF' >&2
Usage: bash tooling/gates/public_readiness_gate.sh [repo|release] [--root <repo-root>] [--policy <policy-path>]
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    repo|release)
      MODE="$1"
      shift
      ;;
    --root)
      TARGET_ROOT="${2:-}"
      shift 2
      ;;
    --policy)
      POLICY_ARG="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "❌ public_readiness_gate: unsupported argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ -z "$TARGET_ROOT" ]; then
  if [ -f "$PWD/contracts/governance/public_readiness_policy.yaml" ] && [ -f "$PWD/package.json" ]; then
    TARGET_ROOT="$PWD"
  else
    TARGET_ROOT="$SCRIPT_REPO_ROOT"
  fi
fi
TARGET_ROOT="$(cd "$TARGET_ROOT" && pwd)"

if [ -z "$POLICY_PATH" ]; then
  if [ -n "$POLICY_ARG" ]; then
    POLICY_PATH="$POLICY_ARG"
  else
    POLICY_PATH="$TARGET_ROOT/contracts/governance/public_readiness_policy.yaml"
  fi
fi

case "$POLICY_PATH" in
  /*) ;;
  *) POLICY_PATH="$TARGET_ROOT/$POLICY_PATH" ;;
esac
POLICY_PATH="$(cd "$(dirname "$POLICY_PATH")" && pwd)/$(basename "$POLICY_PATH")"
ARTIFACT_DIR="$TARGET_ROOT/.runtime-cache/logs/public-readiness"

mkdir -p "$ARTIFACT_DIR"

"$PYTHON_BIN" - "$TARGET_ROOT" "$POLICY_PATH" "$MODE" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

repo_root = Path(sys.argv[1]).resolve()
policy_path = Path(sys.argv[2]).resolve()
mode = sys.argv[3]
policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
if not isinstance(policy, dict):
    raise SystemExit("invalid public readiness policy")

issues: list[str] = []
required_files = [str(item) for item in policy.get("required_repo_surface_files", [])]
for rel in required_files:
    if not (repo_root / rel).exists():
        issues.append(f"missing required public surface file: {rel}")

package_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
for script_name in [str(item) for item in policy.get("required_package_scripts", [])]:
    if not isinstance(scripts, dict) or script_name not in scripts:
        issues.append(f"missing required package.json script: {script_name}")

runbook = (repo_root / "docs" / "open_source_runbook.md").read_text(encoding="utf-8")
for snippet in [str(item) for item in policy.get("required_runbook_snippets", [])]:
    if snippet not in runbook:
        issues.append(f"docs/open_source_runbook.md missing public readiness snippet: {snippet}")

release_mode = policy.get("release_mode", {})
if mode == "release" and isinstance(release_mode, dict) and bool(release_mode.get("require_tracked_files", False)):
    for rel in required_files:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            issues.append(f"release mode requires tracked public surface file: {rel}")

if issues:
    print("❌ public-readiness-repo-surface: failed")
    for issue in issues:
        print(f"- {issue}")
    raise SystemExit(1)

print("✅ public-readiness-repo-surface: passed")
PY

"$PYTHON_BIN" "$ROOT/scripts/check_public_asset_provenance.py" \
  --root "$TARGET_ROOT" \
  --policy "$POLICY_PATH"

"$PYTHON_BIN" "$ROOT/scripts/check_collaboration_surface.py" \
  --root "$TARGET_ROOT"

"$PYTHON_BIN" "$ROOT/scripts/check_local_only_tracking.py" \
  --root "$TARGET_ROOT"

POLICY_FOR_CHECK="$POLICY_PATH"
case "$POLICY_FOR_CHECK" in
  "$TARGET_ROOT"/*) POLICY_FOR_CHECK="${POLICY_FOR_CHECK#$TARGET_ROOT/}" ;;
esac

"$PYTHON_BIN" "$ROOT/scripts/check_public_platform_state.py" \
  --root "$TARGET_ROOT" \
  --policy "$POLICY_FOR_CHECK" \
  --mode "$MODE" \
  --json-out ".runtime-cache/logs/public-readiness/platform-state.json"

echo "✅ public_readiness_gate: root=$TARGET_ROOT mode=$MODE passed"
