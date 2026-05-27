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
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label observability-baseline -- bash tooling/gates/check_observability_baseline.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ check_observability_baseline: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

SUMMARY_PATH="$REPO_ROOT/.runtime-cache/logs/observability-baseline.json"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --summary)
      SUMMARY_PATH="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--summary PATH]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$SUMMARY_PATH")"

"$VENV/bin/python" - "$REPO_ROOT" "$SUMMARY_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
summary_path = Path(sys.argv[2]).resolve()

checks = [
    {
        "name": "logging_fields_trace_id",
        "path": root / "packages" / "observability" / "logging_utils.py",
        "patterns": [r'"trace_id"', r'"event"', r'"status"', r'"failure_domain"', r'"workspace_id"', r'"service"'],
    },
    {
        "name": "obs_doc_tracing",
        "path": root / "docs" / "logging_observability.md",
        "patterns": [r"trace_id", r"tracing"],
    },
    {
        "name": "obs_doc_sli_slo",
        "path": root / "docs" / "logging_observability.md",
        "patterns": [r"SLI", r"SLO", r"error budget"],
    },
    {
        "name": "obs_doc_alerting",
        "path": root / "docs" / "logging_observability.md",
        "patterns": [r"告警", r"alert"],
    },
    {
        "name": "ops_playbook_obs_runbook",
        "path": root / "docs" / "ops_playbook.md",
        "patterns": [r"可观测性", r"SLI", r"SLO", r"告警"],
    },
    {
        "name": "event_schema_contract",
        "path": root / "contracts" / "runtime" / "event_schema.yaml",
        "patterns": [r"failure_domains:", r"required_fields:", r"run_id"],
    },
]

results = []
failed = False
for item in checks:
    target = item["path"]
    if not target.exists():
        results.append({"name": item["name"], "status": "fail", "reason": f"missing file: {target}"})
        failed = True
        continue
    text = target.read_text(encoding="utf-8")
    missing = [p for p in item["patterns"] if re.search(p, text, re.IGNORECASE) is None]
    if missing:
        results.append(
            {
                "name": item["name"],
                "status": "fail",
                "reason": f"missing patterns: {', '.join(missing)}",
                "path": str(target),
            }
        )
        failed = True
    else:
        results.append({"name": item["name"], "status": "pass", "path": str(target)})

summary = {
    "metric": "observability.baseline",
    "status": "pass" if not failed else "fail",
    "checks": results,
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))

if failed:
    raise SystemExit(1)
PY

echo "✅ check_observability_baseline: passed"
