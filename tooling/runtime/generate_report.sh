#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(cd "$(dirname "$ROOT")" && pwd -P)"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
MANIFEST="${1:-}"
OUT="${2:-}"
HOST_PYTHON="$(command -v python3 || command -v python || true)"
ORIGINAL_ARGS=("$@")

if [ ! -f "$CONFIG_LIB" ]; then
  echo "missing config helper: $CONFIG_LIB" >&2
  exit 1
fi
source "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"
IFS='|' read -r ALLOW_EXTERNAL ALLOW_EXTERNAL_SOURCE \
  <<< "$(resolve_allow_external_with_source "0")"
export FILEMAN_ALLOW_EXTERNAL="$ALLOW_EXTERNAL"

if [ -z "$MANIFEST" ]; then
  MANIFEST="$(governance_manifest_root_path "$REPO_ROOT")/manifest.jsonl"
fi
if [ -z "$OUT" ]; then
  OUT="$(governance_artifact_root_path "$REPO_ROOT")/report/report_summary.json"
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --manifest)
      MANIFEST="$2"
      shift 2
      ;;
    --out)
      OUT="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--manifest PATH] [--out PATH]" >&2
      exit 2
      ;;
  esac
done

normalize_host_path() {
  local target="$1"
  if [ -z "$HOST_PYTHON" ]; then
    echo "$target"
    return 0
  fi
  "$HOST_PYTHON" - "$target" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(strict=False))
PY
}

assert_in_repo_preflight() {
  local path="$1"
  case "$path" in
    "$REPO_ROOT"|\
    "$REPO_ROOT"/*|\
    "$FILEMAN_WORKSPACE_ROOT"|\
    "$FILEMAN_WORKSPACE_ROOT"/*) ;;
    *)
      if [ "$ALLOW_EXTERNAL" != "1" ]; then
        echo "path must be inside repository: $path" >&2
        exit 1
      fi
      ;;
  esac
}

MANIFEST="$(normalize_host_path "$MANIFEST")"
OUT="$(normalize_host_path "$OUT")"
assert_in_repo_preflight "$MANIFEST"
assert_in_repo_preflight "$OUT"

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  if [ "$ALLOW_EXTERNAL" = "1" ]; then
    echo "==> generate_report external-path mode: forcing host execution"
    exec env FILEMAN_ALLOW_HOST_EXECUTION=1 bash "$ROOT/runtime/generate_report.sh" "${ORIGINAL_ARGS[@]}"
  fi
  exec bash "$ROOT/scripts/container_exec.sh" --label generate-report -- bash tooling/runtime/generate_report.sh "${ORIGINAL_ARGS[@]}"
fi

if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

if [ ! -f "$VENV/bin/activate" ]; then
  echo "venv not found: $VENV" >&2
  exit 1
fi

normalize_path() {
  local target="$1"
  "$VENV/bin/python" - "$target" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(strict=False))
PY
}

assert_in_repo() {
  local path="$1"
  case "$path" in
    "$REPO_ROOT"|\
    "$REPO_ROOT"/*|\
    "$FILEMAN_WORKSPACE_ROOT"|\
    "$FILEMAN_WORKSPACE_ROOT"/*) ;;
    *)
      if [ "$ALLOW_EXTERNAL" != "1" ]; then
        echo "path must be inside repository: $path" >&2
        exit 1
      fi
      ;;
  esac
}

MANIFEST="$(normalize_path "$MANIFEST")"
OUT="$(normalize_path "$OUT")"
assert_in_repo "$MANIFEST"
assert_in_repo "$OUT"

echo "==> generate_report allow-external=${ALLOW_EXTERNAL} source=${ALLOW_EXTERNAL_SOURCE}"

if [ ! -f "$MANIFEST" ]; then
  echo "manifest not found: $MANIFEST" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"

MANIFEST_PATH="$MANIFEST" OUT_PATH="$OUT" ROOT_PATH="$ROOT" "$VENV/bin/python" - <<'PY'
import os
import sys
from pathlib import Path

root = Path(os.environ["ROOT_PATH"]).resolve()
repo_root = root.parent
sys.path.insert(0, str(repo_root / "packages" / "core"))

from packages.infrastructure.manifest_store import read_jsonl
from packages.application.reporting import Summary, write_report

manifest = Path(os.environ["MANIFEST_PATH"])
rows = read_jsonl(manifest, validate=False)
summary = Summary()
for row in rows:
    summary.update(row)

out = Path(os.environ["OUT_PATH"])
write_report(out, summary)
print(f"Wrote report: {out}")
PY
