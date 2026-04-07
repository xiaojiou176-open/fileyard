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

if [ "${MOVI_IN_CONTAINER:-0}" != "1" ] && [ "${MOVI_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label cli-perf-baseline -- bash tooling/gates/check_cli_perf_baseline.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ check_cli_perf_baseline: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

BUDGET_MS="${MOVI_CLI_REPORT_BUDGET_MS:-1500}"
MANIFEST_PATH="$ROOT/tests/fixtures/golden_expected/manifest.jsonl"
SUMMARY_PATH="$(governance_runtime_logs_path "$REPO_ROOT")/cli-perf-baseline.json"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --budget-ms)
      BUDGET_MS="$2"
      shift 2
      ;;
    --manifest)
      MANIFEST_PATH="$2"
      shift 2
      ;;
    --summary)
      SUMMARY_PATH="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--budget-ms N] [--manifest PATH] [--summary PATH]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$SUMMARY_PATH")"

"$VENV/bin/python" - "$VENV/bin/python" "$ROOT/movi_organizer.py" "$MANIFEST_PATH" "$BUDGET_MS" "$SUMMARY_PATH" <<'PY'
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

py = Path(sys.argv[1]).resolve()
entry = Path(sys.argv[2]).resolve()
manifest = Path(sys.argv[3]).resolve()
budget_ms = int(sys.argv[4])
summary_path = Path(sys.argv[5]).resolve()

if not manifest.exists():
    raise SystemExit(f"❌ check_cli_perf_baseline: manifest not found: {manifest}")

with tempfile.TemporaryDirectory(prefix="cli-perf-", dir=str(Path.cwd() / ".runtime-cache" / "temp")) as tmp_dir:
    out = Path(tmp_dir) / "report.json"
    cmd = [
        str(py),
        str(entry),
        "report",
        "--manifest",
        str(manifest),
        "--out",
        str(out),
        "--validate",
        "--chunk-size",
        "200",
    ]
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True)
    elapsed_ms = int((time.monotonic() - started) * 1000)

summary = {
    "metric": "cli.report.duration_ms",
    "budget_ms": budget_ms,
    "actual_ms": elapsed_ms,
    "status": "pass" if elapsed_ms <= budget_ms and proc.returncode == 0 else "fail",
    "manifest": str(manifest),
    "command": "movi-organizer report --manifest <manifest> --out <tmp> --validate --chunk-size 200",
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))

if proc.returncode != 0:
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    raise SystemExit(proc.returncode)

if elapsed_ms > budget_ms:
    raise SystemExit(1)
PY

echo "✅ check_cli_perf_baseline: passed (budget=${BUDGET_MS}ms)"
